"""The tools Claude sees, and what they tell Claude about using them.

These descriptions are load-bearing. They are the only place the system can
tell Claude *when* delegating is worth it, and getting that wrong in either
direction is the whole failure mode: a table that never convenes is useless,
and one that convenes for every question is slow and expensive. So each
description says what the seat is for and, just as plainly, when to skip it.
"""

from __future__ import annotations

from typing import Any

from .config import Settings
from .memory import open_memory
from .mcp_stdio import Tool
from .orchestrator import Orchestrator
from .providers.registry import status as provider_status
from .roles import role_menu, role_names
from .transcript import open_transcript

ROLE_ENUM = role_names()

_ROLE_HELP = f"Which seat the specialist takes. {role_menu()}."

_DELEGATION_NOTE = (
    "You are the lead: read the reply, judge it, and fold what survives into "
    "your own answer. Do not paste it through to the user, and do not treat it "
    "as more authoritative than your own reasoning."
)


def _ask_schema(provider_label: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    f"The brief for {provider_label}. Self-contained: the "
                    "specialist cannot see your conversation with the user, so "
                    "state the question and everything needed to answer it."
                ),
            },
            "role": {
                "type": "string",
                "enum": ROLE_ENUM,
                "description": _ROLE_HELP,
            },
            "context": {
                "type": "string",
                "description": (
                    "Optional background — code, prior decisions, memory hits. "
                    "Send only what this question needs; everything here costs "
                    "tokens and dilutes the brief."
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Optional model override for this one call. Omit to use the "
                    "configured default."
                ),
            },
            "no_cache": {
                "type": "boolean",
                "description": (
                    "Force a fresh call instead of reusing an identical recent "
                    "answer. Use when you deliberately want a second opinion."
                ),
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    }


