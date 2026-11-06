"""Scatola H3D Chrono (R9 o CM4) usata SOLO come registratore CAN sulla Ducati.

Usa gli strumenti già presenti su Windows 10/11 e Linux: `ssh` e `scp` (OpenSSH), più urllib per l'API.
Niente viene cancellato sulla scatola. I comandi che cambiano lo stato della scatola
(prepara, registra, ferma, ripristina, installa) chiedono conferma.

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


def stato(sc: Scatola):
    print(f"scatola '{sc.nome}' {sc.dest}")
    try:
        print("API:", sc.api("/api/health").decode()[:200])
    except Exception as e:  # noqa: BLE001
        print("API non raggiungibile:", e)
    bus = sc.c["bus"]
    out = sc.ssh(f"hostname; uptime; ip -details -statistics link show {bus} 2>&1 | head -20; "
                 f"echo; systemctl list-units --type=service --no-pager --plain 'r9*' 'yccu*' 'h3d*' 'racebox*' 2>/dev/null | head -20; "
                 f"echo; df -h ~ | tail -1; echo; ls -la ~/{sc.cartella} 2>/dev/null | tail -15; "
                 f"echo; pgrep -af registratore_can.py || echo 'registratore fermo'; pgrep -af candump || true", controlla=False)
    print(out)
    if "LISTEN-ONLY" in out:
        print(f">> {bus} è in LISTEN-ONLY (non dà l'ACK, non disturba il bus della moto)")
    elif "state" in out:
        print(f">> {bus} NON è in listen-only")


def prepara(sc: Scatola, a):
    bus, br = sc.c["bus"], sc.c["bitrate"]
    cmd = []
    for s in sc.c.get("servizi_da_fermare", []):
        cmd.append(f"sudo systemctl stop {s}")
    cmd += [f"sudo ip link set {bus} down", f"sudo ip link set {bus} type can bitrate {br} listen-only on",
            f"sudo ip link set {bus} up", f"ip -details link show {bus} | grep -o 'LISTEN-ONLY' || echo 'ATTENZIONE: listen-only non attivo'"]
    print("Sulla scatola verranno eseguiti:\n  " + "\n  ".join(cmd))
    if not _conferma("Procedo?", a):
        return
    sc.ssh(" && ".join(cmd), interattivo=True)


def ripristina(sc: Scatola, a):
    bus, br = sc.c["bus"], sc.c["bitrate"]
    cmd = [f"sudo ip link set {bus} down", f"sudo ip link set {bus} type can bitrate {br} listen-only off",
           f"sudo ip link set {bus} up"]
    for s in sc.c.get("servizi_da_fermare", []):
        cmd.append(f"sudo systemctl start {s}")
    print("Sulla scatola verranno eseguiti:\n  " + "\n  ".join(cmd))
    if _conferma("Procedo?", a):
        sc.ssh(" && ".join(cmd), interattivo=True)


def installa(sc: Scatola, a):
    print(f"Copio registratore_can.py in ~/dvtool/ su {sc.dest} (non tocca il progetto yccu-peer né i servizi)")
    if not _conferma("Procedo?", a):
        return
    sc.ssh("mkdir -p ~/dvtool")
    sc.scp_a(os.path.join(QUI, "registratore_can.py"), "dvtool/registratore_can.py")
    print(sc.ssh("python3 -c 'import socket; print(\"AF_CAN ok\" if hasattr(socket, \"AF_CAN\") else \"AF_CAN assente\")'"))


def registra(sc: Scatola, a):
    bus, cart = sc.c["bus"], sc.cartella
    if sc.c.get("candump") and not a.python:
        cmd = (f"mkdir -p ~/{cart} && cd ~/{cart} && nohup candump -L '{bus},0:0,#FFFFFFFF' "
               f"> cattura_$(date +%Y%m%d_%H%M%S).log 2>> candump_err.txt & sleep 1; pgrep -af candump")
    else:
        cmd = (f"mkdir -p ~/{cart} && nohup python3 ~/dvtool/registratore_can.py {bus} ~/{cart} "
               f">> ~/{cart}/registratore.out 2>&1 & sleep 1; pgrep -af registratore_can.py; tail -2 ~/{cart}/registratore.out")
    print("Avvio:", cmd)
    if _conferma("Avvio la registrazione?", a):
        print(sc.ssh(cmd, controlla=False))


def ferma(sc: Scatola, a):
    if _conferma("Fermo la registrazione (registratore_can.py / candump)?", a):
        print(sc.ssh("pkill -INT -f registratore_can.py; pkill -INT candump; sleep 1; "
                     "pgrep -af 'registratore_can|candump' || echo fermato", controlla=False))


def elenco(sc: Scatola):
    out = sc.ssh(f"cd ~/{sc.cartella} 2>/dev/null && ls -l --time-style=+%Y-%m-%d_%H:%M *.log 2>/dev/null; "
                 f"echo '--- sessioni app'; ls -1t {shlex.quote(sc.c['progetto'])}/logs/sessions 2>/dev/null | head -10; "
                 f"echo '--- can_cablato'; tail -3 {shlex.quote(sc.c['progetto'])}/app_data/can_cablato/indice.jsonl 2>/dev/null",
                 controlla=False)
    print(out)


def scarica(sc: Scatola, a):
    os.makedirs(a.dest, exist_ok=True)
    elenco_remoto = sc.ssh(f"cd ~/{sc.cartella} && sha256sum *.log marcatori.txt 2>/dev/null", controlla=False)
    voci = [r.split(None, 1) for r in elenco_remoto.splitlines() if r.strip()]
    if not voci:
        print("nessuna cattura in ~/" + sc.cartella)
        return
    attivo = sc.ssh("pgrep -af 'registratore_can|candump' || true", controlla=False)
    for h, nome in voci:
        nome = nome.strip().lstrip("*")
        locale = os.path.join(a.dest, nome)
        if os.path.exists(locale) and _sha_locale(locale) == h and nome != "marcatori.txt":
            print(f"= {nome} già scaricato")
            continue
        sc.scp_da(f"{sc.cartella}/{nome}", locale)
        ok = _sha_locale(locale) == h
        nota = " (la registrazione è ancora attiva: il file può crescere)" if attivo.strip() and nome.endswith(".log") else ""
        print(f"{'OK' if ok else 'IMPRONTA DIVERSA'} {nome} -> {locale}{nota}")
    print("Sulla scatola non è stato cancellato nulla.")


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
     "prepara": lambda: prepara(sc, a), "ripristina": lambda: ripristina(sc, a), "installa": lambda: installa(sc, a),
     "registra": lambda: registra(sc, a), "ferma": lambda: ferma(sc, a), "pacchetto": lambda: pacchetto(sc, a),
     "autorizza": lambda: autorizza(sc, a)}[a.azione]()


if __name__ == "__main__":
    print("usa: python -m dvtool cronometro ...", file=sys.stderr)
