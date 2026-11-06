"""Dati DEMO sintetici per provare tutta la catena senza la moto.

ATTENZIONE: pista, protocollo CAN, tabelle e modello generati qui sono INVENTATI.
Non sono il protocollo Ducati né la calibrazione della centralina: servono solo a collaudare gli strumenti.

  python -m dvtool demo --out esempi/demo
crea: demo.dbc, demo_log.candump, demo_originale.bin, demo_modificato.bin, struttura_demo.json,
      modello_demo.json, profilo_demo.json, patch_demo.json
"""
from __future__ import annotations

import json
import os
import struct

import numpy as np

from . import calib
from . import checksum as cks

G = 9.80665

# ---------------------------------------------------------------- pista (poligono chiuso con raccordi)
_P = np.array([(0, 0), (900, 0), (1000, 250), (700, 420), (800, 650), (450, 700), (300, 520), (100, 600),
               (-150, 420), (-100, 150)], float)
_R = [60, 45, 80, 50, 40, 120, 35, 70, 90, 55]


def curvatura_pista(ds=1.0):
    n = len(_P)
    ang, tl = [], []
    for i in range(n):
        a, b, c = _P[i - 1], _P[i], _P[(i + 1) % n]
        u = (b - a) / np.linalg.norm(b - a)
        v = (c - b) / np.linalg.norm(c - b)
        th = np.arctan2(u[0] * v[1] - u[1] * v[0], u @ v)
        ang.append(th)
        tl.append(_R[i] * np.tan(abs(th) / 2))
    k = []
    for i in range(n):
        L = np.linalg.norm(_P[(i + 1) % n] - _P[i]) - tl[i] - tl[(i + 1) % n]
        arco = abs(ang[i]) * _R[i]
        na = int(round(arco / ds))
        # ingresso/uscita graduali (clotoide approssimata)
        kk = np.full(na, np.sign(ang[i]) / _R[i])
        m = max(2, int(0.3 * na))
        w = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, m))
        kk[:m] *= w
        kk[-m:] *= w[::-1]
        kk *= ang[i] / (kk.sum() * ds)
        k += list(kk)
        k += [0.0] * int(round(L / ds))
    k = np.array(k)
    # il rettilineo principale è dopo il vertice 0: ruota perché il giro parta a metà del rettilineo
    return np.roll(k, -int(np.flatnonzero(k == 0)[0] + 300))


def profilo_velocita(k, ds, mu_lat=1.35, v_max=295 / 3.6, a_acc=8.5, a_fren=11.5, v_ingresso=None):
    v_lim = np.minimum(np.sqrt(mu_lat * G / np.maximum(np.abs(k), 1e-6)), v_max)
    k_s = np.convolve(np.abs(k), np.ones(15) / 15, mode="same")
    v_lim = np.minimum(v_lim, np.sqrt(mu_lat * G / np.maximum(k_s, 1e-6)))
    v = v_lim.copy()
    n = len(v)
    # due giri di passate avanti/indietro (giro chiuso)
    if v_ingresso is not None:
        v[0] = v_ingresso
    for _ in range(2):
        for i in range(1, n):
            alat = v[i - 1] ** 2 * abs(k[i - 1])
            cerchio = max(0.0, 1 - (alat / (mu_lat * G)) ** 2) ** 0.5
            drag = 0.5 * 1.2 * 0.32 * v[i - 1] ** 2 / 215
            a = max(0.0, min(a_acc, 150e3 / (215 * max(v[i - 1], 5))) * cerchio - drag)
            v[i] = min(v_lim[i], np.sqrt(v[i - 1] ** 2 + 2 * a * ds))
        for i in range(n - 2, -1, -1):
            alat = v[i + 1] ** 2 * abs(k[i + 1])
            cerchio = max(0.0, 1 - (alat / (mu_lat * G)) ** 2) ** 0.5
            v[i] = min(v[i], np.sqrt(v[i + 1] ** 2 + 2 * a_fren * max(cerchio, 0.25) * ds))
        if v_ingresso is None:
            v[0] = v[-1]
    return v


RAPPORTI = [108.0, 84.0, 69.0, 59.0, 52.0, 47.0]   # giri/min per km/h, marcia 1..6 (inventati)


def marcia(v_kmh):
    lim = [0, 80, 115, 150, 185, 220]
    return np.clip(np.searchsorted(lim, v_kmh, side="right"), 1, 6)


