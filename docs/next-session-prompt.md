Read everything: every session's code and tests so far, cold, against
`FEATURE-recovery-and-construction.md` and `docs/spec/SESSIONS.md`; then CLAUDE.md,
docs/ARCHITECTURE.md's overview, invariants and baseline, your block in docs/spec/SESSIONS.md and
M1's done-note, then this file, and do Session X1: architecture review of the frame and its first
two tools. Write `docs/spec/REVIEW-<date>.md` from the workflow's template, findings only, read
twice (the second time cold), each finding verified on the code path. No product code, no version.

## State you need that is not in the specs

- **Round 2 is recovery and construction.** R1, R2, R3, D1, F1, C1 and M1 are done. X1, E1, L1, B1,
  T1, S1, X2 and V1 remain, in that order.
- **`api_version` is 0.4.0.** M1 added a value, fields and a capture target only.
- **What X1 reads that is new since F1:**
  - **The frame's tools:** `paint.stroke` and `paint.fill` (`bridge_core/painting.py`, one shared
    `painted` from R on), `layer.update`, and `layer.create`, which now reads the composite for a
    transparency mask. Each runs on `bridge_core/mutation.py`.
  - **Masks:** `layer.create` with `coverage` through `krita_adapter.documents.create_mask`;
    `protection.refuse_held_line` (mask, layer and every group unprotected), meant for L1's
    reorder and remove of masks too; `reach()` starting from a mask's layer; a mask target read one
    byte a pixel (`channels=1`); `capture.read`'s `mask` target; `layer.update` taking `name` and
    `visible` on a mask.
  - **Invariant 1's scan** holds `setSelection` to four sites, by name and by attribute:
    `selections.commit`'s two, `documents.add_active_mask` and `documents.create_mask`.
  - **Mask paint** is `mask: "reveal" | "hide"`, sent beside a null `color`; Krita paints white or
    black under `normal`, by the opacity.
- **What M1 measured that the spec's sources did not say:** greys become mask coverage linearly on
  5.3.4.1, not by lightness. A mask's bounds are its layer's own, and no mask moves them. A local
  selection mask on the layer does not confine mask paint.
- **Decisions written down nowhere else:** the owner allowed M1 to restart Krita when needed, at 0
  unsaved documents. That approval was for M1 only.
- **The hint table moved:** `krita_layer_create` is destructive since 0.22.0 (decision 1's rule,
  the owner's call), so four mutating tools are additive.
- **The probe's mask checks** are `probe/transparency.py`, run inside the paint stage after
  `filling.run`, on their own working copy, with an amber layer for the leak check.
- **M1 is committed locally, not pushed.** `origin/main` stops at "review: a curve's turning point
  could be missed, and 6 smaller". List `origin/main..HEAD` before any push.
- **The evidence stays outside the repository.** The Codex agent holds its bundles.
- **Baseline** (ARCHITECTURE's table, v0.22.0): `verify` 6 stages, all PASS; 970 server tests and
  927 plugin-core tests, 0 skipped; `probe` 171 PASS, 0 FAIL, 25 MEASURED, about 130 s with 0
  documents open; 20 tools; 20 schema files; 30 error codes; 32 bridge ops; 12 capabilities;
  instructions 3,908 characters.
- **Not done:** nothing from M1's block.

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
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber` and
  `c) Pencil-3 Large 4B`.
- **Brush state is window-wide (K3).** A scratchpad driver must read `harness.brush_state` first,
  from a document in the harness folder, with every preset it will activate, and write it back.
- **In a probe check, clear a selection only after any undo that check makes.** Otherwise the undo
  takes back the clear, and the selection confines every later check.
- **Falsifying by test name:** a pytest `-k` with spaces selects nothing, and "no tests ran" reads
  as a failure. Use parametrize ids without spaces, and check each run selected a test.
- **A probe check that compares a composite needs a layer unlike what lies under it,** or hiding it
  changes nothing visible.
- **X1's own traps:** the block's *Watch for* (a review is evidence, a block is scope). Attack in
  particular: the markers against what each op does; whether `uncertain` stays rare in the probe's
  runs; the frame against E1, L1, B1, T1 and S1; the instructions' budget (188 characters spare).
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
