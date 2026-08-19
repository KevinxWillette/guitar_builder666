"""Component-type detection.

The mechanic needs to know what a part is before it can scale it to
real-world size. Detection is deliberately cheap and transparent:

1. Filename keywords ("strat_body.jpg", "gold-humbucker.png", ...).
2. A shape heuristic on the sliced silhouette as a fallback — necks are the
   only part with an extreme aspect ratio.
3. Otherwise the part is filed as ``unknown`` and normalised to a default
   pixel size; the category can be corrected later with --category.
"""

from __future__ import annotations

import re
from pathlib import Path

from .config import CATEGORY_KEYWORDS


def classify_filename(name: str) -> str | None:
    """Return a category from filename keywords, or None."""
    # Strip the extension first — "peg" (-> tuner) hides inside "jpeg", and
    # extensions never carry part-type meaning.
    stem = Path(name).stem
    slug = re.sub(r"[^a-z0-9]+", "_", stem.lower())
    # Longest keywords first so compound names win over their substrings.
    for keyword in sorted(CATEGORY_KEYWORDS, key=len, reverse=True):
        if keyword in slug:
            return CATEGORY_KEYWORDS[keyword]
    return None


def classify_shape(width: int, height: int) -> str | None:
    """Fallback silhouette heuristic based on the sliced bounding box."""
    if width <= 0 or height <= 0:
        return None
    long_side = max(width, height)
    short_side = min(width, height)
    aspect = long_side / short_side
    if aspect >= 4.5:
        return "neck"
    return None


def classify(name: str, width: int = 0, height: int = 0) -> str:
    """Best-effort category for an uploaded component image."""
    return (
        classify_filename(name)
        or classify_shape(width, height)
        or "unknown"
    )