def raggio_reale(piega_deg, R0, r_corona):
    """Raggio di rotolamento reale del pneumatico in piega (toro): R0 - rc*(1-cos(phi))."""
    ph = np.radians(np.abs(piega_deg))
    return R0 - r_corona * (1 - np.cos(ph))


R0_POST, RC_POST = 325.9, 118.0     # 200/55 ZR17 (corona inventata)
R0_ANT, RC_ANT = 299.9, 70.0        # 120/70 ZR17


def simula(seme=7, giri_lanciati=5):
    rng = np.random.default_rng(seme)
    ds = 1.0
    k = curvatura_pista(ds)
    L = len(k) * ds
    pezzi_v, pezzi_k = [], []
    # giro di uscita lento, giri lanciati, giro di rientro
    pezzi_v.append(profilo_velocita(k, ds, mu_lat=0.75, v_max=190 / 3.6, a_acc=4.0, v_ingresso=3.0))
    pezzi_k.append(k)
    for g in range(giri_lanciati):
        mu = 1.33 + rng.uniform(-0.04, 0.03)
        pezzi_v.append(profilo_velocita(k, ds, mu_lat=mu))
        pezzi_k.append(k)
    vr = profilo_velocita(k, ds, mu_lat=0.8, v_max=170 / 3.6, a_acc=3.0)
    # rientro: decelera fino a fermarsi nell'ultimo tratto
    fine = np.linspace(1, 0, len(vr)) ** 0.15
    vr = np.minimum(vr, np.maximum(fine * 60, 0.0) + 0.0)
    vr[-200:] = np.linspace(vr[-200], 0.0, 200)
    pezzi_v.append(vr)
    pezzi_k.append(k)
    v = np.concatenate(pezzi_v)
    kk = np.concatenate(pezzi_k)
    v = np.maximum(v, 0.0)
    s = np.arange(len(v)) * ds
    # tempo dalla distanza
    vm = np.maximum(0.5 * (v[1:] + v[:-1]), 0.3)
    t_s = np.concatenate([[0.0], np.cumsum(ds / vm)])
    # fermo iniziale 20 s e finale 15 s
    t_s = t_s + 20.0
    f = 100.0
    t = np.arange(0, t_s[-1] + 15.0, 1 / f)
    vv = np.interp(t, t_s, v, left=0.0, right=0.0)
    kt = np.interp(t, t_s, kk, left=0.0, right=0.0)
    piega = np.degrees(np.arctan(vv ** 2 * kt / G))
    piega = np.convolve(piega, np.ones(9) / 9, mode="same")
    piega += rng.normal(0, 0.25, len(t)) * (vv > 2)
    acc = np.gradient(vv, t)
    acc = np.convolve(acc, np.ones(15) / 15, mode="same")
    vk = vv * 3.6
    gear = marcia(vk)
    gear = np.where(vk < 2, 0, gear)
    rpm = np.where(vk < 2, 1450 + rng.normal(0, 20, len(t)), vk * np.take(RAPPORTI, np.clip(gear - 1, 0, 5)))
    gas = np.clip(np.where(acc > 0.3, 25 + 75 * np.clip(acc / 7.0, 0, 1), np.where(acc < -1.0, 0.0, 12.0)), 0, 100)
    gas = np.convolve(gas, np.ones(12) / 12, mode="same")
    # slittamento posteriore in uscita di curva (con qualche "spinta" in più su alcuni giri)
    spinta = np.zeros(len(t))
    centri = rng.choice(np.flatnonzero((acc > 2) & (np.abs(piega) > 30)), size=40, replace=False)
    for c in centri:
        w = rng.uniform(0.25, 0.6)
        spinta += rng.uniform(4, 11) * np.exp(-0.5 * ((t - t[c]) / w) ** 2)
    slip_vero = (0.8 + 2.5 * np.clip(acc / 8, 0, 1) * (1 + np.abs(piega) / 40)) * (vk > 20) + spinta * (vk > 20)
    # velocità a terra (al punto di contatto) e velocità misurate (sensore assume R0)
    v_terra_post = vv * (1 + slip_vero / 100)
    R_p = raggio_reale(piega, R0_POST, RC_POST)
    R_a = raggio_reale(piega, R0_ANT, RC_ANT)
    v_post_mis = v_terra_post * (R0_POST / R_p) * 3.6
    v_ant_mis = vv * (R0_ANT / R_a) * 3.6 * 1.012     # +1.2 % errore di taratura circonferenza
    v_post_mis += rng.normal(0, 0.08, len(t))
    v_ant_mis += rng.normal(0, 0.08, len(t))
    v_post_mis = np.maximum(v_post_mis, 0.0)
    v_ant_mis = np.maximum(v_ant_mis, 0.0)
    imb = np.degrees(vv * kt)
    ay = vv ** 2 * kt / G
    return {"t": t, "v_vero": vk, "v_ant": v_ant_mis, "v_post": v_post_mis, "piega": piega, "giri": rpm, "gas": gas,
            "marcia": gear, "imbardata": imb, "ax": acc / G, "ay": ay, "lunghezza_pista": L, "slip_vero": slip_vero}


