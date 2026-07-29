"""Command-line interface for the guitar mechanic.

    python -m guitar_mechanic app              # open the guitar builder app
    python -m guitar_mechanic process          # one pass over uploads/
    python -m guitar_mechanic watch            # keep watching uploads/
    python -m guitar_mechanic status           # what's in the library
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .config import Settings
from .mechanic import Mechanic


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guitar_mechanic",
        description=(
            "Automated enhancer, slicer, scaler, and populator for guitar "
            "components. Drop images in uploads/ and the mechanic works on "
            "them."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="project root containing uploads/ and library/ (default: cwd)",
    )
    parser.add_argument(
        "--ppi",
        type=int,
        default=None,
        help="library pixels-per-inch (default: 48, or the manifest's value)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_process = sub.add_parser("process", help="process everything in uploads/ once")
    p_process.add_argument(
        "--no-enhance", action="store_true",
        help="skip tonal enhancement (clean renders / colour-accurate shots)",
    )
    p_process.add_argument(
        "--category",
        help="force every processed image into this category "
        "(otherwise detected from the filename)",
    )

    p_watch = sub.add_parser("watch", help="watch uploads/ and process new arrivals")
    p_watch.add_argument(
        "--interval", type=float, default=2.0, help="poll interval in seconds"
    )
    p_watch.add_argument("--category", help="force category, as with process")

    sub.add_parser("status", help="summarise the component library")

    p_app = sub.add_parser("app", help="run the guitar builder web app")
    p_app.add_argument("--port", type=int, default=8666)
    return parser


def make_settings(args: argparse.Namespace) -> Settings:
    settings = Settings(root=args.root.resolve())
    if args.ppi:
        settings.ppi = args.ppi
    if getattr(args, "category", None):
        settings.category_override = args.category
    if getattr(args, "no_enhance", False):
        settings.enhance = False
    return settings


def cmd_status(settings: Settings) -> None:
    if not settings.manifest_path.exists():
        print("library is empty — drop images into uploads/ and run "
              "`python -m guitar_mechanic process`")
        return
    with open(settings.manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    components = manifest.get("components", [])
    counts = Counter(c["category"] for c in components)
    print(f"library: {len(components)} component(s) at {manifest.get('ppi')} ppi")
    for category, count in sorted(counts.items()):
        print(f"  {category:<22} {count}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = make_settings(args)

    if args.command == "process":
        results = Mechanic(settings).process_all()
        if not results:
            print(f"nothing to do — uploads folder is empty "
                  f"({settings.uploads_dir})")
        else:
            added = sum(1 for r in results if r.status == "added")
            failed = [r for r in results if r.status == "failed"]
            print(f"done: {added} added, "
                  f"{sum(1 for r in results if r.status == 'duplicate')} duplicates, "
                  f"{len(failed)} failed")
            if failed:
                for r in failed:
                    print(f"  failed: {r.source.name} — {r.error}")
                return 1
    elif args.command == "watch":
        try:
            Mechanic(settings).watch(interval=args.interval)
        except KeyboardInterrupt:
            print("\nmechanic clocking out")
    elif args.command == "status":
        cmd_status(settings)
    elif args.command == "app":
        from .app import serve

        try:
            serve(settings, port=args.port)
        except KeyboardInterrupt:
            print("\nmechanic clocking out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
