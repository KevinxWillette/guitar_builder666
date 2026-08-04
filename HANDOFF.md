# KILLETTE GUITARS — Project Handoff

Repo: github.com/KevinxWillette/guitar_builder666
Working branch: `claude/guitar-component-automation-w2xwfs`  (everything lives here)

## What exists and works

1. **The parts pipeline** (`guitar_mechanic/`) — drop guitar photos in, get
   cut/scaled/cataloged parts out. Auto-splits multi-part images, removes
   attached debris, auto-rotates sideways parts, flags suspect cuts
   (`qc_flags` in the manifest). ML background removal (rembg) + two
   classical fallback engines. 11 passing tests.
   - Desktop: download repo ZIP → double-click `run_windows.bat` /
     `run_mac.command` → builder opens at localhost:8666. See START_HERE.md.
   - Batch: `python -m guitar_mechanic process` (add `--no-enhance` for
     clean renders).

2. **The fan-facing configurator** (`docs/`) — static web app, no server
   needed: parts shelf, tap-to-place, swap-per-slot, drag, randomizer,
   PNG export. Preloaded from `docs/parts/`.

3. **The Guitarmory** (`docs/guitarmory.html`) — fans submit builds from
   the configurator, weekly voting, Build of the Week crowned next to the
   logo. Currently DEMO MODE (votes per-device). To make voting global:
   create a free Supabase project and fill SUPABASE_URL + anon key at the
   top of `docs/armory-store.js` (schema is documented in that file).

4. **Brand assets** (`killette_rebrand/`) — official abalone KILLETTE logo
   (transparent PNG) + all rebranded renders (de-branded pickups sheet,
   relettered headstock, Plite guitars re-scripted).

## Inventory (owner-approved, in `killette_parts/` + mirrored to `docs/parts/`)

- 12 empty shield-body colorways (routed + solid)
- 4 headstocks: black abalone/chrome, black abalone/gold, black chrome, white V
- 10 generated hardware parts (pickups gold/chrome/black/green, bridges
  chrome/gold/black, knobs black/chrome/gold) — NOTE: currently 8-string;
  6-string versions are the next task.
- 6 NEW generated 6-string metal headstock candidates (spear/fang/hatchet
  shapes × gloss-black/blood-red/bone-white) in `generated_candidates/` —
  AWAITING OWNER QC, not yet in inventory.

## Publishing status

- NOT PUBLIC. The `gh-pages` branch currently serves only a "coming soon"
  placeholder (if GitHub Pages is even enabled — unverified).
- To publish when ready: repo Settings → Pages → Branch `gh-pages` → Save,
  then redeploy the real app to gh-pages (one command; any Claude session
  with this repo can do it: copy `docs/*` onto the gh-pages branch).
- Optional custom domain: add CNAME record `build` → kevinxwillette.github.io
  on killykillette.com DNS, plus a CNAME file in the deployment.
- WordPress route: the Premium plan now lists plugin support; the site is
  still on Simple hosting. Activating hosting features (wordpress.com →
  site → Plugins → install anything → confirm transfer) unlocks native
  embedding of the configurator on killykillette.com. Attempted once,
  owner couldn't find the button — retry or contact WP support.

## Next tasks (in priority order, per owner)

1. 6-string components only, metal styles only (BC Rich / ESP / Legator /
   Kiesel / Solar vibes; NO Fender/Strat shapes). Headstocks first —
   candidates ready for QC in `generated_candidates/`.
2. Regenerate pickups/bridges as 6-string (currently 8-string).
3. Owner's 100+ parts folder: zip → attach in chat, or GitHub web upload
   to the working branch → run through pipeline → QC sheet → approve.
4. Wire Supabase for global Guitarmory voting (needs owner's free account).
5. Publish (owner's explicit go only).

## Other accounts wired to this project

- WordPress.com: killykillette.com (Premium, Simple hosting; two other
  draft sites). Killette List page links to a searchable list hosted on
  catbox.moe (blocked for many visitors — replacement plan: host the list
  where the configurator lives, then repoint the page buttons).
- The original uploads for every processed part are archived in `photos/`
  and mirrored in session work folders.