# ---------------------------------------------------------------- DBC demo
DBC_DEMO = '''VERSION "DEMO - protocollo inventato, NON Ducati"

BS_:

BU_: ECU IMU DEMO

BO_ 160 DEMO_Ruote: 8 ECU
 SG_ V_ant : 0|16@1+ (0.01,0) [0|400] "km/h" DEMO
 SG_ V_post : 16|16@1+ (0.01,0) [0|400] "km/h" DEMO

BO_ 176 DEMO_Motore: 8 ECU
 SG_ Giri : 0|16@1+ (1,0) [0|16000] "rpm" DEMO
 SG_ Gas : 16|8@1+ (0.5,0) [0|100] "%" DEMO
 SG_ Farfalla : 24|8@1+ (0.5,0) [0|100] "%" DEMO
 SG_ Marcia : 32|4@1+ (1,0) [0|6] "" DEMO

BO_ 192 DEMO_IMU: 8 IMU
 SG_ Piega : 0|16@1- (0.01,0) [-90|90] "deg" DEMO
 SG_ Imbardata : 16|16@1- (0.01,0) [-300|300] "deg/s" DEMO
 SG_ Ax : 32|16@1- (0.001,0) [-3|3] "g" DEMO
 SG_ Ay : 48|16@1- (0.001,0) [-3|3] "g" DEMO

BO_ 208 DEMO_Controlli: 8 ECU
 SG_ Livello_TC : 0|4@1+ (1,0) [0|8] "" DEMO
 SG_ TC_attivo : 4|1@1+ (1,0) [0|1] "" DEMO
 SG_ Taglio_coppia : 8|8@1+ (0.5,0) [0|100] "%" DEMO

CM_ BO_ 160 "DEMO: velocita ruote come le invierebbe la centralina (raggio nominale)";
CM_ SG_ 192 Piega "DEMO: angolo di piega con segno, destra positivo";
BA_DEF_ BO_ "GenMsgCycleTime" INT 0 10000;
BA_ "GenMsgCycleTime" BO_ 160 20;
BA_ "GenMsgCycleTime" BO_ 176 20;
BA_ "GenMsgCycleTime" BO_ 192 20;
BA_ "GenMsgCycleTime" BO_ 208 20;
'''


def _frame_intel(campi, n):
    """campi: lista di (raw_array, start, len) -> array uint8 (n, 8)."""
    acc = np.zeros(n, dtype=np.uint64)
    for raw, start, lung in campi:
        r = np.asarray(np.rint(raw), dtype=np.int64) & ((1 << lung) - 1)
        acc |= (r.astype(np.uint64) << np.uint64(start))
    return acc.view(np.uint8).reshape(n, 8)


# ---------------------------------------------------------------- struttura e file .bin demo
ASSE_PIEGA = [0, 10, 20, 30, 35, 40, 45, 50, 55, 60, 65]
ASSE_GIRI = [3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000, 11000, 12000, 13000, 14000]
ASSE_V = [30, 60, 90, 120, 160, 200, 250, 300]
ASSE_ECCESSO = [0, 1, 2, 3, 4, 6, 8, 12]
ASSE_PROF = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60]


