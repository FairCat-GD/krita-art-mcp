Read docs/spec/SPEC.md §1 (decisions 5, 26, 27) and §5 (invariants 1, 4, 5), docs/spec/PDD.md
Part 4 (`krita_layer_create`, `krita_selection_set`, `krita_protection_set`,
`krita_history_step`) and Part 8 (K7, K8, K10, K11, K22, K23, K43, K46),
docs/spec/REVIEW-2026-10-24.md (F1, F2, F4, F5, F23, F25), CLAUDE.md, then this file. Then do
Session 7 of docs/spec/SESSIONS.md: preparing a change, with review 6's amendments to its block.
Release 0.7.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 6 and 6a are done; 7 to 15 remain, releasing
  0.7.0 to 0.13.0.
- **The push status.** `origin` is the private GitHub repository `FairCat-GD/krita-art-mcp`.
  `origin/main` holds everything through session 6's review commit, `review: the F24 remedy
  keeps the late-registration case, and 9 smaller`. Session 6a's commit waits for the next approved
  push. List `origin/main..HEAD` before any push.
- **What 6a changed that session 7 builds on** (block 6a's done-note has the detail):
  - **Schemas are amended with `uv run scripts/amend_schemas.py`.** Edit your schema's input, the
    `data` under its output's properties, and its example; the script writes the envelope,
    `guard`, `source`, the completed rule's copy of `data` and inspect's `layers`, and formats the
    files. A test fails if any file is not as the script writes it.
  - **Masks.** The server's `transfer.put_mask` names a mask by its SHA-256 and refreshes one it
    finds; the plugin's `transfer.take_mask(directory, spec)` reads it once and deletes it, and a
    mask that is gone is a retryable `IO_ERROR`. Masks expire from `transfer/` after an hour.
    Because masks are shared by content, two calls sending the same mask race on that delete:
    F23's decision (where the allowed mask's bytes live) should settle mask lifetimes, and
    `take_mask`'s delete-on-read may have to change with it.
  - **Jobs.** A handler returns a JSON-safe dict (stored as a snapshot) or raises `BridgeError`;
    anything else, `BaseException` included, fails its own op as a non-retryable `INTERNAL_ERROR`.
    Retryable still means "changed nothing", and releases the request_id. `CANCELLED` is
    retryable. F25's "dirty before the first mutation" sits on top of this.
  - **The journal.** A no-effect outcome settles only its own attempt; a receipt settles every
    attempt it deduplicated.
  - **The bridge client.** A 404 answered promptly for 2 s (`REGISTER_GRACE_S`) before the bridge
    has said `running` ends a follow with `outcome: "unregistered"` (retryable). F2's bounded
    retention will make a read's operation id 404 once it is dropped; `operation()` on such an id
    then answers `unregistered` after the window, which is right for a read.
  - **The adapter scan** (`tests/plugin/test_source_scans.py`): every adapter function that calls
    `pixelData` calls `waitForDone()` first. `setPixelData` is another name; F1's exception and
    its AST test are this session's.
  - **The probe** prints `probe: N PASS, M FAIL, K MEASURED in S s` and ends its document part
    with a leftover check. It has no undo-label probe any more: build the ledger's label check
    on the agent's own document (session 2's done-note records that the label reads `'Undo '`
    straight after a change, in some reads).
  - **`tools.CALLS`** is the server's call lock (it was `_CALLS`).
- **Baseline** (session 7 moves it only by what it adds):
  - `verify`: 6 stages, all PASS;
  - 360 server tests passed, 0 skipped;
  - 270 plugin-core tests passed, 0 skipped;
  - `probe`: 55 PASS, 0 FAIL, 14 MEASURED, about 12 s;
  - 11 registered tools; 19 schema files; instructions 2,773 characters (F5: this session adds at
    most 300 net, after trimming).
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
    In 6a the owner chose to restart Krita themself; quitting closes their open documents, and
    Krita does not reopen them.
  - **Nothing private in any file or commit message** (`CLAUDE.md`). Never record the names of the
    owner's documents, presets or roots.
- **Block 7's *Ask at the start*** is F23: where the allowed mask's bytes live. Ask it in plan
  mode, before any edit, and settle the mask lifetimes above with it.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor`
  step 5 passes.
- **Falsify each new check once;** a scratchpad driver that breaks one line, runs only the
  guarding test and copies the file back worked well in 6a.
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Running the probe.** `uv run krita-art-mcp probe` needs the installed plugin to match the
  repo (`doctor` step 5). It prints one expected warning, "the baseline … was not kept", from
  server-b deduplicating an open whose transfer file server-a already took.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
