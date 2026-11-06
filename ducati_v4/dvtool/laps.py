"""Stima dei giri SENZA GPS, dalla distanza percorsa.

Idea:
  1. distanza s(t) = integrale della velocità ruota (anteriore di default);
  2. "firma" della pista nel dominio della distanza: profilo di velocità v(s) e,
     se c'è l'angolo di piega, curvatura k(s) = g*tan(piega)/v^2 (non dipende da quanto vai forte);
  3. lunghezza effettiva del giro = picco dell'autocorrelazione della firma
     (assorbe l'errore di circonferenza ruota e la traiettoria reale);
  4. giro modello = un giro centrale; la linea del traguardo è un punto del giro modello
     (default: velocità massima del rettilineo, spostabile di N metri);
  5. ogni passaggio sul traguardo = picco di correlazione normalizzata della finestra
     attorno alla linea, cercato lungo tutto lo stint;
  6. mappa della pista ricostruita integrando la direzione: psi' = g*tan(piega)/v (o imbardata).

Tutto in numpy, nessuna dipendenza esterna.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

G = 9.80665

# lunghezze ufficiali (m) di alcune piste, solo come punto di partenza della ricerca
PISTE = {
    "airola": 1240, "vallelunga": 4085, "mugello": 5245, "misano": 4226, "imola": 4909,
    "magione": 2507, "cremona": 3700, "franciacorta": 2519, "varano": 2350, "adria": 2702,
    "monza": 5793, "pergusa": 4950, "binetto": 1577, "tazio_nuvolari": 2805,
}


@dataclass
class Giro:
    numero: int
    t_inizio: float
    t_fine: float
    s_inizio: float
    s_fine: float
    qualita: float              # correlazione al passaggio di fine giro (0..1)
    tipo: str = "lanciato"      # lanciato | uscita | rientro | dubbio

    @property
    def tempo(self):
        return self.t_fine - self.t_inizio

    @property
    def distanza(self):
        return self.s_fine - self.s_inizio

    def dict(self):
        return {"numero": self.numero, "t_inizio": self.t_inizio, "t_fine": self.t_fine,
                "tempo": self.tempo, "distanza": self.distanza, "qualita": self.qualita, "tipo": self.tipo}


@dataclass
class Risultato:
    lunghezza_giro: float
    giri: list
    stint: list
    s: np.ndarray                    # distanza cumulata per campione
    s_giro: np.ndarray               # distanza nel giro (normalizzata alla lunghezza modello), NaN fuori giro
    n_giro: np.ndarray               # numero del giro per campione (-1 fuori)
    mappa_xy: np.ndarray | None      # (M, 2) punti della pista lungo il giro modello
    mappa_ds: float = 2.0
    linea_s_modello: float = 0.0
    note: list = field(default_factory=list)
    curve: list = field(default_factory=list)   # curve del giro modello, distanze dal traguardo

    def dict(self):
        return {
            "lunghezza_giro": self.lunghezza_giro,
            "giri": [g.dict() for g in self.giri],
            "stint": self.stint,
            "mappa_ds": self.mappa_ds,
            "mappa_xy": None if self.mappa_xy is None else np.round(self.mappa_xy, 2).tolist(),
            "curve": self.curve,
            "note": self.note,
        }


def distanza(t, v_kmh):
    v = np.nan_to_num(np.asarray(v_kmh, dtype=np.float64)) / 3.6
    s = np.concatenate([[0.0], np.cumsum(0.5 * (v[1:] + v[:-1]) * np.diff(t))])
    return s


def _pulisci(v, vmax=400.0):
    """Valori impossibili (codici di errore tipo 0xFFFF, negativi) -> interpolati dai vicini."""
    v = np.asarray(v, dtype=np.float64).copy()
    male = ~np.isfinite(v) | (v < -1) | (v > vmax)
    if male.any() and (~male).sum() > 2:
        i = np.arange(len(v))
        v[male] = np.interp(i[male], i[~male], v[~male])
    return np.maximum(v, 0.0)


def correggi_piega(v_kmh, piega_deg, R0_mm=300.0, r_corona_mm=60.0):
    """Il sensore ruota misura la velocità angolare e la moltiplica per il raggio a moto dritta (R0).
    In piega il raggio di rotolamento cala (gomma toroidale): R = R0 - rc*(1-cos(piega)).
    Senza correzione la distanza in curva risulta più lunga del vero di qualche per mille."""
    ph = np.radians(np.abs(np.nan_to_num(piega_deg)))
    return np.asarray(v_kmh, dtype=np.float64) * (1 - (r_corona_mm / R0_mm) * (1 - np.cos(ph)))


def velocita_riferimento(v_ant, v_post=None, v_cruscotto=None):
    """Anteriore di default (slitta meno in accelerazione); dove l'anteriore crolla
    rispetto alla posteriore in frenata (bloccaggio/ABS) si usa il massimo tra le due."""
    v = _pulisci(v_ant)
    if v_post is not None:
        v_post = _pulisci(v_post)
        vp = np.asarray(v_post, dtype=np.float64)
        crollo = (v < 0.85 * vp) & (vp > 20)
        v[crollo] = vp[crollo]
        v = np.where(np.isnan(v), vp, v)
    if v_cruscotto is not None:
        v = np.where(np.isnan(v), v_cruscotto, v)
    return v


def _stint(t, v, soglia=8.0, pausa_s=8.0, min_s=30.0):
    fermo = v < soglia
    out = []
    i = 0
    n = len(t)
    while i < n:
        while i < n and fermo[i]:
            i += 1
        if i >= n:
            break
        j = i
        ultimo_mov = i
        while j < n:
            if not fermo[j]:
                ultimo_mov = j
            elif t[j] - t[ultimo_mov] > pausa_s:
                break
            j += 1
        if t[ultimo_mov] - t[i] > min_s:
            out.append((i, ultimo_mov))
        i = j
    return out


def _liscia(x, n):
    if n <= 1:
        return x
    k = np.ones(n) / n
    pad = np.pad(x, (n // 2, n - 1 - n // 2), mode="edge")
    return np.convolve(pad, k, mode="valid")


def firma(s_griglia, s, v_kmh, piega=None, imbardata=None):
    """Canali della firma nel dominio della distanza, normalizzati (media 0, varianza 1)."""
    v = np.interp(s_griglia, s, v_kmh)
    canali = [v]
    if piega is not None:
        ph = np.radians(np.clip(np.interp(s_griglia, s, piega), -70, 70))
        vv = np.maximum(v / 3.6, 8.0)
        canali.append(G * np.tan(ph) / vv ** 2)
    elif imbardata is not None:
        vv = np.maximum(v / 3.6, 8.0)
        canali.append(np.radians(np.interp(s_griglia, s, imbardata)) / vv)
    out = []
    for c in canali:
        c = _liscia(c, 5)
        sd = np.std(c)
        out.append((c - np.mean(c)) / (sd if sd > 1e-9 else 1.0))
    return np.array(out)


def _autocorr_picco(F, lag_min, lag_max):
    """Picco dell'autocorrelazione normalizzata (media sui canali) tra lag_min e lag_max campioni."""
    n = F.shape[1]
    lag_max = min(lag_max, n - 10)
    if lag_max <= lag_min:
        return None, 0.0
    best = None
    tot = np.zeros(lag_max - lag_min + 1)
    for c in F:
        nf = 1 << int(np.ceil(np.log2(2 * n)))
        X = np.fft.rfft(c, nf)
        ac = np.fft.irfft(X * np.conj(X), nf)[: n]
        ac = ac / (np.arange(n, 0, -1))      # stima non distorta
        ac = ac / ac[0]
        tot += ac[lag_min: lag_max + 1]
    tot /= F.shape[0]
    # primo massimo locale vicino al massimo assoluto: evita di scegliere 2 o 3 giri invece di 1
    gmax = float(np.max(tot))
    loc = [i for i in range(1, len(tot) - 1) if tot[i] >= tot[i - 1] and tot[i] >= tot[i + 1] and tot[i] >= 0.8 * gmax]
    k = loc[0] if loc else int(np.argmax(tot))
    # rifinitura: massimo nell'intorno (+-3 %)
    w = max(2, int(0.03 * (lag_min + k)))
    a0, a1 = max(0, k - w), min(len(tot), k + w + 1)
    k = a0 + int(np.argmax(tot[a0:a1]))
    # interpolazione parabolica
    if 0 < k < len(tot) - 1:
        a, b, c = tot[k - 1], tot[k], tot[k + 1]
        den = a - 2 * b + c
        d = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
    else:
        d = 0.0
    best = lag_min + k + d
    return best, float(tot[k])


