"""``python -m guitar_mechanic vault ...`` — the vault's command line."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from ..config import SUPPORTED_EXTENSIONS
from . import gallery as gallery_mod
from . import generator as generator_mod
from . import guard, screen
from .config import VaultSettings
from .crypto import BadPassphrase
from .crypto import shred as crypto_shred
from .librarian import Librarian

PASSPHRASE_ENV = "KILLETTE_VAULT_PASSPHRASE"


def add_parser(subparsers) -> argparse.ArgumentParser:
    """Attach the ``vault`` command to the mechanic's CLI."""
    parser = subparsers.add_parser(
        "vault",
        help="the private vault: librarian, pipeline, generator, galleries",
        description=(
            "Everything private lives in vault/: it is ignored by git twice "
            "over, guarded by a pre-commit hook, refused by the builder's "
            "web server, and its galleries are encrypted at rest."
        ),
    )
    sub = parser.add_subparsers(dest="vault_command", required=True)

    sub.add_parser("init", help="create the vault and install every guard")
    sub.add_parser("doctor", help="check that every safety layer is in place")
    sub.add_parser("install-hooks", help="install the pre-commit guard")
    sub.add_parser("status", help="what the vault is holding")
    sub.add_parser("precommit", help="(used by the git hook)")

    p_add = sub.add_parser("add", help="take pictures into the vault")
    p_add.add_argument("paths", nargs="+", type=Path)
    p_add.add_argument("--move", action="store_true",
                       help="move instead of copy (leaves no outside copy)")
    p_add.add_argument("--tag", action="append", default=[])
    p_add.add_argument("--note")

    p_list = sub.add_parser("list", help="search the librarian's index")
    p_list.add_argument("query", nargs="?", default="")
    p_list.add_argument("--verdict", choices=[screen.CLEAR, screen.FLAG,
                                              screen.BLOCK])
    p_list.add_argument("--tag")

    p_release = sub.add_parser(
        "release", help="deliberately move one picture back out of the vault"
    )
    p_release.add_argument("item_id")
    p_release.add_argument("destination", type=Path)

    p_forget = sub.add_parser("forget", help="shred one picture in the vault")
    p_forget.add_argument("item_id")

    p_screen = sub.add_parser("screen", help="screen files without moving them")
    p_screen.add_argument("paths", nargs="+", type=Path)

    p_scrub = sub.add_parser(
        "scrub", help="strip EXIF metadata from images, in place"
    )
    p_scrub.add_argument("paths", nargs="+", type=Path)
    p_scrub.add_argument("--dry-run", action="store_true")

    p_approve = sub.add_parser(
        "approve",
        help="mark files you have reviewed as safe to publish "
             "(waives screen findings, never vault content)",
    )
    p_approve.add_argument("paths", nargs="+", type=Path)
    p_approve.add_argument("--note")

    sub.add_parser("approvals", help="list reviewed-and-public files")

    p_pub = sub.add_parser(
        "check-publish",
        help="audit a folder before it goes on the web (default: docs/)",
    )
    p_pub.add_argument("directory", nargs="?", type=Path, default=None)

    p_proc = sub.add_parser(
        "process",
        help="run the parts pipeline inside the vault (private library)",
    )
    p_proc.add_argument("--no-enhance", action="store_true")
    p_proc.add_argument("--category")

    p_gen = sub.add_parser("generate", help="render images with the local generator")
    p_gen.add_argument("prompt")
    p_gen.add_argument("--seed", type=int)
    p_gen.add_argument("--size", type=int, default=generator_mod.DEFAULT_SIZE)
    p_gen.add_argument("--count", type=int, default=1)
    p_gen.add_argument("--gallery", help="write straight into a locked gallery")

    p_cfg = sub.add_parser("generator", help="configure the generator backend")
    p_cfg.add_argument("--backend", choices=["procedural", "local_model"])
    p_cfg.add_argument("--model-path")
    p_cfg.add_argument("--steps", type=int)
    p_cfg.add_argument("--guidance", type=float)

    p_gal = sub.add_parser("gallery", help="password-locked galleries")
    gal = p_gal.add_subparsers(dest="gallery_command", required=True)
    g_new = gal.add_parser("new", help="create a locked gallery")
    g_new.add_argument("name")
    gal.add_parser("list", help="list galleries (no passphrase needed)")
    g_add = gal.add_parser("add", help="lock files into a gallery")
    g_add.add_argument("name")
    g_add.add_argument("paths", nargs="+", type=Path)
    g_add.add_argument("--shred", action="store_true",
                       help="shred the cleartext original after locking it")
    g_items = gal.add_parser("items", help="list what is inside a gallery")
    g_items.add_argument("name")
    g_export = gal.add_parser("export", help="take one picture back out")
    g_export.add_argument("name")
    g_export.add_argument("item")
    g_export.add_argument("destination", type=Path)
    g_rm = gal.add_parser("remove", help="shred one picture inside a gallery")
    g_rm.add_argument("name")
    g_rm.add_argument("item")
    return parser


