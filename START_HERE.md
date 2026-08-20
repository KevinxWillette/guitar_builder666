# Killette Guitar Builder — Start Here

## Run it on your desktop (the full mechanic: upload photos, auto-cut parts)

1. Install Python from https://python.org (check "Add to PATH" on Windows)
2. Download this repo: green **Code** button → **Download ZIP** → unzip
3. Double-click **run_windows.bat** (Windows) or **run_mac.command** (Mac)
4. Your browser opens the builder at http://localhost:8666 —
   drag guitar photos in and the mechanic cuts them into parts

Optional, for the best background removal: `pip install rembg`

## Put the fan-facing builder on your website (free hosting)

The `docs/` folder is a complete public builder preloaded with all 43
Killette parts — no server needed. To host it free on GitHub Pages:

1. On github.com open this repo → **Settings** → **Pages**
2. Under "Build and deployment": Source = **Deploy from a branch**,
   Branch = `claude/guitar-component-automation-w2xwfs`, folder = `/docs` → **Save**
3. In ~2 minutes your builder is live at:
   `https://kevinxwillette.github.io/guitar_builder666/`
4. Link that URL from killykillette.com (a "BUILD YOUR KILLETTE" button) —
   ask your website assistant to add it.

## Keep private pictures out of the public repo

This repo is public, and `docs/` is served on the open web. Before you
add photos, turn the vault on — once per clone:

```bash
python -m guitar_mechanic vault init
```

That creates `vault/` (never committed) and installs a commit guard that
refuses to let a private picture into a commit, even a resized copy of
one. `python -m guitar_mechanic vault doctor` tells you every layer is up.
Full details in VAULT.md.
