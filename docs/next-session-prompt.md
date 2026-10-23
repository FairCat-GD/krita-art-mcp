Read docs/spec/SPEC.md (§1 decisions 5, 8, 27, 29; §4; §5 invariants 5, 9), docs/spec/PDD.md
(Part 4 *Conventions*: IDs, guard, one writer, request IDs; `krita_document_list`,
`krita_document_create`, `krita_document_close`, `krita_operation_get`/`cancel`; *States & edge
cases*; Part 6 *Entities*; Part 8 *Bridge protocol*, *Plugin internals*, K6, K14, K45), CLAUDE.md,
then this file. Then do Session 3 of docs/spec/SESSIONS.md: operations and the document registry.
Session 3 has five parts:
- **retries and the journal:** journaled before dispatch, the bridge's `request_id` dedup and
  `REQUEST_ID_CONFLICT`, and the uncertain outcome never re-sent;
- **`krita_operation_get` and `krita_operation_cancel`**, with their schemas amended;
- **the plugin's document registry:** ids, strong references and `addView`, mode, the writer
  lease, dirty and unsafe, and the job-start refusals;
- **the tools:** `krita_document_create`, `krita_document_list` and `krita_document_close`, with
  `guard` amended in all 19 schemas;
- **the 20-cycle check** (decision 8).

Release 0.3.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0, 1 and 2 are done; 3–15 remain, and 6, 10 and 13
  are architecture reviews.
- **Session 2 is committed locally, not pushed.** `origin` is the private GitHub repository
  `FairCat-GD/krita-art-mcp`. `origin/main` holds everything through `review: bridge_core never
  reaches Krita, and 9 smaller`. List `origin/main..HEAD` before any push.
- **What Session 2 left that Session 3 builds on:**
  - **The plugin** (`plugin/krita_art_mcp_bridge/`).
    - **`bridge_core/` is pure stdlib.**
      - `jobs.py`: `Jobs`, with one `threading.Condition` around every state change. Operations
        are keyed by the server-minted `operation_id`. A resent `operation_id` returns the same
        operation. It covers `submit`, `drain` (the `job_active` re-entry guard), `wait`,
        `cancel` (queued only) and `stop`. `request_id` and `client` are stored on each
        `Operation` but not yet used: dedup and the lease are Session 3's.
      - `server.py`: the HTTP layer. It checks `Host`, then the token, then 503, then the body.
        Every reply carries `session_id`, `operation_id` and `request_id`. One error body,
        `{code, message, retryable, details}`, serves every refusal. `wait_s` is capped at 10 s.
      - `bridge.py`: `Bridge`. Its `start()` and `stop()` run in the order PDD Part 8 gives. Its
        built-in `server_info` op returns the health snapshot as a job.
      - `bridge_file.py`, `log.py`, `paths.py` (`private_dir`), `capabilities.py`,
        `source_hash.py` and `errors.py` (`CODES`, `BridgeError`, `no_arguments`).
    - **`krita_adapter/`.**
      - `extension.py` (`setup()` and the `applicationClosing` stop).
      - `main_thread.py`: the `Waker` queued signal, and `main_thread_check()`.
      - `runtime.py`: the facts cached at start.
      - `ops.py`: `bridge.unsaved_documents` and `probe.undo_action`. A new op goes in
        `ops.HANDLERS`.
    - **The package `__init__.py`** only registers the extension.
  - **The server** (`src/krita_art_mcp/`).
    - `bridge_client.py`: `BridgeClient.call(op, args, request_id=)` and `.operation(id)` return
      `Done | Failed | Pending`. The bridge is pinned per call. After a send, a lost bridge is
      `INTERNAL_ERROR` with `details.outcome: "uncertain"`. `request_id` defaults to a minted
      `req-…`, and `client` is `{pid, started_at}` (`ps lstart`).
    - `tools/__init__.py`: `TOOLS` and `BUILT_TOOLS`, `build()`, `ExactArguments`, and the runner.
      The runner holds the call lock, validates the arguments, catches everything, and checks
      each result against its schema and 6 MiB. A new tool is one entry in `TOOLS` and a module
      function `(client, arguments) -> CallToolResult`.
    - `envelope.py`: `completed`, `pending`, `failed` and `failure`.
    - `errors.py`: `PROTOCOL`, `API_VERSION` and `CODES` (with hints).
    - Also `setup_checks.py`, `doctor.py`, `install.py`, `plugin_files.py`, `processes.py`,
      `paths.py` and `instructions.py`.
    - `probe/__init__.py`: `Report` and `run()`. A new live check is a function called from
      `_probe`.
  - **The schemas.**
    - The envelope is amended in all 19 schemas: `api_version` `"0.2.0"`, `revision` null, the
      `error.code` enum, and `failed`/`cancelled` carrying an error and null data.
    - `krita_server_info` is fully amended. The other 18 keep their tool-specific parts
      unamended.
    - `guard` is Session 3's shared shape.
  - **The live setup.** The plugin is installed and enabled in the owner's Krita 5.3.4. The data
    dir `~/Library/Application Support/krita-art-mcp/` exists (0700) with `bridge.json`, `logs/`
    and `harness/`.
