Read `REVIEW-2026-11-06.md` whole (F1–F6, F10, F11, F13–F21, F23–F25, F27 are its scope),
`FEATURE-recovery-and-construction.md` decisions 1, 5, 7, 10, `ARCHITECTURE.md` *The tool contract*
(Hints, The instructions, Argument rules are written twice), *Bridge and jobs*, *The verification
core* (The frame, The rollback), *The undo ledger and history*, *The save*, *The server*, *Testing
strategy*; then CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline, your block in
docs/spec/SESSIONS.md and X1's done-note, then this file, and do Session X1a: review fixes — the
frame and the save's finish. X1a has seven parts:
- the save's finish tells the truth (F1, F5, F6): `uncertain` after a completed save unless the
  finish's own discard verified; a finish only from the process that made the call;
- a retryable failure under a derived id runs again (F4);
- the rollback's first undo reads the state (F3);
- the instructions move into descriptions, leaving at least 700 spare (F2);
- parity holds schema-side rules, and one area rule (F10);
- the probe's journal check sees what it reads, and the three mask checks (F11, F24);
- the small fixes and the docs (F13–F21, F23, F25, F27).

Release 0.23.0.

## State you need that is not in the specs

- **Round 2 is recovery and construction**: R1, R2, R3, D1, F1, C1, M1 and X1 are done; X1a, E1,
  L1, B1, T1, S1, X2 and V1 remain, in that order. X1 inserted X1a, so E1 is 0.24.0 and every
  later version moved up by one.
- **X1 is committed locally, not pushed.** `origin/main` holds everything through "review: a
  paint create's parent check was loosened, and 11 smaller". List `origin/main..HEAD` before any
  push.
- **What X1 left that X1a builds on:** every finding has its trace and `file:line` on `189ba26`
  in the review; the pointers below are the ones X1a changes.
  - **The finish's rule:** `src/krita_art_mcp/tools/saving.py:104-107` keeps any stated outcome;
    `tests/test_outcomes.py:641-648` pins it. A finish refused before its marker states
    `not_applied` through `jobs.stated` (`jobs.py:82-93`); the finish's own discards set
    `rollback_verified` (`bridge_core/saving.py:190,197`).
  - **The poll:** `tools/operations.py:65,89-90` runs `Known.finish` for anyone; the plugin's lease
    is `registry.py:198-203`; `_finish_journaled` (`operations.py:192-220`) writes the finished line.
  - **The derived ids:** `jobs.submit` (`jobs.py:185-188`) answers a known op first;
    `_finish_failed` (`:296-298`) releases the request alone; the ids are
    `tools/saving.py:85,87,118-120`.
  - **The rollback's `known`:** `mutation.py:372`; `history._shows` (`history.py:124-129`); the
    two-step tests `tests/plugin/test_mutation.py:66,82`.
  - **The instructions:** `instructions.py`, 3,908 characters; the movable lines and their
    counts are in F2; `tests/test_envelope.py:185,188-192` pin two phrases.
  - **Parity:** `tests/support/parity.py:18-19` turns a named function off; the area rule is
    `strokes.collinear` on the server and `shapes.collinear` over `shapes.points` on the plugin.
  - **The probe:** `probe/__init__.py:274-286`; `probe/transparency.py:263,279-283,301`.
  - **The small fixes,** each with its line in the review: `mutation.py:339,378-381,461`,
    `selections.py:84-90`, `nodes.py:30-47`, `saving.py:109-113,141-145`,
    `tests/plugin/test_outcomes.py:905`, `journal.py:276-286`, `painting.py:376-378,407-411`,
    `tools/__init__.py:199-203`, `capabilities.py:52-57`, `tests/test_schemas.py:200-202`.
- **Decisions written down nowhere else:** the owner chose, at X1, that a poll finishes a save
  only from the process that made the call, with the hint kept read-only; F28 (`rolled_back`'s
  changed meaning for a write-nothing update) stays a fix, with `api_version` 0.4.0.
- **What the review found that a reader may miss:** the hidden file after an `uncertain` finish
  stays (known debt); the fix changes what is said. `eraserMode()` reads false after
  `setEraserMode(True)` on 5.3.4.1, so `_taken` is what refuses `eraser: true` live. The fake
  honours the eraser and restores whole snapshots on undo.
- **Baseline** (ARCHITECTURE's table, v0.22.0, held by X1's runs): `verify` 6 stages, all PASS; 970
  server tests and 931 plugin-core tests, 0 skipped; `probe` 171 PASS, 0 FAIL, 25 MEASURED, 134 s
  with 0 documents open; 20 tools; 20 schema files; 30 error codes; 32 bridge ops; 12
  capabilities; instructions 3,908 characters.
- **Not done:** nothing from X1's block.

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
    because `open` straight after fails with -600. At the end of M1 a quit timed out with 0
    documents open; don't force it: ask.
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
- **Before the probe's paint checks, these stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber` and
  `c) Pencil-3 Large 4B`.
- **Brush state is window-wide (K3).** A scratchpad driver must read `harness.brush_state` first,
  from a document in the harness folder, with every preset it will activate, and write it back.
- **In a probe check, clear a selection only after any undo that check makes.**
- **Falsifying by test name:** a pytest `-k` with spaces selects nothing. Use parametrize ids
  without spaces, and check each run selected a test.
- **X1a's own traps:** the block's *Watch for*. Decision 7 stands: a same-session resend of a save
  is still allowed. The `known` change must leave the two-step tests green and fail the stranger
  test alone. The instructions' two pinned phrases stay; the move is a `Changed` entry.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
