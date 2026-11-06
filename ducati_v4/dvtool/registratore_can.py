#!/usr/bin/env python3
"""Registratore CAN passivo da copiare sulla scatola (Raspberry Pi). Solo libreria standard, nessun pacchetto.

  python3 registratore_can.py can1 ~/catture_ducati            # scrive cattura_AAAAMMGG_hhmmss.log
  python3 registratore_can.py can1 ~/catture_ducati --max-mb 50 # nuovo file ogni 50 MB

Formato di uscita = `candump -L`:   (epoch.microsecondi) can1 123#0011223344556677
così il PC lo legge come le catture della prova SFV4 del 31/10.
Il tempo è quello del kernel alla ricezione (SO_TIMESTAMPNS) quando disponibile.
NON trasmette nulla: apre solo un socket CAN_RAW in lettura. Il bus va messo in listen-only a parte (ip link).
"""
import os
import signal
import socket
import struct
import sys
import time

SO_TIMESTAMPNS = getattr(socket, "SO_TIMESTAMPNS", 35)
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    bus = sys.argv[1]
    cartella = os.path.expanduser(sys.argv[2])
    max_mb = float(sys.argv[sys.argv.index("--max-mb") + 1]) if "--max-mb" in sys.argv else 200.0
    os.makedirs(cartella, exist_ok=True)
    s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    try:
        s.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)
        kernel_ts = True
    except OSError:
        kernel_ts = False
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    s.bind((bus,))
    fermo = {"v": False}

    def stop(*_):
        fermo["v"] = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def nuovo_file():
        nome = os.path.join(cartella, time.strftime("cattura_%Y%m%d_%H%M%S.log"))
        with open(os.path.join(cartella, "marcatori.txt"), "a") as m:
            m.write(f"{time.time():.6f} INIZIO {os.path.basename(nome)} bus={bus} kernel_ts={kernel_ts}\n")
        return nome, open(nome, "w", buffering=1 << 16)

    nome, out = nuovo_file()
    print(f"registro {bus} in {nome}", flush=True)
    n = 0
    ultimo_flush = time.monotonic()
    s.settimeout(1.0)
    while not fermo["v"]:
        try:
            dati, anc, _, _ = s.recvmsg(16, socket.CMSG_SPACE(16))
        except socket.timeout:
            continue
        except InterruptedError:
            continue
        t = None
        for livello, tipo, val in anc:
            if livello == socket.SOL_SOCKET and tipo == SO_TIMESTAMPNS and len(val) >= 16:
                sec, ns = struct.unpack("qq", val[:16])
                t = sec + ns / 1e9
        if t is None:
            t = time.time()
        can_id, dlc = struct.unpack_from("=IB", dati, 0)
        payload = dati[8: 8 + min(dlc, 8)]
        if can_id & CAN_ERR_FLAG:
            ident = f"{can_id & 0x1FFFFFFF:08X}"
        elif can_id & CAN_EFF_FLAG:
            ident = f"{can_id & 0x1FFFFFFF:08X}"
        else:
            ident = f"{can_id & 0x7FF:03X}"
        rtr = "R" if can_id & CAN_RTR_FLAG else ""
        out.write(f"({t:.6f}) {bus} {ident}#{rtr}{payload.hex().upper()}\n")
        n += 1
        ora = time.monotonic()
        if ora - ultimo_flush > 1.0:
            out.flush()
            ultimo_flush = ora
            if out.tell() > max_mb * 1e6:
                out.close()
                nome, out = nuovo_file()
    out.close()
    with open(os.path.join(cartella, "marcatori.txt"), "a") as m:
        m.write(f"{time.time():.6f} FINE {os.path.basename(nome)} frame={n}\n")
    print(f"fermato: {n} frame", flush=True)


if __name__ == "__main__":
    main()
