"""Prove automatiche:  python -m unittest discover -s tests   (dalla cartella ducati_v4)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

QUI = os.path.dirname(os.path.abspath(__file__))


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


class ProvaCalibrazione(unittest.TestCase):
    def setUp(self):
        self.S = synth.struttura_demo()
        self.buf = synth.bin_demo(self.S)

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


class ProvaFineAFine(unittest.TestCase):
    def test_demo_sessione_e_js(self):
        cart = tempfile.mkdtemp()
        try:
            synth.genera(cart)
            prof = leggi_json((os.path.join(cart, "profilo_demo.json")))
            M = leggi_json((os.path.join(cart, "modello_demo.json")))
            S = leggi_json((os.path.join(cart, "struttura_demo.json")))
            with open(os.path.join(cart, "demo_originale.bin"), "rb") as f:
                buf = f.read()
            s = sessione.crea(os.path.join(cart, "demo_log.candump"), prof, cart, M, S, buf)
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