def build_tools(settings: Settings, orchestrator: Orchestrator | None = None) -> list[Tool]:
    """Assemble the tool set Claude gets over MCP."""
    table = orchestrator or Orchestrator(settings)
    memory = open_memory(settings)
    transcript = open_transcript(settings)

    def ask(provider: str):
        def handler(args: dict[str, Any]) -> dict[str, Any]:
            reply = table.ask(
                provider=provider,
                prompt=args.get("prompt", ""),
                role=args.get("role"),
                context=args.get("context"),
                model=args.get("model"),
                use_cache=not bool(args.get("no_cache")),
            )
            return reply.public()

        return handler

    def panel(args: dict[str, Any]) -> dict[str, Any]:
        seats = args.get("seats")
        if not seats:
            # The default table: one builder and one sceptic. Two views that
            # disagree usefully beat two that agree by construction.
            seats = [
                {"provider": "gpt", "role": "engineer"},
                {"provider": "grok", "role": "critic"},
            ]
        replies = table.panel(
            prompt=args.get("prompt", ""),
            seats=seats,
            context=args.get("context"),
            use_cache=not bool(args.get("no_cache")),
        )
        answered = [r for r in replies if r.ok]
        return {
            "replies": [r.public() for r in replies],
            "answered": len(answered),
            "failed": len(replies) - len(answered),
        }

    def status(args: dict[str, Any]) -> dict[str, Any]:
        rows = provider_status(settings)
        if args.get("live"):
            from .providers.registry import probe

            rows = [probe(settings, row["provider"]) for row in rows]
        return {
            "specialists": rows,
            "roles": ROLE_ENUM,
            "config_file": str(settings.source) if settings.source else "built-in defaults",
        }

    def memory_search(args: dict[str, Any]) -> dict[str, Any]:
        if not settings.memory.get("enabled", True):
            return {"enabled": False, "hits": []}
        limit = int(args.get("limit") or settings.memory.get("max_entries_returned", 5))
        hits = memory.search(
            query=args.get("query", ""), tags=args.get("tags"), limit=limit
        )
        return {
            "enabled": True,
            "hits": [
                {
                    "key": entry.key,
                    "tags": entry.tags,
                    "text": entry.text,
                    "score": round(score, 2),
                }
                for entry, score in hits
            ],
        }

    def memory_write(args: dict[str, Any]) -> dict[str, Any]:
        if not settings.memory.get("enabled", True):
            return {"enabled": False, "stored": False}
        entry = memory.write(
            key=args.get("key", ""),
            text=args.get("text", ""),
            tags=args.get("tags"),
        )
        return {"stored": True, "key": entry.key, "tags": entry.tags}

    def show_transcript(args: dict[str, Any]) -> dict[str, Any]:
        call_id = args.get("call_id")
        if call_id:
            record = transcript.get(str(call_id))
            if record is None:
                return {"found": False, "call_id": call_id}
            return {"found": True, "call": record}
        return {"recent": transcript.recent(int(args.get("limit") or 10))}

    return [
        Tool(
            name="ask_gpt",
            description=(
                "Consult GPT as a specialist on your team. Worth doing when a "
                "second engineering opinion, a current-facts check, a costed "
                "comparison or a drafting pass would genuinely improve your "
                "answer. Skip it for things you already know, for trivia, and "
                "for anything where waiting on another model just slows the "
                "user down. " + _DELEGATION_NOTE
            ),
            input_schema=_ask_schema("GPT"),
            handler=ask("gpt"),
        ),
        Tool(
            name="ask_grok",
            description=(
                "Consult Grok as a specialist on your team. Strongest as a "
                "critic of a plan you already have, as a source of a genuinely "
                "different approach, or for current-events research. Skip it "
                "when you only want agreement — a second yes costs the user "
                "time and buys nothing. " + _DELEGATION_NOTE
            ),
            input_schema=_ask_schema("Grok"),
            handler=ask("grok"),
        ),
        Tool(
            name="ask_panel",
            description=(
                "Put one brief to several specialists at once and get all their "
                "replies together; they run in parallel, so two seats cost "
                "roughly the time of one. Use for decisions where disagreement "
                "is informative — architecture choices, go/no-go calls, "
                "anything you would want a second pair of eyes on. Then "
                "reconcile: say which view you took and why, rather than "
                "listing both. A seat that fails comes back marked failed and "
                "the rest still answer."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The shared brief, self-contained.",
                    },
                    "seats": {
                        "type": "array",
                        "description": (
                            "Who sits at this table. Defaults to GPT as engineer "
                            "and Grok as critic."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "provider": {"type": "string", "enum": ["gpt", "grok"]},
                                "role": {"type": "string", "enum": ROLE_ENUM},
                                "prompt": {
                                    "type": "string",
                                    "description": "Optional per-seat brief, overriding the shared one.",
                                },
                                "model": {"type": "string"},
                            },
                            "required": ["provider"],
                            "additionalProperties": False,
                        },
                    },
                    "context": {"type": "string", "description": "Shared background."},
                    "no_cache": {"type": "boolean"},
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
            handler=panel,
        ),
        Tool(
            name="roundtable_status",
            description=(
                "Which specialists are reachable right now, which backend and "
                "model each would use, and why any are unavailable. Check this "
                "when a call fails or when the user asks what the table can do. "
                "Pass live=true to actually ping each provider — that costs a "
                "few tokens on the metered API path, so use it for diagnosis, "
                "not routinely."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "live": {
                        "type": "boolean",
                        "description": "Send a one-word test call to each reachable specialist.",
                    }
                },
                "additionalProperties": False,
            },
            handler=status,
        ),
        Tool(
            name="memory_search",
            description=(
                "Search the shared project memory for standing facts about "
                "the user's projects — decisions already made, fixed specs, "
                "standing preferences. Search before assuming, and forward "
                "only the hits a given specialist actually needs; the whole "
                "profile does not belong in every brief."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What you are looking for."},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional project tags to restrict the search to.",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=memory_search,
        ),
        Tool(
            name="memory_write",
            description=(
                "Record a durable fact about a project so later sessions start "
                "informed. Store settled decisions, standing preferences and "
                "stable specs — not conversational chatter, and not anything "
                "the user would not want kept. Writing to an existing key "
                "replaces it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Short stable name, e.g. 'deploy-target'.",
                    },
                    "text": {"type": "string", "description": "The fact, in a sentence or two."},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Project tags, e.g. ['website', 'infra'].",
                    },
                },
                "required": ["key", "text"],
                "additionalProperties": False,
            },
            handler=memory_write,
        ),
        Tool(
            name="show_transcript",
            description=(
                "Retrieve what a specialist actually said, word for word, "
                "including the brief it was sent. Raw specialist output is kept "
                "out of your answers by default — use this only when the user "
                "asks to see it, or when you need to audit a call that went "
                "wrong. Omit call_id to list recent calls."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "call_id": {"type": "string", "description": "The call to fetch."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "additionalProperties": False,
            },
            handler=show_transcript,
        ),
    ]
