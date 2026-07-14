"""Guitar anatomy — discerning the parts of a whole guitar.

Given a sliced (background-removed) photo of a complete guitar, this module
applies anatomical logic to split it into its parts:

1. Find the instrument's principal axis and rotate it upright.
2. Read the silhouette's *core width profile* down the axis — the widest
   contiguous run of pixels per row. Contiguous runs matter: pointy guitars
   throw long horns up alongside the neck, and total-extent profiles mistake
   horn rows for body rows. Guitar anatomy in run-widths is distinctive:
   a flare at the top (headstock), a long narrow plateau (neck), then the
   big flare (body).
3. Locate the nut (where the headstock flare settles into the narrow neck
   plateau) and the neck pocket (where the profile widens into the body).
4. Cut headstock, neck, and body apart — the neck cut keeps only the
   central strip, so horns stay with the body — with a small overlap so
   parts reassemble without seams, and anchor points recorded so the
   builder lays each part exactly where it belongs.

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
MAX_NECK_WIDTH_RATIO = 0.45  # the neck plateau must be clearly narrower

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
    runs = _run_profile(alpha)          # (run_width, run_start, run_end) rows
    widths = _smooth(runs[:, 0].astype(np.float64))
    rows = np.flatnonzero(widths > 1)
    if rows.size < 40:
        return None
    top, bottom = int(rows[0]), int(rows[-1])
    length = bottom - top + 1

    profile = _read_profile(widths, top, bottom)
    if profile is None:
        return None
    nut_row, pocket_row = profile

    overlap = max(int(length * OVERLAP_FRACTION), 2)
    neck_widths = runs[nut_row:pocket_row, 0]
    median_neck = float(np.median(neck_widths[neck_widths > 0])) or 1.0

    # Neck: tracked downward from the nut; body flare at the joint is
    # clipped so the strip stays neck-wide. Headstock: tracked upward from
    # the nut, so horn tips that climb past the nut line stay off it.
    nut_interval = (int(runs[nut_row][1]), int(runs[nut_row][2]))
    neck_strip = _tracked_strip(
        alpha, nut_interval,
        range(max(nut_row - overlap, 0), min(pocket_row + overlap, alpha.shape[0])),
        max_width=max(2.5 * median_neck, 4.0),
    )
    head_strip = _tracked_strip(
        alpha, nut_interval,
        range(min(nut_row + overlap, alpha.shape[0] - 1), -1, -1),
        max_width=None,  # the headstock flare is legitimate growth
    )

    head_mask, body_mask = _assign_components(
        alpha, neck_strip, head_strip, nut_row
    )
    # Full material below the pocket for the reassembly overlap.
    body_mask[pocket_row - overlap :] = alpha[pocket_row - overlap :]

    head_img, head_box = _cut(scaled, head_mask)
    neck_img, neck_box = _cut(scaled, neck_strip)
    body_img, body_box = _cut(scaled, body_mask)
    if head_img is None or neck_img is None or body_img is None:
        return None

    head_cx = _centroid_x(alpha, nut_row) - head_box[0]
    neck_top_cx = _centroid_x(neck_strip, nut_row) - neck_box[0]
    neck_bot_cx = _centroid_x(neck_strip, pocket_row) - neck_box[0]
    pocket_cx = _centroid_x(neck_strip, pocket_row) - body_box[0]

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


def _run_profile(alpha: np.ndarray) -> np.ndarray:
    """Per row: (widest contiguous run width, its start col, its end col)."""
    h, w = alpha.shape
    out = np.zeros((h, 3), dtype=np.int64)
    padded = np.zeros((h, w + 2), dtype=bool)
    padded[:, 1:-1] = alpha
    diff = np.diff(padded.astype(np.int8), axis=1)
    for y in range(h):
        starts = np.flatnonzero(diff[y] == 1)
        ends = np.flatnonzero(diff[y] == -1)
        if starts.size == 0:
            continue
        lengths = ends - starts
        i = int(np.argmax(lengths))
        out[y] = (lengths[i], starts[i], ends[i])
    return out


def _read_profile(
    widths: np.ndarray, top: int, bottom: int
) -> tuple[int, int] | None:
    """Locate the nut and neck-pocket rows from the core width profile."""
    length = bottom - top + 1
    span = widths[top : bottom + 1]
    max_w = span.max()
    if max_w <= 0:
        return None
    if length / max_w < MIN_ASPECT:
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

    # Neck: the run above the body must have a clearly narrow plateau.
    neck_span = span[:body_start]
    if neck_span.size < 20:
        return None
    nonzero = neck_span[neck_span > 0]
    if nonzero.size == 0 or np.median(nonzero) > MAX_NECK_WIDTH_RATIO * max_w:
        return None

    # Nut: where the headstock flare settles into the neck plateau. The
    # plateau width is the low quartile of the head+neck run; the nut is the
    # first row (searching from the top) where the profile reaches plateau
    # width and stays there for a while.
    plateau = np.percentile(nonzero, 25)
    tolerance = plateau * 1.25
    stay = max(int(body_start * 0.10), 5)
    lo = max(int(body_start * 0.05), 1)
    hi = max(int(body_start * 0.75), lo + 1)
    nut = None
    for row in range(lo, hi):
        window = neck_span[row : row + stay]
        if window.size and (window <= tolerance).all():
            nut = row
            break
    if nut is None:
        nut = lo + int(np.argmin(neck_span[lo:hi]))

    return top + nut, top + body_start


def _tracked_strip(
    alpha: np.ndarray,
    start_interval: tuple[int, int],
    row_order: range,
    max_width: float | None,
) -> np.ndarray:
    """Mask of one part, tracked row by row from a seed interval.

    Each row keeps the run that overlaps the previously tracked interval —
    a horn tip appearing off to the side never overlaps it, so it is never
    picked up. When *max_width* is set, a run that suddenly balloons past
    it (the body flare at the neck joint) is clipped back to the previous
    interval so the strip stays part-width.
    """
    w = alpha.shape[1]
    strip = np.zeros_like(alpha)
    pad = 2
    prev = start_interval
    for y in row_order:
        run = _overlapping_run(alpha[y], prev)
        if run is None:
            continue
        start, end = run
        if max_width is not None and (end - start) > max_width:
            start = max(prev[0], start)
            end = min(prev[1], end)
            if end <= start:
                continue
        else:
            prev = (start, end)
        strip[y, max(start - pad, 0) : min(end + pad, w)] = alpha[
            y, max(start - pad, 0) : min(end + pad, w)
        ]
    return strip


def _assign_components(
    alpha: np.ndarray,
    neck_strip: np.ndarray,
    head_strip: np.ndarray,
    nut_row: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Split the non-neck material into headstock and body.

    Whole connected blobs are assigned, never cut: a blob is headstock when
    it mostly coincides with the tracked headstock strip or sits entirely
    above the nut (tuner pegs poking off the edge); everything else — body,
    horns, whatever they climb past — is body.
    """
    solid = alpha & ~neck_strip
    head_mask = head_strip.copy()
    body_mask = np.zeros_like(alpha)
    try:
        from scipy import ndimage
    except ImportError:  # coarse fallback: split at the nut line
        head_mask[:nut_row] |= solid[:nut_row]
        body_mask[nut_row:] = solid[nut_row:]
        return head_mask, body_mask

    labels, count = ndimage.label(solid)
    for i in range(1, count + 1):
        comp = labels == i
        size = int(comp.sum())
        if not size:
            continue
        in_head = int((comp & head_strip).sum())
        comp_rows = np.flatnonzero(comp.any(axis=1))
        if in_head / size > 0.5 or comp_rows[-1] < nut_row:
            head_mask |= comp
        else:
            body_mask |= comp
    return head_mask, body_mask


