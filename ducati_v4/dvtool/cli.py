"""Riga di comando:  python -m dvtool <comando> ...   (su Windows anche:  py -m dvtool ...)

Comandi principali
  demo        crea i dati sintetici di prova e (opzionale) apre il visualizzatore
  can         inventario | decodifica | verifica   sui log CAN grezzi
  giri        stima i giri senza GPS
  sessione    log -> file di sessione per il visualizzatore (giri + catena di controllo + protocollo)
  calib       elenco | mostra | confronta | applica | checksum | cerca-checksum   sul file della centralina
  pacchetto   crea | apri | verifica   per portare i dati da un PC all'altro
  cronometro  stato | prepara | registra | ferma | scarica | ripristina   per la scatola H3D Chrono (R9/CM4)
  visualizza  avvia il visualizzatore nel browser (server locale, nessuna installazione)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np


def _json(x):
    print(json.dumps(x, indent=1, ensure_ascii=False, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))


def _carica_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_demo(a):
    from . import synth, sessione
    out = a.out
    info = synth.genera(out)
    prof = _carica_json(os.path.join(out, "profilo_demo.json"))
    mod = _carica_json(os.path.join(out, "modello_demo.json"))
    S = _carica_json(os.path.join(out, "struttura_demo.json"))
    with open(os.path.join(out, "demo_originale.bin"), "rb") as f:
        buf = f.read()
    s = sessione.crea(os.path.join(out, "demo_log.candump"), prof, out, mod, S, buf)
    sessione.salva(s, os.path.join(out, "sessione_demo.json.gz"))
    _scrivi_progetto(out, struttura="struttura_demo.json", modello="modello_demo.json",
                     sessioni=["sessione_demo.json.gz"], originale="demo_originale.bin", modificato="demo_modificato.bin",
                     nome="DEMO – dati sintetici")
    print(f"Demo creata in {out}: {info['frame']} frame CAN, {info['durata_s']:.0f} s, pista {info['lunghezza_pista_vera']:.0f} m")
    for n in s["meta"]["note"]:
        print("  -", n)
    if a.apri:
        from . import server
        server.avvia(out, porta=a.porta)


def _scrivi_progetto(cartella, **kw):
    p = os.path.join(cartella, "progetto.json")
    dati = _carica_json(p) if os.path.exists(p) else {}
    for k, v in kw.items():
        if v is not None:
            dati[k] = v
    with open(p, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=1)


def cmd_can(a):
    from . import canlog, protocollo
    from . import dbc as dbcmod
    log = canlog.leggi(a.log, a.tabella)
    print(f"{len(log)} frame, {log.t[-1]-log.t[0]:.1f} s, origine {log.origine} {log.note}", file=sys.stderr)
    if a.azione == "inventario":
        inv = log.inventario()
        if a.json:
            _json(inv)
        else:
            print(f"{'ID':>7} {'frame':>8} {'Hz':>7} {'periodo':>8} {'DLC':>6}  byte variabili   esempio")
            for x in inv:
                print(f"{x['id_hex']:>7} {x['frame']:>8} {x['hz']:7.1f} {x['periodo_ms_mediano'] or 0:8.1f} {str(x['dlc']):>6}  "
                      f"{str(x['byte_variabili']):<16} {x['esempio']}")
        return
    db = dbcmod.carica_dbc(a.dbc)
    if a.azione == "decodifica":
        from . import sessione
        dec = dbcmod.decodifica(db, log.t, log.id, log.data)
        f = a.frequenza
        tg = np.arange(log.t[0], log.t[-1], 1.0 / f)
        ric = sessione.ricampiona(dec, db, tg)
        nomi = sorted(ric)
        with open(a.csv, "w", encoding="utf-8") as fh:
            fh.write("t;" + ";".join(nomi) + "\n")
            for i in range(len(tg)):
                fh.write(f"{tg[i]-tg[0]:.3f};" + ";".join(f"{ric[n][i]:.6g}" for n in nomi) + "\n")
        print(f"scritto {a.csv}: {len(tg)} righe x {len(nomi)} segnali a {f} Hz")
    elif a.azione == "verifica":
        prof = _carica_json(a.profilo) if a.profilo else {}
        r = protocollo.verifica(log, db, prof.get("canali", {}))
        md = protocollo.in_markdown(r)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.write(md)
            print(f"rapporto in {a.out}")
        print(r["giudizio"])


def cmd_giri(a):
    from . import canlog, laps, sessione
    from . import dbc as dbcmod
    prof = _carica_json(a.profilo)
    base = os.path.dirname(os.path.abspath(a.profilo))
    log = canlog.leggi(a.log, a.tabella)
    db = dbcmod.carica_dbc(os.path.join(base, prof["dbc"]) if not os.path.isabs(prof["dbc"]) else prof["dbc"])
    dec = dbcmod.decodifica(db, log.t, log.id, log.data)
    tg = np.arange(log.t[0], log.t[-1], 0.01)
    lg = sessione.canali_logici(prof, sessione.ricampiona(dec, db, tg))
    v = laps.velocita_riferimento(lg.get("v_ant", lg.get("v_post")), lg.get("v_post"))
    if "piega" in lg:
        pa = prof.get("pneumatico_ant", {})
        v = laps.correggi_piega(v, lg["piega"], pa.get("R0_mm", 300.0), pa.get("r_corona_mm", 60.0))
    pista = a.pista or prof.get("pista")
    if pista and str(pista).replace(".", "").isdigit():
        pista = float(pista)
    r = laps.stima_giri(tg, v, piega=lg.get("piega"), imbardata=lg.get("imbardata"), lunghezza_nominale=pista,
                        linea=a.linea, linea_offset_m=a.offset, t_traguardo=a.t_traguardo)
    for n in r.note:
        print("-", n)
    print(f"\n{'giro':>4} {'tipo':<9} {'tempo':>10} {'distanza m':>10} {'qualità':>7}")
    migliore = min((g.tempo for g in r.giri if g.tipo == "lanciato"), default=None)
    for g in r.giri:
        m, s = divmod(g.tempo, 60)
        segno = "  <- migliore" if migliore is not None and g.tempo == migliore else ""
        print(f"{g.numero:>4} {g.tipo:<9} {int(m):>3}:{s:06.3f} {g.distanza:>10.1f} {g.qualita:7.2f}{segno}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(r.dict(), fh, ensure_ascii=False, indent=1)


def cmd_sessione(a):
    from . import sessione
    prof = _carica_json(a.profilo)
    base = os.path.dirname(os.path.abspath(a.profilo))
    mod = _carica_json(a.modello) if a.modello else None
    S = _carica_json(a.struttura) if a.struttura else None
    buf = None
    if a.bin:
        with open(a.bin, "rb") as f:
            buf = f.read()
    par = json.loads(a.parametri) if a.parametri else None
    s = sessione.crea(a.log, prof, base, mod, S, buf, a.frequenza, a.tabella, par, a.pista)
    sessione.salva(s, a.out)
    for n in s["meta"]["note"]:
        print("-", n)
    if s.get("giri"):
        lanc = [g for g in s["giri"]["giri"] if g["tipo"] == "lanciato"]
        print(f"giri lanciati: {len(lanc)}; migliore: {min((g['tempo'] for g in lanc), default=0):.3f} s")
    if s.get("modello"):
        for c in s["modello"]["criteri"]:
            print(f"criterio {c['id']} ({c['nome']}): soddisfatto {c['percentuale_attivo']:.1f}% del tempo")
        for o in s["modello"]["osservati"]:
            print(f"concordanza modello/centralina su {o['id']}: {o['concordanza']*100:.1f}%")
    print(f"scritto {a.out}")


def cmd_calib(a):
    from . import calib
    S = _carica_json(a.struttura)
    if a.azione == "elenco":
        buf = open(a.bin, "rb").read() if a.bin else None
        for r in calib.elenco(S, buf):
            mm = f"  [{r['min']:.4g} .. {r['max']:.4g}]" if "min" in r else ""
            print(f"{r['id']:<28} {r['tipo']:<6} {r['dim']:>6} @{r['indirizzo']:<10} {r['dtype']:<4} {r['unita']:<6}"
                  f"{'' if r['verificato'] else ' (da verificare)'}{mm}  {r['nome']}")
    elif a.azione == "mostra":
        buf = open(a.bin, "rb").read()
        tab = next(t for t in S["tabelle"] if t["id"] == a.tabella)
        r = calib.leggi_tabella(S, tab, buf)
        np.set_printoptions(linewidth=200, precision=3, suppress=True)
        if r["x"] is not None:
            print("x:", r["x"].valori, r["x"].unita)
        if r["y"] is not None:
            print("y:", r["y"].valori, r["y"].unita)
        print(r["z"])
    elif a.azione == "confronta":
        A = open(a.bin, "rb").read()
        B = open(a.altro, "rb").read()
        _json(calib.confronta(S, A, B))
    elif a.azione == "applica":
        buf = open(a.bin, "rb").read()
        patch = _carica_json(a.patch)
        out, avvisi = calib.applica_patch(S, buf, patch, correggi_cs=not a.no_checksum)
        with open(a.out, "wb") as f:
            f.write(out)
        for x in avvisi:
            print("!", x)
        for r in calib.verifica_checksum(S, bytes(out)):
            print(f"checksum {r['id']}: {'OK' if r['ok'] else 'ERRATO'} (0x{r['calcolato']:X})")
        print(f"scritto {a.out} sha256 {calib.sha256(bytes(out))}")
    elif a.azione == "checksum":
        buf = bytearray(open(a.bin, "rb").read())
        for r in calib.verifica_checksum(S, bytes(buf)):
            print(f"{r['id']}: salvato 0x{r['salvato']:X} calcolato 0x{r['calcolato']:X} -> {'OK' if r['ok'] else 'ERRATO'}")
        if a.correggi:
            calib.correggi_checksum(S, buf)
            with open(a.out or a.bin, "wb") as f:
                f.write(buf)
            print("checksum corretti e file scritto")
    elif a.azione == "cerca-checksum":
        from . import checksum as cks
        buf = open(a.bin, "rb").read()
        da, a_ = int(a.da, 0), int(a.a, 0)
        for r in cks.cerca(buf, da, a_)[:50]:
            print(r)


def cmd_pacchetto(a):
    from . import pacchetto
    if a.azione == "crea":
        voci = []
        if a.raccolta:
            voci += _carica_json(a.raccolta)["voci"]
        voci += [{"da": f, "in": a.cartella or ""} for f in (a.file or [])]
        m = pacchetto.crea(voci, a.out, a.nota or "")
        print(f"{a.out}: {len(m['file'])} file, {sum(f['byte'] for f in m['file'])/1e6:.1f} MB")
        for x in m["non_trovati"]:
            print("! non trovato:", x)
    elif a.azione == "verifica":
        _json(pacchetto.verifica(a.zip))
    elif a.azione == "apri":
        r = pacchetto.apri(a.zip, a.dest, a.sovrascrivi)
        print(f"scritti {len(r['scritti'])} file in {a.dest}")
        for x in r["diversi_non_sovrascritti"]:
            print("! già presente e diverso (non sovrascritto, usa --sovrascrivi):", x)


def cmd_cronometro(a):
    from . import cronometro
    cronometro.cli(a)


def cmd_visualizza(a):
    from . import server
    server.avvia(a.cartella, porta=a.porta, apri_browser=not a.no_browser)


def main(argv=None):
    p = argparse.ArgumentParser(prog="dvtool", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)

    d = sp.add_parser("demo", help="dati sintetici di prova")
    d.add_argument("--out", default="esempi/demo")
    d.add_argument("--apri", action="store_true", help="apre subito il visualizzatore")
    d.add_argument("--porta", type=int, default=8765)
    d.set_defaults(f=cmd_demo)

    c = sp.add_parser("can", help="log CAN grezzi")
    c.add_argument("azione", choices=["inventario", "decodifica", "verifica"])
    c.add_argument("log")
    c.add_argument("--dbc")
    c.add_argument("--profilo", help="profilo moto (per i controlli fisici)")
    c.add_argument("--tabella", help="tabella SQLite da usare se ce n'è più d'una")
    c.add_argument("--csv", default="decodificato.csv")
    c.add_argument("--frequenza", type=float, default=50)
    c.add_argument("--out", help="rapporto markdown (verifica)")
    c.add_argument("--json", action="store_true")
    c.set_defaults(f=cmd_can)

    g = sp.add_parser("giri", help="stima giri senza GPS")
    g.add_argument("log")
    g.add_argument("--profilo", required=True)
    g.add_argument("--pista", help="nome (es. vallelunga) o lunghezza in metri")
    g.add_argument("--linea", choices=["vmax", "frenata"], default="vmax")
    g.add_argument("--offset", type=float, default=0.0, help="sposta la linea di N metri (negativo = prima)")
    g.add_argument("--t-traguardo", type=float, dest="t_traguardo", help="istante (s, tempo del log) di un passaggio noto")
    g.add_argument("--tabella")
    g.add_argument("--json")
    g.set_defaults(f=cmd_giri)

    s = sp.add_parser("sessione", help="crea il file di sessione per il visualizzatore")
    s.add_argument("log")
    s.add_argument("--profilo", required=True)
    s.add_argument("--modello")
    s.add_argument("--struttura")
    s.add_argument("--bin", help="file della centralina con cui ricalcolare (originale o modificato)")
    s.add_argument("--parametri", help='JSON, es. \'{"livello": 3}\'')
    s.add_argument("--frequenza", type=float)
    s.add_argument("--pista")
    s.add_argument("--tabella")
    s.add_argument("--out", default="sessione.json.gz")
    s.set_defaults(f=cmd_sessione)

    k = sp.add_parser("calib", help="file della centralina")
    k.add_argument("azione", choices=["elenco", "mostra", "confronta", "applica", "checksum", "cerca-checksum"])
    k.add_argument("--struttura", required=True)
    k.add_argument("--bin")
    k.add_argument("--altro", help="secondo file per 'confronta'")
    k.add_argument("--tabella")
    k.add_argument("--patch")
    k.add_argument("--out")
    k.add_argument("--correggi", action="store_true")
    k.add_argument("--no-checksum", action="store_true")
    k.add_argument("--da", default="0x0")
    k.add_argument("--a", default="0x0")
    k.set_defaults(f=cmd_calib)

    t = sp.add_parser("pacchetto", help="trasferimento dati tra PC")
    t.add_argument("azione", choices=["crea", "apri", "verifica"])
    t.add_argument("zip", nargs="?")
    t.add_argument("--raccolta")
    t.add_argument("--file", nargs="*")
    t.add_argument("--cartella", help="sottocartella nel pacchetto per i --file")
    t.add_argument("--nota")
    t.add_argument("--out", default="ducati_v4_trasferimento.zip")
    t.add_argument("--in", dest="dest", default="privato")
    t.add_argument("--sovrascrivi", action="store_true")
    t.set_defaults(f=cmd_pacchetto)

    r = sp.add_parser("cronometro", help="scatola H3D Chrono (R9) usata come registratore")
    r.add_argument("azione", choices=["stato", "installa", "prepara", "registra", "ferma", "elenco", "scarica",
                                      "ripristina", "pacchetto", "tabelle", "autorizza"])
    r.add_argument("--scatola", help="r9 | cm4 (default dal file privato/cronometro.json, altrimenti r9)")
    r.add_argument("--host", default=os.environ.get("H3D_HOST"), help="IP della scatola (USB o hotspot)")
    r.add_argument("--utente", default=os.environ.get("H3D_UTENTE", "pi"))
    r.add_argument("--config")
    r.add_argument("--python", action="store_true", help="usa registratore_can.py anche se c'è candump")
    r.add_argument("--si", action="store_true", help="non chiedere conferma")
    r.add_argument("--sessione", help="id/nome della sessione da scaricare (default: l'ultima)")
    r.add_argument("--file", help="file .r9session/.db (per 'tabelle') o chiave .pub (per 'autorizza')")
    r.add_argument("--dest", default="privato/acquisizioni")
    r.set_defaults(f=cmd_cronometro)

    v = sp.add_parser("visualizza", help="apre il visualizzatore")
    v.add_argument("cartella", nargs="?", default=".")
    v.add_argument("--porta", type=int, default=8765)
    v.add_argument("--no-browser", action="store_true")
    v.set_defaults(f=cmd_visualizza)

    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
