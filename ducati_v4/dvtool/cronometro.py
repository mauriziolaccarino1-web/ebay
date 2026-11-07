"""Scatola H3D Chrono (R9 o CM4) usata SOLO come registratore CAN sulla Ducati.

Usa gli strumenti già presenti su Windows 10/11 e Linux: `ssh` e `scp` (OpenSSH), più urllib per l'API.
Niente viene installato né cancellato sulla scatola e il software della R9 non viene toccato (vedi op_*).
I comandi che cambiano lo stato del momento (prepara, registra, ferma, ripristina) chiedono conferma.

Fatti dalle sessioni precedenti (da ricontrollare sulla scatola che porti in pista):
  * R9:  hostname r9-yccu, Pi Zero 2 W + Waveshare 2-CH CAN HAT+, utente yccu, USB 169.254.55.1,
         sull'hotspot del telefono l'ultimo ottetto è .206; bus moto = can1 sul morsetto CAN_0 (spi1.1),
         can0 (spi1.2) è il bus della lambda; candump NON installato (si usa registratore_can.py);
         sudo chiede la password. È la scatola che va sulla Ducati.
  * CM4: hostname h3d-cm4, USB 169.254.59.1, candump presente, sudo senza password;
         usata sulla Streetfighter V4 il 31/10 con can1 (spi1.1) in listen-only a 500 kbit/s.
  * I nomi can0/can1 dipendono dall'ordine di avvio: prima di toccare il bus si controlla che il nome
    configurato sia davvero sul morsetto della moto (`presa`, letto da /sys/class/net/canX/device).
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
import time
import urllib.request

PREDEFINITI = {
    "scatole": {
        "r9": {"host": "169.254.55.1", "utente": "yccu", "bus": "can1", "bitrate": 500000,
               "progetto": "/home/yccu/projects/yccu-peer", "porta_api": 8770,
               # i registratori r9 riconfigurano can1 da soli (500k, listen-only OFF): vanno fermati
               "candump": False, "servizi_da_fermare": ["r9-can-correlation", "r9-can"], "presa": "spi1.1"},
        "cm4": {"host": "169.254.59.1", "utente": "yccu", "bus": "can1", "bitrate": 500000,
                "progetto": "/home/yccu/projects/yccu-peer", "porta_api": 8770,
                "candump": True, "servizi_da_fermare": ["h3d-guardiano-cronometro", "h3d-cronometro"], "presa": "spi1.1"},
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
        # la stessa scatola ha la stessa impronta via USB e via hotspot: la si salva sotto l'indirizzo USB
        self.alias = self.c.get("alias") or self.c["host"]
        if host:
            self.c["host"] = host
        if utente:
            self.c["utente"] = utente
        self.cartella = cfg.get("cartella_catture", "catture_ducati")

    @property
    def dest(self):
        return f"{self.c['utente']}@{self.c['host']}"

    def ssh(self, comando, interattivo=False, controlla=True, chiave=None):
        args = ["ssh", "-o", "ConnectTimeout=8", "-o", f"HostKeyAlias={self.alias}"]
        if chiave:   # solo questa chiave (es. la copia temporanea di quella di casa)
            args += ["-i", chiave, "-o", "IdentitiesOnly=yes"]
        args += ["-o", "StrictHostKeyChecking=accept-new"] if interattivo else ["-o", "BatchMode=yes"]
        args += [self.dest, comando]
        if interattivo:
            return subprocess.run(args).returncode
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if controlla and r.returncode != 0:
            raise RuntimeError(f"ssh fallito ({r.returncode}): {r.stderr.strip()}")
        return r.stdout

    def scp_da(self, remoto, locale):
        args = ["scp", "-o", "ConnectTimeout=8", "-o", f"HostKeyAlias={self.alias}", "-o", "BatchMode=yes",
                f"{self.dest}:{remoto}", locale]
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"scp fallito: {r.stderr.strip()}")

    def scp_a(self, locale, remoto):
        args = ["scp", "-o", "ConnectTimeout=8", "-o", f"HostKeyAlias={self.alias}", "-o", "BatchMode=yes",
                locale, f"{self.dest}:{remoto}"]
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
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
        '[ -n "$P" ] && kill -0 "$P" 2>/dev/null && grep -qaE "registratore|candump" "/proc/$P/cmdline" 2>/dev/null && VIVO=$P; ')
# ferma il registratore: prima SIGINT, poi SIGTERM se serve (un processo in background può ignorare SIGINT)
_FERMA = (_PID + '[ -n "$VIVO" ] && { kill -INT "$VIVO"; sleep 1.5; ' + _PID +
          '[ -n "$VIVO" ] && { kill -TERM "$VIVO"; sleep 1; }; }; ')


# /sys della scatola (le prove usano una cartella finta al suo posto)
_SYS = 'S="${DVTOOL_SYS:-/sys}"; '
_PRESE = (_SYS + 'for i in "$S"/class/net/can*; do [ -e "$i" ] && echo "$(basename "$i") '
          '$(basename "$(readlink -e "$i/device" 2>/dev/null)" 2>/dev/null)"; done; ')


def _guardia_presa(sc: Scatola) -> str:
    """Shell: se il nome configurato (can1) dopo questo avvio NON è sul morsetto della moto (spi1.1), si ferma
    prima di toccare qualsiasi cosa. Senza questo si metterebbe in ascolto il bus della lambda e il morsetto
    della moto resterebbe com'è."""
    spi, bus = sc.c.get("presa"), sc.c["bus"]
    if not spi:
        return ""
    return (_SYS + f'PRESA=$(basename "$(readlink -e "$S/class/net/{bus}/device" 2>/dev/null)" 2>/dev/null); '
            f'if [ -n "$PRESA" ] && [ "$PRESA" != "{spi}" ]; then cat > /dev/null; '
            f'echo "PRESA_DIVERSA {bus} è sul morsetto $PRESA, non su {spi}"; ' + _PRESE.replace(_SYS, "") + 'exit 3; fi; ')


