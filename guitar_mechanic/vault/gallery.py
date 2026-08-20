"""Password-locked galleries.

A gallery is a directory of encrypted blobs. Nothing readable is on disk:
the pictures, their filenames, and the prompts that made them all live
inside the ciphertext. The only cleartext is ``gallery.json``, which holds
the gallery's display name, the scrypt salt, and a verifier blob used to
tell a wrong passphrase from a corrupt file.

Consequences worth knowing before you put anything in one:

* Losing the passphrase loses the pictures. There is no recovery hatch,
  by design — a recovery hatch is also a leak.
* Unlocking writes nothing to disk. ``gallery show`` decrypts into memory
  and hands you bytes; ``gallery export`` is the only way a picture comes
  back out in the clear, and it says so out loud.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from . import crypto
from .config import VaultSettings


class GalleryError(Exception):
    pass


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise GalleryError("gallery name must contain a letter or digit")
    return slug


class Gallery:
    """An unlocked handle on a gallery. Holds the key in memory only."""

    def __init__(self, directory: Path, meta: dict, key: bytes) -> None:
        self.directory = directory
        self.meta = meta
        self._key = key

    # ------------------------------------------------------------- storage
    @property
    def name(self) -> str:
        return self.meta["name"]

    @property
    def slug(self) -> str:
        return self.meta["slug"]

    @property
    def _index_path(self) -> Path:
        return self.directory / "index.bin"

    @property
    def _items_dir(self) -> Path:
        return self.directory / "items"

    def _read_index(self) -> list[dict]:
        if not self._index_path.exists():
            return []
        raw = crypto.decrypt(self._index_path.read_bytes(), self._key)
        return json.loads(raw.decode("utf-8"))

    def _write_index(self, items: list[dict]) -> None:
        blob = crypto.encrypt(
            json.dumps(items, indent=2).encode("utf-8"), self._key
        )
        tmp = self._index_path.with_suffix(".bin.tmp")
        tmp.write_bytes(blob)
        tmp.replace(self._index_path)
        self.meta["items"] = len(items)
        _write_meta(self.directory, self.meta)

    # --------------------------------------------------------------- items
    def items(self) -> list[dict]:
        return self._read_index()

    def add_bytes(self, data: bytes, *, name: str,
                  meta: dict | None = None) -> dict:
        """Encrypt *data* into the gallery and return its index record."""
        self._items_dir.mkdir(parents=True, exist_ok=True)
        item_id = secrets.token_hex(8)
        (self._items_dir / f"{item_id}.bin").write_bytes(
            crypto.encrypt(data, self._key)
        )
        record = {
            "id": item_id,
            "name": name,
            "bytes": len(data),
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **(meta or {}),
        }
        items = self._read_index()
        items.append(record)
        self._write_index(items)
        return record

    def add_file(self, path: Path, *, shred_source: bool = False,
                 meta: dict | None = None) -> dict:
        path = Path(path)
        record = self.add_bytes(path.read_bytes(), name=path.name, meta=meta)
        if shred_source:
            crypto.shred(path)
            record = dict(record, source_shredded=True)
            items = self._read_index()
            for i, existing in enumerate(items):
                if existing["id"] == record["id"]:
                    items[i] = record
            self._write_index(items)
        return record

    def read(self, item_id: str) -> tuple[dict, bytes]:
        """Decrypt one item into memory. Nothing touches disk."""
        for record in self._read_index():
            if record["id"] == item_id or record["name"] == item_id:
                blob = (self._items_dir / f"{record['id']}.bin").read_bytes()
                return (record, crypto.decrypt(blob, self._key))
        raise GalleryError(f"no item {item_id!r} in gallery {self.slug!r}")

    def export(self, item_id: str, destination: Path) -> Path:
        """Write one item back out in the clear. The deliberate exit."""
        record, data = self.read(item_id)
        destination = Path(destination)
        if destination.is_dir():
            destination = destination / record["name"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return destination

    def remove(self, item_id: str) -> bool:
        items = self._read_index()
        kept = [i for i in items if i["id"] != item_id and i["name"] != item_id]
        if len(kept) == len(items):
            return False
        for record in items:
            if record not in kept:
                crypto.shred(self._items_dir / f"{record['id']}.bin")
        self._write_index(kept)
        return True


# ---------------------------------------------------------------- lifecycle
def _meta_path(directory: Path) -> Path:
    return directory / "gallery.json"


def _write_meta(directory: Path, meta: dict) -> None:
    tmp = _meta_path(directory).with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    tmp.replace(_meta_path(directory))


def create(settings: VaultSettings, name: str, passphrase: str) -> Gallery:
    slug = _slugify(name)
    directory = settings.galleries_dir / slug
    if _meta_path(directory).exists():
        raise GalleryError(f"gallery {slug!r} already exists")
    if len(passphrase) < 8:
        raise GalleryError("passphrase must be at least 8 characters")
    directory.mkdir(parents=True, exist_ok=True)
    salt = crypto.new_salt()
    key = crypto.derive_key(passphrase, salt)
    meta = {
        "name": name,
        "slug": slug,
        "salt": salt.hex(),
        "kdf": {"algorithm": "scrypt", "n": crypto.KDF_N,
                "r": crypto.KDF_R, "p": crypto.KDF_P},
        "verifier": crypto.make_verifier(key),
        "items": 0,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write_meta(directory, meta)
    gallery = Gallery(directory, meta, key)
    gallery._write_index([])
    return gallery


def unlock(settings: VaultSettings, name: str, passphrase: str) -> Gallery:
    slug = _slugify(name)
    directory = settings.galleries_dir / slug
    path = _meta_path(directory)
    if not path.exists():
        raise GalleryError(f"no gallery named {slug!r}")
    with open(path, encoding="utf-8") as fh:
        meta = json.load(fh)
    kdf = meta.get("kdf", {})
    key = crypto.derive_key(
        passphrase,
        bytes.fromhex(meta["salt"]),
        n=kdf.get("n", crypto.KDF_N),
        r=kdf.get("r", crypto.KDF_R),
        p=kdf.get("p", crypto.KDF_P),
    )
    if not crypto.check_verifier(meta["verifier"], key):
        raise crypto.BadPassphrase(f"wrong passphrase for gallery {slug!r}")
    return Gallery(directory, meta, key)


def listing(settings: VaultSettings) -> list[dict]:
    """Gallery names and sizes — readable without any passphrase."""
    out = []
    for path in sorted(settings.galleries_dir.glob("*/gallery.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "name": meta.get("name"),
            "slug": meta.get("slug"),
            "items": meta.get("items", 0),
            "created_at": meta.get("created_at"),
        })
    return out
