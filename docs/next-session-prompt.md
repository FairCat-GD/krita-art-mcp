Read all of `SPEC.md`; `docs/DEVELOPMENT-WORKFLOW.md` (*Rounds*, step 5, and the `ARCHITECTURE.md`
and between-rounds templates); every done-note and REVIEW file; `CLAUDE.md`; your block (15) in
docs/spec/SESSIONS.md; then this file. Do Session 15: the documentation pass and the round's close.
15 has these parts:
- `docs/ARCHITECTURE.md`, from the template, with the baseline table;
- `docs/USER-GUIDE.md`;
- a truthful README, and `CLAUDE.md` repointed with the as-built paragraph;
- `docs/BACKLOG.md`: everything still open;
- review 13's amendments: F4, F11, F23, F25, F27, F31, F34, §8.8 items 10 and 11;
- the release commit, then a separate `docs: close round 1` commit.

Release 0.16.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 14a are done. 15 (0.16.0, the close) remains.
- **The push status.** `origin` is the private GitHub repository. `origin/main` holds everything
  through 14a's "review: a repeated mistake hid other problems, and 7 smaller". List
  `origin/main..HEAD` before any push.
- **What 14 and 14a left that 15 builds on:**
  - **`probe/acceptance.py`** holds the six exercises, inside `painting.run`'s brush-state window.
  - **`probe/writes.py`** is N-04: `places`, `take`, `strays`. Its limit is in 14's done-note, and
    `ARCHITECTURE.md` should carry it.
  - **`Report.timed`** prints each stage. `probe/common.py` also holds `add_layer`, `select` and
    `turned`.
  - **`Handle.before_change` announces each change** through `port.announce`.
  - **For F31's decision:** the probe has 47 MEASURED lines, the stages and the two "selection equal
    to the allowed polygon" lines among them.
  - **The dead `SILENT_S`** (`probe/saving.py`) is still there for the close's tidying.
- **For `ARCHITECTURE.md`, from 14a's done-note:**
  - **Which forms reach Codex.** It shows its model a TypeScript declaration, never the schema.
    `tests/test_schemas.py` holds the forms: no `allOf`, no `prefixItems`, no `items: false`, a union
    with nothing beside it, and each branch typed. Add this to the deliberate decisions.
  - **Codex's limits:** 5,000 bytes for a normalised input, 16,000 for a rendered one.
  - **The semantic checks stop at their first refusal,** and the note says why.
  - **"Field absent" is `{"not": {}}`,** because a bare `false` loses the error's path.
  - **`MAX_REPORTED_PROBLEMS` is 50,** because of C4, and fields take turns over the cap.
  - **A conditional sits under `dependentSchemas`** on the field it reads, because an `if` passes on
    an absent field and adds a false problem.
- **What the spec said that turned out wrong or harder:** seven amendments are in 14's done-note,
  and five are in 14a's.
- **Decisions written down nowhere else:** H2's and H3's outcomes are in 14's done-note, and the H2
  outcome is on the backlog's sensor item. Review 13's §8.7 said Claude Code holds a registration;
  it does not, and `ARCHITECTURE.md` should not repeat that.
- **Baseline** (14a, 0.15.0):
  - `verify`: 6 stages, all PASS;
  - 669 server tests passed, 0 skipped;
  - 665 plugin-core tests passed, 0 skipped;
  - `probe`: 130 PASS, 0 FAIL, 47 MEASURED; 115.0 s with 1 document open;
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
- **A release restarts the MCP client too.** 0.16.0 stops the Codex agent's `serve` until its client
  restarts, so tell the owner before the restart.
- **Registration in Codex is in place:** `~/.codex/config.toml` has the server, and the owner gave
  the ChatGPT app access to the repository's folder. Run its tests in a new chat, not one doing art.
- **Its rollouts answer what its model saw:** `~/.codex/sessions/`. Read only the tool declarations
  and calls.
- **Before the probe's paint checks, the stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current
  brush and Krita's preset history. The probe saves and writes back the brush state. A scratchpad
  driver must do the same: `harness.brush_state` read first, from a document in the harness
  folder (a created document has no path, so the read fails), and stop if the read fails.
- **Krita's memory grows across large opens and saves** (2.8 GB after the long save in a probe
  run). Restart it, at 0 unsaved, before measuring.
- **The instructions have 195 characters to spare.**
- **The docs describe what was built, not the plan.** Where they differ, the done-notes win.
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
