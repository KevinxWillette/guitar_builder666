# Killy AI Roundtable

Killy talks to Claude. Claude decides whether GPT or Grok would improve the
answer, calls them, checks their work, resolves whatever they disagree about,
and replies once, in its own voice. No copying prompts between three tabs.

Two hard requirements shape everything below: it has to be **free**, and it has
to **actually work**. Everything that served neither was left out.

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

## 1. Why this is free, and how that is guaranteed

The handoff asked what could legitimately be reused from the existing
subscriptions. Verified August 2026:

| Subscription | Includes API access? | What it *does* give us |
|---|---|---|
| **ChatGPT Plus** | **No.** Separate billing entirely; the same email does not join them. | **Codex CLI**, included at no extra cost on every ChatGPT plan, with a documented non-interactive mode (`codex exec`). |
| **SuperGrok / +Build** | **No.** Consumer Grok and the developer platform are separate billing tracks; `console.x.ai` is its own product with its own payment method. | **Grok Build CLI** (`grok`), xAI's official coding CLI, unlocked by SuperGrok / X Premium+ / SuperGrok Heavy, with a documented headless mode (`grok -p`). |
| **Claude Max** | n/a — Claude is the orchestrator, not a called specialist. | Claude Code, which is where the roundtable runs. No Anthropic API key needed. |

The chat *APIs* cost money. But both vendors ship an official CLI that the
subscriptions **already cover**, and both were built to be scripted. Those are
supported entry points, not browser automation, so the free route breaks none of
the handoff's rules about scraping.

**So the free route is the only route the table takes by default.** The config
carries a lock:

```json
{ "free_only": true }
```

While that is on, the paid API backend **cannot be selected** — not by config,
not by a stray `OPENAI_API_KEY` left in the environment, not by accident. Ask a
specialist that has no CLI installed and you get "unavailable", never a bill.
`doctor` states the position in one line every time you run it:

```
money:  LOCKED — free_only is on, so no paid API can be called.
```

There is a paid path in the code, off behind that lock, for one reason: if a
vendor ever breaks or withdraws its free CLI, Killy can flip one flag and keep
working instead of waiting for a rewrite. Turning it on is a deliberate act and
it costs money; leaving it alone costs nothing.

The one real cost of the free route, worth knowing up front: headless CLI runs
draw on the **same usage window as interactive chat**. A heavy roundtable
session can eat into the ChatGPT or Grok allowance Killy wanted for his own
afternoon. That is a real limit, just not a billed one.

<details>
<summary>If you ever unlock spending — what it would cost</summary>

Per call at published August 2026 rates, for a typical brief (~2k tokens in, 1k
out). Rates move; treat this as an order of magnitude.

| Specialist | Model | Rate (in / out per 1M) | Per call |
|---|---|---|---|
| GPT | `gpt-5.5` | $5.00 / $30.00 | ~$0.04 |
| Grok | `grok-4.6` | $2.00 / $6.00 | ~$0.01 |
| GPT (budget) | `gpt-5.4-nano` | $0.20 / $1.25 | ~$0.002 |
| Grok (budget) | `grok-4.3` | $1.25 / $2.50 | ~$0.005 |

Twenty panels a day would be roughly $30/month. On the free route it is $0.
</details>

## 2. What was built

**Python, standard library only** — built and tested on 3.11, written to run on
3.9 and newer. No `pip install`, no virtualenv, no lockfile. That is a
feasibility decision, not a stylistic one: setup is "install two CLIs, run one
command", and every dependency is one more thing that can break on Killy's
machine six months from now. MCP's stdio transport is newline-delimited
JSON-RPC, small enough to implement directly, so it is
(`roundtable/mcp_stdio.py`).

