"""Motore che ricalcola offline la catena di controllo decodificata, campione per campione.

Il modello è un JSON (vedi esempi/modello_demo.json):
{
  "nome": "...", "frequenza_hz": 100,
  "parametri": {"livello": 2},
  "ingressi": [{"id": "piega", "segnale": "piega", "unita": "deg", "descrizione": "..."}],
  "blocchi":  [{"id": "...", "tipo": "...", ...}],          # in qualsiasi ordine: si ordinano da soli
  "criteri":  [{"id": "C1", "nome": "...", "valore": "slip", "soglia": "soglia_slip",
                "confronto": ">", "isteresi": 0.5, "unita": "%"}],
  "rami":     [{"id": "R1", "nome": "...", "condizione": "C1 and C2"}],   # facoltativo
  "logica":   "C1 and C2 and (C3 or C4)",
  "uscite":   [{"id": "taglio", "blocco": "taglio_tab", "attiva_se": "logica"}],
  "osservati":[{"id": "dtc_can", "segnale": "dtc_attivo", "confronta_con": "logica"}]
}

Tipi di blocco:
  costante(valore) | abs | neg | min | max | somma | prodotto | espressione(espressione)
  passabasso(tau_s | alfa) | derivata | rampa(su_per_s, giu_per_s) | satura(min,max)
  tabella(tabella, x, y?)  -> lookup 1D/2D sulla tabella della struttura; nome con {parametro} ammesso
  selettore(condizione, se_vero, se_falso)
  confronto(a, op, b)       -> 0/1
  isteresi(ingresso, on, off)
  conferma(ingresso, t_on_s, t_off_s)  -> antirimbalzo
  ritardo(ingresso, t_s)
Le espressioni sono numpy elemento per elemento: + - * / ** < > <= >= == != and or not,
funzioni abs min max sqrt tan sin cos atan radians degrees clip where sign exp log floor.
"""
from __future__ import annotations

import ast
import re

import numpy as np

from . import calib

_FUNZ = {
    "abs": np.abs, "min": np.minimum, "max": np.maximum, "sqrt": np.sqrt, "tan": np.tan, "sin": np.sin,
    "cos": np.cos, "atan": np.arctan, "atan2": np.arctan2, "radians": np.radians, "degrees": np.degrees,
    "clip": np.clip, "where": np.where, "sign": np.sign, "exp": np.exp, "log": np.log, "floor": np.floor,
    "round": np.round,
}


class ErroreModello(Exception):
    pass


def nomi_in(espressione: str) -> set:
    albero = ast.parse(espressione, mode="eval")
    return {n.id for n in ast.walk(albero) if isinstance(n, ast.Name) and n.id not in _FUNZ}


def valuta(espressione: str, ambiente: dict):
    albero = ast.parse(espressione, mode="eval")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in ambiente:
                return ambiente[n.id]
            if n.id in ("True", "False"):
                return n.id == "True"
            raise ErroreModello(f"nome sconosciuto '{n.id}' in '{espressione}'")
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            op = type(n.op)
            if op is ast.Add: return a + b
            if op is ast.Sub: return a - b
            if op is ast.Mult: return a * b
            if op is ast.Div: return np.divide(a, b)
            if op is ast.Pow: return np.power(a, b)
            if op is ast.Mod: return np.mod(a, b)
            if op is ast.BitAnd: return np.logical_and(a, b)
            if op is ast.BitOr: return np.logical_or(a, b)
            raise ErroreModello(f"operatore non ammesso in '{espressione}'")
        if isinstance(n, ast.UnaryOp):
            a = ev(n.operand)
            if isinstance(n.op, ast.USub): return -a
            if isinstance(n.op, ast.UAdd): return a
            if isinstance(n.op, ast.Not): return np.logical_not(a)
            raise ErroreModello("operatore unario non ammesso")
        if isinstance(n, ast.BoolOp):
            vals = [ev(v) for v in n.values]
            f = np.logical_and if isinstance(n.op, ast.And) else np.logical_or
            out = vals[0]
            for v in vals[1:]:
                out = f(out, v)
            return out
        if isinstance(n, ast.Compare):
            sin = ev(n.left)
            out = True
            for op, dx in zip(n.ops, n.comparators):
                d = ev(dx)
                o = type(op)
                if o is ast.Lt: r = sin < d
                elif o is ast.LtE: r = sin <= d
                elif o is ast.Gt: r = sin > d
                elif o is ast.GtE: r = sin >= d
                elif o is ast.Eq: r = sin == d
                elif o is ast.NotEq: r = sin != d
                else: raise ErroreModello("confronto non ammesso")
                out = np.logical_and(out, r)
                sin = d
            return out
        if isinstance(n, ast.IfExp):
            return np.where(ev(n.test), ev(n.body), ev(n.orelse))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNZ:
            return _FUNZ[n.func.id](*[ev(a) for a in n.args])
        raise ErroreModello(f"costrutto non ammesso in '{espressione}': {ast.dump(n)[:60]}")

    return ev(albero)


