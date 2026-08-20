# The Vault

Private pictures do not belong in a public repo, and this one is public:
`photos/` is committed, and `docs/` is what GitHub Pages serves to the
open web. The vault is the other half of the workshop — the half nothing
escapes from.

```bash
python -m guitar_mechanic vault init      # create it, install the guards
python -m guitar_mechanic vault doctor    # check every layer is still up
```

Everything private lives under `vault/`:

```
vault/
  originals/    private source pictures
  quarantine/   what the safety screen held back
  uploads/      drop zone for the private pipeline
  library/      parts the private pipeline cut — never mirrored to docs/
  generated/    output of the local generator, still in the clear
  galleries/    password-locked galleries, encrypted at rest
  .vaultmeta/   the ledger and index — fingerprints and notes, no pictures
```

## The safety mechanisms

Six layers. They are deliberately independent, so getting past one is not
enough to leak a picture.

**1. Ignored twice.** `vault/` is in the root `.gitignore`, and
`vault/.gitignore` ignores everything from the inside. Rewriting one
still leaves the other.

**2. The commit guard.** A `pre-commit` hook refuses any commit carrying
vault content. It catches three different things:

- anything whose *path* is in the vault, including a `git add -f`;
- anything whose *bytes* match a vault picture;
- anything that merely *looks like* one. Every picture the vault has held
  is fingerprinted with a perceptual hash, so the realistic accident — a
  resized, re-saved, innocently-renamed copy — is caught too. That case
  is covered by a test that drives real `git commit`.

**3. The screen.** Every picture entering the pipeline is checked for
person signals: personal words in the filename, EXIF GPS, faces (when
`opencv-python` is installed), and large smooth skin-tone regions. Bare
ash and mahogany sit squarely in the skin-tone range, so the screen also
measures grain — wood has figure, skin does not — and on this repo's 155
photographs that separates them cleanly.

It fails closed. Anything it cannot read is held. Anything it is unsure
of is held. A false positive costs you one `vault release`; a false
negative is on the internet forever.

**4. The publish audit.** `vault check-publish docs/` runs the same
checks over the folder GitHub Pages serves, and the same audit runs in CI
on every push, because a picture can reach the repo by paths the pipeline
never sees — a drag-and-drop into the GitHub web UI, for instance.

When the screen is wrong about a picture — a dark walnut body reads much
like skin — review it and say so:

```bash
python -m guitar_mechanic vault approve photos/bodies_batch_2/IMG_4059.JPEG \
    --note "walnut body, smooth finish reads as skin tone"
python -m guitar_mechanic vault approvals
```

That writes `.vaultguard/approved.json`, which is committed so CI honours
the same list. Approvals are keyed by hash, so editing a file revokes its
approval, and they waive *heuristic* findings only — a picture the vault
has held is refused no matter what is approved.

**5. The server guard.** The builder app serves the project root, which
is also where the vault sits. It refuses `/vault` and `/.git` outright,
including via `..` and percent-encoding, so forwarding or tunnelling the
port cannot walk into private pictures.

**6. Encryption at rest.** Gallery contents, filenames, and prompts are
all inside the ciphertext (scrypt + SHA-256 keystream + HMAC). A gallery
folder that leaves the machine is unreadable. There is no recovery if you
lose the passphrase — a recovery hatch is also a leak.

## Day to day

```bash
# take pictures in (screened on the way; --move leaves no outside copy)
python -m guitar_mechanic vault add ~/Pictures/shoot --move

# what's in there
python -m guitar_mechanic vault list
python -m guitar_mechanic vault status

# cut parts privately: vault/uploads -> vault/library, never docs/
python -m guitar_mechanic vault process

# check something without moving it, or strip metadata in place
python -m guitar_mechanic vault screen some.jpg
python -m guitar_mechanic vault scrub photos/    # lossless: pixels untouched

# before publishing
python -m guitar_mechanic vault check-publish docs/
```

