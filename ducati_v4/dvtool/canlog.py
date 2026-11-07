"""Lettura dei log CAN grezzi in un formato unico.

Formati riconosciuti (rilevamento automatico):
  * candump -L      "(1697040000.123456) can0 123#DEADBEEF"
  * candump         "  can0  123   [8]  DE AD BE EF 00 11 22 33"
  * candump -ta     "(1697040000.123456)  can0  123   [8]  DE AD ..."
  * Vector ASC      "   0.001234 1  123             Rx   d 8 DE AD ..."
  * CSV             intestazione con colonne tempo/id/dati (o byte d0..d7)
  * SQLite          tabella con colonne tempo + id + payload (archivio .r9session / .db / .sqlite)

Risultato: Log(t [s, float64], id [uint32], dlc [uint8], data [uint8 N x 8], bus [str per frame opzionale]).
"""
from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
import zipfile
from dataclasses import dataclass

import numpy as np


@dataclass
class Log:
    t: np.ndarray
    id: np.ndarray
    dlc: np.ndarray
    data: np.ndarray
    origine: str = ""
    note: str = ""
    errori: dict = None   # frame di errore del controller: {"n": ..., "overflow_rx": ..., "t": [...]}

    def __len__(self):
        return len(self.t)

    def ordina(self):
        o = np.argsort(self.t, kind="stable")
        return Log(self.t[o], self.id[o], self.dlc[o], self.data[o], self.origine, self.note, self.errori)

    def filtra_id(self, ids):
        k = np.isin(self.id, np.asarray(list(ids), dtype=np.uint32))
        return Log(self.t[k], self.id[k], self.dlc[k], self.data[k], self.origine, self.note)

    def inventario(self):
        """Per ogni ID: numero frame, frequenza media, DLC visti, byte che cambiano."""
        out = []
        if len(self) == 0:
            return out
        durata = max(self.t[-1] - self.t[0], 1e-9)
        for ident in np.unique(self.id):
            k = self.id == ident
            tt = self.t[k]
            dd = self.data[k]
            dt = np.diff(tt)
            variabili = [i for i in range(8) if dd.shape[0] > 1 and np.any(dd[:, i] != dd[0, i])]
            out.append({
                "id": int(ident),
                "id_hex": f"0x{int(ident):03X}",
                "frame": int(k.sum()),
                "hz": float(k.sum() / durata),
                "periodo_ms_mediano": float(np.median(dt) * 1000) if dt.size else None,
                "jitter_ms": float(np.std(dt) * 1000) if dt.size else None,
                "dlc": sorted(set(int(x) for x in np.unique(self.dlc[k]))),
                "byte_variabili": variabili,
                "esempio": bytes(dd[0, : int(self.dlc[k][0])]).hex(" ").upper(),
            })
        return out


def _da_liste(tt, ii, ll, dd, origine, note=""):
    n = len(tt)
    data = np.zeros((n, 8), dtype=np.uint8)
    for k, b in enumerate(dd):
        b = b[:8]
        data[k, : len(b)] = np.frombuffer(b, dtype=np.uint8)
    return Log(np.asarray(tt, dtype=np.float64), np.asarray(ii, dtype=np.uint32),
               np.asarray(ll, dtype=np.uint8), data, origine, note).ordina()


_RE_L = re.compile(r"^\((\d+\.\d+)\)\s+(\S+)\s+([0-9A-Fa-f]+)#(R?)([0-9A-Fa-f]*)")
_RE_TA = re.compile(r"^\s*\((\d+\.\d+)\)\s+(\S+)\s+([0-9A-Fa-f]+)\s+\[(\d)\]\s+((?:[0-9A-Fa-f]{2}\s*)*)")
_RE_PLAIN = re.compile(r"^\s*(\S+)\s+([0-9A-Fa-f]+)\s+\[(\d)\]\s+((?:[0-9A-Fa-f]{2}\s*)*)")
_RE_ASC = re.compile(r"^\s*(\d+\.\d+)\s+(\d+)\s+([0-9A-Fa-f]+)x?\s+(Rx|Tx)\s+d\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)*)")


