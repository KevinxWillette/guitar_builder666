"""Drive a provider's official headless CLI as a specialist.

This is the cheap seat. `codex exec` and `grok -p` are the vendors' own
non-interactive modes, and both are covered by the chat subscriptions Killy
already pays for — so a roundtable call over this backend costs nothing beyond
the subscription. No browser automation, no scraping: these are supported
entry points built for scripts.

The argv is assembled from config rather than hard-coded, because CLI flags
drift faster than anything else in this system. If a vendor renames a flag,
`roundtable.config.json` is the fix.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from .base import BackendResult, SpecialistError, SpecialistTimeout, strip_ansi, tail


class CliBackend:
    """Runs one prompt through a provider's headless CLI and returns its output."""

    kind = "cli"

    def __init__(self, name: str, label: str, spec: dict[str, Any], cwd: str | None = None):
        self.name = name
        self.label = label
        self.spec = spec
        self.cwd = cwd
        self.command: list[str] = list(spec.get("command") or [])
        if not self.command:
            raise ValueError(f"{name}: cli.command is empty in the config")
        self.model = spec.get("model")
        self.model_flag = spec.get("model_flag")
        self.prompt_via = spec.get("prompt_via", "arg")
        if self.prompt_via not in ("arg", "stdin"):
            raise ValueError(
                f"{name}: cli.prompt_via must be 'arg' or 'stdin', got {self.prompt_via!r}"
            )

    @property
    def binary(self) -> str:
        return self.command[0]

    def installed(self) -> bool:
        return shutil.which(self.binary) is not None

    def _argv(self, message: str) -> list[str]:
        argv = list(self.command)
        if self.model and self.model_flag:
            argv += [self.model_flag, str(self.model)]
        if self.prompt_via == "arg":
            argv.append(message)
        return argv

    def run(self, system: str, brief: str, timeout: float) -> BackendResult:
        # Headless CLIs take a single prompt — there is no separate system slot —
        # so the role charter rides at the top of the message, fenced off from
        # the brief so the model can tell instruction from payload.
        message = f"{system}\n\n=== BRIEF FROM CLAUDE (the lead) ===\n{brief}"
        argv = self._argv(message)
        # Always hand the child a closed stdin: a CLI that probes for
        # interactive input must see EOF, not hang waiting on our terminal.
        stdin_data = "" if self.prompt_via == "arg" else message

        # A specialist advises; it must not wander into Killy's other work.
        env = dict(os.environ)
        env.setdefault("NO_COLOR", "1")
        env.setdefault("CI", "1")

        try:
            proc = subprocess.run(
                argv,
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.cwd,
                env=env,
            )
        except FileNotFoundError as exc:
            raise SpecialistError(
                f"{self.label}'s CLI (`{self.binary}`) is not installed or not on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise SpecialistTimeout(
                f"{self.label} did not answer within {timeout:.0f}s."
            ) from exc

        stdout = strip_ansi(proc.stdout or "").strip()
        stderr = strip_ansi(proc.stderr or "").strip()

        if proc.returncode != 0:
            detail = tail(stderr or stdout) or f"exit code {proc.returncode}"
            raise SpecialistError(f"{self.label}'s CLI failed: {detail}")
        if not stdout:
            hint = tail(stderr) or "no output on stdout"
            raise SpecialistError(f"{self.label}'s CLI returned nothing ({hint}).")

        return BackendResult(
            text=stdout,
            model=str(self.model) if self.model else f"{self.binary} default",
            usage=None,
            debug={
                # The prompt itself is deliberately not logged here; the
                # transcript layer owns that and can be switched off.
                "argv": argv[: len(self.command) + 2],
                "returncode": proc.returncode,
                "stderr_tail": tail(stderr, 400),
            },
        )