def _overlapping_run(row: np.ndarray, prev: tuple[int, int]) -> tuple[int, int] | None:
    """The run in *row* overlapping interval *prev* most; None if no overlap."""
    padded = np.zeros(row.size + 2, dtype=bool)
    padded[1:-1] = row
    diff = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)
    best, best_overlap = None, 0
    for s, e in zip(starts, ends):
        overlap = min(e, prev[1]) - max(s, prev[0])
        if overlap > best_overlap:
            best, best_overlap = (int(s), int(e)), overlap
    return best


def _cut(
    rgba: Image.Image, mask: np.ndarray
) -> tuple[Image.Image | None, tuple[int, int]]:
    """Cut the masked region tight to its bounding box.

    Returns (image, (left, top)) with the crop origin in full-image coords.
    """
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        return None, (0, 0)
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    left, right = int(cols[0]), int(cols[-1]) + 1
    region = rgba.crop((left, top, right, bottom))
    sub = np.asarray(region).copy()
    sub[..., 3] = np.where(mask[top:bottom, left:right], sub[..., 3], 0)
    return Image.fromarray(sub, mode="RGBA"), (left, top)


def _centroid_x(mask: np.ndarray, row: int) -> int:
    row = min(max(row, 0), mask.shape[0] - 1)
    cols = np.flatnonzero(mask[row])
    if cols.size == 0:
        # Fall back to the nearest non-empty row.
        rows = np.flatnonzero(mask.any(axis=1))
        if rows.size == 0:
            return 0
        nearest = rows[np.argmin(np.abs(rows - row))]
        cols = np.flatnonzero(mask[nearest])
    return int(cols.mean())


def _smooth(values: np.ndarray, window: int = 9) -> np.ndarray:
    kernel = np.ones(window) / window
    return np.convolve(values, kernel, mode="same")