def _ncc(segnale, modello):
    """Correlazione normalizzata scorrevole (multi canale): ritorna array lungo n-m+1."""
    C, n = segnale.shape
    m = modello.shape[1]
    if n < m:
        return np.zeros(0)
    tot = np.zeros(n - m + 1)
    for c in range(C):
        x = segnale[c]
        y = modello[c] - modello[c].mean()
        ny = np.sqrt(np.sum(y * y)) or 1.0
        nf = 1 << int(np.ceil(np.log2(n + m)))
        num = np.fft.irfft(np.fft.rfft(x, nf) * np.conj(np.fft.rfft(y, nf)), nf)[: n - m + 1]
        cs = np.concatenate([[0.0], np.cumsum(x)])
        cs2 = np.concatenate([[0.0], np.cumsum(x * x)])
        som = cs[m:] - cs[:-m]
        som2 = cs2[m:] - cs2[:-m]
        var = np.maximum(som2 - som * som / m, 1e-12)
        tot += num / (np.sqrt(var) * ny)
    return tot / C


def _ncc_pesata(segnale, modello, pesi):
    """Come _ncc ma con un peso per canale (somma pesata delle correlazioni dei singoli canali)."""
    tot = None
    for c, w in enumerate(pesi):
        r = _ncc(segnale[c:c + 1], modello[c:c + 1]) * w
        tot = r if tot is None else tot + r
    return tot / sum(pesi)