def _spiega_presa(sc: Scatola, out: str) -> str:
    return (f"Dopo questo avvio {sc.c['bus']} non è il morsetto della moto ({sc.c.get('presa')}): i nomi delle porte CAN "
            "si sono scambiati. Non è stato cambiato niente. Spegni e riaccendi la scatola e riprova; "
            "se resta così, annota l'elenco qui sotto e imposta «bus» in privato/cronometro.json.\n" + out.strip())


def _ssh(sc: Scatola, comando, ingresso=None, timeout=60):
    args = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", "-o", f"HostKeyAlias={sc.alias}",
            "-o", "StrictHostKeyChecking=accept-new", sc.dest, comando]
    try:
        r = subprocess.run(args, input=ingresso, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
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
           f"echo '#HOST'; hostname; echo '#UP'; uptime -p 2>/dev/null || uptime; echo '#ORA'; date +%s.%N; "
           f"echo '#CAN'; ip -details link show {bus} 2>&1 | head -6; "
           f"echo '#PRESE'; " + _PRESE +
           f"echo '#REG'; [ -n \"$VIVO\" ] && echo \"registratore attivo, PID $VIVO\"; "
           f"echo '#REGSTATO'; [ -n \"$VIVO\" ] && cat \"$D/.registratore.stato\" 2>/dev/null; echo; "
           f"echo '#FILE'; ls -l --time-style=+%Y-%m-%d_%H:%M:%S ~/{cart}/*.log 2>/dev/null | awk '{{print $5, $6, $7}}'; "
           f"echo '#DISCO'; df -h ~ | tail -1; "
           f"echo '#SERVIZI'; for s in {' '.join(sc.c.get('servizi_da_fermare', []))}; do echo \"$s $(systemctl is-active $s 2>/dev/null)\"; done; "
           f"echo '#FINE'")
    t0 = time.time()
    rc, out, err = _ssh(sc, cmd, timeout=20)
    t_pc = (t0 + time.time()) / 2
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
    prese = {}
    for r in parti.get("PRESE", []):
        x = r.split()
        if x:
            prese[x[0]] = x[1] if len(x) > 1 else ""
    spi = sc.c.get("presa")
    presa_ok = None if not spi or not prese.get(sc.c["bus"]) else prese[sc.c["bus"]] == spi
    reg_stato = None
    testo_stato = " ".join(parti.get("REGSTATO", [])).strip()
    if testo_stato:
        try:
            reg_stato = json.loads(testo_stato)
        except ValueError:
            reg_stato = None
    try:
        scarto = round(float(parti.get("ORA", ["nan"])[0]) - t_pc, 1)
    except (ValueError, IndexError):
        scarto = None
    return {"ok": True, "dest": sc.dest, "hostname": " ".join(parti.get("HOST", [])), "acceso_da": " ".join(parti.get("UP", [])),
            "can": can, "listen_only": "LISTEN-ONLY" in can, "can_su": ",UP" in can or "state UP" in can or "UP," in can,
            "bus": sc.c["bus"], "presa": spi, "prese": prese, "presa_ok": presa_ok,
            "orologio_scarto_s": scarto if scarto == scarto else None,
            "registratore": [r for r in parti.get("REG", []) if r.strip()], "registratore_stato": reg_stato, "catture": file,
            "disco": " ".join(parti.get("DISCO", [])), "servizi": dict(r.split(" ", 1) for r in parti.get("SERVIZI", []) if " " in r)}


