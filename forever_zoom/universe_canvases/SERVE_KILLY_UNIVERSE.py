"""
Killy Universe canvas server — always opens in Chrome or Edge, never Internet Explorer.
Double-click OPEN_KILLY_UNIVERSE.bat on Desktop.
"""
from __future__ import annotations

import http.server
import os
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

PORT = 17890
CANVAS_DIR = Path(__file__).resolve().parent
INDEX = CANVAS_DIR / "index.html"

BROWSERS = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LocalAppData", ""))
    / "Google/Chrome/Application/chrome.exe",
]


def find_browser() -> Path | None:
    for p in BROWSERS:
        if p and p.is_file():
            return p
    return None


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def open_browser(url: str) -> None:
    browser = find_browser()
    if browser:
        subprocess.Popen([str(browser), url], close_fds=True)
    else:
        webbrowser.open(url)


def main() -> int:
    if not CANVAS_DIR.is_dir():
        print(f"MISSING FOLDER: {CANVAS_DIR}")
        input("Press Enter to close...")
        return 1
    if not INDEX.is_file():
        print(f"MISSING: {INDEX}")
        input("Press Enter to close...")
        return 1

    port = PORT
    if not port_free(port):
        url = f"http://127.0.0.1:{port}/index.html"
        print()
        print("  Server already running.")
        print(f"  Opening: {url}")
        print()
        open_browser(url)
        input("Press Enter to close this window...")
        return 0

    while not port_free(port) and port < PORT + 20:
        port += 1
    if not port_free(port):
        print(f"No free port near {PORT}")
        input("Press Enter to close...")
        return 1

    os.chdir(CANVAS_DIR)

    class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            super().end_headers()

        def log_message(self, fmt: str, *args) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), NoCacheHandler)

    url = f"http://127.0.0.1:{port}/index.html"
    print()
    print("  KILLY UNIVERSE CANVASES")
    print("  =======================")
    print(f"  Serving: {CANVAS_DIR}")
    print(f"  Open:    {url}")
    print()
    print("  Leave this window open while you use the canvases.")
    print("  Close this window when done.")
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