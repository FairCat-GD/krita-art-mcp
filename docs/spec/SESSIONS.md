# The session plan: round 1, the Phase 1 build

One chat per session. Never run two sessions in one chat: the point of the split is that no
session inherits stale context.

- **Scope** lives here, fixed in advance. The request and its resolved decisions are in `SPEC.md`
  beside this file, with the frozen `PDD.md` and the contract package in `reference/`; they are
  read-only, so do not re-litigate them. If a session finds a block wrong, it amends the block and
  records the reason both in the block and in `docs/next-session-prompt.md`.
- **State** is `CHANGELOG.md` (what shipped) and `docs/next-session-prompt.md` (what the next
  session needs that the docs do not say). Every session rewrites the prompt as its last act.
- **When this round closes,** session 15 deletes this file, `SPEC.md`, `PDD.md`, `reference/` and
  every `REVIEW-*.md`. Git history keeps them, and anything left open moves to `docs/BACKLOG.md`.

**Before starting**, confirm the tree is clean and that `docs/next-session-prompt.md` names the
session you are about to do. **Read order:** the `SPEC.md` sections and `PDD.md` parts the block
names, any `REVIEW-*.md` it names, `CLAUDE.md`, then the prompt. **Then plan, in plan mode,** and
ask the block's *Ask at the start* questions before any edit.

**Every session ends the same way:**
1. `uv run scripts/verify.py` green, plus the harnesses the block names.
2. Every new check falsified, once. Checks that already existed are not falsified again.
3. A `CHANGELOG.md` entry for anything user-visible, and the version bumped as the table says.
4. The docs the block names kept true. Until session 15 writes `ARCHITECTURE.md`, the done-note
   carries what it will need: the deliberate decisions and the counts.
5. A done-note appended to the block, then the prompt rewritten, then a local commit.
6. The owner's `/code-review high`, then a review-fixes commit.
7. The next prompt printed as the chat's last message.

Never push without being asked.

| Session | Scope | Decisions | Version |
|---|---|---|---|
| 1 | Scaffold: the project, `verify`, `--version` and `serve`, the 19 schemas, the C1 check | 4, 5, 14–17, 19, 22–24 | **0.1.0** |
| 2 | Bridge alive: the plugin, loopback HTTP, the job queue, `krita_server_info`, `install-plugin`, `doctor`, the probe | 11, 19, 21–24, 30 | **0.2.0** |
| 3 | Operations and the document registry: retries, the journal, `operation_get`/`cancel`, create, list, close | 5, 8, 27, 29 | **0.3.0** |
| 4 | Opening files: roots, the transfer path, `harness.*`, `document_open` with its baseline, `document_inspect` | 9, 20, 25–27 | **0.4.0** |
| 5 | Reading pixels: `capture`, `sample`, `resource_list` | 5, 10 | **0.5.0** |
| 6 | Architecture review: observe | 2 | — |
| 7 | Preparing a change: `layer_create`, `selection_set`, `protection_set`, the undo ledger, `history_step` | 5, 26, 27 | **0.6.0** |
| 8 | The verification core, and `layer_update` | 20, 27 | **0.7.0** |
| 9 | `paint_stroke`, verified per stroke; N-01/N-09 benchmarks | 6, 20 | **0.8.0** |
| 10 | Architecture review: paint safely | 2 | — |
| 11 | `preview_render`; N-02 benchmark | 6, 31 | **0.9.0** |
| 12 | `document_save`, verified by reopening; H4 long save | 27, 29 | **0.10.0** |
| 13 | Architecture review: every tool built | 2 | — |
| 14 | Acceptance: the full harness, the contract's exercises, H2, H3, final server instructions | 28, 30, 31 | **0.11.0** |
| 15 | Docs, changelog, manual runs; close the round | 2, 32 | **0.12.0** |

A review session (6, 10, 13) changes no product code and cuts no version. A session it inserts
takes the next version, and every later version shifts by one; the handoff says so.

---

## 1: Scaffold

**Read:** `SPEC.md` §1 (decisions 4, 5, 14–17, 19, 22–24), §3, §5 (invariants 1, 7, 8, 14), §6;
`PDD.md` Part 8 (*Build, install & operations*, C1); `docs/DEVELOPMENT-WORKFLOW.md` (*Day one*).

- **The project** (decisions 4, 19).
  - `pyproject.toml` for `krita-art-mcp` (import `krita_art_mcp`, `src/` layout, licence
    `GPL-3.0-or-later`), `.python-version` (3.12), `uv.lock`. Dependencies at the pins, added
    only when first used: `mcp` and `jsonschema` now; Pillow and NumPy in session 4.
  - The layout of SPEC §3, with `plugin/krita_art_mcp_bridge/` holding an importable
    `bridge_core` (its version constant) and an empty `krita_adapter`, so the plugin stages have
    something to check. The `.desktop` file and the extension are session 2's.
- **`verify`** (decision 24). `scripts/verify.py` runs six named stages, each failing on its own,
  then prints a summary:
  - ruff format check; ruff;
  - mypy, strict for `src/`, with `--python-version 3.10` for `plugin/`;
  - pytest on CPython 3.12;
  - plugin-core pytest on CPython 3.10, in an environment with no third-party package but pytest;
  - hygiene.
  - `docs/` is excluded from every stage but hygiene.
- **Hygiene** (decision 14, invariant 14).
  - Every tracked text file is split into lowercase `[a-z0-9]+` runs. The SHA-256 of each run is
    checked against the hash list in the handoff, which moves into a data file under `scripts/`.
    A hit names the file and line, never the term.
  - Every commit message on `HEAD` is checked for attribution: co-author trailers, "generated
    with" lines, AI session links.
