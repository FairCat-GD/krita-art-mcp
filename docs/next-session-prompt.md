Read `FEATURE-recovery-and-construction.md` *The Codex agent's report* (its answers), decisions 1,
3; `ARCHITECTURE.md` *The verification core*, *The undo ledger and history*, *Protection,
selections and masks* (Translate); `REVIEW-2026-11-06.md` §5 S1, F8, F10, F12; then CLAUDE.md,
docs/ARCHITECTURE.md's overview, invariants and baseline, your block in docs/spec/SESSIONS.md and
T1's done-note, then this file, and do Session S1: scale, rotate, shear. Release 0.28.0.

## State you need that is not in the specs

- **Round 2 is recovery and construction.**
  - Done: R1, R2, R3, D1, F1, C1, M1, X1, X1a, E1, L1, B1 and T1.
  - Remaining, in order: S1, X2 and V1.
- **T1 shipped 0.27.0.** The versions stand as the table says: S1 0.28.0 and V1 0.29.0. S1 may be
  cut first if the round runs long; the owner decides.
- **T1 is committed locally, not pushed.** `origin/main` holds everything through B1's review
  commit. List `origin/main..HEAD` before any push, and push only on the owner's approval.
- **What T1 left that S1 meets:**
  - **`krita_layer_transform` exists,** with `operation` a `oneOf` of one branch,
    `{type: "translate", by_px}`. S1 adds its branches to that `oneOf` and the plugin's
    `transform_rules` (`bridge_core/transforms.py`), whose server half is `changes.transform_rules`.
  - **A translate is a transform mask on top of the layer's masks.** It holds the transform tool's
    free transform at identity with `transformedCenter` moved (`bridge_core/translations.py`).
    `scaleNode` and its kin change pixels instead. Measure what each does to a layer holding a
    translate mask, the mask's params included, and where the pivot falls: Krita's exact bounds
    are the layer's own, unmoved.
  - **The labels are per op:** `history.LABELS["layer.transform"]` is `(ADD, "")`, and the
    translate slices it by path. S1's operations push other labels under the same op, so
    `LABELS` needs a label per operation type, each measured in English.
  - **The fingerprint and `WATCHED` hold `transform_sha256`,** the SHA-256 of a transform mask's
    `toXML`. Bounds and `offset_px` are still outside the fingerprint (F8 for S1).
  - **A params step is pushed only once its state is seen to move.** Any unnamed step S1 makes
    needs the same rule.
  - **`krita_layer_duplicate` refuses a layer holding a transform mask.** Undoing the attach of a
    copied transform mask crashes Krita (K53, on the backlog). Don't build a check that undoes such
    a copy.
  - **The instructions are 3,375 characters,** 721 spare; `SPARE_FLOOR` holds 700, leaving 21. An
    S1 line must move a rule into a description first.
  - **39 bridge ops;** `tests/plugin/test_outcomes.py` holds the count. `BOUNDED` is 18.
  - **14 capabilities,** `layer.translate` among them.
  - **The parity helper's schema path** takes list indexes now, as `oneOf` branches need.
- **What turned out wrong or harder:**
  - **Krita's `toXML` attribute order changes per session.** Never compare a Krita XML as text
    across a restart; parse it.
  - **`fromXML` names its step after a bare command,** so its label is empty.
  - **The cumulative-undo refusal lives in `history.py`;** `painting` and `transforms` both call it.
  - **A probe check that runs two calls must give each its own `guard`.** One `request_id` twice is
    `REQUEST_ID_CONFLICT`, and a later undo then takes back the wrong step.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call:** Opus at X1a, E1, L1, B1 and T1. Propose one when a plan
    reworks a heavily tested path, and ask which model.
  - **Live runs** were allowed at 0 unsaved with the Codex agent paused, for T1; ask again.
- **Baseline** (ARCHITECTURE's table, v0.27.0):
  - `verify`: 6 stages, all PASS; 1135 server tests and 1125 plugin-core tests, 0 skipped;
  - `probe`: 216 PASS, 0 FAIL, 25 MEASURED, 142 s with 0 documents open, the journal check reading
    795 dispatched lines;
  - 25 tools, 25 schema files, 30 error codes, 39 bridge ops, 14 capabilities, instructions 3,375
    characters.
- **Not done:** nothing from T1's block.

## Watch for

- **The standing traps:**
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit
    with `git commit -F`, then delete the draft.
  - **Never `git checkout <path>`.** Falsify by copying the file aside and back. Stage explicit
    paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv is at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it for the project.
  - **The owner's Krita is live.** No session touches their documents.
    - Restart Krita only when `doctor` reports 0 unsaved documents, and ask the owner first.
    - `osascript` quitting Krita reports "User canceled" yet Krita quits. Wait for the process to
      go, then a few seconds more, because `open` straight after fails with -600.
    - After a crash, Krita came back within seconds without being asked. Check `pgrep -x krita`
      before starting it.
  - **Krita can start with a dialog open.** It then refuses every document call with
    `KRITA_MODAL_DIALOG`; ask the owner to close it, then rerun.
  - **The probe refuses to run its document checks while any document is unsaved.** Ask the
    owner to save, then rerun.
- **The term list is not empty.** `~/.config/hygiene/terms.txt` holds 75 words. Never assume its
  size, never print a term, and ask before any write to it.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe or measurement run.
- **A client's `serve` runs this checkout as it stands.** Keep the tree working between edits.
  A test that spawns `serve` reads the files as they are mid-run: do not edit while `verify` runs.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor` step
  5 passes. Bump the version first: the plugin's hash and `serve`'s gate both read it.
- **A measurement instrument:**
  - It is easiest as a temporary op in the handlers that have what it needs, gated to harness
    documents like `harness.*`, calling the adapter methods that will ship.
  - Each action is best its own job, so Krita's timers run between them as in real use.
  - Its driver opens an ORA fixture under `<data dir>/harness/` through a stdio `serve`, and keeps
    that `serve`'s data dir out of any folder it deletes.
  - A capture over 1600 px needs `max_px`.
  - Never run it alongside the probe, which sweeps the harness folder.
  - Remove it, then reinstall the plugin, before the commit.
- **Before the probe's paint checks, these stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber` and
  `c) Pencil-3 Large 4B`.
- **Brush state is window-wide (K3).** A scratchpad driver must read `harness.brush_state` first,
  from a document in the harness folder, with every preset it will activate, and write it back.
- **Probe checks:**
  - Clear a selection only after any undo the check makes.
  - A check that compares a composite needs a layer unlike what lies under it.
  - A refusal check must name the rule's own detail.
  - Mind the stack earlier checks leave.
  - A stroke under `preserve_composite_alpha` must land where the composite is already opaque.
- **Falsifying by test name:** a pytest `-k` with spaces selects nothing. A mutation that leaves
  a file unparsable fails collection, not the test: check each mutation's run named its test. A
  parametrised id with a space in it prints split on `FAILED` lines.
- **A test that polls a save or a duplicate must poll from the server instance that made it.**
- **S1's own traps:** the block's *Watch for*. `scaleNode` and its kin are silent no-ops on masks;
  their sizes are relative to exact bounds and rotation pivots on their centre; the filter name is
  validated by the tool because `scaleNode` falls back to Bicubic silently.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
