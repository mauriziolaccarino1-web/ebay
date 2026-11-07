#!/usr/bin/env python3
"""Registratore CAN passivo da copiare sulla scatola (Raspberry Pi). Solo libreria standard, nessun pacchetto.

  python3 registratore_can.py can1 ~/catture_ducati            # scrive cattura_AAAAMMGG_hhmmss.log
  python3 registratore_can.py can1 ~/catture_ducati --max-mb 50 # nuovo file ogni 50 MB
  python3 registratore_can.py can1 /tmp/prova --durata 20       # prova: 20 s poi si ferma e riassume

Formato di uscita = `candump -L`:   (epoch.microsecondi) can1 123#0011223344556677
così il PC lo legge come le catture della prova SFV4 del 31/10 (fatta con candump sulla CM4).
Sulla scatola della R9 candump non c'è: questo registratore ne fa le veci e in più conta quello che si perde.

  * tempo del kernel alla ricezione (SO_TIMESTAMPNS), anche su sistemi a 32 bit;
  * frame di errore del controller registrati come candump "#FFFFFFFF" (20000004 = overflow dell'MCP2515);
  * frame persi dal socket (SO_RXQ_OVFL): se il Pi non tiene il passo lo si vede, invece di non saperlo;
  * i dati vanno sulla scheda SD (fsync) ogni 2 s: se la scatola si spegne col quadro si perde al massimo quello;
  * ogni 5 s scrive .registratore.stato (frame/s, persi, overflow, CPU) per il controllo dalla Guida.

NON trasmette nulla: apre solo un socket CAN_RAW in lettura. Il bus va messo in listen-only a parte (ip link).
"""
import json
import os
import signal
import socket
import struct
import sys
import threading
import time

SO_TIMESTAMPNS = getattr(socket, "SO_TIMESTAMPNS", 35)   # SO_TIMESTAMPNS_OLD: timespec di long (8 o 16 byte)
SO_RXQ_OVFL = getattr(socket, "SO_RXQ_OVFL", 40)
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_ERR_CRTL = 0x00000004
CAN_ERR_CRTL_RX_OVERFLOW = 0x01
ANC = socket.CMSG_SPACE(16) + socket.CMSG_SPACE(4) if hasattr(socket, "CMSG_SPACE") else 64


def apri(bus):
    s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    opz = {}
    for nome, liv, opt, val in (("tempo_kernel", socket.SOL_SOCKET, SO_TIMESTAMPNS, 1),
                                ("conta_persi", socket.SOL_SOCKET, SO_RXQ_OVFL, 1)):
        try:
            s.setsockopt(liv, opt, val)
            opz[nome] = True
        except OSError:
            opz[nome] = False
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)   # senza root il kernel lo limita a rmem_max
    except OSError:
        pass
    opz["buffer_byte"] = s.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
    try:  # anche i frame di errore del controller (es. overflow dell'MCP2515), come candump "#FFFFFFFF"
        s.setsockopt(getattr(socket, "SOL_CAN_RAW", 101), getattr(socket, "CAN_RAW_ERR_FILTER", 2), struct.pack("=I", 0x1FFFFFFF))
        opz["errori"] = True
    except OSError:
        opz["errori"] = False
    s.bind((bus,))
    return s, opz


def ancillari(anc):
    """(tempo del kernel o None, contatore cumulativo dei frame persi dal socket o None)."""
    t = persi = None
    for livello, tipo, val in anc:
        if livello != socket.SOL_SOCKET:
            continue
        if tipo == SO_TIMESTAMPNS:
            if len(val) >= 16:
                sec, ns = struct.unpack("qq", val[:16])     # 64 bit
            elif len(val) >= 8:
                sec, ns = struct.unpack("ii", val[:8])      # 32 bit (es. Raspberry Pi OS armhf)
            else:
                continue
            t = sec + ns / 1e9
        elif tipo == SO_RXQ_OVFL and len(val) >= 4:
            persi = struct.unpack("I", val[:4])[0]
    return t, persi


def riga(dati, t, bus):
    """frame grezzo (struct can_frame) -> (riga candump -L, è un frame di errore, è un overflow del ricevitore)."""
    can_id, dlc = struct.unpack_from("=IB", dati, 0)
    payload = dati[8: 8 + min(dlc, 8)]
    errore = bool(can_id & CAN_ERR_FLAG)
    if errore:
        ident = f"{can_id & (CAN_ERR_FLAG | 0x1FFFFFFF):08X}"   # come candump: 20000004 = overflow del ricevitore
    elif can_id & CAN_EFF_FLAG:
        ident = f"{can_id & 0x1FFFFFFF:08X}"
    else:
        ident = f"{can_id & 0x7FF:03X}"
    rtr = "R" if can_id & CAN_RTR_FLAG and not errore else ""
    overflow = errore and bool(can_id & CAN_ERR_CRTL) and len(payload) > 1 and bool(payload[1] & CAN_ERR_CRTL_RX_OVERFLOW)
    return f"({t:.6f}) {bus} {ident}#{rtr}{payload.hex().upper()}\n", errore, overflow


def _scrivi_stato(cartella, st):
    p = os.path.join(cartella, ".registratore.stato")
    try:
        with open(p + ".tmp", "w") as f:
            json.dump(st, f)
        os.replace(p + ".tmp", p)
    except OSError:
        pass