- **The version** (decisions 22, 23).
  - `0.1.0` in `pyproject.toml`, and `krita-art-mcp --version` prints it.
  - `krita-art-mcp serve` starts an `MCPServer` named `krita-art` over stdio, with
    `serverInfo.version` read from the package metadata and no tools yet.
  - The plugin's version constant equals the package version; a test holds them equal.
- **Schemas** (decision 5).
  - The 19 Phase 1 tools' input and output schemas come unamended from
    `reference/contract-package/krita-mcp-contract/mvp.tools.json`, and their examples from
    `tools.json`. They go into `src/krita_art_mcp/schemas/`, one file per tool.
  - A test validates every example against its schema with a Draft 2020-12 validator.
- **The C1 check.** A test-only server returns `CallToolResult(is_error=True)` with
  `structured_content`, and an in-process client must receive it unchanged, output schema
  included. If the SDK alters or rejects it, stop and ask: this decides how every error is
  returned.
- **The invariant scans** (invariants 1, 7).
  - A source scan bans `setPixelData`, `Filter.apply`, `saveAs`, `exec` and `eval` in `plugin/`.
  - An import scan checks that `bridge_core` imports nothing from `krita` or PyQt, and that the
    plugin imports only the standard library, PyQt and `krita`.
- **Repository files.**
  - `LICENSE`: the GPL-3.0 text.
  - `CHANGELOG.md` from the template, with an empty `[Unreleased]` and `[0.1.0]`, and no link
    references (decision 17).
  - `README.md`: what it is, that Phase 1 is in progress, how to run `verify`, and where the docs
    are.
  - `tests/fixtures/README.md`: fictional data only; tests never read `docs/`; harness data lives
    only under `<data dir>/harness/`.
- **Docs.**
  - `CLAUDE.md`: the Commands table, filled in.
  - README: written.

**Gates:**
- `uv run scripts/verify.py` green, with these tests:
  - all 19 examples validate against their schemas;
  - the C1 error passthrough;
  - the version constants are equal, `--version` prints `0.1.0`, and a stdio `initialize`
    returns `krita-art` and `0.1.0`;
  - the banned-call and import scans;
  - hygiene, on files and on commit messages.
- Each verify stage falsified once, failing at its own step and nowhere else: a misformatted
  line, a lint error, a type error, a failing test, a construct newer than 3.10 in the plugin
  core, and a private term in a tracked file. Each new test falsified once.

**Watch for:**
- **uv fetches CPython 3.10 on first use.** It is a uv-managed interpreter, not system software.
  Never use `/usr/bin/python3` (3.9).
- **`docs/spec/reference/` ships Python scripts and JSON.** Keep `docs/` out of ruff, mypy and
  pytest collection.
- **The package's examples passed only its own subset checker.** Full Draft 2020-12 validation
  may reject some. Fix the copied example, never loosen the schema, and list each fix in the
  done-note.
- **The hygiene stage must not flag itself.** Assemble its attribution patterns so the source
  never holds them literally, and keep the term hashes in one data file.
- **`mcp` 2.3 renamed FastMCP** to `MCPServer` (`from mcp.server.mcpserver import MCPServer`);
  importing `mcp.server.fastmcp` raises (C1).
- **Don't add a dependency before it is used.**

---

## 2: Bridge alive

**Read:** `SPEC.md` §1 (decisions 11, 19, 21–24, 30), §3, §5 (invariants 6, 7, 10–12); `PDD.md`
Part 3 (*First-run experience*), Part 4 (*Conventions*: envelope, errors, long calls;
`krita_server_info`; *Server instructions*), Part 6 (*Files*), Part 8 (*Bridge protocol*, *Plugin
internals*, K1, K14, K19, K40, K41, K48, C1, C3, C4).

- **The plugin** (decision 11, invariant 12).
  - `krita_art_mcp_bridge.desktop` and the package. `__init__.py` adds the extension, and
    `setup()` starts a `ThreadingHTTPServer` on a daemon thread, at 127.0.0.1 on an ephemeral
    port.
  - A 32-byte token per Krita start, and `bridge.json` at 0600, written atomically.
  - It refuses to start while `bridge.json` names another live Krita.
  - On `applicationClosing` (K48), in order: stop accepting, fail queued jobs with `CANCELLED`,
    shut the server down, delete `bridge.json`.
  - Auth: a constant-time token compare, a `Host` check and a 64 MB body cap.
  - `logs/plugin.log`, rotated at 5 MB, never contains the token.
- **Jobs** (invariant 6).
  - A `queue.Queue`, drained on Krita's main thread and woken by a queued Qt signal. A
    `job_active` flag makes a re-entered drain return at once (K41).
  - Endpoints: `POST /v1/call`, `GET /v1/operations/<id>`, `POST /v1/operations/<id>/cancel`
    (queued jobs only), and `GET /v1/health`.
  - The health answer is cached at start: protocol, plugin version and source hash, Krita
    version, Qt major, capabilities.
- **Capabilities** (invariant 10). The matrix of PDD Part 4 `krita_server_info`, each entry
  `{supported, since, notes}` and true for this build: anything not built is `supported: false`.
- **The server.**
  - The bridge client: it re-reads `bridge.json` on every call and polls with `wait_s` of about
    2 s. After the 45 s wait budget it returns `running` with the operation id.
    `KRITA_NOT_RUNNING` only when the connection is refused and `bridge.json` names no live
    Krita. A protocol difference is `PROTOCOL_MISMATCH`.
  - The result envelope and the error mapping, with the envelope's shared shape amended in all 19
    schemas (decision 5). Errors are returned, never raised, each with its one-line text.
  - `krita_server_info`, with its schema amended and `api_version` `"0.2.0"`.
  - The server instructions are started (decision 30).
