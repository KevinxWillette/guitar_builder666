"""The vault's local image generator — lite, offline, unfiltered.

Two backends:

**procedural** (default, always available)
    A seeded renderer built on Pillow and numpy: fractal noise fields,
    radial sigils, fracture bolts, grain and bloom, driven by keywords in
    the prompt. No model weights, no download, no network — it runs on a
    laptop with nothing installed but this repo's requirements, which is
    why it is the default.

**local_model** (opt-in)
    If you have a diffusion model on disk and ``diffusers`` installed,
    point ``vault/.vaultmeta/generator.json`` at the folder and the
    generator uses it. It is loaded strictly offline (hub access is
    switched off before import) and no content filter is attached: what
    you type is what it renders. Nothing about a prompt is logged outside
    the vault, and no prompt ever leaves the machine.

Every output is written inside the vault or straight into a locked
gallery; :func:`_guard_destination` refuses anything else, so a generated
image cannot land in ``docs/`` by a slip of the path.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .config import VaultSettings

DEFAULT_SIZE = 768

# Keyword -> colour ramp (dark, mid, hot). Whatever the prompt is about,
# these decide how it feels.
PALETTES: dict[str, tuple[tuple[int, int, int], ...]] = {
    "blood":   ((8, 2, 3), (104, 8, 12), (232, 46, 38)),
    "bone":    ((16, 15, 13), (146, 138, 120), (245, 240, 226)),
    "abalone": ((6, 10, 18), (28, 120, 128), (196, 240, 230)),
    "chrome":  ((10, 12, 16), (120, 130, 145), (238, 244, 252)),
    "gold":    ((14, 10, 2), (150, 108, 20), (250, 214, 108)),
    "toxic":   ((4, 12, 6), (28, 140, 52), (168, 255, 96)),
    "violet":  ((10, 4, 20), (86, 28, 150), (206, 138, 255)),
    "ember":   ((12, 5, 2), (168, 62, 8), (255, 176, 62)),
    "ice":     ((4, 10, 18), (44, 108, 160), (196, 236, 255)),
    "void":    ((2, 2, 3), (44, 44, 52), (150, 150, 168)),
}

PALETTE_WORDS = {
    "blood": "blood", "gore": "blood", "red": "blood", "crimson": "blood",
    "bone": "bone", "skull": "bone", "ivory": "bone", "ash": "bone",
    "abalone": "abalone", "pearl": "abalone", "shell": "abalone",
    "chrome": "chrome", "steel": "chrome", "silver": "chrome",
    "metal": "chrome", "gold": "gold", "brass": "gold",
    "toxic": "toxic", "slime": "toxic", "green": "toxic", "acid": "toxic",
    "violet": "violet", "purple": "violet", "occult": "violet",
    "ember": "ember", "fire": "ember", "flame": "ember", "burn": "ember",
    "ice": "ice", "frost": "ice", "blue": "ice", "cold": "ice",
    "void": "void", "black": "void", "dark": "void", "shadow": "void",
}

MOTIF_WORDS = {
    "sigil": "sigil", "pentagram": "sigil", "occult": "sigil",
    "ritual": "sigil", "rune": "sigil", "seal": "sigil", "666": "sigil",
    "bolt": "fracture", "lightning": "fracture", "crack": "fracture",
    "shatter": "fracture", "storm": "fracture", "thorn": "fracture",
    "smoke": "nebula", "fog": "nebula", "nebula": "nebula",
    "cloud": "nebula", "mist": "nebula", "cosmic": "nebula",
    "grain": "grit", "grit": "grit", "rust": "grit", "dirt": "grit",
    "halftone": "grit", "print": "grit",
    "burst": "rays", "ray": "rays", "sun": "rays", "star": "rays",
    "explosion": "rays",
}


@dataclass
class GeneratorConfig:
    """Loaded from ``vault/.vaultmeta/generator.json``."""

    backend: str = "procedural"
    model_path: str | None = None
    steps: int = 28
    guidance: float = 7.0
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, settings: VaultSettings) -> "GeneratorConfig":
        path = settings.generator_config_path
        if not path.exists():
            return cls()
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {"backend", "model_path", "steps", "guidance"}
        return cls(
            backend=data.get("backend", "procedural"),
            model_path=data.get("model_path"),
            steps=int(data.get("steps", 28)),
            guidance=float(data.get("guidance", 7.0)),
            extra={k: v for k, v in data.items() if k not in known},
        )

    def save(self, settings: VaultSettings) -> None:
        settings.meta_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "backend": self.backend,
            "model_path": self.model_path,
            "steps": self.steps,
            "guidance": self.guidance,
            **self.extra,
        }
        with open(settings.generator_config_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)


# --------------------------------------------------------------- procedural
def _words(prompt: str) -> list[str]:
    return [w for w in "".join(
        c.lower() if c.isalnum() else " " for c in prompt
    ).split() if w]


def _pick_palette(words: list[str], rng: random.Random) -> tuple:
    # A literal palette name in the prompt wins over a word that merely
    # suggests one ("blood" beats "occult").
    for word in words:
        if word in PALETTES:
            return PALETTES[word]
    for word in words:
        if word in PALETTE_WORDS:
            return PALETTES[PALETTE_WORDS[word]]
    return PALETTES[rng.choice(sorted(PALETTES))]


def _pick_motifs(words: list[str], rng: random.Random) -> list[str]:
    found = []
    for word in words:
        motif = MOTIF_WORDS.get(word)
        if motif and motif not in found:
            found.append(motif)
    if not found:
        found = rng.sample(["sigil", "fracture", "nebula", "rays"], 2)
    if "grit" not in found:
        found.append("grit")
    return found


def _fbm(size: int, rng: random.Random, octaves: int = 5) -> np.ndarray:
    """Fractal value noise in [0, 1], built by stacking upscaled lattices."""
    seed = rng.getrandbits(32)
    state = np.random.default_rng(seed)
    field = np.zeros((size, size), dtype="float32")
    amplitude = 1.0
    total = 0.0
    lattice = 4
    for _ in range(octaves):
        grid = state.random((lattice, lattice)).astype("float32")
        layer = np.asarray(
            Image.fromarray((grid * 255).astype("uint8")).resize(
                (size, size), Image.BICUBIC
            ),
            dtype="float32",
        ) / 255.0
        field += layer * amplitude
        total += amplitude
        amplitude *= 0.5
        lattice *= 2
    field /= max(total, 1e-6)
    lo, hi = float(field.min()), float(field.max())
    return (field - lo) / max(hi - lo, 1e-6)


def _colourise(field: np.ndarray, palette: tuple) -> Image.Image:
    """Map a scalar field through a three-stop colour ramp."""
    dark, mid, hot = (np.array(c, dtype="float32") for c in palette)
    f = field[..., None]
    lower = dark + (mid - dark) * np.clip(f * 2.0, 0, 1)
    upper = mid + (hot - mid) * np.clip((f - 0.5) * 2.0, 0, 1)
    rgb = np.where(f < 0.5, lower, upper)
    return Image.fromarray(np.clip(rgb, 0, 255).astype("uint8"), "RGB")


def _draw_sigil(layer: Image.Image, rng: random.Random, colour) -> None:
    size = layer.size[0]
    draw = ImageDraw.Draw(layer, "RGBA")
    cx = cy = size / 2
    radius = size * rng.uniform(0.28, 0.38)
    points = rng.choice([5, 5, 7, 9])
    step = rng.choice([2, 3])
    width = max(2, size // 340)
    verts = [
        (cx + radius * math.cos(-math.pi / 2 + 2 * math.pi * i / points),
         cy + radius * math.sin(-math.pi / 2 + 2 * math.pi * i / points))
        for i in range(points)
    ]
    order = [verts[(i * step) % points] for i in range(points + 1)]
    draw.line(order, fill=colour, width=width, joint="curve")
    for scale in (1.0, 1.16, 0.42):
        r = radius * scale
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=width)
    for i in range(points):
        angle = -math.pi / 2 + 2 * math.pi * i / points
        inner = radius * 1.16
        outer = radius * rng.uniform(1.24, 1.34)
        draw.line(
            [(cx + inner * math.cos(angle), cy + inner * math.sin(angle)),
             (cx + outer * math.cos(angle), cy + outer * math.sin(angle))],
            fill=colour, width=width,
        )


def _draw_fracture(layer: Image.Image, rng: random.Random, colour) -> None:
    size = layer.size[0]
    draw = ImageDraw.Draw(layer, "RGBA")
    width = max(1, size // 500)
    for _ in range(rng.randint(3, 6)):
        x, y = rng.uniform(0, size), rng.uniform(0, size)
        angle = rng.uniform(0, math.tau)
        for _ in range(rng.randint(18, 34)):
            length = rng.uniform(size * 0.02, size * 0.07)
            nx = x + length * math.cos(angle)
            ny = y + length * math.sin(angle)
            draw.line([(x, y), (nx, ny)], fill=colour, width=width)
            if rng.random() < 0.18:  # branch
                branch = angle + rng.uniform(-1.1, 1.1)
                draw.line(
                    [(nx, ny),
                     (nx + length * 1.5 * math.cos(branch),
                      ny + length * 1.5 * math.sin(branch))],
                    fill=colour, width=width,
                )
            x, y, angle = nx, ny, angle + rng.uniform(-0.45, 0.45)


def _draw_rays(layer: Image.Image, rng: random.Random, colour) -> None:
    size = layer.size[0]
    draw = ImageDraw.Draw(layer, "RGBA")
    cx = cy = size / 2
    count = rng.randint(24, 60)
    for i in range(count):
        angle = math.tau * i / count + rng.uniform(-0.02, 0.02)
        reach = size * rng.uniform(0.35, 0.95)
        draw.line(
            [(cx, cy), (cx + reach * math.cos(angle), cy + reach * math.sin(angle))],
            fill=colour, width=max(1, size // 700),
        )


def _grit(image: Image.Image, rng: random.Random, strength: float = 0.10) -> Image.Image:
    size = image.size[0]
    state = np.random.default_rng(rng.getrandbits(32))
    noise = state.normal(0, 255 * strength, (size, size, 1)).astype("float32")
    arr = np.asarray(image, dtype="float32") + noise
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGB")


def _bloom(image: Image.Image, radius: int, amount: float = 0.55) -> Image.Image:
    glow = image.filter(ImageFilter.GaussianBlur(radius))
    return Image.blend(image, ImageChops.screen(image, glow), amount)


def _vignette(image: Image.Image, strength: float = 0.65) -> Image.Image:
    size = image.size[0]
    y, x = np.mgrid[0:size, 0:size].astype("float32")
    cx = cy = (size - 1) / 2
    distance = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / (size * 0.72)
    mask = np.clip(1.0 - strength * distance ** 2.2, 0, 1)[..., None]
    arr = np.asarray(image, dtype="float32") * mask
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGB")


def render_procedural(prompt: str, *, seed: int, size: int = DEFAULT_SIZE) -> Image.Image:
    """Render one image. Same prompt + same seed always gives the same picture."""
    rng = random.Random(f"{prompt}|{seed}")
    words = _words(prompt)
    palette = _pick_palette(words, rng)
    motifs = _pick_motifs(words, rng)

    field = _fbm(size, rng, octaves=6)
    if "nebula" in motifs:
        field = np.clip(field * 1.25 - 0.12, 0, 1)
    canvas = _colourise(field, palette)

    if rng.random() < 0.7:  # mirror for a made-on-purpose symmetry
        left = canvas.crop((0, 0, size // 2, size))
        canvas.paste(left.transpose(Image.FLIP_LEFT_RIGHT), (size // 2, 0))

    hot = palette[2]
    if motifs != ["grit"]:
        # Pull the field down so the hot line work reads against it; a pale
        # palette otherwise draws white on white.
        canvas = Image.fromarray(
            (np.asarray(canvas, dtype="float32") * 0.72).astype("uint8"), "RGB"
        )
    ink = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for motif in motifs:
        if motif == "sigil":
            _draw_sigil(ink, rng, hot + (225,))
        elif motif == "fracture":
            _draw_fracture(ink, rng, hot + (180,))
        elif motif == "rays":
            _draw_rays(ink, rng, hot + (120,))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), ink).convert("RGB")

    canvas = _bloom(canvas, radius=max(2, size // 90))
    if "grit" in motifs:
        canvas = _grit(canvas, rng)
    return _vignette(canvas)


# -------------------------------------------------------------- local model
def render_local_model(prompt: str, *, seed: int, size: int,
                       config: GeneratorConfig) -> Image.Image:
    """Render with a diffusion model stored on this machine.

    Offline is enforced before ``diffusers`` is imported, and no safety
    checker is attached: the point of a local generator is that the prompt
    is between you and your own hardware.
    """
    import os

    model_path = Path(config.model_path or "")
    if not model_path.exists():
        raise RuntimeError(
            f"local_model backend needs an existing model folder; "
            f"{config.model_path!r} is not on disk. "
            f"Set it with: vault generator --backend local_model "
            f"--model-path /path/to/model"
        )
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["DIFFUSERS_OFFLINE"] = "1"
    try:
        import torch
        from diffusers import StableDiffusionPipeline
    except ImportError as exc:
        raise RuntimeError(
            "local_model backend needs `pip install diffusers torch`"
        ) from exc

    pipe = StableDiffusionPipeline.from_pretrained(
        str(model_path), safety_checker=None, requires_safety_checker=False,
        local_files_only=True,
    )
    pipe.set_progress_bar_config(disable=True)
    if torch.cuda.is_available():
        pipe = pipe.to("cuda")
    generator = torch.Generator(
        device="cuda" if torch.cuda.is_available() else "cpu"
    ).manual_seed(seed)
    return pipe(
        prompt,
        num_inference_steps=config.steps,
        guidance_scale=config.guidance,
        width=size, height=size,
        generator=generator,
    ).images[0]


# -------------------------------------------------------------------- entry
def _guard_destination(settings: VaultSettings, path: Path) -> Path:
    """Generated images never leave the vault by accident."""
    if not settings.contains(path):
        raise ValueError(
            f"the generator only writes inside the vault; {path} is outside it"
        )
    return path


def generate(settings: VaultSettings, prompt: str, *, seed: int | None = None,
             size: int = DEFAULT_SIZE, count: int = 1,
             config: GeneratorConfig | None = None) -> list[tuple[Image.Image, dict]]:
    """Render *count* images. Returns ``(image, provenance)`` pairs."""
    config = config or GeneratorConfig.load(settings)
    base_seed = seed if seed is not None else random.SystemRandom().getrandbits(31)
    out = []
    for index in range(count):
        this_seed = base_seed + index
        if config.backend == "local_model":
            image = render_local_model(
                prompt, seed=this_seed, size=size, config=config
            )
        else:
            image = render_procedural(prompt, seed=this_seed, size=size)
        out.append((image, {
            "prompt": prompt,
            "seed": this_seed,
            "size": size,
            "backend": config.backend,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }))
    return out


def save_to_vault(settings: VaultSettings, image: Image.Image,
                  provenance: dict) -> Path:
    """Write a generated image into ``vault/generated/``."""
    settings.generated_dir.mkdir(parents=True, exist_ok=True)
    stem = "-".join(_words(provenance["prompt"])[:4]) or "generated"
    path = settings.generated_dir / f"{stem}-{provenance['seed']}.png"
    counter = 2
    while path.exists():
        path = settings.generated_dir / f"{stem}-{provenance['seed']}-{counter}.png"
        counter += 1
    _guard_destination(settings, path)
    image.save(path, "PNG")
    sidecar = path.with_suffix(".json")
    with open(sidecar, "w", encoding="utf-8") as fh:
        json.dump(provenance, fh, indent=2)
    return path
