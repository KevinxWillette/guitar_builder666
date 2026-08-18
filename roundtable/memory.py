"""Shared project memory — searched, never broadcast.

The tempting version of this feature ships Killy's whole profile to every
provider on every call. That is expensive, it leaks more than any single
question needs, and it buries the actual brief in noise. So memory here is a
small searchable store: Claude looks things up, reads what came back, and
decides what (if anything) is worth forwarding to a specialist.

The store is line-delimited JSON — greppable, diffable, and repairable by hand
if it ever gets mangled.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

WORD_RE = re.compile(r"[a-z0-9]+")

#: Words too common to say anything about relevance.
STOPWORDS = frozenset(
    """a an and are as at be but by for from how if in is it its of on or that the
    to was what when where which who why with your my me i""".split()
)


def _tokenise(text: str) -> list[str]:
    return [w for w in WORD_RE.findall((text or "").lower()) if w not in STOPWORDS]


@dataclass
class MemoryEntry:
    """One remembered fact about one of Killy's projects."""

    id: str
    key: str
    text: str
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0

    def snippet(self, limit: int = 400) -> str:
        text = self.text.strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + " ..."


class Memory:
    """A tiny keyword-scored store of project facts."""

    def __init__(self, path: Path, max_entry_chars: int = 2000):
        self.path = path
        self.max_entry_chars = max_entry_chars

    # -- storage ---------------------------------------------------------

    def _load(self) -> list[MemoryEntry]:
        if not self.path.exists():
            return []
        entries: list[MemoryEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                # A corrupted line should cost one fact, not the whole memory.
                continue
            entries.append(
                MemoryEntry(
                    id=raw.get("id", ""),
                    key=raw.get("key", ""),
                    text=raw.get("text", ""),
                    tags=list(raw.get("tags") or []),
                    created_at=float(raw.get("created_at") or 0.0),
                    updated_at=float(raw.get("updated_at") or 0.0),
                )
            )
        return entries

    def _save(self, entries: list[MemoryEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(asdict(e), ensure_ascii=False) for e in entries]
        self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    # -- api -------------------------------------------------------------

    def write(self, key: str, text: str, tags: list[str] | None = None) -> MemoryEntry:
        """Store a fact, replacing any earlier fact filed under the same key."""
        key = (key or "").strip()
        if not key:
            raise ValueError("a memory entry needs a key")
        text = (text or "").strip()
        if not text:
            raise ValueError("a memory entry needs some text")
        if len(text) > self.max_entry_chars:
            text = text[: self.max_entry_chars].rstrip() + " ...[truncated]"

        now = time.time()
        entries = self._load()
        clean_tags = sorted({t.strip().lower() for t in (tags or []) if t.strip()})
        for entry in entries:
            if entry.key.lower() == key.lower():
                entry.text = text
                entry.tags = clean_tags or entry.tags
                entry.updated_at = now
                self._save(entries)
                return entry

        entry = MemoryEntry(
            id=uuid.uuid4().hex[:12],
            key=key,
            text=text,
            tags=clean_tags,
            created_at=now,
            updated_at=now,
        )
        entries.append(entry)
        self._save(entries)
        return entry

    def forget(self, key: str) -> bool:
        """Drop a fact. Returns True when something was actually removed."""
        entries = self._load()
        kept = [e for e in entries if e.key.lower() != (key or "").strip().lower()]
        if len(kept) == len(entries):
            return False
        self._save(kept)
        return True

    def all(self) -> list[MemoryEntry]:
        return sorted(self._load(), key=lambda e: e.updated_at, reverse=True)

    def search(
        self, query: str, tags: list[str] | None = None, limit: int = 5
    ) -> list[tuple[MemoryEntry, float]]:
        """Best-matching entries for ``query``, highest score first.

        Scoring is keyword overlap with a bump for key and tag hits — crude, but
        it needs no model, no index and no dependency, and the corpus here is
        dozens of entries rather than millions.
        """
        wanted_tags = {t.strip().lower() for t in (tags or []) if t.strip()}
        terms = set(_tokenise(query))
        scored: list[tuple[MemoryEntry, float]] = []

        for entry in self._load():
            if wanted_tags and not wanted_tags & set(entry.tags):
                continue
            if not terms:
                # A tag-only search is a legitimate way to list a project.
                scored.append((entry, 1.0 if wanted_tags else 0.0))
                continue
            body = set(_tokenise(entry.text))
            key_words = set(_tokenise(entry.key))
            tag_words = set(entry.tags)
            score = (
                2.0 * len(terms & key_words)
                + 1.5 * len(terms & tag_words)
                + 1.0 * len(terms & body)
            )
            if query.strip().lower() in entry.text.lower():
                score += 2.0
            if score > 0:
                scored.append((entry, score))

        scored.sort(key=lambda pair: (-pair[1], -pair[0].updated_at))
        return scored[: max(1, limit)]

    def as_context(self, results: list[tuple[MemoryEntry, float]]) -> str:
        """Render search hits as a context block Claude can hand to a specialist."""
        if not results:
            return ""
        lines = ["Relevant project background:"]
        for entry, _score in results:
            tags = f" [{', '.join(entry.tags)}]" if entry.tags else ""
            lines.append(f"- {entry.key}{tags}: {entry.text}")
        return "\n".join(lines)


def open_memory(settings: Any) -> Memory:
    """Open the memory store described by ``settings``."""
    return Memory(
        path=settings.state_dir / "memory.jsonl",
        max_entry_chars=int(settings.memory.get("max_entry_chars", 2000)),
    )
