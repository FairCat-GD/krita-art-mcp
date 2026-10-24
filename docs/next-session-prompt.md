Read docs/spec/SPEC.md (§1 decisions 5, 10; §5 invariant 8), docs/spec/PDD.md (Part 4
`krita_resource_list`, `krita_capture`, `krita_sample`; Part 12 *Colour-maths fixtures*; Part 8
K12, K17, K21, K36, C2, C4, C5), CLAUDE.md, then this file. Then do Session 5 of
docs/spec/SESSIONS.md: reading pixels. Session 5 has four parts:
- **`krita_capture`:** composite, layer and selection targets; native at `scale: 1`, otherwise
  composited on a background and resampled in Pillow; `max_px` 1600 by default, 4096 at most;
  MCP image content with `_meta: {"codex/imageDetail": "original"}`, plus the path;
- **`krita_sample`:** points and discs, RGBA, hex, L\*a\*b\* and L\*C\*h, composite and layer
  labelled;
- **`krita_resource_list`:** brush presets with their fingerprint, the blend-mode whitelist,
  profiles and palettes;
- **the `source` shape,** amended in all 19 schemas.

Release 0.5.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 4 are done; 5 to 15 remain, and 6, 10 and 13
  are architecture reviews.
- **The push status.** `origin` is the private GitHub repository `FairCat-GD/krita-art-mcp`.
  `origin/main` holds everything through `review: a malformed journal line no longer blocks
  calls, and 9 smaller`. Session 4's commits wait for the next approved push. List
  `origin/main..HEAD` before any push.
- **What Session 4 left that Session 5 builds on:**
  - **The transfer path.**
    - The plugin's `transfer.write(dir, data, width, height, fmt)` writes `BGRA8` or `A8` into
      `transfer/` and returns `{path, size_px, format}`.
    - The server's `transfer.take(directory, spec)` returns an RGBA (or one-channel) NumPy array.
      It never deletes the file: the caller calls `transfer.discard` once what it made is on
      disk.
    - Masks to the plugin: `transfer.put_mask` and `bridge_core.transfer.take_mask`. No tool
      sends one yet.
  - **Resolvers.** A bridge result that names a transfer file is resolved before its receipt.
    - `tools/documents.py` has `resolve_open`, `resolve_inspect` and `resolve_close`, and
      `RESOLVERS` in `tools/operations.py` runs them for `krita_operation_get`.
    - A capture's resolver joins them, so receipts stay pure functions of the outcome.
    - A resolver must never raise: open's logs, and inspect's returns a retryable failure.
  - **`Places`** (`paths.Places`, `call.places`) holds `config_file`, `transfer_dir`,
    `harness_dir` and `baselines_dir`. `build_server(client, journal, places)` requires it.
    Captures go to `<server data dir>/captures/YYYY-MM-DD/`, so Session 5 adds `captures_dir`
    there.
  - **The port** (`bridge_core/port.py`).
    - It has `tree`, `prepare_read` (K46), `composite` (the whole canvas) and `selection`.
    - Capture and sample need reads of a rect, and of one layer's own paint device by id; add
      them beside `composite`.
    - `inspection.check_frame(frame)` is the frame rule to reuse for `source.frame`.
  - **K46 acts only on the document in front.** `Document.setActiveNode` does nothing for a
    document whose view is not active, and `prepare_read` raises if the mask stays active.
    - Opens are safe: their own view is in front.
    - A capture of another document is not. Whether capture calls `Window.showView`, switching
      the owner's tab, is an open decision for Session 5's plan.
  - **The handle** carries `path`, `source_path`, `source_sha256`, `baseline_id` and `protected`.
    For an owner's document every layer is protected (`inspection.protected_ids`).
  - **The layer entry** is one shape in open and inspect, held equal by a schema test. Types are
    the contract's short names (`inspection.TYPES`).
  - **The fixtures** (`probe/fixtures.py`).
    - `write_ora`, `write_png` and `composite` give exact expected pixels: visible content is
      opaque or empty, and R ≠ B everywhere.
    - "probe hidden" is a hidden layer at opacity 0.5. Its own paint device is opaque, which
      Session 5's "a layer capture excludes the layer's opacity" (K12) can use.
    - `harness.export_kra {document_id, target_path}` makes a KRA from a harness document.
  - **The probe's file checks** live in `probe/opening.py`, and its report helpers in
    `probe/report.py`. Its sweep closes probe-named created documents and any document whose path
    lies in the harness folder, through both servers.
  - **Baselines** are `<server data dir>/baselines/<baseline_id>.png`. Ids are `baseline-` plus
    12 hex characters, and a plugin-sent id is checked against that shape before it names a
    file.
