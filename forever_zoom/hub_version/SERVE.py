"""Forever Zoom server — hub + infinite canvas + video board."""
from __future__ import annotations

import http.server
import os
import socket
import subprocess
import threading
from pathlib import Path

PORT = 17892
CANVAS_HOME = Path(__file__).resolve().parent
HOST = "127.0.0.1"

BROWSERS = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "Microsoft/Edge/Application/msedge.exe",
]


def find_browser() -> Path | None:
    for p in BROWSERS:
        if p and p.is_file():
            return p
    return None


def open_browser(url: str) -> None:
    browser = find_browser()
    if browser:
        subprocess.Popen([str(browser), "--new-window", url], close_fds=True)
    else:
        os.startfile(url)  # type: ignore[attr-defined]


def main() -> int:
    os.chdir(CANVAS_HOME)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

        def log_message(self, fmt: str, *args) -> None:
            pass

    # free port if leftover
    try:
        httpd = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print(f"Port {PORT} busy — open http://127.0.0.1:{PORT}/ in Edge")
        open_browser(f"http://127.0.0.1:{PORT}/KILLY_ZOOMQUILT.html")
        return 0

    url = f"http://127.0.0.1:{PORT}/KILLY_ZOOMQUILT.html"
    hub = f"http://127.0.0.1:{PORT}/"
    print()
    print("  FOREVER ZOOM")
    print("  ============")
    print("  Infinite canvas (draw + photos + video):", url)
    print("  Hub (both boards):", hub)
    print("  Leave this window open while you work.")
    print()
    threading.Timer(0.4, lambda: open_browser(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
