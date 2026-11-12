Read everything, as X2's block says: every session's code and tests so far, cold, against
`FEATURE-recovery-and-construction.md` and `docs/spec/SESSIONS.md`; `REVIEW-2026-11-06.md` whole,
for the findings the owner left open; then CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants
and baseline, your block in docs/spec/SESSIONS.md and S1's done-note, then this file, and do
Session X2: the architecture review of construction. It changes no product code and cuts no
version.

## State you need that is not in the specs

- **Round 2 is recovery and construction.**
  - Done: R1, R2, R3, D1, F1, C1, M1, X1, X1a, E1, L1, B1, T1 and S1.
  - Remaining, in order: X2 and V1.
- **S1 shipped 0.28.0.** V1 cuts 0.29.0. A session X2 inserts takes the next version, and V1 moves
  up by one.
- **S1 is not pushed.** `origin/main` holds everything through "docs: the handoff says T1 is
  pushed". List `origin/main..HEAD` before any push, and push only on the owner's approval.
- **What S1 built that X2 should attack:**
  - **The frame takes an op's own witness.** `Mutation.run(..., witness_of=...)` pushes or seals
    the pixel step where a target's diff would, and `_pixel` and `_unnamed` use it for an unpushed
    step. Only `affine.py` passes one.
  - **The witness rect is predicted.** `affine.mapped` gives where an operation takes each paint
    layer's bounds, widened by `REACH` (3) times the scale plus `SLACK` (4). Both digests are real
    reads over it, and the judge refuses, rolled back, a layer whose new bounds leave it. A digest
    padded with the default pixel failed live: a resample leaves colour under alpha 0 outside a
    layer's exact bounds (K54).
  - **`history.step` takes a `REVERSED` move of "Scale Layer", "Rotate Layer" or "Shear Layer" as
    foreign:** Krita's own menu pushes the same names, and the fingerprint does not see pixels.
  - **The receipt's `data` is a flat `anyOf` of four shapes,** and `amend_schemas` and the copy
    test take every non-null branch. No other tool has more than one.
  - **Refusals before the marker:** masks and other kinds, transform masks in the subtree or on a
    group above, lock flags, styles, clone sources, empty bounds, a change of nothing (the shear
    through a replica of Krita's `mapRect`), more than 50 nodes, reads past one, cumulative undo, a
    filter Krita lacks. Hidden and pass-through groups are taken, as measured.
  - **The fake** models the three operations by a nearest-pixel remap about the pivot, and its
    `crop` reads off the canvas as zero bytes.
- **What turned out wrong or harder:**
  - **Krita's exact bounds skip alpha-0 pixels,** though a resample leaves colour there.
  - **An ORA's layers load with their x and y as `offset_px`.**
  - **Probe wall time** was 257 s, against 145 s at 0.27.0. The machine ran at a load average of
    about 3.4, and the benchmark and save stages took most of it; S1's checks alone took 3.7 s. A
    run on a quiet machine would say whether the baseline moved.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call:** Opus at X1a, E1, L1, B1, T1 and S1. Propose one when a
    plan reworks a heavily tested path, and ask which model.
  - **Live runs** were allowed at 0 unsaved with the Codex agent paused, for S1; ask again.
- **Baseline** (ARCHITECTURE's table, v0.28.0):
  - `verify`: 6 stages, all PASS; 1152 server tests and 1201 plugin-core tests, 0 skipped;
  - `probe`: 226 PASS, 0 FAIL, 25 MEASURED, 257 s with 0 documents open under load, the journal
    check reading 841 dispatched lines;
  - 25 tools, 25 schema files, 30 error codes, 39 bridge ops, 17 capabilities, instructions 3,371
    characters.
- **Not done:** nothing from S1's block.

## Watch for

- **A review session writes `docs/spec/REVIEW-<date>.md` and nothing else of product code.** In
  plan mode the owner picks which findings become scope: amendments to V1, or an inserted session.
  Name functions, not lines, in the amendments (F26).
- **The standing traps:**
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit
    with `git commit -F`, then delete the draft.
  - **Never `git checkout <path>`.** Stage explicit paths.
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
- **A client's `serve` runs this checkout as it stands.** Do not edit while `verify` runs: a test
  that spawns `serve` reads the files as they are mid-run.
- **Brush state is window-wide (K3).** A scratchpad driver must read `harness.brush_state` first,
  from a document in the harness folder, with every preset it will activate, and write it back.
- **Falsifying by test name:** a pytest `-k` with spaces selects nothing. A mutation that leaves
  a file unparsable fails collection, not the test: check each mutation's run named its test.
  A mutation that a second rule also catches proves nothing about the first: S1 found three such.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
