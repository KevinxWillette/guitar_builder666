"""Wire the roundtable into the Claude Desktop app.

Claude Desktop reads its MCP servers from one JSON file. Hand-editing that file
is the single most error-prone step in the whole setup — a stray comma silently
costs you every connector you had, not just this one — so this does it: finds
the file for the platform, merges one entry in, and keeps a backup of whatever
was there before.

Two details that bite on Windows specifically. There is usually no ``python3``
command, only ``python`` or the ``py`` launcher, so the entry records
``sys.executable`` — the absolute path of the interpreter that just ran setup
successfully, which sidesteps PATH entirely. And backslashes in that path have
to survive JSON encoding, which they do here because the path is written as
data rather than pasted into a string by hand.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

SERVER_KEY = "killy-roundtable"


def config_path() -> Path:
    """Where Claude Desktop keeps its config on this platform."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def desktop_installed() -> bool:
    """True when Claude Desktop's config directory exists."""
    return config_path().parent.is_dir()


def server_entry(server_script: Path) -> dict[str, Any]:
    """The entry describing this server to Claude Desktop."""
    return {"command": sys.executable, "args": [str(server_script.resolve())]}


def read_config(path: Path) -> tuple[dict[str, Any], str | None]:
    """Load the existing config. Returns (config, problem-if-any)."""
    if not path.is_file():
        return {}, None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"could not read {path}: {exc}"
    if not text.strip():
        return {}, None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"{path} is not valid JSON ({exc}) — fix or remove it first"
    if not isinstance(data, dict):
        return {}, f"{path} does not contain a JSON object"
    return data, None


def install(server_script: Path, path: Path | None = None) -> dict[str, Any]:
    """Add (or update) the roundtable entry in Claude Desktop's config.

    Returns a summary of what happened. Never raises for the ordinary failures
    — a missing directory or an unparseable file comes back as a message the
    caller can print.
    """
    target = path or config_path()
    config, problem = read_config(target)
    if problem:
        return {"ok": False, "path": str(target), "error": problem}

    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    existing = servers.get(SERVER_KEY)
    entry = server_entry(server_script)

    if existing == entry:
        return {"ok": True, "path": str(target), "changed": False, "entry": entry,
                "siblings": sorted(k for k in servers if k != SERVER_KEY)}

    backup = None
    if target.is_file():
        backup = target.with_suffix(f".backup-{time.strftime('%Y%m%d-%H%M%S')}.json")
        try:
            shutil.copy2(target, backup)
        except OSError as exc:
            return {"ok": False, "path": str(target), "error": f"could not back up: {exc}"}

    servers[SERVER_KEY] = entry
    config["mcpServers"] = servers
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "path": str(target), "error": f"could not write: {exc}"}

    return {
        "ok": True,
        "path": str(target),
        "changed": True,
        "replaced": existing is not None,
        "backup": str(backup) if backup else None,
        "entry": entry,
        # Named so the caller can prove nothing else was disturbed.
        "siblings": sorted(k for k in servers if k != SERVER_KEY),
    }
