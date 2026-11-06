Read `FEATURE-recovery-and-construction.md` *The Codex agent's report* (Authoring, its answers),
decision 16; `ARCHITECTURE.md` *Painting*, *Reads, and K46* (Resources), *Testing strategy*
(Hypotheses), *Reference* (K3, K4, K30, K36); `REVIEW-2026-11-06.md` §5 E1, F2, F26 and the Info on
the brush exclusion; then CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline, your
block in docs/spec/SESSIONS.md and X1a's done-note, then this file, and do Session E1: tapers, a
bounded native probe, then the proven subset. E1 has three parts:
- the go/no-go, on a throwaway document, before any product code: a `fromXML` Distance curve on
  size, painted and restored, judged by the block's five conditions;
- on go: `dynamics` on `krita_paint_stroke`, size and opacity over normalised arc length, with a
  `stroke.dynamics` capability;
- on no-go: the limitation published, the sensors to the backlog, documentation alone.

Release 0.24.0 on go; on a no-go E1 ships no version, and every later version moves down by one.

## State you need that is not in the specs

- **Round 2 is recovery and construction**: R1, R2, R3, D1, F1, C1, M1, X1 and X1a are done; E1,
  L1, B1, T1, S1, X2 and V1 remain, in that order.
- **X1a and its review fixes are pushed.** `origin/main` holds everything through "review: a
  no_effect line naming no bridge op settled all, and 5 smaller". List `origin/main..HEAD` before
  any push.
- **What X1a left that E1 builds on:**
  - **The digest memory** is `activated` and `remember` in `bridge_core/painting.py`, with
    `remember` called from the stroke and from the fill, and `_listed`'s preset lookup. Name
    functions, not lines: X1a moved lines below `_check_mask_paint`.
  - **The instructions** are 2,945 characters, 1,151 spare. `tests/test_envelope.py` holds 700
    spare (`SPARE_FLOOR`), the room for E1's line and the four sessions after it. Its `MOVED`
    table holds each rule that left the instructions in its tool's or field's description.
    Rewording one of those descriptions must keep its phrase, or move the row.
  - **The stroke's `verify` description** now says region needs "the pixel brush engine with a
    tip and scatter it can read". `dynamics` on the pixel engine only fits beside it.
  - **Every rollback's details carry `history_sealed`.** The stroke's receipt already had it.
  - **Mask paint refuses `eraser`** in `_check_mask_paint`, which now reads `style.get("eraser")`.
  - **K46's activation is window state, not a change,** like the brush. The fake's `activate` gate
    lets through only the activation off an active selection mask onto the layer
    `nodes.unmasked` names.
- **What the spec said that turned out wrong or harder:**
  - **`_sent` was the wrong record for X1a's poll rule:** a poll's own wait writes it. The record
    is `BridgeClient._made`.
  - **The block's F20 rule had a race,** so F20 uses an alias line instead.
  - Both are in X1a's done-note.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call:** they ran one on Opus at X1a. Propose one only when a
    plan reworks a heavily tested path, and ask which model.
  - F28 stays a fix, with `api_version` 0.4.0.
- **What the review found that a reader may miss:**
  - The hidden file after an `uncertain` save stays: known debt, now including a finish that
    never ran.
  - `eraserMode()` reads false after `setEraserMode(True)` on 5.3.4.1.
  - The fake honours the eraser, and restores whole snapshots on undo.
- **Baseline** (ARCHITECTURE's table, v0.23.0):
  - `verify` 6 stages, all PASS; 1013 server tests and 945 plugin-core tests, 0 skipped;
  - `probe` 174 PASS, 0 FAIL, 25 MEASURED, 136 s with 0 documents open, the journal check reading
    682 dispatched lines;
  - 20 tools; 20 schema files; 30 error codes; 32 bridge ops; 12 capabilities; instructions 2,945
    characters.
- **Not done:** nothing from X1a's block. Three parts of the review it left went to `BACKLOG.md`:
  F16's `transfer.write` tail, F24's edge checks under a selection, and F10's preview pair.

## Watch for

- **The standing traps:**
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit
    with `git commit -F`, delete the draft.
  - **Never `git checkout <path>`.** Falsify by copying the file aside and back. Stage explicit
    paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it for the project.
  - **The owner's Krita is live.** No session touches their documents.
    - Restart Krita only when `doctor` reports 0 unsaved documents, and ask the owner first.
    - `osascript` quitting Krita reports "User canceled" yet Krita quits. Wait for the process to
      go, then a few seconds more, because `open` straight after fails with -600.
    - At the end of M1 a quit timed out with 0 documents open. Don't force it: ask.
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
  needs, gated to harness documents like `harness.*`.
  - Its driver opens an ORA fixture under `<data dir>/harness/` through a stdio `serve`.
  - It keeps that `serve`'s data dir out of any folder it deletes.
  - Never run it alongside the probe, which sweeps the harness folder.
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
- **A probe check that reads a stroke's middle** must name the row it stroked along. A median of
  the changed rows can land on the antialiased edge, one row off.
- **A test that polls a save must poll from the server instance that made it.** Each
  `world.server()` is a new process to the poll rule, so a second instance only reads.
- **E1's own traps:** the block's *Watch for*.
  - `remember` runs before the `fromXML` edit and never after it, or `activated` vouches for the
    edited digest for the Krita session.
  - Mark before the edit, and restore inside the change, checked by digest.
  - The probe is bounded: a no-go is a result.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
