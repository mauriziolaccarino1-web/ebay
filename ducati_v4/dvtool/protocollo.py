"""Verifica che il log della moto segua il protocollo atteso (es. DBC della Streetfighter V4S).

Controlli:
  * ID presenti/assenti rispetto al DBC, ID sconosciuti
  * DLC e periodo reale contro quelli attesi
  * per ogni segnale: campo di valori, % fuori dal [min|max] del DBC, segnali fermi
  * plausibilità fisica sui canali mappati (ruote ant/post coerenti, giri/velocità a gradini con la marcia,
    piega entro +-70 gradi, gas 0..100)
"""
from __future__ import annotations

import numpy as np

from . import dbc as dbcmod


def crc8_j1850(dati: np.ndarray) -> np.ndarray:
    """CRC-8 SAE J1850 (poli 0x1D, init 0xFF, xorout 0xFF, non riflesso) riga per riga su array (N, k)."""
    tab = np.zeros(256, dtype=np.uint8)
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c << 1) ^ 0x1D) & 0xFF if c & 0x80 else (c << 1) & 0xFF
        tab[i] = c
    crc = np.full(dati.shape[0], 0xFF, dtype=np.uint8)
    for k in range(dati.shape[1]):
        crc = tab[crc ^ dati[:, k]]
    return crc ^ 0xFF


def integrita(log) -> list:
    """Per ogni ID: CRC-8 J1850 in B7 su B0..B6, contatore in B6[3:0], frame persi.
    Sulla Streetfighter V4 2023 (prova del 31/10) tutti i frame della centralina tranne 0x360 avevano
    contatore + CRC corretti: ritrovarli identici su un'altra moto è una prova forte che il protocollo è lo stesso."""
    out = []
    for ident in np.unique(log.id):
        k = log.id == ident
        d = log.data[k]
        dl = log.dlc[k]
        tt = log.t[k]
        r = {"id_hex": f"0x{int(ident):03X}", "frame": int(k.sum())}
        if np.all(dl >= 8) and d.shape[0] > 5:
            ok = crc8_j1850(d[:, :7]) == d[:, 7]
            r["crc_j1850_%"] = round(float(ok.mean() * 100), 2)
            cnt = d[:, 6] & 0x0F
            dc = (np.diff(cnt.astype(int)) % 16)
            r["contatore_ok_%"] = round(float(np.mean(dc == 1) * 100), 2)
            if r["contatore_ok_%"] > 80:
                persi = int(np.sum(np.where(dc == 0, 0, dc - 1)))
                r["frame_persi_stimati"] = persi
        if tt.size > 3:
            dt = np.diff(tt)
            med = np.median(dt)
            r["buchi"] = int(np.sum(dt > 2.5 * med)) if med > 0 else 0
        r["protetto"] = bool(r.get("crc_j1850_%", 0) > 95)
        out.append(r)
    return out


def verifica(log, db, canali_mappati: dict | None = None) -> dict:
    inv = {x["id"]: x for x in log.inventario()}
    messaggi = []
    for ident, m in sorted(db.messaggi.items()):
        x = inv.get(ident)
        r = {"id_hex": f"0x{ident:03X}", "nome": m.nome, "dlc_atteso": m.dlc, "periodo_atteso_ms": m.periodo_ms,
             "presente": x is not None}
        if x:
            r.update({"frame": x["frame"], "hz": round(x["hz"], 2), "periodo_ms": x["periodo_ms_mediano"],
                      "dlc_visti": x["dlc"], "dlc_ok": m.dlc in x["dlc"]})
            if m.periodo_ms and x["periodo_ms_mediano"]:
                r["periodo_ok"] = abs(x["periodo_ms_mediano"] - m.periodo_ms) <= max(2.0, 0.25 * m.periodo_ms)
        messaggi.append(r)
    sconosciuti = [v for k, v in sorted(inv.items()) if k not in db.messaggi]
    dec = dbcmod.decodifica(db, log.t, log.id, log.data)
    segnali = []
    for chiave, (tt, vv) in sorted(dec.items()):
        msg, sg = db.segnale(chiave)
        if vv.size == 0:
            continue
        fuori = 0.0
        if sg.massimo > sg.minimo:
            fuori = float(np.mean((vv < sg.minimo) | (vv > sg.massimo)) * 100)
        segnali.append({"segnale": chiave, "unita": sg.unita, "min": float(np.min(vv)), "max": float(np.max(vv)),
                        "media": float(np.mean(vv)), "valori_distinti": int(min(np.unique(vv).size, 9999)),
                        "fermo": bool(np.all(vv == vv[0])), "fuori_campo_%": round(fuori, 2)})
    plaus = plausibilita(dec, canali_mappati or {})
    integ = integrita(log)
    n_pres = sum(1 for m in messaggi if m["presente"])
    n_crc = sum(1 for x in integ if x["protetto"])
    persi = sum(x.get("frame_persi_stimati", 0) for x in integ)
    giudizio = (f"{n_pres}/{len(messaggi)} messaggi del DBC presenti, {len(sconosciuti)} ID non descritti; "
                f"{n_crc}/{len(integ)} ID con contatore+CRC-8 J1850 come la V4S; "
                f"{sum(1 for p in plaus if p['esito'] == 'ok')}/{len(plaus)} controlli fisici ok"
                + (f"; ~{persi} frame persi dal registratore" if persi else ""))
    return {"giudizio": giudizio, "messaggi": messaggi, "id_sconosciuti": sconosciuti, "segnali": segnali,
            "plausibilita": plaus, "integrita": integ}