def op_prepara(sc: Scatola, password: str = "") -> dict:
    """Ferma (solo per ora) i servizi che usano can1 e lo mette in ascolto passivo a 500 kbit/s."""
    bus, br, cart = sc.c["bus"], sc.c["bitrate"], sc.cartella
    servizi = " ".join(sc.c.get("servizi_da_fermare", []))
    cmd = (_guardia_presa(sc) + f'D="$HOME/{cart}"; mkdir -p "$D"; ATTIVI=""; '
           f'for s in {servizi}; do systemctl is-active --quiet "$s" && ATTIVI="$ATTIVI $s"; done; '
           # un secondo «prepara» (turno dopo, servizi già fermi) non deve cancellare la lista di quelli da riavviare
           f'PRIMA=$(cat "$D/.servizi_attivi_prima" 2>/dev/null); '
           f'for s in $PRIMA $ATTIVI; do echo "$s"; done | sort -u | tr "\\n" " " > "$D/.servizi_attivi_prima"; '
           f'sudo -S -p "" sh -c "for s in $ATTIVI; do systemctl stop \\$s; done; ip link set {bus} down; '
           f'ip link set {bus} type can bitrate {br} listen-only on; ip link set {bus} up" && '
           f'echo "servizi fermati:$ATTIVI"; ip -details link show {bus} | grep -o LISTEN-ONLY || echo NON_IN_ASCOLTO')
    rc, out, err = _ssh(sc, cmd, ingresso=(password or "") + "\n", timeout=40)
    ok = rc == 0 and "LISTEN-ONLY" in out
    errore = None
    if "PRESA_DIVERSA" in out:
        errore = _spiega_presa(sc, out)
    elif not ok:
        errore = "password di sudo sbagliata o mancante" if "incorrect password" in err.lower() or "password is required" in err.lower() or "sorry" in err.lower() \
            else (_spiega_errore_ssh(err) if rc == 255 else (err.strip() or out.strip())[-400:])
    return {"ok": ok, "testo": out.strip(), "errore": errore}


def _script_registratore() -> str:
    with open(os.path.join(QUI, "registratore_can.py"), "r", encoding="utf-8") as f:
        return f.read()


def op_registra(sc: Scatola, forza_python: bool = False) -> dict:
    """Avvia il registratore da una copia temporanea in /tmp (niente installato), catture in ~/catture_ducati.
    Con candump (CM4) come il 31/10; sulla R9, che non ce l'ha, con registratore_can.py."""
    bus, cart = sc.c["bus"], sc.cartella
    script = _script_registratore()
    con_candump = "false" if forza_python else "command -v candump >/dev/null 2>&1"
    cmd = (_guardia_presa(sc) + f'D="$HOME/{cart}"; mkdir -p "$D"; ' + _PID +
           f'if [ -n "$VIVO" ]; then cat > /dev/null; echo "GIA_ATTIVO PID $VIVO"; '
           f'elif {con_candump}; then cat > /dev/null; '
           f'F="$D/cattura_$(date +%Y%m%d_%H%M%S).log"; '
           f'setsid nohup candump -L "{bus},0:0,#FFFFFFFF" > "$F" 2>> "$D/candump_err.txt" < /dev/null & '
           f'echo $! > "$D/.registratore.pid"; echo "$(date +%s.%N) INIZIO $(basename "$F") candump bus={bus}" >> "$D/marcatori.txt"; '
           f'echo "con candump -L (come nella prova SFV4) in $F"; sleep 2; '
           f'else cat > /tmp/{NOME_REG}; '
           f'setsid nohup python3 /tmp/{NOME_REG} {bus} "$D" >> "$D/registratore.out" 2>&1 < /dev/null & '
           f'echo $! > "$D/.registratore.pid"; sleep 2; fi; ' + _PID +
           f'[ -n "$VIVO" ] && echo "REGISTRA PID $VIVO" || echo NON_PARTITO; tail -2 "$D/registratore.out" 2>/dev/null; true')
    rc, out, err = _ssh(sc, cmd, ingresso=script, timeout=30)
    ok = rc == 0 and "REGISTRA PID" in out
    errore = None
    if "PRESA_DIVERSA" in out:
        errore = _spiega_presa(sc, out)
    elif not ok:
        errore = _spiega_errore_ssh(err) if rc == 255 else out.strip()[-400:]
    return {"ok": ok, "testo": out.strip(), "gia_attivo": "GIA_ATTIVO" in out, "errore": errore}


