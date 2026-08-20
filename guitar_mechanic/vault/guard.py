"""The guards — the layers that stop a private picture becoming public.

Three gates, deliberately independent so that defeating one is not enough:

``check_staged``
    Runs from a git ``pre-commit`` hook. Refuses a commit that carries
    vault content — by path, by exact hash, or by perceptual lookalike (a
    resized, re-saved copy of a vault picture is still caught) — and
    refuses images the safety screen holds.

``check_publish``
    Run over a directory about to be published (``docs/``, the folder that
    GitHub Pages serves). Same checks, plus EXIF, on files that may have
    reached the repo without ever passing the pipeline.

Screen findings are heuristics and can be wrong — a dark walnut body
reads much like skin. ``approve`` records a reviewed file's hash in
``.vaultguard/approved.json``, which is committed, so the audit stops
holding it. An approval waives *heuristic* findings only: a file that
matches the vault ledger, or lives in the vault, is refused no matter what
is approved.

``doctor``
    Verifies the layers are still installed: the vault ignored in two
    places, the hook present and executable, nothing from the vault
    tracked by git, the app's path guard in place.
"""

from __future__ import annotations

import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import SUPPORTED_EXTENSIONS
from . import screen
from .config import VAULT_DIRNAME, VaultSettings
from .ledger import Ledger

HOOK_MARKER = "guitar_mechanic vault precommit"

APPROVALS_PATH = Path(".vaultguard") / "approved.json"

HOOK_SCRIPT = f"""#!/bin/sh
# Installed by `python -m guitar_mechanic vault install-hooks`.
# Refuses commits that carry anything from the vault. See VAULT.md.
# Bypass (you should not need to): git commit --no-verify
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  echo "vault guard: no python found — refusing the commit to stay safe" >&2
  exit 1
fi
exec "$PY" -m {HOOK_MARKER}
"""


@dataclass
class Violation:
    path: str
    severity: str        # "block" | "warn"
    reason: str

    def line(self) -> str:
        mark = "BLOCK" if self.severity == "block" else "warn "
        return f"  [{mark}] {self.path}\n           {self.reason}"


# ------------------------------------------------------------- approvals
def approvals_path(root: Path) -> Path:
    return root / APPROVALS_PATH


def load_approvals(root: Path) -> dict[str, dict]:
    """Reviewed files, by sha1. Committed, so CI sees the same list."""
    path = approvals_path(root)
    if not path.exists():
        return {}
    try:
        import json

        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {entry["sha1"]: entry for entry in data.get("approved", [])}


