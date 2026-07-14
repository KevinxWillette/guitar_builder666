"""Stage 3 — the scaler.

Resizes a sliced component so parts from different photos share one
coordinate system: the library's pixels-per-inch. A body photographed with a
phone and a knob from a catalogue thumbnail end up correctly proportioned
next to each other on the builder canvas.
"""

from __future__ import annotations

from PIL import Image

from .config import COMPONENT_DIMENSIONS_IN, UNKNOWN_LONGEST_PX


def scale_component(
    image: Image.Image, category: str, ppi: int
) -> tuple[Image.Image, float | None]:
    """Scale *image* for the library.

    Returns ``(scaled_image, real_world_inches)`` where the inches value is
    the assumed longest dimension, or None for unknown categories.
    """
    inches = COMPONENT_DIMENSIONS_IN.get(category)
    target_longest = round(inches * ppi) if inches else UNKNOWN_LONGEST_PX

    longest = max(image.size)
    if longest == 0:
        return image, inches
    factor = target_longest / longest
    new_size = (
        max(round(image.width * factor), 1),
        max(round(image.height * factor), 1),
    )
    return image.resize(new_size, Image.LANCZOS), inches
