Read all of `SPEC.md`; `PDD.md`; `CLAUDE.md`; `REVIEW` 6 and 10; all the code; your block (13) in
docs/spec/SESSIONS.md and block 12's done-note; then this file. Do Session 13: the architecture
review, every tool built. It writes `docs/spec/REVIEW-<date>.md`: findings only, no product code,
no version. The owner then picks, in plan mode, which findings become scope.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 12 are done, 6a, 7a and 10a included. 13 to 15
  remain: 13 (this review, no version), 14 (0.13.0) and 15 (0.14.0, the round's close).
- **The push status.** `origin` is the private GitHub repository. `origin/main` holds
  everything through 12's review commit ("review: a poll of a failed save tells its own outcome,
  and 8 smaller"), pushed with the owner's approval; nothing is local. List `origin/main..HEAD`
  before any push.
- **What 12 built that 13 reads:**
  - **The save is two plugin ops** (`bridge_core/saving.py`):
    - `document.save` exports to a hidden `.<stem>.<token>.saving<ext>` beside the path,
      reopens it with `reopening.read_file` (shared with the preview's baseline read), compares,
      and keeps a `Pending` save on the handle.
    - The server (`tools/saving.py`) decodes `mergedimage.png` and sends `document.save_finish`
      under `<request_id>:finish` and an operation id derived from the save's, so any poll or
      retry gets the finish's own outcome. The finish links the file into place, or removes it,
      and clears dirt only if `Handle.changes` has not moved.
    - A save refuses canvases over 8192 × 8192, a name too long for its hidden file and a folder
      it cannot write before exporting, and removes any folder it made when it fails.
    - `Known.finish` lets `krita_operation_get` finish a save that came back `running`.
  - **The projection is recomposed (`port.refresh`) before every export:** after a stroke it
    differed from its layers' own composite.
  - **`BridgeHTTPServer.get_request` sets `SO_NOSIGPIPE`.** A reply to a client that had given
    up used to kill Krita. That bug dates from session 2, and H4 found it.
  - **Smaller seams:**
    - `BridgeClient.call(budget_s=…)`, so the finish shares the save's 45 s;
    - `BridgeClient.health(timeout_s=…)`;
    - `tools.painting.stroke_op`, which the probe uses;
    - `painting.run(…, then)`, which runs `saving.run` inside its brush window.
  - **ORA's rules as measured:** losses for masks and adjustment layers, rasterised types, alpha
    lock, and opacity Krita's ORA writer lowers (`saving.ora_opacity`); a loss never excuses a
    composite difference.
- **What the spec said that turned out wrong or harder:**
  - **H4's "20 s save"** is not what this machine gives: gradient layers save an 8k canvas in
    about 5 s, noise layers in about 12 s, and long saves need not mean long silences. The owner
    kept the 5 s gradient save; the 20 s target is recorded as measured, not met.
  - **Part 6's ORA notes:** inherit-alpha with multiply keeps its blend, and about half of all
    opacities come back one step lower. A blur filter mask's spread is cropped to its layer, so the
    composite fails.
  - **Decision 29's two unit-only cases both happened live:** an unforced `BUSY`, once, and
    "outcome uncertain" each time Krita died mid-call.
- **Decisions written down nowhere else:** none beyond 12's done-note.
- **Baseline** (12 after its review; 13 changes no code, so none of these moves):
  - `verify`: 6 stages, all PASS;
  - 549 server tests passed, 0 skipped;
  - 636 plugin-core tests passed, 0 skipped;
  - `probe`: 113 PASS, 0 FAIL, 34 MEASURED, 95.6 s;
  - 19 registered tools; 19 schema files; instructions 3,524 characters (session 14 finalises
    them under 4,096).
- **Not done:**
  - **The owner's roots.** `doctor` step 6 FAILs with "no roots" until the owner runs
    `roots add`. No session runs it, and the probe needs no roots.
  - **By hand** (in `docs/BACKLOG.md`): N-03 in Activity Monitor; mirror painting and
    wrap-around put back after a stroke; whether a K46 switch visibly moves the tab; the overlay
    in the mask display mode; K46 with the global selection's mask; a layer style refusing
    region scope; a lazy baseline from a file saved with a selection mask active; an autosave
    holding a document during a save.
  - **In the backlog:** sweeping a hidden save file a Krita crash left; SIGPIPE on Linux, where
    `SO_NOSIGPIPE` does not exist.

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
  step 5 passes. That includes the version bump, which changes the plugin's hash, so bump before
  the first live run. A probe-only change runs against the installed plugin, since its hash is
  unchanged.
- **Before the probe's paint checks, the stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current
  brush and Krita's preset history. The probe saves and writes back the brush state. A scratchpad
  driver must do the same: `harness.brush_state` read first, from a document in the harness
  folder (a created document has no path, so the read fails), and stop if the read fails.
- **If Krita dies silently about 5 s into a call,** suspect a socket before Krita: a client that
  gives up closes its connection, and only `SO_NOSIGPIPE` keeps the bridge's reply from killing
  Krita.
- **Krita's memory grows across large opens and saves** (3.6 GB after many 8k runs). Restart it,
  at 0 unsaved, before measuring.
- **A save never overwrites the working copy.** The lazy baseline is read from that file; the save
  writes only beside its own path.
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
