"""Stage 4 — the populator.

Files a finished component into the library: writes the full-resolution
RGBA cut-out and a thumbnail into ``library/<category>/`` and records the
part in ``library/manifest.json``, which the workbench viewer and any
guitar-builder frontend read as the catalogue of available parts.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .config import THUMBNAIL_SIZE, Settings


def load_manifest(settings: Settings) -> dict:
    if settings.manifest_path.exists():
        with open(settings.manifest_path, encoding="utf-8") as fh:
            return json.load(fh)
    return {"version": 1, "ppi": settings.ppi, "components": []}


def save_manifest(settings: Settings, manifest: dict) -> None:
    settings.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings.manifest_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    tmp.replace(settings.manifest_path)


def known_hashes(manifest: dict) -> set[str]:
    return {c["source_sha1"] for c in manifest["components"] if c.get("source_sha1")}


def populate(
    settings: Settings,
    manifest: dict,
    image: Image.Image,
    *,
    source_name: str,
    source_sha1: str,
    category: str,
    inches: float | None,
    slot: str | None = None,
    anchors: dict | None = None,
    group: str | None = None,
) -> dict:
    """Write *image* into the library and append its manifest entry.

    *slot* is the assembly position on the builder canvas, *anchors* are
    attachment points in the part's own pixel frame (from the anatomy
    splitter), and *group* ties together parts cut from the same upload.
    """
    category_dir = settings.library_dir / category
    category_dir.mkdir(parents=True, exist_ok=True)

    slug = _unique_slug(category_dir, _slugify(Path(source_name).stem))
    component_path = category_dir / f"{slug}.png"
    thumb_path = category_dir / f"{slug}.thumb.png"

    image.save(component_path, "PNG")
    thumb = image.copy()
    thumb.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.LANCZOS)
    thumb.save(thumb_path, "PNG")

    entry = {
        "id": f"{category}/{slug}",
        "category": category,
        "file": component_path.relative_to(settings.library_dir).as_posix(),
        "thumbnail": thumb_path.relative_to(settings.library_dir).as_posix(),
        "width_px": image.width,
        "height_px": image.height,
        "longest_in": inches,
        "ppi": settings.ppi,
        "source": source_name,
        "source_sha1": source_sha1,
        "slot": slot,
        "anchors": anchors or {},
        "group": group,
        "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    manifest["components"].append(entry)
    return entry


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "component"


def _unique_slug(directory: Path, slug: str) -> str:
    candidate = slug
    counter = 2
    while (directory / f"{candidate}.png").exists():
        candidate = f"{slug}-{counter}"
        counter += 1
    return candidate