- **The CLI.**
  - `install-plugin [--krita-data-dir]`. The default comes from K19, it copies `plugin/` into
    `pykrita/`, and it prints the steps left: restart, enable, restart.
  - `doctor` names the first failing step, checking in order:
    1. the plugin files are present and their hash matches;
    2. the kritarc enable key is set;
    3. Krita is running;
    4. the bridge is reachable;
    5. the protocol and hash match.
- **The probe** (decision 24, invariants 11, 13).
  - `krita-art-mcp probe` runs `serve` over stdio as an MCP client and checks the plugin hash
    first.
  - It owns `<data dir>/harness/`: it sweeps leftovers at start and cleans up through the runner.
  - It prints PASS or FAIL per check, then a summary.
- **Runtime probes.**
  - The Python and PyQt versions inside Krita.
  - The `edit_undo` action, and how its text shows the top undo label (invariant 5 needs it).
  - H4, idle: 500 `krita_server_info` calls, with a p95 under 50 ms.
- **The owner's step.** After `install-plugin` and a restart, the owner enables the plugin in
  *Configure Krita › Python Plugin Manager* (on macOS, in the application menu). The session then
  restarts Krita when it is safe (decision 21).
- **Docs.**
  - `CLAUDE.md`: the commands `install-plugin`, `doctor` and `probe`.
  - README: install, enable, and register in Codex and Claude Code, with absolute paths (PDD Part
    8).
  - `CHANGELOG.md`: 0.2.0.

**Gates:**
- `uv run scripts/verify.py`, with these tests:
  - token, `Host` and body-size refusals;
  - job order, and the re-entry guard against a fake adapter;
  - cancel affects queued jobs only;
  - single instance, shutdown order, and `bridge.json`'s mode and atomic write;
  - the client against a fake bridge: `running` after the budget, then the result;
  - the error mapping for each bridge failure;
  - the envelope validates on success and on error;
  - instructions at or under 4,096 characters;
  - the capability matrix's shape.
- `probe`: the plugin hash, health, and `krita_server_info` over stdio. H4 idle and the runtime
  probes are recorded as measured, with the Krita version.
- By hand: N-03, Krita's idle CPU with the plugin under 1% in Activity Monitor, recorded.
- Each new check falsified once.

**Watch for:**
- **A plugin that fails to load says little.** Krita shows import errors in the Python Plugin
  Manager. Start with an extension that only logs, prove it loads, then grow it.
- **The krita bindings never release the GIL** (K40). The HTTP thread is silent during any long
  libkis call. The server's wait budget handles that; the bridge cannot.
- **A polling `QTimer` is wrong.** It fires inside `waitForDone` and starts a second job
  mid-stroke (K41). Use the queued signal.
- **A changed plugin loads only after a Krita restart.** Run `install-plugin`, then restart, but
  only with no unsaved documents; otherwise ask the owner (decision 21).
- **Apps launched from the Dock don't inherit `PATH`.** Client registrations use absolute paths.

---

## 3: Operations and the document registry

**Read:** `SPEC.md` §1 (decisions 5, 8, 27, 29), §4, §5 (invariants 5, 9); `PDD.md` Part 4
(*Conventions*: IDs, guard, one writer, request IDs; `krita_document_list`,
`krita_document_create`, `krita_document_close`, `krita_operation_get`/`cancel`; *States & edge
cases*), Part 6 (*Entities*), Part 8 (*Bridge protocol*, *Plugin internals*, K6, K14, K45).

- **Retries and the journal** (invariant 9).
  - The server journals each call as dispatched before sending it, and as finished after.
  - The bridge keys jobs by `request_id` for the Krita session. A duplicate returns the existing
    operation; a different `args_sha256` is `REQUEST_ID_CONFLICT`.
  - A call whose Krita session ended mid-flight fails on retry with `INTERNAL_ERROR`,
    `retryable: false` and `details.outcome: "uncertain"`, and is never re-sent. This is checked
    by unit tests only (decision 29).
- **`krita_operation_get` and `krita_operation_cancel`**, with their schemas amended.
- **The document registry**, in the plugin.
  - Document ids, with strong references to every wrapper, and `addView` straight after create or
    open (K6).
  - Each call is checked against `Krita.instance().documents()` (`DOCUMENT_NOT_FOUND`).
  - Mode: documents the owner opened by hand are `read_only`.
  - The writer lease (process id and start time; `DOCUMENT_IN_USE`), the dirty marker
    (decision 27), and the unsafe flag.
  - Job-start refusals: a modal dialog (`KRITA_MODAL_DIALOG`) or more than one window
    (`MULTIPLE_WINDOWS`).
- **The tools.**
  - `krita_document_create` takes RGBA / U8 / sRGB with a transparent background; anything else
    is `UNSUPPORTED_CAPABILITY`.
  - `krita_document_list`.
  - `krita_document_close`: `refuse` (`DOCUMENT_DIRTY`) or `discard`.
  - The `guard` shape is amended in all 19 schemas (decision 5).
- **The 20-cycle check** (decision 8). The harness creates and closes 20 documents. A crash stops
  the session, and the owner decides F-20 (PDD Part 8 *Technical risks*).
- **Docs.**
  - `CHANGELOG.md`: 0.3.0.
  - README: the tool list.
  - Server instructions: a fresh UUID per `request_id`, one working copy per agent.

**Gates:**
- `uv run scripts/verify.py`, with these tests:
  - a retry with the same arguments returns the same receipt, and different arguments conflict;
  - the journal is written before the send;
  - an uncertain call is never re-sent;
  - the lease holds across two fake server processes;
  - the dirty rules;
  - `guard` is identical in every schema.
