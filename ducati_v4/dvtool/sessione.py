"""Dal log grezzo al file di sessione per il visualizzatore.

profilo moto (JSON):
{
  "moto": "Ducati Panigale V4 2025",
  "dbc": "percorso/al/file.dbc",            # relativo al profilo
  "canali": {                                 # nomi logici usati da giri e modello -> segnale del DBC
     "v_ant":  {"segnale": "Msg.Segnale", "unita": "km/h"},
     "v_post": "Msg.Segnale",
     "piega":  {"segnale": "...", "scala": 1.0, "offset": 0.0},
     "giri": "...", "gas": "...", "farfalla": "...", "marcia": "...",
     "dtc_livello": "...", "dtc_attivo": "..."
  },
  "pista": "vallelunga" | 4085,
  "linea": "vmax", "linea_offset_m": 0
}
"""
from __future__ import annotations

import base64
import datetime as _dt
import json
import os

import numpy as np

from . import calib, canlog, laps, model, protocollo
from . import dbc as dbcmod


def b64(x) -> str:
    return base64.b64encode(np.asarray(x, dtype="<f4").tobytes()).decode("ascii")


def _discreto(sg) -> bool:
    return sg.lunghezza <= 4 or bool(sg.valori)


def ricampiona(dec: dict, db, t_griglia, nomi=None) -> dict:
    out = {}
    for chiave, (tt, vv) in dec.items():
        if nomi is not None and chiave not in nomi:
            continue
        if tt.size < 2:
            continue
        _, sg = db.segnale(chiave)
        if _discreto(sg):
            idx = np.clip(np.searchsorted(tt, t_griglia, side="right") - 1, 0, len(tt) - 1)
            v = vv[idx]
        else:
            v = np.interp(t_griglia, tt, vv)
        # fuori dal tratto registrato: NaN
        v = np.where((t_griglia < tt[0] - 0.5) | (t_griglia > tt[-1] + 0.5), np.nan, v)
        out[chiave] = v
    return out


def _spec(c):
    return {"segnale": c} if isinstance(c, str) else dict(c)


def canali_logici(profilo: dict, ricamp: dict) -> dict:
    out = {}
    for nome, c in profilo.get("canali", {}).items():
        c = _spec(c)
        sig = c["segnale"]
        trovato = ricamp.get(sig)
        if trovato is None:
            for k, v in ricamp.items():
                if k.split(".", 1)[1] == sig:
                    trovato = v
                    break
        if trovato is None and c.get("espressione"):
            continue
        if trovato is None:
            continue
        v = trovato * c.get("scala", 1.0) + c.get("offset", 0.0)
        if "min" in c or "max" in c:  # valori di avvio/errore (es. 0xFFF) -> NaN
            v = np.where((v < c.get("min", -np.inf)) | (v > c.get("max", np.inf)), np.nan, v)
        out[nome] = v
    # canali calcolati da espressione sugli altri canali logici
    for nome, c in profilo.get("canali", {}).items():
        c = _spec(c)
        if c.get("espressione") and nome not in out:
            try:
                out[nome] = model.valuta(c["espressione"], out)
            except model.ErroreModello:
                pass
    return out


