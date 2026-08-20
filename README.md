# Guitar Builder 666 🎸🔧

Upload guitar pictures — **the mechanic works on them.** The app understands
guitar anatomy, discerns the parts, cuts them out with precision, lays each
part where it belongs on the bench, and lets you check and switch components
until the guitar is yours. Then export the image.

## Quick start

```bash
pip install -r requirements.txt
python -m guitar_mechanic app
# open http://localhost:8666/
```

Drag photos onto the page (or use the upload button):

- **Whole-guitar photos** are anatomically split: the mechanic finds the
  instrument's axis, reads the silhouette's width profile (headstock flare →
  narrow neck → wide body), and cuts headstock / neck / body apart with
  anchor points so they snap back together on the bench.
- **Individual parts** (pickups, bridges, knobs, pickguards …) are
  recognised from the filename — e.g. `gold-humbucker.jpg`,
  `tele_bridge.png` — cut from their background, and scaled to real-world
  size so everything stays in proportion.

On the bench: click a shelf part to place it, drag to fine-tune, click a
placed part and use **◀ swap ▶** (or `[` / `]`) to cycle alternatives in
that slot, `Delete` to remove, **Export my guitar** to download the PNG.

## The pipeline

Every upload goes through four automated stages (`guitar_mechanic/`):

| stage | module | what it does |
|---|---|---|
| enhance | `enhancer.py` | EXIF orientation, white balance, contrast, sharpen |
| slice | `slicer.py` | border-sampling flood fill cuts the subject from its backdrop (uses `rembg` automatically if installed, for busy backgrounds) |
| discern + scale | `anatomy.py`, `classify.py`, `scaler.py` | whole guitars are split into anatomical parts; single components are classified and scaled to real-world inches at the library's pixels-per-inch |
| populate | `populator.py` | files PNG cut-outs + thumbnails into `library/` and records everything in `library/manifest.json` |

## Headless / batch use

```bash
python -m guitar_mechanic process        # one pass over uploads/
python -m guitar_mechanic watch          # keep watching uploads/
python -m guitar_mechanic status         # what's in the library
python -m guitar_mechanic process --category pickup_humbucker  # force a type
```

## Private pictures

Anything private goes in the vault — a local, never-committed,
never-published folder with the librarian, a private copy of the pipeline,
the local image generator, and password-locked galleries:

```bash
python -m guitar_mechanic vault init      # create it, install the guards
python -m guitar_mechanic vault doctor    # check every safety layer is up
```

The vault is ignored twice over, a pre-commit hook refuses any commit
carrying vault content (including a resized copy of it), the builder's
server refuses to serve it, and gallery contents are encrypted at rest.
See [VAULT.md](VAULT.md).

## Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

## Notes & current limits

- Background removal is heuristic (built for plain-ish product-photo
  backdrops). `pip install rembg` upgrades slicing to ML matting.
- Anatomy splitting yields headstock / neck / body. Parts mounted on the
  body (pickups, bridge) stay baked into the body cut — upload them as
  individual photos to swap them.
- Real-world sizes live in `guitar_mechanic/config.py`
  (`COMPONENT_DIMENSIONS_IN`) — tune to taste.
