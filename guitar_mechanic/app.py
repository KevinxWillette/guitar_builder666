"""The guitar builder app server.

Zero-dependency HTTP server (stdlib only) that serves the builder UI and a
small JSON API the UI talks to:

    GET  /               -> the builder (webapp/index.html)
    GET  /library/...    -> processed part images + manifest
    GET  /api/manifest   -> the component library manifest
    POST /api/upload     -> raw image bytes (X-Filename header); runs the
                            full mechanic pipeline and returns the new parts

Run with:  python -m guitar_mechanic app
"""

from __future__ import annotations

import http.server
import json
import threading
from functools import partial
from pathlib import Path

from .config import Settings
from .mechanic import Mechanic

MAX_UPLOAD_BYTES = 40 * 1024 * 1024

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"


class BuilderHandler(http.server.SimpleHTTPRequestHandler):
    # Class-level, set by serve(); one mechanic shared across requests.
    mechanic: Mechanic
    lock: threading.Lock

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        if self.path in ("/", "/index.html"):
            self._send_file(WEBAPP_DIR / "index.html", "text/html; charset=utf-8")
            return
        if self.path == "/api/manifest":
            self._send_manifest()
            return
        super().do_GET()

    def _send_file(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/upload":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_UPLOAD_BYTES:
            self._send_json({"error": "upload must be 1 byte .. 40 MB"}, 400)
            return
        filename = self.headers.get("X-Filename", "upload.png")
        data = self.rfile.read(length)
        with self.lock:
            result = self.mechanic.process_bytes(data, filename)
        payload = {
            "status": result.status,
            "parts": result.entries,
            "error": result.error,
        }
        self._send_json(payload, 200 if result.status != "failed" else 422)

    # ------------------------------------------------------------------
    def _send_manifest(self) -> None:
        manifest_path = self.mechanic.settings.manifest_path
        if manifest_path.exists():
            body = manifest_path.read_bytes()
        else:
            body = json.dumps(
                {"version": 1, "ppi": self.mechanic.settings.ppi, "components": []}
            ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        # Quieten static-file noise; keep API activity visible.
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def serve(settings: Settings, port: int = 8666) -> None:
    settings.ensure_dirs()
    handler = partial(BuilderHandler, directory=str(settings.root))
    BuilderHandler.mechanic = Mechanic(settings)
    BuilderHandler.lock = threading.Lock()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"guitar builder open at http://localhost:{port}/  (ctrl-c to stop)")
    server.serve_forever()