def leggi_testo(righe, origine="testo") -> Log:
    tt, ii, ll, dd = [], [], [], []
    et, ed = [], []
    t_finto = 0.0
    for r in righe:
        m = _RE_L.match(r)
        if m:
            payload = bytes.fromhex(m.group(5)) if m.group(5) else b""
            if len(m.group(3)) == 8 and int(m.group(3), 16) & 0x20000000:
                # frame di errore (candump -L "...#FFFFFFFF"): non è un messaggio della moto
                et.append(float(m.group(1))); ed.append(payload)
                continue
            tt.append(float(m.group(1))); ii.append(int(m.group(3), 16) & 0x1FFFFFFF)
            ll.append(len(payload)); dd.append(payload)
            continue
        m = _RE_TA.match(r)
        if m:
            payload = bytes.fromhex(m.group(5).replace(" ", ""))
            tt.append(float(m.group(1))); ii.append(int(m.group(3), 16)); ll.append(int(m.group(4))); dd.append(payload)
            continue
        m = _RE_ASC.match(r)
        if m:
            payload = bytes.fromhex(m.group(6).replace(" ", ""))
            tt.append(float(m.group(1))); ii.append(int(m.group(3), 16)); ll.append(int(m.group(5))); dd.append(payload)
            continue
        m = _RE_PLAIN.match(r)
        if m:
            payload = bytes.fromhex(m.group(4).replace(" ", ""))
            t_finto += 0.001
            tt.append(t_finto); ii.append(int(m.group(2), 16)); ll.append(int(m.group(3))); dd.append(payload)
    nota = "senza tempi: passo fittizio 1 ms" if t_finto else ""
    log = _da_liste(tt, ii, ll, dd, origine, nota)
    log.errori = _errori(et, ed)
    return log


def _errori(et, ed):
    """Riassunto dei frame di errore: classe controller (0x4) con byte 1 bit 0 = overflow in ricezione."""
    ov = sum(1 for d in ed if len(d) > 1 and d[1] & 0x01)
    return {"n": len(et), "overflow_rx": ov, "t": et}


_COL_T = ("t", "ts", "time", "timestamp", "tempo", "t_s", "t_mono", "mono", "time_s", "t_ns", "ts_ns", "t_us", "ts_us")
_COL_ID = ("id", "can_id", "arb_id", "arbitration_id", "ident", "msg_id", "canid")
_COL_DATA = ("data", "payload", "dati", "bytes", "raw", "hex")


def _scala_tempo(nome: str, valori: np.ndarray) -> np.ndarray:
    n = nome.lower()
    if n.endswith("_ns") or n == "ns":
        return valori / 1e9
    if n.endswith("_us") or n == "us":
        return valori / 1e6
    if n.endswith("_ms") or n == "ms":
        return valori / 1e3
    # euristica: se i valori sono enormi sono ns o us
    if valori.size and np.nanmedian(np.abs(valori)) > 1e14:
        return valori / 1e9
    if valori.size and np.nanmedian(np.abs(valori)) > 1e11:
        return valori / 1e6
    return valori


def _bytes_da(v):
    if v is None:
        return b""
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v)
    s = str(v).strip().replace(" ", "").replace(":", "").replace("0x", "")
    try:
        return bytes.fromhex(s)
    except ValueError:
        return b""


def leggi_csv(testo: str, origine="csv") -> Log:
    rd = csv.DictReader(io.StringIO(testo), delimiter=";" if testo.count(";") > testo.count(",") else ",")
    campi = {c.lower().strip(): c for c in (rd.fieldnames or [])}
    ct = next((campi[c] for c in _COL_T if c in campi), None)
    ci = next((campi[c] for c in _COL_ID if c in campi), None)
    cd = next((campi[c] for c in _COL_DATA if c in campi), None)
    byte_cols = [campi[f"d{i}"] for i in range(8) if f"d{i}" in campi] or [campi[f"b{i}"] for i in range(8) if f"b{i}" in campi]
    if not (ct and ci and (cd or byte_cols)):
        raise ValueError(f"CSV senza colonne tempo/id/dati riconoscibili: {rd.fieldnames}")
    tt, ii, ll, dd = [], [], [], []
    for r in rd:
        idv = r[ci].strip()
        ident = int(idv, 16) if idv.lower().startswith("0x") or re.search(r"[a-fA-F]", idv) else int(idv)
        if cd:
            b = _bytes_da(r[cd])
        else:
            b = bytes(int(r[c], 16) for c in byte_cols if r[c] not in ("", None))
        tt.append(float(r[ct])); ii.append(ident); ll.append(len(b)); dd.append(b)
    t = _scala_tempo(ct, np.asarray(tt, dtype=np.float64))
    return _da_liste(t, ii, ll, dd, origine)


