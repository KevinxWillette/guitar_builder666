"""The table itself: Claude calls in, specialists answer, nobody blocks.

Three things happen here that keep the roundtable usable rather than merely
possible:

* **Failure is isolated.** One specialist being down, slow or broken degrades
  the answer; it never takes the request with it. A dead seat comes back as a
  reply with ``ok=False`` and a reason, and Claude carries on with what it has.
* **Waiting happens in parallel.** A two-specialist panel takes as long as the
  slower one, not both.
* **Repeat questions are free.** Identical briefs inside the cache window reuse
  the stored answer, so Claude re-reading its own notes costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

from .config import Settings, load_settings
from .memory import open_memory
from .providers.base import SpecialistError
from .providers.registry import build_backend
from .roles import DEFAULT_ROLE, get_role
from .transcript import open_transcript


@dataclass
class Reply:
    """One specialist's answer, as the lead sees it."""

    call_id: str
    provider: str
    role: str
    ok: bool
    text: str = ""
    error: str | None = None
    backend: str | None = None
    model: str | None = None
    elapsed_seconds: float = 0.0
    cached: bool = False
    usage: dict[str, Any] | None = None
    #: Kept for the transcript only — never returned to Claude, because the
    #: brief is something Claude wrote and does not need read back to it.
    system: str = ""
    brief: str = ""
    debug: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        """The projection Claude receives: the answer and how it was obtained."""
        row = {
            "call_id": self.call_id,
            "provider": self.provider,
            "role": self.role,
            "ok": self.ok,
            "backend": self.backend,
            "model": self.model,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "cached": self.cached,
        }
        if self.ok:
            row["answer"] = self.text
        else:
            row["error"] = self.error
        if self.usage:
            row["usage"] = self.usage
        return row

    def record(self) -> dict[str, Any]:
        """The full record for the transcript, brief included."""
        return asdict(self)


def clip(text: str, limit: int, what: str) -> str:
    """Trim oversized input, and say so in-band rather than silently."""
    text = text or ""
    if limit <= 0 or len(text) <= limit:
        return text
    return (
        text[:limit].rstrip()
        + f"\n\n[...{what} truncated at {limit} characters by the roundtable...]"
    )


class ResponseCache:
    """Short-lived on-disk cache of identical specialist calls."""

    def __init__(self, path, ttl_seconds: int):
        self.path = path
        self.ttl = max(0, int(ttl_seconds))
        self._lock = threading.Lock()

    @staticmethod
    def key(provider: str, model: str | None, system: str, brief: str) -> str:
        digest = hashlib.sha256()
        for part in (provider, model or "", system, brief):
            digest.update(part.encode("utf-8", "replace"))
            digest.update(b"\x00")
        return digest.hexdigest()

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.ttl:
            return None
        with self._lock:
            entry = self._read().get(key)
        if not entry:
            return None
        if time.time() - float(entry.get("stored_at", 0)) > self.ttl:
            return None
        return entry

    def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.ttl:
            return
        with self._lock:
            data = self._read()
            cutoff = time.time() - self.ttl
            data = {
                k: v
                for k, v in data.items()
                if float(v.get("stored_at", 0)) >= cutoff
            }
            data[key] = {**value, "stored_at": time.time()}
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8"
                )
            except OSError:
                pass


