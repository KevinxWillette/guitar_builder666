"""Tests for the Killy AI Roundtable.

Everything here runs offline with no API keys: real specialists are replaced by
fake backends and, where the subprocess path itself is under test, by throwaway
shell scripts. What is actually being checked is the behaviour Killy depends on
— that one dead specialist cannot sink a request, that the MCP wire format is
right, and that memory hands back only what was asked for.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roundtable import __version__
from roundtable.calibrate import _looks_like_an_answer, calibrate
from roundtable.config import ProviderConfig, load_settings, write_user_config
from roundtable.mcp_stdio import McpServer
from roundtable.memory import Memory
from roundtable.orchestrator import Orchestrator, clip
from roundtable.providers.api_backend import ApiBackend, _extract_text
from roundtable.providers.base import BackendResult, SpecialistError, SpecialistTimeout
from roundtable.providers.cli_backend import CliBackend
from roundtable.roles import ROLES, get_role
from roundtable.tools import build_tools
from roundtable.transcript import Transcript


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """An isolated repo root and state directory, with no config file in sight."""
    monkeypatch.delenv("ROUNDTABLE_CONFIG", raising=False)
    monkeypatch.setenv("ROUNDTABLE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    return tmp_path


@pytest.fixture
def settings(workspace):
    return load_settings(root=workspace)


class FakeBackend:
    """A specialist that answers, fails or stalls on command."""

    kind = "fake"

    def __init__(self, name: str, behaviour: dict[str, str] | None = None, delay: float = 0.0):
        self.name = name
        self.behaviour = behaviour or {}
        self.delay = delay
        self.calls: list[tuple[str, str]] = []

    def run(self, system: str, brief: str, timeout: float) -> BackendResult:
        self.calls.append((system, brief))
        if self.delay:
            time.sleep(self.delay)
        mode = self.behaviour.get(self.name, "answer")
        if mode == "fail":
            raise SpecialistError(f"{self.name} is offline")
        if mode == "timeout":
            raise SpecialistTimeout(f"{self.name} timed out")
        if mode == "crash":
            raise RuntimeError("backend bug")
        return BackendResult(text=f"ANSWER — {self.name} answered", model=f"{self.name}-fake")


def table(settings, behaviour=None, delay=0.0):
    """An orchestrator whose specialists are fakes."""
    return Orchestrator(
        settings, backend_factory=lambda s, name, model=None: FakeBackend(name, behaviour, delay)
    )


# --- configuration ---------------------------------------------------------


def test_defaults_load_without_a_config_file(settings):
    assert set(settings.providers) == {"gpt", "grok"}
    assert settings.provider("gpt").api["base_url"] == "https://api.openai.com/v1"
    assert settings.source is None


def test_user_config_is_deep_merged_over_defaults(workspace):
    (workspace / "roundtable.config.json").write_text(
        json.dumps({"providers": {"grok": {"api": {"model": "grok-experimental"}}}})
    )
    settings = load_settings(root=workspace)
    grok = settings.provider("grok")
    # The override lands...
    assert grok.api["model"] == "grok-experimental"
    # ...without wiping the sibling keys it did not mention.
    assert grok.api["base_url"] == "https://api.x.ai/v1"
    assert grok.label == "Grok"


def test_config_expands_environment_variables(workspace, monkeypatch):
    monkeypatch.setenv("MY_MODEL", "gpt-from-env")
    (workspace / "roundtable.config.json").write_text(
        json.dumps({"providers": {"gpt": {"api": {"model": "${MY_MODEL}"}}}})
    )
    assert load_settings(root=workspace).provider("gpt").api["model"] == "gpt-from-env"


def test_invalid_backend_is_rejected_loudly(workspace):
    (workspace / "roundtable.config.json").write_text(
        json.dumps({"providers": {"gpt": {"backend": "carrier-pigeon"}}})
    )
    with pytest.raises(ValueError, match="carrier-pigeon"):
        load_settings(root=workspace)


def _provider(**kwargs):
    defaults = dict(
        name="gpt",
        label="GPT",
        backend="auto",
        timeout_seconds=10,
        cli={"command": ["definitely-not-installed"]},
        api={"key_env": "OPENAI_API_KEY", "base_url": "x", "model": "y"},
    )
    defaults.update(kwargs)
    return ProviderConfig(**defaults)


def test_backend_resolution_prefers_the_subscription_cli(workspace, monkeypatch):
    """`auto` picks the already-paid-for CLI over the metered API."""
    provider = _provider(free_only=False)
    assert provider.resolve_backend() == "off"
    assert "not installed" in provider.unavailable_reason()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert provider.resolve_backend() == "api"

    monkeypatch.setattr(
        "roundtable.config.shutil.which", lambda binary: "/usr/bin/" + binary
    )
    assert provider.resolve_backend() == "cli"


def test_free_only_blocks_paid_calls_even_with_a_key_available(monkeypatch):
    """The money lock is the point: a stray API key must not start spending."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = _provider(free_only=True)
    assert provider.api_key() == "sk-test"        # the key is right there...
    assert provider.resolve_backend() == "off"    # ...and still nothing is spent.
    assert "only free way" in provider.unavailable_reason()