def _picchi(x, distanza_min, soglia):
    """Massimi locali sopra soglia separati da almeno distanza_min campioni (greedy dal più alto)."""
    ordine = np.argsort(x)[::-1]
    presi = []
    bloccato = np.zeros(len(x), dtype=bool)
    for i in ordine:
        if x[i] < soglia:
            break
        if bloccato[i]:
            continue
        presi.append(i)
        a, b = max(0, i - distanza_min), min(len(x), i + distanza_min + 1)
        bloccato[a:b] = True
    return sorted(presi)


def mappa_pista(L, ds, v_mod, piega_mod=None, imbardata_mod=None):
    """Ricostruisce la forma della pista dal giro modello (senza GPS).
    psi' (per metro) = g*tan(piega)/v^2  oppure imbardata/v. Chiusura forzata a 360 gradi e posizione."""
    vv = np.maximum(v_mod / 3.6, 8.0)
    if piega_mod is not None:
        k = G * np.tan(np.radians(np.clip(piega_mod, -70, 70))) / vv ** 2
    elif imbardata_mod is not None:
        k = np.radians(imbardata_mod) / vv
    else:
        return None
    k = _liscia(k, 7)
    psi = np.concatenate([[0.0], np.cumsum(k[:-1] * ds)])
    tot = psi[-1] + k[-1] * ds
    if abs(tot) > np.pi:  # un giro completo: forza esattamente +-2pi
        psi = psi * (2 * np.pi * np.sign(tot) / tot)
    x = np.concatenate([[0.0], np.cumsum(np.cos(psi[:-1]) * ds)])
    y = np.concatenate([[0.0], np.cumsum(np.sin(psi[:-1]) * ds)])
    # chiusura: togli la deriva lineare in posizione
    ex = x[-1] + np.cos(psi[-1]) * ds
    ey = y[-1] + np.sin(psi[-1]) * ds
    frac = np.arange(len(x)) / len(x)
    x = x - ex * frac
    y = y - ey * frac
    return np.stack([x, y], axis=1)