- `probe`:
  - create, list and close;
  - a retried create returns the original receipt and makes no second document;
  - 20 cycles without a crash;
  - a second `serve` process is refused the lease.
- Each new check falsified once.

**Watch for:**
- **`openDocument` and `createDocument` return owning wrappers.** Hold them (K6).
- **Prior art reports `close` crashing Krita** about 1 in 5 times at the end of long sessions.
  Measure it; don't assume.
- **The harness closes only documents it created.**
- **The server mints `operation_id`.**

---

## 4: Opening files

**Read:** `SPEC.md` §1 (decisions 9, 20, 25–27), §4, §5 (invariants 2, 3, 13); `PDD.md` Part 4
(*Conventions*: coordinates, IDs; `krita_document_open`, `krita_document_inspect`), Part 6 (*Files*,
*Formats*), Part 8 (*Pixel transfer*, *Security & privacy*, K12, K14, K39, K46).

- **Roots** (invariant 3).
  - `krita-art-mcp roots add|list|remove` writes `config.json`, with its version field.
  - `realpath` is enforced on both sides (`PATH_NOT_ALLOWED`).
  - `doctor` gains a "no roots" step.
- **The transfer path.**
  - The plugin writes raw `pixelData` (BGRA for RGBA U8, K12) to `transfer/`. The JSON carries
    path, size and format.
  - The server memory-maps the file with NumPy, swaps it to RGBA, and deletes it. The bridge
    sweeps leftovers at start.
  - Masks go the other way as raw 8-bit files with their SHA-256 (decision 26).
  - Pillow and NumPy are added here.
- **`harness.*`** (decision 20).
  - The namespace and its folder gate.
  - The server-side ORA fixture writer: synthetic layers, fictional content.
  - Later sessions add the node operations their fixtures need.
- **`krita_document_open`**, with its schema amended per PDD Part 4.
  - `working_copy` copies the source into `<working_dir>/<UTC timestamp>-<name>`, inside a root
    and never in the source's own folder. Both hashes are checked (`SOURCE_HASH_MISMATCH`).
  - `read_only` opens the source itself.
  - Formats: KRA, ORA, PNG.
  - Every existing layer is protected except those named in `editable_layer_ids` (KRA) or
    `editable_layer_names` (ORA, PNG; a duplicate name is `INVALID_ARGUMENT`).
  - The `as_opened` composite baseline goes into `baselines/`, with its `baseline_id`. It is
    removed on close, and orphans are swept at server start.
  - Batch mode, and `addView` at once.
- **`krita_document_inspect`**, frame 0 only.
  - The layer tree with every PDD field, and the active layer.
  - Selection bounds and coverage, read through the transfer path.
  - The protection state, the allowed-mask summary, and the mode.
  - A selection mask is never left active (K46).
- **Docs.**
  - `CHANGELOG.md`: 0.4.0.
  - README: the roots step.
  - `CLAUDE.md`: the `roots` commands.
  - Server instructions: open with `working_copy` and a working folder; protection is deliberate.

**Gates:**
- `uv run scripts/verify.py`, with these tests:
  - root escapes through symlinks and `..`;
  - working-copy naming;
  - hash mismatches;
  - the editable-layer lists;
  - BGRA to RGBA;
  - transfer cleanup;
  - the ORA fixture writer;
  - the plugin-side root check.
- `probe`:
  - opens ORA, KRA and PNG fixtures, both as working copies and read-only;
  - the source's hash is unchanged afterwards;
  - the inspected tree matches the fixture;
  - the baseline exists while open and is gone after close;
  - a path outside every root is refused.
- Each new check falsified once.

**Watch for:**
- **ORA and PNG store no layer ids.** A reopened file gets new ones; match by name and order.
- **The projection's `pixelData` is BGRA** for integer RGBA (K12).
- **The harness folder sits inside the real data directory** (decision 25). Sweep only
  `harness/`, and never touch the owner's files.

---

## 5: Reading pixels

**Read:** `SPEC.md` §1 (decisions 5, 10), §5 (invariant 8); `PDD.md` Part 4 (`krita_resource_list`,
`krita_capture`, `krita_sample`), Part 12 (*Colour-maths fixtures*), Part 8 (K12, K17, K21, K36,
C2, C4, C5).

- **`krita_capture`**.
  - Targets: `composite`, `layer`, `selection`.
  - Native pixels at `scale: 1`. Otherwise it composites onto the background (`checker`,
    `transparent` or a colour) and resamples with the named filter in Pillow. `greyscale` is
    optional.
  - `max_px` defaults to 1600 and is capped at 4096; a larger ask must tile.
  - The result: MCP image content with `_meta: {"codex/imageDetail": "original"}`, the path, the
    exact rect, the size, the filter, the profile, and the document-to-image transform.
  - An image over the 6 MB cap comes back as a path with a 1600 px preview (C5).
  - The live check of `target: selection` is session 7's.
- **`krita_sample`**: points, plus an optional disc radius returning the alpha-weighted mean,
  `stdev_L` and the pixel count. It reports RGBA 0–255, hex, L\*a\*b\* (D65) and L\*C\*h, with
  composite and layer values labelled.
- **`krita_resource_list`**.
  - Brush presets: `preset_id` (the file name), name, engine, and `preset_sha256` of
    `Preset(resource).toXML()`.
  - The blend-mode whitelist (ids per K21), profiles and palettes, with cursor and limit.
- **The `source` shape**, amended in all 19 schemas (decision 5).
- **Docs.**
  - `CHANGELOG.md`: 0.5.0.
  - README: the tool list.

