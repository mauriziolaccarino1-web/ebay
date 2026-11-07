"""Socket CAN finto per la scatola finta: esegue il registratore vero (argv[1]) con frame simulati.

Circa 800 frame/s di 0x018 con il tempo del kernel; ogni 100 frame un overflow dell'MCP2515 (20000004);
il contatore SO_RXQ_OVFL sale di 1 ogni 500 frame. Con FINTO_CAN_32BIT=1 il tempo arriva come timespec a 32 bit.
"""
import importlib.util
import os
import socket
import struct
import sys
import time

spec = importlib.util.spec_from_file_location("registratore", sys.argv[1])
reg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reg)
A32 = os.environ.get("FINTO_CAN_32BIT") == "1"


class SocketFinto:
    def __init__(self):
        self.n = 0

    def settimeout(self, t):
        pass

    def recvmsg(self, n, anc):
        time.sleep(0.00125)
        self.n += 1
        t = time.time()
        sec, ns = int(t), int((t - int(t)) * 1e9)
        ts = struct.pack("ii", sec, ns) if A32 else struct.pack("qq", sec, ns)
        a = [(socket.SOL_SOCKET, reg.SO_TIMESTAMPNS, ts), (socket.SOL_SOCKET, reg.SO_RXQ_OVFL, struct.pack("I", self.n // 500))]
        if self.n % 100 == 0:
            d = struct.pack("=IB3x8s", 0x20000004, 8, bytes([0, 1, 0, 0, 0, 0, 0, 0]))
        else:
            d = struct.pack("=IB3x8s", 0x018, 8, bytes(range(8)))
        return d, a, 0, None


reg.apri = lambda bus: (SocketFinto(), {"tempo_kernel": True, "conta_persi": True, "buffer_byte": 212992, "errori": True})
sys.argv = sys.argv[1:]
reg.main()