def trova_curve(ds, v_mod, piega_mod=None, soglia=12.0, unisci_m=40.0, min_m=25.0, piega_positiva="destra", nomi=None):
    """Curve del giro modello, numerate dal traguardo (T1, T2, ...).

    Con la piega: tratti in cui |piega| supera la soglia, con lo stesso verso (una esse = due curve);
    inizio e fine dove la piega scende sotto metà soglia; apice = piega massima.
    Senza piega: minimi di velocità con almeno 15 km/h di calo e di ripresa.
    nomi: lista nell'ordine dal traguardo oppure {"T1": "Curva Grande", ...}."""
    v = np.asarray(v_mod, dtype=float)
    n = len(v)

    def nome(k):
        if isinstance(nomi, dict):
            return nomi.get(f"T{k + 1}", "")
        return nomi[k] if nomi and k < len(nomi) else ""
    out = []
    if piega_mod is not None:
        p = _liscia(np.nan_to_num(np.asarray(piega_mod, dtype=float)), max(3, int(10 / ds)))
        on = np.abs(p) > soglia
        sg = np.sign(p)
        tratti = []
        i = 0
        while i < n:
            if on[i]:
                j = i
                while j < n and on[j] and sg[j] == sg[i]:
                    j += 1
                tratti.append([i, j, sg[i]])
                i = j
            else:
                i += 1
        uniti = []
        for t in tratti:
            if uniti and t[2] == uniti[-1][2] and (t[0] - uniti[-1][1]) * ds < unisci_m:
                uniti[-1][1] = t[1]
            else:
                uniti.append(t)
        uniti = [t for t in uniti if (t[1] - t[0]) * ds >= min_m]
        for k, (a, b, segno) in enumerate(uniti):
            ia = a + int(np.argmax(np.abs(p[a:b])))
            a2, b2 = a, b
            while a2 > 0 and abs(p[a2 - 1]) > soglia * 0.5 and np.sign(p[a2 - 1]) == segno:
                a2 -= 1
            while b2 < n and abs(p[b2]) > soglia * 0.5 and np.sign(p[b2]) == segno:
                b2 += 1
            verso = "destra" if (segno > 0) == (piega_positiva == "destra") else "sinistra"
            out.append({"id": f"T{k + 1}", "nome": nome(k), "inizio": round(a2 * ds, 1), "apice": round(ia * ds, 1),
                        "fine": round(b2 * ds, 1), "verso": verso, "piega_max": round(float(abs(p[ia])), 1),
                        "v_apice": round(float(v[ia]), 1), "v_min": round(float(v[a2:b2].min()), 1)})
    else:
        vs = _liscia(v, max(3, int(20 / ds)))
        minimi = [i for i in range(1, n - 1) if vs[i] <= vs[i - 1] and vs[i] < vs[i + 1]]
        k = 0
        for i in minimi:
            prima = vs[max(0, i - int(300 / ds)): i + 1]
            dopo = vs[i: i + int(300 / ds)]
            if prima.max() - vs[i] < 15 or dopo.max() - vs[i] < 15:
                continue
            a = max(0, i - int(np.argmax(prima[::-1] >= vs[i] + 0.7 * (prima.max() - vs[i]))))
            b = min(n - 1, i + int(np.argmax(dopo >= vs[i] + 0.7 * (dopo.max() - vs[i]))))
            if out and a * ds < out[-1]["fine"]:
                continue
            out.append({"id": f"T{k + 1}", "nome": nome(k), "inizio": round(a * ds, 1), "apice": round(i * ds, 1),
                        "fine": round(b * ds, 1), "verso": "", "piega_max": None, "v_apice": round(float(v[i]), 1),
                        "v_min": round(float(v[i]), 1)})
            k += 1
    return out