# ---------------------------------------------------------------- helpers
def _passphrase(prompt: str = "vault passphrase: ", *, confirm: bool = False) -> str:
    from_env = os.environ.get(PASSPHRASE_ENV)
    if from_env:
        return from_env
    if not sys.stdin.isatty():
        raise SystemExit(
            f"no passphrase available: set {PASSPHRASE_ENV} or run this "
            f"from a terminal"
        )
    value = getpass.getpass(prompt)
    if confirm and value != getpass.getpass("confirm passphrase: "):
        raise SystemExit("passphrases did not match")
    return value


def _expand(paths: list[Path]) -> list[Path]:
    out = []
    for path in paths:
        if path.is_dir():
            out.extend(
                p for p in sorted(path.rglob("*"))
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
            )
        elif path.is_file():
            out.append(path)
    return out


def _report_violations(violations, header: str) -> int:
    blocks = [v for v in violations if v.severity == "block"]
    warns = [v for v in violations if v.severity == "warn"]
    if not violations:
        print(f"{header}: clear")
        return 0
    print(header)
    for violation in blocks + warns:
        print(violation.line())
    if blocks:
        print(f"\n{len(blocks)} blocking problem(s). Nothing left the vault.")
        return 1
    print(f"\n{len(warns)} warning(s), nothing blocking.")
    return 0


