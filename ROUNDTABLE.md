# Killy AI Roundtable

Killy talks to Claude. Claude decides whether GPT or Grok would improve the
answer, calls them, checks their work, resolves whatever they disagree about,
and replies once, in its own voice. No copying prompts between three tabs.

```
 Killy
   │
   ▼
 Claude ───────────── lead, representative, orchestrator
   │  (decides whether to delegate at all)
   │
   ├── ask_gpt(role, brief)  ──► GPT specialist ──┐
   ├── ask_grok(role, brief) ──► Grok specialist ─┤  run in parallel
   └── ask_panel(brief)      ──► both at once ────┘
   │
   ▼
 Claude evaluates each reply, checks claims, reconciles conflicts
   │
   ▼
 One answer to Killy       (raw chatter stays hidden — `show_transcript` on request)
```

---

## 1. The account question, answered first

The handoff asked what can legitimately be reused from Killy's existing
subscriptions before committing to an implementation. The answer, verified
August 2026:

| Subscription | Includes API access? | What it *does* give us |
|---|---|---|
| **ChatGPT Plus** | **No.** Separate billing entirely; the same email does not join them. | **Codex CLI**, included at no extra cost on every ChatGPT plan, with a documented non-interactive mode (`codex exec`). |
| **SuperGrok / +Build** | **No.** Consumer Grok and the developer platform are separate billing tracks; `console.x.ai` is its own product with its own payment method. | **Grok Build CLI** (`grok`), xAI's official coding CLI, unlocked by SuperGrok / X Premium+ / SuperGrok Heavy, with a documented headless mode (`grok -p`). |
| **Claude Max** | n/a — Claude is the orchestrator, not a called specialist. | Claude Code, which is where the roundtable runs. No Anthropic API key needed. |

So the honest answer to "can we reuse the subscriptions?" is **yes, but not the
way the handoff assumed.** The chat *APIs* are not included — but both vendors
ship an official CLI that is, and both were built to be scripted. Those CLIs are
supported entry points, not browser automation, so using them breaks none of the
handoff's rules about scraping.

**The roundtable therefore has two backends per specialist**, and picks
automatically:

- **`cli`** — drives `codex exec` / `grok -p`. Costs nothing beyond the
  subscriptions Killy already pays for. This is the default.
- **`api`** — plain HTTPS to `api.openai.com` / `api.x.ai`. Needs separate paid
  accounts. Used only when a CLI is missing, or when Killy wants a specific
  model.

`auto` prefers the CLI, falls back to the API, and reports the specialist as
unavailable if neither is there. Nothing silently starts spending money.

## 2. What it costs

**On the CLI path: nothing.** Killy already pays for ChatGPT Plus and SuperGrok;
roundtable calls draw on those.

One caveat worth knowing: headless CLI runs draw from the **same usage window as
interactive chat**. A heavy roundtable session can eat into the ChatGPT or Grok
allowance Killy wanted for his own afternoon. That is a real cost, just not a
billed one.

If Killy ever adds API keys, per-call cost at published August 2026 rates, for a
typical brief (~2k tokens in, ~1k out):

| Specialist | Model | Rate (in / out per 1M) | Per call | Per panel |
|---|---|---|---|---|
| GPT | `gpt-5.5` | $5.00 / $30.00 | ~$0.04 | — |
| Grok | `grok-4.6` | $2.00 / $6.00 | ~$0.01 | — |
| Both | — | — | — | **~$0.05** |
| GPT (budget) | `gpt-5.4-nano` | $0.20 / $1.25 | ~$0.002 | — |
| Grok (budget) | `grok-4.3` | $1.25 / $2.50 | ~$0.005 | — |

Twenty panels a day is roughly **$30/month** on the API path and **$0** on the
CLI path. Rates move; treat the table as an order of magnitude, not a quote.

Three things keep the bill down on either path: Claude only delegates when it
helps, identical briefs inside 15 minutes reuse the cached answer, and briefs
are capped (12k characters of prompt, 24k of context) so a runaway paste cannot
become a runaway bill.

## 3. What was built

**Python, standard library only** — built and tested on 3.11, written to run on
3.9 and newer. No `pip install`, no virtualenv, no
lockfile — it runs on the same stock Python that already drives the guitar
mechanic. That matters more than framework niceties here: the setup Killy has to
perform is "install two CLIs, run one command", and every dependency is one more
thing that can break on his machine six months from now. MCP's stdio transport
is newline-delimited JSON-RPC, which is small enough to implement directly, so
it is implemented directly (`roundtable/mcp_stdio.py`).

