"""Turn config into live backends, and report honestly on what is reachable.

Availability is computed, never assumed: a specialist is reachable when its CLI
is installed or its API key is set, and when it is neither, the reason says so
in words Killy can act on.
"""

from __future__ import annotations

from typing import Any

from ..config import ProviderConfig, Settings
from .api_backend import ApiBackend
from .base import Backend, SpecialistError
from .cli_backend import CliBackend


def build_backend(
    settings: Settings, name: str, model: str | None = None
) -> Backend:
    """Build the backend a specialist should use right now.

    ``model`` overrides the configured model for this one call, which is how
    Claude can send a cheap question to a cheap model without anyone editing
    config.

    Raises :class:`SpecialistError` when the specialist is unreachable, so the
    caller handles a missing provider the same way it handles a failing one.
    """
    provider = settings.provider(name)
    resolved = provider.resolve_backend()
    if resolved == "off":
        raise SpecialistError(provider.unavailable_reason() or f"{name} is unavailable.")
    if resolved == "cli":
        spec = dict(provider.cli)
        if model:
            spec["model"] = model
        return CliBackend(
            name=provider.name,
            label=provider.label,
            spec=spec,
            cwd=str(settings.root),
        )
    key = provider.api_key()
    if not key:  # pragma: no cover - resolve_backend already guarantees this
        raise SpecialistError(provider.unavailable_reason() or f"{name} is unavailable.")
    spec = dict(provider.api)
    if model:
        spec["model"] = model
    return ApiBackend(
        name=provider.name, label=provider.label, spec=spec, api_key=key
    )


def describe(provider: ProviderConfig) -> dict[str, Any]:
    """A status row for one specialist: what it would use, and why."""
    resolved = provider.resolve_backend()
    row: dict[str, Any] = {
        "provider": provider.name,
        "label": provider.label,
        "configured_backend": provider.backend,
        "active_backend": resolved,
        "available": resolved != "off",
        "cli_binary": provider.cli_binary,
        "cli_installed": provider.cli_installed(),
        "api_key_env": provider.api.get("key_env"),
        "api_key_present": provider.api_key() is not None,
        "free_only": provider.free_only,
        "timeout_seconds": provider.timeout_seconds,
    }
    if resolved == "cli":
        row["model"] = provider.cli.get("model") or f"{provider.cli_binary} default"
        row["cost"] = "free — covered by the subscription you already pay for"
    elif resolved == "api":
        row["model"] = provider.api.get("model")
        row["cost"] = "metered — billed per token"
    else:
        row["model"] = None
        row["cost"] = None
        row["reason"] = provider.unavailable_reason()
    return row


def status(settings: Settings) -> list[dict[str, Any]]:
    """Status rows for every configured specialist."""
    return [describe(p) for p in settings.providers.values()]


def probe(settings: Settings, name: str, timeout: float = 60.0) -> dict[str, Any]:
    """Actually call a specialist with a trivial brief to prove auth works.

    Cheap but not free — a handful of tokens over the API path — so this is only
    run when asked for (`doctor --live`).
    """
    row = describe(settings.provider(name))
    if not row["available"]:
        row["probe"] = "skipped"
        return row
    try:
        backend = build_backend(settings, name)
        result = backend.run(
            system="You are answering a connectivity check.",
            brief="Reply with the single word: OK",
            timeout=timeout,
        )
    except SpecialistError as exc:
        row["probe"] = "failed"
        row["probe_error"] = str(exc)
        return row
    row["probe"] = "ok"
    row["probe_reply"] = result.text.strip()[:120]
    if result.model:
        row["model"] = result.model
    return row