def struttura_demo():
    S = {"nome": "DEMO – centralina inventata (non Ducati)", "file": {"base": "0x0", "dimensione": 65536},
         "checksum": [{"id": "CS_DEMO", "algoritmo": "sum32_le", "regioni": [["0x0", "0x10000"]],
                       "posizione": "0xFFFC", "formato": "u32le", "complemento": "nessuno"}],
         "assi": {
             "ASSE_PIEGA": {"indirizzo": "0x1000", "n": 11, "dtype": "u16", "endian": "le", "scala": 0.1, "unita": "deg", "segnale": "piega_f"},
             "ASSE_GIRI": {"indirizzo": "0x1020", "n": 12, "dtype": "u16", "endian": "le", "scala": 1, "unita": "rpm", "segnale": "giri"},
             "ASSE_V": {"indirizzo": "0x1040", "n": 8, "dtype": "u16", "endian": "le", "scala": 0.1, "unita": "km/h", "segnale": "v_rif"},
             "ASSE_MARCIA": {"valori": [1, 2, 3, 4, 5, 6], "unita": "", "segnale": "marcia"},
             "ASSE_ECCESSO": {"indirizzo": "0x1060", "n": 8, "dtype": "u16", "endian": "le", "scala": 0.01, "unita": "%", "segnale": "eccesso"},
             "ASSE_PROF": {"indirizzo": "0x1080", "n": 13, "dtype": "u16", "endian": "le", "scala": 0.1, "unita": "deg", "segnale": "piega_abs"},
         },
         "tabelle": [], "profili_pneumatico": []}
    ind = 0x2000
    for liv in (1, 2, 3):
        S["tabelle"].append({"id": f"DEMO_SOGLIA_SLIP_L{liv}", "nome": f"Soglia slittamento livello {liv}", "gruppo": "Criterio 1 – slittamento",
                             "tipo": "mappa", "indirizzo": hex(ind), "dtype": "u16", "endian": "le", "scala": 0.01, "unita": "%",
                             "righe": 11, "colonne": 12, "asse_x": "ASSE_GIRI", "asse_y": "ASSE_PIEGA", "ordine": "righe",
                             "descrizione": "Slittamento posteriore oltre il quale interviene, in funzione di piega e giri", "verificato": True, "fonte": "demo"})
        ind += 11 * 12 * 2 + 0x40
    S["tabelle"] += [
        {"id": "DEMO_PIEGA_MIN", "nome": "Piega minima di abilitazione", "gruppo": "Criterio 2 – piega", "tipo": "curva",
         "indirizzo": "0x2400", "dtype": "u16", "endian": "le", "scala": 0.1, "unita": "deg", "colonne": 8, "asse_x": "ASSE_V",
         "descrizione": "Sotto questa piega il controllo in piega non lavora", "verificato": True, "fonte": "demo"},
        {"id": "DEMO_GAS_MIN", "nome": "Gas minimo", "gruppo": "Criterio 3 – gas", "tipo": "valore", "indirizzo": "0x2420",
         "dtype": "u16", "endian": "le", "scala": 0.1, "unita": "%", "verificato": True, "fonte": "demo"},
        {"id": "DEMO_SOGLIA_DSLIP", "nome": "Soglia derivata slittamento", "gruppo": "Criterio 4 – derivata", "tipo": "curva",
         "indirizzo": "0x2440", "dtype": "u16", "endian": "le", "scala": 0.1, "unita": "%/s", "colonne": 6, "asse_x": "ASSE_MARCIA",
         "verificato": True, "fonte": "demo"},
        {"id": "DEMO_TAGLIO", "nome": "Taglio di coppia", "gruppo": "Uscita", "tipo": "mappa", "indirizzo": "0x2500",
         "dtype": "u8", "scala": 0.5, "unita": "%", "righe": 11, "colonne": 8, "asse_x": "ASSE_ECCESSO", "asse_y": "ASSE_PIEGA",
         "verificato": True, "fonte": "demo"},
        {"id": "DEMO_PROFILO_POST", "nome": "Profilo pneumatico posteriore", "gruppo": "Pneumatici", "tipo": "curva",
         "indirizzo": "0x2600", "dtype": "u16", "endian": "le", "scala": 0.1, "unita": "mm", "colonne": 13, "asse_x": "ASSE_PROF",
         "descrizione": "Raggio di rotolamento in funzione della piega", "verificato": True, "fonte": "demo"},
        {"id": "DEMO_PROFILO_ANT", "nome": "Profilo pneumatico anteriore", "gruppo": "Pneumatici", "tipo": "curva",
         "indirizzo": "0x2640", "dtype": "u16", "endian": "le", "scala": 0.1, "unita": "mm", "colonne": 13, "asse_x": "ASSE_PROF",
         "verificato": True, "fonte": "demo"},
    ]
    S["profili_pneumatico"] = [
        {"id": "post", "tabella": "DEMO_PROFILO_POST", "ruota": "posteriore", "grandezza": "raggio_mm", "R0_mm": R0_POST,
         "larghezza_mm": 200, "misura": "200/55 ZR17"},
        {"id": "ant", "tabella": "DEMO_PROFILO_ANT", "ruota": "anteriore", "grandezza": "raggio_mm", "R0_mm": R0_ANT,
         "larghezza_mm": 120, "misura": "120/70 ZR17"}]
    return S


