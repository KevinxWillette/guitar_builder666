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