- **What the spec said that turned out wrong or harder:**
  - **`Krita.instance().version()` is `"5.3.4.1 (git bd6e8d0)"`,** not a bare version. The
    schema takes any non-empty string.
  - **`osascript -e 'tell application "krita" to quit'` reports "User canceled (-128)"** even
    when Krita quits cleanly: Krita exits before it replies. Check `pgrep -x krita`, not the
    exit code.
  - **A directory created as a parent gets 0755.** The plugin's `paths.private_dir` makes the
    data dir 0700 even when the log created it first.
  - **`doctor` must report the unsaved count when an earlier step fails.** The restart check is
    needed exactly when the plugin is stale.
  - **Krita's bundled `python3.13` cannot run on its own** (its `Python.app` stub is not
    shipped). The live probe is the only check in Krita's runtime.
  - **`edit_undo`'s text is `Undo <top label>`, but it updates asynchronously.**
    - Read straight after `waitForDone()`, it was stale (`"Undo "`) in 2 of 7 reads, whether or
      not Krita was frontmost.
    - Block 9's "rollback … with its label checked" cannot read it straight after the step.
    - Carry this forward until Session 9 designs that check. The measurements are in Session 2's
      done-note.
- **Decisions written down nowhere else** (deliberate, for ARCHITECTURE):
  - **`krita_server_info` runs as a main-thread job,** so its answer proves the main thread is
    free. `/v1/health` is cached and answered on the HTTP thread alone.
  - **The restart check is an op** (`bridge.unsaved_documents`) printed by `doctor`, not part of
    health. Health is cached, and a document's modified flag needs the main thread.
  - **The capability matrix lives in `bridge_core.capabilities`,** and the tool relays it.
    `allowed_roots` joins `krita_server_info` with roots in Session 4.
  - **Protocol 1's fields are fixed.**
    - `request_id`, `client`, every reply's `session_id` and the uniform error body are there
      for Session 3; the lease and dedup need no new protocol.
    - Session 3 decides how long finished operations are kept: today the map only grows, per
      Krita session.
  - **`doctor` and the not-running hint share `setup_checks`.** `KRITA_NOT_RUNNING` names the
    first failing local step in `details.{step, detail, fix}`.
- **Restarting Krita.** The bridge answers now, so a session restarts Krita itself when
  `uv run krita-art-mcp doctor` ends with `0 unsaved`:
  1. run `uv run krita-art-mcp install-plugin`;
  2. quit Krita with `osascript -e 'tell application "krita" to quit'`;
  3. wait until `pgrep -x krita` finds nothing;
  4. run `open -a krita`;
  5. wait for `bridge.json`;
  6. run `doctor` again.

  With any unsaved document, ask the owner (decision 21).
- **Baseline:**
  - `verify`: 6 stages, all PASS;
  - 120 server tests passed, 0 skipped;
  - 85 plugin-core tests passed, 0 skipped;
  - `probe`: 10 PASS, 0 FAIL, plus 3 MEASURED.
