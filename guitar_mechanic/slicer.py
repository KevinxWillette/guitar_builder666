"""Stage 2 — the slicer.

Cuts the component out of its background and returns a tightly-cropped RGBA
image with a transparent background.

Strategy: product photos are almost always shot on a plain-ish backdrop, so
the background is whatever colour touches the image border. The slicer
samples the border, flood-fills every border-connected pixel that looks like
that backdrop, and keeps the rest as the part. If ``rembg`` happens to be
installed it is used instead for tougher, busy backgrounds.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

# Working resolution for mask computation. The mask is computed small and
# fast, then refined at full resolution.
MASK_SIDE = 640

# A border pixel within this colour distance of the dominant border colour
# is treated as a flood-fill seed; connected pixels within GROW_TOLERANCE
# join the background region.
SEED_TOLERANCE = 28.0
GROW_TOLERANCE = 42.0

# Padding (fraction of longest side) kept around the sliced part.
CROP_MARGIN = 0.02


def slice_component(image: Image.Image) -> Image.Image:
    """Return the component cut out of *image* as a cropped RGBA image."""
    rgba = _rembg_cutout(image)
    if rgba is None:
        rgba = _best_cutout(image)
    return _crop_to_alpha(rgba)


def _best_cutout(image: Image.Image) -> Image.Image:
    """Run both classical engines and keep the tighter believable mask.

    GrabCut wins on gradient studio backdrops; border flood wins on flat
    bright ones. Over-inclusion (keeping backdrop) is the common failure
    for both, so among valid candidates the smaller foreground is the
    better cut.
    """
    candidates = []
    for cutout in (_grabcut_cutout, _border_flood_cutout):
        rgba = cutout(image)
        if rgba is None:
            continue
        fill = (np.asarray(rgba.split()[3]) > 16).mean()
        if 0.01 <= fill <= 0.98:
            candidates.append((fill, rgba))
    if not candidates:
        return _border_flood_cutout(image)
    return min(candidates, key=lambda c: c[0])[1]


def _grabcut_cutout(image: Image.Image) -> Image.Image | None:
    """GrabCut with a border-is-background prior.

    Models foreground/background colour distributions, so it handles the
    gradient studio backdrops product photos love — and classifies enclosed
    background holes (between strings, headstock scoops) correctly, which
    border flood fill fundamentally can't.
    """
    try:
        import cv2
    except ImportError:
        return None
    img = image.convert("RGB")
    small = img.copy()
    small.thumbnail((MASK_SIDE, MASK_SIDE), Image.BILINEAR)
    bgr = np.asarray(small)[:, :, ::-1].copy()
    h, w = bgr.shape[:2]
    border = max(min(h, w) // 40, 4)

    mask = np.full((h, w), cv2.GC_PR_FGD, dtype=np.uint8)
    mask[:border, :] = cv2.GC_BGD
    mask[-border:, :] = cv2.GC_BGD
    mask[:, :border] = cv2.GC_BGD
    mask[:, -border:] = cv2.GC_BGD

    bg_model = np.zeros((1, 65), np.float64)
    fg_model = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(bgr, mask, None, bg_model, fg_model, 5, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return None
    fg = np.isin(mask, (cv2.GC_FGD, cv2.GC_PR_FGD))
    # Sanity: a believable subject fills some of the frame but not all of it.
    fill = fg.mean()
    if not 0.02 <= fill <= 0.98:
        return None

    fg = _binary_open(fg, iterations=1)
    fg = _binary_close(fg, iterations=2)
    mask_small = Image.fromarray((fg * 255).astype(np.uint8), mode="L")
    mask_full = mask_small.resize(img.size, Image.BILINEAR)
    mask_full = mask_full.filter(ImageFilter.GaussianBlur(radius=1.2))
    rgba = img.convert("RGBA")
    rgba.putalpha(mask_full)
    return rgba


def _rembg_cutout(image: Image.Image) -> Image.Image | None:
    """Use rembg's ML matting when available; None means fall back."""
    try:
        from rembg import remove  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return remove(image).convert("RGBA")
    except Exception:
        return None


