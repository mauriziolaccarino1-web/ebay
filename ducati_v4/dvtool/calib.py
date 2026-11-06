"""Tabelle di calibrazione nel file della centralina: lettura, scrittura, confronto, patch.

Formato della struttura (JSON), campi principali:
{
  "nome": "...",
  "file": {"base": "0x0", "dimensione": 1048576, "sha256_originale": "..."},
  "checksum": [ ... vedi checksum.py ... ],
  "assi": { "ASSE_GIRI": {"indirizzo": "0xE0300", "n": 14, "dtype": "u16", "endian": "le", "scala": 1, "unita": "rpm"} },
  "tabelle": [
    {"id": "DVO_SOGLIA_L2", "nome": "...", "gruppo": "DVO", "tipo": "mappa",
     "indirizzo": "0x70F48", "dtype": "u16", "endian": "le", "scala": 0.01, "offset": 0, "unita": "%",
     "righe": 11, "colonne": 14, "ordine": "righe",
     "asse_x": "ASSE_GIRI" | {...inline...} | {"valori": [..]},
     "asse_y": ...,
     "descrizione": "...", "verificato": false, "fonte": "sessione ..."}
  ],
  "profili_pneumatico": [ {"id": "PROF_POST", "tabella": "...", "ruota": "posteriore",
                           "grandezza": "raggio_mm" | "fattore" | "delta_mm", "R0_mm": 325.9,
                           "misura": "200/55 ZR17"} ]
}
tipo: valore | curva (1D, asse_x) | mappa (2D, asse_x colonne, asse_y righe)
ordine: "righe" = memorizzata riga per riga (y esterno, x interno), "colonne" = il contrario

Più file della centralina (es. NOSLICK e SLICK):
  "varianti": [{"nome": "NOSLICK", "sha256": "...", "file": "..."}, {"nome": "SLICK", "sha256": "..."}]
Se due file hanno le stesse tabelle in posti diversi, "indirizzo" (e "base", "posizione", le regioni del
checksum) può essere un oggetto per variante: "indirizzo": {"NOSLICK": "0x70F48", "SLICK": "0x71F48"}.
risolvi(struttura, variante) restituisce la struttura con gli indirizzi della variante scelta.
"""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass

import numpy as np

from . import checksum as cks

DTYPE = {
    "u8": ("B", 1, 0, 255), "s8": ("b", 1, -128, 127),
    "u16": ("H", 2, 0, 65535), "s16": ("h", 2, -32768, 32767),
    "u32": ("I", 4, 0, 2**32 - 1), "s32": ("i", 4, -2**31, 2**31 - 1),
    "f32": ("f", 4, None, None),
}


def _int(x):
    return int(x, 0) if isinstance(x, str) else int(x)


def carica_struttura(percorso: str) -> dict:
    with open(percorso, "r", encoding="utf-8") as f:
        return json.load(f)


def _per_variante(x):
    return isinstance(x, dict) and x and all(isinstance(v, (str, int)) for v in x.values()) and \
        not any(k in x for k in ("indirizzo", "valori", "n"))


def trova_variante(struttura, buf: bytes):
    """Nome della variante del file, riconosciuta dall'impronta sha256 (None se non riconosciuta)."""
    h = sha256(bytes(buf))
    for v in struttura.get("varianti", []):
        if v.get("sha256") and v["sha256"].lower() == h:
            return v["nome"]
    return None


