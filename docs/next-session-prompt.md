Read all of docs/spec/SPEC.md; docs/spec/PDD.md Parts 4 and 8, with Part 4's Phase 2 and Phase 3
sections; CLAUDE.md; docs/spec/REVIEW-2026-10-24.md; then this file and the code and tests of
sessions 1–9. Then do Session 10 of docs/spec/SESSIONS.md: the architecture review "paint
safely", findings only, no product code and no version.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 9, 6a and 7a are done. Session 10 is the second
  architecture review. Sessions 11 to 15 remain, releasing 0.10.0 to 0.13.0.
- **The push status.** `origin` is the private GitHub repository `FairCat-GD/krita-art-mcp`.
  `origin/main` holds everything through session 9's review commit ("review: a stroke that
  changes nothing says history stops, and 9 smaller"), its parts and merges included, pushed with
  the owner's approval; nothing is local. List `origin/main..HEAD` before any push.
- **Session 9 ran as a one-session trial of parallel parts.**
  - The kit is `~/Documents/Claude Templates & Notes/AppDev/workflow-kit/parallel/DEVELOPMENT-WORKFLOW.md`.
    This project's own workflow and `CLAUDE.md` did not change.
  - Two parts ran in their own worktrees: 9.1, the plugin core, and 9.2, the server tool. They
    were merged `--no-ff` in that order, after two coordinator work commits.
  - **For the review:** history shows the parts' commits, the two merges and the session commit.
    Block 9's done-note has a *Parts* section recording what went well and what the briefs missed.
  - `.gitignore` now ignores `.claude/worktrees/`, where the app makes session worktrees.
- **What 9 built** (block 9's done-note has the detail):
  - **`krita_paint_stroke`:** one native stroke, verified per stroke inside the plugin.
    - R and a guard ring come from the effective brush.
    - Each stroke step carries a pixel witness that history checks.
    - Rollback is native undo, confirmed.
    - The preset fingerprint leaves out per-call fields, and the bridge remembers its own
      activations.
    - A stroke that changes no pixel seals history, and its receipt says so (`history_sealed`).
  - **Journal lines are version 2:** each call's arguments are kept in a sidecar file.
- **Decided by the owner in session 9:**
  - **Refused for now:** erasing, and strokes shorter than half a pixel.
  - **Accepted and recorded:** Krita writes the presets it activates into `kritarc`'s preset
    history.
  - **F10:** a lazy baseline in session 11 (block 11 amended).
- **For the review's focus** (block 10):
  - **Headroom:** N-01 p95 0.09 s against 1.5 s, N-09 p95 0.23 s against 3 s, with every
    protected layer covering each stroke's region. Corner-to-corner strokes take 0.4 s at 2k and
    3.7 s at 8k.
  - **The harness:** about 70 s, of which the benchmarks are about 15 s.
  - **Review 6's findings in session 9:**
    - F2 and F3 were measured; F3 bit and was fixed by the sidecar.
    - F10 was measured and decided.
    - F19 is held by a test.
    - F5 used 265 of its 300 characters.
- **Baseline** (session 10 changes no code, so it records these as found):
  - `verify`: 6 stages, all PASS;
  - 486 server tests passed, 0 skipped;
  - 558 plugin-core tests passed, 0 skipped;
  - `probe`: 95 PASS, 0 FAIL, 32 MEASURED, about 70 s;
  - 17 registered tools; 19 schema files; instructions 3,175 characters.
- **Not done:**
  - **The owner's roots.** `doctor` step 6 FAILs with "no roots" until the owner runs
    `roots add`. No session runs it, and the probe needs no roots.
  - **By hand** (in `docs/BACKLOG.md`): N-03 in Activity Monitor; mirror painting and wrap-around
    put back after a stroke; whether a K46 switch visibly moves the tab; the overlay in the mask
    display mode; K46 with the global selection's mask; a layer style refusing region scope.

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
- **A review is evidence, not scope** (block 10). It writes `docs/spec/REVIEW-<date>.md`, and the
  owner picks the findings in plan mode.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current brush
  and Krita's preset history. The probe saves and writes back the brush state. A scratchpad
  driver must do the same: use `harness.brush_state` read first, and write it back after.
- **Before the probe's paint checks, the stock presets must be listed in Krita:** `b) Basic-2
  Opacity`, `b) Airbrush Soft`, `y) Texture Spray`.
- **The probe's export can answer `BUSY`** when Krita's autosave holds the harness document. A
  rerun passes.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor`
  step 5 passes.
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