def op_prova_registratore(sc: Scatola, secondi: int = 20) -> dict:
    """Fa girare registratore_can.py per qualche secondo SENZA cambiare niente: can1 resta com'è, i servizi
    restano accesi, niente sudo. Lavora in una cartella temporanea di /tmp che viene cancellata subito.
    Si può fare anche con la scatola sulla R9 (un lettore in più su can1 non trasmette nulla): serve a vedere,
    prima della Ducati, che il registratore gira su questa scatola e quanti frame perde."""
    secondi = max(3, min(int(secondi), 120))
    bus = sc.c["bus"]
    cmd = (_guardia_presa(sc) + f'D="$HOME/{sc.cartella}"; ' + _PID +
           f'if [ -n "$VIVO" ]; then cat > /dev/null; echo "GIA_ATTIVO PID $VIVO"; exit 0; fi; '
           f'T=$(mktemp -d /tmp/dvtool_prova.XXXXXX) || exit 4; cat > "$T/{NOME_REG}"; '
           f'timeout {secondi + 20} python3 "$T/{NOME_REG}" {bus} "$T" --durata {secondi} 2>&1 | tail -6; '
           f'rm -rf "$T"; echo "#CAN"; ip -details link show {bus} 2>&1 | head -3')
    rc, out, err = _ssh(sc, cmd, ingresso=_script_registratore(), timeout=secondi + 45)
    if rc == 255:
        return {"ok": False, "errore": _spiega_errore_ssh(err), "testo": ""}
    if "PRESA_DIVERSA" in out:
        return {"ok": False, "errore": _spiega_presa(sc, out), "testo": out.strip()}
    if "GIA_ATTIVO" in out:
        return {"ok": False, "errore": "c'è già una registrazione in corso: usa «Controlla che stia registrando»", "testo": out.strip()}
    riassunto = None
    for r in out.splitlines():
        if r.startswith("RIASSUNTO "):
            try:
                riassunto = json.loads(r[len("RIASSUNTO "):])
            except ValueError:
                pass
    if riassunto is None:
        return {"ok": False, "errore": "il registratore non è partito su questa scatola:\n" + (out.strip() or err.strip())[-600:],
                "testo": out.strip()}
    can = out.split("#CAN", 1)[1].strip() if "#CAN" in out else ""
    return {"ok": True, "riassunto": riassunto, "giudizio": giudica_prova(riassunto), "can": can,
            "listen_only": "LISTEN-ONLY" in can, "testo": out.strip()}