```
roundtable/
├── __main__.py            serve / doctor / ask / panel / roles / memory / selftest
├── config.py              JSON config, the free_only lock, backend resolution
├── calibrate.py           finds the CLI invocation that works on this machine
├── desktop.py             writes the Claude Desktop config, safely
├── roles.py               the seven specialist seats and their prompts
├── orchestrator.py        dispatch, parallel panels, timeouts, cache, failure isolation
├── memory.py              shared project memory (searched, never broadcast)
├── transcript.py          raw specialist chatter, hidden by default
├── mcp_stdio.py           JSON-RPC 2.0 MCP server over stdio
├── tools.py               the seven tools Claude sees, and their schemas
└── providers/
    ├── base.py            the one interface every backend implements
    ├── cli_backend.py     drives codex exec / grok -p as subprocesses  ← the free path
    ├── api_backend.py     OpenAI-compatible HTTP, both vendors        ← locked off
    └── registry.py        config → live backend, plus availability reporting

setup_roundtable_mac.command   double-click setup (Mac)
setup_roundtable_windows.bat   double-click setup (Windows)
roundtable_server.py           launcher — the one absolute path Claude runs
roundtable.config.example.json copy to roundtable.config.json to change anything
prompts/claude_orchestrator.md Claude's instructions as lead of the table
tests/test_roundtable.py       74 tests, no network, no keys
```

## 3. The tools Claude gets

| Tool | Arguments | What it does |
|---|---|---|
| `ask_gpt` | `prompt`, `role`, `context`, `model`, `no_cache` | One brief to GPT in a named seat. |
| `ask_grok` | same | One brief to Grok in a named seat. |
| `ask_panel` | `prompt`, `seats[]`, `context`, `no_cache` | Same brief to several specialists **in parallel**; two seats cost about the time of one. Defaults to GPT-as-engineer plus Grok-as-critic. |
| `roundtable_status` | `live` | Who is reachable, via which backend, and why anyone is missing. `live: true` actually pings them. |
| `memory_search` | `query`, `tags`, `limit` | Look up standing facts about Killy's projects. |
| `memory_write` | `key`, `text`, `tags` | Record a settled decision or spec. |
| `show_transcript` | `call_id`, `limit` | What a specialist said verbatim, including the brief it was sent. |

A failed specialist returns `ok: false` with a reason rather than raising — so
one dead provider degrades an answer instead of losing the turn.

**On the tool count.** The handoff sketched eight tools (`ask_gpt_engineer`,
`ask_grok_critic`, and so on). This ships two, with the role as an argument.
Same capability, but the role list stays in one place, new seats need no new
tools, and Claude reads a shorter tool list before every single message — a real
cost, paid every turn.

## 4. The seats

| Role | For |
|---|---|
| `engineer` | Code, implementations, debugging. Grounded in the actual repo. |
| `researcher` | Current facts, docs, prior art. Separates verified from remembered. |
| `analyst` | Options, costs, trade-offs — ends on one recommendation, not a menu. |
| `creative` | Names, copy, drafts, directions. |
| `critic` | Attacks a plan to find where it breaks. |
| `builder` | Turns a decision into exact commands and steps. |
| `alternative` | A genuinely different route to the same goal. |

Every seat answers in the same shape — **ANSWER / CONFIDENCE / ASSUMPTIONS /
WATCH OUT** — and every seat is told it is briefing Claude, not Killy. That is
deliberate: specialists who state their confidence and assumptions give Claude
something real to weigh when two of them disagree, and specialists writing for a
colleague who will check their work hedge less and admit unknowns more.

```bash
python3 -m roundtable roles                        # the list
python3 -m roundtable roles --full --role critic   # one prompt, verbatim
```

## 5. Setting it up

Two logins and one double-click. Nothing here asks for a card.

### Windows + Claude Desktop (the setup this was built for)

**Step 1 — Install Node.js**, if you do not have it: <https://nodejs.org>. The
next step needs `npm`, which comes with it.

**Step 2 — Install the two CLIs and sign in.** In a terminal (press Start, type
`cmd`, Enter):

```
npm install -g @openai/codex
codex
```

`codex` opens a browser — choose **Sign in with ChatGPT**. Then install Grok
Build per <https://docs.x.ai/build>, run `grok` once, and sign in with your
SuperGrok account. Both remember you afterwards.

**Step 3 — Double-click `setup_roundtable_windows.bat`.**

It checks both CLIs, works out which command each one actually accepts on your
machine, saves that, and then **writes the Claude Desktop config itself** —
backing up whatever was there and leaving any other MCP servers you have
untouched. No JSON to hand-edit.

**Step 4 — Quit Claude Desktop completely and reopen it.** Closing the window is
not enough; quit it from the system tray, or MCP servers will not reload.

**Step 5 — Paste `prompts/claude_orchestrator.md`** into your Claude project's
custom instructions. Without it the tools work, but Claude uses them like a
search engine instead of running a team.