- **Not done:** the owner's own look at N-03 in Activity Monitor (`top` measured 0.0%; it is in
  `docs/BACKLOG.md`).

## Watch for

- **The standing traps:**
  - **Never `git checkout <path>`.** Falsify by copying the file aside and back.
  - **Stage explicit paths.**
  - **Give stdin-reading commands `< /dev/null`.** A bare `cat > file` with no heredoc hangs.
  - **The Python toolchain.**
    - uv is at `~/.local/bin/uv` (0.12.3), and CPython 3.12.13 is uv-managed.
    - CPython 3.10.20 is uv-managed too, for `plugin-tests`.
    - `/usr/bin/python3` is 3.9.6: never use it.
  - **`docs/spec/reference/` holds Python scripts and JSON.** Keep `docs/` out of ruff, mypy and
    pytest collection.
  - **The owner's Krita is live, with their documents open.** No session touches them, and none
    restarts Krita while a document has unsaved changes.
  - **Nothing private in any file or commit message** (`CLAUDE.md`, *This repository is public*).
- **The plugin's import root.**
  - Tests see `bridge_core` as a top-level package through `plugin/krita_art_mcp_bridge` on
    `pythonpath`. Keep `bridge_core`'s own imports relative, and never import the
    package-qualified name in a test: its `__init__.py` imports Krita.
  - mypy's 3.10 run checks `-p krita_art_mcp_bridge`, with `plugin` on `mypy_path`.
    - `krita` and PyQt are `ignore_missing_imports`.
    - `krita_adapter` may subclass and decorate with their untyped names.
    - The adapter imports `..bridge_core` relatively.
- **What the source scans refuse in `plugin/`.** Each rule has snippet cases in
  `tests/plugin/test_source_scans.py`.
  - `bridge_core` imports only the standard library, and itself relatively.
  - Other plugin code imports its own modules relatively or through `krita_art_mcp_bridge.`, never
    as `bridge_core` (Krita cannot find that name). `krita` and PyQt imports belong under
    `krita_adapter/`.
  - **Banned:**
    - `getattr`, `setattr`, `delattr` and `hasattr` with a computed name;
    - imports of `importlib`, `builtins`, `runpy`, `code` and `codeop`;
    - `setPixelData`, `saveAs` and every `.apply`;
    - the built-ins `exec`, `eval` and `compile`.
  - Qt's `loop.exec()` and `getattr(loop, "exec", None)` pass.
  - Modules removed by Python 3.12 or 3.13 are refused.
- **No `tests/conftest.py`.** The 3.10 run loads every conftest from the rootdir down, and its
  environment holds only pytest.
- **A stdio test waits for each reply, and closes stdin in a `finally`.**
  - The server can exit at end of input before answering queued requests.
  - With the subprocess's own context manager, a failed assertion hung the run for 10 minutes.
- **A plugin change loads only after a Krita restart.**
  - Run `install-plugin`, then restart.
  - `doctor` step 5 and the probe's first check refuse a stale plugin.
  - Each restart follows *Restarting Krita* above.
- **An exception escaping a PyQt5 slot aborts Krita.** Every slot and `setup()` catch everything
  and log to `plugin.log`. Keep that for new signal handlers.
- **Each server process serialises its tool calls** with the runner's lock. A tool function is
  sync, because mcp runs it on a worker thread. Never make one async while it blocks on the
  bridge.
- **A test that needs a live bridge** builds a real `Bridge` with a fake main thread, as the
  `MainThread` class in `tests/test_bridge_client.py` and `tests/plugin/test_bridge_http.py`
  does.
- **Session 3's own traps** are in its block:
  - hold the wrappers `openDocument` and `createDocument` return (K6);
  - measure `close`, don't assume it;
  - the harness closes only documents it created;
  - the server mints `operation_id`.
- **`Document.close()` on a modified document may ask to save.** The undo probe clears the
  modified flag first. A harness close must do the same, or use `dirty_policy: discard`'s path.
- **Comments state the present, briefly.** No session ids, no "used to", no review stories, no
  paragraphs.
- **Every push needs its own approval.** List `origin/main..HEAD` first, because parallel
  sessions may share this checkout.
