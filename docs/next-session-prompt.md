Read docs/spec/SPEC.md (§1 decisions 9, 20, 25–27; §4; §5 invariants 2, 3, 13), docs/spec/PDD.md
(Part 4 *Conventions*: coordinates, IDs; `krita_document_open`, `krita_document_inspect`; Part 6
*Files*, *Formats*; Part 8 *Pixel transfer*, *Security & privacy*, K12, K14, K39, K46), CLAUDE.md,
then this file. Then do Session 4 of docs/spec/SESSIONS.md: opening files. Session 4 has five
parts:
- **roots:** `krita-art-mcp roots add|list|remove`, `config.json` with its version, `realpath`
  on both sides (`PATH_NOT_ALLOWED`), and `doctor`'s "no roots" step;
- **the transfer path:** raw `pixelData` files in `transfer/`, BGRA to RGBA in the server, masks
  the other way with their SHA-256, Pillow and NumPy added;
- **`harness.*`:** the namespace, its folder gate, and the server-side ORA fixture writer;
- **`krita_document_open`:** working copies and read-only opens, KRA / ORA / PNG, protection by
  default, and the `as_opened` baseline;
- **`krita_document_inspect`**, frame 0 only.

Release 0.4.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 3 are done; 4 to 15 remain, and 6, 10 and 13
  are architecture reviews.
- **The push status.** `origin` is the private GitHub repository `FairCat-GD/krita-art-mcp`.
  `origin/main` holds everything through `review: a bridge that fails to publish now stops, and
  6 smaller`. Session 3's `feat:` commit, and its `review:` commit once the review is done, wait
  for the next approved push. List `origin/main..HEAD` before any push.
