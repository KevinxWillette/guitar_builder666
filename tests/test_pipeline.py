"""End-to-end tests for the guitar mechanic pipeline.

Synthetic component photos are generated on the fly (a part-coloured shape
on a plain backdrop, like a marketplace listing) and pushed through the full
enhance -> slice -> scale -> populate flow.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guitar_mechanic import classify, slicer
from guitar_mechanic.config import Settings
from guitar_mechanic.mechanic import Mechanic


def make_photo(path: Path, shape: str, size=(900, 700), bg=(242, 240, 236)):
    """Fake product photo: a component-ish shape on a plain backdrop."""
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    w, h = size
    if shape == "body":
        draw.ellipse([w * 0.15, h * 0.1, w * 0.85, h * 0.9], fill=(140, 60, 20))
        draw.ellipse([w * 0.35, h * 0.05, w * 0.75, h * 0.55], fill=(150, 70, 25))
    elif shape == "neck":
        draw.rectangle([w * 0.05, h * 0.42, w * 0.95, h * 0.58], fill=(90, 60, 30))
    elif shape == "knob":
        r = min(w, h) * 0.3
        draw.ellipse(
            [w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r], fill=(30, 30, 32)
        )
    img.save(path)


@pytest.fixture
def shop(tmp_path):
    settings = Settings(root=tmp_path)
    mech = Mechanic(settings)
    return settings, mech


def test_full_pipeline_populates_library(shop):
    settings, mech = shop
    make_photo(settings.uploads_dir / "mahogany_body.jpg", "body")
    make_photo(settings.uploads_dir / "maple_neck.png", "neck", size=(1200, 400))
    make_photo(settings.uploads_dir / "volume_knob.png", "knob", size=(500, 500))

    results = mech.process_all(log=lambda *_: None)
    assert [r.status for r in results] == ["added", "added", "added"]

    manifest = json.loads(settings.manifest_path.read_text())
    ids = {c["id"] for c in manifest["components"]}
    assert any(i.startswith("body/") for i in ids)
    assert any(i.startswith("neck/") for i in ids)
    assert any(i.startswith("knob/") for i in ids)

    # Uploads folder is swept clean, originals archived.
    assert mech.pending_uploads() == []
    assert len(list(settings.done_dir.iterdir())) == 3


def test_scaling_uses_real_world_dimensions(shop):
    settings, mech = shop
    make_photo(settings.uploads_dir / "strat_body.jpg", "body")
    mech.process_all(log=lambda *_: None)

    manifest = json.loads(settings.manifest_path.read_text())
    entry = manifest["components"][0]
    assert entry["category"] == "body"
    assert entry["longest_in"] == 18.0
    # Longest side should be inches * ppi (within a pixel of rounding).
    expected = round(18.0 * settings.ppi)
    assert abs(max(entry["width_px"], entry["height_px"]) - expected) <= 1


def test_slicer_produces_transparent_cutout(shop):
    settings, mech = shop
    make_photo(settings.uploads_dir / "tone_knob.png", "knob", size=(500, 500))
    mech.process_all(log=lambda *_: None)

    manifest = json.loads(settings.manifest_path.read_text())
    out = Image.open(settings.library_dir / manifest["components"][0]["file"])
    assert out.mode == "RGBA"
    alpha = np.asarray(out.split()[3])
    # Corners (old backdrop) must be transparent, centre must be solid.
    assert alpha[0, 0] < 30 and alpha[-1, -1] < 30
    assert alpha[alpha.shape[0] // 2, alpha.shape[1] // 2] > 200
    # The crop should be tight: the knob was a centred circle, so the
    # cut-out is far smaller than the original 500px frame after scaling.
    assert out.width < 500


def test_duplicate_uploads_are_skipped(shop):
    settings, mech = shop
    make_photo(settings.uploads_dir / "bridge_one.png", "knob", size=(400, 300))
    mech.process_all(log=lambda *_: None)
    # Same pixels, new name — the mechanic recognises the part by content.
    make_photo(settings.uploads_dir / "bridge_two.png", "knob", size=(400, 300))
    results = mech.process_all(log=lambda *_: None)
    assert results[0].status == "duplicate"
    manifest = json.loads(settings.manifest_path.read_text())
    assert len(manifest["components"]) == 1


def test_failed_files_are_quarantined(shop):
    settings, mech = shop
    (settings.uploads_dir / "not_an_image.jpg").write_bytes(b"junk data")
    results = mech.process_all(log=lambda *_: None)
    assert results[0].status == "failed"
    assert (settings.failed_dir / "not_an_image.jpg").exists()


def test_classifier_keywords_and_fallback():
    assert classify.classify("Gold-Humbucker-Pickup.jpg") == "pickup_humbucker"
    assert classify.classify("mahogany BODY photo.png") == "body"
    assert classify.classify("IMG_4021.jpg", width=2000, height=300) == "neck"
    assert classify.classify("IMG_4021.jpg", width=500, height=400) == "unknown"


def make_guitar_photo(path: Path, size=(700, 1600), bg=(244, 242, 238)):
    """Synthetic whole guitar: headstock flare, narrow neck, wide body."""
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    w, h = size
    cx = w / 2
    # headstock: 0..12% of height, wider than the neck
    draw.polygon(
        [(cx - w * 0.07, h * 0.02), (cx + w * 0.07, h * 0.02),
         (cx + w * 0.045, h * 0.13), (cx - w * 0.045, h * 0.13)],
        fill=(60, 40, 25),
    )
    # neck: 12%..55%, narrow
    draw.rectangle(
        [cx - w * 0.04, h * 0.12, cx + w * 0.04, h * 0.56], fill=(120, 85, 45)
    )
    # body: 55%..98%, wide
    draw.ellipse(
        [cx - w * 0.42, h * 0.52, cx + w * 0.42, h * 0.98], fill=(150, 40, 30)
    )
    img.save(path)


def test_whole_guitar_is_split_anatomically(shop):
    settings, mech = shop
    make_guitar_photo(settings.uploads_dir / "IMG_0666.jpg")
    results = mech.process_all(log=lambda *_: None)
    assert results[0].status == "added"
    slots = sorted(e["slot"] for e in results[0].entries)
    assert slots == ["body", "headstock", "neck"]

    manifest = json.loads(settings.manifest_path.read_text())
    by_slot = {c["slot"]: c for c in manifest["components"]}
    # Anchors present for reassembly on the bench.
    assert "pocket" in by_slot["body"]["anchors"]
    assert {"top", "bottom"} <= set(by_slot["neck"]["anchors"])
    assert "bottom" in by_slot["headstock"]["anchors"]
    # All three parts come from the same upload group.
    assert len({c["group"] for c in manifest["components"]}) == 1
    # Body should be the widest part, neck the narrowest.
    assert by_slot["body"]["width_px"] > by_slot["neck"]["width_px"]


def test_classical_fallback_keeps_everything_when_no_backdrop_found():
    # The classical engines specifically must fail open: with no clear
    # backdrop to key out, keep the whole frame rather than lose it.
    rng = np.random.default_rng(666)
    noise = rng.integers(0, 255, size=(300, 300, 3), dtype=np.uint8)
    out = slicer._best_cutout(Image.fromarray(noise, "RGB"))
    alpha = np.asarray(out.split()[3])
    assert (alpha > 200).mean() > 0.9


def test_slicer_never_returns_a_near_empty_cutout():
    # End to end (rembg included, when installed): pathological input
    # with no real subject must never come back essentially blank. An ML
    # model may still make a confident-looking low-signal guess on
    # meaningless input — that guess is accepted rather than
    # second-guessed, since there's no reliable way to distinguish it
    # from a genuinely small real part from the pixels alone.
    rng = np.random.default_rng(666)
    noise = rng.integers(0, 255, size=(300, 300, 3), dtype=np.uint8)
    out = slicer.slice_component(Image.fromarray(noise, "RGB"))
    alpha = np.asarray(out.split()[3])
    assert (alpha > 16).mean() > 0.02


def test_multi_part_upload_is_split(shop):
    settings, mech = shop
    # one image containing two separate knobs on a plain backdrop
    img = Image.new("RGB", (900, 500), (242, 240, 236))
    draw = ImageDraw.Draw(img)
    draw.ellipse([60, 140, 320, 400], fill=(30, 30, 32))
    draw.ellipse([560, 140, 820, 400], fill=(60, 40, 30))
    img.save(settings.uploads_dir / "two_knobs.png")
    results = mech.process_all(log=lambda *_: None)
    assert results[0].status == "added"
    assert len(results[0].entries) == 2


def test_sideways_part_is_uprighted():
    from guitar_mechanic import qc
    wide = Image.new("RGBA", (600, 150), (0, 0, 0, 0))
    d = ImageDraw.Draw(wide)
    d.rectangle([10, 30, 590, 120], fill=(90, 60, 30, 255))
    out = qc.normalize_orientation(wide, "neck")
    assert out.height > out.width


def test_debris_is_removed():
    from guitar_mechanic import qc
    img = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([100, 100, 400, 400], fill=(140, 60, 20, 255))
    d.rectangle([470, 470, 490, 490], fill=(140, 60, 20, 255))  # stray sliver
    parts = qc.split_islands(img)
    assert len(parts) == 1
    alpha = np.asarray(parts[0].split()[3])
    assert (alpha > 16).mean() > 0.3  # cropped tight to the real part


def test_extension_does_not_leak_into_keyword_match():
    # "jpeg" contains "peg" (-> tuner) as a raw substring; the extension
    # must be stripped before keyword matching or every .JPEG file
    # misclassifies as a tuner.
    assert classify.classify_filename("IMG_3928.JPEG") is None
    assert classify.classify_filename("IMG_3928.jpeg") is None
    assert classify.classify("body_shot.jpeg") == "body"
