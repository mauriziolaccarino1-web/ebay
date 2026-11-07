"""Backend della Guida (pagina viewer/guida.html): impostazioni, controlli, cronometro, analisi, file per la centralina.

Tutto gira sul PC, servito solo su 127.0.0.1 da server.py. Le password di sudo arrivano dalla pagina e vanno
direttamente nello stdin di ssh: non vengono mai salvate né scritte nei registri.
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import shutil

from . import calib, cronometro, sessione

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE_IMP = os.path.join(RADICE, "privato", "guida.json")

PREDEFINITE = {
    "scatola": "r9", "host": "169.254.55.1", "pista": "vallelunga",
    "profilo": "esempi/profilo_ducati_v4.json",
    "struttura": "privato/struttura.json", "modello": "privato/modello.json",
    "acquisizioni": "privato/acquisizioni", "calibrazioni": "privato/calibrazioni", "progetto": "privato/progetto",
    "rif": "", "cfr": "",
}


def _p(rel):
    return rel if os.path.isabs(rel) else os.path.join(RADICE, rel)


def impostazioni() -> dict:
    d = dict(PREDEFINITE)
    if os.path.exists(FILE_IMP):
        with open(FILE_IMP, "r", encoding="utf-8") as f:
            d.update(json.load(f))
    return d


def salva_impostazioni(nuove: dict) -> dict:
    d = impostazioni()
    d.update({k: v for k, v in nuove.items() if k in PREDEFINITE})
    os.makedirs(os.path.dirname(FILE_IMP), exist_ok=True)
    with open(FILE_IMP, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return d


def _struttura_compilata(p):
    if not os.path.exists(p):
        return False, "manca: va compilata sul PC di casa (esempi/struttura_da_compilare.json)"
    with open(p, "r", encoding="utf-8") as f:
        S = json.load(f)
    testo = json.dumps(S.get("tabelle", []))
    if not S.get("tabelle") or testo.count("0x00000000") >= len(S["tabelle"]):
        return False, "presente ma con gli indirizzi segnaposto (0x00000000): va completata"
    if not S.get("checksum") or "0x00000000" in json.dumps(S["checksum"]):
        return False, f"{len(S['tabelle'])} tabelle, ma senza regola di checksum: si può analizzare, non preparare il file per la centralina"
    return True, f"{len(S['tabelle'])} tabelle, {len(S['checksum'])} checksum"


def elenchi(imp=None) -> dict:
    imp = imp or impostazioni()
    acq = []
    for f in sorted(glob.glob(os.path.join(_p(imp["acquisizioni"]), "**", "*"), recursive=True), key=os.path.getmtime, reverse=True):
        if os.path.isfile(f) and f.lower().endswith((".log", ".candump", ".jsonl", ".gz", ".csv", ".r9session", ".db", ".sqlite")) \
                and not f.endswith("marcatori.txt"):
            acq.append({"file": os.path.relpath(f, _p(imp["acquisizioni"])), "byte": os.path.getsize(f),
                        "data": _dt.datetime.fromtimestamp(os.path.getmtime(f)).strftime("%d/%m/%Y %H:%M")})
    cal = []
    for f in sorted(glob.glob(os.path.join(_p(imp["calibrazioni"]), "*"))):
        if os.path.isfile(f) and f.lower().endswith((".bin", ".ori", ".hex", ".mod", ".cal")):
            cal.append({"nome": os.path.splitext(os.path.basename(f))[0], "file": os.path.basename(f), "byte": os.path.getsize(f)})
    return {"acquisizioni": acq, "calibrazioni": cal}


def controlli(imp=None) -> list:
    imp = imp or impostazioni()
    out = []

    def voce(nome, ok, dettaglio, aiuto=""):
        out.append({"voce": nome, "ok": bool(ok), "dettaglio": dettaglio, "aiuto": aiuto})
    ssh = shutil.which("ssh")
    voce("Client SSH sul PC", ssh, ssh or "non trovato",
         "Windows: Impostazioni → App → Funzionalità facoltative → aggiungi «Client OpenSSH».")
    chiavi = [os.path.expanduser(f"~/.ssh/{n}.pub") for n in ("id_ed25519", "id_rsa", "id_ecdsa")]
    k = next((c for c in chiavi if os.path.exists(c)), None)
    voce("Chiave SSH di questo PC", k, k or "nessuna chiave",
         "Crea la chiave: «ssh-keygen -t ed25519» (invio a tutte le domande, passphrase vuota). Per autorizzarla serve per qualche "
         "minuto una copia della chiave di casa (con AnyDesk), con la scatola collegata via USB: «dvtool.bat cronometro autorizza "
         "--file %USERPROFILE%\\.ssh\\id_ed25519.pub --chiave %USERPROFILE%\\.ssh\\chiave_casa», poi cancella la copia. "
         "Sulla scatola si aggiunge solo una riga alle chiavi autorizzate (README, «Chiave SSH»).")
    prof = _p(imp["profilo"])
    voce("Profilo della moto", os.path.exists(prof), os.path.relpath(prof, RADICE))
    if os.path.exists(prof):
        with open(prof, "r", encoding="utf-8") as f:
            P = json.load(f)
        dbc = os.path.normpath(os.path.join(os.path.dirname(prof), P.get("dbc", "")))
        voce("DBC del protocollo (V4S)", os.path.exists(dbc), os.path.relpath(dbc, RADICE),
             "Estrai ducati_v4_privato_dal_cloud.zip dentro la cartella privato.")
    ok, det = _struttura_compilata(_p(imp["struttura"]))
    voce("Struttura delle tabelle della centralina", ok, det, "Senza struttura vedi canali, giri, curve e protocollo, ma non criteri, schema e mappe.")
    m = _p(imp["modello"])
    voce("Modello della catena di controllo", os.path.exists(m), os.path.relpath(m, RADICE) if os.path.exists(m) else "manca: va compilato (esempi/modello_da_compilare.json)")
    E = elenchi(imp)
    voce("File della centralina", E["calibrazioni"], ", ".join(c["nome"] for c in E["calibrazioni"]) or f"nessuno in {imp['calibrazioni']}",
         "Metti qui gli originali (NOSLICK, Divac Pro…): la Guida non li modifica mai, i file nuovi hanno un nome diverso.")
    voce("Acquisizioni scaricate", E["acquisizioni"], f"{len(E['acquisizioni'])} in {imp['acquisizioni']}")
    return out


def _scatola(imp):
    cfg = cronometro.configurazione()
    return cronometro.Scatola(cfg, imp.get("scatola") or None, imp.get("host") or None)


def op_cronometro(azione: str, dati: dict) -> dict:
    imp = impostazioni()
    sc = _scatola(imp)
    pw = dati.get("password", "")
    if azione == "stato":
        return cronometro.op_stato(sc)
    if azione == "prepara_registra":
        r1 = cronometro.op_prepara(sc, pw)
        if not r1["ok"]:
            return {"ok": False, "errore": r1["errore"], "passo": "prepara", "testo": r1.get("testo", "")}
        r2 = cronometro.op_registra(sc)
        return {"ok": r2["ok"], "errore": r2.get("errore"), "testo": r1["testo"] + "\n" + r2["testo"], "passo": "registra"}
    if azione == "registra":
        return cronometro.op_registra(sc)
    if azione == "prova_registratore":
        return cronometro.op_prova_registratore(sc, int(dati.get("secondi") or 20))
    if azione == "ferma":
        return cronometro.op_ferma(sc)
    if azione == "marca":
        return cronometro.op_marca(sc, dati.get("testo", ""))
    if azione == "scarica":
        return cronometro.op_scarica(sc, _p(imp["acquisizioni"]))
    if azione == "ripristina":
        return cronometro.op_ripristina(sc, pw)
    return {"ok": False, "errore": f"azione sconosciuta: {azione}"}


def analizza(dati: dict) -> dict:
    """Acquisizione -> sessione (giri, curve, protocollo, catena se c'è) -> cartella progetto per il visualizzatore."""
    imp = impostazioni()
    log = os.path.join(_p(imp["acquisizioni"]), dati["acquisizione"])
    if not os.path.exists(log):
        return {"ok": False, "errore": f"acquisizione non trovata: {dati['acquisizione']}"}
    prof_p = _p(imp["profilo"])
    with open(prof_p, "r", encoding="utf-8") as f:
        prof = json.load(f)
    if dati.get("pista"):
        prof["pista"] = dati["pista"]
    E = elenchi(imp)
    cal = {c["nome"]: os.path.join(_p(imp["calibrazioni"]), c["file"]) for c in E["calibrazioni"]}
    rif = dati.get("rif") or (E["calibrazioni"][0]["nome"] if E["calibrazioni"] else "")
    cfr = dati.get("cfr") or rif
    note = []
    mod = S = buf = None
    sp, mp = _p(imp["struttura"]), _p(imp["modello"])
    compilata, perche = _struttura_compilata(sp)
    if os.path.exists(mp) and os.path.exists(sp) and rif in cal and "segnaposto" not in perche and "manca" not in perche:
        with open(mp, "r", encoding="utf-8") as f:
            mod = json.load(f)
        with open(cal[rif], "rb") as f:
            buf = f.read()
        with open(sp, "r", encoding="utf-8") as f:
            S0 = json.load(f)
        try:
            S = calib.risolvi(S0, calib.trova_variante(S0, buf) or (rif if rif in [v["nome"] for v in S0.get("varianti", [])] else None))
        except KeyError as e:
            note.append(f"struttura: {e}; analisi senza catena di controllo")
            mod = S = buf = None
    else:
        note.append("senza struttura/modello compilati (o senza file della centralina): analisi di canali, giri, curve e protocollo")
    s = sessione.crea(log, prof, os.path.dirname(prof_p), mod, S, buf)
    s["meta"]["calibrazione"] = rif if mod else None
    progetto = _p(imp["progetto"])
    os.makedirs(progetto, exist_ok=True)
    nome_s = "sessione_" + os.path.splitext(os.path.basename(dati["acquisizione"]))[0] + ".json.gz"
    sessione.salva(s, os.path.join(progetto, nome_s))
    P_p = os.path.join(progetto, "progetto.json")
    P = {}
    if os.path.exists(P_p):
        with open(P_p, "r", encoding="utf-8") as f:
            P = json.load(f)
    P["nome"] = prof.get("moto", "")
    if os.path.exists(sp):
        shutil.copy2(sp, os.path.join(progetto, "struttura.json"))
        P["struttura"] = "struttura.json"
    if os.path.exists(mp):
        shutil.copy2(mp, os.path.join(progetto, "modello.json"))
        P["modello"] = "modello.json"
    P["calibrazioni"] = []
    for c in E["calibrazioni"]:
        shutil.copy2(cal[c["nome"]], os.path.join(progetto, c["file"]))
        P["calibrazioni"].append({"nome": c["nome"], "file": c["file"]})
    P["riferimento"], P["confronto"] = rif, cfr
    P["sessioni"] = [nome_s] + [x for x in P.get("sessioni", []) if x != nome_s]
    with open(P_p, "w", encoding="utf-8") as f:
        json.dump(P, f, ensure_ascii=False, indent=1)
    salva_impostazioni({"rif": rif, "cfr": cfr})
    G = s.get("giri") or {}
    lanc = [g for g in G.get("giri", []) if g["tipo"] == "lanciato"]
    prot = s.get("protocollo", {})
    return {"ok": True, "sessione": nome_s, "note": note + s["meta"]["note"], "protocollo": prot.get("giudizio", ""),
            "plausibilita": prot.get("plausibilita", []), "giri": len(lanc),
            "migliore": min((g["tempo"] for g in lanc), default=None), "curve": len(G.get("curve", [])),
            "catena": bool(s.get("modello"))}


def applica(dati: dict) -> dict:
    """Patch dal visualizzatore -> nuovo file per la centralina (l'originale non si tocca), con checksum e confronto."""
    imp = impostazioni()
    base_file = os.path.basename(dati["file"])
    base_p = os.path.join(_p(imp["calibrazioni"]), base_file)
    if not os.path.exists(base_p):
        return {"ok": False, "errore": f"file di partenza non trovato in {imp['calibrazioni']}: {base_file}"}
    sp = _p(imp["struttura"])
    compilata, perche = _struttura_compilata(sp)
    if not compilata:
        return {"ok": False, "errore": f"struttura non pronta per preparare un file: {perche}"}
    with open(base_p, "rb") as f:
        base = f.read()
    with open(sp, "r", encoding="utf-8") as f:
        S0 = json.load(f)
    patch = dati["patch"]
    var = calib.trova_variante(S0, base) or patch.get("variante")
    S = calib.risolvi(S0, var)
    verifica_orig = calib.verifica_checksum(S, base)
    if not all(r["ok"] for r in verifica_orig):
        return {"ok": False, "errore": "il checksum del file ORIGINALE non torna con la regola della struttura: la regola è sbagliata, "
                                       "il file preparato non sarebbe affidabile", "checksum_originale": verifica_orig}
    out, avvisi = calib.applica_patch(S, base, patch)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    nome = f"{os.path.splitext(base_file)[0]}_mod_{stamp}{os.path.splitext(base_file)[1]}"
    dest_dir = os.path.join(_p(imp["calibrazioni"]), "modificati")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, nome)
    with open(dest, "wb") as f:
        f.write(out)
    with open(dest + ".patch.json", "w", encoding="utf-8") as f:
        json.dump(patch, f, ensure_ascii=False, indent=1)
    cs = calib.verifica_checksum(S, bytes(out))
    conf = calib.confronta(S, base, bytes(out))
    ok = all(r["ok"] for r in cs) and not conf["regioni_fuori_struttura"]
    return {"ok": ok, "file": os.path.relpath(dest, RADICE), "percorso": dest, "sha256": calib.sha256(bytes(out)),
            "variante": var, "checksum": cs, "tabelle_cambiate": conf["tabelle"], "fuori_struttura": conf["regioni_fuori_struttura"],
            "avvisi": avvisi, "base": base_file}


def gestisci(metodo: str, percorso: str, corpo: dict) -> tuple[int, dict]:
    try:
        if metodo == "GET" and percorso == "/api/guida/stato":
            imp = impostazioni()
            return 200, {"impostazioni": imp, "controlli": controlli(imp), **elenchi(imp)}
        if metodo == "POST" and percorso == "/api/guida/impostazioni":
            return 200, {"impostazioni": salva_impostazioni(corpo)}
        if metodo == "POST" and percorso.startswith("/api/cronometro/"):
            return 200, op_cronometro(percorso.rsplit("/", 1)[1], corpo)
        if metodo == "POST" and percorso == "/api/guida/analizza":
            return 200, analizza(corpo)
        if metodo == "POST" and percorso == "/api/guida/applica":
            return 200, applica(corpo)
        return 404, {"ok": False, "errore": "percorso sconosciuto"}
    except Exception as e:  # noqa: BLE001  l'errore va mostrato nella pagina
        return 200, {"ok": False, "errore": f"{type(e).__name__}: {e}"}