def risolvi(struttura, variante=None):
    """Copia della struttura con gli indirizzi della variante; senza indirizzi per variante la ritorna uguale."""
    nomi = [v["nome"] for v in struttura.get("varianti", [])]
    trovati = set()

    def giu(o):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k in ("indirizzo", "base", "posizione") and _per_variante(v):
                    trovati.update(v.keys())
                    if variante is None or variante not in v:
                        raise KeyError(f"'{k}' dipende dalla variante ({', '.join(v)}): indica quale con --variante")
                    out[k] = v[variante]
                elif k == "regioni" and isinstance(v, dict):
                    if variante not in v:
                        raise KeyError(f"regioni del checksum per variante ({', '.join(v)}): indica quale con --variante")
                    out[k] = v[variante]
                else:
                    out[k] = giu(v)
            return out
        if isinstance(o, list):
            return [giu(x) for x in o]
        return o
    r = giu(struttura)
    r["variante"] = variante
    if variante and nomi and variante not in nomi and trovati and variante not in trovati:
        raise KeyError(f"variante {variante} sconosciuta: {nomi}")
    return r


def base(struttura) -> int:
    return _int(struttura.get("file", {}).get("base", 0))


def sha256(buf: bytes) -> str:
    return hashlib.sha256(buf).hexdigest()


def _fmt(dtype: str, endian: str):
    c, w, lo, hi = DTYPE[dtype]
    return ("<" if endian in ("le", "little", None) else ">") + c, w, lo, hi


@dataclass
class Asse:
    valori: np.ndarray
    unita: str = ""
    nome: str = ""
    segnale: str = ""
    indirizzo: int | None = None
    spec: dict | None = None


def _risolvi_asse(struttura, spec, buf, n_atteso):
    if spec is None:
        return Asse(np.arange(n_atteso, dtype=float), "", "indice")
    if isinstance(spec, str):
        nome = spec
        spec = struttura.get("assi", {}).get(spec)
        if spec is None:
            raise KeyError(f"asse {nome} non definito in 'assi'")
        spec = dict(spec, nome=spec.get("nome", nome))
    if "valori" in spec:
        v = np.asarray(spec["valori"], dtype=float)
        return Asse(v, spec.get("unita", ""), spec.get("nome", ""), spec.get("segnale", ""), None, spec)
    n = spec.get("n", n_atteso)
    fmt, w, _, _ = _fmt(spec.get("dtype", "u16"), spec.get("endian", "le"))
    off = _int(spec["indirizzo"]) - base(struttura)
    raw = np.array([struct.unpack_from(fmt, buf, off + i * w)[0] for i in range(n)], dtype=float)
    v = raw * spec.get("scala", 1.0) + spec.get("offset", 0.0)
    return Asse(v, spec.get("unita", ""), spec.get("nome", ""), spec.get("segnale", ""), _int(spec["indirizzo"]), spec)


def dimensioni(tab):
    t = tab.get("tipo", "mappa")
    if t == "valore":
        return 1, 1
    if t == "curva":
        return 1, tab.get("colonne", tab.get("n", 1))
    return tab["righe"], tab["colonne"]


def leggi_tabella(struttura, tab, buf: bytes) -> dict:
    r, c = dimensioni(tab)
    fmt, w, _, _ = _fmt(tab.get("dtype", "u16"), tab.get("endian", "le"))
    off = _int(tab["indirizzo"]) - base(struttura)
    n = r * c
    raw = np.array([struct.unpack_from(fmt, buf, off + i * w)[0] for i in range(n)], dtype=float)
    if tab.get("ordine", "righe") == "colonne":
        raw = raw.reshape(c, r).T
    else:
        raw = raw.reshape(r, c)
    z = raw * tab.get("scala", 1.0) + tab.get("offset", 0.0)
    ax = _risolvi_asse(struttura, tab.get("asse_x"), buf, c) if tab.get("tipo") != "valore" else None
    ay = _risolvi_asse(struttura, tab.get("asse_y"), buf, r) if tab.get("tipo") == "mappa" else None
    return {"id": tab["id"], "z": z, "raw": raw, "x": ax, "y": ay}