**Gates:**
- `uv run scripts/verify.py`, with these tests:
  - the four colour fixtures of PDD Part 12, within 0.05;
  - the disc mean;
  - resample geometry and the transform;
  - the size cap;
  - the image `_meta`.
- `probe`:
  - a native capture's bytes equal the fixture's pixels;
  - a layer capture excludes the layer's opacity (K12);
  - samples at known pixels are exact;
  - a preset's fingerprint is unchanged across two reads and a Krita restart, measured and
    recorded.
- Each new check falsified once.

**Watch for:**
- **The MCP SDK's `Image` takes no `_meta`.** Build `ImageContent` directly (C1).
- **Claude Code downscales images** and truncates output at 25,000 tokens (C4). Paths go with
  every image.
- **Never resample an image that was already resampled.**

---

## 6: Architecture review: observe

Placed at the owner's request, after the observe milestone and before the tools that change
pixels.

**Read:** all of `SPEC.md`; `PDD.md` Parts 4, 6 and 8; `CLAUDE.md`; the code and tests from
sessions 1–5.

- **The review** (decision 2) reads the code cold against `SPEC.md`:
  - the layering and boundaries of §3;
  - each invariant, where it is enforced, and any that is not;
  - duplication and drift: the envelope, the errors, and the constants the bridge shares;
  - the job system, the transfer path and the registry, measured against what sessions 7–12 will
    put through them (verification reads, rollback, long saves);
  - data-directory files and their cleanup, measured before and after a harness run;
  - harness health: run time, flakiness, leftovers;
  - test gaps and debt;
  - fit for Phases 2–6: profiles as defaults, `frame`, `revision`, `expected_revision`.
- **`docs/spec/REVIEW-<date>.md`**: numbered findings, each with evidence (`file:line` or a
  measurement), a severity and a proposed remedy. No product code.
- **In plan mode, with the owner:** which findings become scope. Each becomes an amendment to a
  later block, logged there as "amended by review 6", or an inserted fix session with its own
  block and reason, after which versions shift.
- **Docs.** The REVIEW file. The handoff names the chosen findings and where each landed.

**Gates:**
- `uv run scripts/verify.py` and `probe` green as found, with the counts recorded.
- No version and no CHANGELOG entry.
- Commit: `docs: architecture review — observe, findings only`.

**Watch for:**
- **A review is evidence, not scope.** Change no code here, even for an obvious fix; write it
  down as a finding.
- **Measure, don't infer.** Timings, leaks and leftovers are measured.

---

## 7: Preparing a change

**Read:** `SPEC.md` §1 (decisions 5, 26, 27), §5 (invariants 4, 5); `PDD.md` Part 4
(`krita_layer_create`, `krita_selection_set`, `krita_protection_set`, `krita_history_step`), Part
8 (K7, K8, K10, K11, K22, K23, K43, K46); any REVIEW finding the handoff assigns here.

- **`krita_layer_create`**.
  - Types `paint` and `group`, and new layers are editable.
  - Inside a protected group it is allowed, unless an appearance-affecting property of the group
    would change.
  - One undo step.
- **`krita_selection_set`**.
  - The server rasterises rect, ellipse and polygon with Pillow at 4× supersampling.
  - Raster `{mask_uri, mask_sha256, origin_px}`: an 8-bit single-channel PNG inside a root
    (`RESOURCE_HASH_MISMATCH`), sent to the plugin raw.
  - Also `layer_alpha`, `all` and `none`, with combine, feather, grow, shrink and invert.
  - It builds on `doc.selection().duplicate()` or a fresh `Selection()`, and commits with
    `setSelection` in one undo step.
  - It returns `selection_id`, the mask artifact, bounds and coverage.
- **`krita_protection_set`**.
  - Tighten only: protected layer ids, and `allowed_change_mask` as `{uri, sha256}` (a binary
    PNG), `{rect}`, `{polygon}` or `null`.
  - `preserve_composite_alpha` and `preserve_canvas`.
  - It sets the undo floor and clears the redo allowance.
- **The undo ledger** (invariant 5). Every operation records the undo steps it pushed, and the
  harness confirms each count.
- **`krita_history_step`**.
  - Undo or redo, 1 to 50 steps, on the document's view, with `waitForDone()` after each step.
  - Never below the floor; redo stays within the allowance.
  - It returns `verified`, `content_sha256` and a capture path.
- **Refusals** for the new mutations: `DOCUMENT_READ_ONLY` and `LOCKED_TARGET`.
- **`harness.*`**: a selection mask set as the active node (K46).
- **Docs.**
  - `CHANGELOG.md`: 0.6.0.
  - README: the tool list.
  - Server instructions: add a layer before painting; to repair several regions, allow their
    union once and select each; undo steps include selection commits and layer creation.

**Gates:**
- `uv run scripts/verify.py`, with these tests:
  - rasterising, antialiasing and combining;
  - the mask hash;
  - tighten-only;
  - the floor and allowance arithmetic;
  - the ledger.
- `probe`:
  - each operation's undo count matches the ledger;
  - undo past the floor is refused;
  - `capture target: selection` matches the mask;
  - read-only and protected-group refusals;
  - an active selection mask never enters an inspect or a capture.
- Each new check falsified once.

**Watch for:**
- **`Document.selection()` is the live selection.** Never change it in place (K23).
- **A local selection mask on a layer wins** over the global selection (K10).
- **Too many undos can remove the agent's own layer** (K22).

---

## 8: The verification core, and layer_update

**Read:** `SPEC.md` §1 (decisions 20, 27), §5 (invariants 5, 6); `PDD.md` Part 4
(`krita_layer_update`; `krita_paint_stroke`, *Per-stroke verification*), Part 8 (*Verification*,
K13, K22, K42, K43, K44); any REVIEW finding the handoff assigns here.

