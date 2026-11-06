"""Trasferimento dati tra PC (casa -> lavoro): pacchetto zip con manifesto e impronte sha256.

  python -m dvtool pacchetto crea  --raccolta raccolta.json --out ducati_v4_trasferimento.zip
  python -m dvtool pacchetto crea  --file D:\\a\\x.dbc D:\\b\\*.bin --out pacchetto.zip
  python -m dvtool pacchetto apri  pacchetto.zip --in privato
  python -m dvtool pacchetto verifica pacchetto.zip

raccolta.json:
{"voci": [{"da": "D:/lavori/SFV4_23/can/*.dbc", "in": "can"},
          {"da": "D:/lavori/ducati/noslick_disasm/strutture/*.json", "in": "strutture"}]}
"""
from __future__ import annotations

import datetime as _dt
import glob
import hashlib
import json
import os
import platform
import zipfile


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blocco in iter(lambda: f.read(1 << 20), b""):
            h.update(blocco)
    return h.hexdigest()


def _espandi(modello):
    modello = os.path.expandvars(os.path.expanduser(modello))
    trovati = glob.glob(modello, recursive=True)
    out = []
    for p in trovati:
        if os.path.isdir(p):
            for r, _, fs in os.walk(p):
                for f in fs:
                    out.append((os.path.join(r, f), os.path.relpath(os.path.join(r, f), os.path.dirname(p))))
        else:
            out.append((p, os.path.basename(p)))
    return out


def crea(voci: list, uscita: str, nota: str = "") -> dict:
    manifesto = {"creato": _dt.datetime.now().isoformat(timespec="seconds"), "pc": platform.node(),
                 "nota": nota, "file": [], "non_trovati": []}
    with zipfile.ZipFile(uscita, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for v in voci:
            trovati = _espandi(v["da"])
            if not trovati:
                manifesto["non_trovati"].append(v["da"])
                continue
            for sorgente, rel in trovati:
                dest = "/".join(x for x in (v.get("in", ""), rel.replace(os.sep, "/")) if x)
                z.write(sorgente, dest)
                manifesto["file"].append({"percorso": dest, "origine": sorgente, "byte": os.path.getsize(sorgente),
                                          "sha256": _sha(sorgente)})
        z.writestr("MANIFESTO.json", json.dumps(manifesto, indent=1, ensure_ascii=False))
    return manifesto


def verifica(percorso: str) -> dict:
    with zipfile.ZipFile(percorso) as z:
        man = json.loads(z.read("MANIFESTO.json"))
        errori = []
        for f in man["file"]:
            h = hashlib.sha256(z.read(f["percorso"])).hexdigest()
            if h != f["sha256"]:
                errori.append(f["percorso"])
    return {"file": len(man["file"]), "errori": errori, "creato": man["creato"], "pc": man["pc"],
            "non_trovati": man.get("non_trovati", [])}


def apri(percorso: str, destinazione: str, sovrascrivi: bool = False) -> dict:
    r = verifica(percorso)
    if r["errori"]:
        raise ValueError(f"pacchetto danneggiato: {r['errori']}")
    saltati, scritti = [], []
    with zipfile.ZipFile(percorso) as z:
        man = json.loads(z.read("MANIFESTO.json"))
        for f in man["file"]:
            dest = os.path.join(destinazione, *f["percorso"].split("/"))
            if os.path.exists(dest) and not sovrascrivi:
                if _sha(dest) != f["sha256"]:
                    saltati.append(f["percorso"])
                continue
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            with open(dest, "wb") as out:
                out.write(z.read(f["percorso"]))
            scritti.append(f["percorso"])
    return {"scritti": scritti, "diversi_non_sovrascritti": saltati, **r}