def tabelle_sqlite(con) -> list:
    cur = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    out = []
    for (nome,) in cur.fetchall():
        colonne = [r[1] for r in con.execute(f'PRAGMA table_info("{nome}")')]
        n = con.execute(f'SELECT COUNT(*) FROM "{nome}"').fetchone()[0]
        out.append({"tabella": nome, "colonne": colonne, "righe": n})
    return out


def trova_tabella_can(con, preferita: str | None = None):
    """Trova la tabella con i frame CAN grezzi. Ritorna (tabella, col_t, col_id, col_data o lista byte, col_dlc)."""
    cand = []
    for info in tabelle_sqlite(con):
        if preferita and info["tabella"] != preferita:
            continue
        low = {c.lower(): c for c in info["colonne"]}
        ct = next((low[c] for c in _COL_T if c in low), None)
        ci = next((low[c] for c in _COL_ID if c in low), None)
        cd = next((low[c] for c in _COL_DATA if c in low), None)
        cb = [low[f"d{i}"] for i in range(8) if f"d{i}" in low]
        cl = next((low[c] for c in ("dlc", "len", "lunghezza", "length") if c in low), None)
        if ct and ci and (cd or cb):
            punteggio = info["righe"] + (10**9 if "can" in info["tabella"].lower() or "frame" in info["tabella"].lower() else 0)
            cand.append((punteggio, info["tabella"], ct, ci, cd or cb, cl))
    if not cand:
        return None
    cand.sort(reverse=True)
    return cand[0][1:]


def leggi_sqlite(percorso: str, tabella: str | None = None) -> Log:
    con = sqlite3.connect(f"file:{percorso}?mode=ro", uri=True)
    try:
        trovata = trova_tabella_can(con, tabella)
        if not trovata:
            elenco = ", ".join(f"{x['tabella']}({','.join(x['colonne'])})" for x in tabelle_sqlite(con))
            raise ValueError(f"Nessuna tabella CAN riconosciuta in {percorso}. Tabelle: {elenco}")
        tab, ct, ci, cd, cl = trovata
        if isinstance(cd, list):
            q = f'SELECT "{ct}", "{ci}", {", ".join(chr(34)+c+chr(34) for c in cd)} FROM "{tab}" ORDER BY "{ct}"'
            righe = con.execute(q).fetchall()
            tt = [r[0] for r in righe]; ii = [r[1] for r in righe]
            dd = [bytes(int(x or 0) for x in r[2:]) for r in righe]
            ll = [len(d) for d in dd]
        else:
            q = f'SELECT "{ct}", "{ci}", "{cd}"{", " + chr(34) + cl + chr(34) if cl else ""} FROM "{tab}" ORDER BY "{ct}"'
            righe = con.execute(q).fetchall()
            tt = [r[0] for r in righe]
            ii = [int(r[1], 16) if isinstance(r[1], str) else int(r[1]) for r in righe]
            dd = [_bytes_da(r[2]) for r in righe]
            ll = [int(r[3]) if cl and r[3] is not None else len(d) for r, d in zip(righe, dd)]
        t = _scala_tempo(ct, np.asarray(tt, dtype=np.float64))
        return _da_liste(t, ii, ll, dd, f"{percorso}:{tab}", f"tabella {tab}")
    finally:
        con.close()


def leggi_jsonl(righe, origine="jsonl") -> Log:
    """Registratori della scatola H3D (r9-can / can-correlation): una riga JSON per frame,
    {"can_id": <decimale>, "data_hex": "...", "ts_monotonic_ns": ..., "boot_id": "..."}.
    I tempi sono monotoni (ripartono a ogni accensione): restano relativi."""
    import json as _json
    tt, ii, ll, dd = [], [], [], []
    for r in righe:
        r = r.strip()
        if not r or not r.startswith("{"):
            continue
        try:
            o = _json.loads(r)
        except ValueError:
            continue
        if "can_id" not in o:
            continue
        t = o.get("ts_kernel_realtime_ns") or o.get("ts_monotonic_ns") or o.get("ts_ns") or o.get("t_ns")
        if t is None:
            t = (o.get("t") or 0) * 1e9
        b = _bytes_da(o.get("data_hex", o.get("data", "")))
        tt.append(float(t) / 1e9); ii.append(int(o["can_id"]) & 0x1FFFFFFF); ll.append(len(b)); dd.append(b)
    return _da_liste(tt, ii, ll, dd, origine, "tempi monotoni della scatola")


