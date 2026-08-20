"""The ledger — fingerprints of everything the vault has ever held.

Two fingerprints per file:

* **sha1** — catches an exact copy anywhere else on disk or in a commit.
* **dhash** — a 64-bit perceptual hash that survives resizing, re-encoding,
  a crop-free colour tweak, or a JPEG round-trip. This is what catches the
  real leak: a private photo that was resized for the web and no longer
  matches byte-for-byte.

The ledger stores fingerprints and notes only — never image data — and it
lives inside the vault, so it is not committed either.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import VaultSettings

DHASH_SIDE = 8            # 8x9 samples -> 64 bits
NEAR_DISTANCE = 8         # Hamming distance treated as "the same picture"


def sha1_of(path: Path) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dhash_of(path: Path) -> str | None:
    """Perceptual hash as 16 hex chars, or None if it isn't an image."""
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover - Pillow is a hard dep in practice
        return None
    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img).convert("L")
            small = img.resize((DHASH_SIDE + 1, DHASH_SIDE), Image.LANCZOS)
    except Exception:
        return None
    px = small.load()
    bits = 0
    for y in range(DHASH_SIDE):
        for x in range(DHASH_SIDE):
            bits = (bits << 1) | int(px[x + 1, y] > px[x, y])
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


class Ledger:
    """Append-mostly record of vault fingerprints."""

    def __init__(self, settings: VaultSettings) -> None:
        self.settings = settings
        self._data = self._load()

    def _load(self) -> dict:
        path = self.settings.ledger_path
        if path.exists():
            try:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, json.JSONDecodeError):
                pass
        return {"version": 1, "entries": []}

    def save(self) -> None:
        self.settings.meta_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.settings.ledger_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)
        tmp.replace(self.settings.ledger_path)

    # ------------------------------------------------------------------
    @property
    def entries(self) -> list[dict]:
        return self._data["entries"]

    def record(self, path: Path, *, origin: str = "vault",
               note: str | None = None) -> dict:
        """Fingerprint *path* and remember it. Idempotent per sha1."""
        sha1 = sha1_of(path)
        existing = self.by_sha1(sha1)
        if existing:
            return existing
        entry = {
            "sha1": sha1,
            "dhash": dhash_of(path),
            "bytes": path.stat().st_size,
            "name": path.name,
            "origin": origin,
            "note": note,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.entries.append(entry)
        return entry

    def by_sha1(self, sha1: str) -> dict | None:
        for entry in self.entries:
            if entry["sha1"] == sha1:
                return entry
        return None

    def near_matches(self, dhash: str | None,
                     max_distance: int = NEAR_DISTANCE) -> list[tuple[int, dict]]:
        """Ledger entries that look like the same picture."""
        if not dhash:
            return []
        hits = []
        for entry in self.entries:
            other = entry.get("dhash")
            if not other:
                continue
            distance = hamming(dhash, other)
            if distance <= max_distance:
                hits.append((distance, entry))
        return sorted(hits, key=lambda h: h[0])

    def match(self, path: Path) -> tuple[str, dict] | None:
        """Return ``(kind, entry)`` if *path* is vault content.

        ``kind`` is ``"exact"`` for a byte-identical copy or ``"lookalike"``
        for a resized / re-encoded one.
        """
        try:
            exact = self.by_sha1(sha1_of(path))
        except OSError:
            return None
        if exact:
            return ("exact", exact)
        hits = self.near_matches(dhash_of(path))
        if hits:
            return ("lookalike", hits[0][1])
        return None