# --------------------------------------------------------------- commands
def run(args: argparse.Namespace) -> int:
    settings = VaultSettings(root=args.root.resolve())
    command = args.vault_command

    if command == "init":
        settings.ensure()
        hook, action = guard.install_hooks(settings.root)
        print(f"vault ready at {settings.vault_dir}")
        print(f"pre-commit guard {action}: {hook}")
        print("\nnext: `vault doctor` to confirm every layer is up")
        return 0

    if command == "install-hooks":
        hook, action = guard.install_hooks(settings.root)
        print(f"pre-commit guard {action}: {hook}")
        return 0

    if command == "doctor":
        settings.ensure()
        rows = guard.doctor(settings)
        worst = 0
        for layer, healthy, detail in rows:
            mark = "ok  " if healthy else "FAIL"
            print(f"[{mark}] {layer:<44} {detail}")
            worst = worst or (0 if healthy else 1)
        print()
        print("all layers up" if not worst else
              "at least one layer is down — fix it before committing photos")
        return worst

    if command == "precommit":
        violations = guard.check_staged(settings)
        code = _report_violations(violations, "vault guard")
        if code:
            print("\nIf this is genuinely a public picture, take it out of "
                  "the vault first (`vault release <id> <dest>`), or scrub "
                  "it (`vault scrub <file>`).")
        return code

    settings.ensure()

    if command == "status":
        librarian = Librarian(settings)
        stats = librarian.stats()
        print(f"vault: {settings.vault_dir}")
        print(f"  catalogued pictures : {stats['items']}")
        for verdict, count in sorted(stats["by_verdict"].items()):
            print(f"      {verdict:<10} {count}")
        print(f"  fingerprints        : {stats['ledger_fingerprints']}")
        print(f"  locked galleries    : {stats['galleries']}")
        generated = list(settings.generated_dir.glob("*.png"))
        print(f"  generated images    : {len(generated)}")
        private = settings.library_dir / "manifest.json"
        print(f"  private parts library: "
              f"{'present' if private.exists() else 'empty'}")
        return 0

    if command == "add":
        librarian = Librarian(settings)
        held = 0
        for path in _expand(args.paths):
            item = librarian.take_in(
                path, move=args.move, tags=args.tag, note=args.note
            )
            where = "quarantine" if item["verdict"] != screen.CLEAR else "originals"
            detail = f" ({'; '.join(item['reasons'])})" if item["reasons"] else ""
            print(f"  {item['id']}  {item['name']} -> {where}{detail}")
            held += item["verdict"] != screen.CLEAR
        if held:
            print(f"\n{held} image(s) are in quarantine — which is still "
                  f"plaintext on this disk.")
            print("For anything you want encrypted, put it in a locked "
                  "gallery instead:")
            print("  vault gallery new \"Private\"")
            print("  vault gallery add \"Private\" <files or folder> --shred")
        return 0

    if command == "list":
        librarian = Librarian(settings)
        found = librarian.find(args.query, verdict=args.verdict, tag=args.tag)
        if not found:
            print("nothing matches")
            return 0
        for item in found:
            tags = f" [{', '.join(item['tags'])}]" if item["tags"] else ""
            print(f"  {item['id']}  {item['verdict']:<6} {item['name']}{tags}")
        return 0

    if command == "release":
        librarian = Librarian(settings)
        try:
            destination = librarian.release(args.item_id, args.destination)
        except KeyError:
            print(f"no item {args.item_id!r} in the vault")
            return 1
        print(f"released to {destination}")
        print("its fingerprint stays in the ledger, so the commit guard "
              "will still recognise it.")
        return 0

    if command == "forget":
        librarian = Librarian(settings)
        if not librarian.forget(args.item_id):
            print(f"no item {args.item_id!r} in the vault")
            return 1
        print(f"{args.item_id} shredded (fingerprint kept)")
        return 0

    if command == "screen":
        worst = 0
        for path in _expand(args.paths):
            report = screen.screen_image(path)
            print(f"  {report.summary()}")
            if report.verdict == screen.BLOCK:
                worst = 1
        return worst

    if command == "scrub":
        return _scrub(_expand(args.paths), dry_run=args.dry_run)

    if command == "approve":
        paths = _expand(args.paths)
        inside = [p for p in paths if settings.contains(p)]
        if inside:
            print("refusing: these are vault content and cannot be approved")
            for path in inside:
                print(f"  {path}")
            return 1
        added = guard.approve(settings.root, paths, note=args.note)
        for entry in added:
            print(f"  approved {entry['path']}  ({entry['sha1'][:12]})")
        print(f"\nwritten to {guard.APPROVALS_PATH} — commit it so CI "
              f"sees the same list.")
        print("editing any of these files revokes its approval.")
        return 0

    if command == "approvals":
        approved = guard.load_approvals(settings.root)
        if not approved:
            print("nothing approved yet")
            return 0
        for entry in sorted(approved.values(), key=lambda e: e["path"]):
            note = f"  — {entry['note']}" if entry.get("note") else ""
            print(f"  {entry['sha1'][:12]}  {entry['path']}{note}")
        return 0

    if command == "check-publish":
        directory = args.directory or (settings.root / "docs")
        if not directory.exists():
            print(f"{directory} does not exist")
            return 1
        violations = guard.check_publish(settings, directory)
        return _report_violations(violations, f"publish audit of {directory}")

    if command == "process":
        return _process(settings, args)

    if command == "generate":
        return _generate(settings, args)

    if command == "generator":
        config = generator_mod.GeneratorConfig.load(settings)
        if args.backend:
            config.backend = args.backend
        if args.model_path:
            config.model_path = args.model_path
        if args.steps:
            config.steps = args.steps
        if args.guidance:
            config.guidance = args.guidance
        config.save(settings)
        print(f"backend    : {config.backend}")
        print(f"model path : {config.model_path or '(none — procedural)'}")
        print(f"steps      : {config.steps}")
        print(f"guidance   : {config.guidance}")
        if config.backend == "local_model":
            print("\nlocal_model runs offline against weights on this "
                  "machine; no prompt filter is attached and nothing is "
                  "sent anywhere.")
        return 0

    if command == "gallery":
        return _gallery(settings, args)

    return 1


