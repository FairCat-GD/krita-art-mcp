Read docs/spec/REVIEW-2026-10-25.md §3 (F1, F2, F4–F7, F9) and §6; docs/spec/SPEC.md §1
(decision 2), §5 (invariants 5, 8); docs/spec/PDD.md Part 4 (`krita_history_step`), Part 8 (K43,
K44); CLAUDE.md; your block (10a) in docs/spec/SESSIONS.md and block 10's done-note; then this
file. Do Session 10a: review fixes — paint safely. The block is the one home of its items; in
short, it closes the `BaseException` window in `layer.update` (F1), holds invariant 5 on every
`history.step` path and makes its capture best-effort (F2), reports a LOST stop (F6), pins or
rehomes five duplicates (F5), retries a BUSY probe export once (F7), measures Krita's default
undo-stack limit (F9), and measures a non-square image tip against the margin's extent bound
(F4).

Release 0.10.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 10 are done, 6a and 7a included. Session 10
  inserted 10a (this session); 11 to 15 remain, releasing 0.11.0 to 0.14.0.
- **The push status.** `origin` is the private GitHub repository. `origin/main` holds everything
  through session 9's review commit ("review: a stroke that changes nothing says history stops,
  and 9 smaller"). Session 10's architecture-review commit and the review-fixes commit after it
  are local only. List `origin/main..HEAD` before any push.
- **Session 10 changed no product code.** The REVIEW file, the 10a block, the shifted versions
  (11–15 now 0.11.0–0.14.0 in the table and in blocks 11, 12, 14, 15) and this file are its
  whole diff.
- **What 10a touches, as it is now:**
  - `plugin/krita_art_mcp_bridge/bridge_core/layer_update.py` — the mutation phase catches
    `BridgeError`/`Exception` only; the stroke's `BaseException` handler in
    `bridge_core/painting.py:141-145` is the pattern to mirror.
  - `plugin/krita_art_mcp_bridge/bridge_core/history.py` — `step_history` calls `move` bare and
    writes the region capture with a raising `transfer.write`; `verification.files` is the
    best-effort pattern.
  - `krita_history_step.json` — `stopped` gains a LOST value; edit the schema, then
    `uv run scripts/amend_schemas.py` (a test holds the files to it).
  - The F5 copies: `bridge_core/painting.py:36-37` bounds, `krita_adapter/painting.py:12`
    `SRGB_PROFILE`, `probe/painting.py:27` `LABEL`, the allowed-mask size rule
    (`verification.py:222-225` / `protection.py:96-99`), `_refuse_reach`
    (`painting.py:567-575` / `layer_update.py:301-309`).
  - `src/krita_art_mcp/probe/opening.py:100-126` — the BUSY retry.
  - `krita_adapter/documents.py:264-271` — `undo_limit`'s fallback, set to the measured default.
- **Ask at the start** (block 10a): which stock preset carries F4's non-square image tip; if none
  does, the assumption is recorded as unmeasurable with stock presets.
- **Baseline** (session 10, as found; 10a moves these only by what it adds):
  - `verify`: 6 stages, all PASS;
  - 486 server tests passed, 0 skipped;
  - 558 plugin-core tests passed, 0 skipped;
  - `probe`: 95 PASS, 0 FAIL, 32 MEASURED, 67.9 s;
  - 17 registered tools; 19 schema files; instructions 3,175 characters (10a adds none).
- **Not done:**
  - **The owner's roots.** `doctor` step 6 FAILs with "no roots" until the owner runs
    `roots add`. No session runs it, and the probe needs no roots.
  - **By hand** (in `docs/BACKLOG.md`): N-03 in Activity Monitor; mirror painting and
    wrap-around put back after a stroke; whether a K46 switch visibly moves the tab; the overlay
    in the mask display mode; K46 with the global selection's mask; a layer style refusing
    region scope.

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
- **A review fix must not loosen a refusal.** F2's best-effort capture changes only the file
  write; a failed undo still fails the op.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor`
  step 5 passes; F1, F2 and F6 all change the plugin.
- **Before the probe's paint checks, the stock presets must be listed in Krita:** `b) Basic-2
  Opacity`, `b) Airbrush Soft`, `y) Texture Spray`.
- **The probe's export can answer `BUSY`** when Krita's autosave holds the harness document; F7
  makes the probe retry it once — falsify that path like any new check.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current
  brush and Krita's preset history. The probe saves and writes back the brush state; a
  scratchpad driver must do the same (`harness.brush_state` read first, written back after).
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