def registra(s, bus, cartella, opz=None, max_mb=200.0, durata=None, fermo=None, stato_ogni=5.0, fsync_ogni=2.0):
    """Ciclo di registrazione. `s` è un socket CAN_RAW già legato (o un oggetto con recvmsg/settimeout per le prove)."""
    opz = opz or {}
    fermo = fermo if fermo is not None else {"v": False}
    os.makedirs(cartella, exist_ok=True)
    corrente = {"f": None}
    sincro = threading.Event()

    def nuovo_file():
        nome = os.path.join(cartella, time.strftime("cattura_%Y%m%d_%H%M%S.log"))
        if os.path.exists(nome):
            nome = nome[:-4] + f"_{int(time.time() * 1000) % 1000:03d}.log"
        with open(os.path.join(cartella, "marcatori.txt"), "a") as m:
            m.write(f"{time.time():.6f} INIZIO {os.path.basename(nome)} bus={bus} "
                    f"tempo_kernel={opz.get('tempo_kernel')} conta_persi={opz.get('conta_persi')}\n")
        return nome, open(nome, "w", buffering=1 << 16)

    def su_disco():  # fsync in un filo a parte: se la SD è lenta il ciclo di lettura non si ferma
        while not sincro.wait(fsync_ogni):
            f = corrente["f"]
            try:
                if f is not None and not f.closed:
                    os.fsync(f.fileno())
            except (OSError, ValueError):
                pass

    nome, out = nuovo_file()
    corrente["f"] = out
    filo = threading.Thread(target=su_disco, daemon=True)
    filo.start()
    print(f"registro {bus} in {nome}", flush=True)
    n = n_err = n_ovf = 0
    # SO_RXQ_OVFL: il kernel aggiunge il contatore solo dopo la PRIMA perdita, e conta da 0 dall'apertura del socket
    persi = 0 if opz.get("conta_persi") else None
    inizio = time.monotonic()
    cpu0, mono0, n0 = time.process_time(), inizio, 0
    ultimo_flush = inizio
    ultimo_stato = inizio - stato_ogni + 1.0   # il primo stato dopo 1 s, poi ogni stato_ogni
    t_primo = t_ultimo = None
    ids = set()
    s.settimeout(0.5)
    while not fermo["v"]:
        ora = time.monotonic()
        if durata is not None and ora - inizio >= durata:
            break
        try:
            dati, anc, _, _ = s.recvmsg(16, ANC)
        except socket.timeout:
            dati = None
        except InterruptedError:
            continue
        ora = time.monotonic()
        if dati:
            t, p = ancillari(anc)
            if p is not None:
                persi = p
            if t is None:
                t = time.time()
            testo, e, o = riga(dati, t, bus)
            out.write(testo)
            n += 1
            n_err += e
            n_ovf += o
            if not e:
                ids.add(testo.split(" ", 2)[2].split("#", 1)[0])
            t_primo = t if t_primo is None else t_primo
            t_ultimo = t
        if ora - ultimo_flush > 1.0:
            out.flush()
            ultimo_flush = ora
            if out.tell() > max_mb * 1e6:
                out.close()
                nome, out = nuovo_file()
                corrente["f"] = out
        if ora - ultimo_stato >= stato_ogni:
            cpu = time.process_time()
            _scrivi_stato(cartella, {"t": time.time(), "file": os.path.basename(nome), "frame": n,
                                     "frame_al_s": round((n - n0) / max(ora - mono0, 1e-6), 1),
                                     "persi_socket": persi,
                                     "frame_errore": n_err, "overflow": n_ovf,
                                     "cpu_pct": round(100 * (cpu - cpu0) / max(ora - mono0, 1e-6), 1)})
            cpu0, mono0, n0, ultimo_stato = cpu, ora, n, ora
    sincro.set()
    out.flush()
    try:
        os.fsync(out.fileno())
    except OSError:
        pass
    out.close()
    secondi = time.monotonic() - inizio
    r = {"frame": n, "secondi": round(secondi, 1), "frame_al_s": round(n / max(secondi, 1e-6), 1),
         "persi_socket": persi, "frame_errore": n_err, "overflow": n_ovf,
         "id": len(ids), "cpu_pct": round(100 * time.process_time() / max(secondi, 1e-6), 1),
         "tempo_kernel": opz.get("tempo_kernel"), "conta_persi": opz.get("conta_persi"),
         "buffer_byte": opz.get("buffer_byte"), "file": os.path.basename(nome)}
    with open(os.path.join(cartella, "marcatori.txt"), "a") as m:
        m.write(f"{time.time():.6f} FINE {os.path.basename(nome)} frame={n} persi_socket={r['persi_socket']} "
                f"frame_errore={n_err} overflow={n_ovf}\n")
    try:
        os.remove(os.path.join(cartella, ".registratore.stato"))
    except OSError:
        pass
    return r


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    bus = sys.argv[1]
    cartella = os.path.expanduser(sys.argv[2])
    max_mb = float(sys.argv[sys.argv.index("--max-mb") + 1]) if "--max-mb" in sys.argv else 200.0
    durata = float(sys.argv[sys.argv.index("--durata") + 1]) if "--durata" in sys.argv else None
    s, opz = apri(bus)
    fermo = {"v": False}

    def stop(*_):
        fermo["v"] = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    r = registra(s, bus, cartella, opz, max_mb=max_mb, durata=durata, fermo=fermo)
    print(f"fermato: {r['frame']} frame", flush=True)
    print("RIASSUNTO " + json.dumps(r), flush=True)


if __name__ == "__main__":
    main()
