"""Configuration for the roundtable: who the specialists are and how to reach them.

Everything that is likely to drift — model names, CLI flags, API endpoints — is
data in a JSON file rather than code, so upgrading to a newer model or adapting
to a renamed flag is an edit, not a patch.

Lookup order for the config file (first hit wins):

1. ``$ROUNDTABLE_CONFIG``
2. ``roundtable.config.json`` next to the repo root
3. ``~/.killy-roundtable/config.json``
4. built-in defaults below

A user file only needs the keys it wants to change; it is deep-merged onto the
defaults. Any string may contain ``${VAR}`` to pull a value from the
environment, which is how secrets stay out of the file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Where a specialist's work is allowed to come from.
#   cli  — drive the provider's official headless CLI, paid for by Killy's
#          existing chat subscription (ChatGPT Plus, SuperGrok).
#   api  — call the provider's HTTP API with a key, billed per token.
#   auto — use the CLI when its binary is installed, else the API when a key is
#          set, else report the specialist as unavailable.
#   off  — never call this specialist.
BACKENDS = ("auto", "cli", "api", "off")

ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Built-in defaults. The CLI command templates below reflect the documented
# headless modes as of August 2026; `python -m roundtable doctor` verifies them
# against what is actually installed, and any of them can be overridden.
DEFAULTS: dict[str, Any] = {
    "providers": {
        "gpt": {
            "label": "GPT",
            "backend": "auto",
            "timeout_seconds": 180,
            "cli": {
                # `codex exec` runs one prompt and prints the answer. Read-only
                # sandbox: a specialist advises, it does not edit Killy's files.
                "command": [
                    "codex",
                    "exec",
                    "--sandbox",
                    "read-only",
                    "--skip-git-repo-check",
                ],
                "model_flag": "--model",
                "model": None,
                "prompt_via": "arg",
            },
            "api": {
                "base_url": "https://api.openai.com/v1",
                "key_env": "OPENAI_API_KEY",
                "model": "gpt-5.5",
                "max_output_tokens": 4000,
                # Newer OpenAI models reject the older `max_tokens` name.
                "max_tokens_field": "max_completion_tokens",
            },
        },
        "grok": {
            "label": "Grok",
            "backend": "auto",
            "timeout_seconds": 180,
            "cli": {
                # `grok -p` is Grok Build's headless single-prompt mode.
                "command": ["grok", "-p", "--no-auto-update"],
                "model_flag": "--model",
                "model": None,
                "prompt_via": "arg",
            },
            "api": {
                "base_url": "https://api.x.ai/v1",
                "key_env": "XAI_API_KEY",
                "model": "grok-4.6",
                "max_output_tokens": 4000,
                "max_tokens_field": "max_tokens",
            },
        },
    },
    "limits": {
        # Hard ceiling on the context Claude may staple onto one specialist
        # call. Keeps a runaway paste from turning into a runaway bill.
        "context_chars": 24000,
        "prompt_chars": 12000,
        # Identical calls inside this window reuse the stored answer instead of
        # paying for it twice. 0 disables the cache.
        "cache_ttl_seconds": 900,
        # How many specialists may be in flight at once.
        "max_parallel": 4,
    },
    "memory": {
        # Shared project memory is opt-in and searched, never broadcast: Claude
        # pulls the entries a request actually needs and forwards only those.
        "enabled": True,
        "max_entries_returned": 5,
        "max_entry_chars": 2000,
    },
    "transcript": {
        # Raw specialist chatter is logged but stays out of Claude's answer
        # unless Killy asks for it.
        "enabled": True,
        "max_files": 200,
    },
}


def _expand(value: Any) -> Any:
    """Replace ``${VAR}`` with the environment's value, recursively."""
    if isinstance(value, str):
        return ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``overlay`` onto ``base`` without mutating either."""
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def find_config_file(root: Path | None = None) -> Path | None:
    """First config file that exists, following the documented lookup order."""
    candidates: list[Path] = []
    env_path = os.environ.get("ROUNDTABLE_CONFIG")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    base = root or Path(__file__).resolve().parents[1]
    candidates.append(base / "roundtable.config.json")
    candidates.append(Path.home() / ".killy-roundtable" / "config.json")
    for path in candidates:
        if path.is_file():
            return path
    return None


@dataclass
class ProviderConfig:
    """How to reach one specialist provider."""

    name: str
    label: str
    backend: str
    timeout_seconds: float
    cli: dict[str, Any]
    api: dict[str, Any]

    @property
    def cli_binary(self) -> str | None:
        command = self.cli.get("command") or []
        return command[0] if command else None

    def cli_installed(self) -> bool:
        """True when the provider's headless CLI is on PATH."""
        binary = self.cli_binary
        return bool(binary) and shutil.which(binary) is not None

    def api_key(self) -> str | None:
        """The API key from the environment, if the operator set one."""
        key_env = self.api.get("key_env")
        value = os.environ.get(key_env, "").strip() if key_env else ""
        return value or None

    def resolve_backend(self) -> str:
        """Pick the backend this specialist can actually use right now.

        Returns ``cli``, ``api`` or ``off``. ``auto`` prefers the CLI because it
        is already paid for by Killy's chat subscription; the metered API is the
        fallback.
        """
        if self.backend == "off":
            return "off"
        if self.backend == "cli":
            return "cli" if self.cli_installed() else "off"
        if self.backend == "api":
            return "api" if self.api_key() else "off"
        if self.cli_installed():
            return "cli"
        if self.api_key():
            return "api"
        return "off"

    def unavailable_reason(self) -> str | None:
        """Plain-language explanation of why this specialist cannot be called."""
        if self.backend == "off":
            return f"{self.label} is switched off in the config."
        resolved = self.resolve_backend()
        if resolved != "off":
            return None
        binary = self.cli_binary or "its CLI"
        key_env = self.api.get("key_env", "an API key")
        if self.backend == "cli":
            return f"{self.label}'s CLI (`{binary}`) is not installed."
        if self.backend == "api":
            return f"{self.label} has no API key: ${key_env} is not set."
        return (
            f"{self.label} is unreachable: `{binary}` is not installed and "
            f"${key_env} is not set."
        )