def scrivi_tabella(struttura, tab, buf: bytearray, z_fisico) -> list:
    """Scrive i valori fisici; ritorna gli avvisi (saturazioni, arrotondamenti forti)."""
    r, c = dimensioni(tab)
    z = np.asarray(z_fisico, dtype=float).reshape(r, c)
    fmt, w, lo, hi = _fmt(tab.get("dtype", "u16"), tab.get("endian", "le"))
    raw = (z - tab.get("offset", 0.0)) / tab.get("scala", 1.0)
    avvisi = []
    if lo is not None:
        rr = np.rint(raw)
        sat = (rr < lo) | (rr > hi)
        if np.any(sat):
            avvisi.append(f"{tab['id']}: {int(sat.sum())} celle fuori dal campo del tipo {tab.get('dtype')}, saturate")
        raw = np.clip(rr, lo, hi)
    seq = raw.T.reshape(-1) if tab.get("ordine", "righe") == "colonne" else raw.reshape(-1)
    off = _int(tab["indirizzo"]) - base(struttura)
    for i, v in enumerate(seq):
        struct.pack_into(fmt, buf, off + i * w, int(v) if lo is not None else float(v))
    return avvisi


def intervallo_tabella(struttura, tab):
    r, c = dimensioni(tab)
    _, w, _, _ = _fmt(tab.get("dtype", "u16"), tab.get("endian", "le"))
    a = _int(tab["indirizzo"]) - base(struttura)
    return a, a + r * c * w


def regioni_diverse(a: bytes, b: bytes, unisci=16):
    n = min(len(a), len(b))
    x = np.frombuffer(a[:n], dtype=np.uint8) != np.frombuffer(b[:n], dtype=np.uint8)
    idx = np.flatnonzero(x)
    if idx.size == 0:
        return []
    out = []
    s = e = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - e <= unisci:
            e = i
        else:
            out.append((s, e + 1))
            s = e = i
    out.append((s, e + 1))
    return out


def confronta(struttura, a: bytes, b: bytes) -> dict:
    """Differenze tabella per tabella + regioni cambiate fuori dalle tabelle note."""
    tab_out = []
    coperte = []
    for tab in struttura.get("tabelle", []):
        ta = leggi_tabella(struttura, tab, a)
        tb = leggi_tabella(struttura, tab, b)
        d = tb["z"] - ta["z"]
        coperte.append(intervallo_tabella(struttura, tab))
        if np.any(d != 0):
            rel = np.where(ta["z"] != 0, d / np.abs(ta["z"]) * 100, np.nan)
            tab_out.append({"id": tab["id"], "nome": tab.get("nome", ""), "celle_cambiate": int(np.count_nonzero(d)),
                            "delta_min": float(d.min()), "delta_max": float(d.max()),
                            "delta_rel_medio_%": float(np.nanmean(rel[d != 0])) if np.any(d != 0) else 0.0})
    for nome, spec in struttura.get("assi", {}).items():
        if "indirizzo" in spec:
            _, w, _, _ = _fmt(spec.get("dtype", "u16"), spec.get("endian", "le"))
            s0 = _int(spec["indirizzo"]) - base(struttura)
            coperte.append((s0, s0 + spec["n"] * w))
    for spec in struttura.get("checksum", []):
        p = _int(spec["posizione"]) - base(struttura)
        coperte.append((p, p + cks._FMT[spec.get("formato", "u32le")][1]))
    ignote = []
    for s, e in regioni_diverse(a, b, unisci=4):
        if not any(cs <= s and e <= ce for cs, ce in coperte):
            ignote.append({"inizio": hex(s + base(struttura)), "fine": hex(e + base(struttura)), "byte": e - s})
    return {"tabelle": tab_out, "regioni_fuori_struttura": ignote}


def verifica_checksum(struttura, buf: bytes) -> list:
    return [cks.verifica(buf, s, base(struttura)) for s in struttura.get("checksum", [])]


def correggi_checksum(struttura, buf: bytearray) -> list:
    return [cks.correggi(buf, s, base(struttura)) for s in struttura.get("checksum", [])]