```
roundtable/
├── __init__.py
├── __main__.py            serve / doctor / ask / panel / roles / memory / selftest
├── config.py              JSON config, env expansion, backend resolution
├── roles.py               the seven specialist seats and their prompts
├── orchestrator.py        dispatch, parallel panels, timeouts, cache, failure isolation
├── memory.py              shared project memory (searched, never broadcast)
├── transcript.py          raw specialist chatter, hidden by default
├── mcp_stdio.py           JSON-RPC 2.0 MCP server over stdio
├── tools.py               the seven tools Claude sees, and their schemas
└── providers/
    ├── base.py            the one interface every backend implements
    ├── cli_backend.py     drives codex exec / grok -p as subprocesses
    ├── api_backend.py     OpenAI-compatible HTTP, covers both vendors
    └── registry.py        config → live backend, plus availability reporting

roundtable_server.py           launcher — the one absolute path Claude runs
roundtable.config.example.json copy to roundtable.config.json to change anything
prompts/claude_orchestrator.md Claude's instructions as lead of the table
tests/test_roundtable.py       57 tests, no network, no keys
```

## 4. The tools Claude gets

| Tool | Arguments | What it does |
|---|---|---|
| `ask_gpt` | `prompt`, `role`, `context`, `model`, `no_cache` | One brief to GPT in a named seat. |
| `ask_grok` | same | One brief to Grok in a named seat. |
| `ask_panel` | `prompt`, `seats[]`, `context`, `no_cache` | Same brief to several specialists **in parallel**; two seats cost about the time of one. Defaults to GPT-as-engineer plus Grok-as-critic. |
| `roundtable_status` | `live` | Who is reachable, via which backend and model, and why anyone is missing. `live: true` actually pings them. |
| `memory_search` | `query`, `tags`, `limit` | Look up standing facts about Killy's projects. |
| `memory_write` | `key`, `text`, `tags` | Record a settled decision or spec. |
| `show_transcript` | `call_id`, `limit` | What a specialist said verbatim, including the brief it was sent. |

Every call returns `ok`, and a failed specialist returns `ok: false` with a
reason rather than raising — so one dead provider degrades an answer instead of
losing the turn.

**A note on the tool count.** The handoff sketched eight tools
(`ask_gpt_engineer`, `ask_grok_critic`, and so on). This ships two, with the
role as an argument. Same capability, but the role list stays in one place, new
seats need no new tools, and Claude reads a shorter tool list before every
single message — which is a real cost, paid on every turn. `roles.py` is the one
file to edit to add a seat.

## 5. The seats

| Role | For |
|---|---|
| `engineer` | Code, implementations, debugging. Grounded in the actual repo. |
| `researcher` | Current facts, docs, prior art. Separates verified from remembered. |
| `analyst` | Options, costs, trade-offs — ends on one recommendation, not a menu. |
| `creative` | Names, copy, lyrics, visual and brand directions. |
| `critic` | Attacks a plan to find where it breaks. |
| `builder` | Turns a decision into exact commands and steps. |
| `alternative` | A genuinely different route to the same goal. |

Every seat answers in the same shape — **ANSWER / CONFIDENCE / ASSUMPTIONS /
WATCH OUT** — and every seat is told it is briefing Claude, not Killy. That is
deliberate: specialists who state their confidence and assumptions give Claude
something real to weigh when two of them disagree, and specialists writing for a
colleague who will check their work hedge less and admit unknowns more.

Read any prompt in full:

```bash
python3 -m roundtable roles                              # the list
python3 -m roundtable roles --full --role critic         # one prompt, verbatim
```

## 6. Setting it up

Nothing here needs a developer. Each step says how to tell it worked.

**Step 1 — Install the two specialist CLIs.**

These are the vendors' own tools, signed into with the subscriptions Killy
already has. Install each one and log in when it opens a browser:

- **Codex (GPT)** — installed with `npm install -g @openai/codex`, then run
  `codex` once and choose **Sign in with ChatGPT**.
- **Grok Build (Grok)** — install per xAI's current instructions at
  `docs.x.ai/build`, then run `grok` once and sign in with the SuperGrok
  account. Credentials land in `~/.grok/auth.json` and refresh themselves.

Take the exact install command from each vendor's page rather than from here —
those change. Step 3 tells you whether it worked, whatever the command was.

**Step 2 — (Optional) API keys, only if a CLI won't work.**

Skip this unless step 3 says a specialist is unreachable and you cannot install
its CLI. Keys come from `platform.openai.com` and `console.x.ai`, are billed
separately from the subscriptions, and are set as environment variables —
`OPENAI_API_KEY` and `XAI_API_KEY` — never written into a file in this repo.

**Step 3 — Check the table.**

```bash
cd /path/to/guitar_builder666
python3 -m roundtable doctor
```

It prints each specialist, the backend and model it would use, what it costs,
and — if it cannot be reached — exactly why. Add `--live` to actually ping each
one and prove the login works.

**Step 4 — Connect it to Claude.**

In Claude Code, one command, with the **full** path:

```bash
claude mcp add killy-roundtable -- python3 /full/path/to/guitar_builder666/roundtable_server.py
```

For Claude Desktop, add this to `claude_desktop_config.json` instead:

```json
{
  "mcpServers": {
    "killy-roundtable": {
      "command": "python3",
      "args": ["/full/path/to/guitar_builder666/roundtable_server.py"]
    }
  }
}
```

