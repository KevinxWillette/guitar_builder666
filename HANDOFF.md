# KILLETTE GUITARS — Project Handoff

Repo: github.com/KevinxWillette/guitar_builder666
Working branch: `claude/guitar-component-automation-w2xwfs`  (everything lives here — always work on this branch, don't create new ones)

Give this file to any new Claude Code session (desktop or remote) as the first thing to read. It should also read `killette_parts/manifest.json` to see the live inventory and `guitar_mechanic/` to see the pipeline it's extending.

## What exists and works

1. **The parts pipeline** (`guitar_mechanic/`) — drop guitar photos in, get
   cut/scaled/cataloged parts out. Auto-splits multi-part images, removes
   attached debris, auto-rotates sideways parts, flags suspect cuts
   (`qc_flags` in the manifest). ML background removal (rembg) + two
   classical fallback engines (GrabCut, border flood-fill). Computes real
   anchor points for reassembly (see below). 13 passing tests
   (`python -m pytest tests/ -q`, ~6-10 min due to rembg model load).
   - Desktop: download repo ZIP → double-click `run_windows.bat` /
     `run_mac.command` → builder opens at localhost:8666. See START_HERE.md.
   - Batch: `python -m guitar_mechanic process` (add `--no-enhance` for
     clean renders; add `--category body` etc. to force a category and
     skip the whole-guitar anatomy detector, e.g. for photos of a *sheet*
     of parts that might false-trigger it — see Known Issues below).
   - For a big folder, don't run one giant `process` call — it OOMs. Use
     `run_chunked.sh` (processes 5 files per subprocess, self-healing).

2. **The fan-facing configurator** (`docs/index.html`) — static web app, no
   server needed: parts shelf, tap-to-place, swap-per-slot, drag,
   randomizer, PNG export. Preloaded from `docs/parts/` (mirror of
   `killette_parts/` — keep them in sync any time the manifest changes).

3. **The Guitarmory** (`docs/guitarmory.html` + `docs/armory-store.js`) —
   fans submit builds from the configurator, weekly voting, Build of the
   Week crowned next to the logo. Currently DEMO MODE (votes per-device via
   localStorage). To make voting global: owner creates a free Supabase
   project and fills `SUPABASE_URL` + anon key at the top of
   `docs/armory-store.js` (schema documented in that file).

4. **Brand assets** (`killette_rebrand/`) — official abalone KILLETTE logo
   (transparent PNG, the *only* logo image to use for inlay work — never
   generate a substitute) + rebranded renders.

## Live inventory (`killette_parts/manifest.json`, mirrored to `docs/parts/`)

214 components: **178 body, 26 pickup (incl. EMG-style humbuckers), 4
headstock, 3 bridge, 3 knob, 0 neck.**

**Zero necks is the current hard blocker** — everything downstream (anchor
math, scaling, the configurator's layering) is ready and waiting, but there
is nothing to snap a headstock+body together with. This is the single
highest-value thing the owner can supply next: real photos of guitar necks
(ideally already joined to a headstock or body, so the pipeline can anatomy-
split it and derive anchors from a real photo instead of guessing).

### Anchor system (for reassembling parts on the builder canvas)

Every part has real, geometrically-derived anchor points in
`manifest.json` (`anchors` field), not guessed defaults:
- **Body**: `{"pocket": [x, y]}` — where the neck's bottom should sit.
  Found by scanning the alpha mask top-down for where the shield
  silhouette's two "horns" merge into one contiguous run (stable for 15+
  rows) — that merge point is the real neck-pocket location.
- **Neck**: `{"top": [x, y], "bottom": [x, y]}`.
- **Headstock**: `{"bottom": [x, y]}` — last alpha row's horizontal center,
  where it joins the neck's top.

`docs/index.html`'s `anchor()` JS function still has bounding-box-center
fallback guesses for parts that lack real anchors — currently unused since
every live part has real ones, but leave it in as a safety net.

## Known issues / things to watch for

- **`guitar_mechanic/anatomy.py`'s whole-guitar detector has a false-positive
  mode**: it can misread a *non-guitar* photo (e.g. a multi-colorway grid/
  catalog page with a notch-like silhouette feature) as a full guitar and
  chop it into a fake headstock + broken body. Found and fixed once
  (`IMG_3982.JPEG`, commit `e17e771`) via `--category body` override to
  force the multi-island splitter instead. Not fixed at the algorithm
  level — if a newly-uploaded batch produces a headstock/body pair that
  looks wrong or oddly small, check whether the source photo was actually
  a single whole guitar before trusting the split.
- **Generated headstocks are banned.** Procedural/AI-generated headstock
  candidates were tried and explicitly rejected by the owner ("those look
  nothing like a guitar headstock"). Headstock inventory must come only
  from real photos/renders. Generated hardware (pickups/bridges/knobs) is
  fine and already in use.
- **6-string vs 8-string**: current hardware (pickups/bridges/knobs) is
  8-string; regenerating as 6-string is still an open task (see below).
  Styles should read as metal-guitar (BC Rich / ESP-LTD / Legator / Kiesel
  / Solar), explicitly NOT Fender/Strat-shaped.

## Publishing status

- NOT PUBLIC. `gh-pages` currently serves only a "coming soon" placeholder.
  Do not redeploy the real app without explicit owner go-ahead — it was
  published once and the owner immediately said "that's not finished, we
  can't just publish it."
- To publish when ready: repo Settings → Pages → Branch `gh-pages` → Save,
  then copy `docs/*` onto the `gh-pages` branch.
- Optional custom domain: CNAME record `build` → kevinxwillette.github.io on
  killykillette.com DNS, plus a CNAME file in the deployment.
- WordPress route: Premium plan includes plugin support, but the site is
  still on Simple hosting — needs a one-time free migration to Atomic
  hosting (site → Plugins → install anything → confirm transfer) before the
  configurator can be natively embedded. Owner couldn't find the migration
  button on a first attempt; unresolved.

## Next tasks (priority order, per owner)

1. **Get real neck photos** (see "zero necks" above — the actual blocker
   right now).
2. Regenerate pickups/bridges/knobs as 6-string versions.
3. Keep ingesting any new part photos the owner supplies (drag into chat,
   zip upload, or connected Google Drive) — run through the pipeline,
   visually QC via a contact sheet before merging into the live manifest,
   watch for the anatomy false-positive mode above.
4. Wire Supabase for global Guitarmory voting (needs owner's free account
   + the two keys in `docs/armory-store.js`).
5. Publish (owner's explicit go only) and/or complete the WordPress Atomic
   hosting migration for native embedding.

## Other accounts wired to this project

- WordPress.com: killykillette.com (Premium, Simple hosting; two other
  draft sites). The "Killette List" page links to a searchable resource
  list currently hosted on catbox.moe, which is blocked for many visitors
  — replacement plan is to host the list alongside the configurator and
  repoint the page buttons.
- Google Drive is connected to Claude sessions on this project — check it
  for newly uploaded part photos before asking the owner to re-send.
- The original uploads for every processed part are archived in `photos/`.