def giudica_prova(r: dict) -> list:
    """Frasi in chiaro sul risultato della prova del registratore."""
    g = []
    if not r.get("frame"):
        g.append("Nessun frame: il bus è muto (moto spenta o quadro spento?) o il cavo non è sul morsetto della moto. "
                 "Il registratore però è partito: su questa scatola funziona.")
        return g
    g.append(f"{r['frame']} frame in {r['secondi']} s ({r['frame_al_s']:.0f} al secondo), ID diversi: {r.get('id', '?')}.")
    if r.get("persi_socket") is None:
        g.append("Il conteggio dei frame persi dal socket non è disponibile su questa scatola.")
    elif r["persi_socket"] == 0:
        g.append("Nessun frame perso dal registratore: il Pi tiene il passo.")
    else:
        g.append(f"Il registratore ha perso {r['persi_socket']} frame: il Pi non tiene il passo (CPU {r.get('cpu_pct')}%).")
    if r.get("overflow"):
        al_min = 60 * r["overflow"] / max(r["secondi"], 1e-6)
        g.append(f"{r['overflow']} overflow del controller MCP2515 ({al_min:.0f} al minuto). Il 31/10 con la CM4 erano "
                 "15 al minuto: vengono contati a parte nella verifica del protocollo.")
    else:
        g.append("Nessun overflow del controller.")
    g.append("Tempi del kernel: sì." if r.get("tempo_kernel") else "Tempi del kernel non disponibili: si usa l'ora del programma (meno precisa).")
    g.append(f"CPU del registratore: {r.get('cpu_pct')}% di un core.")
    return g


def op_marca(sc: Scatola, testo: str) -> dict:
    """Segna un momento (come i marcatori della prova SFV4): riga «epoca testo» in ~/catture_ducati/marcatori.txt,
    con l'orologio della scatola, lo stesso delle catture."""
    t = " ".join(str(testo).split())[:80] or "segno"
    rc, out, err = _ssh(sc, f'D="$HOME/{sc.cartella}"; mkdir -p "$D"; T=$(date +%s.%N); printf "%s %s\\n" "$T" {shlex.quote(t)} >> "$D/marcatori.txt"; echo "$T"',
                        timeout=15)
    return {"ok": rc == 0, "t": out.strip(), "testo": t, "errore": None if rc == 0 else _spiega_errore_ssh(err)}


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
        esiti.append(_scarica_uno(sc, nome, h, locale, registrazione_attiva=bool(attivo.strip())))
    return {"ok": all(e["ok"] for e in esiti), "file": esiti, "dest": os.path.abspath(dest),
            "registrazione_attiva": bool(attivo.strip()), "nota": "sulla scatola non è stato cancellato nulla"}


def _scarica_uno(sc: Scatola, nome: str, h: str, locale: str, registrazione_attiva: bool, tentativi: int = 3) -> dict:
    """Scarica in <nome>.part e lo rinomina solo se l'impronta coincide: un trasferimento interrotto (wifi) non
    lascia mai un file troncato al posto di una copia buona. Riprova da solo."""
    parte = locale + ".part"
    ultimo = ""
    for i in range(tentativi):
        try:
            sc.scp_da(f"{sc.cartella}/{nome}", parte)
        except RuntimeError as e:
            ultimo = f"trasferimento interrotto ({e})"
            continue
        if _sha_locale(parte) == h:
            os.replace(parte, locale)
            return {"nome": nome, "ok": True, "byte": os.path.getsize(locale),
                    "esito": "scaricato e verificato" + (f" (al tentativo {i + 1})" if i else "")}
        ultimo = "impronta diversa"
        if registrazione_attiva:
            break   # il file cresce mentre lo copio: riprovare non serve
    if os.path.exists(parte):
        if registrazione_attiva and nome.endswith(".log") and ultimo == "impronta diversa":
            parziale = locale[:-4] + "_parziale.log"
            os.replace(parte, parziale)
            return {"nome": nome, "ok": False, "byte": os.path.getsize(parziale), "parziale": os.path.basename(parziale),
                    "esito": f"la registrazione sta ancora scrivendo questo file: copia parziale in {os.path.basename(parziale)}, "
                             "utile per un'occhiata; per la copia verificata ferma la registrazione e riscarica"}
        os.remove(parte)
    return {"nome": nome, "ok": False, "esito": f"{ultimo or 'non scaricato'} dopo {tentativi} tentativi: riprova "
                                                  "(la copia che avevi sul PC, se c'era, non è stata toccata)"}


