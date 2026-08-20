"""Tests for the vault — the layers that keep private pictures private.

Each test names the leak it is preventing, because a safety mechanism
nobody can explain is a safety mechanism nobody maintains.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guitar_mechanic.app import BuilderHandler
from guitar_mechanic.vault import crypto, gallery, generator, guard, screen
from guitar_mechanic.vault.config import VaultSettings
from guitar_mechanic.vault.ledger import Ledger
from guitar_mechanic.vault.librarian import Librarian

PASSPHRASE = "anvil-obsidian-thunder-77"


@pytest.fixture
def vault(tmp_path) -> VaultSettings:
    settings = VaultSettings(root=tmp_path)
    settings.ensure()
    (tmp_path / ".gitignore").write_text("vault/\n", encoding="utf-8")
    return settings


def make_skin_photo(path: Path, size=(900, 1200)) -> Path:
    """A stand-in personal photo: a smooth skin-toned subject."""
    img = Image.new("RGB", size, (208, 202, 196))
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.ellipse([w * 0.17, h * 0.1, w * 0.83, h * 0.92], fill=(221, 174, 142))
    draw.ellipse([w * 0.33, h * 0.22, w * 0.67, h * 0.52], fill=(214, 166, 134))
    img.filter(ImageFilter.GaussianBlur(7)).save(path, quality=92)
    return path


def make_wood_photo(path: Path, size=(900, 1200)) -> Path:
    """A guitar body: skin-coloured, but with grain."""
    img = Image.new("RGB", size, (236, 232, 226))
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.rounded_rectangle(
        [w * 0.12, h * 0.1, w * 0.88, h * 0.9], radius=90, fill=(198, 158, 112)
    )
    for x in range(int(w * 0.12), int(w * 0.88), 7):
        shade = 150 + (x % 5) * 18
        draw.line([(x, h * 0.1), (x + 12, h * 0.9)], fill=(shade, shade - 40, 70), width=3)
    img.save(path, quality=92)
    return path


# ------------------------------------------------------------------ crypto
def test_gallery_ciphertext_survives_the_wrong_passphrase(vault):
    """Leak prevented: a stolen gallery folder opened by someone else."""
    locked = gallery.create(vault, "Night Work", PASSPHRASE)
    locked.add_bytes(b"\x89PNG private pixels", name="one.png")

    with pytest.raises(crypto.BadPassphrase):
        gallery.unlock(vault, "Night Work", "not-the-passphrase")

    reopened = gallery.unlock(vault, "night work", PASSPHRASE)
    record, data = reopened.read("one.png")
    assert data == b"\x89PNG private pixels"
    assert record["name"] == "one.png"


def test_nothing_readable_is_left_on_disk(vault):
    """Leak prevented: filenames and pixels legible in a backup or sync."""
    locked = gallery.create(vault, "Night Work", PASSPHRASE)
    locked.add_bytes(b"unmistakable-pixel-data", name="a-telling-filename.png")

    on_disk = b"".join(
        p.read_bytes() for p in (vault.galleries_dir / "night-work").rglob("*")
        if p.is_file()
    )
    assert b"unmistakable-pixel-data" not in on_disk
    assert b"a-telling-filename" not in on_disk


def test_tampering_is_detected(vault):
    key = crypto.derive_key(PASSPHRASE, crypto.new_salt())
    blob = bytearray(crypto.encrypt(b"payload" * 100, key))
    blob[40] ^= 0x01
    with pytest.raises(crypto.BadPassphrase):
        crypto.decrypt(bytes(blob), key)


# ------------------------------------------------------------------ screen
def test_a_personal_photo_is_blocked_and_a_guitar_is_not(tmp_path):
    """Leak prevented: a personal picture processed as if it were a part."""
    person = screen.screen_image(make_skin_photo(tmp_path / "beach.jpg"))
    guitar = screen.screen_image(make_wood_photo(tmp_path / "ash_body.jpg"))

    assert person.verdict in (screen.FLAG, screen.BLOCK)
    assert not person.safe_to_publish
    assert guitar.verdict == screen.CLEAR, guitar.reasons


def test_exif_alone_is_a_note_not_a_hold(tmp_path):
    """Otherwise every phone photo of a guitar would be refused."""
    from PIL import Image as PILImage

    path = make_wood_photo(tmp_path / "body.jpg")
    with PILImage.open(path) as img:
        exif = img.getexif()
        exif[306] = "2026:01:01 00:00:00"
        img.save(path, exif=exif)
    report = screen.screen_image(path)
    assert report.verdict == screen.CLEAR
    assert any("EXIF" in note for note in report.notes)


def test_a_personal_filename_alone_is_enough(tmp_path):
    path = make_wood_photo(tmp_path / "family_at_the_beach.jpg")
    report = screen.screen_image(path)
    assert report.verdict == screen.BLOCK
    assert any("filename" in r for r in report.reasons)


def test_an_unreadable_file_is_held_not_passed(tmp_path):
    """The screen fails closed: what it cannot read, it does not pass."""
    broken = tmp_path / "corrupt.jpg"
    broken.write_bytes(b"this is not an image")
    assert screen.screen_image(broken).verdict == screen.BLOCK


def test_cutouts_are_not_judged_on_skin_fraction(tmp_path):
    """A part on a transparent background is all subject; the fraction lies."""
    knob = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    ImageDraw.Draw(knob).ellipse([20, 20, 380, 380], fill=(214, 176, 96, 255))
    path = tmp_path / "knob-gold.png"
    knob.save(path)
    report = screen.screen_image(path)
    assert report.verdict == screen.CLEAR, report.reasons
    assert "cut-out" in report.details.get("skin_note", "")


# ------------------------------------------------------------------ ledger
def test_a_resized_re_encoded_copy_is_still_recognised(vault, tmp_path):
    """Leak prevented: the web-sized copy nobody remembers making."""
    original = make_skin_photo(tmp_path / "original.jpg")
    ledger = Ledger(vault)
    ledger.record(original)

    leaked = tmp_path / "innocent_backdrop.png"
    with Image.open(original) as img:
        img.resize((img.width // 2, img.height // 2)).save(leaked)

    match = ledger.match(leaked)
    assert match is not None
    kind, _entry = match
    assert kind in ("exact", "lookalike")


def test_an_unrelated_picture_is_not_a_false_match(vault, tmp_path):
    ledger = Ledger(vault)
    ledger.record(make_skin_photo(tmp_path / "private.jpg"))
    assert ledger.match(make_wood_photo(tmp_path / "guitar.jpg")) is None


# --------------------------------------------------------------- librarian
def test_the_librarian_quarantines_what_the_screen_holds(vault, tmp_path):
    librarian = Librarian(vault)
    private = librarian.take_in(make_skin_photo(tmp_path / "snap.jpg"))
    guitar = librarian.take_in(make_wood_photo(tmp_path / "body.jpg"))

    assert private["verdict"] != screen.CLEAR
    assert (vault.quarantine_dir / private["name"]).exists()
    assert guitar["verdict"] == screen.CLEAR
    assert (vault.originals_dir / guitar["name"]).exists()


def test_a_released_picture_is_still_remembered(vault, tmp_path):
    """Releasing is deliberate, but it does not erase the fingerprint."""
    librarian = Librarian(vault)
    item = librarian.take_in(make_skin_photo(tmp_path / "snap.jpg"))
    destination = librarian.release(item["id"], tmp_path / "out")
    assert destination.exists()
    assert Ledger(vault).by_sha1(item["sha1"]) is not None


# ------------------------------------------------------------------ guards
def test_vault_paths_are_refused_outright(vault):
    inside = vault.originals_dir / "anything.png"
    inside.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8)).save(inside)
    violations = guard.check_paths([inside], vault)
    assert [v.severity for v in violations] == ["block"]


def test_a_missing_ignore_layer_is_a_blocking_problem(vault):
    (vault.root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    assert any(v.severity == "block" for v in guard.check_gitignore(vault))


def test_the_precommit_hook_blocks_a_real_commit(tmp_path):
    """End to end, through git itself."""
    import os

    repo = tmp_path / "repo"
    repo.mkdir()
    # The hook runs `python -m guitar_mechanic`; in a scratch repo the
    # package is only importable via PYTHONPATH.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])

    def run(*a):
        return subprocess.run(a, cwd=repo, capture_output=True, text=True, env=env)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "T")
    (repo / ".gitignore").write_text("vault/\n", encoding="utf-8")

    settings = VaultSettings(root=repo)
    settings.ensure()
    guard.install_hooks(repo)
    assert guard.hook_installed(repo)

    librarian = Librarian(settings)
    librarian.take_in(make_skin_photo(tmp_path / "private.jpg"))

    # The same picture, resized and renamed, staged in a public folder.
    leaked = repo / "photos"
    leaked.mkdir()
    with Image.open(tmp_path / "private.jpg") as img:
        img.resize((img.width // 2, img.height // 2)).save(leaked / "backdrop.png")

    run("git", "add", "-f", "photos/backdrop.png")
    committed = run("git", "commit", "-m", "add backdrop")
    assert committed.returncode != 0
    assert "BLOCK" in committed.stdout + committed.stderr
    assert run("git", "log", "--oneline").returncode != 0  # no commit exists


def test_doctor_reports_every_layer(vault):
    rows = guard.doctor(vault)
    layers = [name for name, _healthy, _detail in rows]
    assert any("gitignore" in name for name in layers)
    assert any("pre-commit" in name for name in layers)
    assert any("tracked" in name for name in layers)


# --------------------------------------------------------------- app guard
@pytest.mark.parametrize("path", [
    "/vault/originals/private.jpg",
    "/vault",
    "/library/../vault/originals/private.jpg",
    "/vault/galleries/night-work/items/abc.bin",
    "/.git/config",
    "/vault/originals/%2e%2e/private.jpg",
])
def test_the_builder_server_never_serves_the_vault(path):
    """Leak prevented: the local app is port-forwarded or tunnelled."""
    probe = type("Probe", (), {"path": path})()
    assert BuilderHandler._is_private(probe) is True


@pytest.mark.parametrize("path", ["/", "/index.html", "/library/body/x.png",
                                  "/api/manifest"])
def test_public_paths_still_serve(path):
    probe = type("Probe", (), {"path": path})()
    assert BuilderHandler._is_private(probe) is False


# --------------------------------------------------------------- generator
def test_the_generator_is_deterministic(vault):
    one = generator.render_procedural("blood sigil storm", seed=99, size=128)
    two = generator.render_procedural("blood sigil storm", seed=99, size=128)
    assert list(one.tobytes()) == list(two.tobytes())


def test_the_generator_refuses_to_write_outside_the_vault(vault):
    with pytest.raises(ValueError):
        generator._guard_destination(vault, vault.root / "docs" / "parts" / "x.png")


def test_generated_images_land_in_the_vault(vault):
    (image, provenance), = generator.generate(
        vault, "chrome rays", seed=5, size=128, count=1
    )
    path = generator.save_to_vault(vault, image, provenance)
    assert vault.contains(path)
    assert path.with_suffix(".json").exists()


def test_the_generator_has_no_prompt_filter(vault):
    """The local generator renders what it is asked; that is the point."""
    for prompt in ["blood gore ritual sacrifice", "occult 666 pentagram",
                   "a perfectly nice sunset"]:
        image = generator.render_procedural(prompt, seed=1, size=64)
        assert image.size == (64, 64)


# ------------------------------------------------------------- approvals
def test_approval_waives_a_screen_finding(vault, tmp_path):
    """A dark walnut body reads as skin; a human can say otherwise."""
    photo = make_skin_photo(vault.root / "body.jpg")
    assert any(v.severity == "block" for v in guard.check_paths([photo], vault))

    guard.approve(vault.root, [photo], note="reviewed: it is a guitar")
    assert not guard.check_paths([photo], vault)


def test_editing_an_approved_file_revokes_its_approval(vault):
    photo = make_skin_photo(vault.root / "body.jpg")
    guard.approve(vault.root, [photo], note="reviewed")
    assert not guard.check_paths([photo], vault)

    make_skin_photo(photo, size=(880, 1180))       # same path, new bytes
    assert any(v.severity == "block" for v in guard.check_paths([photo], vault))


def test_approval_cannot_waive_vault_content(vault, tmp_path):
    """The waiver covers heuristics, never a picture the vault has held."""
    private = make_skin_photo(tmp_path / "private.jpg")
    Librarian(vault).take_in(private)

    leaked = vault.root / "photos_backdrop.png"
    leaked.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(private) as img:
        img.resize((img.width // 2, img.height // 2)).save(leaked)

    guard.approve(vault.root, [leaked], note="I promise it is fine")
    violations = guard.check_paths([leaked], vault)
    assert any(v.severity == "block" for v in violations)
    assert any("vault picture" in v.reason for v in violations)


# ----------------------------------------------------------------- scrub
def test_scrubbing_a_jpeg_keeps_every_pixel(tmp_path):
    """Metadata goes; the picture must not be quietly re-compressed."""
    import numpy as np

    from guitar_mechanic.vault.cli import _scrub, strip_jpeg_metadata

    path = make_wood_photo(tmp_path / "body.jpg")
    with Image.open(path) as img:
        exif = img.getexif()
        exif[306] = "2026:01:01 12:00:00"
        exif[315] = "a-tracking-uuid"
        img.save(path, exif=exif)
    before = np.asarray(Image.open(path).convert("RGB")).astype(int)

    _scrub([path], dry_run=False)

    with Image.open(path) as scrubbed:
        assert not scrubbed.getexif()
        after = np.asarray(scrubbed.convert("RGB")).astype(int)
    assert (before == after).all()
    assert b"a-tracking-uuid" not in path.read_bytes()


def test_a_failed_scrub_leaves_the_original_intact(tmp_path):
    """The first version of this truncated the file it was protecting."""
    from guitar_mechanic.vault.cli import _scrub

    broken = tmp_path / "not-an-image.jpg"
    broken.write_bytes(b"definitely not a jpeg")
    _scrub([broken], dry_run=False)
    assert broken.read_bytes() == b"definitely not a jpeg"
    assert not list(tmp_path.glob("*.scrub.tmp"))


def test_stripper_leaves_a_non_jpeg_alone(tmp_path):
    from guitar_mechanic.vault.cli import strip_jpeg_metadata

    assert strip_jpeg_metadata(b"\x89PNG\r\n\x1a\n rest") == b"\x89PNG\r\n\x1a\n rest"


def test_the_ignore_rule_does_not_swallow_the_package():
    """Regression: a bare `vault/` line also ignores guitar_mechanic/vault/."""
    root = Path(__file__).resolve().parents[1]
    lines = [line.strip() for line in (root / ".gitignore").read_text().splitlines()]
    assert "/vault/" in lines, "the vault ignore must be anchored to the root"
    assert "vault/" not in lines

    checked = subprocess.run(
        ["git", "check-ignore", "guitar_mechanic/vault/cli.py"],
        cwd=root, capture_output=True, text=True,
    )
    assert checked.returncode != 0, "the vault package must stay tracked"


# ---------------------------------------------------------- face detection
def test_a_face_box_must_also_look_like_skin():
    """Wood grain fires a Haar cascade constantly; skin is the tiebreak."""
    skin = Image.new("RGB", (200, 200), (221, 174, 142)).filter(
        ImageFilter.GaussianBlur(3)
    )
    wood = Image.new("RGB", (200, 200), (198, 158, 112))
    draw = ImageDraw.Draw(wood)
    for x in range(0, 200, 5):
        draw.line([(x, 0), (x + 8, 200)], fill=(150, 110, 70), width=2)

    assert screen._confirm_face(skin) is True
    assert screen._confirm_face(wood) is False


def test_the_screen_always_says_whether_faces_were_checked(tmp_path):
    """A signal that is silently off is worse than one never claimed."""
    report = screen.screen_image(make_wood_photo(tmp_path / "body.jpg"))
    assert report.details.get("face_detection")
    if report.details["faces"] is None:
        assert any("face detection" in note for note in report.notes)


def test_missing_opencv_is_reported_not_swallowed(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_cv2(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("no cv2")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_cv2)
    count, how = screen.detect_faces(make_wood_photo(tmp_path / "body.jpg"))
    assert count is None
    assert "opencv" in how.lower()