class Orchestrator:
    """Routes Claude's requests to specialists and hands back their replies."""

    def __init__(self, settings: Settings | None = None, backend_factory=None):
        self.settings = settings or load_settings()
        # Injectable so the tests can seat fake specialists at the table.
        self._backend_factory = backend_factory or build_backend
        limits = self.settings.limits
        self.context_chars = int(limits.get("context_chars", 24000))
        self.prompt_chars = int(limits.get("prompt_chars", 12000))
        self.max_parallel = max(1, int(limits.get("max_parallel", 4)))
        self.cache = ResponseCache(
            self.settings.state_dir / "cache.json",
            int(limits.get("cache_ttl_seconds", 900)),
        )
        self.transcript = open_transcript(self.settings)
        self.memory = open_memory(self.settings)

    # -- briefing --------------------------------------------------------

    def build_brief(self, prompt: str, context: str | None = None) -> str:
        """Assemble what the specialist actually reads."""
        parts = [clip(prompt, self.prompt_chars, "brief")]
        if context and context.strip():
            parts.append(
                "=== CONTEXT SUPPLIED BY THE LEAD ===\n"
                + clip(context.strip(), self.context_chars, "context")
            )
        return "\n\n".join(parts)

    # -- one specialist --------------------------------------------------

    def ask(
        self,
        provider: str,
        prompt: str,
        role: str | None = None,
        context: str | None = None,
        model: str | None = None,
        use_cache: bool = True,
    ) -> Reply:
        """Put one question to one specialist. Always returns; never raises."""
        call_id = uuid.uuid4().hex[:8]
        role_name = (role or DEFAULT_ROLE).strip().lower()

        try:
            seat = get_role(role_name)
        except KeyError as exc:
            return Reply(
                call_id=call_id,
                provider=provider,
                role=role_name,
                ok=False,
                error=str(exc),
            )
        if not (prompt or "").strip():
            return Reply(
                call_id=call_id,
                provider=provider,
                role=role_name,
                ok=False,
                error="the brief was empty — a specialist needs something to answer",
            )

        system = seat.system_prompt(provider)
        brief = self.build_brief(prompt, context)
        started = time.monotonic()

        cache_key = self.cache.key(provider, model, system, brief)
        if use_cache:
            hit = self.cache.get(cache_key)
            if hit:
                return Reply(
                    call_id=call_id,
                    provider=provider,
                    role=role_name,
                    ok=True,
                    text=hit.get("text", ""),
                    backend=hit.get("backend"),
                    model=hit.get("model"),
                    elapsed_seconds=time.monotonic() - started,
                    cached=True,
                    system=system,
                    brief=brief,
                )

        try:
            provider_cfg = self.settings.provider(provider)
        except KeyError as exc:
            return Reply(
                call_id=call_id,
                provider=provider,
                role=role_name,
                ok=False,
                error=str(exc),
            )

        try:
            backend = self._backend_factory(self.settings, provider, model)
            result = backend.run(system, brief, provider_cfg.timeout_seconds)
        except SpecialistError as exc:
            reply = Reply(
                call_id=call_id,
                provider=provider,
                role=role_name,
                ok=False,
                error=str(exc),
                elapsed_seconds=time.monotonic() - started,
                system=system,
                brief=brief,
            )
            self.transcript.record(reply.record())
            return reply
        except Exception as exc:  # a backend bug must not sink the request
            reply = Reply(
                call_id=call_id,
                provider=provider,
                role=role_name,
                ok=False,
                error=f"{provider} backend raised {type(exc).__name__}: {exc}",
                elapsed_seconds=time.monotonic() - started,
                system=system,
                brief=brief,
            )
            self.transcript.record(reply.record())
            return reply

        reply = Reply(
            call_id=call_id,
            provider=provider,
            role=role_name,
            ok=True,
            text=result.text,
            backend=getattr(backend, "kind", None),
            model=result.model,
            elapsed_seconds=time.monotonic() - started,
            usage=result.usage,
            system=system,
            brief=brief,
            debug=result.debug,
        )
        self.cache.put(
            cache_key,
            {"text": reply.text, "model": reply.model, "backend": reply.backend},
        )
        self.transcript.record(reply.record())
        return reply

    # -- several specialists ---------------------------------------------

    def panel(
        self,
        prompt: str,
        seats: list[dict[str, Any]],
        context: str | None = None,
        use_cache: bool = True,
    ) -> list[Reply]:
        """Ask several specialists at once. Replies come back in seat order.

        Slow seats overlap instead of queueing, and a seat that fails simply
        returns its failure — the panel still delivers everyone else.
        """
        if not seats:
            return []
        workers = min(self.max_parallel, len(seats))

        def run(seat: dict[str, Any]) -> Reply:
            return self.ask(
                provider=seat.get("provider", ""),
                prompt=seat.get("prompt") or prompt,
                role=seat.get("role"),
                context=seat.get("context", context),
                model=seat.get("model"),
                use_cache=use_cache,
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(run, seats))
