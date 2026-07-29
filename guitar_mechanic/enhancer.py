"""Stage 1 — the enhancer.

Takes a raw upload (phone photo, marketplace listing screenshot, scan) and
cleans it up so the slicer has good material to work with: correct EXIF
orientation, neutralise colour cast, stretch contrast, and sharpen.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# Cap working resolution; marketplace photos can be enormous and everything
# downstream only needs enough pixels for the library PPI.
MAX_SIDE = 2400


def prepare(image: Image.Image) -> Image.Image:
    """Orientation + transparency flattening only — no tonal changes.

    For clean renders and catalogue shots where colour accuracy matters
    more than correction.
    """
    img = ImageOps.exif_transpose(image)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return img


def enhance(image: Image.Image) -> Image.Image:
    """Return an enhanced RGB copy of *image*."""
    img = ImageOps.exif_transpose(image)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    # Flatten any existing transparency onto white — uploads with alpha are
    # usually catalogue cut-outs on a transparent background.
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background

    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)

    img = _gray_world_white_balance(img)
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Color(img).enhance(1.06)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=80, threshold=3))
    return img


def _gray_world_white_balance(img: Image.Image, strength: float = 0.6) -> Image.Image:
    """Mild gray-world white balance: pull channel means toward neutral.

    *strength* blends between the original (0.0) and fully balanced (1.0)
    image so the correction never overshoots on legitimately colourful parts.
    """
    arr = np.asarray(img, dtype=np.float64)
    means = arr.reshape(-1, 3).mean(axis=0)
    gray = means.mean()
    if gray <= 0:
        return img
    gains = gray / np.maximum(means, 1e-6)
    # Blend the gains toward 1.0 by (1 - strength).
    gains = 1.0 + (gains - 1.0) * strength
    balanced = np.clip(arr * gains, 0, 255).astype(np.uint8)
    return Image.fromarray(balanced, mode="RGB")