# JPEG segments that carry identity: EXIF/XMP, IPTC, and comments. APP0
# (JFIF) and APP2 (ICC colour profile) are kept — they describe the pixels,
# not the photographer.
JPEG_METADATA_MARKERS = {0xE1, 0xED, 0xEE, 0xFE}


def strip_jpeg_metadata(data: bytes) -> bytes:
    """Remove metadata segments from JPEG *data* without re-encoding it.

    Byte-level surgery, so the pixels come out bit-identical. Returns the
    input unchanged if it is not a JPEG we recognise.
    """
    if not data.startswith(b"\xff\xd8"):
        return data
    out = bytearray(b"\xff\xd8")
    i = 2
    end = len(data)
    while i < end - 1:
        if data[i] != 0xFF:
            break                       # not at a marker: give up, copy rest
        marker = data[i + 1]
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += data[i:i + 2]
            i += 2
            continue
        if marker == 0xDA:              # start of scan: entropy data follows
            out += data[i:]
            return bytes(out)
        if i + 4 > end:
            break
        length = int.from_bytes(data[i + 2:i + 4], "big")
        segment_end = i + 2 + length
        if length < 2 or segment_end > end:
            break
        if marker not in JPEG_METADATA_MARKERS:
            out += data[i:segment_end]
        i = segment_end
    else:
        return bytes(out)
    return data                          # anything unexpected: leave it alone


def _scrub(paths: list[Path], *, dry_run: bool) -> int:
    """Strip metadata in place, atomically, without touching the pixels."""
    import os

    from PIL import Image, ImageOps

    changed = 0
    skipped = 0
    for path in paths:
        try:
            with Image.open(path) as img:
                fmt = (img.format or "").upper()
                exif = img.getexif()
                if not exif:
                    continue
                rotated = exif.get(274, 1) not in (1, None)
                if dry_run:
                    print(f"  would scrub {path}")
                    changed += 1
                    continue
                if fmt == "JPEG" and not rotated:
                    original = path.read_bytes()
                    cleaned = strip_jpeg_metadata(original)
                    if cleaned == original:
                        skipped += 1
                        continue
                    payload = cleaned
                    mode = "bytes"
                else:
                    # A rotated JPEG has to be re-encoded to bake the
                    # orientation in before the tag can go; PNG and friends
                    # re-save losslessly either way.
                    baked = ImageOps.exif_transpose(img)
                    clean = baked.copy()
                    clean.info = {}
                    payload = None
                    mode = "image"
            temporary = path.with_name(path.name + ".scrub.tmp")
            if mode == "bytes":
                temporary.write_bytes(payload)
            elif fmt == "JPEG":
                clean.save(temporary, "JPEG", quality=95, subsampling=0,
                           optimize=True)
            else:
                clean.save(temporary, fmt or None)
            # Only once the new file is complete does the old one go.
            os.replace(temporary, path)
        except Exception as exc:
            print(f"  could not scrub {path}: {exc} (left untouched)")
            temporary = path.with_name(path.name + ".scrub.tmp")
            if temporary.exists():
                temporary.unlink()
            continue
        note = " (re-encoded to bake rotation)" if mode == "image" else ""
        print(f"  scrubbed {path}{note}")
        changed += 1
    if skipped:
        print(f"{skipped} file(s) had nothing strippable")
    print(f"{changed} file(s) {'would be ' if dry_run else ''}scrubbed")
    return 0