def _apri_testo(percorso):
    import gzip
    if percorso.endswith(".gz"):
        return gzip.open(percorso, "rt", encoding="utf-8", errors="replace")
    if percorso.endswith(".zst"):
        raise ValueError("file .zst: decomprimilo prima (zstd -d) oppure usa i segmenti .gz")
    return open(percorso, "r", encoding="utf-8", errors="replace")


def leggi_cartella(percorso: str) -> Log:
    """Cartella di segmenti (app_data/can_cablato/<boot>/...jsonl.gz) o di catture candump: li unisce in ordine."""
    files = []
    for r, _, fs in os.walk(percorso):
        for fn in fs:
            if fn.endswith((".jsonl", ".jsonl.gz", ".log", ".candump")) and fn not in ("indice.jsonl", "marcatori.txt"):
                files.append(os.path.join(r, fn))
    if not files:
        raise ValueError(f"nessun segmento CAN in {percorso}")
    logs = [leggi(f) for f in sorted(files)]
    t = np.concatenate([x.t for x in logs]); i = np.concatenate([x.id for x in logs])
    l = np.concatenate([x.dlc for x in logs]); d = np.concatenate([x.data for x in logs])
    out = Log(t, i, l, d, percorso, f"{len(files)} segmenti").ordina()
    er = [x.errori for x in logs if x.errori]
    out.errori = {"n": sum(e["n"] for e in er), "overflow_rx": sum(e["overflow_rx"] for e in er), "t": [v for e in er for v in e["t"]]}
    return out


def leggi(percorso: str, tabella: str | None = None) -> Log:
    """Rilevamento automatico del formato."""
    if os.path.isdir(percorso):
        return leggi_cartella(percorso)
    est = os.path.splitext(percorso)[1].lower()
    if percorso.endswith((".jsonl", ".jsonl.gz")):
        with _apri_testo(percorso) as f:
            return leggi_jsonl(f, percorso)
    if percorso.endswith(".gz"):
        with _apri_testo(percorso) as f:
            testo = f.read()
        return leggi_jsonl(testo.splitlines(), percorso) if testo.lstrip().startswith("{") else leggi_testo(testo.splitlines(), percorso)
    with open(percorso, "rb") as f:
        testa = f.read(16)
    if testa.startswith(b"SQLite format 3"):
        return leggi_sqlite(percorso, tabella)
    if testa.startswith(b"PK"):
        return leggi_archivio(percorso, tabella)
    with open(percorso, "r", encoding="utf-8", errors="replace") as f:
        testo = f.read()
    if testo.lstrip().startswith('{"'):
        return leggi_jsonl(testo.splitlines(), percorso)
    if est == ".csv" or (testo[:200].count(",") > 3 and "#" not in testo[:200]):
        try:
            return leggi_csv(testo, percorso)
        except ValueError:
            pass
    return leggi_testo(testo.splitlines(), percorso)


def leggi_archivio(percorso: str, tabella: str | None = None) -> Log:
    """Archivio zip (es. pacchetto .r9session): estrae db (+ -wal) e/o log testuali in una cartella temporanea."""
    import tempfile
    with zipfile.ZipFile(percorso) as z, tempfile.TemporaryDirectory() as tmp:
        z.extractall(tmp)
        candidati = []
        for radice, _, files in os.walk(tmp):
            for fn in files:
                p = os.path.join(radice, fn)
                if fn.endswith(("-wal", "-shm", "-journal")):
                    continue
                with open(p, "rb") as f:
                    if f.read(16).startswith(b"SQLite format 3"):
                        candidati.append(("sqlite", p))
                    elif fn.lower().endswith((".log", ".asc", ".csv", ".txt", ".candump")):
                        candidati.append(("testo", p))
        logs = []
        for tipo, p in candidati:
            try:
                logs.append(leggi_sqlite(p, tabella) if tipo == "sqlite" else leggi(p))
            except ValueError:
                continue
        if not logs:
            raise ValueError(f"Nessun log CAN trovato dentro {percorso}")
        logs.sort(key=len, reverse=True)
        lg = logs[0]
        lg.origine = f"{percorso}!{os.path.basename(lg.origine)}"
        return lg


def scrivi_candump(log: Log, percorso: str, bus: str = "can0"):
    with open(percorso, "w", encoding="ascii") as f:
        for t, i, l, d in zip(log.t, log.id, log.dlc, log.data):
            f.write(f"({t:.6f}) {bus} {int(i):03X}#{bytes(d[: int(l)]).hex().upper()}\n")
