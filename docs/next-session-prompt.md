Read `SPEC.md` §1 (decisions 27, 29), §5 (invariant 2); `PDD.md` Part 4 (`krita_document_save`),
Part 6 (*Formats*), Part 8 (K14, K39, K45, K46), Part 12 (H4); CLAUDE.md; your block (12) in
docs/spec/SESSIONS.md and block 11's done-note; then this file. Do Session 12:
`krita_document_save`, verified by reopening, with H4's long save.

Release 0.12.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 11 are done, 6a, 7a and 10a included. 12 to 15
  remain, releasing 0.12.0 to 0.14.0.
- **The push status.** `origin` is the private GitHub repository. `origin/main` holds
  everything through 11's review commit ("review: a bad baseline file is read anew, and 9
  smaller"), pushed with the owner's approval; nothing is local. List `origin/main..HEAD` before
  any push.
- **What 11 left that 12 builds on:**
  - **Reopening a file inside a job works.** `previews._as_opened` opens a working copy's file a
    second time with `port.open` (batch mode, no view), reads it, and closes it in the same job
    through `registry.discard`. A file Krita keeps open is registered owned, read-only and
    unsafe, and the op fails naming it.
    - Measured live on Krita 5.3.4.1: a second open of an open file is allowed, and nothing is
      left in `documents()`.
    - The save's verify-by-reopen can follow the same path.
    - The probe's fixtures never save a KRA with a selection mask active; that case is in the
      backlog's *Not yet checked by hand*.
  - **The baseline is lazy.**
    - The open mints `baseline_id` and writes nothing.
    - The first `krita_preview_render` that names it reads it from the file, after checking the
      file still hashes to `source_sha256`. That holds because no save overwrites the working
      copy: `document_save` must keep it so.
    - `baseline_untouched` at close still hashes the source.
  - **`pixels.read_rects`, `check_read_space`, `check_target` and `inside`** are module-level in
    `bridge_core/pixels.py`, shared by capture, sample and the preview.
  - **`imaging.background`, `imaging.lightness` and `imaging.artifact`** are public;
    `sheets.py` and the capture and preview receipts use them.
  - **`probe.report.sheet_cell`** crops one cell out of a sheet's PNG, for probe checks.
  - **A kept baseline that cannot be read** is removed by the render that finds it, so the next
    render reads it from the file again.
  - **`FakePort.open` adds no view;** only `show` brings a document to the front, as Krita does
    (K6).
- **Measured in 11, for `ARCHITECTURE.md` at session 15** (details in 11's done-note):
  - N-02: the first render, which reads the baseline, 0.74 s; p95 of 20 after it 0.32 s.
  - Opening the 8192² N-09 master takes 0.5 s without the baseline write (4.7–5.2 s before).
- **Decisions written down nowhere else:** none beyond 11's done-note.
- **Baseline** (11 after its review; 12 moves these only by what it adds):
  - `verify`: 6 stages, all PASS;
  - 528 server tests passed, 0 skipped;
  - 587 plugin-core tests passed, 0 skipped;
  - `probe`: 101 PASS, 0 FAIL, 33 MEASURED, 79.3 s;
  - 18 registered tools; 19 schema files; instructions 3,351 characters (session 14 finalises
    them under 4,096).
- **Not done:**
  - **The owner's roots.** `doctor` step 6 FAILs with "no roots" until the owner runs
    `roots add`. No session runs it, and the probe needs no roots.
  - **By hand** (in `docs/BACKLOG.md`): N-03 in Activity Monitor; mirror painting and
    wrap-around put back after a stroke; whether a K46 switch visibly moves the tab; the overlay
    in the mask display mode; K46 with the global selection's mask; a layer style refusing
    region scope; a lazy baseline from a file saved with a selection mask active.
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
  step 5 passes. That includes the version bump, which changes the plugin's hash, so bump before
  the first live run. A probe-only change runs against the installed plugin, since its hash is
  unchanged.
- **Before the probe's paint checks, the stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current
  brush and Krita's preset history. The probe saves and writes back the brush state; a
  scratchpad driver must do the same (`harness.brush_state` read first, written back after).
- **A save never overwrites the working copy.** The lazy baseline is read from that file;
  `exportImage` to a new path keeps it (K39).
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
