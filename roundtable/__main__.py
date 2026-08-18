"""Command line for the roundtable.

    python -m roundtable serve      # what Claude launches (MCP over stdio)
    python -m roundtable doctor     # is the table reachable, and how
    python -m roundtable ask ...    # put a question to one specialist by hand
    python -m roundtable panel ...  # ask several at once
    python -m roundtable roles      # who can sit where
    python -m roundtable memory ... # inspect the shared project memory
    python -m roundtable selftest   # prove the plumbing works, offline
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .config import load_settings
from .memory import open_memory
from .mcp_stdio import McpServer
from .orchestrator import Orchestrator
from .providers.registry import probe, status
from .roles import ROLES
from .tools import build_tools

SERVER_NAME = "killy-roundtable"


def cmd_serve(args: argparse.Namespace) -> int:
    settings = load_settings()
    server = McpServer(SERVER_NAME, __version__, build_tools(settings))
    try:
        server.serve()
    except KeyboardInterrupt:  # pragma: no cover - operator pressed ctrl-c
        pass
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = load_settings()
    rows = (
        [probe(settings, name) for name in settings.providers]
        if args.live
        else status(settings)
    )
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0 if all(r["available"] for r in rows) else 1

    print(f"AI Roundtable {__version__}")
    print(f"config: {settings.source or 'built-in defaults'}")
    print(f"state:  {settings.state_dir}")
    if settings.free_only:
        print("money:  LOCKED — free_only is on, so no paid API can be called.")
    else:
        print("money:  UNLOCKED — free_only is off; paid API calls are allowed.")
    print()
    for row in rows:
        mark = "OK " if row["available"] else "-- "
        print(f"{mark}{row['label']} ({row['provider']})")
        if row["available"]:
            print(f"     via {row['active_backend']} · model {row['model']}")
            print(f"     cost: {row['cost']}")
        else:
            print(f"     {row.get('reason', 'unavailable')}")
        if "probe" in row:
            if row["probe"] == "ok":
                print(f"     live check: replied {row.get('probe_reply', '')!r}")
            elif row["probe"] == "failed":
                print(f"     live check FAILED: {row.get('probe_error')}")
                print("     -> usually a wrong CLI flag or a login that expired.")
                print("        Run the command by hand, then fix `command` in")
                print("        roundtable.config.json to match what works.")
        print()

    reachable = [r for r in rows if r["available"]]
    if not reachable:
        print("No specialists are reachable yet — see ROUNDTABLE.md, 'Setting it up'.")
        print("Claude still works on its own; it just has nobody to delegate to.")
        return 1
    print(f"{len(reachable)} of {len(rows)} specialists reachable.")
    return 0


def _print_reply(reply: Any) -> None:
    head = f"--- {reply.provider} as {reply.role}"
    if reply.ok:
        detail = f" ({reply.backend} · {reply.model} · {reply.elapsed_seconds:.1f}s"
        detail += ", cached)" if reply.cached else ")"
        print(head + detail)
        print(reply.text)
    else:
        print(head + " — FAILED)")
        print(reply.error)
    print()


def cmd_ask(args: argparse.Namespace) -> int:
    table = Orchestrator(load_settings())
    reply = table.ask(
        provider=args.provider,
        prompt=args.prompt,
        role=args.role,
        context=args.context,
        model=args.model,
        use_cache=not args.no_cache,
    )
    _print_reply(reply)
    return 0 if reply.ok else 1


def cmd_panel(args: argparse.Namespace) -> int:
    table = Orchestrator(load_settings())
    seats = [
        {"provider": provider, "role": role}
        for provider, role in (
            ("gpt", args.gpt_role),
            ("grok", args.grok_role),
        )
        if role != "none"
    ]
    replies = table.panel(args.prompt, seats, context=args.context, use_cache=not args.no_cache)
    for reply in replies:
        _print_reply(reply)
    answered = sum(1 for r in replies if r.ok)
    print(f"{answered}/{len(replies)} specialists answered.")
    print("(Claude would now reconcile these into one answer.)")
    return 0 if answered else 1


def cmd_roles(args: argparse.Namespace) -> int:
    wanted = [ROLES[args.role]] if args.role else list(ROLES.values())
    for role in wanted:
        if args.full:
            print("=" * 72)
            print(f"{role.name.upper()} — as played by {args.provider}")
            print("=" * 72)
            print(role.system_prompt(args.provider))
            print()
        else:
            print(f"{role.name:<12} {role.summary}")
    return 0


def cmd_memory(args: argparse.Namespace) -> int:
    settings = load_settings()
    memory = open_memory(settings)
    if args.memory_command == "add":
        entry = memory.write(args.key, args.text, args.tag)
        print(f"stored {entry.key!r}" + (f" [{', '.join(entry.tags)}]" if entry.tags else ""))
        return 0
    if args.memory_command == "forget":
        return 0 if memory.forget(args.key) else 1
    if args.memory_command == "search":
        hits = memory.search(args.query, tags=args.tag, limit=args.limit)
        if not hits:
            print("nothing matched.")
            return 1
        for entry, score in hits:
            tags = f" [{', '.join(entry.tags)}]" if entry.tags else ""
            print(f"{score:5.1f}  {entry.key}{tags}\n       {entry.snippet()}")
        return 0
    entries = memory.all()
    if not entries:
        print("memory is empty.")
        return 0
    for entry in entries:
        tags = f" [{', '.join(entry.tags)}]" if entry.tags else ""
        print(f"{entry.key}{tags}\n    {entry.snippet(160)}")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """Exercise the whole stack with fake specialists — no network, no keys."""
    import io

    from .providers.base import BackendResult, SpecialistError

    class FakeBackend:
        kind = "fake"

        def __init__(self, name: str):
            self.name = name

        def run(self, system: str, brief: str, timeout: float) -> BackendResult:
            if self.name == "grok":
                raise SpecialistError("pretend Grok is offline")
            return BackendResult(text="ANSWER — fake specialist reporting in.", model="fake-1")

    settings = load_settings()
    table = Orchestrator(settings, backend_factory=lambda s, n, m=None: FakeBackend(n))
    tools = build_tools(settings, table)
    server = McpServer(SERVER_NAME, __version__, tools)

    checks: list[tuple[str, bool, str]] = []

    handshake = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        }
    )
    ok = bool(handshake) and handshake.get("result", {}).get("protocolVersion") == "2025-06-18"
    checks.append(("MCP handshake", ok, str(handshake)[:80]))

    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in listed["result"]["tools"]]
    checks.append(("tools/list", "ask_gpt" in names and "ask_panel" in names, ", ".join(names)))

    called = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "ask_gpt", "arguments": {"prompt": "ping", "role": "engineer"}},
        }
    )
    body = called["result"]["content"][0]["text"]
    checks.append(("ask_gpt round trip", "fake specialist" in body, body[:60]))

    panel = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "ask_panel", "arguments": {"prompt": "ping", "no_cache": True}},
        }
    )
    panel_body = json.loads(panel["result"]["content"][0]["text"])
    degraded = panel_body["answered"] == 1 and panel_body["failed"] == 1
    checks.append(("panel survives a dead specialist", degraded, json.dumps(panel_body)[:60]))

    notification = server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    checks.append(("notifications get no reply", notification is None, repr(notification)))

    unknown = server.handle({"jsonrpc": "2.0", "id": 5, "method": "no/such/method"})
    checks.append(("unknown method errors cleanly", unknown.get("error", {}).get("code") == -32601, ""))

    stream = io.StringIO()
    McpServer(SERVER_NAME, __version__, tools)._write(stream, {"jsonrpc": "2.0", "id": 6, "result": {}})
    checks.append(("frames are newline delimited", stream.getvalue().endswith("\n"), ""))

    width = max(len(name) for name, _, _ in checks)
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}  {name:<{width}}  {detail}")
    failed = [c for c in checks if not c[1]]
    print()
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed.")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m roundtable",
        description="Killy AI Roundtable — Claude's specialist bench.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the MCP server on stdio (Claude launches this)")
    serve.set_defaults(func=cmd_serve)

    doctor = subparsers.add_parser("doctor", help="report which specialists are reachable")
    doctor.add_argument("--live", action="store_true", help="actually ping each specialist")
    doctor.add_argument("--json", action="store_true", help="machine-readable output")
    doctor.set_defaults(func=cmd_doctor)

    ask = subparsers.add_parser("ask", help="put one question to one specialist")
    ask.add_argument("provider", help="gpt or grok")
    ask.add_argument("prompt")
    ask.add_argument("--role", default=None, choices=sorted(ROLES))
    ask.add_argument("--context", default=None)
    ask.add_argument("--model", default=None)
    ask.add_argument("--no-cache", action="store_true")
    ask.set_defaults(func=cmd_ask)

    panel = subparsers.add_parser("panel", help="ask several specialists at once")
    panel.add_argument("prompt")
    panel.add_argument("--gpt-role", default="engineer", choices=sorted(ROLES) + ["none"])
    panel.add_argument("--grok-role", default="critic", choices=sorted(ROLES) + ["none"])
    panel.add_argument("--context", default=None)
    panel.add_argument("--no-cache", action="store_true")
    panel.set_defaults(func=cmd_panel)

    roles = subparsers.add_parser("roles", help="list the specialist seats")
    roles.add_argument("--full", action="store_true", help="print the full system prompts")
    roles.add_argument("--role", default=None, choices=sorted(ROLES), help="just this seat")
    roles.add_argument("--provider", default="gpt", help="whose version of the prompt to show")
    roles.set_defaults(func=cmd_roles)

    memory = subparsers.add_parser("memory", help="inspect the shared project memory")
    memory_sub = memory.add_subparsers(dest="memory_command")
    mem_list = memory_sub.add_parser("list", help="show everything remembered")
    mem_add = memory_sub.add_parser("add", help="remember a fact")
    mem_add.add_argument("key")
    mem_add.add_argument("text")
    mem_add.add_argument("--tag", action="append", default=[])
    mem_search = memory_sub.add_parser("search", help="search remembered facts")
    mem_search.add_argument("query")
    mem_search.add_argument("--tag", action="append", default=[])
    mem_search.add_argument("--limit", type=int, default=5)
    mem_forget = memory_sub.add_parser("forget", help="drop a fact by key")
    mem_forget.add_argument("key")
    memory.set_defaults(func=cmd_memory, memory_command=None)
    for sub in (mem_list, mem_add, mem_search, mem_forget):
        sub.set_defaults(func=cmd_memory)

    selftest = subparsers.add_parser("selftest", help="prove the plumbing works, offline")
    selftest.set_defaults(func=cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