def _process(settings: VaultSettings, args: argparse.Namespace) -> int:
    """Run the parts pipeline entirely inside the vault."""
    from ..config import Settings
    from ..mechanic import Mechanic

    librarian = Librarian(settings)
    held = 0
    for path in sorted(settings.uploads_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        report = screen.screen_image(path)
        if report.verdict == screen.BLOCK:
            librarian.take_in(path, move=True)
            print(f"  held back: {report.summary()}")
            held += 1

    private = Settings(root=settings.vault_dir)
    private.enhance = not args.no_enhance
    if args.category:
        private.category_override = args.category
    results = Mechanic(private).process_all()
    added = sum(len(r.entries) for r in results)
    print(f"private pipeline: {added} part(s) filed into "
          f"{settings.library_dir}, {held} image(s) held back")
    print("nothing here is mirrored into docs/ — this library is private.")
    return 0


def _generate(settings: VaultSettings, args: argparse.Namespace) -> int:
    config = generator_mod.GeneratorConfig.load(settings)
    try:
        rendered = generator_mod.generate(
            settings, args.prompt, seed=args.seed, size=args.size,
            count=args.count, config=config,
        )
    except RuntimeError as exc:
        print(f"generator: {exc}")
        return 1

    if args.gallery:
        passphrase = _passphrase(f"passphrase for gallery {args.gallery!r}: ")
        try:
            locked = gallery_mod.unlock(settings, args.gallery, passphrase)
        except (gallery_mod.GalleryError, BadPassphrase) as exc:
            print(f"gallery: {exc}")
            return 1
        import io

        for image, provenance in rendered:
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            stem = "-".join(generator_mod._words(provenance["prompt"])[:4])
            record = locked.add_bytes(
                buffer.getvalue(),
                name=f"{stem or 'generated'}-{provenance['seed']}.png",
                meta=provenance,
            )
            print(f"  locked into {locked.slug}: {record['name']} "
                  f"({record['bytes']:,} bytes, encrypted)")
        return 0

    for image, provenance in rendered:
        path = generator_mod.save_to_vault(settings, image, provenance)
        print(f"  {path.relative_to(settings.root)}  (seed {provenance['seed']})")
    print("still in the clear inside the vault — "
          "`vault gallery add <name> <file> --shred` to lock them away.")
    return 0


def _gallery(settings: VaultSettings, args: argparse.Namespace) -> int:
    command = args.gallery_command

    if command == "list":
        rows = gallery_mod.listing(settings)
        if not rows:
            print("no galleries yet — `vault gallery new <name>`")
            return 0
        for row in rows:
            print(f"  {row['slug']:<24} {row['items']:>4} item(s)   "
                  f"created {row['created_at']}")
        return 0

    if command == "new":
        passphrase = _passphrase(
            f"new passphrase for {args.name!r}: ", confirm=True
        )
        try:
            locked = gallery_mod.create(settings, args.name, passphrase)
        except gallery_mod.GalleryError as exc:
            print(f"gallery: {exc}")
            return 1
        print(f"created gallery {locked.slug!r} at "
              f"{locked.directory.relative_to(settings.root)}")
        print("there is no recovery if you lose this passphrase — that is "
              "the point.")
        return 0

    passphrase = _passphrase(f"passphrase for gallery {args.name!r}: ")
    try:
        locked = gallery_mod.unlock(settings, args.name, passphrase)
    except (gallery_mod.GalleryError, BadPassphrase) as exc:
        print(f"gallery: {exc}")
        return 1

    if command == "add":
        librarian = Librarian(settings)
        held = 0
        for path in _expand(args.paths):
            librarian.ledger.record(path, origin="gallery")
            record = locked.add_file(path, shred_source=args.shred)
            if args.shred:
                # The generator leaves a cleartext sidecar holding the
                # prompt; it goes the same way as the picture.
                sidecar = path.with_suffix(".json")
                if sidecar.exists():
                    crypto_shred(sidecar)
            suffix = " (original shredded)" if args.shred else ""
            print(f"  locked {record['name']} ({record['bytes']:,} bytes)"
                  f"{suffix}")
        librarian.save()
        return 0

    if command == "items":
        items = locked.items()
        if not items:
            print("gallery is empty")
            return 0
        for record in items:
            prompt = record.get("prompt")
            extra = f'  "{prompt}"' if prompt else ""
            print(f"  {record['id']}  {record['name']:<38} "
                  f"{record['bytes']:>9,} b{extra}")
        return 0

    if command == "export":
        try:
            destination = locked.export(args.item, args.destination)
        except gallery_mod.GalleryError as exc:
            print(f"gallery: {exc}")
            return 1
        print(f"exported in the clear to {destination}")
        print("that copy is outside the vault now — the commit guard will "
              "still recognise it if it wanders into a commit.")
        return 0

    if command == "remove":
        if not locked.remove(args.item):
            print(f"no item {args.item!r} in {locked.slug!r}")
            return 1
        print(f"{args.item} shredded from {locked.slug!r}")
        return 0

    return 1
