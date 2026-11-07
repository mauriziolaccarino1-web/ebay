"""Prove automatiche:  python -m unittest discover -s tests   (dalla cartella ducati_v4)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import numpy as np

QUI = os.path.dirname(os.path.abspath(__file__))


def leggi_testo(p):
    with open(p) as f:
        return f.read()


def leggi_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)
sys.path.insert(0, os.path.dirname(QUI))

from dvtool import calib, canlog, dbc, laps, model, pacchetto, protocollo, sessione, synth  # noqa: E402
from dvtool import checksum as cks  # noqa: E402


class ProvaDBC(unittest.TestCase):
    def test_intel_motorola_andata_ritorno(self):
        testo = '''BO_ 36 M: 8 ECU
 SG_ A : 7|13@0+ (0.0625,0) [0|500] "km/h" X
 SG_ B : 20|13@0+ (0.0625,0) [0|500] "km/h" X
 SG_ C : 39|3@0+ (1,0) [0|7] "" X
 SG_ D : 48|16@1- (0.01,0) [-300|300] "" X
'''
        db = dbc.analizza_dbc(testo)
        m = db.messaggi[36]
        b = dbc.codifica(m, {"A": 123.4375, "B": 98.25, "C": 5, "D": -12.34})
        l = canlog.leggi_testo([f"(1.0) can1 024#{b.hex()}"])
        d = dbc.decodifica(db, l.t, l.id, l.data)
        self.assertAlmostEqual(d["M.A"][1][0], 123.4375)
        self.assertAlmostEqual(d["M.B"][1][0], 98.25)
        self.assertEqual(d["M.C"][1][0], 5)
        self.assertAlmostEqual(d["M.D"][1][0], -12.34, places=6)

    def test_frame_reale_sfv4(self):
        # 024#00000000E02001F2 dalla prova del 31/10: marcia 7 all'avvio, contatore 1, CRC F2
        testo = '''BO_ 36 ECU_EngineStatus1_024: 8 ECU
 SG_ Gear : 39|3@0+ (1,0) [0|7] "" X
 SG_ Counter : 51|4@0+ (1,0) [0|15] "" X
 SG_ CRC : 63|8@0+ (1,0) [0|255] "" X
'''
        db = dbc.analizza_dbc(testo)
        l = canlog.leggi_testo(["(1.0) can1 024#00000000E02001F2", "(1.01) can1 080#2BC2BC03452001D9"])
        d = dbc.decodifica(db, l.t, l.id, l.data)
        self.assertEqual(d["ECU_EngineStatus1_024.Gear"][1][0], 7)
        self.assertEqual(d["ECU_EngineStatus1_024.Counter"][1][0], 1)
        crc = protocollo.crc8_j1850(l.data[:, :7])
        self.assertEqual(list(crc), [0xF2, 0xD9])


class ProvaLog(unittest.TestCase):
    def test_formati(self):
        a = canlog.leggi_testo(["(1697040000.100000) can0 123#DEADBEEF", "(1697040000.110000) can0 7FF#"])
        self.assertEqual(list(a.id), [0x123, 0x7FF])
        j = canlog.leggi_jsonl(['{"can_id": 24, "data_hex": "0102", "ts_monotonic_ns": 5000000000, "boot_id": "x"}'])
        self.assertEqual(j.id[0], 24)
        self.assertAlmostEqual(j.t[0], 5.0)
        c = canlog.leggi_csv("t;id;data\n0.1;0x18;0011\n0.2;0x18;0022\n")
        self.assertEqual(int(c.data[1, 1]), 0x22)


class ProvaGiri(unittest.TestCase):
    def test_giri_senza_gps(self):
        sim = synth.simula()
        v = laps.correggi_piega(sim["v_ant"], sim["piega"], 299.9, 60)
        r = laps.stima_giri(sim["t"], v, piega=sim["piega"])
        lanc = [g for g in r.giri if g.tipo == "lanciato"]
        self.assertEqual(len(lanc), 5)
        s_vera = laps.distanza(sim["t"], sim["v_vero"])
        L = sim["lunghezza_pista"]
        p0 = np.interp(lanc[0].t_inizio, sim["t"], s_vera)
        veri = np.diff([np.interp(p0 + k * L, s_vera, sim["t"]) for k in range(6)])
        errori = np.abs(np.array([g.tempo for g in lanc]) - veri)
        self.assertLess(errori.max(), 0.02, f"errori {errori}")


class ProvaCurve(unittest.TestCase):
    def test_curve_dalla_piega_e_dalla_velocita(self):
        sim = synth.simula()
        v = laps.correggi_piega(sim["v_ant"], sim["piega"], 299.9, 60)
        r = laps.stima_giri(sim["t"], v, piega=sim["piega"], curve_opz={"piega_positiva": "sinistra", "nomi": ["Prima"]})
        self.assertGreaterEqual(len(r.curve), 8)
        self.assertEqual(r.curve[0]["nome"], "Prima")
        apici = [c["apice"] for c in r.curve]
        self.assertEqual(apici, sorted(apici))
        self.assertTrue(all(c["inizio"] <= c["apice"] <= c["fine"] for c in r.curve))
        self.assertTrue(all(c["piega_max"] > 45 for c in r.curve))      # giri lanciati, non quello di uscita
        self.assertEqual({c["verso"] for c in r.curve}, {"destra", "sinistra"})
        r2 = laps.stima_giri(sim["t"], v)                                  # senza piega: dai minimi di velocità
        self.assertLessEqual(abs(len(r2.curve) - len(r.curve)), 1)


class ProvaCalibrazione(unittest.TestCase):
    def setUp(self):
        self.S = calib.risolvi(synth.struttura_demo(), "NOSLICK")
        self.buf = synth.bin_demo(self.S)

    def test_varianti(self):
        S = synth.struttura_demo()
        with self.assertRaises(KeyError):
            calib.risolvi(S)  # i profili hanno indirizzi per variante
        Sn, Ss = calib.risolvi(S, "NOSLICK"), calib.risolvi(S, "SLICK")
        bn, bs = synth.bin_demo(Sn, "NOSLICK"), synth.bin_demo(Ss, "SLICK")
        S["varianti"][0]["sha256"] = calib.sha256(bytes(bn))
        S["varianti"][1]["sha256"] = calib.sha256(bytes(bs))
        self.assertEqual(calib.trova_variante(S, bs), "SLICK")
        tp = next(t for t in Ss["tabelle"] if t["id"] == "DEMO_PROFILO_POST")
        self.assertNotEqual(tp["indirizzo"], next(t for t in Sn["tabelle"] if t["id"] == "DEMO_PROFILO_POST")["indirizzo"])
        # stessa tabella letta al suo indirizzo: profilo slick con corona più ampia (raggio minore a 60 gradi)
        rn = calib.leggi_tabella(Sn, next(t for t in Sn["tabelle"] if t["id"] == "DEMO_PROFILO_POST"), bn)["z"][0]
        rs = calib.leggi_tabella(Ss, tp, bs)["z"][0]
        self.assertAlmostEqual(rn[0], rs[0], places=1)
        self.assertLess(rs[-1], rn[-1])
        self.assertTrue(all(r["ok"] for r in calib.verifica_checksum(Ss, bytes(bs))))

    def test_checksum_originale_ok(self):
        self.assertTrue(all(r["ok"] for r in calib.verifica_checksum(self.S, bytes(self.buf))))

    def test_patch_e_checksum(self):
        tab = next(t for t in self.S["tabelle"] if t["id"] == "DEMO_SOGLIA_SLIP_L2")
        z = calib.leggi_tabella(self.S, tab, self.buf)["z"] * 1.1
        patch = {"base_sha256": calib.sha256(bytes(self.buf)), "modifiche": [{"tabella": tab["id"], "valori": z.tolist()}]}
        out, avvisi = calib.applica_patch(self.S, bytes(self.buf), patch)
        self.assertEqual(avvisi, [])
        self.assertTrue(all(r["ok"] for r in calib.verifica_checksum(self.S, bytes(out))))
        diff = calib.confronta(self.S, bytes(self.buf), bytes(out))
        self.assertEqual([t["id"] for t in diff["tabelle"]], [tab["id"]])
        self.assertEqual(diff["regioni_fuori_struttura"], [])

    def test_algoritmi(self):
        self.assertEqual(cks.calcola("crc32", b"123456789")[0], 0xCBF43926)
        self.assertEqual(cks.calcola("crc16_ccitt", b"123456789")[0], 0x29B1)
        self.assertEqual(cks.calcola("crc16_modbus", b"123456789")[0], 0x4B37)
        self.assertEqual(cks.calcola("crc32_mpeg2", b"123456789")[0], 0x0376E6E7)

    def test_lookup(self):
        z = np.array([[0.0, 10.0], [20.0, 30.0]])
        self.assertAlmostEqual(float(calib.lookup2d(np.array([0.0, 1.0]), np.array([0.0, 1.0]), z, 0.5, 0.5)), 15.0)
        self.assertAlmostEqual(float(calib.lookup2d(np.array([0.0, 1.0]), np.array([0.0, 1.0]), z, 5, -3)), 10.0)


class ProvaModello(unittest.TestCase):
    def test_espressioni(self):
        env = {"a": np.array([1.0, 5.0]), "b": np.array([2.0, 2.0])}
        np.testing.assert_allclose(model.valuta("max(a, b) * 2 if a > 1 else -1", env), [-1, 10])
        np.testing.assert_allclose(model.valuta("a > 1 and not b > 3", env), [0, 1])
        with self.assertRaises(model.ErroreModello):
            model.valuta("__import__('os')", env)

    def test_ordine_e_isteresi(self):
        M = {"ingressi": [{"id": "x"}], "blocchi": [{"id": "y", "tipo": "espressione", "espressione": "z * 2"},
                                                    {"id": "z", "tipo": "abs", "ingressi": ["x"]}],
             "criteri": [{"id": "C1", "valore": "y", "soglia": 4, "confronto": ">", "isteresi": 1}], "logica": "C1"}
        x = np.array([0, 2.1, 2.2, 1.8, 1.4, 1.0])
        r = model.esegui(M, {"x": x}, np.arange(6) * 0.01)
        np.testing.assert_allclose(r["criteri"]["C1"]["attivo"], [0, 1, 1, 1, 0, 0])


class ProvaGuida(unittest.TestCase):
    def setUp(self):
        from dvtool import guida
        self.g = guida
        self.cart = tempfile.mkdtemp()
        self.vecchi = (guida.RADICE, guida.FILE_IMP)
        guida.RADICE = self.cart
        guida.FILE_IMP = os.path.join(self.cart, "privato", "guida.json")
        os.makedirs(os.path.join(self.cart, "privato", "calibrazioni"))
        S = synth.struttura_demo()
        Sn = calib.risolvi(S, "NOSLICK")
        self.buf = bytes(synth.bin_demo(Sn, "NOSLICK"))
        S["varianti"][0]["sha256"] = calib.sha256(self.buf)
        with open(os.path.join(self.cart, "privato", "calibrazioni", "NOSLICK.bin"), "wb") as f:
            f.write(self.buf)
        self.S = S
        with open(os.path.join(self.cart, "privato", "struttura.json"), "w") as f:
            json.dump(S, f)
        tab = next(t for t in Sn["tabelle"] if t["id"] == "DEMO_SOGLIA_SLIP_L2")
        z = calib.leggi_tabella(Sn, tab, self.buf)["z"] * 1.1
        self.patch = {"modifiche": [{"tabella": tab["id"], "valori": z.tolist()}]}

    def tearDown(self):
        self.g.RADICE, self.g.FILE_IMP = self.vecchi
        shutil.rmtree(self.cart)

    def test_prepara_file_senza_toccare_l_originale(self):
        r = self.g.applica({"file": "NOSLICK.bin", "patch": self.patch})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["variante"], "NOSLICK")
        self.assertEqual([t["id"] for t in r["tabelle_cambiate"]], ["DEMO_SOGLIA_SLIP_L2"])
        self.assertEqual(r["fuori_struttura"], [])
        self.assertTrue(os.path.exists(r["percorso"]) and os.path.exists(r["percorso"] + ".patch.json"))
        with open(os.path.join(self.cart, "privato", "calibrazioni", "NOSLICK.bin"), "rb") as f:
            self.assertEqual(f.read(), self.buf)  # originale intatto

    def test_rifiuta_se_il_checksum_dell_originale_non_torna(self):
        self.S["checksum"][0]["algoritmo"] = "crc32"   # regola sbagliata
        with open(os.path.join(self.cart, "privato", "struttura.json"), "w") as f:
            json.dump(self.S, f)
        r = self.g.applica({"file": "NOSLICK.bin", "patch": self.patch})
        self.assertFalse(r["ok"])
        self.assertIn("ORIGINALE", r["errore"])
        self.assertFalse(os.path.exists(os.path.join(self.cart, "privato", "calibrazioni", "modificati")))


@unittest.skipUnless(shutil.which("bash") and os.name == "posix", "serve bash (Linux)")
class ProvaCronometroScatolaFinta(unittest.TestCase):
    """Ciclo completo contro una scatola finta (ssh, sudo, ip, systemctl simulati in tests/scatola_finta)."""

    def setUp(self):
        from dvtool import cronometro
        self.c = cronometro
        self.M = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.M, "home")); os.makedirs(os.path.join(self.M, "stato"))
        shutil.copytree(os.path.join(QUI, "scatola_finta"), os.path.join(self.M, "bin"))
        self.env = (os.environ.get("SCATOLA"), os.environ["PATH"])
        os.environ["SCATOLA"] = self.M
        os.environ["PATH"] = os.path.join(self.M, "bin") + os.pathsep + os.environ["PATH"]

    def tearDown(self):
        if self.env[0] is None:
            os.environ.pop("SCATOLA", None)
        else:
            os.environ["SCATOLA"] = self.env[0]
        os.environ["PATH"] = self.env[1]
        shutil.rmtree(self.M)

    def _ciclo(self, nome, servizio):
        c = self.c
        open(os.path.join(self.M, "stato", "attivo_" + servizio), "w").close()
        sc = c.Scatola(c.configurazione(os.path.join(self.M, "nessuno.json")), nome)
        self.assertFalse(c.op_prepara(sc, "sbagliata")["ok"])
        p_can = os.path.join(self.M, "stato", "can1")
        if os.path.exists(p_can):
            with open(p_can) as f:
                self.assertNotEqual(f.read().strip(), "on")   # password sbagliata: can1 non cambia
        self.assertTrue(c.op_prepara(sc, "segreta")["ok"])
        r = c.op_registra(sc)
        self.assertTrue(r["ok"], r)
        self.assertTrue(c.op_registra(sc)["gia_attivo"])
        self.assertTrue(c.op_marca(sc, "TC cambiato")["ok"])
        time.sleep(1.5)
        st = c.op_stato(sc)
        self.assertTrue(st["listen_only"])
        self.assertIsNotNone(st["orologio_scarto_s"])
        self.assertLess(abs(st["orologio_scarto_s"]), 2)
        if nome == "r9":   # il registratore Python scrive il suo stato (frame/s, persi, overflow, CPU)
            self.assertGreater(st["registratore_stato"]["frame"], 0, st)
        self.assertTrue(c.op_ferma(sc)["ok"])
        d = os.path.join(self.M, "scaricati")
        r = c.op_scarica(sc, d)
        self.assertTrue(r["ok"], r)
        with open(os.path.join(d, "marcatori.txt")) as f:
            self.assertIn("TC cambiato", f.read())
        self.assertTrue(c.op_ripristina(sc, "segreta")["ok"])
        self.assertTrue(os.path.exists(os.path.join(self.M, "stato", "attivo_" + servizio)))   # riavviato com'era
        self.assertEqual(sorted(os.listdir(os.path.join(self.M, "home"))), ["catture_ducati"])  # nient'altro sulla scatola
        return d

    def test_r9_senza_candump(self):
        d = self._ciclo("r9", "r9-can-correlation")
        log = canlog.leggi(os.path.join(d, next(f for f in os.listdir(d) if f.endswith(".log"))))
        self.assertEqual(set(int(x) for x in log.id), {0x18})          # registratore vero, socket finto
        self.assertGreater(log.errori["overflow_rx"], 0)
        self.assertLess(abs(float(log.t[-1]) - time.time()), 60)       # tempo del kernel, epoca
        with open(os.path.join(d, "marcatori.txt")) as f:
            fine = [r for r in f if " FINE " in r]
        self.assertEqual(len(fine), 1)
        self.assertIn("persi_socket=", fine[0])

    def _r9(self):
        open(os.path.join(self.M, "stato", "attivo_r9-can-correlation"), "w").close()
        return self.c.Scatola(self.c.configurazione(os.path.join(self.M, "nessuno.json")), "r9")

    def _prese(self, mappa):
        S = os.path.join(self.M, "sys")
        for nome, spi in mappa.items():
            os.makedirs(os.path.join(S, "devices", spi), exist_ok=True)
            os.makedirs(os.path.join(S, "class", "net", nome), exist_ok=True)
            os.symlink(os.path.join(S, "devices", spi), os.path.join(S, "class", "net", nome, "device"))
        os.environ["DVTOOL_SYS"] = S
        self.addCleanup(os.environ.pop, "DVTOOL_SYS", None)

    def _niente_cambiato(self):
        self.assertTrue(os.path.exists(os.path.join(self.M, "stato", "attivo_r9-can-correlation")))
        reg = os.path.join(self.M, "stato", "registro")
        self.assertFalse(os.path.exists(reg) and leggi_testo(reg).strip(), "comandi eseguiti sulla scatola")

    def test_prova_registratore_non_cambia_niente(self):
        import glob
        prima = set(glob.glob("/tmp/dvtool_prova.*"))
        sc = self._r9()
        self._prese({"can0": "spi1.2", "can1": "spi1.1"})
        r = self.c.op_prova_registratore(sc, 3)
        self.assertTrue(r["ok"], r)
        R = r["riassunto"]
        self.assertGreater(R["frame"], 300)
        self.assertGreater(R["overflow"], 0)
        self.assertGreaterEqual(R["persi_socket"], 1)
        self.assertTrue(R["tempo_kernel"])
        self.assertTrue(any("perso" in g for g in r["giudizio"]))
        self._niente_cambiato()
        self.assertEqual(set(glob.glob("/tmp/dvtool_prova.*")), prima)    # cartella temporanea cancellata
        self.assertFalse(os.path.exists(os.path.join(self.M, "home", "catture_ducati")))
        self.assertTrue(self.c.op_stato(sc)["presa_ok"])

    def test_porte_scambiate_dopo_avvio(self):
        sc = self._r9()
        self._prese({"can0": "spi1.1", "can1": "spi1.2"})   # can1 è finito sul morsetto della lambda
        st = self.c.op_stato(sc)
        self.assertEqual(st["prese"], {"can0": "spi1.1", "can1": "spi1.2"})
        self.assertFalse(st["presa_ok"])
        for r in (self.c.op_prepara(sc, "segreta"), self.c.op_registra(sc), self.c.op_prova_registratore(sc, 3)):
            self.assertFalse(r["ok"])
            self.assertIn("scambiat", r["errore"])
        self._niente_cambiato()
        p_can = os.path.join(self.M, "stato", "can1")
        self.assertFalse(os.path.exists(p_can) and leggi_testo(p_can).strip() == "on")

    def test_cm4_con_candump(self):
        p = os.path.join(self.M, "bin", "candump")
        with open(p, "w") as f:
            f.write("#!/bin/bash\nexec -a candump bash -c \"trap 'exit 0' INT TERM; while true; do "
                    "echo '(1.000000) can1 018#0011223344556677'; echo '(1.001000) can1 20000004#0001000000000000'; sleep 0.1; done\"\n")
        os.chmod(p, 0o755)
        d = self._ciclo("cm4", "h3d-cronometro")
        log = canlog.leggi(os.path.join(d, next(f for f in os.listdir(d) if f.endswith(".log"))))
        self.assertEqual(set(int(x) for x in log.id), {0x18})          # l'overflow non diventa l'ID 0x004
        self.assertEqual(log.errori["overflow_rx"], log.errori["n"])
        self.assertGreater(log.errori["n"], 0)


class ProvaRegistratore(unittest.TestCase):
    def test_tempo_32_e_64_bit_e_frame(self):
        import socket
        import struct
        from dvtool import registratore_can as R
        t, p = R.ancillari([(socket.SOL_SOCKET, R.SO_TIMESTAMPNS, struct.pack("qq", 1794035528, 316057053)),
                            (socket.SOL_SOCKET, R.SO_RXQ_OVFL, struct.pack("I", 7))])
        self.assertAlmostEqual(t, 1794035528.316057, places=5)
        self.assertEqual(p, 7)
        t, p = R.ancillari([(socket.SOL_SOCKET, R.SO_TIMESTAMPNS, struct.pack("ii", 1794035528, 500000000))])
        self.assertAlmostEqual(t, 1794035528.5, places=5)   # timespec a 32 bit (Raspberry Pi OS armhf)
        self.assertIsNone(p)
        fr = lambda i, d: struct.pack("=IB3x8s", i, len(d), bytes(d).ljust(8, b"\0"))
        self.assertEqual(R.riga(fr(0x018, range(8)), 1.5, "can1"), ("(1.500000) can1 018#0001020304050607\n", False, False))
        self.assertEqual(R.riga(fr(0x20000004, [0, 1, 0, 0, 0, 0, 0, 0]), 1.5, "can1")[1:], (True, True))
        self.assertTrue(R.riga(fr(0x20000004, [0, 1, 0, 0, 0, 0, 0, 0]), 1.5, "can1")[0].startswith("(1.500000) can1 20000004#0001"))
        self.assertEqual(R.riga(fr(0x80000000 | 0x18DAF110, [1, 2]), 2.0, "can1")[0], "(2.000000) can1 18DAF110#0102\n")
        self.assertEqual(R.riga(fr(0x40000000 | 0x123, []), 2.0, "can1")[0], "(2.000000) can1 123#R\n")


class ProvaFineAFine(unittest.TestCase):
    def test_demo_sessione_e_js(self):
        cart = tempfile.mkdtemp()
        try:
            synth.genera(cart)
            prof = leggi_json((os.path.join(cart, "profilo_demo.json")))
            M = leggi_json((os.path.join(cart, "modello_demo.json")))
            with open(os.path.join(cart, "demo_NOSLICK.bin"), "rb") as f:
                buf = f.read()
            S0 = leggi_json((os.path.join(cart, "struttura_demo.json")))
            S = calib.risolvi(S0, calib.trova_variante(S0, buf))
            with open(os.path.join(cart, "marcatori.txt"), "w") as f:
                f.write("1762430460.5 TC cambiato da 2 a 3\n1000.0 fuori dalla cattura\n")
            s = sessione.crea(os.path.join(cart, "demo_log.candump"), prof, cart, M, S, buf)
            self.assertEqual([m["testo"] for m in s["meta"]["marcatori"]], ["TC cambiato da 2 a 3"])
            os.remove(os.path.join(cart, "marcatori.txt"))
            sessione.salva(s, os.path.join(cart, "sessione_demo.json.gz"))
            self.assertGreater(s["modello"]["osservati"][0]["concordanza"], 0.9)
            self.assertEqual(sum(1 for g in s["giri"]["giri"] if g["tipo"] == "lanciato"), 5)
            if shutil.which("node"):
                r = subprocess.run(["node", os.path.join(QUI, "parita_js.js"), cart], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        finally:
            shutil.rmtree(cart)

    def test_pacchetto(self):
        cart = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(cart, "src"))
            with open(os.path.join(cart, "src", "a.dbc"), "w") as f:
                f.write("VERSION \"\"\n")
            z = os.path.join(cart, "p.zip")
            m = pacchetto.crea([{"da": os.path.join(cart, "src", "*.dbc"), "in": "can"}, {"da": os.path.join(cart, "manca", "*")}], z)
            self.assertEqual(len(m["file"]), 1)
            self.assertEqual(len(m["non_trovati"]), 1)
            r = pacchetto.apri(z, os.path.join(cart, "dest"))
            self.assertTrue(os.path.exists(os.path.join(cart, "dest", "can", "a.dbc")))
            self.assertEqual(r["errori"], [])
        finally:
            shutil.rmtree(cart)

    def test_modelli_da_compilare_si_caricano(self):
        es = os.path.join(os.path.dirname(QUI), "esempi")
        S = leggi_json((os.path.join(es, "struttura_da_compilare.json")))
        M = leggi_json((os.path.join(es, "modello_da_compilare.json")))
        self.assertEqual(len(calib.elenco(S)), len(S["tabelle"]))
        self.assertEqual(len(model.ordina(M)), len(M["blocchi"]))
        leggi_json((os.path.join(es, "profilo_ducati_v4.json")))


if __name__ == "__main__":
    unittest.main()
