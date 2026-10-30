Read `SPEC.md` §1 (decisions 28, 30, 31), §9; `PDD.md` Part 4 (*Server instructions*), Part 12;
`reference/contract-package/krita-mcp-art-workflow-brief.md` §7; `REVIEW-2026-10-30.md` §5, §8.7
and F4, F8; `CLAUDE.md`; your block (14) in docs/spec/SESSIONS.md and block 13a's done-note; then
this file. Do Session 14: acceptance. 14 has these parts:
- the full harness, every check from sessions 2–12 with timings recorded;
- the contract's six acceptance exercises, as scoped in SPEC §9;
- the H2 preset sheet: six stock presets as shipped, flat strokes, for the owner to judge;
- H3 by hand: the owner registers the server in Codex, and the Codex agent describes a capture of
  a known test pattern;
- the server instructions finalised at or under 4,096 characters, naming the save's
  8192 × 8192 bound (F4);
- N-01's selected-canvas variant, measured and recorded (F8);
- N-04 in the harness, its list of writes from the review's §5 and §8.7;
- F-24, a floating message while a job runs, if time allows.

Ask at the start: which six stock presets the H2 sheet uses. Propose them from
`krita_resource_list`, and the owner confirms.

Release 0.14.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 13a are done, 6a, 7a and 10a included. 14
  (0.14.0) and 15 (0.15.0, the round's close) remain.
- **The push status.** `origin` is the private GitHub repository. `origin/main` holds everything
  through 13a's "review: a blend's moved check reads after the refresh, and 7 smaller". List
  `origin/main..HEAD` before any push.
- **What 13a left that 14 builds on:**
  - **`probe/common.py`** is the one home of the probe's shared helpers, public: `guard`, `close`,
    `by_name`, `history_args`, `harness_call`, `open_args`, `open_working`, `inspect_data`,
    `document_dirty`, `capture`, `capture_composite`, `capture_selection`, `brush_colour`,
    `brush_args`, `stroke_args`, `line_points`, `finished`, `krita_rss_kb`, `megabytes`. The
    acceptance exercises should import from it. `report.py` keeps `tool`, `code`, `differs` and
    `sheet_cell`. `painting.run` calls `saving.run` directly, inside its brush-state window.
  - **`BridgeClient(any_plugin=True)`** is what `doctor` and the probe use, and it skips both the
    version and the protocol check; a default client, `serve`'s, refuses either.
  - **`Report.open_documents`** prints beside the wall time.
  - **`harness.retention` and `harness.preset_digests`** replaced the `probe.*` ops; they take no
    document and no folder gate.
  - **The dead `SILENT_S`** (`probe/saving.py`) was in the review's §8.1 and in no block; it is
    still there for the close's tidying.
- **What the spec said that turned out wrong or harder:** block 13a's gate would have blinded
  `doctor`'s unsaved count on a stale plugin, and its "one `toXML`" contradicted its own "the
  checks stay"; both are amendments in the done-note.
- **Decisions written down nowhere else:** the block's seven amendments are in its done-note; SPEC
  decision 24 has its dated note.
- **Baseline** (13a, 0.13.0):
  - `verify`: 6 stages, all PASS;
  - 553 server tests passed, 0 skipped;
  - 658 plugin-core tests passed, 0 skipped;
  - `probe`: 113 PASS, 0 FAIL, 34 MEASURED; 93.5 s with 0 documents open;
  - 19 registered tools; 19 schema files; instructions 3,524 characters (572 to spare); 30 error
    codes; 32 bridge ops.
- **Not done:**
  - **The owner's roots.** `doctor` step 6 FAILs with "no roots" until the owner runs
    `roots add`. No session runs it, and the probe needs no roots.
  - **By hand** (in `docs/BACKLOG.md`): N-03 in Activity Monitor; mirror painting and
    wrap-around put back after a stroke; whether a K46 switch visibly moves the tab; the overlay
    in the mask display mode; K46 with the global selection's mask; a layer style refusing
    region scope; a lazy baseline from a file saved with a selection mask active; an autosave
    holding a document during a save; a document closed by hand during a save's finish.
  - **In the backlog from review 13:** saving over 8192 × 8192 (banded reads), one validator of
    argument shape or parity tests, schemas that advertise what refuses, one verified-mutation
    frame, a journal retention rule.

## Watch for

- **The standing traps:**
  - **Never `git checkout <path>`.** Stage explicit paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it for the project.
  - **The owner's Krita is live.** No session touches their documents. Restart Krita only when
    `doctor` reports 0 unsaved documents, and ask the owner first; another agent may be working.
    `osascript` quitting Krita reports "User canceled" yet Krita quits: wait for the process to go,
    then a few seconds more, because `open` straight after fails with -600.
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it
    (`--message`), commit with `git commit -F`, delete the draft.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor`
  step 5 passes. That includes the version bump, which changes the plugin's hash, so bump before
  the first live run. **`serve` now refuses a plugin of another version:** a stale plugin fails
  every tool with `PROTOCOL_MISMATCH` until Krita restarts.
- **A release restarts the MCP client too.** A `serve` already running keeps its old version, so
  after a bump it refuses the new plugin until its client restarts. H3 and any Claude Code use of
  the registered server need a fresh client after 0.14.0's install.
- **Before the probe's paint checks, the stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current
  brush and Krita's preset history. The probe saves and writes back the brush state. A scratchpad
  driver must do the same: `harness.brush_state` read first, from a document in the harness
  folder (a created document has no path, so the read fails), and stop if the read fails.
- **If Krita dies silently about 5 s into a call,** suspect a socket before Krita: a client that
  gives up closes its connection, and only `SO_NOSIGPIPE` keeps the bridge's reply from killing
  Krita.
- **Krita's memory grows across large opens and saves** (3.4 GB after the long save in a probe
  run). Restart it, at 0 unsaved, before measuring.
- **The instructions have 572 characters to spare,** and the review's §2.4 names what an agent
  would meet that they do not say: erasing refused, a stroke under half a pixel refused, region
  scope needing the pixel engine, and the save's bound.
- **The acceptance fixtures are fictional.** Never use the first game's art.
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
