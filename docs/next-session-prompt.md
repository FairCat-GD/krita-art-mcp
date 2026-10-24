Read docs/spec/SPEC.md §5 (invariants 6, 9, 12, 13), docs/spec/REVIEW-2026-10-24.md (§3 and
§5), docs/spec/PDD.md Part 8 (*Bridge protocol*, K41, K48), CLAUDE.md, then this file. Then do
Session 6a of docs/spec/SESSIONS.md: the review fixes after the *observe* milestone, one item
per finding of review 6. Release 0.6.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 6 are done; 6a and 7 to 15 remain. Review 6
  inserted 6a on 2026-10-24, so sessions 7–15 now release 0.7.0–0.13.0 (the table in
  `SESSIONS.md` is updated; each block's Docs line says so).
- **The push status.** `origin` is the private GitHub repository `FairCat-GD/krita-art-mcp`.
  `origin/main` holds everything through `review: failed resolves discard their pixels, and 9
  smaller` (`d5af786`). Session 6's commits (`docs: architecture review — observe, findings
  only`, and its review commit) are local. List `origin/main..HEAD` before any push.
- **What 6a fixes, by finding** (the pointers in block 6a are to `d5af786`, which is HEAD's
  code):
  - **F24** `bridge_client._follow`: the 404 grace runs for the whole budget and `operation()`
    on an id in `_sent` is never strict, so a lost POST is `running` for ever. Bound the grace;
    keep `test_a_poll_waits_for_a_call_the_bridge_has_not_registered_yet` passing.
  - **F7** `Jobs.cancel` keeps the request id bound and is non-retryable; `stop()` releases and is
    retryable. Make them one rule, on both sides (`errors.py` `CANCELLED` default).
  - **F11** a non-JSON handler result raises in the HTTP handler and loops the client; serialise
    once in `Jobs._run`.
  - **F27** `Waker._run` and `Jobs._run` catch `Exception` only.
  - **F9** `KritaDocuments.selection()` has no `waitForDone()`.
  - **F6** `ops.undo_action` uses `activeWindow()` and `showView`; ask the owner at the start:
    retire it, or route it through `bring_forward`/`restore_view`.
  - **F12** `_expire` removes `.raw` only; masks stay until the next bridge start.
  - **F8** every tool op needs its `RECEIPTS` entry held by a table or a test.
  - **F19, F26** a server-side blend-mode whitelist, and `MAX_POINTS`, `MAX_RADIUS`, `MAX_LIMIT`
    pinned to the schema limits, in `tests/test_envelope.py`'s constants test.
  - **F15** `roots add` refuses `/`, the home folder and a folder containing the data directory.
  - **F16** the baseline sweep thread runs under `_CALLS`. **F17** `tests/test_tools.py:41`
    points its `BridgeClient` at `tmp_path`.
  - **F14** `harness/` is made 0700 (`probe/__init__.py:51`); `plugin.log` 0600 (`log.py:30`).
  - **F13** the probe's summary prints its wall time; a last check lists `transfer/` (empty) and
    the probe's documents (none open).
  - **F18** the schema amendment tooling is committed (or the shared shapes generated).
  - **F20** `CHANGELOG.md` gets the `[0.5.0]` link reference
    (`5ead34bc4e5624e92165b211d1daa2f66ed95fb1`) beside `[0.6.0]`'s.
- **What exists after Session 5** is unchanged (the done-notes of sessions 1–5 hold the detail):
  11 tools; the plugin's ops `server_info`, `document.*`, `capture.read`, `sample.read`,
  `resource.list`, `harness.*`, `bridge.unsaved_documents`, `probe.*`; the server modules
  `tools/{documents,observe,operations,pixels,dispatch}.py`, `bridge_client.py`, `journal.py`,
  `probe/`; the plugin core `bridge_core/` and the adapter `krita_adapter/`; the test world in
  `tests/support/worlds.py` (3.12 only), `tests/fixtures` 3.10-valid.
- **Baseline** (as review 6 found it; 6a moves only what its tests add):
  - `verify`: 6 stages, all PASS;
  - 334 server tests passed, 0 skipped;
  - 249 plugin-core tests passed, 0 skipped;
  - `probe`: 55 PASS, 0 FAIL, 15 MEASURED, 13.5 s wall time;
  - 11 registered tools; 19 schema files; instructions 2,773 characters.
- **Not done:**
  - **The owner's roots.** `doctor` step 6 FAILs with "no roots" until the owner runs
    `roots add`. No session runs it, and the probe needs no roots.
  - **By hand** (in `docs/BACKLOG.md`): N-03 in Activity Monitor; whether a K46 switch visibly
    moves the tab; the overlay in the mask display mode.

## Watch for

- **The standing traps:**
  - **Never `git checkout <path>`.** Stage explicit paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it.
  - **The owner's Krita is live, with their documents open.** No session touches them. Restart
    Krita only when `doctor` reports 0 unsaved documents; otherwise ask the owner (decision 21).
    The owner may have another agent working in Krita, so ask before assuming a restart is safe.
    Review 6 needed three probe runs: one was gated by an unsaved document, one found Krita
    closed.
  - **Nothing private in any file or commit message** (`CLAUDE.md`). Never record the names of the
    owner's documents, presets or roots.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor`
  step 5 passes; 6a changes `jobs.py`, `transfer.py`, `log.py`, the adapter.
- **The 404 grace has a real case** (a POST stuck behind a long Krita call registers late); the
  bound must keep it.
- **Falsify each new check once;** the review added none, so the whole of 6a's additions are new.
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Running the probe.** `uv run krita-art-mcp probe` needs the installed plugin to match the
  repo (`doctor` step 5). It prints one expected warning, "the baseline … was not kept", from
  server-b deduplicating an open whose transfer file server-a already took.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
