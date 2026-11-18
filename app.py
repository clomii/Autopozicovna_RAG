"""Local web server for the car rental RAG assignment."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Timer
from urllib.parse import quote, unquote, urlsplit
import json
import webbrowser

from rag.pipeline import Pipeline

BASE = Path(__file__).resolve().parent
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, pipeline, snapshot, with_vectors):
        self.pipeline = pipeline
        self.snapshot = snapshot
        self.with_vectors = with_vectors
        self.busy = Lock()
        self.building = False
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "MotorRentRAG/1.0"

    def _allowed_host(self):
        return self.headers.get("Host") in {
            f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"
        }

    def _send(self, status, payload, mime, headers=None, head=False):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self'; script-src 'self'; "
                         "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; object-src 'none'")
        for name, val in (headers or {}).items():
            self.send_header(name, val)
        self.end_headers()
        if not head:
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _json(self, data, status=200):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", head=self.command == "HEAD")

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        if not self._allowed_host():
            self._json({"error": "Aplikácia je dostupná len na localhost."}, 403)
            return
        path = urlsplit(self.path).path
        if path in STATIC:
            name, mime = STATIC[path]
            self._send(200, (BASE / "web" / name).read_bytes(), mime, head=head)
            return
        if path == "/api/status":
            self._json(self.server.pipeline.status(self.server.snapshot, self.server.building))
            return
        if path.startswith("/sources/"):
            name = unquote(path.removeprefix("/sources/"))
            source = next((s for s in self.server.snapshot.corpus.sources if s.file == name), None)
            if source is not None:
                folder = BASE / "data" / ("pdfs" if source.kind == "pdf" else "ontology")
                location = (folder / name).resolve()
                if location.parent == folder.resolve() and location.is_file():
                    mime = "application/pdf" if source.kind == "pdf" else "application/octet-stream"
                    disposition = "inline" if source.kind == "pdf" else "attachment"
                    self._send(200, location.read_bytes(), mime, {
                        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}",
                    }, head=head)
                    return
        self._json({"error": "Táto adresa neexistuje."}, 404)

    def do_POST(self):
        if not self._allowed_host() or self.headers.get("Origin") not in (
            None, f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        ):
            self._json({"error": "Povolené sú iba požiadavky z lokálnej aplikácie."}, 403)
            return
        path = urlsplit(self.path).path
        if path not in {"/api/ask", "/api/reindex"}:
            self._json({"error": "Táto adresa neexistuje."}, 404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192 or self.headers.get_content_type() != "application/json":
                raise ValueError
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, OSError):
            self._json({"error": "Očakáva sa malý JSON objekt."}, 400)
            return
        question = payload.get("question", "")
        mode, scope = payload.get("retrieval", "hybrid"), payload.get("scope", "all")
        generate = payload.get("generate", True)
        if path == "/api/ask" and (
            not isinstance(question, str) or not 2 <= len(question.strip()) <= 500
            or mode not in ("hybrid", "lexical") or scope not in ("all", "pdf", "owl")
            or not isinstance(generate, bool)
        ):
            self._json({"error": "Zadaj otázku s dĺžkou 2 až 500 znakov a platný režim."}, 400)
            return
        if not self.server.busy.acquire(blocking=False):
            self._json({"error": "Aplikácia práve spracúva inú požiadavku. Skús o chvíľu."}, 409)
            return
        try:
            if path == "/api/reindex":
                self.server.building = True
                self.server.snapshot = self.server.pipeline.build(self.server.with_vectors, force=True)
                self._json(self.server.pipeline.status(self.server.snapshot, False))
            else:
                self._json(self.server.pipeline.ask(self.server.snapshot, question.strip(),
                                                    mode, scope, generate))
        except Exception as exc:
            self.log_error("Spracovanie zlyhalo: %s", type(exc).__name__)
            self._json({"error": "Požiadavku sa nepodarilo spracovať. Skontroluj konzolu aplikácie."}, 500)
        finally:
            self.server.building = False
            self.server.busy.release()


def main():
    args = argparse.ArgumentParser(description="Lokálny RAG: Motor Rent")
    args.add_argument("--port", type=int, default=8000)
    args.add_argument("--open", action="store_true", help="Otvor web v prehliadači.")
    args.add_argument("--lexical", action="store_true", help="Pri štarte nepočítaj vektory.")
    opt = args.parse_args()
    try:
        pipeline = Pipeline(BASE)
        print("Načítavam PDF a OWL. Pri prvom spustení môže tvorba vektorov chvíľu trvať.", flush=True)
        snapshot = pipeline.build(not opt.lexical)
        server = LocalServer(opt.port, pipeline, snapshot, not opt.lexical)
    except (OSError, ValueError) as exc:
        args.error(str(exc))
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Motor Rent RAG: {url}\n{snapshot.vector_note}\nUkončenie: Ctrl+C", flush=True)
    if opt.open:
        Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
