"""Server locale per il visualizzatore e la Guida.

  python -m dvtool visualizza <cartella_progetto>     solo il visualizzatore
  python -m dvtool guida                              Guida passo per passo + visualizzatore sul progetto privato/progetto

Serve la pagina (cartella viewer/) e, sotto /progetto/, i file della cartella del progetto.
Ascolta solo su 127.0.0.1: niente esce dal PC. Le azioni della Guida (/api/...) chiedono un codice casuale
creato a ogni avvio e accettano solo richieste rivolte a 127.0.0.1/localhost (difesa da pagine web estranee).
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import posixpath
import secrets
import threading
import urllib.parse
import webbrowser

VIEWER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "viewer")

TIPI = {".js": "text/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8", ".json": "application/json",
        ".gz": "application/gzip", ".bin": "application/octet-stream", ".svg": "image/svg+xml"}


class Gestore(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, progetto=None, codice=None, guida=False, porta=None, **kw):
        self.progetto = progetto
        self.codice = codice
        self.guida = guida
        self.porta = porta
        super().__init__(*a, directory=VIEWER, **kw)

    # --- sicurezza: solo richieste a 127.0.0.1/localhost su questa porta
    def _host_ok(self):
        h = (self.headers.get("Host") or "").lower()
        return h in (f"127.0.0.1:{self.porta}", f"localhost:{self.porta}")

    def _json(self, stato, dati):
        corpo = json.dumps(dati, ensure_ascii=False).encode("utf-8")
        self.send_response(stato)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if not self._host_ok():
            self.send_error(403)
            return
        p = urllib.parse.urlsplit(self.path).path
        if p == "/api/codice":
            # leggibile solo da pagine servite da qui (stessa origine): una pagina estranea non può leggerlo
            return self._json(200, {"codice": self.codice, "guida": self.guida})
        if p.startswith("/api/"):
            if not self.guida or self.headers.get("X-Dvtool-Codice") != self.codice:
                return self._json(403, {"ok": False, "errore": "codice mancante"})
            from . import guida
            stato, dati = guida.gestisci("GET", p, {})
            return self._json(stato, dati)
        return super().do_GET()

    def do_POST(self):
        if not self._host_ok() or not self.guida or self.headers.get("X-Dvtool-Codice") != self.codice:
            return self._json(403, {"ok": False, "errore": "non autorizzato"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            corpo = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json(400, {"ok": False, "errore": "JSON non valido"})
        from . import guida
        stato, dati = guida.gestisci("POST", urllib.parse.urlsplit(self.path).path, corpo)
        return self._json(stato, dati)

    def translate_path(self, path):
        p = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
        if p.startswith("/progetto/"):
            rel = posixpath.normpath(p[len("/progetto/"):]).lstrip("/")
            if rel.startswith(".."):
                return os.path.join(self.progetto, "__vietato__")
            return os.path.join(self.progetto, *rel.split("/"))
        return super().translate_path(path)

    def guess_type(self, path):
        return TIPI.get(os.path.splitext(path)[1].lower(), super().guess_type(path))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def avvia(cartella: str, porta: int = 8765, apri_browser: bool = True, guida: bool = False):
    cartella = os.path.abspath(cartella)
    os.makedirs(cartella, exist_ok=True)
    if not guida and not os.path.exists(os.path.join(cartella, "progetto.json")):
        print(f"! in {cartella} non c'è progetto.json: la pagina si apre vuota, trascina i file nella finestra")
    codice = secrets.token_urlsafe(24)
    gestore = functools.partial(Gestore, progetto=cartella, codice=codice, guida=guida, porta=porta)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", porta), gestore)
    url = f"http://127.0.0.1:{porta}/" + ("guida.html" if guida else "")
    print(f"{'Guida' if guida else 'Visualizzatore'} su {url}  (progetto: {cartella})  — chiudi questa finestra per uscire")
    if apri_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
