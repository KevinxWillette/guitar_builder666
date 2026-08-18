"""The record of what the specialists actually said.

Killy asked for one clean answer, not a wall of model chatter — so raw replies
never ride along in Claude's response. They are written here instead, keyed by
call id, and Claude can fetch one back the moment Killy asks "what did Grok
actually say?". Hiding the chatter and destroying it are different things.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


class Transcript:
    """Append-only store of specialist calls, one JSON file per call."""

    def __init__(self, directory: Path, enabled: bool = True, max_files: int = 200):
        self.directory = directory
        self.enabled = enabled
        self.max_files = max_files

    def record(self, reply: Any) -> None:
        """Write one specialist call to disk. Never raises into the caller."""
        if not self.enabled:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            payload = asdict(reply) if is_dataclass(reply) else dict(reply)
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
            path = self.directory / f"{stamp}-{payload.get('call_id', 'call')}.json"
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self._prune()
        except OSError:
            # A full disk must not take the roundtable down; the answer to
            # Killy matters more than the log of it.
            pass

    def _prune(self) -> None:
        files = sorted(self.directory.glob("*.json"))
        excess = len(files) - self.max_files
        for path in files[:excess] if excess > 0 else []:
            try:
                path.unlink()
            except OSError:
                pass

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """Summaries of the most recent calls, newest first."""
        rows: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.json"), reverse=True)[:limit]:
            data = self._read(path)
            if data is None:
                continue
            rows.append(
                {
                    "call_id": data.get("call_id"),
                    "provider": data.get("provider"),
                    "role": data.get("role"),
                    "backend": data.get("backend"),
                    "model": data.get("model"),
                    "ok": data.get("ok"),
                    "elapsed_seconds": data.get("elapsed_seconds"),
                    "file": path.name,
                }
            )
        return rows

    def get(self, call_id: str) -> dict[str, Any] | None:
        """The full record of one call, including the brief that was sent."""
        for path in sorted(self.directory.glob(f"*-{call_id}.json"), reverse=True):
            data = self._read(path)
            if data is not None:
                return data
        return None

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None


def open_transcript(settings: Any) -> Transcript:
    """Open the transcript store described by ``settings``."""
    return Transcript(
        directory=settings.state_dir / "transcripts",
        enabled=bool(settings.transcript.get("enabled", True)),
        max_files=int(settings.transcript.get("max_files", 200)),
    )