def bin_demo(S):
    buf = bytearray(b"\xFF" * 0x10000)
    for nome, ax, sc in (("ASSE_PIEGA", ASSE_PIEGA, 0.1), ("ASSE_GIRI", ASSE_GIRI, 1), ("ASSE_V", ASSE_V, 0.1),
                         ("ASSE_ECCESSO", ASSE_ECCESSO, 0.01), ("ASSE_PROF", ASSE_PROF, 0.1)):
        off = int(S["assi"][nome]["indirizzo"], 16)
        for i, v in enumerate(ax):
            struct.pack_into("<H", buf, off + 2 * i, int(round(v / sc)))
    per = {t["id"]: t for t in S["tabelle"]}
    P = np.array(ASSE_PIEGA, float)[:, None]
    Rg = np.array(ASSE_GIRI, float)[None, :]
    for liv, fatt in ((1, 1.3), (2, 1.0), (3, 0.8)):
        z = fatt * (13.0 - 7.0 * (P / 65) ** 1.3) * (1 + 0.15 * (Rg - 8000) / 6000)
        calib.scrivi_tabella(S, per[f"DEMO_SOGLIA_SLIP_L{liv}"], buf, z)
    calib.scrivi_tabella(S, per["DEMO_PIEGA_MIN"], buf, [[30, 28, 26, 24, 22, 20, 18, 18]])
    calib.scrivi_tabella(S, per["DEMO_GAS_MIN"], buf, [[15.0]])
    calib.scrivi_tabella(S, per["DEMO_SOGLIA_DSLIP"], buf, [[60, 55, 50, 45, 40, 40]])
    E = np.array(ASSE_ECCESSO, float)[None, :]
    calib.scrivi_tabella(S, per["DEMO_TAGLIO"], buf, np.clip(4 * E * (1 + P / 60), 0, 100))
    ph = np.array(ASSE_PROF, float)
    # profili in centralina: un po' diversi da quelli veri (come una gomma diversa dall'originale)
    calib.scrivi_tabella(S, per["DEMO_PROFILO_POST"], buf, [raggio_reale(ph, R0_POST, 104.0)])
    calib.scrivi_tabella(S, per["DEMO_PROFILO_ANT"], buf, [raggio_reale(ph, R0_ANT, 70.0)])
    calib.correggi_checksum(S, buf)
    return buf


