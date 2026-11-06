"""Checksum dei file di calibrazione.

Le specifiche stanno nella struttura (campo "checksum"), per esempio:
  {"id": "CS_CAL", "algoritmo": "sum32_le", "regioni": [["0x40000", "0x7FFFC"]],
   "posizione": "0x7FFFC", "formato": "u32le", "complemento": "nessuno"}

algoritmo: sum8 | sum16_le | sum16_be | sum32_le | sum32_be | crc16_ccitt | crc16_modbus | crc32 | crc32_mpeg2
complemento: nessuno | uno (~x) | due (-x)
Le regioni sono [inizio, fine) in indirizzi della struttura (vengono tradotti con la base del file).
La posizione del checksum, se cade dentro una regione, viene esclusa dal calcolo.
"""
from __future__ import annotations

import struct
import zlib


def _int(x):
    return int(x, 0) if isinstance(x, str) else int(x)


def _crc16(data: bytes, poly: int, init: int, riflesso: bool, xorout: int = 0) -> int:
    crc = init
    if riflesso:
        rpoly = int(f"{poly:016b}"[::-1], 2)
        for b in data:
            crc ^= b
            for _ in range(8):
                crc = (crc >> 1) ^ rpoly if crc & 1 else crc >> 1
    else:
        for b in data:
            crc ^= b << 8
            for _ in range(8):
                crc = ((crc << 1) ^ poly) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return (crc ^ xorout) & 0xFFFF


def _crc32_mpeg2(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


def calcola(algoritmo: str, data: bytes) -> tuple[int, int]:
    """Ritorna (valore, bit)."""
    a = algoritmo.lower()
    if a == "sum8":
        return sum(data) & 0xFF, 8
    if a in ("sum16_le", "sum16_be"):
        d = data + b"\0" * (len(data) % 2)
        fmt = "<" if a.endswith("le") else ">"
        return sum(struct.unpack(f"{fmt}{len(d)//2}H", d)) & 0xFFFF, 16
    if a in ("sum32_le", "sum32_be"):
        d = data + b"\0" * ((4 - len(data) % 4) % 4)
        fmt = "<" if a.endswith("le") else ">"
        return sum(struct.unpack(f"{fmt}{len(d)//4}I", d)) & 0xFFFFFFFF, 32
    if a == "sum8_32":  # somma dei byte su 32 bit
        return sum(data) & 0xFFFFFFFF, 32
    if a == "crc16_ccitt":
        return _crc16(data, 0x1021, 0xFFFF, False), 16
    if a == "crc16_xmodem":
        return _crc16(data, 0x1021, 0x0000, False), 16
    if a == "crc16_modbus":
        return _crc16(data, 0x8005, 0xFFFF, True), 16
    if a == "crc32":
        return zlib.crc32(data) & 0xFFFFFFFF, 32
    if a == "crc32_mpeg2":
        return _crc32_mpeg2(data), 32
    raise ValueError(f"algoritmo di checksum sconosciuto: {algoritmo}")


ALGORITMI = ["sum8", "sum16_le", "sum16_be", "sum32_le", "sum32_be", "sum8_32",
             "crc16_ccitt", "crc16_xmodem", "crc16_modbus", "crc32", "crc32_mpeg2"]

_FMT = {"u8": ("<B", 1), "u16le": ("<H", 2), "u16be": (">H", 2), "u32le": ("<I", 4), "u32be": (">I", 4)}


def _complementa(v: int, bit: int, tipo: str) -> int:
    m = (1 << bit) - 1
    if tipo in ("uno", "ones", "~"):
        return (~v) & m
    if tipo in ("due", "twos", "-"):
        return (-v) & m
    return v & m


def _dati_regioni(buf: bytes, spec: dict, base: int) -> bytes:
    pos = _int(spec["posizione"]) - base if "posizione" in spec else None
    larg = _FMT[spec.get("formato", "u32le")][1]
    escludi = [(_int(a) - base, _int(b) - base) for a, b in spec.get("escludi", [])]
    if pos is not None:
        escludi.append((pos, pos + larg))
    pezzi = []
    for a, b in spec["regioni"]:
        a, b = _int(a) - base, _int(b) - base
        cur = a
        for ea, eb in sorted(escludi):
            if eb <= cur or ea >= b:
                continue
            pezzi.append(buf[cur:max(cur, ea)])
            cur = max(cur, eb)
        pezzi.append(buf[cur:b])
    return b"".join(pezzi)


def verifica(buf: bytes, spec: dict, base: int = 0) -> dict:
    dati = _dati_regioni(buf, spec, base)
    v, bit = calcola(spec["algoritmo"], dati)
    atteso = _complementa(v, bit, spec.get("complemento", "nessuno"))
    fmt, larg = _FMT[spec.get("formato", "u32le")]
    pos = _int(spec["posizione"]) - base
    salvato = struct.unpack_from(fmt, buf, pos)[0]
    atteso &= (1 << (8 * larg)) - 1
    return {"id": spec.get("id", "?"), "salvato": salvato, "calcolato": atteso, "ok": salvato == atteso,
            "posizione": spec["posizione"], "algoritmo": spec["algoritmo"]}


def correggi(buf: bytearray, spec: dict, base: int = 0) -> dict:
    r = verifica(bytes(buf), spec, base)
    fmt, _ = _FMT[spec.get("formato", "u32le")]
    struct.pack_into(fmt, buf, _int(spec["posizione"]) - base, r["calcolato"])
    r2 = verifica(bytes(buf), spec, base)
    r2["prima"] = r["salvato"]
    return r2


def cerca(buf: bytes, inizio: int, fine: int, finestra_ricerca=None) -> list:
    """Calcola tutti gli algoritmi su [inizio, fine) e cerca i risultati (LE/BE, con complementi) nel file.
    Utile per individuare dove sta un checksum quando si conosce la regione protetta."""
    dati = buf[inizio:fine]
    trovati = []
    a0, a1 = finestra_ricerca or (0, len(buf))
    for alg in ALGORITMI:
        v, bit = calcola(alg, dati)
        for comp in ("nessuno", "uno", "due"):
            x = _complementa(v, bit, comp)
            larg = bit // 8
            for endian in ("<", ">"):
                if larg == 1:
                    pat = bytes([x])
                else:
                    pat = x.to_bytes(larg, "little" if endian == "<" else "big")
                if larg < 2:
                    continue  # un byte da solo dà troppe corrispondenze casuali
                i = buf.find(pat, a0, a1)
                while i != -1:
                    trovati.append({"algoritmo": alg, "complemento": comp, "endian": "le" if endian == "<" else "be",
                                    "posizione": hex(i), "valore": hex(x)})
                    i = buf.find(pat, i + 1, a1)
    return trovati