- **The verification core.** `layer_update` uses it now and `paint_stroke` in session 9. All of
  it runs in the plugin's main-thread job.
  - **Scope:** the node's bounds, a region, or the whole canvas.
  - **Reach analysis:** a filter mask or filter layer, a layer style, a transform mask, or a
    clone layer of the target, whether on the target, on an ancestor or above it, makes region
    scope `UNSUPPORTED_CAPABILITY`, naming the reason, unless `verify: "full"`.
  - **Before and after reads** of the composite and the target in scope, plus protected-layer
    hashes.
  - **The checks:**
    - no composite byte changes where the allowed mask is 0;
    - protected hashes are unchanged;
    - under `preserve_composite_alpha`, no alpha byte changes.
  - Whole-buffer byte operations only, never per-pixel Python loops.
  - Before, after and diff buffers go out as transfer files, and the server computes the counts
    and the diff image.
- **`krita_layer_update`**.
  - Properties: `name`, `visible`, `opacity`, `blend_mode` (whitelist), `inherit_alpha`,
    `alpha_locked`, `locked`, `active`.
  - `LOCKED_TARGET` on a protected layer or any ancestor of one.
  - Appearance changes end with `refreshProjection()` and `waitForDone()` (K42), then are
    verified.
  - **On a violation:** restore (native undo for a blend change, the old values for the rest),
    refresh, confirm, and fail with `PROTECTED_REGION_CHANGED`.
  - **An unconfirmed restore** is `ROLLBACK_FAILED`. The document is marked unsafe, and later
    paint and update calls fail with `DOCUMENT_UNSAFE`.
  - The receipt says which changes are undoable.
- **K43:** the redo of a rolled-back blend change is refused.
- **`harness.*`**: a filter layer, a filter mask, a transform mask and a clone layer.
- **Docs.**
  - `CHANGELOG.md`: 0.7.0.
  - Server instructions: to recolour inside a silhouette under `preserve_composite_alpha`, paint
    on a new `inherit_alpha` layer; most property changes cannot be undone.

**Gates:**
- `uv run scripts/verify.py`, with tests of the core against a fake adapter: each check, each
  rollback path, the unsafe flag, and the reach classification.
- `probe`:
  - an opacity change that leaks into a protected region is restored and confirmed;
  - `inherit_alpha` on a layer over the rim fixture passes under `preserve_composite_alpha`;
  - a filter layer above the target makes region scope `UNSUPPORTED_CAPABILITY`, and full scope
    passes;
  - the redo of a rolled-back blend change is refused.
- Each new check falsified once. When two layers guard one promise, break the layer the check
  is about.

**Watch for:**
- **Opacity, visibility and inherit-alpha don't redraw on their own** (K42).
- **Those changes aren't undoable** (K22). Their restore writes the old property values back,
  which is a property write, not a pixel write.
- **Byte masks are fast enough.** `int.from_bytes` takes about 40 ms for an 11 MB region (PDD
  Part 4).

---

## 9: paint_stroke

**Read:** `SPEC.md` §1 (decisions 6, 20), §5 (invariants 1, 5, 6); `PDD.md` Part 4
(`krita_paint_stroke`, *States & edge cases*), Part 5 (N-01, N-06 to N-09), Part 8 (K2 to K5, K9,
K10, K18, K21, K30, K37, K43, K44, K47); any REVIEW finding the handoff assigns here.

- **`krita_paint_stroke`**, with its schema amended per PDD Part 4: `pressure` and `time_ms`
  optional; `rotation_deg`, `tangential_pressure` and `speed` added; an explicit `layer_id`;
  `smooth`, `input_fallback` and `verify`.
  - **The brush.** Applied inside the job in the fixed order (K3), with the effective values read
    back.
    - Blend modes come from the whitelist.
    - `eraser` with `alpha_lock` is `INVALID_ARGUMENT` (K37).
    - `antialias` is omitted or `true`.
  - **The input gate.** Any per-point input other than the defaults is `UNSUPPORTED_CAPABILITY`,
    unless `input_fallback: "flat"`; the receipt carries `input_applied`.
  - **The stroke.** `smooth: catmull_rom` on the server, then `Node.paintPath` at pressure 1.0
    (K4).
  - **The target** must be a paint layer, with `paintAbility() == "PAINT"` (checked after
    activating the view) and no local selection mask.
  - Mirror painting and wrap-around are switched off for the job, and restored after (K2, K47).
  - A point outside the canvas grown by half the brush size is `INVALID_ARGUMENT`.
  - `OUTSIDE_ALLOWED_MASK` is checked before painting.
- **Verification**, through session 8's core.
  - Region R is the path bounds grown by `max(32, size × (0.5 + s))`, where `s` is the preset's
    scatter, parsed from the preset (K44). The target's bounds are checked too.
  - Rollback is one native undo, with its label checked, then confirmed.
  - The receipt has the PDD's fields.
- **K43:** the redo of a rolled-back stroke is refused.
- **`harness.*`**: view zoom, pan and rotation (N-07), and a local selection mask.
- **Benchmarks** (decision 6), failing over budget:
  - N-01: a 2000 × 2000 document with 20 protected layers, 200 points, a 40 px brush; p95 under
    1.5 s.
  - N-09: 8192 × 8192 with 30 protected layers; p95 under 3 s.
- **Docs.**
  - `CHANGELOG.md`: 0.8.0.
  - README: the tool list.
  - Server instructions: one stroke per call; `input_fallback` and what flat strokes mean; there
    is no raw pixel tool; the owner may be watching and must not edit presets while an agent
    paints.

