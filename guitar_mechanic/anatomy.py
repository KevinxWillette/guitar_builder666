"""Guitar anatomy — discerning the parts of a whole guitar.

Given a sliced (background-removed) photo of a complete guitar, this module
applies anatomical logic to split it into its parts:

1. Find the instrument's principal axis and rotate it upright.
2. Read the silhouette's width profile down the axis. Guitar anatomy is
   distinctive: a small flare at the top (headstock), a long narrow run
   (neck), then a large flare (body).
3. Locate the nut (headstock/neck boundary, the narrowest point near the
   top) and the neck pocket (where the profile widens into the body).
4. Cut headstock, neck, and body apart — with a small overlap so they
   reassemble without seams — and record anchor points so the builder can
   lay each part exactly where it belongs.

The whole guitar is scaled to real-world proportions (a standard electric
guitar is ~39 inches long) before cutting, so parts from different photos
interchange on the assembly canvas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

FULL_GUITAR_LENGTH_IN = 39.0

# Silhouette rules that make something read as "a whole guitar":
MIN_ASPECT = 2.0          # long and thin overall
BODY_WIDTH_RATIO = 0.55   # body rows are at least this fraction of max width
MIN_BODY_FRACTION = 0.28  # body occupies this much of the total length...
MAX_BODY_FRACTION = 0.72  # ...but not nearly all of it
MAX_NECK_WIDTH_RATIO = 0.45  # the neck run must be clearly narrower than the body

# Cuts overlap by this fraction of total length so reassembly is seamless.
OVERLAP_FRACTION = 0.015

ALPHA_THRESHOLD = 16


@dataclass
class GuitarPart:
    slot: str            # "headstock" | "neck" | "body"
    image: Image.Image   # scaled RGBA cut-out
    anchors: dict        # px coords in this part's frame, see below


def split_guitar(rgba: Image.Image, ppi: int) -> list[GuitarPart] | None:
    """Split a sliced full-guitar image into anatomical parts.

    Returns None when the silhouette doesn't read as a whole guitar (the
    caller then treats the upload as a single component instead).

    Anchor conventions (all in the part's own pixel frame):
      headstock: {"bottom": [x, y]}  — joins the top of the neck
      neck:      {"top": [x, y], "bottom": [x, y]}
      body:      {"pocket": [x, y]}  — where the neck bottom lands
    """
    upright = _rotate_upright(rgba)
    if upright is None:
        return None

    scaled = _scale_to_real_world(upright, ppi)
    alpha = _mask(scaled)
    widths = _smooth(alpha.sum(axis=1).astype(np.float64))
    rows = np.flatnonzero(widths > 0)
    if rows.size < 40:
        return None
    top, bottom = int(rows[0]), int(rows[-1])
    length = bottom - top + 1

    profile = _read_profile(widths, top, bottom)
    if profile is None:
        return None
    nut_row, pocket_row = profile

    overlap = max(int(length * OVERLAP_FRACTION), 2)
    head_img, head_box = _cut(scaled, alpha, top, nut_row + overlap)
    neck_img, neck_box = _cut(scaled, alpha, nut_row - overlap, pocket_row + overlap)
    body_img, body_box = _cut(scaled, alpha, pocket_row - overlap, bottom + 1)
    if head_img is None or neck_img is None or body_img is None:
        return None

    head_cx = _centroid_x(alpha, nut_row) - head_box[0]
    neck_top_cx = _centroid_x(alpha, nut_row) - neck_box[0]
    neck_bot_cx = _centroid_x(alpha, pocket_row) - neck_box[0]
    pocket_cx = _centroid_x(alpha, pocket_row) - body_box[0]

    return [
        GuitarPart(
            "headstock",
            head_img,
            {"bottom": [head_cx, (nut_row + overlap) - head_box[1]]},
        ),
        GuitarPart(
            "neck",
            neck_img,
            {
                "top": [neck_top_cx, nut_row - neck_box[1]],
                "bottom": [neck_bot_cx, pocket_row - neck_box[1]],
            },
        ),
        GuitarPart(
            "body",
            body_img,
            {"pocket": [pocket_cx, pocket_row - body_box[1]]},
        ),
    ]


# ----------------------------------------------------------------- geometry


def _mask(rgba: Image.Image) -> np.ndarray:
    return np.asarray(rgba.split()[3]) > ALPHA_THRESHOLD


def _rotate_upright(rgba: Image.Image) -> Image.Image | None:
    """Rotate so the principal axis is vertical with the body at the bottom."""
    alpha = _mask(rgba)
    ys, xs = np.nonzero(alpha)
    if ys.size < 100:
        return None
    coords = np.stack([xs - xs.mean(), ys - ys.mean()])
    cov = coords @ coords.T / ys.size
    eigvals, eigvecs = np.linalg.eigh(cov)
    # Largest eigenvector = long axis; rotate it onto the y axis.
    vx, vy = eigvecs[:, int(np.argmax(eigvals))]
    angle = math.degrees(math.atan2(vx, vy))  # rotation that makes axis vertical
    upright = rgba.rotate(
        -angle, expand=True, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0)
    )

    # Body (the wide end) goes at the bottom.
    mask = _mask(upright)
    widths = mask.sum(axis=1)
    rows = np.flatnonzero(widths > 0)
    if rows.size == 0:
        return None
    third = max(rows.size // 3, 1)
    top_mean = widths[rows[:third]].mean()
    bottom_mean = widths[rows[-third:]].mean()
    if top_mean > bottom_mean:
        upright = upright.transpose(Image.FLIP_TOP_BOTTOM)
    return upright


def _scale_to_real_world(rgba: Image.Image, ppi: int) -> Image.Image:
    alpha = _mask(rgba)
    rows = np.flatnonzero(alpha.any(axis=1))
    length = int(rows[-1] - rows[0] + 1)
    target = FULL_GUITAR_LENGTH_IN * ppi
    factor = target / max(length, 1)
    size = (max(round(rgba.width * factor), 1), max(round(rgba.height * factor), 1))
    return rgba.resize(size, Image.LANCZOS)


def _read_profile(
    widths: np.ndarray, top: int, bottom: int
) -> tuple[int, int] | None:
    """Locate the nut and neck-pocket rows from the width profile."""
    length = bottom - top + 1
    span = widths[top : bottom + 1]
    max_w = span.max()
    if max_w <= 0:
        return None

    # Overall proportions must read as a guitar.
    cols_extent = max_w  # widths are pixel counts, a fine proxy for extent
    if length / max(cols_extent, 1) < MIN_ASPECT:
        return None

    # Body: the wide region nearest the bottom. The silhouette tapers at the
    # body's lower edge, so anchor on the last row that is genuinely wide and
    # walk up through the contiguous wide run it belongs to.
    wide = span > BODY_WIDTH_RATIO * max_w
    wide_rows = np.flatnonzero(wide)
    if wide_rows.size == 0:
        return None
    last_wide = int(wide_rows[-1])
    if (length - 1 - last_wide) > 0.18 * length:
        return None  # the wide mass isn't at the bottom — not guitar-shaped
    i = last_wide
    while i >= 0 and wide[i]:
        i -= 1
    body_start = i + 1  # first wide row of the body region (profile-relative)
    body_fraction = (length - body_start) / length
    if not (MIN_BODY_FRACTION <= body_fraction <= MAX_BODY_FRACTION):
        return None

    # Neck: the run above the body must be clearly narrower.
    neck_span = span[:body_start]
    if neck_span.size < 20:
        return None
    if np.median(neck_span[neck_span > 0]) > MAX_NECK_WIDTH_RATIO * max_w:
        return None

    # Nut: narrowest point in the upper part of the head+neck run (the
    # headstock flares above it). Search 8%..60% down that run.
    lo = max(int(body_start * 0.08), 1)
    hi = max(int(body_start * 0.60), lo + 1)
    nut = lo + int(np.argmin(neck_span[lo:hi]))

    return top + nut, top + body_start


def _cut(
    rgba: Image.Image, alpha: np.ndarray, row_from: int, row_to: int
) -> tuple[Image.Image | None, tuple[int, int]]:
    """Crop rows [row_from, row_to) tight to the silhouette.

    Returns (image, (left, top)) with the crop origin in full-image coords.
    """
    row_from = max(row_from, 0)
    row_to = min(row_to, rgba.height)
    if row_to <= row_from:
        return None, (0, 0)
    band = alpha[row_from:row_to]
    cols = np.flatnonzero(band.any(axis=0))
    if cols.size == 0:
        return None, (0, 0)
    left, right = int(cols[0]), int(cols[-1]) + 1
    img = rgba.crop((left, row_from, right, row_to))
    return img, (left, row_from)


def _centroid_x(alpha: np.ndarray, row: int) -> int:
    row = min(max(row, 0), alpha.shape[0] - 1)
    cols = np.flatnonzero(alpha[row])
    if cols.size == 0:
        # Fall back to the nearest non-empty row.
        rows = np.flatnonzero(alpha.any(axis=1))
        nearest = rows[np.argmin(np.abs(rows - row))]
        cols = np.flatnonzero(alpha[nearest])
    return int(cols.mean())


def _smooth(values: np.ndarray, window: int = 9) -> np.ndarray:
    kernel = np.ones(window) / window
    return np.convolve(values, kernel, mode="same")
