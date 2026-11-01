Read block 14's done-note; `PDD.md` Part 7 and C1–C5; `SPEC.md` §5 (invariants 8, 11); `README.md`
(*Registering the server*); `CLAUDE.md`; your block (14a) in docs/spec/SESSIONS.md; then this file.
Do Session 14a: the fixes from the Codex agent's first capture. 14a has these parts:
- find out why `krita_capture` reached Codex as `args: unknown`, then fix it with no schema
  loosened;
- an argument error that names every problem;
- a file-name fallback for a document that lists an empty `name`.

Release 0.15.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 14 are done. 14a (0.15.0) and 15 (0.16.0, the
  close) remain.
- **The push status.** `origin` is the private GitHub repository. `origin/main` holds everything
  through 13a's "review: a blend's moved check reads after the refresh, and 7 smaller". List
  `origin/main..HEAD` before any push; 14's commits are not pushed.
- **What 14 left that 14a and 15 build on:**
  - **`probe/acceptance.py`** holds the six exercises, inside `painting.run`'s brush-state window.
  - **`probe/writes.py`** is N-04: `places`, `take`, `strays`. Its limit is in 14's done-note, and
    `ARCHITECTURE.md` should carry it.
  - **`Report.timed`** prints each stage. `probe/common.py` also holds `add_layer`, `select` and
    `turned`.
  - **`Registry.guarded` announces each write** through `port.announce`.
  - **For 15, F31's decision has more to weigh:** the probe now has 47 MEASURED lines, the stages
    and the two "selection equal to the allowed polygon" lines among them.
  - **The dead `SILENT_S`** (`probe/saving.py`) is still there for the close's tidying.
- **What the spec said that turned out wrong or harder:** six amendments are in 14's done-note, the
  selection's inset and the order of the probe's first sweep among them.
- **Decisions written down nowhere else:** H2's and H3's outcomes are in 14's done-note, and the H2
  outcome is on the backlog's sensor item. Review 13's §8.7 said Claude Code holds a registration;
  it does not, and `ARCHITECTURE.md` should not repeat that.
- **Baseline** (14, 0.14.0):
  - `verify`: 6 stages, all PASS;
  - 575 server tests passed, 0 skipped;
  - 660 plugin-core tests passed, 0 skipped;
  - `probe`: 129 PASS, 0 FAIL, 47 MEASURED; 112.7 s with 1 document open;
  - 19 registered tools; 19 schema files; instructions 3,901 characters (195 to spare); 30 error
    codes; 32 bridge ops.
- **Not done:**
  - **By hand** (in `docs/BACKLOG.md`): the floating message; N-03 in Activity Monitor; mirror
    painting and wrap-around put back after a stroke; whether a K46 switch visibly moves the tab;
    the overlay in the mask display mode; K46 with the global selection's mask; a layer style
    refusing region scope; a lazy baseline from a file saved with a selection mask active; an
    autosave holding a document during a save; a document closed by hand during a save's finish.
  - **The trial and publishing** are the owner's, after the round.

## Watch for

- **The standing traps:**
  - **Never `git checkout <path>`.** Stage explicit paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it for the project.
  - **The owner's Krita is live.** No session touches their documents. Restart Krita only when
    `doctor` reports 0 unsaved documents, and ask the owner first. `osascript` quitting Krita reports
    "User canceled" yet Krita quits: wait for the process to go, then a few seconds more, because
    `open` straight after fails with -600.
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it
    (`--message`), commit with `git commit -F`, delete the draft.
- **Another agent now works in Krita.** The Codex agent paints the owner's art through this server.
  Ask the owner before any probe run: a dialog it raises refuses every call until it closes, and
  fails what the run overlaps. Done-notes record what was measured, never its work or its documents.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor`
  step 5 passes. That includes the version bump, which changes the plugin's hash, so bump before
  the first live run. **`serve` refuses a plugin of another version:** a stale plugin fails every
  tool with `PROTOCOL_MISMATCH` until Krita restarts.
- **A release restarts the MCP client too.** 0.15.0 stops the Codex agent's `serve` until its client
  restarts, so tell the owner before the restart.
- **Registration in Codex is in place:** `~/.codex/config.toml` has the server, and the owner gave
  the ChatGPT app access to the repository's folder. Run its tests in a new chat, not one doing art.
- **Before the probe's paint checks, the stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current
  brush and Krita's preset history. The probe saves and writes back the brush state. A scratchpad
  driver must do the same: `harness.brush_state` read first, from a document in the harness
  folder (a created document has no path, so the read fails), and stop if the read fails.
- **Krita's memory grows across large opens and saves** (2.8 GB after the long save in a probe
  run). Restart it, at 0 unsaved, before measuring.
- **The instructions have 195 characters to spare.**
- **`[0.14.0]`'s link** needs its own commit's hash, so it lands in the review commit.
- **The docs describe what was built, not the plan.** Where they differ, the done-notes win.
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