## Locked galleries

```bash
python -m guitar_mechanic vault gallery new "Night Work"
python -m guitar_mechanic vault gallery add "Night Work" some.png --shred
python -m guitar_mechanic vault gallery items "Night Work"
python -m guitar_mechanic vault gallery export "Night Work" <id> ~/Desktop
```

`gallery list` works without a passphrase and shows only names and
counts. Everything else needs the passphrase, which is never stored —
type it, or put it in `KILLETTE_VAULT_PASSPHRASE` for scripting.
`--shred` overwrites the cleartext original (and the generator's prompt
sidecar) after locking it away.

## The local generator

Local, offline, and unfiltered — it renders what you ask it to, and no
prompt or picture leaves the machine.

```bash
python -m guitar_mechanic vault generate "blood ritual sigil, lightning, rust" \
    --seed 666 --count 4
python -m guitar_mechanic vault generate "chrome abalone rays" \
    --gallery "Night Work"          # straight into the locked gallery
```

The default backend is **procedural**: seeded fractal noise, sigils,
fracture bolts, bloom and grain, steered by keywords in the prompt
(palettes like `blood`, `bone`, `abalone`, `chrome`, `gold`, `toxic`,
`violet`, `ember`, `ice`, `void`; motifs like `sigil`, `lightning`,
`nebula`, `rays`, `grit`). It needs nothing beyond this repo's
requirements, and the same prompt with the same seed always gives the
same picture.

If you have diffusion weights on disk and `diffusers` installed, point
the generator at them:

```bash
python -m guitar_mechanic vault generator --backend local_model \
    --model-path /path/to/model
```

That backend is loaded strictly offline, with no safety checker attached.
Output goes to `vault/generated/`, or straight into a locked gallery with
`--gallery`. The generator refuses to write anywhere outside the vault.

## What this does not protect against

Worth knowing, because a safety mechanism you trust past its limits is
worse than none:

- **History is forever.** These guards stop the *next* leak. Anything
  already pushed is already public, and stays in the git history even if
  you delete the file. Removing it means rewriting history and rotating
  anything it exposed.
- **`--no-verify` skips the hook**, and a fresh clone has no hooks until
  you run `vault install-hooks`. That is why the same audit runs in CI.
- **The screen is a heuristic**, not a guarantee. It has no idea what is
  in a picture; it measures skin tone, grain, faces and filenames. Install
  `opencv-python` to turn on face detection — without it the strongest
  person signal is missing.
- **Shredding is best effort.** On SSDs and copy-on-write filesystems the
  old blocks can survive. It is a speed bump, not an erasure guarantee.
- **Scrubbing does not reach what is already pushed.** `vault scrub`
  strips EXIF from the working copy; the old bytes stay in git history.
- **The vault is only as private as the machine.** Anything with a
  passphrase is encrypted; `originals/`, `uploads/`, `library/` and
  `generated/` are not. Backup and cloud-sync tools will happily copy
  them — exclude `vault/` from those too.

## Turning on face detection

The screen's strongest person signal is off unless OpenCV is installed,
and the version matters:

```bash
pip install "opencv-python<5"
```

OpenCV 5 removed the bundled Haar cascade, and its DNN replacement needs
a model file that does not ship with the wheel. If you are on 5, either
pin below it or drop a YuNet ONNX model at
`vault/.vaultmeta/face_detection_yunet.onnx` and the screen will use it.

`vault doctor` tells you which of these you have — it probes the detector
rather than assuming, because a safety signal that is quietly switched
off is worse than one that was never claimed.

A raw cascade is close to useless here: on this repo's 142 guitar photos
the stock parameters claim faces in 121 of them, because wood grain looks
like a face to a Haar cascade. So a candidate box is only counted if the
pixels inside it also read as skin — smooth, and skin-toned. That takes
the 121 down to 1, and the three residual false positives across the whole
repo are handled by `vault approve`.