@dataclass
class Settings:
    """Everything the roundtable needs to run, assembled from config + defaults."""

    root: Path
    providers: dict[str, ProviderConfig]
    limits: dict[str, Any]
    memory: dict[str, Any]
    transcript: dict[str, Any]
    source: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def state_dir(self) -> Path:
        """Where memory, transcripts and the response cache live."""
        override = os.environ.get("ROUNDTABLE_STATE_DIR")
        path = Path(override).expanduser() if override else self.root / ".roundtable"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def provider(self, name: str) -> ProviderConfig:
        try:
            return self.providers[name]
        except KeyError:
            known = ", ".join(sorted(self.providers)) or "none"
            raise KeyError(f"unknown specialist provider {name!r}; known: {known}")


def load_settings(
    root: Path | None = None, overrides: dict[str, Any] | None = None
) -> Settings:
    """Build :class:`Settings` from defaults, the config file, and ``overrides``."""
    base = root or Path(__file__).resolve().parents[1]
    data = DEFAULTS
    source = find_config_file(base)
    if source is not None:
        try:
            user = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{source} is not valid JSON: {exc}") from exc
        if not isinstance(user, dict):
            raise ValueError(f"{source} must contain a JSON object")
        data = _merge(data, user)
    if overrides:
        data = _merge(data, overrides)
    data = _expand(data)

    providers: dict[str, ProviderConfig] = {}
    for name, spec in (data.get("providers") or {}).items():
        backend = spec.get("backend", "auto")
        if backend not in BACKENDS:
            raise ValueError(
                f"provider {name!r}: backend {backend!r} must be one of "
                f"{', '.join(BACKENDS)}"
            )
        providers[name] = ProviderConfig(
            name=name,
            label=spec.get("label", name.upper()),
            backend=backend,
            timeout_seconds=float(spec.get("timeout_seconds", 180)),
            cli=dict(spec.get("cli") or {}),
            api=dict(spec.get("api") or {}),
        )

    return Settings(
        root=base,
        providers=providers,
        limits=dict(data.get("limits") or {}),
        memory=dict(data.get("memory") or {}),
        transcript=dict(data.get("transcript") or {}),
        source=source,
        raw=data,
    )
