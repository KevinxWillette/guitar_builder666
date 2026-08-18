"""Find the CLI invocation that actually works on this machine.

The flags in the defaults are researched, not verified — vendor CLIs rename
things, and a wrong flag is the single most likely reason the table fails to
convene. Rather than leaving Killy to debug that, this probes the plausible
invocations with a throwaway question, keeps the first one that answers, and
writes it into the config.

That turns "these flags should work" into "these flags were tested on your
machine at 19:04 today", which is the difference between a system that is
finished and one that only looks finished.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .config import Settings, write_user_config
from .providers.base import SpecialistError
from .providers.cli_backend import CliBackend

#: A trivial brief. Short on purpose: it should cost almost nothing and it is
#: obvious from the reply whether the CLI understood us.
PROBE_SYSTEM = "You are answering a one-word connectivity check."
PROBE_BRIEF = "Reply with the single word: OK"

#: Candidate invocations per provider, best guess first. Each is (argv,
#: prompt_via, note). They differ only in the ways vendor CLIs actually vary:
#: which subcommand, which sandbox flag, and whether the prompt is an argument
#: or piped in.
CANDIDATES: dict[str, list[tuple[list[str], str, str]]] = {
    "gpt": [
        (["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check"], "arg",
         "sandboxed, no git check"),
        (["codex", "exec", "--skip-git-repo-check"], "arg", "no git check"),
        (["codex", "exec", "--sandbox", "read-only"], "arg", "sandboxed"),
        (["codex", "exec"], "arg", "plain exec"),
        (["codex", "exec", "-"], "stdin", "prompt piped in"),
    ],
    "grok": [
        (["grok", "-p", "--no-auto-update"], "arg", "headless, no update check"),
        (["grok", "-p"], "arg", "headless"),
        (["grok", "--print"], "arg", "print mode"),
        (["grok", "-p", "--no-auto-update"], "stdin", "headless, prompt piped in"),
        (["grok"], "stdin", "prompt piped in"),
    ],
}


def _looks_like_an_answer(text: str) -> bool:
    """Did the CLI answer the question, or just print help at us?

    A usage screen is the classic wrong-flag symptom, and it arrives on stdout
    with exit code 0 often enough that returncode alone will not catch it.
    """
    if not text or not text.strip():
        return False
    lowered = text.strip().lower()
    if len(lowered) > 4000:
        return False
    tells = ("usage:", "unknown option", "unrecognized", "unexpected argument",
             "invalid value", "see --help", "command not found")
    return not any(tell in lowered for tell in tells)


def try_candidate(
    provider: str,
    label: str,
    argv: list[str],
    prompt_via: str,
    cwd: str,
    timeout: float,
) -> tuple[bool, str]:
    """Run one candidate invocation. Returns (worked, what happened)."""
    try:
        backend = CliBackend(
            provider, label, {"command": argv, "prompt_via": prompt_via}, cwd=cwd
        )
        result = backend.run(PROBE_SYSTEM, PROBE_BRIEF, timeout)
    except SpecialistError as exc:
        return False, str(exc)
    if not _looks_like_an_answer(result.text):
        return False, f"answered with what looks like usage text: {result.text[:120]!r}"
    return True, result.text.strip()[:120]


def calibrate_provider(
    settings: Settings,
    provider: str,
    timeout: float = 90.0,
    report: Callable[[str], None] = print,
) -> dict[str, Any] | None:
    """Probe candidates for one provider; return the winner, or None."""
    config = settings.provider(provider)
    candidates = CANDIDATES.get(provider)
    if not candidates:
        # An unknown provider still gets one shot: whatever the config says.
        candidates = [(list(config.cli.get("command") or []),
                       config.cli.get("prompt_via", "arg"), "as configured")]

    binary = candidates[0][0][0] if candidates and candidates[0][0] else provider
    if not config.cli_installed():
        report(f"  {config.label}: not installed — skipping it.")
        return None

    for argv, prompt_via, note in candidates:
        shown = " ".join(argv) + (" <prompt>" if prompt_via == "arg" else " < prompt")
        report(f"  asking {config.label} this way: {shown}")
        started = time.monotonic()
        worked, detail = try_candidate(
            provider, config.label, argv, prompt_via, str(settings.root), timeout
        )
        elapsed = time.monotonic() - started
        if worked:
            report(f"    -> that worked. {config.label} answered {detail!r}.")
            return {"command": argv, "prompt_via": prompt_via}
        report(f"    -> no good ({detail}). Trying another way.")

    report(
        f"  {config.label} would not answer any way I asked. Usually that means "
        f"it is installed but not signed in yet."
    )
    return None


def calibrate(
    settings: Settings,
    providers: list[str] | None = None,
    timeout: float = 90.0,
    report: Callable[[str], None] = print,
    save: bool = True,
) -> dict[str, dict[str, Any]]:
    """Probe every provider and persist whatever worked."""
    wanted = providers or list(settings.providers)
    found: dict[str, dict[str, Any]] = {}

    for name in wanted:
        report(f"\nChecking {settings.provider(name).label}...")
        winner = calibrate_provider(settings, name, timeout=timeout, report=report)
        if winner:
            found[name] = winner

    if found and save:
        updates = {"providers": {name: {"cli": cli} for name, cli in found.items()}}
        path = write_user_config(settings.root, updates)
        report(f"\n  Remembered what works, so this only happens once.")
    return found
