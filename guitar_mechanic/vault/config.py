"""Where the vault lives and what it contains.

The vault is a single directory at the project root that is *never*
committed, *never* mirrored into ``docs/``, and *never* served by the
builder app. Everything private — original photos, the private pipeline,
generated images, and the password-locked galleries — lives under it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

VAULT_DIRNAME = "vault"

# Written into vault/.gitignore. A nested ignore file means the vault stays
# ignored even if somebody rewrites the project's root .gitignore.
NESTED_GITIGNORE = """\
# The vault ignores itself, from the inside.
# Do not delete this file: it is one of the layers keeping private
# pictures out of git. See VAULT.md.
*
!.gitignore
"""

VAULT_README = """\
THE VAULT — private, local, never committed, never published.

  originals/    private source images (the librarian's stacks)
  quarantine/   images the safety screen held back
  uploads/      drop zone for the private pipeline
  library/      parts cut by the private pipeline (never mirrored to docs/)
  generated/    output of the local generator, still in the clear
  galleries/    password-locked galleries — encrypted at rest
  .vaultmeta/   ledger + index (hashes and notes, no image data)

Nothing in here is tracked by git. `python -m guitar_mechanic vault doctor`
checks that every safety layer is still in place.
"""


@dataclass
class VaultSettings:
    """Paths for one vault. ``root`` is the project root, not the vault."""

    root: Path = field(default_factory=Path.cwd)

    @property
    def vault_dir(self) -> Path:
        return self.root / VAULT_DIRNAME

    @property
    def originals_dir(self) -> Path:
        return self.vault_dir / "originals"

    @property
    def quarantine_dir(self) -> Path:
        return self.vault_dir / "quarantine"

    @property
    def uploads_dir(self) -> Path:
        return self.vault_dir / "uploads"

    @property
    def library_dir(self) -> Path:
        return self.vault_dir / "library"

    @property
    def generated_dir(self) -> Path:
        return self.vault_dir / "generated"

    @property
    def galleries_dir(self) -> Path:
        return self.vault_dir / "galleries"

    @property
    def meta_dir(self) -> Path:
        return self.vault_dir / ".vaultmeta"

    @property
    def ledger_path(self) -> Path:
        return self.meta_dir / "ledger.json"

    @property
    def index_path(self) -> Path:
        return self.meta_dir / "index.json"

    @property
    def generator_config_path(self) -> Path:
        return self.meta_dir / "generator.json"

    @property
    def gitignore_path(self) -> Path:
        return self.vault_dir / ".gitignore"

    def all_dirs(self) -> list[Path]:
        return [
            self.vault_dir,
            self.originals_dir,
            self.quarantine_dir,
            self.uploads_dir,
            self.library_dir,
            self.generated_dir,
            self.galleries_dir,
            self.meta_dir,
        ]

    def ensure(self) -> None:
        """Create the vault and (re)assert its own ignore file."""
        for d in self.all_dirs():
            d.mkdir(parents=True, exist_ok=True)
        current = (
            self.gitignore_path.read_text(encoding="utf-8")
            if self.gitignore_path.exists()
            else None
        )
        if current != NESTED_GITIGNORE:
            self.gitignore_path.write_text(NESTED_GITIGNORE, encoding="utf-8")
        readme = self.vault_dir / "README.txt"
        if not readme.exists():
            readme.write_text(VAULT_README, encoding="utf-8")

    def contains(self, path: Path) -> bool:
        """True if *path* is inside the vault (resolved, symlinks included)."""
        try:
            probe = path.resolve()
        except OSError:
            probe = path.absolute()
        try:
            probe.relative_to(self.vault_dir.resolve())
            return True
        except ValueError:
            return False