MODELLO_DEMO = {
    "nome": "DEMO – taglio coppia in piega a 4 criteri (inventato)",
    "frequenza_hz": 100,
    "parametri": {"livello": 2},
    "ingressi": [
        {"id": "v_ant", "segnale": "v_ant", "unita": "km/h", "descrizione": "velocità ruota anteriore (raggio nominale)"},
        {"id": "v_post", "segnale": "v_post", "unita": "km/h", "descrizione": "velocità ruota posteriore (raggio nominale)"},
        {"id": "piega", "segnale": "piega", "unita": "deg", "descrizione": "angolo di piega IMU"},
        {"id": "giri", "segnale": "giri", "unita": "rpm"},
        {"id": "gas", "segnale": "gas", "unita": "%"},
        {"id": "marcia", "segnale": "marcia", "unita": ""}],
    "blocchi": [
        {"id": "piega_abs", "tipo": "abs", "ingressi": ["piega"], "descrizione": "|piega|: le tabelle usano il valore assoluto"},
        {"id": "piega_f", "tipo": "passabasso", "ingressi": ["piega_abs"], "tau_s": 0.04, "descrizione": "filtro del 1° ordine"},
        {"id": "R_post", "tipo": "tabella", "tabella": "DEMO_PROFILO_POST", "x": "piega_abs", "unita": "mm", "descrizione": "raggio di rotolamento posteriore"},
        {"id": "R_ant", "tipo": "tabella", "tabella": "DEMO_PROFILO_ANT", "x": "piega_abs", "unita": "mm"},
        {"id": "v_post_c", "tipo": "espressione", "espressione": f"v_post * R_post / {R0_POST}", "unita": "km/h", "descrizione": "velocità a terra posteriore corretta col profilo"},
        {"id": "v_ant_c", "tipo": "espressione", "espressione": f"v_ant * R_ant / {R0_ANT}", "unita": "km/h"},
        {"id": "v_rif", "tipo": "passabasso", "ingressi": ["v_ant_c"], "tau_s": 0.05, "unita": "km/h"},
        {"id": "slip", "tipo": "espressione", "espressione": "(v_post_c - v_rif) / max(v_rif, 15) * 100", "unita": "%"},
        {"id": "slip_f", "tipo": "passabasso", "ingressi": ["slip"], "tau_s": 0.03, "unita": "%"},
        {"id": "dslip", "tipo": "derivata", "ingressi": ["slip_f"], "unita": "%/s"},
        {"id": "dslip_f", "tipo": "passabasso", "ingressi": ["dslip"], "tau_s": 0.05, "unita": "%/s"},
        {"id": "soglia_slip", "tipo": "tabella", "tabella": "DEMO_SOGLIA_SLIP_L{livello}", "x": "giri", "y": "piega_f", "unita": "%"},
        {"id": "piega_min", "tipo": "tabella", "tabella": "DEMO_PIEGA_MIN", "x": "v_rif", "unita": "deg"},
        {"id": "gas_min", "tipo": "tabella", "tabella": "DEMO_GAS_MIN", "x": "gas", "unita": "%"},
        {"id": "soglia_dslip", "tipo": "tabella", "tabella": "DEMO_SOGLIA_DSLIP", "x": "marcia", "unita": "%/s"},
        {"id": "eccesso", "tipo": "espressione", "espressione": "max(slip_f - soglia_slip, 0)", "unita": "%"},
        {"id": "taglio_tab", "tipo": "tabella", "tabella": "DEMO_TAGLIO", "x": "eccesso", "y": "piega_f", "unita": "%"}],
    "criteri": [
        {"id": "C1", "nome": "Slittamento oltre soglia", "valore": "slip_f", "soglia": "soglia_slip", "confronto": ">", "isteresi": 0.5, "unita": "%"},
        {"id": "C2", "nome": "Piega oltre il minimo", "valore": "piega_f", "soglia": "piega_min", "confronto": ">", "isteresi": 1.0, "unita": "deg"},
        {"id": "C3", "nome": "Gas aperto", "valore": "gas", "soglia": "gas_min", "confronto": ">", "unita": "%"},
        {"id": "C4", "nome": "Slittamento che cresce in fretta", "valore": "dslip_f", "soglia": "soglia_dslip", "confronto": ">", "unita": "%/s"}],
    "rami": [
        {"id": "R1", "nome": "Ramo slittamento", "condizione": "C1 and C2 and C3"},
        {"id": "R2", "nome": "Ramo derivata", "condizione": "C4 and C2 and C3 and not C1"}],
    "logica": "R1 or R2",
    "uscite": [{"id": "taglio", "blocco": "taglio_tab", "attiva_se": "logica", "unita": "%"}],
    "osservati": [{"id": "tc_attivo", "segnale": "tc_attivo", "confronta_con": "logica"}],
}

PROFILO_DEMO = {
    "moto": "DEMO (dati sintetici)",
    "dbc": "demo.dbc",
    "pista": None,
    "linea": "vmax",
    "canali": {
        "v_ant": {"segnale": "DEMO_Ruote.V_ant", "unita": "km/h", "nome": "velocità ruota anteriore"},
        "v_post": {"segnale": "DEMO_Ruote.V_post", "unita": "km/h", "nome": "velocità ruota posteriore"},
        "giri": {"segnale": "DEMO_Motore.Giri", "unita": "rpm"},
        "gas": {"segnale": "DEMO_Motore.Gas", "unita": "%"},
        "farfalla": {"segnale": "DEMO_Motore.Farfalla", "unita": "%"},
        "marcia": {"segnale": "DEMO_Motore.Marcia", "unita": ""},
        "piega": {"segnale": "DEMO_IMU.Piega", "unita": "deg"},
        "imbardata": {"segnale": "DEMO_IMU.Imbardata", "unita": "deg/s"},
        "tc_livello": {"segnale": "DEMO_Controlli.Livello_TC", "unita": ""},
        "tc_attivo": {"segnale": "DEMO_Controlli.TC_attivo", "unita": ""},
        "taglio_can": {"segnale": "DEMO_Controlli.Taglio_coppia", "unita": "%"},
    },
}


