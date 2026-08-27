# Forever Zoom

Backup of the Forever Zoom canvas project (uploaded 2026-08-27). Three tiers,
matching the notes that came with the files:

## `FOREVER ZOOM/` — the current, canonical board

The folder your `READ_ME` note says to use ("USE Desktop\FOREVER ZOOM instead").
A single self-contained video canvas:

- `index.html` — the whole app (canvas, clip list, pan/zoom, drag, project
  export/import). No dependencies.
- `OPEN FOREVER ZOOM.bat` — starts `python -m http.server 8765` and opens
  Edge at `http://127.0.0.1:8765/index.html`.
- `HOW_TO_USE_AND_SHARE.txt` — usage and zip-to-share instructions.
- `media/` — optional backup folder for clips you want to include in a shared zip.

To restore on a Windows desktop: copy this folder to the Desktop and
double-click `OPEN FOREVER ZOOM.bat` (needs Python installed).

## `hub_version/` — two-board hub variant

An alternate build with a landing hub linking two boards:

- `index.html` — hub page ("Two boards. One folder.")
- `KILLY_ZOOMQUILT.html` — the deep-zoom infinite canvas with Draw mode (E),
  photo/video layers, editor panel.
- `video-board.html` — the flat video board (same app as the canonical
  `FOREVER ZOOM/index.html`).
- `SERVE.py` + `OPEN FOREVER ZOOM.bat` — custom server on port 17891 that
  opens the infinite canvas directly.

## `legacy/` — old leftovers

Desktop launcher shims and notes from earlier layouts (`INFINITE/`,
`UNIVERSE/`, `KILLY_UNIVERSE_CANVASES/` — those folders themselves were not
uploaded). Kept for reference only; `_populate_log.json` records the last
layer-populate run (520 layers, 2026-07-11).
