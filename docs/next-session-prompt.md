Read `REVIEW-2026-10-30.md` §3 (the findings block 13a names), §6 and §8.3; `SPEC.md` §4, §5
(invariants 6, 9, 11), decision 23 with its note; `PDD.md` Part 8 (*Bridge protocol*, K12, K45);
`CLAUDE.md`; your block (13a) in docs/spec/SESSIONS.md and block 13's done-note; then this file.
Do Session 13a: the review fixes after the every-tool-built milestone. 13a has these parts:
- `serve` refuses a plugin of another version, and `ephemeral` becomes a required call field
  (F1, F10);
- the wait-before-read scan covers every `…PixelData` name (F2);
- inspect counts its selection in the plugin, with no transfer file (F3);
- `baseline_untouched` by stat first, a hash only when the stat moved (F9);
- no hidden save file is left on the finish's stat-mismatch path or when the owner closes the
  document by hand mid-finish (F17);
- one harness namespace: `probe.preset_xml` goes, the two measurements move under `harness.*`
  (F6);
- one preset lookup and one `toXML` per stroke, one tree per update phase (F7);
- the probe's shared helpers in one public home (F5);
- the small ones: the single-point branch, two dead parameters, the duplicated rect and integer
  helpers, the second validator, the double serialisations (F12, F13, F20, F21, F22);
- four cross-side copies pinned (F18);
- the lines: the probe's measured names, README's save line, the `[0.12.0]` link, the
  open-document count beside the probe's time (F14, F15, F16, F34).