def genera(cartella: str, seme=7):
    from . import model
    os.makedirs(cartella, exist_ok=True)
    sim = simula(seme)
    S = struttura_demo()
    buf = bin_demo(S)
    # la "centralina vera" del demo: il modello con la calibrazione ORIGINALE (profilo pneumatico diverso dalla gomma vera)
    segn = {k: sim[k] for k in ("v_ant", "v_post", "piega", "giri", "gas", "marcia")}
    ris = model.esegui(MODELLO_DEMO, segn, sim["t"], S, bytes(buf))
    tc = ris["logica"]
    taglio = ris["uscite"]["taglio"]
    farfalla = np.clip(sim["gas"] * (1 - taglio / 100), 0, 100)
    t = sim["t"]
    # frame a 50 Hz con un po' di jitter, 4 messaggi sfalsati
    passo = 2
    idx = np.arange(0, len(t), passo)
    n = len(idx)
    fr = []
    jit = np.random.default_rng(seme).normal(0, 0.0003, (4, n))
    fr.append((t[idx] + 0.0010 + jit[0], 0x0A0, _frame_intel([(sim["v_ant"][idx] / 0.01, 0, 16), (sim["v_post"][idx] / 0.01, 16, 16)], n)))
    fr.append((t[idx] + 0.0035 + jit[1], 0x0B0, _frame_intel([(sim["giri"][idx], 0, 16), (sim["gas"][idx] / 0.5, 16, 8),
                                                              (farfalla[idx] / 0.5, 24, 8), (sim["marcia"][idx], 32, 4)], n)))
    fr.append((t[idx] + 0.0060 + jit[2], 0x0C0, _frame_intel([(sim["piega"][idx] / 0.01, 0, 16), (sim["imbardata"][idx] / 0.01, 16, 16),
                                                              (sim["ax"][idx] / 0.001, 32, 16), (sim["ay"][idx] / 0.001, 48, 16)], n)))
    fr.append((t[idx] + 0.0085 + jit[3], 0x0D0, _frame_intel([(np.full(n, 2), 0, 4), (tc[idx], 4, 1), (taglio[idx] / 0.5, 8, 8)], n)))
    T = np.concatenate([f[0] for f in fr]) + 1762430400.0
    I = np.concatenate([np.full(n, f[1]) for f in fr])
    D = np.concatenate([f[2] for f in fr])
    o = np.argsort(T, kind="stable")
    with open(os.path.join(cartella, "demo_log.candump"), "w", encoding="ascii") as fh:
        for ti, ii, dd in zip(T[o], I[o], D[o]):
            fh.write(f"({ti:.6f}) can0 {ii:03X}#{dd.tobytes().hex().upper()}\n")
    with open(os.path.join(cartella, "demo.dbc"), "w", encoding="ascii") as fh:
        fh.write(DBC_DEMO)
    with open(os.path.join(cartella, "demo_originale.bin"), "wb") as fh:
        fh.write(buf)
    # file "modificato": soglie livello 2 +20 % sopra i 40 gradi, profilo posteriore riportato al vero
    per = {x["id"]: x for x in S["tabelle"]}
    mod = bytearray(buf)
    z = calib.leggi_tabella(S, per["DEMO_SOGLIA_SLIP_L2"], buf)["z"]
    z[np.array(ASSE_PIEGA) >= 40, :] *= 1.2
    calib.scrivi_tabella(S, per["DEMO_SOGLIA_SLIP_L2"], mod, z)
    calib.scrivi_tabella(S, per["DEMO_PROFILO_POST"], mod, [raggio_reale(np.array(ASSE_PROF, float), R0_POST, RC_POST)])
    calib.correggi_checksum(S, mod)
    with open(os.path.join(cartella, "demo_modificato.bin"), "wb") as fh:
        fh.write(mod)
    S["file"]["sha256_originale"] = calib.sha256(bytes(buf))
    for nome, ogg in (("struttura_demo.json", S), ("modello_demo.json", MODELLO_DEMO), ("profilo_demo.json", PROFILO_DEMO)):
        with open(os.path.join(cartella, nome), "w", encoding="utf-8") as fh:
            json.dump(ogg, fh, ensure_ascii=False, indent=1)
    return {"lunghezza_pista_vera": sim["lunghezza_pista"], "frame": int(len(T)), "durata_s": float(t[-1])}
