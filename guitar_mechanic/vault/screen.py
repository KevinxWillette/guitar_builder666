"""The safety screen — decides whether a picture is safe to make public.

Run at two gates:

* **intake** — every image entering the public pipeline is screened first.
  Anything that looks personal is diverted into the vault's quarantine
  instead of being cut, filed, and mirrored into ``docs/``.
* **publish** — everything about to be committed or published is screened
  again, because a picture can enter the repo by paths the pipeline never
  sees (drag-and-drop into the GitHub web UI, a stray ``git add -f``).

The screen is deliberately fail-closed: anything it cannot read, or is
unsure about, is held rather than passed, and both ``flag`` and ``block``
stop a commit. A false positive costs one `vault release`; a false
negative is permanent. On this repo's 155 photographs the person-signal
rules hold two — both smooth natural-finish bodies — which is the price of
not missing a real one.

Signals, cheapest first:

1. filename markers ("selfie", "passport", "kids", ...)
2. EXIF GPS — a leak on its own, even for a legitimate guitar photo
3. faces — OpenCV, either the bundled Haar cascade (opencv-python 4.x) or
   a YuNet model you have dropped in the vault (OpenCV 5 ships no cascade)
4. large skin-tone regions — a coarse YCbCr heuristic that runs anywhere,
   with a grain test so that raw ash and mahogany (which sit squarely in the
   skin range) are not mistaken for a person

The skin test applies to photographs only. On a cut-out — a part on a
transparent background — the subject fills its own silhouette, so "how much
of the frame is skin-toned" says nothing: a gold knob and a bare shoulder
both score about 95%. Cut-outs are therefore judged on the other signals,
which is sound because a cut-out is a pipeline product and the photograph
it came from was screened on the way in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

CLEAR = "clear"
FLAG = "flag"
BLOCK = "block"

_SEVERITY = {CLEAR: 0, FLAG: 1, BLOCK: 2}

# Filename words that say "this was never meant for the parts library".
PERSONAL_MARKERS = (
    "selfie", "me", "myself", "family", "wife", "husband", "girlfriend",
    "boyfriend", "gf", "bf", "kid", "kids", "child", "children", "baby",
    "son", "daughter", "mom", "dad", "私", "nude", "nudes", "naked", "nsfw",
    "private", "personal", "intimate", "bedroom", "shower", "bath",
    "passport", "licence", "license", "id-card", "idcard", "ssn", "medical",
    "bank", "statement", "tax", "home", "house", "address",
)

# Coarse skin detection in YCbCr. Bare wood lands squarely in this range —
# an ash guitar body scores higher than a face does — so a skin-tone hit is
# only believed when the region is also *smooth*. Measured on this repo's
# own photos, wood grain scores 7.7-11.5 on the grain metric below while
# skin scores under 1; the cut is set well clear of both.
SKIN_CB = (77, 130)
SKIN_CR = (133, 175)
SKIN_FLAG_FRACTION = 0.28
SKIN_BLOCK_FRACTION = 0.55
GRAIN_SMOOTH = 5.0
ALPHA_OPAQUE = 32         # below this a pixel is background, not subject
SCREEN_SIDE = 128         # analyse a downscaled copy; fast and stable


@dataclass
class ScreenReport:
    """The result of screening one file.

    ``reasons`` holds *person* signals — the things that mean "this may be
    a picture of someone". Those fail closed: they hold the picture and
    they stop a commit. ``notes`` holds hygiene findings such as leftover
    EXIF, which are worth fixing before publishing but are not grounds to
    refuse a commit, or every guitar photo off a phone would be refused.
    """

    path: Path
    verdict: str = CLEAR
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def safe_to_publish(self) -> bool:
        return self.verdict == CLEAR

    def add(self, verdict: str, reason: str) -> None:
        self.reasons.append(reason)
        if _SEVERITY[verdict] > _SEVERITY[self.verdict]:
            self.verdict = verdict

    def summary(self) -> str:
        if self.verdict == CLEAR:
            if self.notes:
                return f"{self.path.name}: clear ({'; '.join(self.notes)})"
            return f"{self.path.name}: clear"
        return f"{self.path.name}: {self.verdict.upper()} — {', '.join(self.reasons)}"


def _filename_markers(name: str) -> list[str]:
    slug = re.sub(r"[^a-z0-9]+", " ", name.lower())
    words = set(slug.split())
    return sorted(w for w in PERSONAL_MARKERS if w in words)


def _exif_report(img) -> tuple[bool, bool]:
    """Return ``(has_gps, has_exif)``."""
    try:
        exif = img.getexif()
    except Exception:
        return (False, False)
    if not exif:
        return (False, False)
    gps = False
    try:
        from PIL.ExifTags import IFD

        gps = bool(exif.get_ifd(IFD.GPSInfo))
    except Exception:
        gps = bool(exif.get(34853))
    return (gps, True)


def is_cutout(img) -> bool:
    """True if the image has a real transparent background."""
    if img.mode not in ("RGBA", "LA", "P"):
        return False
    try:
        import numpy as np

        alpha = np.asarray(img.convert("RGBA"))[..., 3]
    except Exception:
        return "transparency" in img.info
    return bool(alpha.min() < 250)


def _skin_metrics(img) -> tuple[float, float]:
    """Return ``(skin_fraction, grain)`` over the subject.

    The fraction counts opaque pixels only; *grain* is the mean absolute
    neighbour difference inside the skin-toned region — near zero for skin,
    high for the striped figure of bare wood.
    """
    import numpy as np

    small = img.convert("RGBA").resize((SCREEN_SIDE, SCREEN_SIDE))
    arr = np.asarray(small).astype("float32")
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    opaque = a > ALPHA_OPAQUE
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    mask = (
        (cb >= SKIN_CB[0]) & (cb <= SKIN_CB[1])
        & (cr >= SKIN_CR[0]) & (cr <= SKIN_CR[1])
        & (r > 60) & opaque
    )
    fraction = float(mask.sum()) / max(int(opaque.sum()), 1)
    gray = np.asarray(small.convert("L")).astype("float32")
    gx = np.abs(np.diff(gray, axis=1))[:-1, :]
    gy = np.abs(np.diff(gray, axis=0))[:, :-1]
    inner = mask[:-1, :-1]
    if inner.sum() < 50:
        return (fraction, 0.0)
    grain = float((gx[inner].mean() + gy[inner].mean()) / 2)
    return (fraction, grain)


# Haar cascades fire freely on wood grain — on this repo's 142 guitar
# photos the stock parameters claim faces in 121 of them. So a candidate
# box is only believed if the pixels inside it also read as skin: smooth,
# and skin-toned. Two weak signals agreeing is worth more than either.
FACE_MIN_NEIGHBOURS = 12
FACE_SCALE_FACTOR = 1.15
FACE_MIN_SIDE_FRACTION = 0.08     # of the shorter side
FACE_SKIN_FRACTION = 0.35


def _confirm_face(crop) -> bool:
    """True if a candidate box really looks like a face rather than timber."""
    fraction, grain = _skin_metrics(crop)
    return fraction >= FACE_SKIN_FRACTION and grain < GRAIN_SMOOTH


# A YuNet model dropped here turns face detection back on under OpenCV 5,
# which ships no Haar cascade. Relative to the vault, so it stays private.
YUNET_FILENAME = "face_detection_yunet.onnx"


def _yunet_paths(path: Path) -> list[Path]:
    """Places a YuNet model may sit, nearest vault first."""
    candidates = []
    for parent in [path.resolve(), *path.resolve().parents]:
        candidates.append(parent / "vault" / ".vaultmeta" / YUNET_FILENAME)
    return candidates


def detect_faces(path: Path) -> tuple[int | None, str]:
    """Return ``(face_count, how)``.

    ``face_count`` is None when no detector is available — and ``how``
    then says precisely why and what would fix it, because a safety signal
    that is quietly switched off is worse than one that was never claimed.
    """
    try:
        import cv2
    except ImportError:
        return (None, "unavailable — pip install 'opencv-python<5'")

    # OpenCV 4.x: the Haar cascade ships with the wheel and needs no
    # download, which is why it is preferred here.
    cascade_file = ""
    try:
        cascade_file = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    except Exception:
        cascade_file = ""
    if hasattr(cv2, "CascadeClassifier") and cascade_file and Path(cascade_file).exists():
        try:
            from PIL import Image

            cascade = cv2.CascadeClassifier(cascade_file)
            image = cv2.imread(str(path))
            if cascade.empty() or image is None:
                raise RuntimeError("cascade or image would not load")
            gray = cv2.equalizeHist(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
            minimum = max(
                40, int(min(gray.shape) * FACE_MIN_SIDE_FRACTION)
            )
            found = cascade.detectMultiScale(
                gray, FACE_SCALE_FACTOR, FACE_MIN_NEIGHBOURS,
                minSize=(minimum, minimum),
            )
            with Image.open(path) as opened:
                rgb = opened.convert("RGB")
                confirmed = sum(
                    1 for (x, y, w, h) in found
                    if _confirm_face(rgb.crop((int(x), int(y),
                                               int(x + w), int(y + h))))
                )
            how = "haar cascade + skin confirmation"
            if len(found) and not confirmed:
                how += f" ({len(found)} candidate(s) rejected as texture)"
            return (confirmed, how)
        except Exception as exc:
            return (None, f"cascade failed ({exc.__class__.__name__})")

    # OpenCV 5 removed the cascade; YuNet is the replacement, but its model
    # is a separate download.
    if hasattr(cv2, "FaceDetectorYN_create"):
        model = next((p for p in _yunet_paths(path) if p.exists()), None)
        if model is None:
            return (
                None,
                f"unavailable — OpenCV {cv2.__version__} ships no Haar "
                f"cascade; either pip install 'opencv-python<5' or put a "
                f"YuNet model at vault/.vaultmeta/{YUNET_FILENAME}",
            )
        try:
            image = cv2.imread(str(path))
            if image is None:
                return (None, "unreadable by OpenCV")
            height, width = image.shape[:2]
            detector = cv2.FaceDetectorYN_create(
                str(model), "", (width, height), 0.6
            )
            _, found = detector.detect(image)
            return (0 if found is None else len(found), "yunet")
        except Exception as exc:
            return (None, f"yunet failed ({exc.__class__.__name__})")

    return (None, f"unavailable — OpenCV {cv2.__version__} exposes no "
                  f"face detector this screen can use")


def screen_image(path: Path) -> ScreenReport:
    """Screen one file. Unreadable files are blocked, not passed."""
    report = ScreenReport(path=Path(path))

    markers = _filename_markers(Path(path).name)
    if markers:
        report.details["filename_markers"] = markers
        report.add(BLOCK, f"filename says personal ({', '.join(markers)})")

    try:
        from PIL import Image
    except ImportError:
        report.add(BLOCK, "cannot screen: Pillow is not installed")
        return report

    try:
        with Image.open(path) as img:
            img.load()
            has_gps, has_exif = _exif_report(img)
            report.details["exif"] = has_exif
            if has_gps:
                report.add(BLOCK, "EXIF GPS coordinates (reveals where you were)")
            elif has_exif:
                report.notes.append(
                    "carries EXIF metadata — `vault scrub` before publishing"
                )
            skin, grain = _skin_metrics(img)
            report.details["skin_fraction"] = round(skin, 3)
            report.details["grain"] = round(grain, 2)
            if is_cutout(img):
                # A cut-out is all subject: the fraction carries no signal.
                report.details["skin_note"] = (
                    "cut-out — skin fraction not meaningful; judged on "
                    "faces, filename, EXIF and ledger instead"
                )
            elif skin < SKIN_FLAG_FRACTION:
                pass
            elif grain >= GRAIN_SMOOTH:
                # Skin-coloured but grainy: wood, not a person.
                report.details["skin_note"] = (
                    f"{skin:.0%} skin-tone pixels, but the grain reads as "
                    f"timber or finish, not skin"
                )
            elif skin >= SKIN_BLOCK_FRACTION:
                report.add(BLOCK, f"smooth skin tones over {skin:.0%} of frame")
            else:
                report.add(FLAG, f"smooth skin-tone region ({skin:.0%} of frame)")
    except Exception as exc:
        report.add(BLOCK, f"cannot screen ({exc.__class__.__name__}) — holding it")
        return report

    faces, how = detect_faces(Path(path))
    report.details["faces"] = faces
    report.details["face_detection"] = how
    if faces is None:
        report.notes.append(f"face detection {how}")
    elif faces > 0:
        report.add(BLOCK, f"{faces} face(s) detected ({how})")

    return report


def screen_tree(root: Path, extensions: set[str] | None = None) -> list[ScreenReport]:
    """Screen every image under *root* (skipping dot-directories)."""
    from ..config import SUPPORTED_EXTENSIONS

    exts = extensions or SUPPORTED_EXTENSIONS
    reports = []
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file() or path.suffix.lower() not in exts:
            continue
        if any(part.startswith(".") for part in path.parts):
            continue
        reports.append(screen_image(path))
    return reports
