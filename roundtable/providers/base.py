"""What every backend has in common.

A backend takes a system prompt and a brief and returns text. It does not know
about roles, memory, caching or MCP — that all lives above it — which is what
makes the CLI and API paths interchangeable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

# Terminal colour codes and cursor moves that a CLI may emit even when piped.
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")


class SpecialistError(RuntimeError):
    """A specialist could not be reached, or refused to answer.

    Raised rather than returned so the orchestrator can catch one failing
    specialist and keep the rest of the table working.
    """


class SpecialistTimeout(SpecialistError):
    """A specialist did not answer inside its timeout."""


@dataclass
class BackendResult:
    """One specialist's raw answer, before the orchestrator dresses it up."""

    text: str
    model: str | None = None
    usage: dict[str, Any] | None = None
    #: Anything worth keeping for debugging: argv, status codes, stderr tail.
    debug: dict[str, Any] = field(default_factory=dict)


class Backend(Protocol):
    """The one method the orchestrator needs from any transport."""

    kind: str

    def run(self, system: str, brief: str, timeout: float) -> BackendResult: ...


def strip_ansi(text: str) -> str:
    """Remove terminal escape sequences from CLI output."""
    return ANSI_RE.sub("", text)


def tail(text: str, limit: int = 800) -> str:
    """Last ``limit`` characters, for error messages that must stay readable."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]