def stima_giri(t, v_kmh, piega=None, imbardata=None, lunghezza_nominale=None,
               linea="vmax", linea_offset_m=0.0, t_traguardo=None, ds=2.0,
               soglia_qualita=0.55, peso_curvatura=0.8, curve_opz=None) -> Risultato:
    """Stima i giri.

    t: tempi (s); v_kmh: velocità di riferimento; piega: angolo di piega con segno (gradi) se disponibile.
    lunghezza_nominale: metri (o nome pista in PISTE); se None la cerca tra 800 e 7000 m.
    linea: "vmax" (punto di velocità massima del giro modello) | "frenata" (prima staccata forte dopo vmax)
    linea_offset_m: spostamento della linea rispetto al punto scelto (negativo = prima).
    t_traguardo: se noto, un istante (s) in cui la moto passa sul traguardo: ha la precedenza su 'linea'.
    """
    t = np.asarray(t, dtype=np.float64)
    v = np.nan_to_num(np.asarray(v_kmh, dtype=np.float64))
    note = []
    if isinstance(lunghezza_nominale, str):
        lunghezza_nominale = PISTE.get(lunghezza_nominale.lower().replace(" ", "_"))
    s = distanza(t, v)
    stints = _stint(t, v)
    n = len(t)
    s_giro = np.full(n, np.nan)
    n_giro = np.full(n, -1, dtype=np.int32)
    if not stints:
        return Risultato(0.0, [], [], s, s_giro, n_giro, None, ds, 0.0, ["nessuno stint in movimento"])

    # --- 1. lunghezza del giro dall'autocorrelazione (stint più lungo per primo)
    stime = []
    for (a, b) in sorted(stints, key=lambda ab: s[ab[1]] - s[ab[0]], reverse=True):
        lung = s[b] - s[a]
        g = np.arange(s[a], s[b], ds)
        if len(g) < 200:
            continue
        F = firma(g, s, v, piega, imbardata)
        if lunghezza_nominale:
            lo, hi = 0.88 * lunghezza_nominale, 1.12 * lunghezza_nominale
        else:
            lo, hi = 800.0, min(7000.0, lung / 2.05)
        if lung < 1.9 * lo:
            continue
        lag, val = _autocorr_picco(F, int(lo / ds), int(hi / ds))
        if lag is not None:
            stime.append((lag * ds, val, lung))
    if not stime:
        if lunghezza_nominale:
            L = float(lunghezza_nominale)
            note.append("stint troppo corti per l'autocorrelazione: uso la lunghezza nominale")
        else:
            return Risultato(0.0, [], [], s, s_giro, n_giro, None, ds, 0.0,
                             ["stint troppo corti e lunghezza pista non indicata"])
    else:
        pesi = np.array([max(x[1], 0.01) * x[2] for x in stime])
        L = float(np.sum(pesi * np.array([x[0] for x in stime])) / np.sum(pesi))
        note.append(f"lunghezza giro stimata {L:.1f} m (correlazione {max(x[1] for x in stime):.2f})")
        if lunghezza_nominale:
            note.append(f"rapporto con la nominale {L / lunghezza_nominale:.4f} (errore circonferenza+traiettoria)")

    # --- 2. giro modello: dallo stint più lungo, un giro a metà
    a, b = max(stints, key=lambda ab: s[ab[1]] - s[ab[0]])
    g_all = np.arange(s[a], s[b], ds)
    F_all = firma(g_all, s, v, piega, imbardata)
    nL = int(round(L / ds))
    if len(g_all) >= nL + 10:
        centro = len(g_all) // 2
        i0 = max(0, min(centro - nL // 2, len(g_all) - nL))
        mod = F_all[:, i0: i0 + nL]
        partenze = [g_all[i0]]
        # affina il modello mediando i giri allineati (2 passate)
        for _ in range(2):
            r = _ncc(F_all, mod)
            pk = _picchi(r, int(0.7 * nL), 0.5)
            pezzi = [F_all[:, p: p + nL] for p in pk if p + nL <= F_all.shape[1]]
            if len(pezzi) >= 2:
                mod = np.median(np.array(pezzi), axis=0)
                partenze = [g_all[p] for p in pk if p + nL <= F_all.shape[1]]
    else:
        mod = F_all
        partenze = [g_all[0]]
        note.append("stint più corto di un giro: modello parziale")
    nL = mod.shape[1]

    # profilo velocità e piega del modello in unità fisiche (linea, mappa, curve): mediana dei giri allineati,
    # senza il primo e l'ultimo (uscita e rientro dai box, più lenti) quando i giri sono abbastanza
    if len(partenze) >= 4:
        partenze = partenze[1:-1]
    s_mod0 = partenze[0]

    def _mediana(x):
        if x is None:
            return None
        return np.median(np.array([np.interp(p0 + np.arange(nL) * ds, s, x) for p0 in partenze]), axis=0)
    v_mod = _mediana(v)
    p_mod = _mediana(piega)
    y_mod = _mediana(imbardata)

    # --- 3. posizione della linea nel modello
    if t_traguardo is not None:
        s_line_abs = float(np.interp(t_traguardo, t, s))
        pos = int(round(((s_line_abs - s_mod0) % L) / ds)) % nL
        note.append(f"linea del traguardo dall'istante indicato t={t_traguardo:.2f} s")
    else:
        pos = int(np.argmax(_liscia(v_mod, 15)))
        if linea == "frenata":
            dv = np.gradient(_liscia(v_mod, 9))
            dopo = np.roll(dv, -pos)
            k = np.argmax(dopo < -0.6 * ds)  # calo > 0.6 km/h per metro
            pos = (pos + int(k)) % nL
        pos = (pos + int(round(linea_offset_m / ds))) % nL
    # ruota il modello per avere la linea a metà finestra
    W = max(int(0.35 * nL), 50)
    finestra = np.roll(mod, -(pos - W // 2), axis=1)[:, :W]
    v_mod_r = np.roll(v_mod, -pos)
    p_mod_r = np.roll(p_mod, -pos) if p_mod is not None else None
    y_mod_r = np.roll(y_mod, -pos) if y_mod is not None else None

    # --- 4. passaggi sul traguardo in ogni stint
    giri = []
    num = 1
    stint_info = []
    for (a, b) in stints:
        g = np.arange(s[a], s[b], ds)
        info = {"t_inizio": float(t[a]), "t_fine": float(t[b]), "distanza": float(s[b] - s[a]), "giri": 0}
        if len(g) < W + 5:
            stint_info.append(info)
            continue
        F = firma(g, s, v, piega, imbardata)
        if F.shape[0] > 1 and peso_curvatura is not None:
            # la curvatura non dipende da quanto si va forte: pesa di più per localizzare il passaggio
            Fw = np.concatenate([F[:1] * (1 - peso_curvatura), F[1:] * peso_curvatura])
            fw = np.concatenate([finestra[:1] * (1 - peso_curvatura), finestra[1:] * peso_curvatura])
            r = _ncc_pesata(Fw, fw, [1 - peso_curvatura, peso_curvatura])
        else:
            r = _ncc(F, finestra)
        pk = _picchi(r, int(0.75 * nL), soglia_qualita)
        def fine(p):  # interpolazione parabolica del picco: precisione sotto il passo di griglia
            if 0 < p < len(r) - 1:
                a_, b_, c_ = r[p - 1], r[p], r[p + 1]
                den = a_ - 2 * b_ + c_
                return 0.5 * (a_ - c_) / den if abs(den) > 1e-12 else 0.0
            return 0.0
        s_pass = [g[p] + (W // 2 + fine(p)) * ds for p in pk]
        q_pass = [float(r[p]) for p in pk]
        t_pass = np.interp(s_pass, s, t)
        # uscita box
        if s_pass:
            giri.append(Giro(0, float(t[a]), float(t_pass[0]), float(s[a]), float(s_pass[0]), q_pass[0], "uscita"))
        for k in range(len(s_pass) - 1):
            d = s_pass[k + 1] - s_pass[k]
            tipo = "lanciato" if abs(d / L - 1) < 0.04 else "dubbio"
            giri.append(Giro(num, float(t_pass[k]), float(t_pass[k + 1]), float(s_pass[k]), float(s_pass[k + 1]),
                             min(q_pass[k], q_pass[k + 1]), tipo))
            sel = (s >= s_pass[k]) & (s < s_pass[k + 1])
            s_giro[sel] = (s[sel] - s_pass[k]) * (L / d)
            n_giro[sel] = num
            num += 1
            info["giri"] += 1
        if s_pass:
            giri.append(Giro(-1, float(t_pass[-1]), float(t[b]), float(s_pass[-1]), float(s[b]), q_pass[-1], "rientro"))
        stint_info.append(info)

    mappa = mappa_pista(L, ds, v_mod_r, p_mod_r, y_mod_r)
    if mappa is None:
        note.append("mappa pista non ricostruibile: serve l'angolo di piega o l'imbardata")
    co = curve_opz or {}
    curve = trova_curve(ds, v_mod_r, p_mod_r, soglia=co.get("soglia_piega", 12.0), piega_positiva=co.get("piega_positiva", "destra"),
                        nomi=co.get("nomi"))
    note.append(f"{len(curve)} curve riconosciute nel giro modello" + ("" if p_mod_r is not None else " (dai minimi di velocità: senza piega)"))
    return Risultato(L, giri, stint_info, s, s_giro, n_giro, mappa, ds, 0.0, note, curve)