- **What Session 3 left that Session 4 builds on:**
  - **The plugin's registry** (`bridge_core/registry.py`).
    - A `Handle` has `document_id`, `document` (the strong reference), `owned`, `mode`, `dirty`,
      `unsafe` and `lease`. Session 4 adds the source path and hash, the baseline id, and the
      protection fields.
    - `Registry.add(document, mode, client)` registers a document the bridge made and gives the
      lease to the caller. Open will use it with `working_copy` or `read_only`.
    - `sync()` matches wrappers with `==` (libkis wrappers are unhashable) and prunes documents
      that are gone. It gives the owner's documents `read_only` handles with `owned=False`.
    - `guarded(handler, dirties=, writes=, allow_unsafe=)` wraps every document mutation. Its
      order:
      1. the job-start refusal (modal dialog, not exactly one window; both retryable);
      2. the lookup (`DOCUMENT_NOT_FOUND`);
      3. `DOCUMENT_READ_ONLY` (not owned, or `writes` on a `read_only` mode);
      4. `DOCUMENT_UNSAFE`;
      5. the lease (`DOCUMENT_IN_USE`);
      6. the handler;
      7. `dirty` when `dirties(args)`.

      A close is `writes=False`, so an agent can close its own read-only opens.
  - **The plugin's document ops** (`bridge_core/documents.py`, behind a port that
    `krita_adapter/documents.py` implements): `document.create`, `document.list` and
    `document.close`. New ops join `documents.handlers()` or a sibling, and the extension
    merges them into the bridge's handlers.
  - **Jobs** (`bridge_core/jobs.py`): a handler is `(args, call)`, and `call.client` is the
    lease identity.
    - A `request_id` names one operation for the Krita session.
    - A retryable `BridgeError` means "changed nothing" and releases the id, so raise a
      retryable error only before an op changes anything.
  - **The server's journaled path** (`tools/dispatch.py`). `journaled(call, tool, arguments,
    request_id, send, receipt)` is how `krita_document_open` must dispatch.
    - **Op args must be a pure function of the tool's arguments,** or a genuine retry hashes
      differently and conflicts. Session 7's mask transfer files must be named by their
      SHA-256.
    - **A receipt depends only on the op's outcome** (`from_outcome`), and `RECEIPTS` in
      `tools/operations.py` maps each op to its tool, so `krita_operation_get` can rebuild it.
      Add open's and inspect's ops there.
  - **The journal** (`journal.py`): `<server data dir>/journal/YYYY-MM-DD.jsonl`. It indexes 7
    UTC days. The server data dir is `paths.server_data_dir()`, which honours
    `KRITA_ART_MCP_DATA_DIR`; the baselines and captures go there too.
  - **`krita_document_close`** returns `baseline_untouched: null` without a source. Session 4
    fills it, and removes the `as_opened` baseline on close.
  - **`mode`** is `new` (create), `working_copy` or `read_only`.
  - **The test fakes** live in `tests/fixtures/fake_krita.py` (`FakePort`, `FakeDocument`,
    `MainThread`). They are on pytest's `pythonpath` and mypy's `mypy_path`, and are 3.10-valid
    for the plugin run.
  - **The probe** gives each `serve` its own `KRITA_ART_MCP_DATA_DIR` under `harness/`
    (`server-a`, `server-b`).
    - Its document checks run only after the gate "no Krita document has unsaved changes".
    - It sweeps documents named `krita-art-mcp probe…` that the bridge made, at start and end.
- **What the spec said that turned out wrong or harder:**
  - **`Krita.createDocument` makes an opaque white "Background" paint layer,** whatever
    "transparent" means elsewhere: the default pixel is opaque white and the layer opacity 255.
    Create swaps it for a fresh paint layer "Layer 1" through `Node.setChildNodes`, which pushes
    no undo step (`addChildNode` and `Node.remove` do). Session 7's undo floor needs no special
    case for created documents.
  - **`Krita.createDocument` asserts that the colour space exists** (`Q_ASSERT(cs)`), so a
    wrong profile name could abort Krita. The plugin re-checks the colour space before any
    Krita call.
  - **`ps -o lstart` depends on the locale and time zone,** which differ between a shell and
    Krita launched from the Dock. Both sides run `ps` with `LC_ALL=C TZ=UTC`.
  - **The owner works in Krita while sessions run.** Twice the probe met a modal dialog (an
    open-file dialog) and correctly refused with `KRITA_MODAL_DIALOG`; it passed once the
    dialog was closed. A probe FAIL of that kind means "wait", not a bug.
- **Decisions written down nowhere else** (deliberate, for ARCHITECTURE):
  - **Retry layers.** The bridge dedups within a Krita session. The journal answers a receipt
    from any session, and refuses an `unknown` attempt from another session as uncertain.
  - **Outcomes.** `receipt` and `no_effect` settle every deduplicated attempt in their session;
    `not_sent` and `conflict` settle only their own.
  - **Polls.** A poll treats a 404 as "not registered yet" until the bridge has answered once,
    because operations are kept for the whole session.
  - **Document ids** are `doc-` plus 12 random hex characters, never reused across Krita
    restarts.
  - **Probe journals.** The harness's servers write their journals under `harness/`, never the
    owner's data dir.
- **Baseline** (the next session moves these only by what it adds):
  - `verify`: 6 stages, all PASS;
  - 163 server tests passed, 0 skipped;
  - 138 plugin-core tests passed, 0 skipped;
  - `probe`: 23 PASS, 0 FAIL, 4 MEASURED;
  - 6 registered tools.
- **Not done:**
  - the owner's own look at N-03 in Activity Monitor (in `docs/BACKLOG.md`);
  - the `CHANGELOG.md` link reference for 0.3.0, which needs the session commit's sha and is
    added with the review commit.

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
    Never record the names of the owner's open documents.
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
  environment holds only pytest. Shared fakes go in `tests/fixtures/`, 3.10-valid.
- **A stdio test waits for each reply, and closes stdin in a `finally`.**
  - The server can exit at end of input before answering queued requests.
  - With the subprocess's own context manager, a failed assertion hung the run for 10 minutes.
- **A plugin change loads only after a Krita restart.**
  - Run `install-plugin`, then restart.
  - `doctor` step 5 and the probe's first check refuse a stale plugin.
  - **Restarting Krita.** When `uv run krita-art-mcp doctor` ends with `0 unsaved`:
    1. run `uv run krita-art-mcp install-plugin`;
    2. quit Krita with `osascript -e 'tell application "krita" to quit'` (it reports "User
       canceled (-128)" even when Krita quits cleanly);
    3. wait until `pgrep -x krita` finds nothing;
    4. run `open -a krita`;
    5. wait for `bridge.json`;
    6. run `doctor` again.

    With any unsaved document, ask the owner (decision 21).
- **An exception escaping a PyQt5 slot aborts Krita.** Every slot and `setup()` catch everything
  and log to `plugin.log`. Keep that for new signal handlers.
- **Each server process serialises its tool calls** with the runner's lock. A tool function is
  sync, because mcp runs it on a worker thread. Never make one async while it blocks on the
  bridge.
- **A test that needs a live bridge** builds a real `Bridge` with `fake_krita.MainThread`, as
  `tests/test_document_tools.py` does with the real registry and a `FakePort`.
- **Session 4's own traps** are in its block:
  - ORA and PNG store no layer ids, so match them by name and order;
  - the projection's `pixelData` is BGRA;
  - the harness folder sits inside the real data directory, so sweep only `harness/`.
- **Also for Session 4:**
  - **Open with batch mode and `addView` at once** (K6, K14), as create does.
  - **On any failure after `openDocument`,** clear the modified flag and close the document in
    the same job, or it lingers as an owner `read_only` document the probe never sweeps.
  - **`Document.close()` on a modified document may ask to save.** The port's `close()` clears
    the modified flag first; keep every close going through it.
- **Comments state the present, briefly.** No session ids, no "used to", no review stories, no
  paragraphs.
- **Every push needs its own approval.** List `origin/main..HEAD` first, because parallel
  sessions may share this checkout.