def _dipendenze(b: dict) -> set:
    t = b["tipo"]
    dip = set(b.get("ingressi", []))
    for k in ("x", "y", "a", "b", "ingresso", "se_vero", "se_falso"):
        v = b.get(k)
        if isinstance(v, str):
            dip |= nomi_in(v) if re.search(r"[^\w]", v) else {v}
    for k in ("espressione", "condizione"):
        if k in b:
            dip |= nomi_in(b[k])
    return dip


def ordina(modello: dict) -> list:
    blocchi = {b["id"]: b for b in modello.get("blocchi", [])}
    noti = {i["id"] for i in modello.get("ingressi", [])} | set(modello.get("parametri", {}))
    fatto, ordine = set(noti), []
    rimasti = dict(blocchi)
    while rimasti:
        progresso = False
        for bid, b in list(rimasti.items()):
            dip = _dipendenze(b) - {"t", "dt"}
            if dip <= fatto:
                ordine.append(b)
                fatto.add(bid)
                del rimasti[bid]
                progresso = True
        if not progresso:
            mancano = {bid: sorted(_dipendenze(b) - fatto) for bid, b in rimasti.items()}
            raise ErroreModello(f"dipendenze irrisolte o circolari: {mancano}")
    return ordine


def _passabasso(x, alfa):
    y = np.empty_like(x)
    acc = x[0]
    for i, v in enumerate(x):
        acc = acc + alfa * (v - acc)
        y[i] = acc
    return y


def _rampa(x, su, giu):
    y = np.empty_like(x)
    acc = x[0]
    for i, v in enumerate(x):
        d = v - acc
        acc = acc + (min(d, su) if d > 0 else max(d, -giu))
        y[i] = acc
    return y


def _isteresi(x, on, off):
    y = np.zeros(len(x))
    st = False
    for i, v in enumerate(x):
        if not st and v >= on:
            st = True
        elif st and v <= off:
            st = False
        y[i] = st
    return y


def _conferma(x, n_on, n_off):
    y = np.zeros(len(x))
    st, cnt = False, 0
    for i, v in enumerate(x > 0.5):
        if v != st:
            cnt += 1
            if (v and cnt >= n_on) or (not v and cnt >= n_off):
                st, cnt = v, 0
        else:
            cnt = 0
        y[i] = st
    return y


def _confronta(v, s, op):
    return {">": v > s, ">=": v >= s, "<": v < s, "<=": v <= s}[op]


def _margine(v, s, op):
    """Distanza dalla soglia, positiva = criterio NON ancora soddisfatto."""
    return (s - v) if op in (">", ">=") else (v - s)