Release 0.13.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 13 are done, 6a, 7a and 10a included. 13a, 14
  and 15 remain: 13a (0.13.0), 14 (0.14.0) and 15 (0.15.0, the round's close). Review 13 inserted
  13a on 2026-10-30, so 14 and 15 moved from 0.13.0–0.14.0.
- **The push status.** `origin` is the private GitHub repository. `origin/main` holds everything
  through 12's review commit ("review: a poll of a failed save tells its own outcome, and 8
  smaller"). Session 13's commit and its review commit are local, not pushed. List
  `origin/main..HEAD` before any push.
- **What 13 found that 13a builds on** (every pointer in `REVIEW-2026-10-30.md` is to `f61c7f2`,
  which is still the code):
  - **`bridge_client._open`** (`src/krita_art_mcp/bridge_client.py:263-279`) reads only `pid`,
    `protocol`, `port`, `token`, `session_id` and `ephemeral_reads`; `plugin_version` and
    `plugin_hash` are in `bridge.json` already (`bridge_core/bridge.py:93-110`). `doctor` already
    turns a `PROTOCOL_MISMATCH` health into step 5 (`doctor.py:38-48`); the probe's first check
    (`probe/__init__.py:68-71`) does not, and must.
  - **`ephemeral`** is optional on the bridge (`bridge_core/server.py:20-22, 204-211`) and sent
    only when `bridge.ephemeral_reads` (`bridge_client.py:145-147`); the test world writes
    `bridge.json` without the flag (`tests/test_bridge_client.py:203-218`), and
    `test_bridge_lifecycle.py:40-52` lists the file's keys.
  - **The wait scan** is `tests/plugin/test_source_scans.py:213-229`, matching the names
    `pixelData` and `waitForDone`; the one `projectionPixelData` read is
    `krita_adapter/documents.py:368`, waited for at `:365`.
  - **Inspect's selection** crosses as an `A8` transfer file (`bridge_core/inspection.py:119-130`)
    that `tools/documents.resolve_inspect` (`:164-186`) counts and deletes; `selection.set`
    counts in the plugin at `selections.py:99-103` (`selected_pixels = len(pixels) -
    pixels.count(0)`; coverage is `sum / 255`). The output schema's `selection` object is
    `{bounds_px, selected_pixels, coverage_px}` and stays.
  - **`baseline_untouched`** is `files.unchanged(source_path, source_sha256)` at
    `bridge_core/saving.py:130-132` and `documents.py:69-70`; `Pending.stat` and `_stat`
    (`saving.py:70, 163, 536-541`) are the inode-size-mtime pattern to reuse; the open sets the
    handle's fields at `opening.py:119-124`.
  - **The hidden save file's two leaks:** `saving.py:161-165` (the stat-mismatch branch returns
    without `_remove`/`_unmake`) and `registry.py:117-120` (`sync` drops a handle and its
    `Pending`).
  - **The `probe.*` ops:** `krita_adapter/ops.py:21-47` (two of them) and `bridge.py:47, 59-61`
    (`probe.retention`); their callers are `probe/pixels.py:318` and `probe/painting.py:962`.
    `harness.*` handlers live in `bridge_core/harness.py`; the retention op needs the `Jobs`
    object, which only `Bridge` holds, so it may stay in `bridge.py` under its new name.
  - **The stroke's preset work:** `bridge_core/painting.py:67-68` (`_preset`, `_listed`), `:80`
    (`set_brush`, whose adapter reads the brush back with a `toXML`), `:82`, `:124`;
    `FakeResources.asked` (`tests/fixtures/fake_krita.py:919, 927-929`) counts the `preset_xmls`
    calls, so the tests can hold the new count. `layer_update`'s tree reads: `layer_update.py:40,
    80, 117` and `:131, 135` inside `_blend`.
  - **The probe's copies:** `probe/painting.py:231-250`, `probe/changes.py:75-104`,
    `probe/previews.py:213-226` (captures); `probe/updates.py:65-71` and `probe/saving.py:92-97`
    (`_dirty`); `probe/saving.py:100-103` (`_layers`) against `probe/changes.py:107-110`;
    `_open` at `probe/updates.py:56-62`, `probe/previews.py:81-84`, `probe/painting.py:209-211`;
    `probe/changes.py:158-161` (`_png`) against `fixtures.py:253-254`; `probe/opening.py:41-42`
    (`sha`); the private imports at `probe/saving.py:19-27`.
  - **The small ones:** `strokes.py:10-11`; `masks.py:46` and `envelope.py:50`; `saving.py:368-376`
    against `verification.py:308-317`, `pixels.py:148, 161-166` against `masks.py:41-53` and
    `painting.py:457`; `tools/__init__.py:97-99` against `operations.py:145-151`;
    `tools/__init__.py:168` and `bridge_client.py:149, 286`.
  - **The copies to pin:** `probe/saving.py:34-47` against `bridge_core/saving.py:23-39`;
    `bridge_core/saving.py:21` against `colour.py:17`; `tools/saving.py:17` against
    `bridge_core/saving.py:18`; `probe/pixels.py:23`. The constants test is
    `tests/test_envelope.py:68-85`.
  - **The lines:** `probe/painting.py:965, 982`; `README.md:45`; `CHANGELOG.md:488` (the
    references stop at `[0.11.0]`; 0.12.0's manifest bump is `7d18a6a`); `probe/report.py:32-37`
    prints the summary, and `bridge.unsaved_documents` answers `{open, unsaved}`.
- **What the spec said that turned out wrong or harder:** nothing new in 13; the handoff's
  earlier notes (H4's 5 s save, ORA's opacity drift, decision 29's cases seen live) stand.
- **Decisions written down nowhere else:** the owner's choice of landings is in the REVIEW's §6
  and block 13's done-note; the protocol choice is decision 23's note.
- **Baseline** (13 as found; 13a changes code, so the test counts move by what it adds and the
  probe gains one line):
  - `verify`: 6 stages, all PASS;
  - 549 server tests passed, 0 skipped;
  - 636 plugin-core tests passed, 0 skipped;
  - `probe`: 113 PASS, 0 FAIL, 34 MEASURED; 95.6 s on an empty Krita, 145.6 s with 87 documents
    open (document ops about three times slower, the benchmarks unmoved);
  - 19 registered tools; 19 schema files; instructions 3,524 characters (session 14 finalises
    them under 4,096 with 572 to spare); 30 error codes; 33 bridge ops (32 after 13a).
- **Not done:**
  - **The owner's roots.** `doctor` step 6 FAILs with "no roots" until the owner runs
    `roots add`. No session runs it, and the probe needs no roots.
  - **By hand** (in `docs/BACKLOG.md`): N-03 in Activity Monitor; mirror painting and
    wrap-around put back after a stroke; whether a K46 switch visibly moves the tab; the overlay
    in the mask display mode; K46 with the global selection's mask; a layer style refusing
    region scope; a lazy baseline from a file saved with a selection mask active; an autosave
    holding a document during a save.
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
    `osascript` quitting Krita reports "User canceled" yet Krita quits: wait for the process to go.
    On 2026-10-30 it held 87 open documents, none unsaved.
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it
    (`--message`), commit with `git commit -F`, delete the draft.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor`
  step 5 passes. That includes the version bump, which changes the plugin's hash, so bump before
  the first live run. From 13a, `serve` refuses a plugin of another version too, so a stale
  plugin fails every tool with `PROTOCOL_MISMATCH` until Krita restarts.
- **The version check meets the probe first.** The probe's "the bridge answers its health check"
  goes through `_open`; make it report a `PROTOCOL_MISMATCH` the way `doctor` step 5 does (the
  install fix), or the first live run after the bump reads as a dead bridge.
- **Before the probe's paint checks, the stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current
  brush and Krita's preset history. The probe saves and writes back the brush state. A scratchpad
  driver must do the same: `harness.brush_state` read first, from a document in the harness
  folder (a created document has no path, so the read fails), and stop if the read fails.
- **If Krita dies silently about 5 s into a call,** suspect a socket before Krita: a client that
  gives up closes its connection, and only `SO_NOSIGPIPE` keeps the bridge's reply from killing
  Krita.
- **Krita's memory grows across large opens and saves** (2.5 GB after a probe run). Restart it,
  at 0 unsaved, before measuring.
- **A save never overwrites the working copy.** The lazy baseline is read from that file; the save
  writes only beside its own path.
- **A review fix must not loosen a refusal.** F3 changes who counts, F9 when the hash runs; what
  inspect reports and what a changed source answers stay the same.
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
