"""The mechanic — orchestrates enhance -> discern -> slice -> scale -> populate.

Every upload is enhanced and cut from its background, then the mechanic
applies anatomical logic: if the silhouette reads as a whole guitar it is
split into headstock, neck, and body (each with anchor points for the
assembly canvas); otherwise it is classified as a single component and
scaled to its real-world size.
"""

from __future__ import annotations

import hashlib
import shutil
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import anatomy, classify, enhancer, populator, scaler, slicer
from .config import CATEGORY_SLOTS, DEFAULT_SLOT, SUPPORTED_EXTENSIONS, Settings


@dataclass
class Result:
    source: Path
    status: str  # "added" | "duplicate" | "failed"
    entries: list[dict] = field(default_factory=list)
    error: str | None = None


class Mechanic:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.settings.ensure_dirs()

    # ------------------------------------------------------------------
    def pending_uploads(self) -> list[Path]:
        return sorted(
            p
            for p in self.settings.uploads_dir.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        )

    def process_all(self, log=print) -> list[Result]:
        """One pass over the uploads folder."""
        uploads = self.pending_uploads()
        if not uploads:
            return []
        manifest = populator.load_manifest(self.settings)
        seen = populator.known_hashes(manifest)
        results = [self._process_one(p, manifest, seen, log) for p in uploads]
        populator.save_manifest(self.settings, manifest)
        return results

    def process_bytes(self, data: bytes, filename: str, log=print) -> Result:
        """Process one in-memory upload (the web app's entry point)."""
        safe_name = Path(filename).name or "upload.png"
        path = self.settings.uploads_dir / safe_name
        counter = 2
        while path.exists():
            path = self.settings.uploads_dir / (
                f"{Path(safe_name).stem}-{counter}{Path(safe_name).suffix}"
            )
            counter += 1
        path.write_bytes(data)
        manifest = populator.load_manifest(self.settings)
        seen = populator.known_hashes(manifest)
        result = self._process_one(path, manifest, seen, log)
        populator.save_manifest(self.settings, manifest)
        return result

    def watch(self, interval: float = 2.0, log=print) -> None:
        """Poll the uploads folder forever, processing new arrivals."""
        log(
            f"guitar mechanic on duty — watching {self.settings.uploads_dir} "
            f"(ctrl-c to stop)"
        )
        while True:
            results = self.process_all(log)
            if results:
                added = sum(len(r.entries) for r in results)
                log(f"pass complete: {added} part(s) added to the library")
            time.sleep(interval)

    # ------------------------------------------------------------------
    def _process_one(
        self, path: Path, manifest: dict, seen: set[str], log
    ) -> Result:
        log(f"[mechanic] working on {path.name} ...")
        try:
            data = path.read_bytes()
            sha1 = hashlib.sha1(data).hexdigest()
            if sha1 in seen:
                log("[mechanic]   already in the library — skipping")
                self._move(path, self.settings.done_dir)
                return Result(path, "duplicate")

            with Image.open(path) as raw:
                enhanced = enhancer.enhance(raw)
            sliced = slicer.slice_component(enhanced)

            entries: list[dict]
            if self.settings.category_override:
                entries = [self._file_component(
                    manifest, sliced, path.name, sha1,
                    self.settings.category_override,
                )]
            else:
                parts = anatomy.split_guitar(sliced, self.settings.ppi)
                if parts:
                    log(
                        "[mechanic]   that's a whole guitar — "
                        "splitting headstock / neck / body"
                    )
                    entries = [
                        self._file_guitar_part(manifest, part, path.name, sha1)
                        for part in parts
                    ]
                else:
                    category = classify.classify(
                        path.name, sliced.width, sliced.height
                    )
                    entries = [self._file_component(
                        manifest, sliced, path.name, sha1, category
                    )]

            seen.add(sha1)
            for entry in entries:
                log(
                    f"[mechanic]   filed {entry['id']} "
                    f"({entry['width_px']}x{entry['height_px']}px, "
                    f"slot: {entry['slot']})"
                )
            self._move(path, self.settings.done_dir)
            return Result(path, "added", entries=entries)
        except Exception as exc:  # keep the shop open if one part fails
            log(f"[mechanic]   FAILED on {path.name}: {exc}")
            traceback.print_exc()
            self._move(path, self.settings.failed_dir)
            return Result(path, "failed", error=str(exc))

    def _file_guitar_part(
        self, manifest: dict, part: anatomy.GuitarPart, source: str, sha1: str
    ) -> dict:
        return populator.populate(
            self.settings,
            manifest,
            part.image,
            source_name=f"{part.slot}_{source}",
            source_sha1=sha1,
            category=part.slot,
            inches=round(max(part.image.size) / self.settings.ppi, 2),
            slot=part.slot,
            anchors=part.anchors,
            group=sha1[:10],
        )

    def _file_component(
        self, manifest: dict, sliced: Image.Image, source: str,
        sha1: str, category: str,
    ) -> dict:
        scaled, inches = scaler.scale_component(
            sliced, category, self.settings.ppi
        )
        return populator.populate(
            self.settings,
            manifest,
            scaled,
            source_name=source,
            source_sha1=sha1,
            category=category,
            inches=inches,
            slot=CATEGORY_SLOTS.get(category, DEFAULT_SLOT),
        )

    @staticmethod
    def _move(path: Path, dest_dir: Path) -> None:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / path.name
        counter = 2
        while dest.exists():
            dest = dest_dir / f"{path.stem}-{counter}{path.suffix}"
            counter += 1
        shutil.move(str(path), str(dest))
