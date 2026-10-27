Read `SPEC.md` §1 (decisions 6, 31); `PDD.md` Part 1 (pillar 4), Part 4 (`krita_preview_render`),
Part 5 (N-02); `REVIEW-2026-10-24.md` F5; CLAUDE.md; your block (11) in docs/spec/SESSIONS.md and
block 10a's done-note; then this file. Do Session 11: `krita_preview_render`, with:
- the lazy `as_opened` baseline (block 11's F10 amendment);
- the sheet composed on the server from native captures;
- the N-02 benchmark.

Release 0.11.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 10a are done, 6a and 7a included. 11 to 15
  remain, releasing 0.11.0 to 0.14.0.
- **10a is committed locally, not pushed.** `origin/main` holds everything through `71548d5`
  (session 10's review commit). 10a's commit and its review-fixes commit wait for the next
  approved push. List `origin/main..HEAD` before any push.
- **What 10a left that 11 builds on:**
  - **`history.unconfirmed(handle)`** is the one guard around a change and its rollback. It lets
    the op's own `BridgeError` through, and on any other raise it seals, marks unsafe and
    re-raises. The stroke and `layer_update` use it. A new mutating op uses it too; 11 adds
    none.
  - **`verification.write`** is the one home of the best-effort transfer write: a file that
    cannot be written is logged and left out. History's capture and `verification.files` use it.
  - **`krita_history_step`'s `stopped`** now takes `document_unsafe` (LOST, or a step whose
    move raised); `unconfirmed` means Krita did not take the step and it was put back.
  - **`undo_limit()` falls back to 200,** Krita's own default.
  - **The probe** has a tall-tip MEASURED line (`_tall_tip`, its own 480 × 480 working copy),
    and the KRA export retries one BUSY.
- **Measured in 10a, for `ARCHITECTURE.md` at session 15** (details in 10a's done-note):
  - Krita sizes an image tip by its longer side: the 7 × 32 Wood Fiber tip reached 0.52 × size
    past the path, inside R's margin, so `EXTENT[IMAGE] = √2⁄2` holds.
  - Krita keeps exactly the undo limit the ledger reads.
  - `KisConfig::undoStackLimit` defaults to 200 (`libs/ui/kis_config.cc:192-195` at the running
    build `bd6e8d0`).
- **Decisions written down nowhere else:** none beyond 10a's done-note.
- **Baseline** (10a, as committed; 11 moves these only by what it adds):
  - `verify`: 6 stages, all PASS;
  - 490 server tests passed, 0 skipped;
  - 567 plugin-core tests passed, 0 skipped;
  - `probe`: 95 PASS, 0 FAIL, 33 MEASURED, 74.3 s;
  - 17 registered tools; 19 schema files; instructions 3,175 characters (11 may add at most 300
    net).
- **Not done:**
  - **The owner's roots.** `doctor` step 6 FAILs with "no roots" until the owner runs
    `roots add`. No session runs it, and the probe needs no roots.
  - **By hand** (in `docs/BACKLOG.md`): N-03 in Activity Monitor; mirror painting and
    wrap-around put back after a stroke; whether a K46 switch visibly moves the tab; the overlay
    in the mask display mode; K46 with the global selection's mask; a layer style refusing
    region scope.
  - **A live BUSY export** was never forced; the probe's retry is held by its unit test.

## Watch for

- **The standing traps:**
  - **Never `git checkout <path>`.** Stage explicit paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it for the project.
  - **The owner's Krita is live.** No session touches their documents. Restart Krita only when
    `doctor` reports 0 unsaved documents, and ask the owner first; another agent may be working.
    `osascript` quitting Krita reports "User canceled" yet Krita quits: wait for the process to go.
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it
    (`--message`), commit with `git commit -F`, delete the draft.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor`
  step 5 passes. A probe-only change runs against the installed plugin, since its hash is
  unchanged.
- **Before the probe's paint checks, the stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current
  brush and Krita's preset history. The probe saves and writes back the brush state; a
  scratchpad driver must do the same (`harness.brush_state` read first, written back after).
- **A fit-to-window image is not evidence of game size** (block 11): the cell transform must be
  exact after rounding.
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