def approve(root: Path, paths: list[Path], *, note: str | None = None) -> list[dict]:
    """Record files as reviewed-and-public. Never touches vault content."""
    import json
    from datetime import datetime, timezone

    from .ledger import sha1_of

    approved = load_approvals(root)
    added = []
    for path in paths:
        entry = {
            "sha1": sha1_of(path),
            "path": str(path.relative_to(root) if path.is_absolute() else path),
            "note": note,
            "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        approved[entry["sha1"]] = entry
        added.append(entry)
    destination = approvals_path(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "comment": "Files reviewed by a human and confirmed safe to publish. "
                   "Keyed by sha1, so editing a file revokes its approval. "
                   "This waives heuristic screen findings only — vault "
                   "content is refused regardless.",
        "approved": sorted(approved.values(), key=lambda e: e["path"]),
    }
    with open(destination, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return added


def _run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def staged_files(repo_root: Path) -> list[Path]:
    out = _run_git(
        ["diff", "--cached", "--name-only", "--diff-filter=ACMR"], repo_root
    )
    return [repo_root / line for line in out.splitlines() if line.strip()]


def tracked_under(repo_root: Path, prefix: str) -> list[str]:
    out = _run_git(["ls-files", "--", prefix], repo_root)
    return [line for line in out.splitlines() if line.strip()]


# ---------------------------------------------------------------- the gates
def check_paths(paths: list[Path], settings: VaultSettings, *,
                ledger: Ledger | None = None,
                run_screen: bool = True) -> list[Violation]:
    """The shared body of every gate."""
    ledger = ledger if ledger is not None else Ledger(settings)
    approved = load_approvals(settings.root)
    violations: list[Violation] = []
    for path in paths:
        try:
            display = str(path.relative_to(settings.root))
        except ValueError:
            display = str(path)

        if settings.contains(path):
            violations.append(Violation(
                display, "block",
                "inside the vault — vault content is never committed",
            ))
            continue
        if not path.is_file():
            continue

        match = ledger.match(path)
        if match:
            kind, entry = match
            if kind == "exact":
                violations.append(Violation(
                    display, "block",
                    f"byte-identical to a vault picture "
                    f"(recorded {entry['recorded_at']} as {entry['name']})",
                ))
            else:
                violations.append(Violation(
                    display, "block",
                    f"looks like the vault picture {entry['name']} "
                    f"— a resized or re-saved copy still counts",
                ))
            continue

        if run_screen and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            from .ledger import sha1_of

            try:
                if sha1_of(path) in approved:
                    continue        # reviewed by a human, and unchanged since
            except OSError:
                pass
            report = screen.screen_image(path)
            if report.verdict in (screen.BLOCK, screen.FLAG):
                # Both are person signals, and both fail closed.
                violations.append(Violation(
                    display, "block", "; ".join(report.reasons)
                ))
            elif report.notes:
                violations.append(Violation(
                    display, "warn", "; ".join(report.notes)
                ))
    return violations


def check_gitignore(settings: VaultSettings) -> list[Violation]:
    """Both ignore layers must still be in place."""
    out = []
    root_ignore = settings.root / ".gitignore"
    if not root_ignore.exists() or VAULT_DIRNAME not in root_ignore.read_text(
        encoding="utf-8"
    ):
        out.append(Violation(
            ".gitignore", "block",
            f"the root .gitignore no longer ignores {VAULT_DIRNAME}/",
        ))
    if settings.vault_dir.exists() and not settings.gitignore_path.exists():
        out.append(Violation(
            f"{VAULT_DIRNAME}/.gitignore", "block",
            "the vault's own ignore file is missing",
        ))
    return out


def check_staged(settings: VaultSettings) -> list[Violation]:
    """Everything about to be committed."""
    violations = check_gitignore(settings)
    violations += check_paths(staged_files(settings.root), settings)
    tracked = tracked_under(settings.root, f"{VAULT_DIRNAME}/")
    for entry in tracked:
        violations.append(Violation(
            entry, "block", "tracked by git even though it is in the vault",
        ))
    return violations


def check_publish(settings: VaultSettings, directory: Path) -> list[Violation]:
    """Everything in a directory that is about to go on the open web."""
    directory = Path(directory)
    files = [p for p in sorted(directory.rglob("*")) if p.is_file()]
    return check_paths(files, settings)


# ------------------------------------------------------------------- hooks
def hooks_dir(repo_root: Path) -> Path:
    out = _run_git(["rev-parse", "--git-path", "hooks"], repo_root).strip()
    return (repo_root / out) if out else (repo_root / ".git" / "hooks")


def install_hooks(repo_root: Path) -> tuple[Path, str]:
    """Install the pre-commit guard. Returns ``(path, action)``."""
    directory = hooks_dir(repo_root)
    directory.mkdir(parents=True, exist_ok=True)
    hook = directory / "pre-commit"
    action = "installed"
    if hook.exists():
        existing = hook.read_text(encoding="utf-8", errors="replace")
        if HOOK_MARKER in existing:
            action = "already installed"
        else:
            backup = hook.with_suffix(".pre-vault.bak")
            backup.write_text(existing, encoding="utf-8")
            action = f"replaced (previous hook saved as {backup.name})"
    hook.write_text(HOOK_SCRIPT, encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return (hook, action)


def hook_installed(repo_root: Path) -> bool:
    hook = hooks_dir(repo_root) / "pre-commit"
    if not hook.exists():
        return False
    text = hook.read_text(encoding="utf-8", errors="replace")
    return HOOK_MARKER in text and bool(hook.stat().st_mode & stat.S_IXUSR)


# ------------------------------------------------------------------ doctor
def doctor(settings: VaultSettings) -> list[tuple[str, bool, str]]:
    """Check every layer. Returns ``(layer, healthy, detail)`` rows."""
    rows: list[tuple[str, bool, str]] = []

    root_ignore = settings.root / ".gitignore"
    ignored = root_ignore.exists() and VAULT_DIRNAME in root_ignore.read_text(
        encoding="utf-8"
    )
    rows.append((
        "root .gitignore ignores vault/", ignored,
        "present" if ignored else "MISSING — add a `vault/` line",
    ))

    nested = settings.gitignore_path.exists()
    rows.append((
        "vault/.gitignore (second layer)", nested,
        "present" if nested else "MISSING — run `vault init`",
    ))

    hooked = hook_installed(settings.root)
    rows.append((
        "pre-commit guard", hooked,
        "installed and executable" if hooked
        else "MISSING — run `vault install-hooks`",
    ))

    tracked = tracked_under(settings.root, f"{VAULT_DIRNAME}/")
    rows.append((
        "nothing from the vault is tracked", not tracked,
        "clean" if not tracked else f"{len(tracked)} tracked file(s): "
        f"{', '.join(tracked[:3])}",
    ))

    app = settings.root / "guitar_mechanic" / "app.py"
    guarded = app.exists() and "vault" in app.read_text(encoding="utf-8")
    rows.append((
        "builder app refuses to serve the vault", guarded,
        "guard present" if guarded else "MISSING — app.py has no vault guard",
    ))

    ledger = Ledger(settings)
    rows.append((
        "ledger", True,
        f"{len(ledger.entries)} fingerprint(s) remembered",
    ))
    approved = load_approvals(settings.root)
    rows.append((
        "reviewed-and-public list", True,
        f"{len(approved)} file(s) approved by hand",
    ))

    probe = settings.meta_dir / ".face-probe.png"
    try:
        from PIL import Image

        settings.meta_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), (128, 128, 128)).save(probe)
        _count, how = screen.detect_faces(probe)
    except Exception as exc:
        how = f"could not probe ({exc.__class__.__name__})"
    finally:
        probe.unlink(missing_ok=True)
    working = "unavailable" not in how and "failed" not in how
    rows.append((
        "face detection (strongest signal)", working, how,
    ))
    return rows
