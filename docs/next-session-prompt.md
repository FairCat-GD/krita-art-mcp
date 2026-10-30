Read `REVIEW-2026-10-30.md` §3 (the findings block 13a names), §6 and §8.3; `SPEC.md` §4, §5
(invariants 6, 9, 11), decision 23 with its note; `PDD.md` Part 8 (*Bridge protocol*, K12, K45);
`CLAUDE.md`; your block (13a) in docs/spec/SESSIONS.md and block 13's done-note; then this file.
Do Session 13a: the review fixes after the every-tool-built milestone. 13a has these parts:
- `serve` refuses a plugin of another version, and `ephemeral` becomes a required call field
  (F1, F10);
- the wait-before-read scan covers the three read names (F2);
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
  through 13's review-fixes commit ("review: the scan remedy would have flagged the allowed
  write, and 6 smaller"), pushed with the owner's approval; nothing is local. List
  `origin/main..HEAD` before any push.
- **What 13 found that 13a builds on:** block 13a holds every item with its `file:line` pointer,
  and the REVIEW's §3 the evidence; both point at `f61c7f2`, which is still the code. Beyond
  the block:
  - **`doctor` already turns a `PROTOCOL_MISMATCH` health into step 5** (`doctor.py:38-48`),
    reading the protocol numbers from the error's details; the probe's first check
    (`probe/__init__.py:68-71`) treats any failed health as "no bridge" and must learn the
    mismatch too.
  - **The test fixtures write `plugin_version: "0.2.0"`** (`tests/test_bridge_client.py:203-218`)
    and list `bridge.json`'s keys (`test_bridge_lifecycle.py:40-52`); the test world in
    `tests/support/worlds.py` runs a real `Bridge`, whose version is the package's.
  - **`FakeResources.asked`** (`tests/fixtures/fake_krita.py:919, 927-929`) counts the
    `preset_xmls` calls a stroke makes, so F7's new count can be held by a test.
  - **`harness.retention` needs the `Jobs` object,** which only `Bridge` holds
    (`bridge_core/bridge.py:47, 59-61`); it may stay in `bridge.py` under its new name.
  - **`Pending.stat` and `_stat`** (`bridge_core/saving.py:70, 163, 536-541`) are the
    inode-size-mtime pattern F9 reuses at the open (`opening.py:119-124`).
  - **The hash's cold cost is unmeasured:** the REVIEW's 0.07 s per 200 MB is a warm floor on
    CPython 3.12; 13a measures the cold case once inside Krita before changing the hash.
- **What the spec said that turned out wrong or harder:** nothing new in 13; the handoff's
  earlier notes (H4's 5 s save, ORA's opacity drift, decision 29's cases seen live) stand.
- **Decisions written down nowhere else:** the owner's choice of landings is in the REVIEW's §6
  and block 13's done-note; the protocol choice is decision 23's note, with a pointer in §4.
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
- **The wait scan must never match `setPixelData`.** Its one allowed site writes a selection
  without a wait; the scan names the three read names, not a suffix.
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