**Gates:**
- `uv run scripts/verify.py`, with these tests: the brush order, the input gate, the smoothing,
  the arithmetic of R, and the receipt.
- `probe`:
  - **H6 / N-06:** 10 colours, `#A7C284` among them, exact at the stroke centre with a hard round
    brush at opacity 1.
  - **N-07:** equal hashes from strokes made at two zoom, pan and rotation settings.
  - **N-08 / H8:** soft and scatter presets beside a binary mask. Zero pixels change outside it,
    every leak is rolled back and verified, and region and full scope give the same verdict.
  - **The rim fixture:** a correction on a new `inherit_alpha` layer under
    `preserve_composite_alpha` passes; the same stroke on a normal layer is rolled back.
  - One call is one undo step.
  - A retry returns the original receipt and paints nothing.
  - N-01 and N-09 are within budget.
- Each new check falsified once.

**Watch for:**
- **Brush, colour and opacity are window-wide, shared with the owner** (K3). Set all of them on
  every call, and the harness restores them.
- **Activating a preset resets the composite op**, so set the blend after it.
  `setCurrentBrushPreset` does nothing when the preset is already current.
- **An unknown blend id silently paints `normal`** (K21).
- **Strokes over 1 s show Krita's busy dialog** (K41). It is expected; it is not a modal refusal.
- **Colour exactness goes through `ManagedColor`** (K18). Measure it, and record what was measured.

---

## 10: Architecture review: paint safely

Placed at the owner's request, after the paint-safely milestone and before the delivery tools.

**Read:** all of `SPEC.md`; `PDD.md` Parts 4 and 8, and Part 4's Phase 2 and Phase 3 sections;
`CLAUDE.md`; `REVIEW` 6; the code and tests from sessions 1–9.

- **The review** reads the code cold, as in session 6, with these in focus:
  - protection, the verification core, rollback, the undo ledger and the reach analysis;
  - invariants 1, 4, 5, 6 and 13, each traced to the tests and harness checks that hold it;
  - what became of review 6's findings;
  - whether the core is shaped for Phase 2 operations (filters, transforms, fills under the same
    rules) and for Phase 3 transactions;
  - headroom against N-01 and N-09;
  - the harness's run time.
- **`docs/spec/REVIEW-<date>.md`**, and the owner's choice of scope, as in session 6.
- **Docs.** The REVIEW file and the handoff.

**Gates:**
- `uv run scripts/verify.py` and `probe` green as found, with the counts recorded.
- No version.
- Commit: `docs: architecture review — paint safely, findings only`.

**Watch for:**
- **Evidence, not scope**, as in session 6.

---

## 11: preview_render

**Read:** `SPEC.md` §1 (decisions 6, 31); `PDD.md` Part 1 (pillar 4), Part 4
(`krita_preview_render`), Part 5 (N-02); any REVIEW finding the handoff assigns here.

- **`krita_preview_render`**, with its schema amended per PDD Part 4.
  - **Recipes:** explicit `{id, target_pixels_per_unit | target_size_px, integer_zoom?}`, with a
    `filter`.
  - **Sources:** `{document_id, frame, target, layer_id?, baseline_id?, crop_rect?, anchor_px?,
    export_pixels_per_unit?, master_to_export_scale?}`, where per-source values override the
    defaults.
  - **Around them:** backgrounds, tints (the second cut, decision 31), greyscale, and the
    overlays `selection` and `allowed_mask`.
  - **Output:** the image, its path, and per cell the exact document-to-cell transform after
    rounding.
  - Never resamples an image that was already resampled.
  - A world-unit recipe needs a `master_to_export_scale` for every source.
- **The sheet is composed on the server** (Pillow), from native captures read through the
  transfer path.
- **Benchmark N-02:** two recipes on a 2000 × 2000 master, p95 under 2.0 s.
- **Docs.**
  - `CHANGELOG.md`: 0.9.0.
  - README: the tool list.
  - Server instructions: check `krita_preview_render` at the asset's game sizes after every one
    to three strokes.

**Gates:**
- `uv run scripts/verify.py`, with these tests: the scale formula and rounding, per-cell
  transforms, integer zoom with nearest-neighbour sampling, anchor alignment, and overlays drawn
  only in the sheet.
- `probe`:
  - the first game's recipes (export 4 px per unit; review 2.95 and 1.8) and 128 / 256 px icons,
    rendered from fixtures;
  - a baseline beside the current state after a stroke;
  - N-02 within budget.
- Each new check falsified once.

**Watch for:**
- **A fit-to-window image is not evidence of game size.** The cell transform must be exact after
  rounding.

---

## 12: document_save

**Read:** `SPEC.md` §1 (decisions 27, 29), §5 (invariant 2); `PDD.md` Part 4
(`krita_document_save`), Part 6 (*Formats*), Part 8 (K14, K39, K45, K46), Part 12 (H4); any REVIEW
finding the handoff assigns here.

- **`krita_document_save`**, with its schema amended.
  - `.kra` or `.ora` to a new path inside a root; it never overwrites (`FILE_EXISTS`).
  - `exportImage` in batch mode, never `saveAs` (K39).
  - `BUSY`, retryable, when `exportImage` returns false under an autosave. Checked by unit tests
    only (decision 29).
  - A selection mask is never the active node (K46).
  - RGBA / U8 / sRGB documents only.
- **Verification.**
  - The live composite, the composite of the saved file reopened read-only in Krita, and its
    `mergedimage.png` decoded by the server without colour conversion must all be equal.
  - KRA: the size, the profile, the hierarchy, and per node every field and the pixel hashes,
    masks included.
  - ORA: what ORA stores, with masks and adjustment layers listed as `expected_losses`.
  - Any mismatch is `SAVE_VERIFY_FAILED`.
  - It returns `reopened_verified`, `layers_preserved`, `baseline_untouched`,
    `composite_preserved` and `expected_losses`.
  - A verified save clears the dirty marker. The working document's path never changes.
