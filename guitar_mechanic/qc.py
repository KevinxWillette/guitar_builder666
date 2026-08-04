"""Quality control for cut parts.

Catches the failure modes batch uploads produce:

- catalog sheets / photos with several parts  -> split into separate parts
- slivers of neighbouring parts left attached -> removed
- parts photographed sideways                 -> rotated upright
- suspect cuts (touching the frame, hollow)   -> flagged in the manifest
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

ALPHA = 16

# An island at least this fraction of the biggest island is its own part;
# anything smaller than the stray threshold is debris and gets erased.
KEEP_FRACTION = 0.25
STRAY_FRACTION = 0.02

# Categories that should stand upright on the canvas.
UPRIGHT_CATEGORIES = {"body", "neck", "headstock", "pickguard", "unknown"}


def _components(alpha: np.ndarray):
    try:
        import cv2
        n, labels, stats, _ = cv2.connectedComponentsWithStats(
            (alpha * 255).astype(np.uint8), 8
        )
        return [
            (int(stats[i][4]), (labels == i)) for i in range(1, n)
        ]
    except ImportError:
        from scipy import ndimage
        labels, n = ndimage.label(alpha)
        return [
            (int((labels == i).sum()), labels == i) for i in range(1, n + 1)
        ]


def split_islands(rgba: Image.Image) -> list[Image.Image]:
    """Split a cut image into its significant parts, discarding debris.

    Returns one image per real part (largest first). A single-part image
    comes back as a one-element list with any debris cleaned off.
    """
    arr = np.asarray(rgba.convert("RGBA")).copy()
    alpha = arr[..., 3] > ALPHA
    comps = sorted(_components(alpha), key=lambda c: -c[0])
    if not comps:
        return [rgba]
    main_area = comps[0][0]
    parts = []
    for area, mask in comps:
        if area >= main_area * KEEP_FRACTION:
            sub = arr.copy()
            sub[..., 3] = np.where(mask, sub[..., 3], 0)
            ys, xs = np.nonzero(mask)
            pad = 4
            crop = sub[
                max(ys.min() - pad, 0):ys.max() + pad,
                max(xs.min() - pad, 0):xs.max() + pad,
            ]
            parts.append(Image.fromarray(crop, "RGBA"))
        # islands between stray and keep thresholds are ambiguous debris:
        # they vanish with the strays rather than become junk parts
    return parts if parts else [rgba]


def normalize_orientation(rgba: Image.Image, category: str) -> Image.Image:
    """Rotate a clearly sideways part upright.

    Conservative: only acts on upright categories whose principal axis is
    within 30 degrees of horizontal.
    """
    if category not in UPRIGHT_CATEGORIES:
        return rgba
    alpha = np.asarray(rgba.split()[3]) > ALPHA
    ys, xs = np.nonzero(alpha)
    if len(ys) < 50:
        return rgba
    coords = np.stack([xs - xs.mean(), ys - ys.mean()])
    cov = coords @ coords.T / len(xs)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)
    elongation = math.sqrt(max(eigvals[order[1]], 1e-9) / max(eigvals[order[0]], 1e-9))
    if elongation < 1.15:
        return rgba  # too round to have a meaningful axis
    vx, vy = eigvecs[:, order[1]]
    ang = math.degrees(math.atan2(vy, vx)) % 180.0
    if ang < 30 or ang > 150:  # lying on its side
        return rgba.rotate(-90, expand=True, resample=Image.BICUBIC)
    return rgba


def flags(rgba: Image.Image) -> list[str]:
    """Warnings about a finished cut, stored in the manifest for review."""
    out = []
    alpha = np.asarray(rgba.split()[3]) > ALPHA
    h, w = alpha.shape
    if h < 8 or w < 8:
        return ["tiny"]
    fill = alpha.mean()
    if fill < 0.15:
        out.append("sparse_cut")          # mostly empty box: overcut suspect
    border = np.concatenate([alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]])
    if border.mean() > 0.20:
        out.append("touches_frame")       # part ran off the photo: undercut
    comps = _components(alpha)
    if len(comps) > 1:
        main = max(a for a, _ in comps)
        if sum(1 for a, _ in comps if a > main * KEEP_FRACTION) > 1:
            out.append("multiple_islands")
    return out
