Read all of docs/spec/SPEC.md, docs/spec/PDD.md (Parts 4, 6 and 8), CLAUDE.md, then this file.
Then do Session 6 of docs/spec/SESSIONS.md: the architecture review after the *observe*
milestone. It changes no product code and cuts no version. It reads the code and tests of sessions
1–5 cold against SPEC.md and writes `docs/spec/REVIEW-<date>.md`: numbered findings, each with
evidence (`file:line` or a measurement), a severity and a proposed remedy. In plan mode, the owner
picks which findings become scope: an amendment to a later block, or an inserted fix session
(later versions then shift). Commit: `docs: architecture review — observe, findings only`.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 5 are done; 6 to 15 remain, and 6, 10 and 13
  are architecture reviews.
- **The push status.** `origin` is the private GitHub repository `FairCat-GD/krita-art-mcp`.
  `origin/main` holds everything through `review: a failed open never strands a document, and
  8 smaller`. Session 5's commits are local until the owner approves a push. List
  `origin/main..HEAD` before any push.
- **What exists after Session 5** (the done-notes of sessions 1–5 hold the detail):
  - **11 tools:** server_info, document list/open/create/inspect/close, operation get/cancel,
    resource_list, capture, sample.
  - **The plugin's ops:** `server_info`, `document.*`, `capture.read`, `sample.read`,
    `resource.list`, `harness.export_kra`, `harness.select_mask`, `harness.front_document`,
    `bridge.unsaved_documents`, `probe.undo_action`, `probe.preset_digests`.
  - **Server modules:** `tools/{documents,observe,operations,pixels,dispatch}.py`, `colour.py`,
    `imaging.py`, `transfer.py`, `baselines.py`, `journal.py`, `roots.py`, `paths.py`,
    `bridge_client.py`, `probe/{__init__,opening,pixels,fixtures,report}.py`.
  - **Plugin core:** `bridge_core/{bridge,jobs,server,registry,documents,opening,inspection,
    pixels,resources,harness,transfer,roots,files,port,...}.py`; the adapter in
    `krita_adapter/{documents,resources,ops,extension,...}.py`.
- **Things a review should look at, found by Session 5:**
  - **Resolvers.** `resolve_open`, `resolve_inspect`, `resolve_capture`, `resolve_sample` and
    `resolve_close` each turn a bridge outcome into a receipt's data, with three different
    idempotence stories (baseline id, retryable re-read, files named by operation id).
  - **Transfer files after a failed resolve.** A resolver that fails without a retry leaves its
    transfer file to the plugin's one-hour expiry (`STALE_S`).
  - **K46 on reads.** The guard is kept, but with marching ants an active selection mask changed
    no composite byte, so the probe measures the overlay rather than checking it. The switch
    itself (`View.setVisible`, then putting the previous view back) is checked live.
  - **Preset fingerprints are canonical XML.** The raw `toXML()` digest changed across a Krita
    restart; Session 9's `preset_sha256` check must use `bridge_core.resources.fingerprint`.
  - **The test world** lives in `tests/support/worlds.py` (3.12 only); `tests/fixtures` stays
    3.10-valid.
- **Baseline** (the review records these as found):
  - `verify`: 6 stages, all PASS;
  - 330 server tests passed, 0 skipped;
  - 246 plugin-core tests passed, 0 skipped;
  - `probe`: 55 PASS, 0 FAIL, 15 MEASURED;
  - 11 registered tools.
- **Not done:**
  - **The owner's roots.** `doctor` step 6 FAILs with "no roots" until the owner runs `roots add`.
    No session runs it, and the probe needs no roots.
  - **By hand** (in `docs/BACKLOG.md`): N-03 in Activity Monitor; whether a K46 switch visibly
    moves the tab; the overlay in the mask display mode.

## Watch for

- **A review is evidence, not scope.** Change no code, not even an obvious fix; write it down.
- **Measure, don't infer.** Timings, leaks and leftovers are measured: list the data directory's
  `transfer/`, `harness/`, `captures/` and `baselines/` before and after a probe run.
- **The standing traps:**
  - **Never `git checkout <path>`.** Stage explicit paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it.
  - **The owner's Krita is live, with their documents open.** No session touches them. Restart
    Krita only when `doctor` reports 0 unsaved documents; otherwise ask the owner (decision 21).
    The owner may have another agent working in Krita, so ask before assuming a restart is safe.
  - **Nothing private in any file or commit message** (`CLAUDE.md`). Never record the names of the
    owner's documents, presets or roots.
- **Running the probe.** `uv run krita-art-mcp probe` needs the installed plugin to match the repo
  (`doctor` step 5). It prints one expected warning, "the baseline … was not kept", from server-b
  deduplicating an open whose transfer file server-a already took.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
