Read `FEATURE-recovery-and-construction.md` *The Codex agent's report* (its answers), decisions 1, 3,
14; `ARCHITECTURE.md` *The invariants* (1, 4, 5), *Documents*, *Reads, and K46*, *Protection,
selections and masks*, *The verification core*, *Painting* (the fill too), *The undo ledger and
history*, *The save*; then CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline,
your block in docs/spec/SESSIONS.md and C1's done-note, then this file, and do Session M1:
transparency masks. Measure first, in a harness document, then build on the verified-mutation
frame, version 0.22.0.

## State you need that is not in the specs

- **Round 2 is recovery and construction.** R1, R2, R3, D1, F1 and C1 are done. M1, X1, E1, L1, B1,
  T1, S1, X2 and V1 remain, in that order.
- **`api_version` is 0.4.0.** C1 added a tool and fields only.
- **What C1 left for M1:**
  - **The fill is `paint.fill` in `bridge_core/painting.py`,** beside the stroke. Both run one
    shared function from R on (`painted`): scope, reads, `OUTSIDE_ALLOWED_MASK`, the frame, the
    brush re-read, the judge and `back`. Each op brings its R, its noun and its paint call. A mask
    target joins there, with `channels=1` on `verifiable`.
  - **Shapes are `bridge_core/shapes.py`,** pure: exact fields, the area rule, and a box by a
    curve's extrema.
  - **The fill activates `c) Pencil-3 Large 4B` every time** (`FILL_PRESET`), a build-up
    `paintbrush` preset, and refuses it if it washes or carries a masking brush. Measured: every
    preset fills the same visible pixels, but a wash preset writes colour under alpha 0 up to 3 px
    past the shape. MyPaint presets filled exactly as the build-up one on an RGBA layer.
    `paintAbility()` refuses MyPaint on a non-RGBA device (K9), so on a one-byte mask the fill's
    own preset is what keeps MyPaint out: no extra rule is needed for it.
  - **A selection's bounds run past the canvas** (an inverted rect's are 448 × 320 on a 400 × 300
    canvas). `painting._selected` clips them; anything that reads `selection_bounds` must too.
  - **Plugin tests share `tests/fixtures/paint_world.py`** (the stroke's `World`). The fake fill
    paints the shape's aligned box, and `FakeResources.stock` holds the fill preset unlisted.
- **C1 is not pushed.** `origin/main` stops at "review: a rollback with nothing to move flipped
  the view, and 6 smaller". List `origin/main..HEAD` before any push.
- **The evidence stays outside the repository.** The Codex agent holds its bundles.
- **Baseline** (ARCHITECTURE's table, v0.21.0): `verify` 6 stages, all PASS; 953 server tests and
  878 plugin-core tests, 0 skipped; `probe` 159 PASS, 0 FAIL, 25 MEASURED, about 130 s with 0
  documents open; 20 tools; 20 schema files; 30 error codes; 32 bridge ops; instructions 3,750
  characters.
- **Not done:** `capabilities.py`'s `selection.enforced` note still says "Strokes keep to the
  global selection"; fills do too. It is a plugin string, so it waits for the next plugin change.

## Watch for

- **The standing traps:**
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit
    with `git commit -F`, delete the draft.
  - **Never `git checkout <path>`.** Stage explicit paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it for the project.
  - **The owner's Krita is live.** No session touches their documents. Restart Krita only when
    `doctor` reports 0 unsaved documents, and ask the owner first. `osascript` quitting Krita
    reports "User canceled" yet Krita quits: wait for the process to go, then a few seconds more,
    because `open` straight after fails with -600.
  - **Krita can start with a dialog open.** It refuses every document call with
    `KRITA_MODAL_DIALOG`; ask the owner to close it, then rerun.
  - **The probe refuses to run its document checks while any document is unsaved.** Ask the
    owner to save, then rerun.
- **The term list is not empty.** `~/.config/hygiene/terms.txt` holds 75 words. Never assume its
  size, never print a term, and ask before any write to it.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe or measurement run.
- **A client's `serve` runs this checkout as it stands.** Keep the tree working between edits.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor` step
  5 passes. Bump the version first: the plugin's hash and `serve`'s gate both read it.
- **A measurement instrument** is easiest as a temporary op in the handlers that have what it
  needs, gated to harness documents like `harness.*`. Its driver opens an ORA fixture under
  `<data dir>/harness/` through a stdio `serve`, and keeps that `serve`'s data dir out of any
  folder it deletes. Never run it alongside the probe, which sweeps the harness folder.
- **Before the probe's paint checks, these stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`, and now
  `c) Pencil-3 Large 4B`.
- **Brush state is window-wide (K3).** A scratchpad driver must read `harness.brush_state` first,
  from a document in the harness folder, with every preset it will activate, and write it back.
- **In a probe check, clear a selection only after any undo that check makes.** Otherwise the undo
  takes back the clear, and the selection confines every later check.
- **M1's own traps:** the block's *Watch for* (one byte per pixel through the frame; `selection()`
  is live; existing masks are protected at open; `reach()` on a mask target).
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