def test_free_only_overrides_an_explicit_api_backend(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = _provider(backend="api", free_only=True)
    assert provider.resolve_backend() == "off"
    assert "free_only" in provider.unavailable_reason()


def test_free_only_never_blocks_the_free_cli(monkeypatch):
    monkeypatch.setattr("roundtable.config.shutil.which", lambda binary: "/usr/bin/" + binary)
    assert _provider(free_only=True).resolve_backend() == "cli"


def test_free_only_is_on_by_default_and_can_be_switched_off(workspace):
    assert load_settings(root=workspace).free_only is True
    assert all(p.free_only for p in load_settings(root=workspace).providers.values())

    (workspace / "roundtable.config.json").write_text(json.dumps({"free_only": False}))
    settings = load_settings(root=workspace)
    assert settings.free_only is False
    assert not any(p.free_only for p in settings.providers.values())


def test_the_orchestrator_refuses_a_paid_call_under_the_lock(workspace, monkeypatch):
    """End to end: with the lock on, a real dispatch never reaches a backend."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = load_settings(root=workspace)
    reply = Orchestrator(settings).ask("gpt", "would this cost money?")
    assert reply.ok is False
    assert "free" in reply.error


def test_switched_off_provider_stays_off(workspace, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    (workspace / "roundtable.config.json").write_text(
        json.dumps({"providers": {"grok": {"backend": "off"}}})
    )
    settings = load_settings(root=workspace)
    assert settings.provider("grok").resolve_backend() == "off"


# --- roles -----------------------------------------------------------------


def test_every_role_carries_the_shared_output_contract():
    for name in ROLES:
        prompt = get_role(name).system_prompt("gpt")
        assert "CONFIDENCE" in prompt and "ASSUMPTIONS" in prompt
        # The framing that keeps specialists briefing Claude, not Killy.
        assert "Claude is the lead" in prompt


def test_unknown_role_names_the_alternatives():
    with pytest.raises(KeyError, match="engineer"):
        get_role("wizard")


# --- orchestration ---------------------------------------------------------


def test_ask_returns_the_specialists_answer(settings):
    reply = table(settings).ask("gpt", "How do I wire this?", role="engineer")
    assert reply.ok
    assert "gpt answered" in reply.text
    assert reply.role == "engineer"
    assert reply.public()["answer"] == reply.text
    # The brief Claude wrote is kept for the transcript but not read back to it.
    assert "brief" not in reply.public()


def test_a_failing_specialist_returns_a_reason_rather_than_raising(settings):
    reply = table(settings, {"grok": "fail"}).ask("grok", "thoughts?", role="critic")
    assert reply.ok is False
    assert "offline" in reply.error


def test_a_backend_bug_is_contained(settings):
    """An unexpected exception must degrade one seat, not the whole request."""
    reply = table(settings, {"gpt": "crash"}).ask("gpt", "hello")
    assert reply.ok is False
    assert "RuntimeError" in reply.error


def test_timeout_is_reported_as_a_failed_seat(settings):
    reply = table(settings, {"gpt": "timeout"}).ask("gpt", "hello")
    assert reply.ok is False
    assert "timed out" in reply.error


def test_empty_and_unknown_inputs_are_rejected_before_any_call(settings):
    orchestrator = table(settings)
    assert orchestrator.ask("gpt", "   ").error.startswith("the brief was empty")
    assert "unknown role" in orchestrator.ask("gpt", "hi", role="wizard").error
    assert "unknown specialist" in orchestrator.ask("mystery", "hi").error


def test_panel_keeps_going_when_one_seat_dies(settings):
    replies = table(settings, {"grok": "fail"}).panel(
        "Ship it?",
        [{"provider": "gpt", "role": "engineer"}, {"provider": "grok", "role": "critic"}],
    )
    assert [r.provider for r in replies] == ["gpt", "grok"]  # seat order preserved
    assert [r.ok for r in replies] == [True, False]


def test_panel_runs_seats_in_parallel(settings):
    """Two half-second specialists must cost about half a second, not one."""
    seats = [{"provider": "gpt", "role": "engineer"}, {"provider": "grok", "role": "critic"}]
    started = time.monotonic()
    replies = table(settings, delay=0.4).panel("Ship it?", seats, use_cache=False)
    elapsed = time.monotonic() - started
    assert all(r.ok for r in replies)
    assert elapsed < 0.75, f"seats appear to have run one after another ({elapsed:.2f}s)"


def test_per_seat_prompts_override_the_shared_brief(settings):
    orchestrator = table(settings)
    replies = orchestrator.panel(
        "shared brief",
        [
            {"provider": "gpt", "role": "engineer", "prompt": "bespoke brief"},
            {"provider": "grok", "role": "critic"},
        ],
    )
    assert "bespoke brief" in replies[0].brief
    assert "shared brief" in replies[1].brief


def test_identical_calls_are_served_from_cache(settings):
    orchestrator = table(settings)
    first = orchestrator.ask("gpt", "same question", role="analyst")
    second = orchestrator.ask("gpt", "same question", role="analyst")
    assert first.cached is False
    assert second.cached is True
    assert second.text == first.text
    # ...and an explicit second opinion bypasses it.
    assert orchestrator.ask("gpt", "same question", role="analyst", use_cache=False).cached is False


def test_a_different_role_is_a_different_question(settings):
    orchestrator = table(settings)
    orchestrator.ask("gpt", "same words", role="engineer")
    assert orchestrator.ask("gpt", "same words", role="critic").cached is False


def test_oversized_input_is_trimmed_with_a_visible_marker(settings):
    orchestrator = table(settings)
    orchestrator.prompt_chars = 50
    reply = orchestrator.ask("gpt", "x" * 500)
    assert "truncated at 50 characters" in reply.brief
    assert len(reply.brief) < 300


def test_clip_leaves_short_text_alone():
    assert clip("short", 100, "brief") == "short"


def test_context_is_fenced_off_from_the_brief(settings):
    reply = table(settings).ask("gpt", "the question", context="the background")
    assert "CONTEXT SUPPLIED BY THE LEAD" in reply.brief
    assert reply.brief.index("the question") < reply.brief.index("the background")


# --- the CLI backend (real subprocesses) -----------------------------------


def _fake_cli(directory: Path, name: str, script: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    return path


@pytest.mark.skipif(os.name == "nt", reason="shell-script stand-ins are POSIX only")
def test_cli_backend_runs_a_real_process_and_returns_its_output(tmp_path):
    _fake_cli(tmp_path / "bin", "faketool", '#!/bin/sh\necho "ANSWER — heard: $1"\n')
    backend = CliBackend(
        "gpt", "GPT", {"command": [str(tmp_path / "bin" / "faketool")], "prompt_via": "arg"}
    )
    result = backend.run("system prompt", "the brief", timeout=10)
    assert "the brief" in result.text
    assert "system prompt" in result.text  # the role rides along in the message


@pytest.mark.skipif(os.name == "nt", reason="shell-script stand-ins are POSIX only")
def test_cli_backend_can_deliver_the_prompt_on_stdin(tmp_path):
    _fake_cli(tmp_path / "bin", "stdintool", "#!/bin/sh\ncat\n")
    backend = CliBackend(
        "grok", "Grok", {"command": [str(tmp_path / "bin" / "stdintool")], "prompt_via": "stdin"}
    )
    assert "the brief" in backend.run("system", "the brief", timeout=10).text


@pytest.mark.skipif(os.name == "nt", reason="shell-script stand-ins are POSIX only")
def test_cli_backend_reports_a_failing_process(tmp_path):
    _fake_cli(tmp_path / "bin", "angrytool", '#!/bin/sh\necho "not logged in" >&2\nexit 3\n')
    backend = CliBackend("gpt", "GPT", {"command": [str(tmp_path / "bin" / "angrytool")]})
    with pytest.raises(SpecialistError, match="not logged in"):
        backend.run("system", "brief", timeout=10)


@pytest.mark.skipif(os.name == "nt", reason="shell-script stand-ins are POSIX only")
def test_cli_backend_times_out_rather_than_hanging(tmp_path):
    _fake_cli(tmp_path / "bin", "slowtool", "#!/bin/sh\nsleep 5\n")
    backend = CliBackend("gpt", "GPT", {"command": [str(tmp_path / "bin" / "slowtool")]})
    with pytest.raises(SpecialistTimeout):
        backend.run("system", "brief", timeout=0.5)


@pytest.mark.skipif(os.name == "nt", reason="shell-script stand-ins are POSIX only")
def test_cli_backend_strips_terminal_colour_codes(tmp_path):
    _fake_cli(tmp_path / "bin", "colourtool", '#!/bin/sh\nprintf "\\033[31mred answer\\033[0m\\n"\n')
    backend = CliBackend("gpt", "GPT", {"command": [str(tmp_path / "bin" / "colourtool")]})
    assert backend.run("system", "brief", timeout=10).text == "red answer"


def test_cli_backend_says_so_when_the_tool_is_not_installed():
    backend = CliBackend("gpt", "GPT", {"command": ["no-such-binary-anywhere"]})
    assert backend.installed() is False
    with pytest.raises(SpecialistError, match="not installed"):
        backend.run("system", "brief", timeout=5)


def test_cli_backend_rejects_an_empty_command():
    with pytest.raises(ValueError, match="cli.command is empty"):
        CliBackend("gpt", "GPT", {"command": []})


def test_cli_backend_appends_the_model_flag_when_configured():
    backend = CliBackend(
        "gpt", "GPT", {"command": ["tool", "exec"], "model_flag": "--model", "model": "gpt-x"}
    )
    assert backend._argv("hello") == ["tool", "exec", "--model", "gpt-x", "hello"]


# --- calibration: finding the invocation that works on this machine --------


def test_usage_text_is_not_mistaken_for_an_answer():
    """The classic wrong-flag symptom: a usage screen, on stdout, exit code 0."""
    assert _looks_like_an_answer("OK") is True
    assert _looks_like_an_answer("Usage: codex exec [OPTIONS]") is False
    assert _looks_like_an_answer("error: unexpected argument '--sandbox'") is False
    assert _looks_like_an_answer("unknown option --print") is False
    assert _looks_like_an_answer("") is False
    assert _looks_like_an_answer("   ") is False


@pytest.mark.skipif(os.name == "nt", reason="shell-script stand-ins are POSIX only")
def test_calibrate_finds_the_working_flags_and_saves_them(workspace, monkeypatch):
    """A CLI that rejects the first candidate must not leave the table broken."""
    bin_dir = workspace / "bin"
    # This stand-in rejects --sandbox, as if the flag had been renamed.
    _fake_cli(
        bin_dir,
        "codex",
        '#!/bin/sh\n'
        'for a in "$@"; do\n'
        '  if [ "$a" = "--sandbox" ]; then echo "error: unexpected argument"; exit 0; fi\n'
        "done\n"
        "echo OK\n",
    )
    # ...and this one only answers when the prompt arrives on stdin.
    _fake_cli(
        bin_dir,
        "grok",
        '#!/bin/sh\ndata=$(cat)\nif [ -n "$data" ]; then echo OK; else echo "Usage: grok"; exit 0; fi\n',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    settings = load_settings(root=workspace)
    found = calibrate(settings, timeout=15, report=lambda *_: None)

    # It skipped the broken candidate rather than giving up on GPT...
    assert found["gpt"]["command"] == ["codex", "exec", "--skip-git-repo-check"]
    assert found["gpt"]["prompt_via"] == "arg"
    # ...and discovered that Grok needs the prompt piped in.
    assert found["grok"]["prompt_via"] == "stdin"

    # The result is persisted, so the machine is only figured out once.
    saved = json.loads((workspace / "roundtable.config.json").read_text())
    assert saved["providers"]["gpt"]["cli"]["command"] == found["gpt"]["command"]
    # ...and reloading actually picks it up.
    assert load_settings(root=workspace).provider("gpt").cli["command"] == found["gpt"]["command"]


@pytest.mark.skipif(os.name == "nt", reason="shell-script stand-ins are POSIX only")
def test_calibrate_reports_nothing_when_a_cli_never_answers(workspace, monkeypatch):
    _fake_cli(workspace / "bin", "codex", '#!/bin/sh\necho "Usage: codex"\nexit 0\n')
    monkeypatch.setenv("PATH", f"{workspace / 'bin'}{os.pathsep}{os.environ['PATH']}")
    found = calibrate(load_settings(root=workspace), timeout=15, report=lambda *_: None)
    assert "gpt" not in found


def test_calibrate_skips_a_cli_that_is_not_installed(workspace):
    found = calibrate(load_settings(root=workspace), timeout=5, report=lambda *_: None)
    assert found == {}
    # Nothing was written, because nothing was learned.
    assert not (workspace / "roundtable.config.json").exists()


def test_write_user_config_merges_instead_of_clobbering(workspace):
    write_user_config(workspace, {"providers": {"gpt": {"cli": {"command": ["a"]}}}})
    write_user_config(workspace, {"providers": {"grok": {"cli": {"command": ["b"]}}}})
    saved = json.loads((workspace / "roundtable.config.json").read_text())
    assert saved["providers"]["gpt"]["cli"]["command"] == ["a"]  # survived
    assert saved["providers"]["grok"]["cli"]["command"] == ["b"]


def test_write_user_config_never_destroys_an_unparseable_file(workspace):
    broken = workspace / "roundtable.config.json"
    broken.write_text("{ this was hand-edited badly")
    path = write_user_config(workspace, {"free_only": True})
    assert path.name == "roundtable.config.generated.json"
    assert broken.read_text().startswith("{ this was")  # left alone


# --- the API backend (no network) ------------------------------------------


def test_api_backend_builds_a_chat_completions_payload():
    backend = ApiBackend(
        "gpt",
        "GPT",
        {
            "base_url": "https://api.example.com/v1",
            "model": "gpt-test",
            "max_output_tokens": 500,
            "max_tokens_field": "max_completion_tokens",
        },
        api_key="sk-test",
    )
    payload = backend._payload("system", "brief")
    assert backend.endpoint == "https://api.example.com/v1/chat/completions"
    assert payload["model"] == "gpt-test"
    assert payload["max_completion_tokens"] == 500
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]


def test_api_backend_returns_the_assistant_text(monkeypatch):
    backend = ApiBackend(
        "grok", "Grok", {"base_url": "https://x", "model": "grok-test"}, api_key="k"
    )
    monkeypatch.setattr(
        ApiBackend,
        "_post",
        lambda self, body, timeout: {
            "model": "grok-test",
            "choices": [{"message": {"content": "ANSWER — via API"}}],
            "usage": {"total_tokens": 42},
        },
    )
    result = backend.run("system", "brief", timeout=5)
    assert result.text == "ANSWER — via API"
    assert result.usage == {"total_tokens": 42}


def test_api_backend_rejects_an_empty_answer(monkeypatch):
    backend = ApiBackend("gpt", "GPT", {"base_url": "https://x", "model": "m"}, api_key="k")
    monkeypatch.setattr(
        ApiBackend,
        "_post",
        lambda self, body, timeout: {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
    )
    with pytest.raises(SpecialistError, match="finish_reason=length"):
        backend.run("system", "brief", timeout=5)


def test_api_backend_understands_the_content_parts_shape():
    payload = {
        "choices": [
            {"message": {"content": [{"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]}}
        ]
    }
    assert _extract_text(payload) == "part one\npart two"


def test_api_backend_needs_a_model_and_a_base_url():
    with pytest.raises(ValueError, match="api.model"):
        ApiBackend("gpt", "GPT", {"base_url": "https://x"}, api_key="k")
    with pytest.raises(ValueError, match="api.base_url"):
        ApiBackend("gpt", "GPT", {"model": "m"}, api_key="k")


# --- shared memory ---------------------------------------------------------


def test_memory_writes_searches_and_upserts(tmp_path):
    memory = Memory(tmp_path / "memory.jsonl")
    memory.write("deploy-target", "The site deploys from the docs folder.", ["infra"])
    memory.write("python-version", "Everything targets Python 3.9.", ["infra"])

    hits = memory.search("where does it deploy")
    assert hits[0][0].key == "deploy-target"

    memory.write("python-version", "Everything targets Python 3.11 now.", ["infra"])
    assert len(memory.all()) == 2  # replaced, not duplicated
    assert "3.11" in memory.search("python-version")[0][0].text


def test_memory_search_is_scoped_not_a_data_dump(tmp_path):
    """The point of search is that unrelated projects stay out of the brief."""
    memory = Memory(tmp_path / "memory.jsonl")
    memory.write("build-command", "The build runs with make release.", ["infra"])
    memory.write("editor-choice", "Drafts are written in plain markdown.", ["writing"])

    hits = memory.search("how does the build run")
    assert [entry.key for entry, _ in hits] == ["build-command"]

    tagged = memory.search("anything", tags=["writing"])
    assert all("writing" in entry.tags for entry, _ in tagged)


def test_memory_truncates_oversized_entries(tmp_path):
    memory = Memory(tmp_path / "memory.jsonl", max_entry_chars=50)
    entry = memory.write("long", "y" * 500)
    assert entry.text.endswith("[truncated]")
    assert len(entry.text) < 100


def test_memory_survives_a_corrupted_line(tmp_path):
    path = tmp_path / "memory.jsonl"
    memory = Memory(path)
    memory.write("good", "a real fact", ["tag"])
    path.write_text(path.read_text() + "{ this is not json\n")
    assert [e.key for e in memory.all()] == ["good"]


def test_memory_rejects_blank_entries_and_forgets_on_request(tmp_path):
    memory = Memory(tmp_path / "memory.jsonl")
    with pytest.raises(ValueError):
        memory.write("", "text")
    with pytest.raises(ValueError):
        memory.write("key", "   ")
    memory.write("temp", "throwaway")
    assert memory.forget("temp") is True
    assert memory.forget("temp") is False


# --- transcripts -----------------------------------------------------------


def test_transcript_stores_the_full_call_and_hands_it_back(tmp_path, settings):
    orchestrator = table(settings)
    reply = orchestrator.ask("gpt", "a memorable question", role="engineer")

    record = orchestrator.transcript.get(reply.call_id)
    assert record is not None
    assert "a memorable question" in record["brief"]  # the brief is kept...
    assert record["text"] == reply.text
    assert orchestrator.transcript.recent(5)[0]["call_id"] == reply.call_id


def test_transcript_prunes_to_its_limit(tmp_path):
    transcript = Transcript(tmp_path / "t", enabled=True, max_files=3)
    for i in range(6):
        transcript.record({"call_id": f"{i:04d}", "provider": "gpt", "ok": True})
    assert len(list((tmp_path / "t").glob("*.json"))) <= 3


def test_transcript_can_be_switched_off(tmp_path):
    transcript = Transcript(tmp_path / "t", enabled=False)
    transcript.record({"call_id": "x"})
    assert not (tmp_path / "t").exists()


# --- the MCP wire ----------------------------------------------------------


@pytest.fixture
def server(settings):
    return McpServer("killy-roundtable", __version__, build_tools(settings, table(settings)))


def request(server, method, params=None, msg_id=1):
    message = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        message["params"] = params
    return server.handle(message)


def test_initialize_echoes_a_version_the_client_asked_for(server):
    result = request(server, "initialize", {"protocolVersion": "2024-11-05"})["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["serverInfo"]["name"] == "killy-roundtable"


def test_initialize_falls_back_for_an_unknown_version(server):
    result = request(server, "initialize", {"protocolVersion": "1999-01-01"})["result"]
    assert result["protocolVersion"] == "2025-06-18"


def test_tools_list_advertises_the_whole_bench(server):
    tools = request(server, "tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "ask_gpt",
        "ask_grok",
        "ask_panel",
        "roundtable_status",
        "memory_search",
        "memory_write",
        "show_transcript",
    }
    for tool in tools:
        assert tool["description"] and tool["inputSchema"]["type"] == "object"


def test_notifications_are_never_answered(server):
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping_is_answered_empty(server):
    assert request(server, "ping")["result"] == {}


def test_unknown_methods_and_malformed_messages_error_cleanly(server):
    assert request(server, "no/such/method")["error"]["code"] == -32601
    assert server.handle({"id": 1, "method": "tools/list"})["error"]["code"] == -32600


def test_calling_a_tool_returns_content(server):
    result = request(
        server, "tools/call", {"name": "ask_gpt", "arguments": {"prompt": "ping", "role": "engineer"}}
    )["result"]
    assert result["isError"] is False
    body = json.loads(result["content"][0]["text"])
    assert body["ok"] is True and "gpt answered" in body["answer"]


def test_a_failing_specialist_is_a_result_not_a_transport_error(settings):
    """Claude should read the failure and adapt, not lose the turn to an exception."""
    server = McpServer("t", "0", build_tools(settings, table(settings, {"grok": "fail"})))
    result = request(server, "tools/call", {"name": "ask_grok", "arguments": {"prompt": "ping"}})["result"]
    assert result["isError"] is False
    body = json.loads(result["content"][0]["text"])
    assert body["ok"] is False and "offline" in body["error"]


def test_an_unknown_tool_is_an_invalid_params_error(server):
    assert request(server, "tools/call", {"name": "ask_gemini", "arguments": {}})["error"]["code"] == -32602


def test_a_tool_that_raises_is_reported_inside_the_result(settings):
    from roundtable.mcp_stdio import Tool

    def explode(args):
        raise RuntimeError("tool blew up")

    server = McpServer("t", "0", [Tool("boom", "d", {"type": "object"}, explode)])
    result = request(server, "tools/call", {"name": "boom", "arguments": {}})["result"]
    assert result["isError"] is True
    assert "tool blew up" in result["content"][0]["text"]


def test_panel_tool_reports_partial_success(settings):
    server = McpServer("t", "0", build_tools(settings, table(settings, {"grok": "fail"})))
    result = request(server, "tools/call", {"name": "ask_panel", "arguments": {"prompt": "ship?"}})["result"]
    body = json.loads(result["content"][0]["text"])
    assert body["answered"] == 1 and body["failed"] == 1


def test_status_tool_explains_why_a_specialist_is_missing(server):
    body = json.loads(
        request(server, "tools/call", {"name": "roundtable_status", "arguments": {}})["result"]["content"][0]["text"]
    )
    assert {row["provider"] for row in body["specialists"]} == {"gpt", "grok"}
    assert all("reason" in row for row in body["specialists"])  # nothing is installed in CI
    assert "engineer" in body["roles"]


def test_memory_tools_round_trip_through_mcp(server):
    request(
        server,
        "tools/call",
        {
            "name": "memory_write",
            "arguments": {"key": "backup-policy", "text": "Backups run nightly to an external disk.", "tags": ["infra"]},
        },
    )
    body = json.loads(
        request(server, "tools/call", {"name": "memory_search", "arguments": {"query": "when do backups run"}})[
            "result"
        ]["content"][0]["text"]
    )
    assert body["hits"][0]["key"] == "backup-policy"


def test_transcript_tool_returns_what_a_specialist_actually_said(server):
    call = json.loads(
        request(server, "tools/call", {"name": "ask_gpt", "arguments": {"prompt": "ping"}})["result"]["content"][0][
            "text"
        ]
    )
    body = json.loads(
        request(server, "tools/call", {"name": "show_transcript", "arguments": {"call_id": call["call_id"]}})[
            "result"
        ]["content"][0]["text"]
    )
    assert body["found"] is True
    assert body["call"]["text"] == call["answer"]


def test_the_server_loop_speaks_newline_delimited_json(server):
    import io

    incoming = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        "not json at all\n"
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
    )
    outgoing = io.StringIO()
    server.serve(incoming, outgoing)

    lines = [json.loads(line) for line in outgoing.getvalue().splitlines() if line.strip()]
    # initialize, a parse error for the junk, tools/list — and nothing for the notification.
    assert [entry.get("id") for entry in lines] == [1, None, 2]
    assert lines[1]["error"]["code"] == -32700
