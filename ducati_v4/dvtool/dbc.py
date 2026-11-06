"""Lettore DBC minimo e decodifica vettoriale dei frame CAN.

Nessuna dipendenza oltre a numpy. Supporta:
  BO_  messaggi, SG_ segnali (Intel @1 e Motorola @0, con segno, fattore/offset),
  multiplex semplice (M / mN), VAL_ tabelle valori, CM_ commenti,
  BA_ "GenMsgCycleTime" per il periodo atteso.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Segnale:
    nome: str
    start: int
    lunghezza: int
    intel: bool          # True = little endian (@1), False = Motorola (@0)
    con_segno: bool
    fattore: float
    offset: float
    minimo: float
    massimo: float
    unita: str
    mux: str | None = None        # None, "M" (selettore) oppure valore del multiplexer
    commento: str = ""
    valori: dict = field(default_factory=dict)

    def decodifica_raw(self, le: np.ndarray, be: np.ndarray) -> np.ndarray:
        """Estrae il valore grezzo da interi a 64 bit (le = little endian, be = big endian)."""
        mask = np.uint64((1 << self.lunghezza) - 1) if self.lunghezza < 64 else np.uint64(0xFFFFFFFFFFFFFFFF)
        if self.intel:
            raw = (le >> np.uint64(self.start)) & mask
        else:
            msb = (self.start // 8) * 8 + (7 - self.start % 8)   # posizione contata dal MSB del byte 0
            lsb = msb + self.lunghezza - 1
            raw = (be >> np.uint64(63 - lsb)) & mask
        raw = raw.astype(np.int64) if self.lunghezza < 64 else raw.view(np.int64)
        if self.con_segno and self.lunghezza < 64:
            soglia = 1 << (self.lunghezza - 1)
            raw = np.where(raw >= soglia, raw - (1 << self.lunghezza), raw)
        return raw

    def fisico(self, raw: np.ndarray) -> np.ndarray:
        return raw.astype(np.float64) * self.fattore + self.offset


@dataclass
class Messaggio:
    id: int
    nome: str
    dlc: int
    trasmettitore: str
    segnali: list = field(default_factory=list)
    periodo_ms: float | None = None
    commento: str = ""

    @property
    def mux(self):
        for s in self.segnali:
            if s.mux == "M":
                return s
        return None


@dataclass
class Database:
    messaggi: dict = field(default_factory=dict)   # id -> Messaggio
    bitrate: int | None = None

    def per_nome(self, nome: str):
        for m in self.messaggi.values():
            if m.nome == nome:
                return m
        return None

    def segnale(self, nome: str):
        """Cerca un segnale per nome ("Msg.Segnale" oppure solo "Segnale")."""
        if "." in nome:
            mn, sn = nome.split(".", 1)
            m = self.per_nome(mn)
            if m:
                for s in m.segnali:
                    if s.nome == sn:
                        return m, s
            return None
        for m in self.messaggi.values():
            for s in m.segnali:
                if s.nome == nome:
                    return m, s
        return None


_RE_BO = re.compile(r"^BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+(\w+)")
_RE_SG = re.compile(
    r"^\s*SG_\s+(\w+)\s*(M|m\d+)?\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*"
    r"\(\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\)\s*"
    r"\[\s*([-+0-9.eE]+)\s*\|\s*([-+0-9.eE]+)\s*\]\s*\"([^\"]*)\""
)
_RE_CM_SG = re.compile(r'^CM_\s+SG_\s+(\d+)\s+(\w+)\s+"((?:[^"\\]|\\.)*)"\s*;', re.S)
_RE_CM_BO = re.compile(r'^CM_\s+BO_\s+(\d+)\s+"((?:[^"\\]|\\.)*)"\s*;', re.S)
_RE_VAL = re.compile(r"^VAL_\s+(\d+)\s+(\w+)\s+(.*);")
_RE_BA_CYCLE = re.compile(r'^BA_\s+"GenMsgCycleTime"\s+BO_\s+(\d+)\s+(\d+)\s*;')
_RE_BAUD = re.compile(r'^BA_\s+"Baudrate"\s+(\d+)\s*;')


def carica_dbc(percorso: str) -> Database:
    with open(percorso, "r", encoding="utf-8", errors="replace") as f:
        testo = f.read()
    return analizza_dbc(testo)


def analizza_dbc(testo: str) -> Database:
    db = Database()
    corrente = None
    # i commenti possono andare su più righe: li uniamo prima
    righe = testo.replace("\r\n", "\n").split("\n")
    buf = []
    for r in righe:
        if buf:
            buf.append(r)
            if r.rstrip().endswith(";"):
                _riga_lunga("\n".join(buf), db)
                buf = []
            continue
        if r.startswith("CM_") and not r.rstrip().endswith(";"):
            buf = [r]
            continue
        m = _RE_BO.match(r)
        if m:
            ident = int(m.group(1)) & 0x1FFFFFFF
            corrente = Messaggio(ident, m.group(2), int(m.group(3)), m.group(4))
            db.messaggi[ident] = corrente
            continue
        m = _RE_SG.match(r)
        if m and corrente is not None:
            mux = m.group(2)
            if mux and mux.startswith("m"):
                mux = mux[1:]
            corrente.segnali.append(Segnale(
                nome=m.group(1), start=int(m.group(3)), lunghezza=int(m.group(4)),
                intel=m.group(5) == "1", con_segno=m.group(6) == "-",
                fattore=float(m.group(7)), offset=float(m.group(8)),
                minimo=float(m.group(9)), massimo=float(m.group(10)), unita=m.group(11), mux=mux))
            continue
        if r.strip() == "":
            corrente = None
        _riga_lunga(r, db)
    return db


def _riga_lunga(r: str, db: Database):
    m = _RE_CM_SG.match(r)
    if m:
        msg = db.messaggi.get(int(m.group(1)) & 0x1FFFFFFF)
        if msg:
            for s in msg.segnali:
                if s.nome == m.group(2):
                    s.commento = m.group(3)
        return
    m = _RE_CM_BO.match(r)
    if m:
        msg = db.messaggi.get(int(m.group(1)) & 0x1FFFFFFF)
        if msg:
            msg.commento = m.group(2)
        return
    m = _RE_VAL.match(r)
    if m:
        msg = db.messaggi.get(int(m.group(1)) & 0x1FFFFFFF)
        if msg:
            coppie = re.findall(r'(-?\d+)\s+"([^"]*)"', m.group(3))
            for s in msg.segnali:
                if s.nome == m.group(2):
                    s.valori = {int(k): v for k, v in coppie}
        return
    m = _RE_BA_CYCLE.match(r)
    if m:
        msg = db.messaggi.get(int(m.group(1)) & 0x1FFFFFFF)
        if msg:
            msg.periodo_ms = float(m.group(2))
        return
    m = _RE_BAUD.match(r)
    if m:
        db.bitrate = int(m.group(1))


def interi64(data: np.ndarray):
    """data: array uint8 (N, 8) -> (little endian u64, big endian u64)."""
    d = np.zeros((data.shape[0], 8), dtype=np.uint8)
    d[:, : data.shape[1]] = data[:, :8]
    le = d.view("<u8").reshape(-1)
    be = d.view(">u8").reshape(-1).astype(np.uint64)
    return le.astype(np.uint64), be


def decodifica(db: Database, t: np.ndarray, ids: np.ndarray, data: np.ndarray, solo=None) -> dict:
    """Decodifica tutti i segnali noti.

    Ritorna {"Msg.Segnale": (t, valori)} con i tempi del messaggio di origine.
    solo: insieme opzionale di nomi segnale da tenere (nome semplice o Msg.Segnale).
    """
    uscita = {}
    for ident, msg in db.messaggi.items():
        sel = ids == ident
        if not np.any(sel):
            continue
        tm = t[sel]
        le, be = interi64(data[sel])
        mux = msg.mux
        mux_raw = mux.decodifica_raw(le, be) if mux else None
        for s in msg.segnali:
            chiave = f"{msg.nome}.{s.nome}"
            if solo is not None and chiave not in solo and s.nome not in solo:
                continue
            raw = s.decodifica_raw(le, be)
            val = s.fisico(raw)
            if s.mux not in (None, "M"):
                k = mux_raw == int(s.mux)
                uscita[chiave] = (tm[k], val[k])
            else:
                uscita[chiave] = (tm, val)
    return uscita


def codifica(msg: Messaggio, valori: dict) -> bytes:
    """Codifica un frame (usato dai dati sintetici e dai test)."""
    le = 0
    be_bits = [0] * 64
    for s in msg.segnali:
        if s.nome not in valori:
            continue
        raw = int(round((valori[s.nome] - s.offset) / s.fattore))
        raw &= (1 << s.lunghezza) - 1
        if s.intel:
            le |= raw << s.start
        else:
            msb = (s.start // 8) * 8 + (7 - s.start % 8)
            for i in range(s.lunghezza):
                bit = (raw >> (s.lunghezza - 1 - i)) & 1
                be_bits[msb + i] = bit
    out = bytearray(le.to_bytes(8, "little"))
    for pos, bit in enumerate(be_bits):
        if bit:
            out[pos // 8] |= 0x80 >> (pos % 8)
    return bytes(out[: msg.dlc])
