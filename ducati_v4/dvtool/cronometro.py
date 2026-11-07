"""Scatola H3D Chrono (R9 o CM4) usata SOLO come registratore CAN sulla Ducati.

Usa gli strumenti già presenti su Windows 10/11 e Linux: `ssh` e `scp` (OpenSSH), più urllib per l'API.
Niente viene installato né cancellato sulla scatola e il software della R9 non viene toccato (vedi op_*).
I comandi che cambiano lo stato del momento (prepara, registra, ferma, ripristina) chiedono conferma.

Fatti dalle sessioni precedenti (da ricontrollare sulla scatola che porti in pista):
  * R9:  hostname r9-yccu, Pi Zero 2 W + Waveshare 2-CH CAN HAT+, utente yccu, USB 169.254.55.1,
         sull'hotspot del telefono l'ultimo ottetto è .206; bus moto = can1; candump NON installato;
         sudo chiede la password.
  * CM4: hostname h3d-cm4, USB 169.254.59.1, candump presente, sudo senza password;
         usata sulla Streetfighter V4 il 31/10 con can1 in listen-only a 500 kbit/s.
  * API r9-app sulla porta 8770, intestazione X-R9-Token (token in app_data/config/token);
         GET /api/health, GET /api/v1/sessions/{id}/package[/info]. Il CAN grezzo NON passa dall'API.
  * Senza GPS i tempi dei registratori r9-can sono solo monotoni: per questo qui si registra in formato
         candump -L (tempo di sistema), come nella prova SFV4.

Configurazione: privato/cronometro.json (se manca si usano i valori sotto).
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import urllib.request

PREDEFINITI = {
    "scatole": {
        "r9": {"host": "169.254.55.1", "utente": "yccu", "bus": "can1", "bitrate": 500000,
               "progetto": "/home/yccu/projects/yccu-peer", "porta_api": 8770,
               # i registratori r9 riconfigurano can1 da soli (500k, listen-only OFF): vanno fermati
               "candump": False, "servizi_da_fermare": ["r9-can-correlation", "r9-can"]},
        "cm4": {"host": "169.254.59.1", "utente": "yccu", "bus": "can1", "bitrate": 500000,
                "progetto": "/home/yccu/projects/yccu-peer", "porta_api": 8770,
                "candump": True, "servizi_da_fermare": ["h3d-guardiano-cronometro", "h3d-cronometro"]},
    },
    "scatola": "r9",
    "cartella_catture": "catture_ducati",
}

QUI = os.path.dirname(os.path.abspath(__file__))


def configurazione(percorso=None):
    cfg = json.loads(json.dumps(PREDEFINITI))
    p = percorso or os.path.join(os.path.dirname(QUI), "privato", "cronometro.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            utente = json.load(f)
        for k, v in utente.items():
            if k == "scatole":
                for nome, sc in v.items():
                    cfg["scatole"].setdefault(nome, {}).update(sc)
            else:
                cfg[k] = v
    return cfg


class Scatola:
    def __init__(self, cfg, nome=None, host=None, utente=None):
        self.nome = nome or cfg["scatola"]
        self.c = dict(cfg["scatole"][self.nome])
        if host:
            self.c["host"] = host
        if utente:
            self.c["utente"] = utente
        self.cartella = cfg.get("cartella_catture", "catture_ducati")

    @property
    def dest(self):
        return f"{self.c['utente']}@{self.c['host']}"

    def ssh(self, comando, interattivo=False, controlla=True):
        args = ["ssh", "-o", "ConnectTimeout=8", "-o", f"HostKeyAlias={self.c['host']}"]
        args += ["-t"] if interattivo else ["-o", "BatchMode=yes"]
        args += [self.dest, comando]
        if interattivo:
            return subprocess.run(args).returncode
        r = subprocess.run(args, capture_output=True, text=True)
        if controlla and r.returncode != 0:
            raise RuntimeError(f"ssh fallito ({r.returncode}): {r.stderr.strip()}")
        return r.stdout

    def scp_da(self, remoto, locale):
        args = ["scp", "-o", "ConnectTimeout=8", "-o", f"HostKeyAlias={self.c['host']}", "-o", "BatchMode=yes",
                f"{self.dest}:{remoto}", locale]
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"scp fallito: {r.stderr.strip()}")

    def scp_a(self, locale, remoto):
        args = ["scp", "-o", "ConnectTimeout=8", "-o", f"HostKeyAlias={self.c['host']}", "-o", "BatchMode=yes",
                locale, f"{self.dest}:{remoto}"]
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"scp fallito: {r.stderr.strip()}")

    def api(self, percorso, token=None, timeout=5):
        url = f"http://{self.c['host']}:{self.c['porta_api']}{percorso}"
        req = urllib.request.Request(url, headers={"X-R9-Token": token} if token else {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def token(self):
        t = os.environ.get("H3D_TOKEN")
        if t:
            return t.strip()
        return self.ssh(f"cat {shlex.quote(self.c['progetto'])}/app_data/config/token").strip()


def _conferma(domanda, a):
    if getattr(a, "si", False):
        return True
    r = input(f"{domanda} [s/N] ").strip().lower()
    return r in ("s", "si", "sì", "y", "yes")


def _sha_locale(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- operazioni (usate dalla Guida e dalla riga di comando)
# Sulla scatola NON si installa nulla e non si cambia nulla in modo permanente:
#   * il registratore è una copia temporanea in /tmp (sparisce allo spegnimento);
#   * i servizi R9 che usano can1 vengono solo FERMATI (non disattivati) e rimessi com'erano da "ripristina";
#   * can1 in listen-only è un'impostazione del momento: allo spegnimento torna come la imposta la R9;
#   * resta solo la cartella dati ~/catture_ducati con le catture.
NOME_REG = "dvtool_registratore.py"
# il registratore si riconosce dal suo PID salvato (non con pgrep -f: la shell che esegue il comando via ssh
# contiene lo stesso nome nella sua riga di comando e verrebbe scambiata per il registratore)
_PID = ('P=$(cat "$D/.registratore.pid" 2>/dev/null); VIVO=""; '
        '[ -n "$P" ] && kill -0 "$P" 2>/dev/null && grep -q registratore "/proc/$P/cmdline" 2>/dev/null && VIVO=$P; ')
# ferma il registratore: prima SIGINT, poi SIGTERM se serve (un processo in background può ignorare SIGINT)
_FERMA = (_PID + '[ -n "$VIVO" ] && { kill -INT "$VIVO"; sleep 1.5; ' + _PID +
          '[ -n "$VIVO" ] && { kill -TERM "$VIVO"; sleep 1; }; }; ')


def _ssh(sc: Scatola, comando, ingresso=None, timeout=60):
    args = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", "-o", f"HostKeyAlias={sc.c['host']}",
            "-o", "StrictHostKeyChecking=accept-new", sc.dest, comando]
    try:
        r = subprocess.run(args, input=ingresso, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 255, "", "comando ssh non trovato: su Windows 10/11 attiva «Client OpenSSH» nelle funzionalità facoltative"
    except subprocess.TimeoutExpired:
        return 255, "", "la scatola non risponde (tempo scaduto)"
    return r.returncode, r.stdout, r.stderr


def _spiega_errore_ssh(err: str) -> str:
    e = err.lower()
    if "permission denied" in e:
        return "la scatola ha rifiutato la chiave: autorizza la chiave pubblica di questo PC (passo Impostazioni)"
    if "timed out" in e or "no route" in e or "unreachable" in e or "tempo scaduto" in e or "could not resolve" in e:
        return "scatola non raggiungibile: controlla il cavo USB (o l'hotspot) e l'indirizzo"
    if "host key" in e:
        return "l'impronta della scatola è cambiata rispetto a quella salvata su questo PC"
    return err.strip()[-400:]


def op_stato(sc: Scatola) -> dict:
    bus, cart = sc.c["bus"], sc.cartella
    cmd = (f'D="$HOME/{cart}"; ' + _PID +
           f"echo '#HOST'; hostname; echo '#UP'; uptime -p 2>/dev/null || uptime; "
           f"echo '#CAN'; ip -details link show {bus} 2>&1 | head -6; "
           f"echo '#REG'; [ -n \"$VIVO\" ] && echo \"registratore attivo, PID $VIVO\"; "
           f"echo '#FILE'; ls -l --time-style=+%Y-%m-%d_%H:%M:%S ~/{cart}/*.log 2>/dev/null | awk '{{print $5, $6, $7}}'; "
           f"echo '#DISCO'; df -h ~ | tail -1; "
           f"echo '#SERVIZI'; for s in {' '.join(sc.c.get('servizi_da_fermare', []))}; do echo \"$s $(systemctl is-active $s 2>/dev/null)\"; done; "
           f"echo '#FINE'")
    rc, out, err = _ssh(sc, cmd, timeout=20)
    if rc != 0:
        return {"ok": False, "errore": _spiega_errore_ssh(err), "dest": sc.dest}
    parti, chiave = {}, None
    for riga in out.splitlines():
        if riga.startswith("#"):
            chiave = riga[1:]
            parti[chiave] = []
        elif chiave:
            parti[chiave].append(riga)
    can = "\n".join(parti.get("CAN", []))
    file = []
    for r in parti.get("FILE", []):
        x = r.split()
        if len(x) >= 3:
            file.append({"byte": int(x[0]), "data": x[1], "nome": os.path.basename(x[2])})
    return {"ok": True, "dest": sc.dest, "hostname": " ".join(parti.get("HOST", [])), "acceso_da": " ".join(parti.get("UP", [])),
            "can": can, "listen_only": "LISTEN-ONLY" in can, "can_su": ",UP" in can or "state UP" in can or "UP," in can,
            "registratore": [r for r in parti.get("REG", []) if r.strip()], "catture": file,
            "disco": " ".join(parti.get("DISCO", [])), "servizi": dict(r.split(" ", 1) for r in parti.get("SERVIZI", []) if " " in r)}


def op_prepara(sc: Scatola, password: str = "") -> dict:
    """Ferma (solo per ora) i servizi che usano can1 e lo mette in ascolto passivo a 500 kbit/s."""
    bus, br, cart = sc.c["bus"], sc.c["bitrate"], sc.cartella
    servizi = " ".join(sc.c.get("servizi_da_fermare", []))
    cmd = (f'D="$HOME/{cart}"; mkdir -p "$D"; ATTIVI=""; '
           f'for s in {servizi}; do systemctl is-active --quiet "$s" && ATTIVI="$ATTIVI $s"; done; '
           f'echo "$ATTIVI" > "$D/.servizi_attivi_prima"; '
           f'sudo -S -p "" sh -c "for s in $ATTIVI; do systemctl stop \\$s; done; ip link set {bus} down; '
           f'ip link set {bus} type can bitrate {br} listen-only on; ip link set {bus} up" && '
           f'echo "servizi fermati:$ATTIVI"; ip -details link show {bus} | grep -o LISTEN-ONLY || echo NON_IN_ASCOLTO')
    rc, out, err = _ssh(sc, cmd, ingresso=(password or "") + "\n", timeout=40)
    ok = rc == 0 and "LISTEN-ONLY" in out
    errore = None
    if not ok:
        errore = "password di sudo sbagliata o mancante" if "incorrect password" in err.lower() or "password is required" in err.lower() or "sorry" in err.lower() \
            else (_spiega_errore_ssh(err) if rc == 255 else (err.strip() or out.strip())[-400:])
    return {"ok": ok, "testo": out.strip(), "errore": errore}


def op_registra(sc: Scatola) -> dict:
    """Avvia il registratore da una copia temporanea in /tmp (niente installato), catture in ~/catture_ducati."""
    bus, cart = sc.c["bus"], sc.cartella
    with open(os.path.join(QUI, "registratore_can.py"), "r", encoding="utf-8") as f:
        script = f.read()
    cmd = (f'D="$HOME/{cart}"; mkdir -p "$D"; ' + _PID +
           f'if [ -n "$VIVO" ]; then cat > /dev/null; echo "GIA_ATTIVO PID $VIVO"; else '
           f'cat > /tmp/{NOME_REG}; '
           f'setsid nohup python3 /tmp/{NOME_REG} {bus} "$D" >> "$D/registratore.out" 2>&1 < /dev/null & '
           f'echo $! > "$D/.registratore.pid"; sleep 2; fi; ' + _PID +
           f'[ -n "$VIVO" ] && echo "REGISTRA PID $VIVO" || echo NON_PARTITO; tail -2 "$D/registratore.out"')
    rc, out, err = _ssh(sc, cmd, ingresso=script, timeout=30)
    ok = rc == 0 and "REGISTRA PID" in out
    return {"ok": ok, "testo": out.strip(), "gia_attivo": "GIA_ATTIVO" in out,
            "errore": None if ok else (_spiega_errore_ssh(err) if rc == 255 else out.strip()[-400:])}


def op_ferma(sc: Scatola) -> dict:
    rc, out, err = _ssh(sc, f'D="$HOME/{sc.cartella}"; ' + _FERMA + _PID + '[ -n "$VIVO" ] && echo "ANCORA ATTIVO $VIVO" || echo FERMO', timeout=20)
    return {"ok": rc == 0 and "FERMO" in out, "testo": out.strip(), "errore": None if rc == 0 else _spiega_errore_ssh(err)}


def op_scarica(sc: Scatola, dest: str) -> dict:
    os.makedirs(dest, exist_ok=True)
    rc, out, err = _ssh(sc, f"cd ~/{sc.cartella} 2>/dev/null && sha256sum *.log marcatori.txt 2>/dev/null", timeout=120)
    if rc == 255:
        return {"ok": False, "errore": _spiega_errore_ssh(err), "file": []}
    voci = [r.split(None, 1) for r in out.splitlines() if r.strip()]
    rc2, attivo, _ = _ssh(sc, f'D="$HOME/{sc.cartella}"; ' + _PID + 'echo "$VIVO"', timeout=20)
    esiti = []
    for h, nome in voci:
        nome = nome.strip().lstrip("*")
        locale = os.path.join(dest, nome)
        if os.path.exists(locale) and _sha_locale(locale) == h and nome != "marcatori.txt":
            esiti.append({"nome": nome, "esito": "già scaricato", "ok": True, "byte": os.path.getsize(locale)})
            continue
        try:
            sc.scp_da(f"{sc.cartella}/{nome}", locale)
            ok = _sha_locale(locale) == h
            esiti.append({"nome": nome, "ok": ok, "byte": os.path.getsize(locale),
                          "esito": "scaricato e verificato" if ok else "impronta diversa (in registrazione? riprova dopo averla fermata)"})
        except RuntimeError as e:
            esiti.append({"nome": nome, "ok": False, "esito": str(e)})
    return {"ok": all(e["ok"] for e in esiti), "file": esiti, "dest": os.path.abspath(dest),
            "registrazione_attiva": bool(attivo.strip()), "nota": "sulla scatola non è stato cancellato nulla"}


def op_ripristina(sc: Scatola, password: str = "") -> dict:
    """Ferma il registratore, rimette can1 in modo normale e riavvia SOLO i servizi che erano attivi prima."""
    bus, br, cart = sc.c["bus"], sc.c["bitrate"], sc.cartella
    cmd = (f'D="$HOME/{cart}"; ' + _FERMA +
           f'ATTIVI=$(cat "$D/.servizi_attivi_prima" 2>/dev/null); '
           f'sudo -S -p "" sh -c "ip link set {bus} down; ip link set {bus} type can bitrate {br} listen-only off; '
           f'ip link set {bus} up; for s in $ATTIVI; do systemctl start \\$s; done" && echo "servizi riavviati:$ATTIVI"; '
           f'ip -details link show {bus} | grep -q LISTEN-ONLY && echo ANCORA_IN_ASCOLTO || echo NORMALE')
    rc, out, err = _ssh(sc, cmd, ingresso=(password or "") + "\n", timeout=40)
    ok = rc == 0 and "NORMALE" in out
    errore = None
    if not ok:
        errore = "password di sudo sbagliata o mancante" if "sorry" in err.lower() or "password" in err.lower() \
            else (_spiega_errore_ssh(err) if rc == 255 else (err.strip() or out.strip())[-400:])
    return {"ok": ok, "testo": out.strip(), "errore": errore}


# ---------------------------------------------------------------- riga di comando
def stato(sc: Scatola):
    r = op_stato(sc)
    if not r["ok"]:
        print("!", r["errore"])
        return
    print(f"{r['hostname']} ({r['dest']}) · acceso {r['acceso_da']} · disco {r['disco']}")
    print(r["can"])
    print(">> can1 in LISTEN-ONLY (non disturba il bus della moto)" if r["listen_only"] else ">> can1 NON è in listen-only")
    print("registratore:", r["registratore"] or "fermo")
    print("servizi:", r["servizi"])
    for f in r["catture"]:
        print(f"  {f['nome']}  {f['byte']/1e6:.1f} MB  {f['data']}")


def prepara(sc: Scatola, a):
    print("Ferma per ora i servizi che usano can1 (non li disattiva) e mette can1 in ascolto a 500 kbit/s.")
    print("ATTENZIONE: solo con la scatola collegata alla Ducati. Mai sulla R9: la sua centralina vuole l'ACK della scatola.")
    if not _conferma("Procedo?", a):
        return
    import getpass
    r = op_prepara(sc, getpass.getpass("password di sudo sulla scatola (invio se non serve): "))
    print(r["testo"] if r["ok"] else "! " + str(r["errore"]))


def ripristina(sc: Scatola, a):
    print("Ferma il registratore, rimette can1 normale e riavvia solo i servizi che erano attivi.")
    if not _conferma("Procedo?", a):
        return
    import getpass
    r = op_ripristina(sc, getpass.getpass("password di sudo sulla scatola (invio se non serve): "))
    print(r["testo"] if r["ok"] else "! " + str(r["errore"]))


def registra(sc: Scatola, a):
    if _conferma("Avvio la registrazione (copia temporanea in /tmp, niente installato)?", a):
        r = op_registra(sc)
        print(r["testo"] if r["ok"] else "! " + str(r["errore"]))


def ferma(sc: Scatola, a):
    if _conferma("Fermo la registrazione?", a):
        r = op_ferma(sc)
        print(r["testo"] if r["ok"] else "! " + str(r["errore"]))


def elenco(sc: Scatola):
    stato(sc)


def scarica(sc: Scatola, a):
    r = op_scarica(sc, a.dest)
    if r.get("errore"):
        print("!", r["errore"])
        return
    for f in r["file"]:
        print(f"{'OK' if f['ok'] else '!!'} {f['nome']}: {f['esito']}")
    print(r["nota"])


def autorizza(sc: Scatola, a):
    """Da eseguire dal PC che GIÀ entra nella scatola: aggiunge la chiave pubblica di un altro PC (es. lavoro)."""
    pub = open(a.file, "r", encoding="ascii").read().strip()
    if not pub.startswith(("ssh-ed25519 ", "ssh-rsa ", "ecdsa-")) or "PRIVATE" in pub:
        raise SystemExit("serve il file .pub (chiave PUBBLICA), non la chiave privata")
    print(f"Aggiungo a ~/.ssh/authorized_keys di {sc.dest}:\n  {pub[:60]}...")
    if not _conferma("Procedo?", a):
        return
    q = shlex.quote(pub)
    print(sc.ssh(f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && (grep -qxF {q} ~/.ssh/authorized_keys 2>/dev/null || echo {q} >> ~/.ssh/authorized_keys) "
                 f"&& chmod 600 ~/.ssh/authorized_keys && echo chiave presente"))


def pacchetto(sc: Scatola, a):
    """Scarica una sessione dell'app come .r9session (utile per R9; per la Ducati i canali sono nel CAN grezzo)."""
    tok = sc.token()
    sid = a.sessione
    if not sid:
        sid = sc.ssh(f"ls -1t {shlex.quote(sc.c['progetto'])}/logs/sessions | head -1").strip()
    info = json.loads(sc.api(f"/api/v1/sessions/{sid}/package/info", tok))
    print(json.dumps(info, indent=1)[:800])
    dati = sc.api(f"/api/v1/sessions/{sid}/package?incomplete=1", tok, timeout=120)
    os.makedirs(a.dest, exist_ok=True)
    p = os.path.join(a.dest, f"{sid}.r9session")
    with open(p, "wb") as f:
        f.write(dati)
    print(f"scritto {p} ({len(dati)/1e6:.1f} MB)")


