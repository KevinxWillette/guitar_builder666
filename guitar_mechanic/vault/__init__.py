"""The vault — the private half of the workshop.

Private pictures, the private pipeline, the local generator, and the
password-locked galleries all live inside ``vault/``, which is ignored by
git twice over, guarded at commit time, refused by the builder's web
server, and encrypted where it matters.

    python -m guitar_mechanic vault init
    python -m guitar_mechanic vault doctor
"""

from .config import VaultSettings  # noqa: F401
from .librarian import Librarian  # noqa: F401

__all__ = ["VaultSettings", "Librarian"]