def crea(percorso_log: str, profilo: dict, cartella_profilo: str = ".", modello_def=None, struttura=None,
         buf=None, frequenza=None, tabella_sqlite=None, parametri=None, pista=None) -> dict:
    note = []
    log = canlog.leggi(percorso_log, tabella_sqlite)
    if len(log) == 0:
        raise ValueError("log vuoto")
    note.append(f"{len(log)} frame CAN da {os.path.basename(percorso_log)} ({log.note})")
    dbc_path = profilo.get("dbc")
    if dbc_path and not os.path.isabs(dbc_path):
        dbc_path = os.path.join(cartella_profilo, dbc_path)
    db = dbcmod.carica_dbc(dbc_path) if dbc_path else dbcmod.Database()
    dec = dbcmod.decodifica(db, log.t, log.id, log.data)
    f = frequenza or (modello_def or {}).get("frequenza_hz") or 100
    t0, t1 = float(log.t[0]), float(log.t[-1])
    tg = np.arange(t0, t1, 1.0 / f)
    ric = ricampiona(dec, db, tg)
    logici = canali_logici(profilo, ric)
    mancanti = [k for k in profilo.get("canali", {}) if k not in logici]
    if mancanti:
        note.append("canali logici non trovati nel log: " + ", ".join(mancanti))

    # --- giri senza GPS
    giri_out = None
    s = s_giro = n_giro = None
    if "v_ant" in logici or "v_post" in logici:
        v = laps.velocita_riferimento(logici.get("v_ant", logici.get("v_post")), logici.get("v_post"))
        if "piega" in logici and profilo.get("correzione_piega", True):
            pa = profilo.get("pneumatico_ant", {})
            v = laps.correggi_piega(v, logici["piega"], pa.get("R0_mm", 300.0), pa.get("r_corona_mm", 60.0))
            note.append(f"distanza corretta per il raggio in piega (R0 {pa.get('R0_mm', 300.0)} mm, "
                        f"raggio corona {pa.get('r_corona_mm', 60.0)} mm)")
        r = laps.stima_giri(tg, v, piega=logici.get("piega"), imbardata=logici.get("imbardata"),
                            lunghezza_nominale=pista if pista is not None else profilo.get("pista"),
                            linea=profilo.get("linea", "vmax"), linea_offset_m=profilo.get("linea_offset_m", 0.0),
                            t_traguardo=profilo.get("t_traguardo"))
        giri_out = r.dict()
        s, s_giro, n_giro = r.s, r.s_giro, r.n_giro
        note += r.note
    else:
        note.append("senza velocità ruota non posso stimare i giri")

    # --- modello della catena di controllo
    mod_out = None
    if modello_def:
        try:
            ris = model.esegui(modello_def, logici, tg - t0, struttura, buf, parametri)
            crit = []
            for c in modello_def.get("criteri", []):
                rc = ris["criteri"][c["id"]]
                noti = set(ris["ordine"]) | set(logici)
                voce = {"id": c["id"], "nome": c.get("nome", c["id"]), "unita": c.get("unita", ""),
                        "confronto": c.get("confronto", ">"), "isteresi": c.get("isteresi", 0.0),
                        "valore_id": c["valore"] if c["valore"] in noti else None,
                        "soglia_id": c["soglia"] if isinstance(c["soglia"], str) and c["soglia"] in noti else None,
                        "attivo": b64(rc["attivo"]), "percentuale_attivo": float(np.mean(rc["attivo"]) * 100),
                        "scala": float(np.nanpercentile(np.abs(rc["soglia"]), 90) or 1.0)}
                if voce["valore_id"] is None:
                    voce["valore"] = b64(rc["valore"])
                if voce["soglia_id"] is None:
                    voce["soglia"] = b64(rc["soglia"])
                crit.append(voce)
            blocchi = [{"id": bid, "b64": b64(ris["valori"][bid])} for bid in ris["ordine"]]
            ingressi = [{"id": i["id"]} for i in modello_def.get("ingressi", [])]  # sono già tra i canali
            usate = []
            for bid, u in ris["tabelle_usate"].items():
                usate.append({"blocco": bid, "tabella": u["tabella"],
                              "x": b64(u["x"]) if "x" in u else None, "y": b64(u["y"]) if "y" in u else None})
            oss = model.confronto_osservati(modello_def, ris, logici, tg)
            mod_out = {"def": modello_def, "criteri": crit, "blocchi": blocchi, "ingressi": ingressi,
                       "rami": [{"id": k, "b64": b64(v)} for k, v in ris["rami"].items()],
                       "logica": b64(ris["logica"]), "uscite": [{"id": k, "b64": b64(v)} for k, v in ris["uscite"].items()],
                       "tabelle_usate": usate, "osservati": oss, "parametri": parametri or modello_def.get("parametri", {})}
        except model.ErroreModello as e:
            note.append(f"modello non eseguito: {e}")

    # --- canali per il visualizzatore
    canali = []
    for nome, v in logici.items():
        c = _spec(profilo["canali"][nome])
        canali.append({"id": nome, "nome": c.get("nome", nome), "unita": c.get("unita", ""), "gruppo": "principali",
                       "b64": b64(v)})
    mappati = {_spec(c)["segnale"] for c in profilo.get("canali", {}).values()}
    extra = profilo.get("extra", "*" if len(ric) <= 60 else [])
    for chiave, v in ric.items():
        if chiave in mappati or chiave.split(".", 1)[1] in mappati:
            continue  # già presente col nome logico
        if extra != "*" and chiave not in extra:
            continue
        _, sg = db.segnale(chiave)
        canali.append({"id": chiave, "nome": chiave, "unita": sg.unita, "gruppo": chiave.split(".")[0], "b64": b64(v)})
    if extra != "*" and len(ric) > 60:
        note.append(f"{len(ric)} segnali nel DBC: nel file solo quelli mappati e quelli in 'extra' del profilo")
    if s is not None:
        canali.append({"id": "distanza", "nome": "distanza percorsa", "unita": "m", "gruppo": "giri", "b64": b64(s)})
        canali.append({"id": "s_giro", "nome": "distanza nel giro", "unita": "m", "gruppo": "giri", "b64": b64(s_giro)})
        canali.append({"id": "n_giro", "nome": "numero giro", "unita": "", "gruppo": "giri", "b64": b64(n_giro)})

    sorgenti = {}
    for nome, c in profilo.get("canali", {}).items():
        c = _spec(c)
        trovato = db.segnale(c["segnale"]) if c.get("segnale") else None
        if trovato:
            m, _ = trovato
            sorgenti[nome] = {"segnale": f"{m.nome}.{trovato[1].nome}", "id_hex": f"0x{m.id:03X}",
                              "stato": c.get("verificato", "")}
    prot = protocollo.verifica(log, db, profilo.get("canali", {})) if db.messaggi else {
        "giudizio": "nessun DBC", "messaggi": [], "id_sconosciuti": log.inventario(), "segnali": [], "plausibilita": []}
    return {
        "tipo": "sessione_dvtool", "versione": 1,
        "meta": {"origine": os.path.basename(percorso_log), "creato": _dt.datetime.now().isoformat(timespec="seconds"),
                 "moto": profilo.get("moto", ""), "dbc": os.path.basename(dbc_path) if dbc_path else None,
                 "t0_assoluto": t0, "note": note, "sorgenti": sorgenti,
                 "file_calibrazione_sha256": calib.sha256(bytes(buf)) if buf is not None else None},
        "tempo": {"dt": 1.0 / f, "n": int(len(tg))},
        "canali": canali, "giri": giri_out, "modello": mod_out, "protocollo": prot,
    }


def salva(sess: dict, percorso: str):
    """Salva il JSON; se il nome finisce in .gz lo comprime (il visualizzatore lo apre lo stesso)."""
    testo = json.dumps(sess, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    if percorso.endswith(".gz"):
        import gzip
        with gzip.open(percorso, "wt", encoding="utf-8", compresslevel=6) as fh:
            fh.write(testo)
    else:
        with open(percorso, "w", encoding="utf-8") as fh:
            fh.write(testo)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError(type(o))