Then ask Claude: *"what does roundtable_status say?"* It should name GPT and
Grok and how it reaches them.

### Mac

Identical, except double-click `setup_roundtable_mac.command` at step 3.

### Claude Code (terminal) instead of Desktop

Setup detects it and prints a `claude mcp add ...` line to run, with the right
interpreter and path already filled in.

### Notes that save time

- **It has to run on your own computer.** The roundtable drives CLIs that are
  logged in there, so it needs Claude Desktop or the Claude Code CLI. Claude in
  a web browser cannot reach a local MCP server.
- **Windows rarely has a `python3` command** — only `python` or `py`. Nothing
  here depends on that: the launcher finds whichever you have, and the Desktop
  config records the interpreter's full path rather than trusting PATH.
- **Setup is safe to re-run.** It is idempotent, it backs up before writing, and
  it never touches your other MCP servers.

### If a specialist will not answer

```
python -m roundtable calibrate       # re-probe the CLI flags and re-save
python -m roundtable doctor --live   # call each one, print the real error
```

Nine times out of ten a CLI is installed but not logged in. Run it by hand once,
sign in, re-run setup.

## 6. Using it

Killy just talks to Claude. Claude decides. Worth knowing:

- **To see the raw replies**, ask: *"what did Grok actually say?"* Claude fetches
  the verbatim transcript. Otherwise the chatter stays out of the way.
- **To force a second opinion**, ask for one: *"have Grok tear this apart."*
- **When a specialist is down**, Claude answers anyway and says so in a line.

By hand, without Claude, for testing:

```bash
python3 -m roundtable ask grok "Is this plan sound?" --role critic
python3 -m roundtable panel "Should this store state in a file or a database?"
python3 -m roundtable selftest      # proves the plumbing works, offline
```

## 7. Shared memory

Working today: a searchable store of standing facts, one JSON line each, in
`.roundtable/memory.jsonl` (git-ignored, local, never uploaded anywhere).

```bash
python3 -m roundtable memory add deploy-target \
  "The public site is served from the docs/ folder on GitHub Pages." --tag infra
python3 -m roundtable memory search "where does the site deploy from"
```

Memory is **searched, never broadcast**: Claude looks things up and forwards only
the hits a question needs. Shipping a whole profile to two vendors on every call
would be expensive, would leak far more than any single question needs, and
would bury the actual brief.

The upgrade path, when keyword search stops being enough: `Memory.search()` is
the only method that would change. Swap keyword scoring for embeddings behind
the same signature and nothing above it moves — not the tools, not the schemas,
not Claude's instructions.

## 8. Testing

```bash
pip install pytest
python3 -m pytest tests/test_roundtable.py -v     # 74 tests, ~1 second
```

No network, no API keys, no accounts. Specialists are replaced by fakes, and
where the subprocess path itself is under test, by throwaway shell scripts.
Verified: the MCP wire format (handshake, version negotiation, notifications,
error codes, newline framing), **that the money lock holds even with an API key
sitting in the environment**, that a dead specialist cannot sink a panel, that
panels really run in parallel, that timeouts and crashes are contained, that the
cache and its bypass work, that memory stays scoped, and that oversized briefs
are trimmed visibly rather than silently.

`python3 -m roundtable selftest` gives the same end-to-end assurance without
pytest.

## 9. Limits worth knowing

- **The CLI flags were researched, not verified against live vendor docs** —
  those were unreachable from the machine this was built on. This is why
  `calibrate` exists: it tries the plausible invocations on your machine and
  keeps what works, so drift is handled automatically rather than by hand. If
  every candidate fails, the argv is still plain JSON you can edit.
- **Grok Build is an agentic coding CLI.** Specialists run with this repo as
  their working directory so they can read code they are asked about. Codex is
  pinned to `--sandbox read-only`; the equivalent flag for `grok` could not be
  verified here, so add its sandbox flag to `command` in the config if you want
  it locked down. Git is the backstop either way — anything a specialist changed
  shows up in `git status`.
- **Calls are synchronous**, with a per-provider timeout (default 180s). No
  streaming: Claude waits for the whole reply.
- **`shared_project_files` from the handoff was deliberately not built.** Claude
  Code already reads this repo directly, and CLI specialists run inside it, so a
  file-shipping tool would have duplicated both.

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