- **What the spec said that turned out wrong or harder:**
  - **Two-sided checks mask each other in tests.** The server and the plugin both refuse escapes,
    frames and bad working dirs, so a test of the server's refusal also asserts
    `operation_id is None`: the plugin's refusal comes back through the bridge with one.
  - **Krita's ORA loader sets each layer's offset** (`Node.position()`), and `Node.bounds()` is
    the exact bounds.
  - **A PNG opens as one layer named "Background".**
  - **A fresh open is not marked modified,** and a fresh document's selection is `None`.
- **Decisions written down nowhere else** (deliberate, for ARCHITECTURE):
  - **Working copies** are `<working_dir>/<YYYYMMDDTHHMMSS.mmmZ>-<basename(realpath)>`, minted
    in the job, made under `O_EXCL`, and removed on any later failure.
  - **Transfer names.** The plugin's files are `<32 hex>.raw`; the server's masks are
    `mask-<sha256>.a8`.
  - **`allowed_roots`** comes from the plugin's own read of `config.json`, without the harness
    folder.
  - **`journaled(..., precheck=)`** runs a check that can change between attempts, such as the
    roots, only while no attempt of that `request_id` is unsettled.
  - **A document a failing job cannot close** stays registered, owned and unsafe, so `discard`
    can end it; the error's `details.document_id` names it.
- **Baseline** (the next session moves these only by what it adds):
  - `verify`: 6 stages, all PASS;
  - 243 server tests passed, 0 skipped;
  - 194 plugin-core tests passed, 0 skipped;
  - `probe`: 45 PASS, 0 FAIL, 9 MEASURED;
  - 8 registered tools.
- **Not done:**
  - **The owner's roots.** `doctor` step 6 FAILs with "no roots" until the owner runs `roots add`.
    No session runs it, and the probe needs no roots.
  - **The owner's own look at N-03** in Activity Monitor (in `docs/BACKLOG.md`).
  - **The `[0.4.0]` CHANGELOG link reference** goes in with the review commit, once the feat
    commit has its sha.

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
    Never record the names of the owner's open documents, or their roots.
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
- **No test may reach the owner's folders.**
  - Every `build_server` gets a temporary `Journal` and `Places`.
  - The stdio `serve` test sets `KRITA_ART_MCP_DATA_DIR`, because `serve()` sweeps baselines
    at start.
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
- **Session 5's own traps** are in its block:
  - the SDK's `Image` takes no `_meta`, so build `ImageContent` (C1);
  - Claude Code downscales images and caps output at 25,000 tokens (C4), so paths go with every
    image;
  - never resample an image that was already resampled.
- **Also for Session 5:**
  - **The probe's output shows one expected warning,** "the baseline … was not kept". It comes
    from server-b, which dedups an open whose transfer file server-a already took.
  - **Falsifying live checks without the whole probe.** A scratch driver that runs only the new
    probe module against real servers (as `probe.opening.run` is called from `_documents`) saves
    the 500-call H4 run on every break.
  - **Never rename with a blanket `sed`.** `s/_tool(/tool(/` also turned `call_tool` into
    `calltool`.
  - **Fixed clocks collide working-copy names** in tests: give each open its own `working_dir`.
- **Comments state the present, briefly.** No session ids, no "used to", no review stories, no
  paragraphs.
- **Every push needs its own approval.** List `origin/main..HEAD` first, because parallel
  sessions may share this checkout.