def _border_flood_cutout(image: Image.Image) -> Image.Image:
    img = image.convert("RGB")
    small = img.copy()
    small.thumbnail((MASK_SIDE, MASK_SIDE), Image.BILINEAR)
    arr = np.asarray(small, dtype=np.float32)
    h, w = arr.shape[:2]

    border = np.concatenate(
        [arr[0, :], arr[-1, :], arr[:, 0], arr[:, -1]], axis=0
    )
    bg_color = np.median(border, axis=0)
    dist = np.linalg.norm(arr - bg_color, axis=2)

    seeds = np.zeros((h, w), dtype=bool)
    for sl in ((0, slice(None)), (-1, slice(None)), (slice(None), 0), (slice(None), -1)):
        edge = dist[sl] < SEED_TOLERANCE
        seeds[sl] |= edge

    background = _flood(seeds, dist < GROW_TOLERANCE)
    background |= _enclosed_backdrop(background, dist < GROW_TOLERANCE)
    foreground = ~background
    foreground = _binary_open(foreground, iterations=2)
    foreground = _binary_close(foreground, iterations=3)

    if not foreground.any():
        # Backdrop detection failed (part fills the frame, or busy
        # background) — keep everything rather than return nothing.
        foreground = np.ones((h, w), dtype=bool)

    mask_small = Image.fromarray((foreground * 255).astype(np.uint8), mode="L")
    mask = mask_small.resize(img.size, Image.BILINEAR)
    # Feather the cut edge slightly so the part composites cleanly.
    mask = mask.filter(ImageFilter.GaussianBlur(radius=1.2))

    rgba = img.convert("RGBA")
    rgba.putalpha(mask)
    return rgba


def _enclosed_backdrop(background: np.ndarray, backdrop_like: np.ndarray) -> np.ndarray:
    """Backdrop showing through enclosed holes (headstock scoops, gaps).

    Flood fill can't reach regions the part fully surrounds; any blob of
    strongly backdrop-coloured pixels that isn't already background is one
    of those windows.
    """
    try:
        from scipy import ndimage
    except ImportError:
        return np.zeros_like(background)
    candidates = backdrop_like & ~background
    labels, count = ndimage.label(candidates)
    if not count:
        return candidates & False
    keep = np.zeros_like(background)
    min_area = max(int(background.size * 0.0005), 8)
    sizes = ndimage.sum_labels(np.ones_like(labels), labels, range(1, count + 1))
    for i, size in enumerate(sizes, start=1):
        if size >= min_area:
            keep |= labels == i
    return keep


def _flood(seeds: np.ndarray, allowed: np.ndarray) -> np.ndarray:
    """Grow *seeds* through 4-connected *allowed* pixels until stable."""
    region = seeds & allowed
    while True:
        grown = region.copy()
        grown[1:, :] |= region[:-1, :]
        grown[:-1, :] |= region[1:, :]
        grown[:, 1:] |= region[:, :-1]
        grown[:, :-1] |= region[:, 1:]
        grown &= allowed
        if (grown == region).all():
            return region
        region = grown


def _shift_or(mask: np.ndarray) -> np.ndarray:
    out = mask.copy()
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def _shift_and(mask: np.ndarray) -> np.ndarray:
    out = mask.copy()
    out[1:, :] &= mask[:-1, :]
    out[:-1, :] &= mask[1:, :]
    out[:, 1:] &= mask[:, :-1]
    out[:, :-1] &= mask[:, 1:]
    return out


def _binary_open(mask: np.ndarray, iterations: int) -> np.ndarray:
    for _ in range(iterations):
        mask = _shift_and(mask)
    for _ in range(iterations):
        mask = _shift_or(mask)
    return mask


def _binary_close(mask: np.ndarray, iterations: int) -> np.ndarray:
    for _ in range(iterations):
        mask = _shift_or(mask)
    for _ in range(iterations):
        mask = _shift_and(mask)
    return mask


def _crop_to_alpha(rgba: Image.Image) -> Image.Image:
    alpha = np.asarray(rgba.split()[3])
    solid = alpha > 16
    if not solid.any():
        return rgba
    rows = np.flatnonzero(solid.any(axis=1))
    cols = np.flatnonzero(solid.any(axis=0))
    margin = int(max(rgba.size) * CROP_MARGIN)
    top = max(int(rows[0]) - margin, 0)
    bottom = min(int(rows[-1]) + 1 + margin, rgba.height)
    left = max(int(cols[0]) - margin, 0)
    right = min(int(cols[-1]) + 1 + margin, rgba.width)
    return rgba.crop((left, top, right, bottom))
