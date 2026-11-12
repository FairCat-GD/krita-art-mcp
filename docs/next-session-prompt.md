Read `REVIEW-2026-11-12.md` whole (F1–F9 and F11–F21 are your scope);
`FEATURE-recovery-and-construction.md` decisions 1, 4, 5, 9, 10, 11, 13, 16; `ARCHITECTURE.md` *The
tool contract* (Argument rules are written twice, Codex's limits), *The verification core*, *The
undo ledger and history*, *Painting* (a taper), *The save*, *The server*, *Testing strategy*, and
*Reference* K22, K51, K53, K54; then CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and
baseline, your block in docs/spec/SESSIONS.md and X2's done-note, then this file, and do Session
X2a: review fixes — construction.

## State you need that is not in the specs

- **Round 2 is recovery and construction.**
  - Done: R1, R2, R3, D1, F1, C1, M1, X1, X1a, E1, L1, B1, T1, S1 and X2.
  - Remaining, in order: X2a and V1.
- **X2 inserted X2a.** X2a cuts 0.29.0 and V1 0.30.0. S1 shipped 0.28.0.
- **X2 is committed locally, not pushed.** `origin/main` holds everything through "review:
  transform refusals read an unwaited tree, and 7 smaller". List `origin/main..HEAD` before any
  push, and push only on the owner's approval.
- **What X2 found that X2a fixes first:**
  - **F1, the High.** L1's four layer ops and `layer_update` read `KritaDocuments.tree`, which never
    waits, before their first wait, and refuse, scope and judge from it. S1's review fixed exactly
    this in `affine.run` and `transforms.translate`; copy that. The review's three runs (a
    protected layer removed, K53's crash path, a region leak verified) are the tests to write.
  - **The decisions to ask at the start** are in the block: F4's integral floats, F7's seal, F16's
    `dirty`, F20's replayed receipts.
  - **F10 is not X2a's.** The fake's per-command pixel undo goes to `BACKLOG.md` in X2a's docs pass.
- **What turned out wrong or harder:**
  - **The cold read's second wave was not wholly cold:** the outcomes brief carried three of the
    first wave's questions; the review says which.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call:** Opus at X1a, E1, L1, B1, T1 and S1. Propose one when a
    plan reworks a heavily tested path, and ask which model. X2a's F1 reworks five ops' starts.
  - **Live runs** were allowed at 0 unsaved with the Codex agent paused, for X2's baseline; ask
    again.
- **Baseline** (ARCHITECTURE's table, v0.28.0, measured again at X2):
  - `verify`: 6 stages, all PASS; 1152 server tests and 1204 plugin-core tests, 0 skipped;
  - `probe`: 226 PASS, 0 FAIL, 25 MEASURED, 150.1 s with 0 documents open, the journal check
    reading 841 dispatched lines;
  - 25 tools, 25 schema files, 30 error codes, 39 bridge ops, 17 capabilities, instructions 3,371
    characters;
  - Codex's renderer: the stroke's normalised input 4,339 of 5,000 bytes, 661 to spare.
- **Not done:** nothing from X2's block.

## Watch for

- **A retryable refusal is a change of nothing,** proven at its raise: the AST scan finds each new
  one, and `tests/plugin/test_outcomes.py` pins it in `RETRYABLE` with its own test.
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