def tabelle(a):
    from . import canlog
    import sqlite3
    import tempfile
    import zipfile
    p = a.file
    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z, tempfile.TemporaryDirectory() as tmp:
            z.extractall(tmp)
            for r, _, fs in os.walk(tmp):
                for fn in fs:
                    q = os.path.join(r, fn)
                    with open(q, "rb") as f:
                        if f.read(16).startswith(b"SQLite format 3"):
                            con = sqlite3.connect(q)
                            print(fn, json.dumps(canlog.tabelle_sqlite(con), indent=1, ensure_ascii=False))
                            con.close()
                    if fn.endswith(".json"):
                        print(fn, open(q, encoding="utf-8", errors="replace").read()[:600])
    else:
        with open(p, "rb") as f:
            if not f.read(16).startswith(b"SQLite format 3"):
                raise SystemExit(f"{p}: non è né un pacchetto .r9session (zip) né un database SQLite")
        con = sqlite3.connect(p)
        print(json.dumps(canlog.tabelle_sqlite(con), indent=1, ensure_ascii=False))


def cli(a):
    if a.azione == "tabelle":
        return tabelle(a)
    cfg = configurazione(getattr(a, "config", None))
    sc = Scatola(cfg, getattr(a, "scatola", None), a.host, a.utente if a.utente != "pi" else None)
    {"stato": lambda: stato(sc), "elenco": lambda: elenco(sc), "scarica": lambda: scarica(sc, a),
     "prepara": lambda: prepara(sc, a), "ripristina": lambda: ripristina(sc, a),
     "registra": lambda: registra(sc, a), "ferma": lambda: ferma(sc, a), "pacchetto": lambda: pacchetto(sc, a),
     "autorizza": lambda: autorizza(sc, a)}[a.azione]()


if __name__ == "__main__":
    print("usa: python -m dvtool cronometro ...", file=sys.stderr)