def _serie(dec, nome):
    if not nome:
        return None
    for k, v in dec.items():
        if k == nome or k.split(".", 1)[1] == nome:
            return v
    return None


def plausibilita(dec: dict, canali: dict) -> list:
    out = []

    def seg(log_id):
        c = canali.get(log_id)
        return _serie(dec, c["segnale"] if isinstance(c, dict) else c) if c else None

    va, vp = seg("v_ant"), seg("v_post")
    if va is not None and vp is not None:
        tg = va[0]
        vpi = np.interp(tg, vp[0], vp[1])
        k = (va[1] > 40) & (vpi > 40)
        if k.sum() > 50:
            rap = np.median(vpi[k] / va[1][k])
            out.append({"controllo": "ruota posteriore / anteriore a velocità > 40 km/h",
                        "valore": round(float(rap), 4),
                        "esito": "ok" if 0.95 < rap < 1.10 else "da verificare",
                        "nota": "atteso 1.00-1.05 (slittamento + raggio di rotolamento)"})
    rpm, marcia = seg("giri"), seg("marcia")
    if rpm is not None and va is not None and marcia is not None:
        tg = rpm[0]
        v = np.interp(tg, va[0], va[1])
        g = np.round(np.interp(tg, marcia[0], marcia[1]))
        k = (v > 30) & (rpm[1] > 2500)
        rapporti = {}
        for m in range(1, 7):
            kk = k & (g == m)
            if kk.sum() > 30:
                r = rpm[1][kk] / v[kk]
                rapporti[m] = (float(np.median(r)), float(np.std(r) / np.median(r)))
        ordinati = [rapporti[m][0] for m in sorted(rapporti)]
        crescente = all(a > b for a, b in zip(ordinati, ordinati[1:]))
        out.append({"controllo": "giri/velocità per marcia (deve calare marcia dopo marcia)",
                    "valore": {m: round(r[0], 1) for m, r in rapporti.items()},
                    "esito": "ok" if crescente and len(rapporti) >= 2 else "da verificare",
                    "nota": "dispersione per marcia: " + ", ".join(f"{m}a {r[1]*100:.1f}%" for m, r in rapporti.items())})
    piega = seg("piega")
    if piega is not None:
        mx = float(np.max(np.abs(piega[1])))
        segno = bool(np.min(piega[1]) < -5 and np.max(piega[1]) > 5)
        out.append({"controllo": "angolo di piega", "valore": round(mx, 1),
                    "esito": "ok" if 20 < mx < 70 else "da verificare",
                    "nota": ("con segno (destra/sinistra)" if segno else "solo valore assoluto o un lato")})
    gas = seg("gas")
    if gas is not None:
        out.append({"controllo": "comando gas (min..max)", "valore": [round(float(np.min(gas[1])), 1), round(float(np.max(gas[1])), 1)],
                    "esito": "ok" if np.min(gas[1]) >= -1 and np.max(gas[1]) <= 101 else "da verificare", "nota": "atteso 0..100 %"})
    return out


def in_markdown(r: dict) -> str:
    righe = ["# Verifica protocollo CAN", "", f"**Esito:** {r['giudizio']}", "", "## Messaggi del DBC", "",
             "| ID | nome | presente | Hz | periodo ms (atteso) | DLC visti (atteso) |", "|---|---|---|---|---|---|"]
    for m in r["messaggi"]:
        righe.append(f"| {m['id_hex']} | {m['nome']} | {'sì' if m['presente'] else '**no**'} | {m.get('hz','')} | "
                     f"{m.get('periodo_ms') and round(m['periodo_ms'],1)} ({m['periodo_atteso_ms'] or '-'}) | "
                     f"{m.get('dlc_visti','')} ({m['dlc_atteso']}) |")
    righe += ["", "## ID presenti nel log ma non nel DBC", "", "| ID | Hz | DLC | byte che cambiano | esempio |", "|---|---|---|---|---|"]
    for x in r["id_sconosciuti"]:
        righe.append(f"| {x['id_hex']} | {x['hz']:.1f} | {x['dlc']} | {x['byte_variabili']} | `{x['esempio']}` |")
    righe += ["", "## Integrità (contatore B6[3:0] + CRC-8 J1850 in B7, come sulla V4S)", "",
              "| ID | frame | CRC ok % | contatore ok % | frame persi | buchi |", "|---|---|---|---|---|---|"]
    for x in r.get("integrita", []):
        righe.append(f"| {x['id_hex']} | {x['frame']} | {x.get('crc_j1850_%', '')} | {x.get('contatore_ok_%', '')} | "
                     f"{x.get('frame_persi_stimati', '')} | {x.get('buchi', '')} |")
    righe += ["", "## Controlli fisici", ""]
    for p in r["plausibilita"]:
        righe.append(f"- **{p['esito']}** — {p['controllo']}: {p['valore']} ({p['nota']})")
    righe += ["", "## Segnali", "", "| segnale | unità | min | max | fermo | fuori campo % |", "|---|---|---|---|---|---|"]
    for s in r["segnali"]:
        righe.append(f"| {s['segnale']} | {s['unita']} | {s['min']:.3g} | {s['max']:.3g} | {'sì' if s['fermo'] else ''} | {s['fuori_campo_%']} |")
    return "\n".join(righe) + "\n"
