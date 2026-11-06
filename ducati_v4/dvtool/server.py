"""Server locale per il visualizzatore: python -m dvtool visualizza <cartella_progetto>

Serve la pagina (cartella viewer/) e, sotto /progetto/, i file della cartella del progetto
(progetto.json, sessioni, struttura, modello, .bin). Ascolta solo su 127.0.0.1: niente esce dal PC.
"""
from __future__ import annotations

import functools
import http.server
import os
import posixpath
import threading
import urllib.parse
import webbrowser

VIEWER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "viewer")

TIPI = {".js": "text/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8", ".json": "application/json",
        ".gz": "application/gzip", ".bin": "application/octet-stream", ".svg": "image/svg+xml"}


class Gestore(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, progetto=None, **kw):
        self.progetto = progetto
        super().__init__(*a, directory=VIEWER, **kw)

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


def avvia(cartella: str, porta: int = 8765, apri_browser: bool = True):
    cartella = os.path.abspath(cartella)
    if not os.path.exists(os.path.join(cartella, "progetto.json")):
        print(f"! in {cartella} non c'è progetto.json: la pagina si apre vuota, trascina i file nella finestra")
    gestore = functools.partial(Gestore, progetto=cartella)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", porta), gestore)
    url = f"http://127.0.0.1:{porta}/"
    print(f"Visualizzatore su {url}  (progetto: {cartella})  — Ctrl+C per chiudere")
    if apri_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