Restart Claude. Ask it *"what does roundtable_status say?"* — it should name GPT
and Grok and how it would reach them.

**Step 5 — Tell Claude how to lead.**

Paste `prompts/claude_orchestrator.md` into the project's custom instructions.
Without it the tools still work, but Claude will use them like a search engine
rather than running a team — delegating too often, and relaying replies instead
of judging them.

## 7. Using it

Killy just talks to Claude. Claude decides. Some things worth knowing:

- **To see the raw replies**, ask: *"what did Grok actually say?"* Claude fetches
  the verbatim transcript. Otherwise the chatter stays out of the way.
- **To force a second opinion**, ask for one: *"have Grok tear this apart."*
- **When a specialist is down**, Claude answers anyway and says so in a line.

By hand, without Claude, for testing:

```bash
python3 -m roundtable ask grok "Is this bridge spacing right for a 6-string?" --role critic
python3 -m roundtable panel "Should the Guitarmory vote store be Supabase or a static JSON file?"
python3 -m roundtable selftest      # proves the plumbing works, offline
```

## 8. Shared memory, now and later

Working today: a searchable store of standing facts, one JSON line each, in
`.roundtable/memory.jsonl` (git-ignored).

```bash
python3 -m roundtable memory add headstock-policy \
  "Generated headstocks were rejected by the owner; headstocks must come from real photos." \
  --tag guitars
python3 -m roundtable memory search "can we generate headstocks"
```

The design constraint is the one the handoff called for: memory is **searched,
never broadcast.** Claude looks things up and forwards only the hits a given
question needs. Shipping Killy's whole profile to two vendors on every call
would be expensive, would leak far more than any single question needs, and
would bury the actual brief.

The upgrade path, when the store outgrows keyword search: `Memory.search()` is
the only method that would change. Swap keyword scoring for embeddings behind
the same signature and nothing above it moves — not the tools, not the schemas,
not Claude's instructions. That is why `memory.py` has no other callers.

## 9. Testing

```bash
pip install pytest
python3 -m pytest tests/test_roundtable.py -v     # 57 tests, ~1 second
```

No network, no API keys, no accounts. Specialists are replaced by fakes, and
where the subprocess path itself is under test, by throwaway shell scripts. What
is actually verified: the MCP wire format (handshake, version negotiation,
notifications, error codes, newline framing), that a dead specialist cannot sink
a panel, that panels really do run in parallel, that timeouts and crashes are
contained, that the cache and its bypass work, that memory stays scoped, and
that oversized briefs get trimmed visibly rather than silently.

`python3 -m roundtable selftest` runs an end-to-end check with no pytest at all.

## 10. Limits worth knowing

- **The CLI flags are the most likely thing to break.** They reflect the
  documented headless modes as of August 2026, but vendor docs were unreachable
  from the machine this was built on, so treat them as well-researched defaults
  rather than verified ones. `doctor --live` is the real test, and any flag that
  drifts is a config edit, not a code change — which is exactly why the argv
  lives in JSON.
- **Model IDs drift.** `gpt-5.5` and `grok-4.6` were current in August 2026.
  They are config, and only used on the API path.
- **Grok Build is an agentic coding CLI.** The roundtable runs specialists with
  this repo as their working directory so they can read the code they are asked
  about. Codex is pinned to `--sandbox read-only`; the equivalent flag for
  `grok` could not be verified here, so if you want it locked down, add its
  sandbox flag to `command` in the config. Git is the backstop either way —
  anything a specialist changed shows up in `git status`.
- **Calls are synchronous**, with a per-provider timeout (default 180s). No
  streaming: Claude waits for the whole reply.
- **`shared_project_files` from the handoff was deliberately not built.** Claude
  Code already reads this repo directly, and CLI specialists run inside it, so a
  file-shipping tool would have duplicated both. If specialists ever need files
  Claude cannot reach, that is the moment to add it — not before.

## Sources

- [Does ChatGPT Plus Include API Access? No, It's Separate](https://folding-sky.com/blog/why-use-api-keys-not-chatgpt)
- [ChatGPT Subscription vs OpenAI API: Separate Bills & Credits](https://www.toolcolumn.com/learn/chatgpt-subscription-vs-openai-api-pricing)
- [Codex CLI — non-interactive mode](https://developers.openai.com/codex/noninteractive)
- [Codex exec in CI: headless guide](https://www.developersdigest.tech/blog/codex-exec-ci-headless-guide)
- [Grok Build — xAI Docs](https://docs.x.ai/build/overview)
- [Grok Build — headless & scripting](https://docs.x.ai/build/cli/headless-scripting)
- [Grok Pricing 2026: SuperGrok, X Premium+ & API Costs](https://diyai.io/ai-tools/text-generation/grok-pricing/)
- [xAI Grok API pricing (August 2026)](https://benchlm.ai/xai/api-pricing)
- [OpenAI API pricing (August 2026)](https://benchlm.ai/openai/api-pricing)