- **H4, long save.** A save of about 20 s, with a retried paint call queued behind it. The bridge
  answers within 1 s after the save, and no job is lost or duplicated.
- **Docs.**
  - `CHANGELOG.md`: 0.10.0.
  - README: the tool list.

**Gates:**
- `uv run scripts/verify.py`, with these tests: `mergedimage.png` decoding, the comparisons, the
  losses list, and the dirty marker clearing.
- `probe`:
  - a KRA round trip preserves layer ids and every compared field;
  - an ORA round trip lists masks as losses and keeps the composite equal;
  - an `inherit_alpha` layer saved to ORA reads back as inherit-alpha;
  - save, then close with `refuse`, succeeds;
  - H4.
- Each new check falsified once.

**Watch for:**
- **`exportImage` never clears Krita's modified flag** (K45). Dirtiness is the bridge's marker.
- **`exportImage` writes a temp file under `QDir::tempPath()`.** N-04 allows Krita's own temp
  files.
- **Verification reopens and closes internally**, so session 3's close measurements apply here
  too.

---

## 13: Architecture review: every tool built

Placed at the owner's request, after the last tool and before acceptance.

**Read:** all of `SPEC.md`; `PDD.md`; `CLAUDE.md`; `REVIEW` 6 and 10; all the code.

- **The review** covers the whole system, cold:
  - everything in sessions 6 and 10;
  - the preview and save paths;
  - the server instructions against the tools as built;
  - the deliberate decisions and the debt that session 15 will write into `ARCHITECTURE.md`;
  - the counts that will form its baseline.
- **`docs/spec/REVIEW-<date>.md`**, and the owner's choice of scope, as in session 6.
- **Docs.** The REVIEW file and the handoff.

**Gates:**
- `uv run scripts/verify.py` and `probe` green as found, with the counts recorded.
- No version.
- Commit: `docs: architecture review — every tool built, findings only`.

**Watch for:**
- **Evidence, not scope**, as in session 6.

---

## 14: Acceptance

**Read:** `SPEC.md` §1 (decisions 28, 30, 31), §9; `PDD.md` Part 4 (*Server instructions*), Part
12; `reference/contract-package/krita-mcp-art-workflow-brief.md` §7; any REVIEW finding the
handoff assigns here.

- **The full harness:** every check from sessions 2–12, with timings recorded.
- **The contract's acceptance exercises**, as scoped in SPEC §9:
  1. zoom and pan, with pressure reported unsupported or flattened;
  2. a detail on a new layer, on a sprite fixture and on a UI-icon fixture: base, exterior and
     alpha preserved, and edits to the protected base refused;
  3. a soft or scatter brush next to a boundary: zero changes outside it, and a violation rolled
     back;
  4. undo a batch, and retry a completed request;
  5. previews from explicit recipes;
  6. save, close and reopen a `.kra`, checking layers, masks, visibility, profile and pixels.
- **The H2 preset sheet:** six stock presets as shipped, flat strokes, for the owner to judge
  (decision 28).
- **H3, by hand:** the owner registers the server in Codex, and the Codex agent describes a
  capture of a known test pattern.
- **The server instructions, finalised** against PDD Part 4's list, at or under 4,096 characters.
- **F-24** (a floating message while a job runs), if time allows (decision 31).
- **N-04 in the harness:** nothing is written outside the roots, the data directory, and Krita's
  own temp and autosave files.
- **Docs.**
  - `CHANGELOG.md`: 0.11.0.
  - README: registration, checked by hand in both clients.
- **Ask at the start of 14:** which six stock presets the H2 sheet uses. The session proposes
  them from `krita_resource_list`, and the owner confirms.

**Gates:**
- `uv run scripts/verify.py`, and the full `probe` green.
- Each exercise recorded with its outcome.
- The owner's verdict on the H2 sheet recorded, and H3's result recorded.
- Each new check falsified once.

**Watch for:**
- **The exercises' fixtures are fictional.** Never use the first game's art. The trial on real
  art comes after the round.

---

## 15: Documentation pass, and the round's close

**Read:** all of `SPEC.md`; `docs/DEVELOPMENT-WORKFLOW.md` (*Rounds*, step 5, and the
`ARCHITECTURE.md` and between-rounds templates); every done-note and REVIEW file.

- **`docs/ARCHITECTURE.md`**, from the template: the overview, the invariants and how each is
  enforced, the bridge contract, the data layer, one section per subsystem, the testing strategy,
  packaging, the deliberate decisions, the known debt, and the baseline table (verify counts,
  probe checks and run time, tool count, error codes).
- **`docs/USER-GUIDE.md`**: install, enable, register, roots; the core loop from an agent's side;
  every error code and what to do; the limits of Phase 1.
- **A truthful README**, and **`CLAUDE.md`** repointed with the as-built paragraph.
- **`docs/BACKLOG.md`**: everything still open, including *Not yet checked by hand* (decision 29's
  two items among them), and the REVIEW findings the owner did not take.
- **Docs.**
  - `CHANGELOG.md`: 0.12.0.
  - The release commit carries the last done-note.
  - Then a separate `docs: close round 1` commit deletes `docs/spec/` and rewrites the handoff
    from the between-rounds template, naming the release commit.

**Gates:**
- `uv run scripts/verify.py`, and `probe` green once more, its counts going into the baseline.
- Hygiene clean across the whole history.

**Watch for:**
- **The docs describe what was built, not the plan.** Where they differ, the done-notes win.
