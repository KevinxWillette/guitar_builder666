"""The librarian — keeps the vault's stacks in order.

Every picture that enters the vault is fingerprinted into the ledger and
catalogued in the index. The librarian is also the only door into the
vault: :meth:`Librarian.take_in` is what moves a picture from the ordinary
world into the private one, and it screens on the way in so that anything
personal ends up in quarantine rather than in the public pipeline.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..config import SUPPORTED_EXTENSIONS
from . import screen
from .config import VaultSettings
from .crypto import shred
from .ledger import Ledger


class Librarian:
    def __init__(self, settings: VaultSettings | None = None) -> None:
        self.settings = settings or VaultSettings()
        self.settings.ensure()
        self.ledger = Ledger(self.settings)
        self._index = self._load_index()

    # ---------------------------------------------------------------- index
    def _load_index(self) -> dict:
        path = self.settings.index_path
        if path.exists():
            try:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, json.JSONDecodeError):
                pass
        return {"version": 1, "items": []}

    def save(self) -> None:
        self.settings.meta_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.settings.index_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._index, fh, indent=2)
        tmp.replace(self.settings.index_path)
        self.ledger.save()

    @property
    def items(self) -> list[dict]:
        return self._index["items"]

    # ----------------------------------------------------------- taking in
    def take_in(self, source: Path, *, move: bool = False,
                tags: list[str] | None = None,
                note: str | None = None) -> dict:
        """Bring one picture into the vault.

        The safety screen runs first: a clear picture lands in
        ``originals/``, anything flagged or blocked lands in
        ``quarantine/`` and is marked so no pipeline will pick it up.
        """
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(source)
        report = screen.screen_image(source)
        destination_dir = (
            self.settings.originals_dir
            if report.verdict == screen.CLEAR
            else self.settings.quarantine_dir
        )
        destination = _unique(destination_dir / source.name)
        if move:
            shutil.move(str(source), str(destination))
        else:
            shutil.copy2(str(source), str(destination))

        entry = self.ledger.record(
            destination, origin=str(source), note=note
        )
        item = {
            "id": entry["sha1"][:12],
            "name": destination.name,
            "path": destination.relative_to(self.settings.vault_dir).as_posix(),
            "sha1": entry["sha1"],
            "dhash": entry["dhash"],
            "verdict": report.verdict,
            "reasons": report.reasons,
            "screen": report.details,
            "tags": sorted(tags or []),
            "note": note,
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.items.append(item)
        self.save()
        return item

    def take_in_tree(self, source_dir: Path, *, move: bool = False,
                     tags: list[str] | None = None) -> list[dict]:
        taken = []
        for path in sorted(Path(source_dir).rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                if self.settings.contains(path):
                    continue
                taken.append(self.take_in(path, move=move, tags=tags))
        return taken

    # ------------------------------------------------------------- lookups
    def find(self, query: str = "", *, verdict: str | None = None,
             tag: str | None = None) -> list[dict]:
        needle = query.lower().strip()
        out = []
        for item in self.items:
            if verdict and item["verdict"] != verdict:
                continue
            if tag and tag not in item["tags"]:
                continue
            haystack = " ".join(
                [item["name"], item.get("note") or "", " ".join(item["tags"])]
            ).lower()
            if needle and needle not in haystack:
                continue
            out.append(item)
        return out

    def get(self, item_id: str) -> dict | None:
        for item in self.items:
            if item["id"] == item_id or item["sha1"] == item_id:
                return item
        return None

    def resolve(self, item: dict) -> Path:
        return self.settings.vault_dir / item["path"]

    # ------------------------------------------------------------- actions
    def release(self, item_id: str, destination: Path) -> Path:
        """Move a quarantined picture back out, deliberately.

        The ledger entry stays: a released picture is still remembered, so
        the commit guard will still recognise it if it later turns up in a
        commit by accident.
        """
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        source = self.resolve(item)
        destination = Path(destination)
        if destination.is_dir():
            destination = destination / source.name
        destination = _unique(destination)
        shutil.move(str(source), str(destination))
        item["released_to"] = str(destination)
        item["released_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.save()
        return destination

    def forget(self, item_id: str) -> bool:
        """Shred a picture. Its fingerprint stays in the ledger."""
        item = self.get(item_id)
        if item is None:
            return False
        path = self.resolve(item)
        if path.exists():
            shred(path)
        item["shredded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.save()
        return True

    def stats(self) -> dict:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item["verdict"]] = counts.get(item["verdict"], 0) + 1
        return {
            "items": len(self.items),
            "by_verdict": counts,
            "ledger_fingerprints": len(self.ledger.entries),
            "galleries": sum(
                1 for p in self.settings.galleries_dir.glob("*/gallery.json")
            ),
        }


def _unique(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1