def applica_patch(struttura, buf: bytes, patch: dict, correggi_cs=True) -> tuple[bytearray, list]:
    """patch = {"base_sha256": "...", "modifiche": [{"tabella": id, "valori": [[...]]} | {"indirizzo": "0x..", "hex": ".."}]}"""
    out = bytearray(buf)
    avvisi = []
    atteso = patch.get("base_sha256")
    if atteso and atteso != sha256(bytes(buf)):
        avvisi.append("ATTENZIONE: il file di partenza non è quello su cui è stata fatta la patch (sha256 diverso)")
    per_id = {t["id"]: t for t in struttura.get("tabelle", [])}
    for m in patch.get("modifiche", []):
        if "tabella" in m:
            tab = per_id.get(m["tabella"])
            if tab is None:
                avvisi.append(f"tabella {m['tabella']} non presente nella struttura: saltata")
                continue
            avvisi += scrivi_tabella(struttura, tab, out, m["valori"])
        elif "indirizzo" in m:
            off = _int(m["indirizzo"]) - base(struttura)
            dati = bytes.fromhex(m["hex"])
            out[off: off + len(dati)] = dati
    if correggi_cs and struttura.get("checksum"):
        for r in correggi_checksum(struttura, out):
            if not r["ok"]:
                avvisi.append(f"checksum {r['id']} non corretto dopo la scrittura!")
    elif not struttura.get("checksum"):
        avvisi.append("NESSUN checksum definito nella struttura: il file NON è pronto da scrivere in centralina")
    return out, avvisi


def lookup1d(x_asse, z, x):
    """Interpolazione lineare con saturazione ai bordi (come le centraline)."""
    return np.interp(x, x_asse, z)


def lookup2d(x_asse, y_asse, z, x, y):
    """Bilineare con saturazione. z[righe=y, colonne=x]."""
    x = np.clip(np.asarray(x, dtype=float), x_asse[0], x_asse[-1])
    y = np.clip(np.asarray(y, dtype=float), y_asse[0], y_asse[-1])
    ix = np.clip(np.searchsorted(x_asse, x, side="right") - 1, 0, len(x_asse) - 2) if len(x_asse) > 1 else np.zeros_like(x, dtype=int)
    iy = np.clip(np.searchsorted(y_asse, y, side="right") - 1, 0, len(y_asse) - 2) if len(y_asse) > 1 else np.zeros_like(y, dtype=int)
    if len(x_asse) > 1:
        fx = (x - x_asse[ix]) / np.where(x_asse[ix + 1] != x_asse[ix], x_asse[ix + 1] - x_asse[ix], 1)
    else:
        fx = np.zeros_like(x)
    if len(y_asse) > 1:
        fy = (y - y_asse[iy]) / np.where(y_asse[iy + 1] != y_asse[iy], y_asse[iy + 1] - y_asse[iy], 1)
    else:
        fy = np.zeros_like(y)
    ix1 = np.minimum(ix + 1, len(x_asse) - 1)
    iy1 = np.minimum(iy + 1, len(y_asse) - 1)
    z00 = z[iy, ix]; z01 = z[iy, ix1]; z10 = z[iy1, ix]; z11 = z[iy1, ix1]
    return (z00 * (1 - fx) * (1 - fy) + z01 * fx * (1 - fy) + z10 * (1 - fx) * fy + z11 * fx * fy)


def elenco(struttura, buf: bytes | None = None) -> list:
    out = []
    for tab in struttura.get("tabelle", []):
        r, c = dimensioni(tab)
        riga = {"id": tab["id"], "nome": tab.get("nome", ""), "gruppo": tab.get("gruppo", ""),
                "tipo": tab.get("tipo", "mappa"), "dim": f"{r}x{c}", "indirizzo": tab["indirizzo"],
                "dtype": tab.get("dtype", "u16"), "unita": tab.get("unita", ""), "verificato": tab.get("verificato", False)}
        if buf is not None:
            z = leggi_tabella(struttura, tab, buf)["z"]
            riga["min"] = float(z.min()); riga["max"] = float(z.max())
        out.append(riga)
    return out
