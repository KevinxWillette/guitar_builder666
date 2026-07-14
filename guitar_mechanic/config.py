"""Shared configuration for the guitar mechanic pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Canonical resolution of the component library. Every processed component is
# rendered at this many pixels per real-world inch so that parts from
# different photos fit together on the same guitar canvas.
DEFAULT_PPI = 48

# Longest real-world dimension (in inches) of each component category. The
# scaler resizes a sliced component so its longest side spans this many
# inches at the library PPI. Values are typical electric-guitar sizes.
COMPONENT_DIMENSIONS_IN = {
    "body": 18.0,
    "neck": 21.0,
    "headstock": 8.0,
    "pickguard": 11.5,
    "pickup_humbucker": 3.5,
    "pickup_single_coil": 3.3,
    "pickup": 3.4,
    "bridge": 3.2,
    "tailpiece": 4.0,
    "tuner": 1.8,
    "knob": 1.0,
    "nut": 1.7,
    "switch": 3.0,
    "jack_plate": 1.5,
    "strap_button": 0.6,
    "tremolo_arm": 6.0,
    "truss_rod_cover": 2.5,
    "string_tree": 0.8,
}

# Pixel size used for components the classifier can't identify: the longest
# side is normalised to this instead of a real-world dimension.
UNKNOWN_LONGEST_PX = 800

# Filename keywords -> category. Checked longest-keyword-first so
# "humbucker_pickup" beats plain "pickup".
CATEGORY_KEYWORDS = {
    "humbucker": "pickup_humbucker",
    "single_coil": "pickup_single_coil",
    "singlecoil": "pickup_single_coil",
    "p90": "pickup_single_coil",
    "pickup": "pickup",
    "pickguard": "pickguard",
    "scratchplate": "pickguard",
    "body": "body",
    "neck": "neck",
    "headstock": "headstock",
    "fretboard": "neck",
    "fingerboard": "neck",
    "bridge": "bridge",
    "tremolo_arm": "tremolo_arm",
    "whammy": "tremolo_arm",
    "tremolo": "bridge",
    "tailpiece": "tailpiece",
    "tuner": "tuner",
    "machine_head": "tuner",
    "machinehead": "tuner",
    "peg": "tuner",
    "knob": "knob",
    "pot": "knob",
    "nut": "nut",
    "switch": "switch",
    "selector": "switch",
    "jack": "jack_plate",
    "strap_button": "strap_button",
    "strap": "strap_button",
    "truss": "truss_rod_cover",
    "string_tree": "string_tree",
}

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

# Category -> assembly slot on the builder canvas. Slots are the positions a
# part can occupy on the guitar; the builder lets you swap any part within
# its slot.
CATEGORY_SLOTS = {
    "body": "body",
    "neck": "neck",
    "headstock": "headstock",
    "pickguard": "pickguard",
    "pickup_humbucker": "pickup",
    "pickup_single_coil": "pickup",
    "pickup": "pickup",
    "bridge": "bridge",
    "tailpiece": "bridge",
    "knob": "knob",
    "switch": "switch",
    "tuner": "tuner",
}
DEFAULT_SLOT = "other"

THUMBNAIL_SIZE = 256


@dataclass
class Settings:
    """Runtime settings for one mechanic session."""

    root: Path = field(default_factory=Path.cwd)
    ppi: int = DEFAULT_PPI
    category_override: str | None = None

    @property
    def uploads_dir(self) -> Path:
        return self.root / "uploads"

    @property
    def done_dir(self) -> Path:
        return self.uploads_dir / "_done"

    @property
    def failed_dir(self) -> Path:
        return self.uploads_dir / "_failed"

    @property
    def library_dir(self) -> Path:
        return self.root / "library"

    @property
    def manifest_path(self) -> Path:
        return self.library_dir / "manifest.json"

    def ensure_dirs(self) -> None:
        for d in (self.uploads_dir, self.done_dir, self.failed_dir, self.library_dir):
            d.mkdir(parents=True, exist_ok=True)