def esegui(modello: dict, segnali: dict, t: np.ndarray, struttura=None, buf=None, parametri=None) -> dict:
    """segnali: {id_ingresso: array} già ricampionati sulla griglia t.
    Ritorna: {"valori": {id: array}, "criteri": {...}, "rami": {...}, "logica": array, "tabelle_usate": {...}}"""
    par = dict(modello.get("parametri", {}))
    par.update(parametri or {})
    n = len(t)
    dt = float(np.median(np.diff(t))) if n > 1 else 0.01
    env = {"t": t, "dt": dt}
    env.update({k: np.full(n, float(v)) for k, v in par.items()})
    for ing in modello.get("ingressi", []):
        sid = ing["id"]
        if sid not in segnali:
            raise ErroreModello(f"ingresso '{sid}' (segnale {ing.get('segnale')}) assente nei dati")
        env[sid] = np.asarray(segnali[sid], dtype=float)
    tab_per_id = {tb["id"]: tb for tb in (struttura or {}).get("tabelle", [])}
    usate = {}
    for b in ordina(modello):
        bid, tipo = b["id"], b["tipo"]
        ins = [env[i] for i in b.get("ingressi", [])]

        def arg(k):
            v = b[k]
            if isinstance(v, (int, float)):
                return np.full(n, float(v))
            return env[v] if v in env else valuta(v, env)

        if tipo == "costante":
            out = np.full(n, float(b["valore"]))
        elif tipo == "abs":
            out = np.abs(ins[0])
        elif tipo == "neg":
            out = -ins[0]
        elif tipo == "min":
            out = np.minimum.reduce(ins)
        elif tipo == "max":
            out = np.maximum.reduce(ins)
        elif tipo == "somma":
            out = np.sum(ins, axis=0)
        elif tipo == "prodotto":
            out = np.prod(ins, axis=0)
        elif tipo == "espressione":
            out = valuta(b["espressione"], env)
        elif tipo == "passabasso":
            alfa = b.get("alfa")
            if alfa is None:
                tau = float(b["tau_s"])
                alfa = dt / (tau + dt)
            out = _passabasso(ins[0], float(alfa))
        elif tipo == "derivata":
            out = np.gradient(ins[0], t)
        elif tipo == "rampa":
            out = _rampa(ins[0], float(b["su_per_s"]) * dt, float(b["giu_per_s"]) * dt)
        elif tipo == "satura":
            out = np.clip(ins[0], b.get("min", -np.inf), b.get("max", np.inf))
        elif tipo == "tabella":
            nome = b["tabella"].format(**{k: int(v) if float(v).is_integer() else v for k, v in par.items()})
            if nome not in tab_per_id or buf is None:
                raise ErroreModello(f"blocco {bid}: tabella '{nome}' non disponibile (serve struttura + file .bin)")
            letta = calib.leggi_tabella(struttura, tab_per_id[nome], buf)
            xv = arg("x")
            if tab_per_id[nome].get("tipo") == "curva":
                out = calib.lookup1d(letta["x"].valori, letta["z"][0], xv)
                usate[bid] = {"tabella": nome, "x": xv}
            elif tab_per_id[nome].get("tipo") == "valore":
                out = np.full(n, float(letta["z"][0, 0]))
                usate[bid] = {"tabella": nome}
            else:
                yv = arg("y")
                out = calib.lookup2d(letta["x"].valori, letta["y"].valori, letta["z"], xv, yv)
                usate[bid] = {"tabella": nome, "x": xv, "y": yv}
        elif tipo == "selettore":
            out = np.where(valuta(b["condizione"], env) > 0, arg("se_vero"), arg("se_falso"))
        elif tipo == "confronto":
            out = _confronta(arg("a"), arg("b"), b["op"]).astype(float)
        elif tipo == "isteresi":
            out = _isteresi(arg("ingresso"), float(b["on"]), float(b["off"]))
        elif tipo == "conferma":
            out = _conferma(arg("ingresso"), max(1, int(round(b.get("t_on_s", 0) / dt))),
                            max(1, int(round(b.get("t_off_s", 0) / dt))))
        elif tipo == "ritardo":
            k = int(round(float(b["t_s"]) / dt))
            x = arg("ingresso")
            out = np.concatenate([np.full(k, x[0]), x[:-k]]) if k > 0 else x
        else:
            raise ErroreModello(f"tipo di blocco sconosciuto: {tipo}")
        env[bid] = np.asarray(out, dtype=float) * np.ones(n)

    criteri = {}
    for c in modello.get("criteri", []):
        v = env[c["valore"]] if c["valore"] in env else valuta(c["valore"], env)
        s = env[c["soglia"]] if isinstance(c["soglia"], str) and c["soglia"] in env else (
            np.full(n, float(c["soglia"])) if not isinstance(c["soglia"], str) else valuta(c["soglia"], env))
        op = c.get("confronto", ">")
        ist = float(c.get("isteresi", 0.0))
        if ist:
            # entra quando supera la soglia, esce quando torna indietro di 'isteresi'
            m = _margine(v, s, op)
            att = _isteresi(-m, 0.0 if op in (">", "<") else -1e-12, -ist)
        else:
            att = _confronta(v, s, op).astype(float)
        m = _margine(v, s, op)
        scala = float(c.get("scala") or (np.nanpercentile(np.abs(s), 90) or 1.0))
        criteri[c["id"]] = {"valore": v, "soglia": s, "margine": m, "margine_rel": m / scala, "attivo": att}
        env[c["id"]] = att
    rami = {}
    for r in modello.get("rami", []):
        rami[r["id"]] = valuta(r["condizione"], env).astype(float)
        env[r["id"]] = rami[r["id"]]
    logica = valuta(modello["logica"], env).astype(float) if modello.get("logica") else np.zeros(n)
    env["logica"] = logica
    uscite = {}
    for u in modello.get("uscite", []):
        val = env[u["blocco"]]
        if u.get("attiva_se"):
            val = np.where(valuta(u["attiva_se"], env) > 0, val, u.get("valore_riposo", 0.0))
        uscite[u["id"]] = val
        env[u["id"]] = val
    return {"valori": {k: v for k, v in env.items() if isinstance(v, np.ndarray) and v.shape == (n,)},
            "criteri": criteri, "rami": rami, "logica": logica, "uscite": uscite, "tabelle_usate": usate,
            "ordine": [b["id"] for b in ordina(modello)]}


def confronto_osservati(modello: dict, ris: dict, segnali: dict, t) -> list:
    """Concordanza tra la previsione del modello e ciò che la centralina ha fatto davvero (dal CAN)."""
    out = []
    for o in modello.get("osservati", []):
        if o["id"] not in segnali:
            continue
        oss = np.asarray(segnali[o["id"]]) > o.get("soglia", 0.5)
        prev = ris["valori"].get(o.get("confronta_con", "logica"), ris["logica"]) > 0.5
        tp = int(np.sum(oss & prev)); fp = int(np.sum(~oss & prev)); fn = int(np.sum(oss & ~prev))
        out.append({"id": o["id"], "campioni_osservati": int(oss.sum()), "campioni_previsti": int(prev.sum()),
                    "entrambi": tp, "solo_modello": fp, "solo_centralina": fn,
                    "concordanza": tp / max(1, tp + fp + fn)})
    return out