def op_ripristina(sc: Scatola, password: str = "") -> dict:
    """Ferma il registratore, rimette can1 in modo normale e riavvia SOLO i servizi che erano attivi prima."""
    bus, br, cart = sc.c["bus"], sc.c["bitrate"], sc.cartella
    cmd = (f'D="$HOME/{cart}"; ' + _FERMA +
           f'ATTIVI=$(cat "$D/.servizi_attivi_prima" 2>/dev/null); '
           f'sudo -S -p "" sh -c "ip link set {bus} down; ip link set {bus} type can bitrate {br} listen-only off; '
           f'ip link set {bus} up; for s in $ATTIVI; do systemctl start \\$s; done" && echo "servizi riavviati:$ATTIVI" && '
           f'rm -f "$D/.servizi_attivi_prima"; '
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
    if r.get("orologio_scarto_s") is not None:
        print(f"orologio della scatola: {r['orologio_scarto_s']:+.1f} s rispetto al PC")
    print("porte CAN:", ", ".join(f"{k} = {v or '?'}" for k, v in r.get("prese", {}).items()) or "?",
          "" if r.get("presa_ok") is not False else f"  !! {r['bus']} NON è il morsetto della moto ({r['presa']})")
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
        r = op_registra(sc, forza_python=getattr(a, "python", False))
        print(r["testo"] if r["ok"] else "! " + str(r["errore"]))


def prova(sc: Scatola, a):
    sec = int(getattr(a, "secondi", None) or 20)
    print(f"Prova del registratore per {sec} s: legge {sc.c['bus']} com'è, non ferma servizi, non usa sudo, "
          "non lascia file (cartella temporanea in /tmp cancellata subito). Va bene anche sulla R9.")
    r = op_prova_registratore(sc, sec)
    if not r["ok"]:
        print("!", r["errore"])
        return
    for g in r["giudizio"]:
        print(" -", g)
    print(" can:", "LISTEN-ONLY" if r["listen_only"] else "normale", "(non è stato cambiato)")


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
    """Aggiunge la chiave pubblica di questo PC (o di un altro) alle chiavi autorizzate della scatola.

    Serve una chiave che la scatola accetta GIÀ: quella di casa. Dal PC di lavoro: --chiave <copia temporanea
    della chiave privata di casa>, poi la copia va cancellata. Sulla scatola si aggiunge solo una riga."""
    if not a.file:
        raise SystemExit("serve --file <chiave PUBBLICA .pub da autorizzare>, es. %USERPROFILE%\\.ssh\\id_ed25519.pub")
    pub = open(a.file, "r", encoding="ascii").read().strip()
    if not pub.startswith(("ssh-ed25519 ", "ssh-rsa ", "ecdsa-")) or "PRIVATE" in pub:
        raise SystemExit("serve il file .pub (chiave PUBBLICA), non la chiave privata")
    chiave = getattr(a, "chiave", None)
    if chiave and not os.path.exists(chiave):
        raise SystemExit(f"chiave per entrare non trovata: {chiave}")
    print(f"Aggiungo a ~/.ssh/authorized_keys di {sc.dest}:\n  {pub[:60]}...")
    print(f"Entro con: {chiave or 'le chiavi predefinite di questo PC'}")
    if not _conferma("Procedo?", a):
        return
    q = shlex.quote(pub)
    rc = sc.ssh(f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && (grep -qxF {q} ~/.ssh/authorized_keys 2>/dev/null || echo {q} >> ~/.ssh/authorized_keys) "
                f"&& chmod 600 ~/.ssh/authorized_keys && echo chiave presente", interattivo=True, chiave=chiave)
    if rc != 0:
        print(f"! non riuscito (ssh {rc}): la scatola accetta la chiave indicata con --chiave? è collegata?")
        return
    privata = a.file[:-4] if a.file.endswith(".pub") else None
    if privata and os.path.exists(privata):
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", "-o", f"HostKeyAlias={sc.alias}",
                            "-i", privata, "-o", "IdentitiesOnly=yes", sc.dest, "echo ok"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            print("Verificato: la nuova chiave entra da sola (come la usano la Guida e i comandi).")
        else:
            print("! la nuova chiave non entra ancora senza domande: se ha una passphrase la Guida non può usarla "
                  "(ricreala premendo invio alla passphrase).", r.stderr.strip()[-200:])
    if chiave:
        print(f"Ora cancella la copia temporanea della chiave di casa: del \"{chiave}\"")


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
     "prova": lambda: prova(sc, a),
     "autorizza": lambda: autorizza(sc, a)}[a.azione]()


if __name__ == "__main__":
    print("usa: python -m dvtool cronometro ...", file=sys.stderr)
