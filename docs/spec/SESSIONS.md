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
session you are about to do. **Read** in the workflow's order (the cycle, step 2), starting with
what your block's **Read** line names. **Then plan, in plan mode,** and ask the block's *Ask at
the start* questions before any edit.

**Every session ends the same way:**
1. `uv run scripts/verify.py` green, plus the harnesses the block names.
2. Every new check falsified, once. Checks that already existed are not falsified again.
3. A `CHANGELOG.md` entry for anything user-visible, and the version bumped as the table says.
4. The docs the block names kept true. Until session 15 writes `ARCHITECTURE.md`, the done-note
   carries what it will need: the deliberate decisions and the counts.
5. A done-note appended to the block, then the prompt rewritten, then
   `uv run scripts/verify.py --message <draft>` run with the drafted commit message, then a local
   commit (amended by 7a, after the workflow kit).
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
| 6a | Review fixes: observe (inserted by review 6) | 2 | **0.6.0** |
| 7 | Preparing a change: `layer_create`, `selection_set`, `protection_set`, the undo ledger, `history_step` | 5, 26, 27 | **0.7.0** |
| 7a | Hygiene and the workflow kit (inserted at the owner's request) | 14, 16 | — |
| 8 | The verification core, and `layer_update` | 20, 27 | **0.8.0** |
| 9 | `paint_stroke`, verified per stroke; N-01/N-09 benchmarks | 6, 20 | **0.9.0** |
| 10 | Architecture review: paint safely | 2 | — |
| 10a | Review fixes: paint safely (inserted by review 10) | 2 | **0.10.0** |
| 11 | `preview_render`; N-02 benchmark | 6, 31 | **0.11.0** |
| 12 | `document_save`, verified by reopening; H4 long save | 27, 29 | **0.12.0** |
| 13 | Architecture review: every tool built | 2 | — |
| 14 | Acceptance: the full harness, the contract's exercises, H2, H3, final server instructions | 28, 30, 31 | **0.13.0** |
| 15 | Docs, changelog, manual runs; close the round | 2, 32 | **0.14.0** |

A review session (6, 10, 13) changes no product code and cuts no version. A session it inserts
takes the next version, and every later version shifts by one; the handoff says so. Review 6
inserted 6a on 2026-10-24, so sessions 7–15 moved from 0.6.0–0.12.0 to 0.7.0–0.13.0. The owner
inserted 7a on 2026-10-24 with no version, so no version moved. Review 10 inserted 10a on
2026-10-25, so sessions 11–15 moved from 0.10.0–0.13.0 to 0.11.0–0.14.0.

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
  line, a lint error, a type error, a failing test, and a private term in a tracked file. A
  construct newer than 3.10 in the plugin core is guarded by two stages, so it fails at both
  3.10 stages (mypy on `plugin/`, plugin pytest) and at no other. Each new test falsified once.

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

**Done (2026-10-23, 0.1.0).**
- **Decided with the owner at the start:**
  - **`CHANGELOG.md` gets link references now.** Decision 17 ruled them out only until a remote
    existed, and `origin` exists.
    - `[0.1.0]` links to this session's commit, so it is written in the review commit, the first
      moment that sha exists.
    - `[Unreleased]` stays unlinked until the first tag.
- **The project.**
  - `pyproject.toml` uses `uv_build`, the `src/` layout and GPL-3.0-or-later, beside
    `.python-version` (3.12) and `uv.lock`.
  - **Dependencies:** `mcp` 2.3.0 and `jsonschema` 4.26.0.
  - **Dev:** pytest 9.1.1, ruff 0.17.2, mypy 2.4.0, and `types-jsonschema`, because
    `jsonschema` ships no `py.typed`.
  - **Ruff** targets py310 for `plugin/` and `tests/plugin/` through `per-file-target-version`.
- **The plugin root.**
  - `plugin/krita_art_mcp_bridge/` has no `__init__.py` yet.
  - `bridge_core` (holding `PLUGIN_VERSION`) and an empty `krita_adapter` are top-level packages
    for pytest (`pythonpath`) and for mypy (`mypy_path`, `-p`).
  - Tests import `bridge_core`, never `krita_art_mcp_bridge.bridge_core`. They then never run the
    package `__init__.py`, which will import Krita.
- **`--version` and `serve`.**
  - `krita_art_mcp.cli` uses argparse.
    - `--version` prints `krita-art-mcp 0.1.0`.
    - With no command, it prints usage and exits 2.
  - `server.build_server()` returns `MCPServer("krita-art", version=__version__)`, with no tools
    and no instructions. `__version__` comes from the package metadata.
- **Schemas.**
  - **The copy.** 19 files, `src/krita_art_mcp/schemas/krita_<tool>.json`, copied by a one-off
    script that is not committed.
    - Each holds the `mvp.tools.json` entry unamended (`name`, `description`, `inputSchema`,
      `outputSchema`, `annotations`), plus `example` from `tools.json`.
    - They are written as 2-space JSON.
    - `schemas.tool_names()` and `schemas.load()` read them as package data.
  - **Full Draft 2020-12 validation (jsonschema 4.26.0)** needed no example fix. The package's six
    error examples also validate against all 19 output schemas.
- **C1 holds.**
  - **What was checked.** An `MCPServer` tool is built by hand: `mcp.server.mcpserver.tools.Tool`
    with `FuncMetadata(arg_model=…, output_schema=<the contract's JSON Schema>)`.
    - It returns `CallToolResult(is_error=True, content=[…], structured_content=<envelope>)`.
    - An in-process `mcp.Client` receives it unchanged, and the contract's output schema is listed
      as it is.
  - **Why it passes.**
    - `MCPServer` validates results only against a pydantic `output_model`, which hand-built
      metadata lacks (`func_metadata.py`, `convert_result`).
    - The client skips output-schema validation for `is_error` results (`client/session.py`,
      `call_tool`).
  - **What it means for later sessions.**
    - Errors are returned this way.
    - The hand-built `Tool` is how a tool publishes the contract's exact schemas.
    - Its pydantic `arg_model` filters the arguments. An empty model passes none through, even
      with `extra="allow"` (measured). How exact arguments reach a tool and are validated against
      its JSON Schema is session 2's design.
- **The scans** (`tests/plugin/test_source_scans.py`, with `ast`, on 3.10).
  - **Banned:** any name, attribute, imported name or string constant equal to `setPixelData`,
    `saveAs`, `exec` or `eval`, and every `.apply` attribute.
  - **Allowed imports:** absolute imports only from 3.10's `sys.stdlib_module_names`, `krita`,
    `PyQt5`, `PyQt6` and the plugin's own packages.
  - **Placement:** `krita` and PyQt imports only under `krita_adapter/`.
- **Hygiene.** `scripts/hygiene.py`, with the seven hashes in `scripts/hygiene_terms.txt`.
  - **Files.** It checks the contents and paths of tracked files and of untracked files that are
    not ignored. Files containing NUL are skipped as binary.
  - **Commit messages.** Every message reachable from `HEAD` is checked against the attribution
    patterns (assembled from pieces) and the term hashes.
  - **Reporting.** A hit names the file and line, or the commit and message line, with a
    12-character hash prefix.
- **`verify`** is `scripts/verify.py`, in six stages.
  - **`format`** and **`lint`.**
  - **`types`** runs mypy three times, because mypy takes either packages or files in one run:
    - strict on 3.12, over `src`, `scripts` and `tests`;
    - `--python-version 3.10`, over `-p bridge_core -p krita_adapter`;
    - `--python-version 3.10`, over `tests/plugin`.
  - **`tests`.**
  - **`plugin-tests`:** `uv run --isolated --no-project --python 3.10 --with pytest==<uv.lock's>`.
    Its environment holds pytest and pytest's own dependencies, nothing else.
  - **`hygiene`.**
  - Every stage runs whatever the others do. `verify.py <stage>…` runs only the stages named.
- **Repository files.**
  - **`LICENSE`:** the GPL-3.0 text, copied from Krita's bundled `pyqtbuild/.../LICENSE.gpl3`
    (674 lines, sha256 `8ceb4b9e…5b903`), so nothing was downloaded.
  - `CHANGELOG.md`, `README.md`, `tests/fixtures/README.md`, and the Commands table in
    `CLAUDE.md`.
- **Amendments:**
  - **CHANGELOG link references.** The block said none, citing decision 17. `origin` exists now,
    so `[0.1.0]` gets one in the review commit. Amended at plan time, with the owner.
  - **Hygiene checks more than the block names:**
    - untracked files, so a new file is checked before it is staged;
    - file paths;
    - private terms in commit messages.

    The session's own finding: each closes a gap in the same invariant.
  - **`types` runs mypy three times,** because mypy refuses packages and files in one run. The
    session's own finding.
- **Measured** (mcp 2.3.0):
  - **The stdio `initialize`** (protocol `2025-06-18`) answers `serverInfo {krita-art, 0.1.0}`.
  - **Closing stdin early.** When stdin closes right after a burst of requests, the server can
    exit before answering the later ones. The stdio test therefore waits for each reply.
  - **The 3.10 environment** holds pytest 9.1.1, exceptiongroup, iniconfig, packaging, pluggy,
    Pygments, tomli and typing_extensions, on CPython 3.10.20.
  - **Ruff's py310 target works.** A `type` alias statement is flagged in `plugin/` and not in
    `src/`.
- **Checked by hand:**
  - `uv run krita-art-mcp --version` prints `krita-art-mcp 0.1.0`;
  - `krita-art-mcp` with no command prints usage and exits 2;
  - `serve < /dev/null` exits 0.
- **Falsified:**
  - **Stages:**
    - `x=[1,2]` in `server.py` failed `format` only;
    - an unused `import os` failed `lint` only;
    - `x: int = "a"` in `cli.py` failed `types` only;
    - a changed `--version` expectation failed `tests` only;
    - a throwaway word in an untracked file, with its hash added, failed `hygiene` only;
    - `from typing import Self` in `bridge_core` failed `types` (its 3.10 run; the 3.12 run
      passed) and `plugin-tests`, and nowhere else.
  - **Tests.** Each failed when broken and passed again once restored:
    - a schema file removed;
    - a stray field in an example;
    - top-level `additionalProperties: true` (a first attempt edited a nested one and proved
      nothing);
    - a changed envelope in C1;
    - the plugin version changed (equality) and shortened (shape);
    - a changed `serverInfo` expectation. This first hung the stdio test for 10 minutes, until
      the test closed stdin in a `finally`;
    - the plugin path misspelt (sources found);
    - `doc.saveAs` planted (banned call);
    - `import numpy` (stdlib, Qt and Krita imports);
    - `import krita` in `bridge_core` (adapter only);
    - the terms file emptied;
    - the lowercasing removed (file and line);
    - the path scan disabled;
    - the binary skip removed;
    - the trailer pattern changed;
    - `--others` dropped (untracked files).
- **Numbers:**
  - `verify`: 6 stages, all PASS;
  - 49 server tests passed, 0 skipped;
  - 5 plugin-core tests passed, 0 skipped;
  - 19 schema files and 7 term hashes.
- **Review (`/code-review high`), 10 findings: 10 fixed and 0 skipped.**
  - **`bridge_core` never reaches Krita.**
    - Imports are now resolved, relative ones included.
    - A new test holds `bridge_core` to the standard library and to relative imports of itself,
      so a path to `krita_adapter` or to the package is refused.
    - Own modules elsewhere are imported relatively or through `krita_art_mcp_bridge.`, as Krita
      loads them.
  - **The stdlib allowlist is 3.10's minus the modules removed by 3.12 and 3.13,** since the
    plugin runs on Krita's 3.13. `imp`, `cgi`, `distutils` and the like are refused.
  - **`verify` runs every command of a stage,** even after one fails.
  - **The banned-call scan refuses the built-ins `exec`, `eval` and `compile` by name, not by
    attribute.** PyQt6's `loop.exec()` and `getattr(loop, "exec", None)` pass.
  - **Indirect routes to the banned calls are refused:**
    - `getattr`, `setattr`, `delattr` and `hasattr` with a computed name;
    - `__import__`, `vars`, `__builtins__`, `__dict__`, `__getattribute__`, `attrgetter` and
      `methodcaller`;
    - imports of `builtins`, `importlib`, `runpy`, `code` and `codeop`.

    Snippet tests list what is refused and what passes.
  - **Hygiene checks staged content too,** read from the index with `git cat-file --batch`, so
    a term staged and then removed from the working copy is reported as `path (staged):line`.
    A repository with no commits yet now passes the message check instead of crashing; the
    staged-content test found this.
  - **Hygiene also hashes camel-case words and digit groups inside each run,** so `myTermNotes`
    and `term2026` are caught.
    - A term inside an all-lowercase run joined to another word is still missed.
    - Matching every substring would flag ordinary words that contain a short term, and a hit
      cannot name the term to explain itself.
  - **One `EXPECTED_VERSION` in `tests/test_version.py`** holds the three version expectations.
    The handoff names it as the fourth place a version bump touches.
  - **The stdio test matches replies by `id`,** skipping notifications, within one 30 s deadline.
  - **A stage that cannot start fails on its own:**
    - no uv, or a package missing from `uv.lock`, raises `SetupError`;
    - a command that cannot be run reports as failed;
    - the other stages and the summary still run.
  - **The `[0.1.0]` link reference** is added to `CHANGELOG.md`, as agreed at plan time.
  - **Falsified.** Each failed when broken and passed once restored:
    - `from .. import krita_adapter` in `bridge_core` (core purity);
    - `import imp` (removed modules);
    - `getattr(object(), 'save' + 'As')` (banned call);
    - `exec` added to the banned attributes (allowed uses);
    - the code-module list emptied (banned uses found);
    - the core-purity rule disabled (import rules refuse);
    - the adapter exemption removed (import rules allow);
    - the sub-token pass removed (joined terms);
    - the staged scan dropped (staged content);
    - the no-commit guard removed (same test);
    - `all()` over a generator restored (every command runs);
    - `SystemExit` instead of `SetupError` (uv missing);
    - the setup catch removed (stage fails alone);
    - `EXPECTED_VERSION` changed (three version tests);
    - the initialize reply awaited under the wrong id, which failed by its 30 s timeout and left
      no server behind.
  - **Numbers after the review:**
    - `verify`: 6 stages, all PASS;
    - 54 server tests passed, 0 skipped (+5);
    - 47 plugin-core tests passed, 0 skipped (+42, most of them snippet cases).

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
- **The owner's step.** After `install-plugin`, the owner restarts Krita, enables the plugin in
  *Configure Krita › Python Plugin Manager* (on macOS, in the application menu), and restarts it
  again. Until the bridge answers, the session asks the owner for every restart; once it answers,
  the session restarts Krita itself when it is safe (decision 21).
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
  only when the bridge reports no unsaved documents; with no bridge yet, or any unsaved document,
  ask the owner (decision 21). The health answer should expose what the restart check needs.
- **Apps launched from the Dock don't inherit `PATH`.** Client registrations use absolute paths.

**Done (2026-10-23, 0.2.0).**
- **Decided with the owner at the start:**
  - **The `edit_undo` probe runs on a throwaway document of its own,** and only when no
    document has unsaved changes. Otherwise it is skipped and recorded as skipped.
- **The plugin.**
  - **The files.** `krita_art_mcp_bridge.desktop` sits beside the package. The package
    `__init__.py` only registers the extension.
  - **`bridge_core`** (pure stdlib):
    - `jobs.py`: one `threading.Condition` guards every state change. `drain()` carries the
      `job_active` re-entry guard and refuses to run off the main thread. Cancel acts only on
      queued jobs, and `stop()` fails the queue with `CANCELLED`.
    - `server.py`: a `ThreadingHTTPServer` on `127.0.0.1:0`, with daemon threads, a backlog of 64
      and a 10 s handler timeout.
      - It checks, in order: `Host`, the token (as bytes, with `hmac.compare_digest`), 503 while
        stopping, then the body (411 with no length or when chunked; 413 over 64 MB, before
        reading).
      - Its four endpoints are as PDD Part 8.
    - `bridge.py`: `start()` and `stop()` in PDD Part 8's order. `shutdown()` runs only while the
      serve thread is alive.
    - `bridge_file.py`: 0600, written through a temp file and `os.replace`. Single instance by a
      live pid whose name is `krita`. It deletes the file only when the file is its own.
    - The rest: `log.py` (5 MB rotation, the token redacted from the formatted text),
      `capabilities.py`, `source_hash.py`, `errors.py`, and `paths.py` with `private_dir`.
  - **`krita_adapter`:**
    - `extension.py`: `setup()` and the `applicationClosing` stop, each wrapped in a catch-all
      that logs. It activates the Notifier if it is inactive.
    - `main_thread.py`: the `Waker` queued signal, with an `@pyqtSlot` drain.
    - `runtime.py` and `ops.py`.
- **The server.**
  - `bridge_client.py`: `BridgeClient.call` and `.operation` return `Done`, `Failed` or
    `Pending`.
    - It pins the bridge for each call, and maps every bridge failure as the plan set out.
    - After a send, a lost bridge is `INTERNAL_ERROR` with `outcome: "uncertain"`.
  - `tools/__init__.py`:
    - `ExactArguments` passes the client's arguments through untouched.
    - The runner holds a lock, so each server process serialises its calls. It validates the
      arguments (Draft 2020-12), catches every exception, and checks each result against its
      schema and 6 MiB.
    - `TOOLS` and `BUILT_TOOLS = ["krita_server_info"]`.
  - `tools/observe.py` has `krita_server_info`. `envelope.py`, `errors.py` and
    `instructions.py` (936 characters) complete it.
  - **The schemas.** The envelope is amended in all 19 by a one-off script, not committed.
- **The CLI.** `install-plugin` (`install.py`, `plugin_files.py`), and `doctor` (`doctor.py`,
  `setup_checks.py`, shared with the `KRITA_NOT_RUNNING` hint).
- **The probe.** `probe/__init__.py`.
  - It owns `<data dir>/harness/`: it sweeps the folder at start, and an `ExitStack` sweeps it at
    the end.
  - It checks the plugin hash first and stops on a mismatch, then health, stdio, H4 and the
    runtime probes.
- **Amendments:**
  - **The restart check is an op, not part of health.** The block suggested the health answer
    expose it. But health is cached at start, and a document's modified flag needs the main
    thread. So `bridge.unsaved_documents` exists, and `doctor` prints its counts. Settled in the
    plan.
  - **`doctor` prints those counts whichever step fails.** The check matters most when the
    plugin is stale, which the first live restart showed. The session's own finding.
  - **Protocol 1 carries more than PDD Part 8 lists:**
    - every reply carries `session_id`, `operation_id` and `request_id`;
    - one error body serves every refusal;
    - `wait_s` is capped at 10 s;
    - cancel answers a `cancelled` flag;
    - `/v1/health` answers in the common reply shape;
    - `bridge.json` gained `session_id`, which SPEC §4's Bridge entity lacks.

    These are so that Session 3's dedup, lease and uncertain outcome need no new protocol.
    Settled in the plan, after its design review.
  - **The envelope amendment also closes the error codes and the `cancelled` status:**
    - `error.code` is an enum of the 30 Phase 1 codes;
    - `failed` and `cancelled` require an error and null data.

    Beside them, `api_version` is `"0.2.0"` and `revision` is always null. Settled in the plan.
  - **`krita_server_info`'s data.**
    - It is `{session_id, server_version, plugin_version, protocol, krita_version, qt_major,
      capabilities, limits}`.
    - Dropped: `profile_schema_version`, `unsupported` and `edit_timeout_seconds`.
    - `allowed_roots` joins with roots in Session 4.

    Settled in the plan.
  - **The 3.10 mypy run checks `-p krita_art_mcp_bridge`,** with `plugin` on `mypy_path`, so
    the adapter's relative `..bridge_core` resolves. Per-module overrides cover `krita` and
    PyQt. The previous handoff foresaw it.
- **Measured** (Krita 5.3.4 on macOS, Apple Silicon):
  - **The runtime.**
    - `Krita.instance().version()` is `"5.3.4.1 (git bd6e8d0)"`.
    - Python 3.13.5, PyQt 5.15.11, Qt 5.15.7.
    - `Node.paintPolylineStroke` is absent.
    - `Extension.setup()` runs on Python's main thread.
  - **H4 idle**, 500 `krita_server_info` calls over stdio, in three runs:
    - p95 5.5, 4.9 and 5.3 ms;
    - p50 4.5 to 4.9 ms;
    - max 7.9 to 48.1 ms;
    - 0 failed.
  - **`edit_undo`'s text is `Undo <top label>`.**
    - After adding a layer it read `"Undo Add Layer"`.
    - It is `"Undo"` at Krita start, and `"Undo "` once a document has closed.
    - The tooltip, `"Undo last action (⌘Z)"`, carries no label.
    - **Read straight after `waitForDone()`, it was stale (`"Undo "`) in 2 of 7 reads,**
      whether or not Krita was frontmost. The label updates asynchronously, so the rollback
      label check of block 9 cannot read it straight after the step.
  - **Seven create, layer and close cycles** of a 64 × 64 never-saved document: no crash.
  - **Shutdown.** Once the Notifier is activated, `applicationClosing` fires on quit. The log
    shows the bridge stopped, and `bridge.json` is gone.
  - **`osascript … quit` returns "User canceled (-128)"** even when Krita quits cleanly.
  - **The data dir.** Created as the log's parent, it came out 0755. `private_dir` now makes it
    0700, which a test holds.
  - **Krita's bundled `python3.13` cannot run on its own,** because its `Python.app` is not
    shipped.
  - **mcp 2.3.0.**
    - It dispatches tool calls concurrently.
    - It never validates input over stdio.
    - A `FuncMetadata` subclass that overrides `validate_arguments` passes arguments
      unchanged.
  - **Python 3.13's `socketserver`.**
    - `shutdown()` waits forever unless `serve_forever` runs.
    - Daemon handler threads are never joined.
- **Checked by hand:**
  - **The plugin-enable flow.** The owner restarted Krita, enabled *Krita Art MCP Bridge*,
    and restarted it again. The bridge answered on its first load.
  - **N-03.** Krita idle with the plugin loaded: 0.0% CPU in six `top` samples 5 s apart, as
    without the plugin. The owner's own look in Activity Monitor is in `docs/BACKLOG.md`.
  - **A restart under decision 21.**
    1. `doctor` reported 0 unsaved documents.
    2. Krita was quit with `osascript` and relaunched with `open -a krita`.
    3. The new plugin answered, and `doctor` passed all five steps.
- **Falsified:** 62 checks, each broken in the product code. Each failed at its own test, and
  passed again once the file was restored byte for byte. Each break:
  - **The HTTP refusals.**
    - `Host`;
    - the token;
    - the token compared as text;
    - the body cap;
    - the chunked and length refusals;
    - 503 while stopping;
    - the reply ids;
    - the health snapshot;
    - the cancel flag;
    - the 404;
    - `localhost`;
    - the malformed call.
  - **The jobs.**
    - FIFO;
    - the re-entry guard;
    - cancel acting on queued jobs only;
    - stop refusing new jobs;
    - the main-thread check;
    - an exception becoming `INTERNAL_ERROR`;
    - an unknown op;
    - a resent id.
  - **The lifecycle.**
    - The 0600 mode;
    - the atomic replace;
    - single instance;
    - deleting only its own `bridge.json`;
    - the stop order;
    - stop with no serve thread;
    - the token redaction;
    - the rotation size;
    - the private data folder.
  - **The core.**
    - The matrix's shape;
    - nothing supported before it is built;
    - the hash skipping caches;
    - known codes only;
    - a 3.11 import in the adapter, which failed `types` alone.
  - **The server.**
    - The constants and the hashes agree;
    - the error and pending envelopes;
    - the `cancelled` status;
    - the instructions' length, and that they are served;
    - built tools only;
    - exact arguments;
    - argument validation;
    - a raising tool;
    - result validation and size;
    - call serialisation.
  - **The client.**
    - Done;
    - running after the budget;
    - polls capped at the budget;
    - error passthrough;
    - the missing step named;
    - a stale or malformed `bridge.json`;
    - a refused connection, retryable or after Krita died;
    - the protocol mismatch;
    - the silent bridge;
    - each of the four uncertain cases;
    - a refused connection while polling;
    - `krita_server_info`'s data, missing step and pending result.
  - **The commands.**
    - `install-plugin`: caches skipped, the old copy removed, the restart-only message, a
      missing folder;
    - `doctor`: the step order, the hash steps (installed and running), the `.desktop` file,
      the kritarc parsing, and the document counts reported or held back;
    - the probe: the stale-plugin stop, both sweeps, and the health failure.
  - **Tests strengthened while falsifying,** where the first version passed for the wrong
    reason:
    - the chunked case now sends a length;
    - kritarc's "not enabled" case writes `=false`;
    - the malformed-`bridge.json` case checks its message;
    - the probe records what it saw at start;
    - a mid-call stop must be uncertain.

    Tests added for gaps the falsification found:
    - another session's `bridge.json` is left alone;
    - a bridge that stops listening mid-call;
    - a stale installed copy.
- **Numbers:**
  - `verify`: 6 stages, all PASS;
  - 120 server tests passed, 0 skipped (+66);
  - 85 plugin-core tests passed, 0 skipped (+38);
  - `probe`: 10 PASS, 0 FAIL, 3 MEASURED;
  - 1 registered tool; 19 schema files.
- **Review (`/code-review high`), 10 findings: 7 fixed and 3 skipped.**
  - **A bridge that fails after its serve thread starts now stops itself.** `Bridge.start`
    stops and re-raises if writing `bridge.json` fails. The extension hooks `applicationClosing`
    before it starts the bridge, so any part that ran is stopped at quit.
  - **`doctor` reports a protocol mismatch at step 5, with the reinstall fix.** It used to call
    it an unreachable bridge, with "restart Krita".
  - **A client that left before its reply is not logged as a failure.** `BrokenPipeError`,
    `ConnectionResetError` and `TimeoutError` go to debug, so polls that time out during a long
    call no longer flood `plugin.log` with tracebacks.
  - **Validation messages are cut to 200 characters.** jsonschema quotes the offending value,
    which could push an `INVALID_ARGUMENT` past 6 MiB and turn it into `INTERNAL_ERROR`.
  - **`doctor` waits at most 5 s** for the document counts, not the 45 s budget.
  - **`setup_checks.plugin_current` is the one check of the running plugin** (invariant 11),
    shared by `doctor` step 5 and the probe's first check.
  - **The instructions read the wait budget from `WAIT_BUDGET_S`.**
  - **Skipped:**
    - a resent `operation_id` with other arguments returns the first operation. Ids are
      server-minted UUIDs, and conflicts belong to Session 3's `request_id` dedup;
    - operations are kept for the whole Krita session. How long to keep them is Session 3's
      call, alongside dedup, which needs them for that session;
    - `/bin/ps` runs on every call. It guards against sending the token to a process that
      reused Krita's pid.
  - **Falsified:**
    - start failing to publish;
    - quiet disconnects;
    - the protocol-mismatch step;
    - short messages;
    - the budget in the instructions;
    - the shared plugin check.

    Each failed at its own test, and passed once restored.
  - **Numbers after the review:**
    - `verify`: 6 stages, all PASS;
    - 122 server tests passed, 0 skipped (+2);
    - 87 plugin-core tests passed, 0 skipped (+2);
    - `probe`: 10 PASS, 0 FAIL, 3 MEASURED, on the reinstalled plugin after a self-restart
      (0 unsaved documents).

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

**Done (2026-10-24, 0.3.0).**
- **Decided with the owner at the start:**
  - **The probe's document checks run only when no Krita document has unsaved changes.**
    Otherwise they FAIL with "save your documents first".
  - **A created document reports `mode: "new"`.** Modes are `new`, `working_copy` and
    `read_only`.
  - **Only calls that carry a `request_id` are journaled.** Reads are not.
  - **Invariant 9 gains a 7-day window across Krita restarts.** It is an owner amendment, noted
    beside invariant 9 in `SPEC.md`. Within one Krita session the bridge dedups however old the
    id.
- **A design review in plan mode found nine holes;** the plan folded in their fixes:
  - the alias of a retry's own operation id;
  - non-200 answers counted as not submitted;
  - the lease passing only on proof;
  - bridge conflicts that do not bind an id;
  - the three 404 cases of `operation_get`;
  - op args as a pure function of the tool arguments;
  - the window as an owner decision;
  - `addView` before any check, with cleanup on failure;
  - retryable meaning "changed nothing".
- **The plugin.**
  - **`bridge_core/jobs.py`.**
    - A `request_id` names one operation for the Krita session. Its `args_sha256` is the SHA-256
      of canonical `{op, args}`.
    - A duplicate returns the original operation, and its own `operation_id` becomes an alias of
      it. Other arguments answer `REQUEST_ID_CONFLICT`.
    - A retryable failure releases the id but keeps its hash bound. A reused `operation_id` is
      `INVALID_ARGUMENT`.
    - `stop()` fails queued calls as retryable `CANCELLED`, because they never ran.
    - Finished operations are kept for the session, with their args dropped.
    - Handlers receive a `Call` (`operation_id`, `request_id`, `client`). Every reply carries
      `op`.
  - **`server.py`** requires `client = {pid, started_at}`, with a non-empty start time. A call's
    reply follows the operation it submitted.
  - **`bridge_core/registry.py`** holds the handles:
    - a random `doc-` id;
    - a strong reference to the wrapper;
    - `owned`, `mode`, `dirty`, `unsafe` and `lease`.

    `sync()` matches wrappers by `==`, prunes documents that are gone, and gives the owner's
    documents `read_only` handles. `guarded()` runs, in order:
    1. the job-start refusal;
    2. the lookup;
    3. `DOCUMENT_READ_ONLY`;
    4. `DOCUMENT_UNSAFE`;
    5. the lease;
    6. the handler;
    7. `dirty`.
  - **`bridge_core/documents.py`** has the ops `document.create`, `document.list` and
    `document.close`, behind a port.
  - **`bridge_core/processes.py`** runs `ps` with `LC_ALL=C TZ=UTC`, and holds `holder_alive`
    and `is_live_krita`, which moved there from `bridge_file`.
  - **`krita_adapter/documents.py`** implements the port.
- **The server.**
  - **`journal.py`.** The day file is 0600 in a 0700 folder. Each line is written in one
    `os.write` under `flock`, after a newline if a crashed writer left a partial line.
    - It indexes the last 7 UTC days and follows appended lines.
    - Each attempt's outcome is `receipt`, `no_effect`, `not_sent`, `conflict` or `unknown`.
      `receipt` and `no_effect` settle every attempt the bridge deduplicated in that session.
      `not_sent` and `conflict` settle only their own attempt.
  - **`tools/dispatch.py`** checks, in order:
    1. a conflict;
    2. a receipt;
    3. uncertain under another Krita session, checked in `before_send`;
    4. otherwise it journals and sends.
  - **`bridge_client.py`** gains:
    - `before_send`, an adopted `operation_id`, and `Failed.submitted`;
    - `request_id` and `session_id` on outcomes;
    - `operation(sent_in=)`, which is strict for unknown ids and uncertain across sessions;
    - `cancel()`;
    - no send without a start time.
  - **The runner** passes `ToolCall(bridge, journal, client_name)`. The client name comes from
    the MCP `initialize`.
  - **`paths.server_data_dir()`** honours `KRITA_ART_MCP_DATA_DIR`.
  - **The tools** are `tools/documents.py` and `tools/operations.py`. `RECEIPTS` maps ops to
    receipts.
- **The schemas.**
  - **`guard`** is `{document_id, request_id}` in the 8 schemas that carry it, with its examples
    amended. A test holds every copy identical, and `expected_revision` absent everywhere.
  - **The five tools are amended** as the plan set out.
  - **The amendment was made by a one-off script,** which is not committed.
- **The probe.**
  - Each `serve` gets `KRITA_ART_MCP_DATA_DIR=<harness>/server-a|server-b`.
  - It runs the 13 new checks only after the unsaved gate.
  - It sweeps probe-named, bridge-made documents at start and end.
- **Amendments:**
  - **A retryable failure releases its `request_id`.** Without that, a call refused while a
    dialog was open could never run under its id. Settled in the plan.
  - **The lease goes to the creator.** PDD Part 4 says the first process to mutate; create is
    taken as that first mutation, or a second process's close would take the lease. Settled in
    the plan.
  - **Create's other models and backgrounds are `INVALID_ARGUMENT`** through the contract's
    enums. The block says `UNSUPPORTED_CAPABILITY`; PDD names depths only. Settled in the plan.
  - **`operation_get` drops `result_uri`,** a Phase 3 resource URI, as well as `rollback_state`.
    Its data is `{operation_id, tool, state, progress, receipt}`. Settled in the plan.
  - **Close's `baseline_untouched` is `boolean | null`,** null without a source. Settled in the
    plan.
  - **Protocol 1 gains `op` in operation replies, and a stricter `client`.** Both are additive.
    Settled in the plan.
  - **`MULTIPLE_WINDOWS` is retryable on both sides.** The owner closes the window and the call
    can run. Settled in the plan.
  - **`Krita.createDocument` makes an opaque white "Background" layer,** not a transparent one.
    The plugin replaces it with a new paint layer, "Layer 1", through `Node.setChildNodes`,
    which pushes no undo step, so undo cannot bring the white back. It then checks that layer's
    opacity, and the alpha of its pixel (0, 0). Found from Krita's source
    (`libs/libkis/Krita.cpp`, `KisDocument::newImage`, `Node::setChildNodes`) while building.
  - **A poll waits on a 404 until the bridge has answered once.** The bridge keeps every
    operation for its session, so a 404 before an answer means the call is not registered yet.
    Before, `operation()` reported such a call as uncertain. Found by falsification.
  - **`krita_operation_get` writes a finished line only for an attempt still open.** The probe
    found it writing a second one. Found by the live probe.
- **Measured** (Krita 5.3.4 on macOS, Apple Silicon):
  - **20 create and close cycles, no crash,** in four runs. Each cycle took 149 to 150 ms on
    average, 156 to 166 ms at most. `krita_document_close` stays (decision 8).
  - **A new document's profile is `sRGB-elle-V2-srgbtrc.icc`.** It is RGBA / U8, and its
    initial layer is transparent at opacity 255.
  - **libkis `Document` wrappers compare by document with `==`.** Two lists give one stable id.
  - **H4 idle:** p95 5.7 to 7.2 ms.
  - **Twice, the owner was working in Krita during the session.** The probe's job-start check
    refused with `KRITA_MODAL_DIALOG` each time, as designed. The owner also saved before the
    document checks ran.
- **Falsified:**
  - **The method.** Each check was broken in the product code. It failed at its own test, then
    was restored and compared byte for byte.
  - **Plugin core, 30 checks.**
    - Dedup, the alias, the conflict and key-order hashing.
    - Release on a retryable failure, with the hash kept.
    - `stop()`'s retryable cancel, args dropped, `op` in replies, a reused operation id, the
      handler's client.
    - The client shape, and the reply following its own operation.
    - The owner's documents not owned, pruning, and the lease refusing a live holder.
    - The holder never asked about itself, dirty on success only, unsafe, and read-only writes.
    - The job-start refusals, random ids, create's cleanup, the transparent-layer check, and
      the profile refusal.
    - Close refusing dirty and close confirmed.
    - The start-time compare, and a failed `ps` keeping the lease.
  - **The server, 30 checks.**
    - The journal before the send, the receipt from the journal, and both conflict sides.
    - A conflict not binding, uncertain never re-sent, and the `not_sent` and `no_effect`
      outcomes.
    - `submitted` only on 200, the adopted id, and the three 404 cases.
    - The start time required, `operation_get` finishing a call, receipt validation, and
      cancel refusing a running op.
    - The 7-day window, following appended lines, the newline after a cut line, and a newer
      version refused.
    - The private file, outcome settling (both ways), the data-dir variable, and the server's
      depth refusal.
    - The lease end to end, `guard` identical, no `expected_revision`, the sRGB constants, and
      no second finished line.
  - **The probe, live, 11 of its 13 new checks.**
    - **By real failures:** create and the 20 cycles (both refused by a modal dialog), and the
      journal line count.
    - **By breaks in the server:** list, `operation_get`, cancel, the unsaved gate, the retry,
      the conflict, the 16-bit refusal and close.
    - **Lease and unknown id** are plugin-side; they are falsified in the unit tests, and were
      not reinstalled to break them live.
  - **Tests strengthened while falsifying:**
    - the release test now conflicts before the retry;
    - the tail test has the file before the first lookup.

    Tests added for gaps:
    - a retry of a running call follows the original;
    - no send without a start time;
    - a receipt that breaks its schema;
    - outcome settling;
    - a poll waiting for a late registration;
    - no second finished line.
- **Numbers:**
  - `verify`: 6 stages, all PASS;
  - 163 server tests passed, 0 skipped (+41);
  - 138 plugin-core tests passed, 0 skipped (+51);
  - `probe`: 23 PASS, 0 FAIL, 4 MEASURED;
  - 6 registered tools; 19 schema files.
- **Review (`/code-review high`), 10 findings, all fixed at the owner's request.**
  - **A malformed journal line no longer stops every journaled call.** A line that parses but
    lacks a field, or names an unknown phase or outcome, is skipped. All its fields are read
    before the index changes. The read offset now moves line by line, so a line that stops a
    read is never applied twice.
  - **Create gives the view to Krita's one window,** `windows()[0]`, not `activeWindow()`,
    which can be None.
  - **Create makes "Layer 1" the active node** (`setActiveNode`, after `addView`). It then
    checks that the layer is active, beside its opacity and its pixel.
  - **`build_server` needs a journal.** Every test passes a temporary one, so no test can write
    the owner's journal.
  - **A test holds the two `PS_ENV` copies equal,** because the lease depends on both sides
    formatting start times alike.
  - **The client remembers only calls it left running,** not every call it ever sent.
  - **The runner passes the client's name in one step,** not through two wrappers.
  - **The changelog says calls are refused,** not that they wait, while a dialog is open.
  - **The handoff no longer names a dialog nobody saw.**
  - **The journal's window comment carries no amendment date.**
  - **Falsified:**
    - the skipped malformed line;
    - the per-line offset;
    - the client remembering only running calls;
    - the `PS_ENV` agreement;
    - the active initial layer.

    Each failed at its own test, and passed once restored.
  - **Numbers after the review:**
    - `verify`: 6 stages, all PASS;
    - 169 server tests passed, 0 skipped (+6);
    - 139 plugin-core tests passed, 0 skipped (+1);
    - `probe`: 23 PASS, 0 FAIL, 4 MEASURED, on the reinstalled plugin after a self-restart
      (0 unsaved documents).

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

**Done (2026-10-24, 0.4.0).**
- **Decided with the owner at the start:**
  - **KRA fixtures come from `harness.export_kra`.** Krita's own exporter writes them, from a
    server-written ORA opened in the harness folder.
  - **Open refuses documents that are not RGBA / U8** with `COLOR_PROFILE_MISMATCH`, cleaned up
    in the same job. Any RGB profile is accepted.
  - **Layer types use the contract's short names** (`paint`, `group`, `selection_mask`…), mapped
    from Krita's; an unknown type passes through as Krita names it.
  - **Inspect leaves the owner's view and active node alone.** It reads no composite pixels, so
    K46 runs where the composite is read: open's baseline now, captures and saves later.
- **A design review in plan mode found one blocker and fourteen smaller holes;** the plan folded
  in their fixes:
  - the blocker: tests would have read the owner's `config.json` and `transfer/`;
  - cleanup from the moment the copy exists, and an unclosable document kept as an owned,
    unsafe handle;
  - a baseline written before its transfer file goes;
  - a plugin-sent `baseline_id` checked before it names a file;
  - inspect's second poll answered, not raised;
  - K46 confirmed by re-reading the active node;
  - binary-alpha fixtures for exact composites;
  - escapes that can reach nothing;
  - roots never re-checked for a call still unsettled;
  - `O_EXCL` instead of `os.link`;
  - the realpath's extension;
  - the source hashed before a close;
  - 3.10 and source-scan traps;
  - the orphan sweep off the startup path.
- **The plugin.**
  - **`bridge_core/roots.py`** reads `config.json` on every check. The roots are the config's,
    realpathed, plus the harness folder.
  - **`bridge_core/transfer.py`** writes `BGRA8` and `A8` files at 0600 in a 0700 `transfer/`,
    sweeps it at bridge start (after the single-instance check), and reads a server mask once,
    checked against its SHA-256.
  - **`bridge_core/opening.py`** is `document.open`, in this order:
    1. the argument rules and the roots;
    2. the copy, or the read-only hash;
    3. `port.open`;
    4. the colour space;
    5. K46;
    6. the tree;
    7. the editable lists;
    8. the composite;
    9. the baseline id;
    10. registering it, last.
  - **`bridge_core/files.py`** copies under `O_EXCL` while hashing, then re-reads the copy.
  - **`bridge_core/inspection.py`** is `document.inspect` and the layer entry shared with open.
  - **`bridge_core/harness.py`** is `harness.export_kra` and its folder gate. It takes no lease.
  - **`bridge_core/port.py`** holds the port protocol.
  - **`Registry.discard`** closes a document a failing job made, or keeps it owned and unsafe.
    Create uses it too.
  - **`Handle`** gains `path`, `source_path`, `source_sha256`, `baseline_id`, `protected`,
    `allowed_mask`, `preserve_composite_alpha` and `preserve_canvas`.
  - **`document.close`** returns `baseline_id`, and `baseline_untouched` from a re-hash.
    `document.baselines` lists the live ids. `server_info` reads `allowed_roots` on every call.
  - **The adapter** gains `open` (batch mode, `addView`), `tree`, `prepare_read` (K46),
    `composite`, `selection` and `export_kra` (`exportImage`).
- **The server.**
  - **`paths.Places`** holds the config, transfer, harness and baselines folders.
    `build_server(client, journal, places)` requires it.
  - **`roots.py`** has the config, the check and the CLI.
  - **`transfer.py`** has `take` (`O_NOFOLLOW`, folder and size checks, BGRA to RGBA),
    `discard` and `put_mask`.
  - **`baselines.py`** has `adopt` (PNG through `mkstemp` and `os.replace`, then the transfer
    file goes), `remove` and `sweep`.
  - **`tools/documents.py`** has open, inspect, and the `resolve_*` steps that turn transfer files
    into data before a receipt. `RESOLVERS` runs them for `krita_operation_get`.
  - **`journaled`** gains `precheck`.
  - **`serve()`** sweeps orphaned baselines on a daemon thread.
  - **`doctor`** gains step 6.
- **The schemas:** `krita_document_open`, `krita_document_inspect` and `krita_server_info`
  (`allowed_roots`), each amended by a one-off script, not committed. 8 tools are registered.
- **The probe.**
  - Report helpers move to `probe/report.py`.
  - The file checks are in `probe/opening.py`.
  - The ORA and PNG writer is `probe/fixtures.py`.
  - The sweep also closes leftover documents whose path lies in the harness folder, through both
    servers.
- **Amendments:**
  - **Fields beyond PDD Part 4.**
    - Open and inspect carry `mode`, `path`, `source_path`, the colour space,
      `active_layer_id` and `baseline_id`; inspect carries `unsafe` too.
    - A flat list with `parent_id` and `order` stands in for "children".

    Settled in the plan.
  - **The editable lists are tied to the format.** Ids are for KRA only, names for ORA and PNG
    only. A name matching several layers is `INVALID_ARGUMENT`, stricter than decision 27. A
    `read_only` open refuses `working_dir` and both lists, by schema conditionals. Settled in
    the plan.
  - **A missing `working_dir` is made,** after the root check. Settled in the plan.
  - **`allowed_roots` leaves out the harness folder,** so agents never work where the probe
    sweeps. The plugin reports it from the same `config.json`, so the receipt stays a function of
    the outcome. The leaving-out was settled in the plan; the plugin reporting it was found while
    building.
  - **The roots step is doctor's step 6,** after the bridge, so the `KRITA_NOT_RUNNING` hint is
    unchanged. Settled in the plan.
  - **`journaled` gains `precheck`;** create shares the owned-unsafe fallback. Settled in the
    plan (review).
  - **Transfer files are resolved before the receipt.** `resolve_*` adopt, read or remove them, so
    receipts stay pure functions of the outcome. Found while building.
  - **`allowed_change_mask` is null-only** until Session 7 defines its summary. Settled in the
    plan.
  - **Protocol 1 gains four ops,** `document.open`, `document.inspect`, `document.baselines` and
    `harness.export_kra`, plus `allowed_roots` in `server_info`'s result. All additive. Found
    while building.
  - **A baseline whose transfer file another server took is a one-line warning.** The probe's
    retry through server-b, with its own data folder, showed a traceback. Found by the live probe.
- **Measured** (Krita 5.3.4 on macOS, Apple Silicon, 64 × 48 fixtures):
  - **Krita's ORA loader sets the layer offset.** A layer at x=8, y=12 reports `offset_px`
    `[8, 12]`, and `Node.bounds()` gives its exact bounds, `{8, 12, 20, 16}`.
  - **What the ORA attributes become:** `edit-locked` is `locked`, `svg:src-atop` is
    inherit-alpha, `svg:multiply` is `multiply`, and opacity 0.5 lands within 1/255.
  - **A PNG opens as one layer named "Background".**
  - **A fresh open is not marked modified** (0 of 1 unsaved), so no flag is cleared.
  - **A fresh document has no selection** (`None`).
  - **Baselines are byte-exact:** the PNG's equals its pixels, the ORA's the fixture composite,
    and the KRA's (exported from that ORA) the ORA's.
  - **Layer ids:** a KRA keeps them across two opens, and an ORA's are new at every open.
  - **No harness file appears in kritarc's recent files.**
  - **Open and create times.** `read_only` opens took 129–190 ms. The create and close cycle
    took 142–152 ms. Two consecutive runs of the build before the last measured a mean of 690
    and 704 ms per cycle, and the second 685–739 ms per open, while the runs before and after
    them measured 142–190 ms. The cause is not known, and it did not recur.
  - **H4 idle:** p95 5.4 ms.
  - **After every probe run,** `transfer/` and `harness/` were empty, no document was left open,
    and `plugin.log` held no error.
- **Checked by hand:**
  - **Two self-restarts under decision 21.** The first had 3 open documents, 0 unsaved; the
    second 0 and 0. Both used `install-plugin`, `osascript` quit and `open -a krita`.
  - **`doctor` after the restart:** steps 1–5 PASS, and step 6 FAILs with "no roots". The owner
    has added none, and a session never runs `roots`.
- **Falsified:**
  - **The method.** Each check was broken in the product code by a script, failed at its own
    test, and was restored by copying the file back and comparing bytes.
  - **The unit tests, 100 checks.**
    - Roots on both sides:
      - realpath, the harness folder, NUL bytes and `/`;
      - the config's privacy, versions and agreement;
      - `roots add`, and a broken config never overwritten.
    - Transfer:
      - the swap and the A8 read;
      - the size, folder, `O_NOFOLLOW`, directory and format refusals;
      - the sweep;
      - the mask's name, its deletion, and its hash, folder and size checks.
    - Baselines:
      - adopt's order and the kept file;
      - the id check;
      - the sweep's listing order, Krita closed, and a bridge that cannot say;
      - the warning.
    - Open:
      - the copy's name, `O_EXCL`, the made folder and the source's folder;
      - both hashes;
      - the plugin's root and realpath-format checks;
      - the editable lists and their refusals;
      - every cleanup path, and the unsafe fallback (create's too);
      - the job-start refusal before the copy;
      - `baseline_untouched` and `document.baselines`.
    - Inspect:
      - protection for created, owner and opened documents;
      - no K46 and no lease;
      - the type map, frame 0 and the selection file;
      - the job-start refusal.
    - Harness:
      - no lease;
      - both folder gates and the owner's documents;
      - no overwrite, and `BUSY`.
    - The bridge:
      - the start sweep, after the single-instance check;
      - `allowed_roots`.
    - The server tools:
      - adoption and removal;
      - the request id;
      - the precheck and its unsettled skip;
      - the server's own refusals;
      - `RESOLVERS`;
      - inspect's counts, discard, frame and retryable gone file;
      - the start sweep.
    - doctor step 6, the fixture writer, and the shared layer shape.
  - **The probe, live, 13 of its 22 new checks,** each by a break in the server code:
    - `allowed_roots`;
    - the six round trips;
    - the three byte-exact baselines;
    - both id checks;
    - the editable lists;
    - the hash mismatch;
    - the server's escapes;
    - the retry;
    - frame 1;
    - the untouched fixtures;
    - kritarc, through a fake kritarc in the driver.

    The other three are plugin-side (the export, its refusals, the bypassed symlink). They are
    falsified in the unit tests and were not reinstalled to break them live.
  - **Tests strengthened while falsifying:**
    - the source-hash test names which file differed, because the copy's re-read had masked it;
    - `is_symlink` went, and `O_NOFOLLOW` is the one guard;
    - `_open` registers last, and a failing `new_id` makes the transfer cleanup reachable;
    - the server's refusals (`working_dir` beside the source, frame 1, the probe's escapes) must
      carry no `operation_id`, because the plugin's own refusal had masked them.

    The order "editable lists before the composite" is not checked: cleanup makes it invisible,
    so it is efficiency only.
- **Numbers:**
  - `verify`: 6 stages, all PASS;
  - 243 server tests passed, 0 skipped (+74);
  - 194 plugin-core tests passed, 0 skipped (+55);
  - `probe`: 45 PASS, 0 FAIL, 9 MEASURED (+22, +5);
  - 8 registered tools; 19 schema files.
- **Review (`/code-review high`), 9 findings, all fixed at the owner's request.**
  - **A document Krita opened but could not show is never stranded.** The adapter's `open` now
    stops at `openDocument`, and a new port step, `show` (`addView`, `waitForDone`), runs under
    the core's cleanup. A failed close there keeps the document owned and unsafe, as every other
    failure does.
  - **A source that cannot be read leaks no descriptor.** The copy wraps its `O_EXCL` descriptor
    before it opens the source.
  - **A full disk is `IO_ERROR`.** `transfer.write` maps an `OSError` from the folder, the open or
    the write.
  - **Baselines are `.npy` arrays,** not PNGs. Writing one runs at disk speed inside the call's
    time, where a PNG encode of an 8k master could have pushed a reply past the client's
    timeout. `baselines.load` maps one, so previews can crop it cheaply.
  - **Transfer files no server read for an hour are removed at the next write** (`STALE_S`, the
    plugin's own `.raw` files only, never a server's mask).
  - **The composite and the selection cross as buffers.** The adapter hands over a `memoryview`
    of Krita's `QByteArray` (with `bytes` as the fallback), so a large read is never held twice.
    Which branch Krita's PyQt takes was not measured; the byte-exact baselines hold either way.
  - **`doctor`'s fix for a broken config** says to fix or delete it.
  - **A test holds the format tables equal** on both sides: the transfer layouts and the open
    extensions.
  - **`RECEIPTS` holds each op's resolver,** `Known(tool, receipt, resolve)`, so an op cannot be
    given a receipt without its resolver.
  - **Falsified:** the show step outside the cleanup, the descriptor order, a buffer refused, a
    folder error escaping, no expiry, masks expiring, a wrong `.npy`, the old fix line, drifting
    formats, and a missing resolver. Each failed at its own test, and passed once restored.
  - **Numbers after the review:**
    - `verify`: 6 stages, all PASS;
    - 244 server tests passed, 0 skipped (+1);
    - 200 plugin-core tests passed, 0 skipped (+6);
    - `probe`: 45 PASS, 0 FAIL, 9 MEASURED, on the reinstalled plugin after a self-restart (0
      unsaved documents); `transfer/` and `harness/` empty afterwards.

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

**Done (2026-10-24, 0.5.0).**
- **Decided with the owner at the start:**
  - **K46 on reads: switch only when needed.** A composite read whose document has a selection
    mask as its active node brings an agent's own document forward, makes the mask's layer active,
    reads, puts the previous view back, then writes the transfer file. An owner's document in that
    state is refused with `DOCUMENT_READ_ONLY` (`reason: selection_mask_active`) and left alone.
    Every other read touches no view.
  - **Colour maths for sRGB only.** `lab`, `lch`, `stdev_l` and greyscale captures need
    `sRGB-elle-V2-srgbtrc.icc` or `sRGB built-in`: the document's profile for a composite, the
    layer's own for a layer. Otherwise they are null, and a greyscale capture is
    `COLOR_PROFILE_MISMATCH`.
  - **Scale 1 is native.** `background` or `greyscale` there is `INVALID_ARGUMENT`.
  - **The read limit.** `limits.capture_pixels` (4096²) bounds the image; a new
    `limits.capture_source_pixels` (8192²) bounds the area read. Raised by the design review.
  - **After the live probe: keep the K46 guard, and measure the overlay.** With marching ants, an
    active selection mask changed no composite byte, so the overlay is MEASURED, while the probe
    still checks the switch, the active layer and the view put back.
- **A design review in plan mode found one blocker and 27 smaller holes;** the plan folded in
  their fixes. The blocker: composite reads of an owner's document in GrayA/U16 or LabA/U8 would
  have passed the byte count as BGRA8 and reported wrong colours. Among the rest: frame 0 checked
  against the document's current time; the fingerprint canonicalised; resolver order and
  idempotence; NaN-free discs; the real read limit; `View.setVisible` instead of `Window.showView`;
  harness ops without a lease; schema data copies held equal.
- **The server.**
  - **`colour.py`:** L\*a\*b\* with Part 12's matrix and white, L\*C\*h, hex, and the disc
    statistics.
  - **`imaging.py`:** output geometry and the transform, rendering (resample, then composite;
    checker, colour, transparent; L\* greyscale), previews from the native crop, and the
    `captures/` files and their 7-day sweep.
  - **`tools/pixels.py`:** `krita_capture` and `krita_sample`, their server rules, resolvers and
    receipts. **`tools/observe.py`:** `krita_resource_list` and the new limit.
  - **`krita_operation_get`** appends the receipt's text line and image.
  - **`envelope.MAX_RESULT_BYTES`** moved from `tools/__init__.py`; **`Places.captures_dir`** added;
    **`documents.frame_refusal`** shared by inspect, capture and sample.
- **The plugin.**
  - **`bridge_core/pixels.py`:** `capture.read` and `sample.read`, with the K46 rule.
  - **`bridge_core/resources.py`:** `resource.list`, the K21 whitelist, and the canonical
    fingerprint.
  - **`bridge_core/harness.py`:** `harness.select_mask {document_id, layer_id, rect}` and
    `harness.front_document`.
  - **The port** gains `composite_rects`, `layer_rects`, `selection_rect`, `mask_active`,
    `bring_forward`, `restore_view`, `front`, `add_active_mask`, and `current_time` in `describe`;
    a `ResourcesPort` beside it. **`krita_adapter/resources.py`** is new.
  - **`probe.preset_digests`** (a runtime probe) digests every preset's raw and canonical XML.
- **The schemas:** `source` is `{document_id, frame}` in capture, sample and preview_render;
  capture, sample and resource_list amended; `limits.capture_source_pixels`. Amended by a one-off
  script, not committed. 11 tools are registered.
- **The probe:** `probe/pixels.py`, 10 new checks and 6 new MEASURED lines; `open_args` and `sha`
  in `probe/opening.py` are now public.
- **The tests:** `World` moved to `tests/support/worlds.py`, a 3.12-only folder on pytest's and
  mypy's paths, because `tests/fixtures` stays 3.10-valid.
- **Amendments:**
  - **Resample, then composite.** The block says composite, then resample; a checker composited
    first averages to flat grey at small scales. Settled in the plan.
  - **The fingerprint is SHA-256 of `toXML()` canonicalised (C14N 2.0).** Measured: the raw digest
    changed across a Krita restart and the canonical one did not. Settled in the plan (review);
    confirmed live.
  - **Resource entries keep the contract's `id` and `sha256`,** which are paint calls'
    `preset_id` and `preset_sha256`; `supported_settings` is removed. Settled in the plan.
  - **Sample's output follows PDD Part 4's list;** the contract's `srgb_rgba`, `native_channels`
    and `native_channel_order` are replaced. Settled in the plan.
  - **A capture's `uri` lies in the data folder,** where PDD Part 4 says every `uri` is in an
    allowed root. Settled in the plan.
  - **Layer reads are paint layers only;** a selection capture with no selection is refused; a
    document showing another frame is refused. Settled in the plan.
  - **Two harness ops** for the K46 check (decision 20). Settled in the plan; `select_mask`'s
    layer and rect became arguments while building.
  - **The K46 live check measures the overlay.** The plan made `overlay_seen` a FAIL that stops
    the session; it was false, and the owner chose to keep the guard and measure. Found by the
    live probe.
- **Measured** (Krita 5.3.4 on macOS, Apple Silicon):
  - **The selection overlay:** a local selection mask made the active node of a probe document in
    front changed no composite byte (marching ants, the default display).
  - **The K46 switch:** `View.setVisible` made the document's view active, `setActiveNode` then
    took, and the previous view came back.
  - **Preset fingerprints:** 144 presets, 144 distinct ids. Raw XML digest `fab1aa54e032233b`
    before a restart and `844a95dcd1309fbc` after; canonical `d31399fb15465c79` both times; the
    listed digest `ea6a5d3b3a45fb56` both times.
  - **Resources:** 21 RGBA / U8 profiles, 13 palettes.
  - **The fixtures open as `sRGB-elle-V2-srgbtrc.icc`.**
  - **A native capture of the 64 × 48 fixture:** 36 ms through stdio.
  - **After every probe run,** `transfer/` and `harness/` were empty, no document was left open,
    and `plugin.log` held no error.
- **Checked by hand:**
  - **Two self-restarts under decision 21,** each at 0 unsaved documents (the owner saved first).
  - **`doctor` after the restarts:** steps 1–5 PASS; step 6 FAILs with "no roots".
- **Falsified:**
  - **The method.** A script broke the product code, the check's own test failed, and the file
    was copied back and compared byte for byte.
  - **The unit tests, 69 checks:** the matrix, the white, the hue range, hex rounding, negative
    zero, the achromatic hue, alpha weighting, colourless transparency, disc membership, sRGB only,
    the stdev root; half-up sides, `max_px`, comparing before converting, the per-axis transform,
    resample then composite, opaque RGB, L\* greyscale and its alpha, previews from the crop and
    their halving, private writes, 7 days, `find`; discard after writing, the preview first, the
    second lookup, greyscale needing sRGB, the resolver never raising, op ids naming files, the
    image `_meta`, the path in the text, `operation_get`'s pass-through, the four server refusals
    and the frame rule, the two copies of the read limit, samples kept and captures reused (both
    lookups at once, since the second masks the first); the shared `source` and the data copies;
    the owner's document left alone, the view put back on failure, the write after it, the
    forward step, switching only for a mask, 8-bit RGBA composites, frame 0 on screen, the
    canvas, the plugin's read cap, unknown, non-paint and 16-bit layers, clipped squares, points
    on the canvas, the radius range, a selection to capture, `render` an object; the canonical
    fingerprint, page-only fingerprints, the cursor past the end, no empty last page, the limit,
    a broken preset, the whitelist; `select_mask` in front, `front_document`'s folder.
  - **Tests strengthened while falsifying:** five passed with their check broken, and now fail:
    hue range, a preview made from a resampled image, a crash between the two writes, a PNG
    another server finished meanwhile, and the plugin's read cap (the canvas check had masked it).
  - **The probe, live, 6 of its 10 new checks,** each by a break in the server code through a
    driver running only `probe.pixels`: the native capture, the sub-rect, the checker resample,
    the refusals, the exact samples, the discs. The layer captures, the resource lists and the K46
    switch are plugin-side; they are falsified in the unit tests, and were not reinstalled to break
    them live (the owner chose to drop those restarts).
- **Known debt:** a resolver that fails without a retry (a malformed outcome) leaves its transfer
  file to the plugin's one-hour expiry; three such files came from the falsification runs.
- **Numbers:**
  - `verify`: 6 stages, all PASS;
  - 330 server tests passed, 0 skipped (+86);
  - 246 plugin-core tests passed, 0 skipped (+46);
  - `probe`: 55 PASS, 0 FAIL, 15 MEASURED (+10, +6);
  - 11 registered tools; 19 schema files.
- **Review (`/code-review high`), 10 findings, all fixed at the owner's request.**
  - **A capture or sample whose resolve fails without a retry discards its transfer file,** up to
    256 MB, instead of leaving it to the one-hour expiry. This was the known debt above.
  - **The frame rule refuses only an animated document away from frame 0.** A still document
    whose timeline was scrubbed shows the same picture at every frame, and now reads. `describe`
    reports `animated`, walking the nodes only when the current time is not 0.
  - **Open's baseline obeys the same frame rule** (`inspection.check_shown_frame`), so an as-opened
    baseline is never another frame. It runs before the composite, inside open's cleanup.
  - **A non-finite `scale` is `INVALID_ARGUMENT`,** where NaN reached `math.floor` and became
    `INTERNAL_ERROR`.
  - **`captures/` is made 0700 itself;** `mkdir`'s mode reached only the day folder.
  - **One folder that only looks like a date no longer stops the 7-day sweep.**
  - **`resource.list` refuses a `kind` that is not text** with `INVALID_ARGUMENT`, not a
    `TypeError`.
  - **A fresh capture's PNG is not read back from disk;** the maker returns its bytes.
  - **The probe's fixture comparison is one function,** `report.differs`.
  - **One rule names the filter applied,** `imaging.filter_for`, used by `render` and the
    receipt.
  - **Falsified:** both discards, no read-back, the finite scale, the private folder, the sweep,
    the animated-only rule and the rule itself, open's frame check, and the text `kind`. Each failed
    at its own test and passed once restored.
  - **Measured on the reinstalled plugin** (Krita was started, having been quit, with nothing
    open): the raw preset digest changed a third time (`54921366fb2a3653`) and the canonical one
    held (`d31399fb15465c79`); the three leftover transfer files were swept at bridge start.
  - **Numbers after the review:**
    - `verify`: 6 stages, all PASS;
    - 334 server tests passed, 0 skipped (+4);
    - 249 plugin-core tests passed, 0 skipped (+3);
    - `probe`: 55 PASS, 0 FAIL, 15 MEASURED; `transfer/` and `harness/` empty afterwards.

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

**Done (2026-10-24, no version).**
- **Decided with the owner in plan mode**, over the 27 findings of `REVIEW-2026-10-24.md`:
  - **F1 (High):** `Selection.setPixelData` becomes the scan's one exception, in one adapter
    function on a `Selection()` it built, held by an AST test; invariant 1's wording stands and
    SPEC §5 carries the owner's dated note. Amendment to block 7.
  - **F2, F3, F4, F5, F25 (Medium)** become amendments: F2 and F4 to 7, F3 to 9, F5 to 7, 8, 9,
    11 and 14, F25 to 7 and 8.
  - **The mechanical fixes** (F6–F9, F11–F20, F24, F26, F27) become one inserted session, **6a**
    at 0.6.0; sessions 7–15 shift to 0.7.0–0.13.0.
  - **F10** is measured in 9. **F23** is 7's *Ask at the start*. **F21, F22** are recorded.
    Nothing goes to the backlog.
- **The review.** `REVIEW-2026-10-24.md`: method, the baseline as found, what holds (the
  layering, every invariant traced to its enforcement and tests, the constants held equal, fit
  for Phases 2–6), 27 findings with `file:line` evidence, the drift inventory, the job system,
  transfer path and registry against sessions 7–12, where each finding landed, and the
  measurements. A second, independent cold read of the core files, without the first read's
  notes, added F24–F27 and confirmed six others.
- **The plan.** The table and the 6a block above; amendment lines in blocks 7, 8, 9, 11 and 14,
  each marked "amended by review 6"; the versions of 7–15 shifted.
- **Amendments:** none to this block. The measurements ran after the owner approved the plan,
  since `probe` drives the owner's Krita; the probe needed three runs (one gated by an unsaved
  document, one with Krita closed, one full), recorded in the REVIEW's §7.
- **Measured** (Krita 5.3.4.1 on macOS, Apple Silicon; details in the REVIEW):
  - `probe`: 13.5 s wall time; H4 p50 5.2 ms, p95 18.0 ms, max 59.5 ms on a Krita 20 s old;
    create and close mean 153 ms, max 183 ms; opens 155–175 ms; a native capture 36 ms.
  - The raw preset digest changed a fourth time; the canonical one held.
  - `transfer/` and `harness/` empty after every run; `plugin.log` without warning or error.
  - A bridge start at 18:13 with no `stopped` before it: Krita had ended without its quit signal;
    the next start took over the stale `bridge.json` as designed.
  - The server instructions: 2,773 of 4,096 characters.
- **Checked by hand:** the owner saved their documents, quit Krita and started it again with
  none open, so the full probe could run; the session restarted nothing itself.
- **Falsified:** nothing; the review adds no check.
- **Numbers** (unchanged, as found):
  - `verify`: 6 stages, all PASS;
  - 334 server tests passed, 0 skipped;
  - 249 plugin-core tests passed, 0 skipped;
  - `probe`: 55 PASS, 0 FAIL, 15 MEASURED;
  - 11 registered tools; 19 schema files.
- **Review (`/code-review high`), 10 findings, all fixed at the owner's request.** All in the
  documents this session wrote.
  - **Block 6a's F24 remedy would have broken the late-registration case:** a strict
    `operation()` on an id never seen registered is the state a POST stuck behind a long save
    leaves. The remedy now bounds the 404 window after the bridge's first answer and keeps waiting
    while it answers nothing.
  - **The F13 leftover check runs before the final sweeps,** so a leak the sweep would hide is a
    FAIL.
  - **The F2 amendment names its mechanism:** an additive protocol field the server sets on reads,
    never the id's shape, since an agent may send any non-empty string.
  - **F15's refusal covers the data directory itself and folders inside it,** not only its
    parents.
  - **The REVIEW's counts:** the server is 19 modules, not 25; the earlier doctor reading was six
    minutes before the full run, not an hour.
  - **6a's read order and the handoff name invariant 3,** since 6a changes `roots add`.
  - **The done-note no longer credits findings to an agent;** it says what the REVIEW's method
    says, a second independent cold read.
  - **The handoff reports what exists:** this session's two commits, once the review commit is
    made; and it points at block 6a as the one home of its items instead of restating them.
  - **README's version line** joins 6a's Docs.
  - **Falsified:** nothing; no check was added.
  - **Numbers after the review:** unchanged.

---

## 6a: Review fixes — observe

Inserted by review 6 on 2026-10-24. The owner chose one fix session for the review's mechanical
findings, so that session 7, the round's largest block, starts clean. Each item names its
finding in `REVIEW-2026-10-24.md`; the pointers are to the code as the review saw it (`d5af786`).

**Read:** `SPEC.md` §5 (invariants 3, 6, 9, 12, 13); `REVIEW-2026-10-24.md` §3 and §5; `PDD.md`
Part 8 (*Bridge protocol*, K41, K48).

- **The bridge client** (F24, invariant 9). A POST the bridge never registered is reported
  `running` for ever (`src/krita_art_mcp/bridge_client.py:200-230`, `:142-145`). Bound the 404
  grace: once the bridge has answered anything in a follow, a 404 that persists past a short
  window (seconds, not the budget) is "unknown operation", in `call()` and `operation()` alike.
  A POST stuck behind a long Krita call must still be found: while the bridge answers nothing
  (timeouts), the follow keeps waiting, and the first 404s after it answers get the window,
  because the backlogged POST may register a moment after the GET. A retry of the tool call
  still runs, since the bridge never saw its request id.
- **Jobs** (F7, F11, F27).
  - `cancel` routes through `_finish_failed` and `CANCELLED` is retryable on both sides
    (`bridge_core/jobs.py:223-227`, `src/krita_art_mcp/errors.py:19`): a cancelled queued job
    never ran, like one failed at stop.
  - `Jobs._run` serialises the handler's result once (`json.dumps`) and fails the operation with
    `INTERNAL_ERROR` when it cannot, so a non-JSON result can never loop the client
    (`bridge_core/server.py:94`, `bridge_client.py:204-205`).
  - `Waker._run` catches `BaseException`, logs it and swallows it, re-raising `SystemExit` only
    (`krita_adapter/main_thread.py:19-25`).
- **The adapter** (F6, F9).
  - `KritaDocuments.selection()` waits for Krita before reading (`krita_adapter/documents.py:127-140`).
  - `probe.undo_action` switches views as the adapter does (`windows()[0]`, `View.setVisible`
    through `bring_forward`/`restore_view`) or is retired, the owner's choice at the start
    (`krita_adapter/ops.py:29, 46`). Its measurement is kept in session 2's done-note.
- **Transfer** (F12). Masks expire too: `_expire` covers `mask-*.a8` after a longer window, or the
  server discards its mask when the call is not sent (`bridge_core/transfer.py:57-66`,
  `src/krita_art_mcp/transfer.py:49-68`).
- **Receipts** (F8). One table per tool, `(tool, op, receipt, resolve)`, from which the send and
  `RECEIPTS` both derive, or a test that every `call("…")` literal in the tool modules has its
  entry (`src/krita_art_mcp/tools/operations.py:27-41`).
- **Constants** (F19, F26). A server-side blend-mode whitelist held equal to the plugin's
  (`bridge_core/resources.py:16-27`; the probe's copy at `probe/pixels.py:23-34` reads it);
  `MAX_POINTS`, `MAX_RADIUS` and `MAX_LIMIT` pinned to the schema limits in the constants test
  (`tests/test_envelope.py:45-52`).
- **Roots** (F15). `roots add` refuses `/`, the home folder, and any folder equal to, containing
  or inside the data directory, with a message (`src/krita_art_mcp/roots.py:86-96`); invariant 3's
  realpath rule applies to the refusal too.
- **The server** (F16, F17). The baseline sweep runs under `_CALLS` (`src/krita_art_mcp/server.py:31-34`);
  `tests/test_tools.py:41` points its client at `tmp_path`.
- **The data directory** (F14). The harness folder is made private (`probe/__init__.py:51`) and
  `plugin.log` is 0600 (`bridge_core/log.py:30`).
- **The probe** (F13). The summary prints the run's wall time; a last check, run before the
  final sweeps, lists `transfer/` (empty) and the probe's own documents (none open), so a leak the
  sweep would hide is a FAIL.
- **Schemas** (F18). The amendment tooling is committed under `scripts/` (or the shared shapes
  are generated into the 19 files from one source and the result tested), so sessions 7–12 amend
  with it instead of one-off scripts.
- **Docs.**
  - `CHANGELOG.md`: 0.6.0, and the missing `[0.5.0]` link reference
    (`5ead34bc4e5624e92165b211d1daa2f66ed95fb1`) (F20).
  - README (the version in *Status*) and `CLAUDE.md`: the probe's run-time line and
    `roots add`'s refusals, where they state the behaviour.
- **Ask at the start of 6a:** retire `probe.undo_action`, or make it switch views as the adapter
  does. Proposed by review 6, not yet confirmed.

**Gates:**
- `uv run scripts/verify.py`, with these tests: the bounded 404 grace and the strict answer
  afterwards; cancel releasing its request id; a non-JSON result failing typed; the swallowed
  `BaseException`; the mask expiry; every tool op in `RECEIPTS`; the three bounds and the
  whitelist held equal; the refused roots; the private harness folder and log.
- `probe` green, printing its wall time, and its leftover check PASS.
- Each new check falsified once.

**Watch for:**
- **The 404 grace has a real case.** A POST stuck behind a long Krita call registers only when
  the GIL is released; `test_a_poll_waits_for_a_call_the_bridge_has_not_registered_yet` must
  keep passing with the bound.
- **`probe.undo_action` touches the owner's view.** Whatever is chosen, run it only with the
  owner's documents saved, as now.
- **A changed plugin loads only after a Krita restart;** decision 21 applies.

**Done (2026-10-24, 0.6.0).**
- **Decided with the owner at the start:**
  - **F6 (the block's Ask): `probe.undo_action` is retired.** Its measurement (the label reads
    `'Undo '` straight after a change) stays in session 2's done-note; sessions 7 and 9 build their
    label checks on the agent's own document.
  - **F7 changes the journal:** a no-effect outcome settles only the attempt it names; a receipt
    still settles every attempt it deduplicated. Otherwise a late `krita_operation_get` on a
    cancelled op marks a running retry settled, and a Krita restart could run it twice. It reverses
    session 3's rule and test that a no-effect outcome settles them all.
  - **F27 swallows `SystemExit` too:** in a PyQt5 slot it ends Krita, the loss F27 guards against.
  - **F12: masks expire after the same hour as raw files,** since the server refreshes a mask it
    sends again and a missing mask is retryable.
  - **The owner restarted Krita** to load the plugin (3 documents open, 0 unsaved).
- **A design check in plan mode** (one independent read of the code paths) found the F7 gap; the
  404 window filling with time in which Krita held the GIL; a message promising more than the
  client knows; error bodies the reply could not carry; a queue stalled and a job stranded
  `running` after an interrupt; and a mask taken by one call while another refreshed it. The plan
  folded in a fix for each.
- **The server.**
  - **`bridge_client`:** a 404 answered promptly for `REGISTER_GRACE_S` (2 s) before the bridge
    has said `running` ends the follow with `_unregistered`: retryable `INTERNAL_ERROR`, `outcome:
    "unregistered"`, in `call()` and `operation()` alike. A timeout, a reset or a reply slower than
    0.5 s restarts the window. `outcome_of` keeps such an attempt unsettled.
  - **`journal`:** `NO_EFFECT` settles by operation id, like `CONFLICT` and `NOT_SENT`.
  - **`errors`:** `CANCELLED` is retryable.
  - **`roots.refusal`:** `roots add` refuses `/`, the home folder, and any folder equal to,
    holding or inside a data folder (the one holding `config.json`, and the server's), by realpath.
  - **`tools.CALLS`** (was `_CALLS`) also serialises the baseline sweep at server start.
  - **`tools/observe.BLEND_MODES`**, held equal to the plugin's; the probe reads it.
  - **`paths.private_dir`**, used for the harness folder; **`transfer.put_mask`** refreshes a mask
    it finds and writes one that is missing.
- **The plugin.**
  - **`jobs`:** `cancel` fails through `_finish_failed` (retryable, request id released); a result
    must be a dict that survives `json.dumps(allow_nan=False)`, and is stored as that snapshot; an
    error body that cannot be sent becomes a plain `INTERNAL_ERROR`; `_run` fails its op on any
    `BaseException`; `drain` fails an op it popped but never finished; `drain_in_slot` swallows and
    logs anything still escaping, and `Waker._run` calls it.
  - **`transfer`:** `_expire` takes masks too, and also runs after a mask is taken; a mask that is
    gone is a retryable `IO_ERROR`.
  - **`log`:** `plugin.log` is made 0600, an older one narrowed, and a rotated one 0600.
  - **The adapter:** `selection()` and `layers()` call `waitForDone()` first; `ops.py` loses the
    undo probe.
- **The probe:** the summary reads `probe: N PASS, M FAIL, K MEASURED in S s`; a last check
  (`_no_leftovers`, before the final sweeps) finds open probe documents and transfer files; the
  harness folder is 0700.
- **Tooling:** `scripts/amend_schemas.py` holds the envelope, `guard` and `source`, copies each
  `data` into the completed rule and open's `layers` into inspect's, and formats the 19 files;
  `--check` changes nothing. It was a no-op on the files as they stood; a test holds them to it.
- **Amendments:**
  - **The three decisions above** (F7's journal rule, F27's `SystemExit`, F12's hour), the owner's,
    in plan mode.
  - **F24: one answer for `call()` and `operation()`,** retryable `outcome: "unregistered"`, not
    `INVALID_ARGUMENT` "unknown operation", whose wording reads as the agent's mistake; and a slow
    reply restarts the window. Settled in the plan (design check).
  - **F9: `layers()` waits too.** The scan that holds F9 found it. Settled in the plan.
  - **F11 checks error bodies as well as results,** and keeps the result as a snapshot. Settled in
    the plan (design check).
  - **F27 catches per job, and no op is stranded,** beside the slot's guard, so a swallowed
    interrupt never stalls the queue. Settled in the plan (design check).
  - **F12: a missing mask is retryable, and taking a mask expires the rest.** Settled in the plan
    (design check).
  - **F15 also refuses the server's data folder** (`KRITA_ART_MCP_DATA_DIR`, which holds the
    journal). Settled in the plan.
  - **F13's summary counts MEASURED too,** so no session counts them by hand. Settled in the plan.
  - **F8 took the block's test branch, F18 its generator branch.** Settled in the plan.
- **Measured** (Krita 5.3.4.1 on macOS, Apple Silicon, on a Krita the owner had just restarted with
  nothing open):
  - **`probe`:** 55 PASS, 0 FAIL, 14 MEASURED in 12.3 s; the leftover check PASS; H4 p50 5.5 ms,
    p95 8.8 ms, max 19.4 ms; create and close mean 144 ms, max 156 ms; opens 132–151 ms; a native
    capture 29 ms; the one expected "baseline … was not kept" line.
  - **The raw preset digest changed a fifth time** (`234ce3da55e8e01c`); the canonical one held
    (`d31399fb15465c79`).
  - **Modes:** `plugin.log` went from 0644 to 0600 at the new plugin's first start, and `harness/`
    from 0755 to 0700 at the probe's; everything in the data folder is now 0700 or 0600.
  - **Leftovers:** `transfer/` and `harness/` empty after both runs; `plugin.log` with no warning or
    error, and a `stopped` line for the Krita the owner quit.
- **Checked by hand:** `doctor` after the owner's restart: steps 1–5 PASS, step 6 FAIL "no roots";
  0 open documents.
- **Falsified:**
  - **The method.** A scratchpad driver broke one product line at a time (the scan itself, for the
    scan's own test), ran only the guarding test, copied the file back and compared it byte for
    byte; `git status` matched before and after.
  - **47 breaks, each failing at its own test:** the window ending a lost POST and a call left
    running, the id leaving `_sent`, the silence, slow-reply and reset restarts; `unregistered`
    unsettled and mapped to UNKNOWN; the no-effect rule; `CANCELLED` retryable on the server, in
    the bridge's cancel and in its release; a non-JSON result end to end and in the core; an error
    body; the snapshot; an interrupt in a handler, before a job runs, and in the slot; the log
    narrowed and rotated; masks expiring, on a take too, and a gone mask retryable; the refreshed
    mask; the two adapter waits and the scan's own rule; every op in `RECEIPTS`; the blend modes and
    the three bounds; the five roots refusals; the sweep under `CALLS`; the summary line and the
    private harness folder; the leftover check's documents and files; a stale schema file, and the
    script's `guard` and `data` copies.
  - **Live:** the leftover check FAILed ("1 document(s) open") with the pixel checks' first close
    skipped, and the final sweep closed that document.
- **Known debt:** an interrupt landing between taking a job and running it fails that job, but the
  jobs queued behind it wait for the next call to wake the queue. A server killed mid-write leaves a
  `.mask-*.tmp`, which only the bridge's start sweeps.
- **Numbers:**
  - `verify`: 6 stages, all PASS;
  - 360 server tests passed, 0 skipped (+26);
  - 270 plugin-core tests passed, 0 skipped (+21);
  - `probe`: 55 PASS, 0 FAIL, 14 MEASURED (−1 and +1 PASS, −1 MEASURED), 12.3 s;
  - 11 registered tools; 19 schema files; instructions 2,773 characters.
- **Review (`/code-review high`), 10 findings, all fixed at the owner's request.**
  - **A deduplicated attempt stayed unsettled after a refusal it shared,** so later retries
    skipped the roots precheck and a retry after a restart was refused. A finished line now
    carries `bridge_operation_id`, the operation the bridge answered with, and a no-effect outcome
    settles that attempt and its own.
  - **A too-wide root already in `config.json` took effect.** Both sides' `allowed()` now refuse
    every path while one is listed (the plugin's `reaches_too_far` holds the server's rule), and
    `doctor` step 6 counts them. The server's `World` keeps its data folder apart from the art
    root, as on the owner's Mac.
  - **The leftover check counted another client's transfer files.** It counts only files that
    appeared during the document checks and still exist after a one-second pause.
  - **A deleted `plugin.log` broke rotation;** `_rotate` renames only a file that exists.
  - **`amend_schemas.py` used the locale's encoding;** it reads and writes UTF-8, and renders
    once.
  - **The start-up sweep held the call lock for up to 5 s;** its budget is 2 s.
  - **The window tests' margins** are 0.2 s or more, with a 1.2 s grace.
  - **A dead `CANCELLED` case** left the outcome test.
  - **The server's data-folder `mkdir`s** (journal, transfer, roots, baselines, captures) use
    `paths.private_dir`.
  - **Falsified:** 13 breaks, each failing at its own test: the deleted-log rotation; files from
    before the run and another client's file; the no-effect rule and the server recording the
    bridge's operation; the load-time refusal on each side, the plugin rule's home and above
    cases, and doctor's count; the three widened window cases. The home case first passed with
    its rule broken, because the data folder lay inside home and the holding rule caught it; the
    test now keeps the data folder outside home, and it fails. The encoding fix has no check that
    can fail under this machine's UTF-8 locale.
  - **Measured** on the reinstalled plugin (the session quit Krita with 0 documents open and
    started it again, at the owner's word): `probe` 55 PASS, 0 FAIL, 14 MEASURED in 12.5 s; H4 p95
    9.1 ms; the raw preset digest changed a sixth time (`eb2cc2667d8c69a9`), the canonical one held;
    `transfer/` and `harness/` empty, `harness/` 0700, `plugin.log` 0600 with no warning or error.
  - **Numbers after the review:**
    - `verify`: 6 stages, all PASS;
    - 370 server tests passed, 0 skipped (+10);
    - 271 plugin-core tests passed, 0 skipped (+1);
    - `probe`: 55 PASS, 0 FAIL, 14 MEASURED.

---

## 7: Preparing a change

**Read:** `SPEC.md` §1 (decisions 5, 26, 27), §5 (invariants 1, 4, 5); `PDD.md` Part 4
(`krita_layer_create`, `krita_selection_set`, `krita_protection_set`, `krita_history_step`), Part
8 (K7, K8, K10, K11, K22, K23, K43, K46); `REVIEW-2026-10-24.md` F1, F2, F4, F5, F23, F25.

- **Amended by review 6 (2026-10-24):**
  - **F1: raster selections load through `Selection.setPixelData`, the scan's one exception.**
    One adapter function may call `setPixelData`, on a receiver the same function built with
    `Selection()`; an AST test holds both rules (the receiver's origin, and no other call site),
    and the scan stays as it is everywhere else. SPEC §5 invariant 1 carries the owner's note;
    `CLAUDE.md`'s invariant line is updated here.
  - **F2: bounded retention in the bridge.** Operations whose `request_id` the server minted
    (reads) are kept only until first delivery plus a window; operations with an agent's
    `request_id` stay for the session, as invariant 9 wants (`bridge_core/jobs.py:92-96`). The
    bridge tells them apart by an additive protocol field the server sets on reads, never by the
    id's shape: an agent may send any non-empty string.
  - **F4: the K46 node choice lives in the core.** `_unmasked`'s logic
    (`krita_adapter/documents.py:284-293`) becomes a pure function over `tree()`'s dict in
    `bridge_core`, tested with a global and a local mask; the adapter activates the chosen id.
  - **F5: the instructions' budget.** This session adds at most 300 characters net and trims the
    present text first; 2,773 of 4,096 are used.
  - **F25: dirty before the first mutation.** Every mutating handler marks its handle dirty (or
    unsafe) before its first libkis mutation, so an exception afterwards leaves it dirty; the
    "dirty on success only" test (`tests/plugin/test_documents.py:192-199`) is reshaped to say
    "clean after a refusal before the mutation".
- **Ask at the start of 7** (F23): where the allowed mask's bytes live — in memory on the handle
  (64 MB for an 8k canvas, per document) or in a file under the data directory read per stroke.
  Proposed by review 6, not yet confirmed.
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
  - `CHANGELOG.md`: 0.7.0 (0.6.0 before review 6 inserted 6a).
  - README: the tool list.
  - `CLAUDE.md`: invariant 1's enforcement line (F1).
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

**Done (2026-10-24, 0.7.0).**
- **Decided with the owner at the start:**
  - **F23 (the block's Ask): the allowed mask lives in memory** on the plugin's handle, one byte
    per canvas pixel (0 or 255), with its summary; PDD Part 6's "mask path and hash" is "mask bytes
    and hash".
  - **Mask transfer files are one per request:** `mask-<16 hex of SHA-256(request_id)>-<sha256>.a8`.
    The plugin takes a mask straight after its argument checks, before any other refusal; the
    server removes the request's masks after any final outcome (in the call, in
    `krita_operation_get` and in `krita_operation_cancel`), never while it is pending.
  - **`protected_layer_ids` is the whole set:** it must keep every protected layer that still
    exists (`INVALID_ARGUMENT` naming those it would unprotect); unknown ids are
    `LAYER_NOT_FOUND`.
  - **Shapes off the canvas are refused, never clipped,** with `canvas_px`; the server refuses a
    box over `capture_source_pixels` before it rasterises.
  - **The owner let the session restart Krita** while it had no documents open, and, after the
    crash below, chose to reproduce and fix it.
- **A design check in plan mode** (one independent read of the code paths) found: a rollback that
  could undo the owner's document (K7); undo labels read before Krita updated them; labels that do
  not identify a step ("Add Layer" for every node added); the ledger missing a rollback's K43
  rule; F2 marking a reply delivered before it was written; the plugin not checking a PNG's path;
  rasterising unbounded before the plugin could refuse; masks left behind on Pending paths;
  nullable fields the schemas lacked; the F1 rule's binding gaps; a fake that kept the active mask
  outside the tree; and Krita's undo limit. The plan folded in a fix for each.
- **The plugin core.**
  - **`ledger`:** `Step{op, operation_id, label, before, after, region}` and `Ledger{steps,
    applied, floor, redo, bottom}`; `push` truncates the redo tail (K43), `rolled_back` pops a
    rollback's step and offers no redo, `seal` stops history below a step the bridge cannot name
    (protection changes, harness ops that push, a mutation that raised), and `bottom` follows
    Krita's `undoStackLimit`. A step's fingerprint is the sorted node ids without the root's
    selection masks, and the SHA-256 of the selection's canvas-clipped bounds and bytes.
  - **`history`:** `move` undoes or redoes one step with the document's view in front (K7):
    posted events flushed, the top label naming the step and the fingerprint matching, then the
    opposite label and fingerprint after; an unconfirmed move is reversed once, otherwise the
    document is unsafe. `history.step` refuses more than `undo_available`/`redo_available`; a step
    the bridge did not make refuses before any change and seals; one after k steps stops with
    `verified: false`; an undo Krita did not take is put back and retryable. `LABELS`:
    `layer.create` "Add Layer", `selection.set` and `selection.clear` "" (measured).
  - **`layers`:** `layer.create` under the root or a group (a protected group too), directly above
    a sibling or on top when `above_id` is null, as `addChildNode` places it; verified by diffing
    `tree()` (one new id, where asked; the parent and every protected node unchanged but for
    order), and rolled back through `move` on a violation (`LOCKED_TARGET`, `INTERNAL_ERROR`, or
    `ROLLBACK_FAILED` and unsafe).
  - **`selections`:** `selection.set`; a pure `recipe()` fixes the order: shape, grow, shrink,
    feather, invert, combine, commit. `subtract`/`intersect` with no selection are refused; `none`
    with no selection pushes nothing but dirties (decision 27). The receipt's `selection_id`
    (`sel-` + the fingerprint's hash) and `selected_pixels` come from the plugin.
  - **`protection`:** `protection.set` places the mask in a canvas-sized buffer, checks it binary,
    tightens only by `int.from_bytes` (`new & ~cur`), keeps flags on, requires a PNG mask to be the
    canvas's size, seals the ledger, and reports the summary (sha256, bounds, allowed pixels).
  - **`masks`:** the mask argument shared by both ops: its check, take, plugin-side roots check of
    a PNG's realpath (invariant 3), box, canvas bounds and placement.
  - **`nodes` (F4):** `unmasked(tree)` picks the node for K46; `unmasked_view` brings the
    document forward, activates it, confirms and restores; open, capture/sample and the harness
    export use it.
  - **`registry` (F25):** `Handle.before_change()` dirties the handle (and stamps `changed_at`)
    before a handler's first libkis mutation; `guarded` lost `dirties`.
  - **`jobs`/`server` (F2):** a call may carry `ephemeral`; the server marks a read delivered once
    its final reply is written; a prune at most once a minute drops ephemeral ops 10 minutes after
    delivery, or 1 hour after finishing undelivered, with every alias, request and binding.
    `bridge.json` says `ephemeral_reads: true`, and a server sends the field only to such a bridge.
  - **`documents`:** a close waits out `SETTLE_S` (0.5 s) since the document last changed, letting
    Krita's own timers run with user input held back (see Measured).
  - **`harness`:** `harness.activate`, `harness.undo_labels` (with the raw action texts) and
    `harness.label_timing`; `harness.select_mask` seals the ledger.
  - **Inspect** reports the allowed mask's summary and `history {undo_available, redo_available}`;
    `selection.enforced`'s note names `krita_selection_set`.
- **The adapter:** `create_layer`, `activate`, `undo`/`redo` (the actions, then wait and flush),
  `undo_labels` (flush, then the action texts; a disabled action is None, an unnamed step ""),
  `undo_actions`, `undo_limit` (`Krita.readSetting("", "undoStackLimit", "30")`, 0 unlimited),
  `label_timing`, `selection_bounds`, and `close(document, settle_s)`. `selections.commit` runs the
  recipe; `_from_mask` is the plugin's one `setPixelData` site, on a `Selection()` it builds (F1).
  The shim gains `QCoreApplication`, `QEventLoop` and `EXCLUDE_USER_INPUT`, the one enum, resolved
  per PyQt version there.
- **The server.**
  - **`masks`:** NumPy sampling at 4 × 4 sub-pixel centres in bands of 64 rows; antialiased values
    `(k·255 + 8) // 16`; binary allowed masks at k ≥ 8; polygons even-odd with edges half-open in
    y; PNGs inside a root, by SHA-256, mode L only (0/255 for allowed masks).
  - **`tools/changes`:** the four tools, journaled on `guard.request_id`, with mask preparation
    inside `send`; `transparency_mask` is `UNSUPPORTED_CAPABILITY` before Krita; the selection's
    mask PNG is found before it is made, and is null when another server took the pixels first (a
    retry it shared), as the open's baseline already is.
  - **`transfer`:** `request_key`, `put_mask(directory, mask, request_id)`, `discard_masks`.
  - **Schemas** (then `amend_schemas.py`): as the plan, with `coverage_px` left to inspect; the
    input `allOf` of `history_step` removed by hand.
  - **Instructions (F5):** 2,620 characters (−153), with this session's rules added.
- **The probe (`probe/changes.py`):** read-only refusals; layer_create placement, the protected
  group, the composite and dirty; selection shapes, combines and the invert, exact; the ledger's
  counts over layers and selections; the retried selection_set; K46 with a selection mask active;
  protection's floor and tighten-only refusals; the label timing; five closes straight after a
  selection change.
- **Amendments:**
  - **The four decisions above** are the owner's, at plan time.
  - **The probe's "protected-group refusal" checks the allowance:** Phase 1's layer_create adds an
    empty, normal layer and cannot change a group's appearance; unit tests hold the
    `LOCKED_TARGET` path. Amended at plan time, with the owner.
  - **NumPy sampling replaces Pillow drawing at 4×:** the same supersampling, with a fill rule that
    is defined and testable. Amended at plan time, with the owner.
  - **Steps are confirmed by fingerprint as well as label, and labels are read after a flush with
    the view in front,** because labels do not identify a step and session 2 found them stale.
    Design check, amended at plan time, with the owner.
  - **`feather_px` is an integer (Krita's `feather` takes an int); `grow_px`/`shrink_px` added;
    `subtract`/`intersect` with no selection refused; receipts carry `undo_steps`; Phase 3 fields
    removed; inspect gains the mask summary and `history`.** Amended at plan time, with the owner.
  - **`above_id: null` means on top, not at the bottom:** the first live run showed
    `addChildNode(node, None)` puts the node on top, and the verification rolled the plan's
    "bottom" back as misplaced. The session's own finding.
  - **`coverage_px` left the selection receipt; `selection_id` and `selected_pixels` come from the
    plugin,** so a second server that shares a retry gets the receipt without the pixels the first
    server took. The session's own finding.
  - **`ephemeral` is advertised in `bridge.json`:** the new server could not count Krita's
    documents through the old plugin, which refused the field, so `doctor`'s restart gate failed.
    The session's own finding.
  - **A close settles for 0.5 s after a change** (below). The owner chose to reproduce and fix it.
- **Measured** (Krita 5.3.4.1 on macOS, Apple Silicon):
  - **A crash, reproduced and fixed.** Krita crashed in `KisNodeModel::processUpdateQueue` (a null
    pointer, from a `KisSignalCompressor` timer) when a document closed straight after a selection
    change: first after a debug script, then at the first iteration of a loop of open, select,
    close (and of select alone); layer creation alone survived 10 loops, and a 0.5 s pause before
    the close, or clearing the selection first, survived. With the settle, 20 select-then-close and
    10 layer-select-undo-close loops survived.
  - **Undo labels:** "Add Layer" after `addChildNode`; `setSelection` pushes an unnamed step
    ("Undo ", enabled), for a selection and for None alike; Krita keeps Redo enabled as "Redo "
    with nothing to redo.
  - **Label timing:** straight after a push in the same job the label was stale in 1 of 7 reads in
    the first run and 0 of 7 in each later one; after the flush, current in 7 of 7 every time.
  - **`setActiveNode` on the global selection's own mask** leaves the previous layer active, so the
    global branch of K46 cannot be made from a script; Krita lists that mask as a root child named
    "Selection Mask".
  - **`addChildNode` makes the new layer active.**
  - **Grow, shrink and feather by 3 of a 20 × 16 rect:** {17, 11, 26, 22} 568 px; {23, 17, 14, 10}
    140 px; {17, 11, 26, 22} 572 px.
  - **An export answered `BUSY` once:** Krita's autosave held the harness document during
    `harness.export_kra`, which the bridge reports as retryable and the probe, which never retries,
    as a FAIL; the next run passed. It had not been seen before.
  - **`probe` on the 0.7.0 build:** 66 PASS, 0 FAIL, 21 MEASURED in 18.4 s; H4 p50 5.5 ms, p95
    6.6 ms, max 38.0 ms; create and close mean 149 ms, max 158 ms; opens 153–159 ms; a native
    capture 51 ms; the raw preset digest changes from run to run (`016cfd6fd3f93c11` here), the
    canonical one held (`d31399fb15465c79`); `transfer/` and `harness/` empty after every run,
    `plugin.log` with no warning or error.
- **Checked by hand:** `doctor` before and after each of the session's Krita restarts: 0
  documents open, 0 unsaved, steps 1–5 PASS on the new plugin, step 6 FAIL "no roots".
- **Falsified:**
  - **The method.** A scratchpad driver broke one product line at a time (the scan itself, for the
    scan's own tests), ran only the guarding test (on 3.10 for the plugin core), counted only a
    pytest exit of 1 as a failure, copied the file back and compared it byte for byte; the tree's
    diff hash matched before and after.
  - **110 breaks, each failing at its own test:**
    - the ledger's truncation, rollback, floor, limit, undo arithmetic and fingerprint filter;
    - F4's three branches and its error, the open's and the export's unmasking;
    - layer_create's parent and sibling rules, placement, protected properties, dirty restore,
      rollback pop, unsafe mark and seal;
    - the read-only refusal and masks taken before it;
    - the recipe's order, the readback, combine without a selection, the canvas bound, another
      request's mask, the plugin's roots check, `none`, its modifiers, layer_alpha and the
      modifier bound;
    - `loosened`, the summary, the seal, each tighten-only rule, unknown ids, the binary check, the
      PNG's size and inspect's history;
    - history's limits, label and state checks, the stop part-way, the retryable reversal, the
      view in front, the step bound and the region's union and hash;
    - the harness ops' front rule and seals, F25, the settle and its use;
    - F2's keep, unsent expiry, unfinished reads, aliases, bindings, the once-a-minute prune, the
      written-reply mark, the final-reply gate, the field's type, its advertisement and the
      client's gate;
    - F1's rule, binding, module and import checks, and the product's site renamed or rebound;
    - the request-keyed names and discard;
    - the rasteriser's sample offset, parity, bands, ellipse, limits, binary rule and rounding, and
      every PNG refusal;
    - the four tools' receipts, refusals, mask settling, pending rule, origins and step names;
    - the three new bounds against the schemas.
  - **Seven breaks first passed,** each showing a weak test or a redundant line:
    - `rolled_back`'s `redo = 0` and the scan's "exactly one call" gate could never matter (a push
      leaves no redo; only one call is ever exempt), so both lines went;
    - the read-only test used only an owner's document, the summary test no row with two allowed
      pixels, the step-bound test refusals the availability check also made, and the delivery test
      no read marked before it finished; each test was strengthened;
    - the HTTP test could not see the server's final-reply gate behind the jobs' own; it now
      watches the calls the server makes.
    All seven then failed.
  - **Live.**
    - **Four server breaks failed one check each:** `above_id` dropped (layer_create), the
      raster's origin (selection shapes), subtract sent as intersect (combines) and a step's tool
      name (the ledger's counts).
    - **Six plugin breaks failed their checks:** layer_create allowed on a read_only document, the
      K46 unmasking skipped, a dropped protected id accepted, the bridge's dedup off (the retried
      selection_set, beside the older retry checks), and the close's settle off, which crashed
      Krita at the close-at-once check, as found.
    - **The seal's break first passed,** because the K46 check's harness op had sealed history
      already and no redo was on offer; protection now runs before K46 with an undo first, and the
      break then failed the protection check alone.
    - **A first server round misfired:** dropping the selection's `request_id` broke every mask's
      key, so the retry check was falsified on the plugin side instead.
  - **Not falsified:** the label-timing check. Without the flush, stale reads were 1 and 0 of 7,
    so its break would rarely fail.
- **Known debt:**
  - **Selection steps are confirmed by state alone:** their Undo label is empty, and Krita keeps
    Redo enabled as "Redo " with nothing to redo. A named step on top (the owner's stroke) still
    stops history.
  - **Labels are English** (in `docs/BACKLOG.md`).
  - **The global-mask branch of K46 is held by unit tests only** (in `docs/BACKLOG.md`).
  - **The close's settle** delays a close by up to 0.5 s after the document last changed; Krita's
    crash itself is upstream's (in `docs/BACKLOG.md`).
  - **History's region, capture and hash** are unit-tested only until strokes record regions
    (session 9).
  - **A server that shares a retry with another gets the selection's receipt without its mask
    PNG,** as the open's baseline already is.
- **Numbers:**
  - `verify`: 6 stages, all PASS;
  - 409 server tests passed, 0 skipped (+39);
  - 356 plugin-core tests passed, 0 skipped (+85);
  - `probe`: 66 PASS, 0 FAIL, 21 MEASURED (+11 PASS, +7 MEASURED), 18.4 s;
  - 15 registered tools (+4); 19 schema files; instructions 2,620 characters (−153).
- **Review (`/code-review high`), 8 findings, all fixed at the owner's request.**
  - **Harness ops changed nodes without counting as changes,** so a close soon after them got no
    settle. `Handle.touched()` stamps `changed_at`; `before_change()`, `harness.select_mask`,
    `harness.label_timing` and `harness.activate` call it.
  - **The settle depended on bridge changes alone.** Krita's layer docker shows the document in
    front whoever changed it, so a close of that document always waits `SETTLE_S`, one behind
    only within it of a change, and a discard after a failed create or open waits too. The rule
    lives in `bridge_core/closing.py`.
  - **A history capture whose pixels another server took failed retryably for ever;** it is now
    left out (`capture` and `content_sha256` null), as the selection's mask is. One helper,
    `_kept_png`, writes both PNGs (the capture's own writer keeps its previews and greyscale).
  - **Reads failed at once (a conflicting retry, an unknown op) were never forgotten:** they
    now finish through `_finish_failed`, which stamps `finished_at`.
  - **An undo Krita did not take left the document dirty** although refused as unchanged; `move`
    restores `dirty` when it puts the step back.
  - **History read and hashed the selection twice per step,** and layer creation twice per call:
    a multi-step undo now reuses the state the previous step confirmed (N + 1 reads for N
    steps), and a layer creation reuses the selection hash it read before (one read).
  - **A probe comment told the crash's history;** it now states what the close does.
  - **Falsified:** 13 breaks, each failing at its own test: the in-front settle and its use in
    the close, the three harness stamps, both discards' settle, both immediate failures'
    finish, the reversal's dirty restore, the reused state in history and in layer creation, and
    the left-out capture.
  - **Measured** on the reinstalled plugin (the session restarted Krita with 0 documents open):
    `probe` 66 PASS, 0 FAIL, 21 MEASURED in 38.1 s, up from 18.4 s, because a close of the
    document in front now waits 0.5 s: create and close mean 720 ms (149 ms before), H4 p95
    6.2 ms; `transfer/` and `harness/` empty, `plugin.log` with no warning or error.
  - **Numbers after the review:**
    - `verify`: 6 stages, all PASS;
    - 410 server tests passed, 0 skipped (+1);
    - 364 plugin-core tests passed, 0 skipped (+8);
    - `probe`: 66 PASS, 0 FAIL, 21 MEASURED, 38.1 s.

---

## 7a: Hygiene and the workflow kit

Inserted at the owner's request on 2026-10-24: "bring this repository's hygiene and workflow up
to the updated workflow kit, and walk the owner through what belongs on the private-term list".
It takes no version: nothing a user of the server sees changes, so later versions do not shift.

**Read:** `SPEC.md` §1 (decisions 13, 14, 16), §5 (invariant 14); `scripts/hygiene.py`,
`scripts/verify.py` and `tests/test_hygiene.py`; the workflow kit's `DEVELOPMENT-WORKFLOW.md`
(*Nothing private in the repository*) and `KICKOFF.md` (*The hygiene stage's design*).

- **The hygiene stage, moved to the kit's design:**
  - the terms come from `~/.config/hygiene/terms.txt`, outside the repository, one word per
    line; a missing file fails the stage and an empty one passes; tests point the stage at
    fictional terms and never read the owner's file; `scripts/hygiene_terms.txt` is deleted,
    because a hash of a short word is reversed by hashing a dictionary of names;
  - tokens are runs of letters and digits in any script, plus the camel-case words and digit
    groups inside them; terms and tokens are normalised to NFC and lowercased;
  - the attribution patterns name the AI tools, so a codegen script's note passes; co-author
    trailers and AI session links still fail;
  - a hit names the file and line, or the commit and message line, never the term;
  - one run, the last act before each commit, message included: `verify.py --message <file>`.
- **The workflow.** The kit's `DEVELOPMENT-WORKFLOW.md` is copied into `docs/`, keeping this
  repository's *In this repository* paragraph. The done-note lists what changes for sessions
  8–15.
- **The docs.** `CLAUDE.md` (the public section, gaining "Unsure whether something is public?
  Ask the owner before writing it; a word they call private goes on the term list", the
  Commands table and the Git notes), README's hygiene line, and the handoff's standing trap.
  Decision 14 and invariant 14 change only by the owner's dated amendment.
- **The term list,** walked through with the owner in small batches, each question with a
  recommended answer. A word is added only with the owner's yes, after a check against the tree
  and history; no done-note, handoff or commit message names a term, only counts.
- **History.** The hashes stay in history after the file is deleted. Rewriting it needs a force
  push and is the owner's decision; if deferred, it goes to `docs/BACKLOG.md` as a step before
  the repository is made public.
- **Ask at the start of 7a:** its version (proposed: none); the amendment to decision 14 and
  invariant 14; what the old list held; history.
- **Amended at plan time, with the owner:** the workflow kit changed after the session started,
  and the block follows it.
  - Its build design for the stage moved to `KICKOFF.md`; the workflow keeps the rules.
  - `verify` with the drafted message is the last act before each commit, after the done-note
    and the handoff, so those are checked too.
  - The draft is `"$(git rev-parse --git-dir)/COMMIT_DRAFT"` (`.git/COMMIT_DRAFT` breaks in a
    worktree), written fresh for every commit and deleted after it.
  - At push time, the last commit's message (`git log -1 --format=%B`) goes into the draft
    before `verify` runs, then the push note is amended in.
  - This file's header follows the kit: the read order is the workflow's, and step 5 runs
    `verify` with the drafted message before the commit.

**Gates:**
- `uv run scripts/verify.py --message <draft>` green, as the last act before the commit.
- Each new check falsified once: a missing terms file fails and an empty one passes; a Cyrillic
  term is found, and so is the same term in NFD; `myTermNotes` and `term2026` are found; a term
  or a co-author trailer in the drafted message fails; a codegen script's note passes.
- No probe: nothing Krita-facing changes.

**Watch for:**
- **Unsure whether something is public? Ask the owner before writing it.**
- **Never print a term:** not in output, notes, the handoff or commit messages.
- **`~/.config/hygiene/terms.txt` is outside the repository:** ask before each write to it.
- **The handoff keeps opening Session 8** and carries forward everything it says; only the
  hygiene trap and the push status change.

**Done (2026-10-24, no version).**
- **Decided with the owner at the start:**
  - **No version.** Nothing a user of the server sees changes, so there is no CHANGELOG entry,
    and sessions 8–15 keep 0.8.0–0.13.0.
  - **The owner's own identifiers stay off the list.** Five of the old list's seven hashes were
    the owner's name forms, home-folder name and email handle, all public on every commit's
    author line and on GitHub. Decision 14, invariant 14 and §6 carry the owner's dated
    amendments.
  - **The other two hashes are dropped unidentified:** the owner does not remember them.
  - **The term list holds 0 words.** The owner does not count the first game's name as
    sensitive, and named no persona, no other people, and no projects or clients. The list
    already existed, empty, and this session wrote nothing to it.
  - **History is deferred** to a step before publishing, in `docs/BACKLOG.md`.
  - **The kit changed mid-session;** its changes became the plan-time amendments above.
- **Built:**
  - **`scripts/hygiene.py`**
    - **The list.** It reads `--terms`, defaulting to `~/.config/hygiene/terms.txt`. A missing
      file fails with its path; an empty one passes. A line that is not one word fails with its
      line number, never its text, since it could never match.
    - **Tokens.** Each line is NFC-normalised and split into runs of letters, digits and
      combining marks. The camel-case words and digit groups inside each run come from a
      per-letter case map, so camel case splits in any script. Terms and tokens are folded
      alike (NFC, lowercase, NFC).
    - **Attribution.** A "generated" line counts only when "with", "by" or "using" is followed
      by Claude, ChatGPT, GPT, OpenAI, Codex, Copilot, Gemini, Cursor or AI. Co-author trailers
      and AI session links are unchanged.
    - **Hits** read `path:N: private term`, `path: private term in the path`,
      `path (staged):N: private term`, `commit <sha>, message line N: <kind>` and
      `commit message draft, line N: <kind>`, with one problem per line and no hash.
    - **The draft.** `--message` is checked like a commit message; an unreadable draft fails.
  - **`scripts/verify.py`** parses `[stage …] [--message FILE]`. The draft's absolute path goes
    to the hygiene command, and `--message` without the hygiene stage exits 2.
  - **`scripts/hygiene_terms.txt`** is deleted.
- **Docs:**
  - `docs/DEVELOPMENT-WORKFLOW.md` is the kit's file verbatim, with the *In this repository*
    paragraph kept.
  - `CLAUDE.md`: the read order, step 9 and rule 1, the public section with the ask rule and
    the owner's data, the Commands table, and the Git note on drafting.
  - README's hygiene line; this file's header (read order and step 5) and table.
  - `SPEC.md`'s three amendments; `docs/BACKLOG.md`'s history step; the handoff.
- **What changes for sessions 8–15:**
  - **The commit order.** The done-note and the handoff come first. Then the message is written
    fresh into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, `uv run scripts/verify.py --message`
    runs with it, the commit is made with `git commit -F`, and the draft is deleted.
    - The review commit goes the same way.
    - A push note first puts `git log -1 --format=%B` into the draft, then runs `verify`, then
      amends.
    - No hygiene run after a commit.
  - **The term list** lives in `~/.config/hygiene/terms.txt`; `verify` fails without it.
  - **Unsure whether something is public?** Ask the owner before writing it; a word they call
    private goes on the list, with their yes.
  - **Done-notes and handoffs never name the owner's own data** (documents, folders, presets,
    roots).
  - **The read order.** The block's Read line, `CLAUDE.md`, `ARCHITECTURE.md`'s overview,
    invariants and baseline once it exists, then from `SESSIONS.md` only the header, the block
    and the previous done-note, then the prompt. The Read line is a floor.
  - **Session 15.** It is the round's release. Its review commit follows the close and carries
    the Review section in its message and the handoff, since the close has deleted this file.
    Its `ARCHITECTURE.md` is written to be read by section, with each decision in its
    subsystem's section.
  - **Tags** only where the table marks a milestone; round 1's marks none.
  - **Already done here:** a Read line in every block, `6a`/`7a` ids, architecture reviews with
    their own subject, and session 15 cutting 0.13.0.
- **Deliberate decisions:**
  - **No test can read the owner's list.** An autouse fixture points `TERMS_FILE` at a missing
    temp file, and the tests' lists are written outside every repository they scan.
  - **Combining marks join a run.** `[^\W_]+` splits a word in a script with vowel signs. The
    class is built from Unicode's M categories as 310 ranges at import (0.05 s); as single
    characters it made the stage three times slower.
  - **A list line that is not one word fails** instead of being skipped.
  - **`--message` without hygiene is refused,** so a draft never goes unchecked silently.
- **Falsified:** 19 breaks, each failing its own test. In the list: a missing file passing, an
  empty file failing, a line that is not one word accepted. In tokens: ASCII-only runs
  (Cyrillic), no NFC in the fold (NFD), runs without marks, no camel split, camel split on ASCII
  only. In messages: the draft left out of `check`, terms left out of messages, a broken trailer
  pattern, the old untargeted "generated" pattern, a tool list that matches nothing. In output:
  a hit printing its line. The default: a default other than `TERMS_FILE`, `TERMS_FILE` inside
  the repository, an unreadable draft passing. In `verify.py`: `--message` dropped, and allowed
  without hygiene.
- **By hand:** `scripts/hygiene.py --terms <missing>` exits 1 naming the path. Against the
  owner's empty list the stage passes in 0.6 s, against 0.3 s before.
- **Known debt:** a tool missing from the nine names passes a "generated" line. What the stage
  cannot see is in `SPEC.md` §6.
- **Numbers:**
  - `verify`: 6 stages, all PASS (hygiene 0.6 s);
  - 420 server tests passed, 0 skipped (+10);
  - 364 plugin-core tests passed, 0 skipped (+0);
  - `probe`: not run, as nothing Krita-facing changed (66 PASS, 0 FAIL, 21 MEASURED at 7's
    review).
- **Review (`/code-review high`), 8 findings, all fixed at the owner's request.**
  - **No test held `main` passing the draft to the scan;** a dropped argument would have let a
    co-author trailer through `verify --message`. A test now runs `main` on a temporary
    repository with a trailer in the draft.
  - **A byte-order mark** stuck to the list's first word and failed it as "not one word"; the
    list is read as `utf-8-sig`.
  - **Comment lines** in the list failed the stage; a line starting with `#` is skipped again,
    as the old hash file allowed.
  - **Stage names after `--message`** were refused; `verify.py` parses them intermixed.
  - **The credit pattern crossed line breaks,** so "generated with" at a line's end met a tool
    name on the next line; it now stays within one line.
  - **Other credit phrasings passed:** "written", "created", "authored" and "produced" count as
    well as "generated", with "via" beside "with", "by" and "using", and up to three words
    before the tool ("with the help of").
  - **An empty list still tokenised every line;** the scan now returns at once.
  - **The missing-list error printed the home path,** which a done-note could copy; a path under
    the home folder prints with `~`.
  - **Falsified:** 8 breaks, each failing its own test: `main` without the draft, plain
    `utf-8`, comments as words, the path without `~`, `parse_args`, a credit across lines, no
    words before the tool, "generated" as the only verb. The empty-list return is an
    efficiency change with no check of its own.
  - **Numbers after the review:**
    - `verify`: 6 stages, all PASS;
    - 424 server tests passed, 0 skipped (+4);
    - 364 plugin-core tests passed, 0 skipped.

---

## 8: The verification core, and layer_update

**Read:** `SPEC.md` §1 (decisions 20, 27), §5 (invariants 5, 6); `PDD.md` Part 4
(`krita_layer_update`; `krita_paint_stroke`, *Per-stroke verification*), Part 8 (*Verification*,
K13, K22, K42, K43, K44); `REVIEW-2026-10-24.md` F5, F19, F25.

- **Amended by review 6 (2026-10-24):**
  - **F25:** the core's contract marks the handle dirty before the first libkis mutation, as
    session 7 began; a confirmed rollback leaves it as it was, an unconfirmed one marks it unsafe.
  - **F19:** `blend_mode`'s enum in `krita_layer_update` is checked against the server's
    whitelist constant (6a).
  - **F5:** at most 300 characters net added to the instructions.
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
  - `CHANGELOG.md`: 0.8.0 (0.7.0 before review 6 inserted 6a).
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

**Done (2026-10-25, 0.8.0).**
- **Decided with the owner at the start:**
  - **Restarts:** the session may quit and relaunch Krita after `install-plugin` whenever `doctor`
    reports 0 unsaved documents.
  - **`layer_update` checks the composite and the tree, not protected-layer hashes:** a property
    write cannot move a layer's pixels, and hashing every protected layer over a canvas-wide
    layer's bounds costs a read of each. The core builds and tests the hash check (paint layers
    only, one buffer at a time); `paint_stroke` wires it.
  - **The plugin computes the counts, the server makes the images,** so a second server that
    shares a retry still gets the counts (as `selected_pixels` in 7).
  - **The rim check shows a hidden recolour layer with `inherit_alpha` in the same call,** with a
    contrast check refusing `visible` alone: toggling `inherit_alpha` alone on a layer with pixels
    always changes alpha on a soft rim.
- **Decided with the owner mid-session:** Krita was killed opening an 8k document (Measured), so
  the cost was measured at 4096 × 4096 and the 8k kill went to `docs/BACKLOG.md`.
- **A design check in plan mode** (one independent read of the plan against the code) found: an
  exception after the first write left the change unverified, and a retryable one would have let
  a retry make it again (`jobs.py` drops a request that fails retryably); a stale projection would
  make a good restore look failed; region scope missed non-whitelist blends, filter layers nested
  in later siblings, derived-bounds layer types and animation; the rollback's tree comparison had
  to skip bounds; the fingerprint change had call sites and typed tests to follow, and a blend step
  needed a region for history's capture; the PNG names would collide; the diff had to be built
  before raw files went; failure details must never carry raw files or become a retryable
  `IO_ERROR`; full scope needed cost bounds; the probe's documents and order had to keep each check
  observable; K43's check had to show Krita's Redo naming the step; a failed activation should be
  reported, not fail a verified change. The plan folded in a fix for each.
- **The plugin core.**
  - **`verification`** (pure, 3.10):
    - `reach(tree, effects, target)` lists every node that can carry a change past the target's
      bounds: on the target, inside it or on an ancestor, a filter, transform or colorize mask, a
      filter layer, a layer style, a blend outside the whitelist, or a type whose bounds are
      derived (`layer_type`: anything but paint and group layers and transparency and selection
      masks); a filter layer anywhere in a later sibling's subtree, of the target or of an
      ancestor; a clone of the target or an ancestor, or with no source Krita names.
    - `scope` is the union of the exact bounds of the target and its descendants, clipped to the
      canvas, or the canvas for `full`.
    - `refuse_unverifiable` refuses an animated document, one showing another frame, and a scope
      over `MAX_READ_PIXELS`. `allowed_rows` takes the mask's rows for the scope and refuses a
      mask the canvas has outgrown.
    - `read` takes the composite inside `unmasked_view` (K46), and optionally the target's pixels
      and a SHA-256 per hashed layer.
    - `check` works in bands of 2^20 pixels. Per pixel it makes a flags byte (1 changed, 2 outside
      the mask, 4 alpha changed) from `int.from_bytes` XORs over the strided channel slices and
      `translate` tables. It counts with `translate` and `count`, and bounds the changes row by
      row with `find`/`rfind`.
    - `same` compares two reads byte for byte. `files` writes before and after (BGRA8, up to
      `MAX_IMAGE_PIXELS` = 4096²) for a pass, before and the flags (A8) for a refusal; a file it
      cannot write is left out.
  - **`layer_update`:**
    - Exact arguments: `active` only `true`; opacity to 0–255 by `int(o * 255 + 0.5)`.
    - Refusals: the root and masks `INVALID_ARGUMENT`; `alpha_locked` on a non-paint layer
      `INVALID_ARGUMENT`; a protected layer or an ancestor of one `LOCKED_TARGET`.
    - Only values that differ are written. An appearance change gets reach (region), scope, the
      refusals, a refresh, then the before-read.
    - `before_change()` marks dirty first, except for `active` alone, which only `touched()`.
    - Writes: the blend first (its ledger step pushed, `after` reusing the selection hash), then
      the other properties in a fixed order, then a refresh.
    - Checks: the tree (the target as asked, every other node's watched fields unchanged, never
      bounds), then the after-read and `check`.
    - Rollback, on a leak, a tree mismatch or any exception: old values written back, the blend
      undone through `history.move` with `rolled_back()`, a refresh, then the tree and the scope
      confirmed. Confirmed: `dirty` back, the error non-retryable. Otherwise `ROLLBACK_FAILED`
      and unsafe.
    - A failed activation after a change is reported, not raised. The step's region is the
      changed bounds.
  - **`ledger`:** the fingerprint's nodes are `(id, blend mode)` pairs (`node_states`).
    `history.LABELS["layer.update"]` is "Composition Mode Change".
  - **`harness.add_node`:** a blur filter layer above a layer, a blur filter mask or a transform
    mask on it, or a clone of it on top. Harness folder only; it seals the ledger and stamps
    `touched()`.
- **The adapter:** `set_blend`, `set_properties` (name, locked, alpha_locked, inherit_alpha,
  visible, opacity), `refresh` (`refreshProjection`, `waitForDone`), `effects` (`layerStyleToAsl`,
  `CloneLayer.sourceNode`, `animated`), `add_fixture_node`.
- **The server.**
  - **`krita_layer_update`** (`tools/changes.py`), journaled; `resolve_update`, also in
    `operations.RECEIPTS`, makes `<op>.before.png` and `<op>.after.png`, or `<op>.diff.png`, found
    before made. The images are null when another server took the pixels or a PNG cannot be
    made; the code never changes. The receipt inlines the diff from `details.verification.diff`.
    `STEP_TOOLS` names the blend step.
  - **`verification.py`:** the PNGs, and the diff image (offending pixels red over the scope as
    it was, faded toward white, at most 1024 px long, block-reduced so none vanishes; alpha
    changes offend only under `preserve_composite_alpha`).
  - **The schema** gains `active` (`const: true`), `verify`, the blend enum (F19, held by a test
    against `observe.BLEND_MODES`), and the receipt's `undoable`, `undo_steps` and `verification`;
    its example is new. `amend_schemas.py` ran.
  - **Instructions (F5):** 2,920 characters (+300).
- **The probe (`probe/updates.py`, fixtures `update_stack` and `rim_stack`):** three working
  copies. A: `active` alone; the ledger and labels; `LOCKED_TARGET`; then the harness nodes. B: the
  allowed rect, the opacity leak and K43. C: the rim under `preserve_composite_alpha`.
  `krita_layer_update` joins the read-only refusals. The helpers it shares with `probe/changes.py`
  are public there.
- **Amendments:**
  - **The three decisions above** are the owner's, at plan time.
  - **Region scope refuses more than PDD Part 4 lists:** blends outside the whitelist, derived-bounds
    layer types, filter layers inside later siblings, animated documents and scopes over one read
    are each refused before any change. Design check, amended at plan time, with the owner.
  - **The projection is refreshed before the before-read,** so a write elsewhere that Krita has not
    drawn yet (K42) is not read as this change. Design check, amended at plan time, with the owner.
  - **A refusal sends the before image and the flags, not the after image,** and the diff is drawn
    over the scope as the rollback left it: the after buffer is dropped before the re-read. The
    session's own finding.
  - **The receipt's before and after images stop at 4096²,** the largest capture; the counts are
    always there. Design check, amended at plan time, with the owner.
  - **The 8k cost was measured at 4096 × 4096.** The owner's choice, mid-session.
- **Measured** (Krita 5.3.4.1 on macOS, Apple Silicon):
  - **Labels:** `setBlendingMode` pushes "Composition Mode Change". Two blend changes of one layer
    are two steps. Name, opacity, visibility, inherit-alpha, alpha lock and lock push none: the Undo
    label stays the blend's, and history then undoes both blends.
  - **The creators:** `createFilterLayer`, `createFilterMask(name, filter, selection)`,
    `createTransformMask` and `createCloneLayer` all work. Each add pushes "Add Layer". The
    composite changed for the blur filter layer, the blur filter mask and the clone, not for the
    identity transform mask. A filter layer and a filter mask report blend "copy".
  - **A blur filter layer above** spread an opacity change of a 24 × 16 layer to a 34 × 26 rect
    (`verify: "full"`).
  - **A refused, restored and confirmed opacity change:** 21 ms on 64 × 48. The restored composite
    matched the before-read byte for byte every time.
  - **Under `inherit_alpha`** Krita kept every alpha byte of a soft rim, but changed the colour
    bytes of every fully transparent pixel under the layer: 1,728 px changed, 768 of them visible
    (in `docs/BACKLOG.md`).
  - **4096 × 4096, one layer over a base:** a verified opacity change 0.57 s (region over the whole
    layer) and 0.64 s (full); a leak with its rollback and confirmation 0.79 s; open 0.6 s.
  - **8192 × 8192:** Krita was killed, with no crash report and no clean shutdown in
    `plugin.log`, during the bridge's `document.open` of a two-layer ORA, before any update. Not
    reproduced (in `docs/BACKLOG.md`).
  - **`probe` on the 0.8.0 build:** 75 PASS, 0 FAIL, 25 MEASURED in 40.7 s; H4 p50 5.0 ms, p95
    5.5 ms, max 39.4 ms; create and close mean 708 ms; `transfer/` and `harness/` empty,
    `plugin.log` with no warning or error.
- **Checked by hand:** `doctor` before and after each of the session's five Krita restarts and
  its relaunch after the kill: 0 documents open, 0 unsaved, steps 1–5 PASS, step 6 FAIL "no
  roots".
- **Falsified:**
  - **The method:** the scratchpad driver of 6a and 7, which checks the tree's diff hash before
    and after.
  - **65 unit breaks, each failing at its own test:**
    - the core: each mark table, the preserve rule, bands, hashes, the empty-scope bound, `same`,
      the mask rows, the hashed read, the unmasked read, the empty read, the clip, each reach
      rule and the listing of every reason, the animated refusal, the files' flags, cap and
      write failure;
    - `layer_update`: the after image, rounding, the step's region, the fingerprint's blend,
      active-only, appearance-only reads, unchanged values, the ancestor and mask rules, the
      opacity bound, the reach and animated refusals, the dirty restore, the preserve flag,
      `rolled_back`, the confirming re-read, an undo not taken, retryable errors, a rollback that
      raises, a value Krita adjusted, the first refresh, the empty scope, the activation rule;
    - the harness seal and kinds, the read-only refusal;
    - the server: the flag constants, the blend enum, the image bound, the PNG names, `verify`
      sent, the inline diff, a shared retry (its two guards broken together), the diff's
      block-reduce, preserve rule and fade, an untouched refusal, images that cannot be made.
  - **Two tests were strengthened** before their breaks failed:
    - the band test used one colour everywhere, so a band read from the wrong place matched;
    - the harness seal test had no ledger step to seal, so a dropped seal changed nothing.
  - **Live:**
    - **A server break** (`verify` always region) failed the filter-layer check. It also failed
      the each-named check, whose opacity matched a value an earlier step had set; that check now
      uses one no earlier call sets.
    - **Plugin build 1** (six breaks) failed its six checks: active-only dirtying, a wrong blend
      label, the ancestor rule off, the sibling filter scan off, the clone source unread, the
      preserve flag dropped.
    - **Plugin build 2** (four breaks) failed its four checks: the dirty restore, a rollback
      granting a redo (K43), the inherit-alpha write ignored, read-only updates allowed. The
      other failures in each build followed from a break the other build tested.
- **Known debt:**
  - **Layer styles** are held by unit tests only (in `docs/BACKLOG.md`).
  - **Filters are classed by type,** so a per-pixel filter layer forces `verify: "full"` (in
    `docs/BACKLOG.md`).
  - **Colour changes under alpha 0 count** as changes (in `docs/BACKLOG.md`).
  - **Labels are English** (in `docs/BACKLOG.md`, from 7).
- **Numbers:**
  - `verify`: 6 stages, all PASS;
  - 434 server tests passed, 0 skipped (+10);
  - 438 plugin-core tests passed, 0 skipped (+74);
  - `probe`: 75 PASS, 0 FAIL, 25 MEASURED (+9 PASS, +4 MEASURED), 40.7 s;
  - 16 registered tools (+1); 19 schema files; instructions 2,920 characters (+300).
- **Review (`/code-review high`), 10 findings, all fixed at the owner's request.**
  - **The blend rule refused every blend outside the paint whitelist,** on ancestors too. Only
    copy, destination-in and destination-atop composite past a layer's extent
    (`kis_layer_projection_plane.cpp:48-50`, `v6.0.4.1`), and only on the changed layers: the rule
    now names those three on the target and its subtree (`SPREADING_BLENDS`).
  - **A PNG that could not be written lost its pixels,** because the raw files went regardless;
    they now stay until their PNG exists, for a later rebuild.
  - **The inline diff had no size bound,** so an oversized one would turn the refusal into a bare
    `INTERNAL_ERROR`; it is inlined only under `INLINE_BYTES`, and its artifact always named.
  - **The diff image did float work at the scope's full size;** it now composites and greys with
    Pillow in 8 bits and fades the shrunk image only.
  - **Two full-size PNGs per update** cost about 1.4 s for painted art at 4096² under the server's
    call lock (0.72 s each, measured); the receipt keeps before and after up to 2048² now, held
    equal on both sides (`IMAGE_PIXELS`, `MAX_IMAGE_PIXELS`).
  - **The PNG helpers had two homes;** `verification.keep`, `image_of` and `artifact` serve the
    selection's mask and history's capture too.
  - **`effects` serialised every layer style for every change;** styles and clones are read only
    for region scope.
  - **The leak counts were in the details twice;** they live in `details.verification`.
  - **The instructions named only part of the refusals;** they now add copy blends and animated
    documents, at 2,910 characters (+290).
  - **Comments of three lines** are shortened.
  - **Falsified:** 7 breaks, each failing its own test: the spreading blends named, per-pixel and
    ancestor blends not, full scope reading no styles, one home for the counts, raw files kept on a
    failed write, the inline bound, the image bound held equal.
  - **Measured:** `probe` 75 PASS, 0 FAIL, 25 MEASURED in 38.6 s on the reviewed build. The first
    run stopped at the export's `BUSY` (Krita's autosave); the rerun passed.
  - **Numbers after the review:**
    - `verify`: 6 stages, all PASS;
    - 436 server tests passed, 0 skipped (+2);
    - 442 plugin-core tests passed, 0 skipped (+4);
    - `probe`: 75 PASS, 0 FAIL, 25 MEASURED, 38.6 s.

---

## 9: paint_stroke

**Read:** `SPEC.md` §1 (decisions 6, 20), §5 (invariants 1, 5, 6); `PDD.md` Part 4
(`krita_paint_stroke`, *States & edge cases*), Part 5 (N-01, N-06 to N-09), Part 8 (K2 to K5, K9,
K10, K18, K21, K30, K37, K43, K44, K47); `REVIEW-2026-10-24.md` F2, F3, F5, F10, F19.

- **Amended by review 6 (2026-10-24), measured and recorded in the done-note:**
  - **F2:** Krita's memory before and after the N-01 run, against the bridge's retention.
  - **F3:** the journal's size and a fresh server's first-lookup time after the N-01 run; if
    either bites, the index stops decoding `args` (a sidecar per operation, the lines small).
  - **F10:** the open time and disk use of the N-09 fixture's baseline (256 MB as BGRA8); then
    a bound on `working_copy` opens above `capture_source_pixels`, a tiled baseline, or a
    baseline written lazily for the first `preview_render`, the owner's call.
  - **F19:** `blend_mode`'s enum in `krita_paint_stroke` is checked against the server's
    whitelist constant (6a).
  - **F5:** at most 300 characters net added to the instructions.
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
  - N-09: 8192 × 8192 with 30 protected layers; p95 under 3 s. The fixture's layers are
    sparse (small content on the full canvas), so the ORA stays small; measure Krita's memory
    before and after and record it.
- **Docs.**
  - `CHANGELOG.md`: 0.9.0 (0.8.0 before review 6 inserted 6a).
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

**Done (2026-10-25, 0.9.0).**
- **Decided with the owner at plan time:**
  - **Benchmark strokes:** 20 per benchmark, each a 200-point S-curve about 600 px long in a
    400 × 400 area, 40 px brush (R 464 × 364); three corner-to-corner strokes measured, not gated.
  - **R's margin is set by the tip** (`e` 0.5 for a round auto tip, √2⁄2 for square and image
    tips); it only widens R.
  - **F3's rule:** it bites if, extrapolated to 7 days × 2,000 strokes of 200 points, a fresh
    first lookup would pass 1 s or the journal 100 MB; then the arguments move to a sidecar here.
  - **Restarts:** at 0 unsaved documents, without asking.
  - **Parallel parts, as a one-session trial** of the kit's *Parallel parts* section
    (`~/Documents/Claude Templates & Notes/AppDev/workflow-kit/parallel/DEVELOPMENT-WORKFLOW.md`);
    this project's workflow and `CLAUDE.md` unchanged. Krita runs only at integration.
- **Decided with the owner mid-session:**
  - **The preset fingerprint leaves out what every stroke sets** (opacity, flow, blend, eraser,
    and the tip's diameter, scale and angle), since Krita writes them into the active preset and
    the next stroke's hash check would fail.
  - **Krita's preset history in `kritarc` is accepted and recorded:** activating presets makes
    Krita write `LastPreset` and `presethistory` itself. A scratchpad driver of this session
    activated about 50 stock presets without saving the brush state first, so the owner's earlier
    selection there was not put back.
  - **A one-point stroke and `eraser: true` are refused** with `UNSUPPORTED_CAPABILITY` (measured
    below); erasing goes to `docs/BACKLOG.md`.
  - **F10: a lazy baseline, in session 11** (block 11 amended).
- **A design check in plan mode** (one independent read of the plan against the code) found:
  - a stroke's ledger step has no identity of its own (equal fingerprints, a shared label), so
    history could undo another stroke and cross the protection floor;
  - R was built from the asked brush, not the one Krita paints with;
  - the target-bounds check cannot see a dab outside R inside the layer's old bounds, and fails at
    the canvas edge;
  - a raise in `paint_path` was assumed to have changed nothing;
  - the protected-layer hash skip needed the bounds compared after the stroke;
  - the memory of full scope at 8k; `step.region`; the schema copy and the tests that hold it.

  The plan folded in a fix for each: the witness, the brush read back and checked twice, the
  guard ring, the raise path, the bounds comparison.
- **The plugin core** (`bridge_core/painting.py`, `brushes.py`; part 9.1):
  - **`paint.stroke`,** guarded like `layer.update`, with exact arguments, then the refusals in
    order: colour space, the target (protected, type and space, any local selection mask), on-curve
    points past the canvas grown by half the size, the preset by file id (with the 5 nearest),
    the listed fingerprint, cumulative undo, region reach.
  - **Inside `in_front`:** the brush set in K3's order and read back (preset, blend, eraser and
    alpha lock must be taken), `paintAbility()`, the reach from the effective preset's XML
    (`brush_reach`: engine, tip, spacing, scatter; region fails closed on another engine, an
    unknown tip or missing scatter keys), R and the ring R′, the refusals over the scope,
    `OUTSIDE_ALLOWED_MASK` over R, a refresh, the before-read (the composite over the scope, the
    target over R′ or its old bounds ∪ R′, each protected paint layer meeting the scope hashed over
    its bounds ∩ scope), the brush read again, the fingerprint, `before_change()`, `paint_path`.
  - **The checks:** the composite; every protected paint layer's bounds and hash; in region scope
    the target's diff inside R and its bounds inside its old bounds ∪ unclipped R′.
  - **The step** carries a witness (the target's own bytes over its diff D, hashed before and
    after); `history.move` checks it before and after every move. An empty D seals the ledger.
  - **Rollback:** one undo through `history.move`, or after a raise a re-read and an undo only
    when the label and a witness built from the re-read match; confirmed by the re-read, `same()`
    and the bounds; otherwise unsafe and `ROLLBACK_FAILED`. Never retryable; a `BaseException`
    marks the document unsafe.
  - **The preset check remembers the bridge's own activations** for the Krita session (the
    digest a preset had before its first activation, by the digest it has after), so a preset
    Krita fills in on loading keeps its listed hash, and any other change still mismatches.
  - **Harness:** `harness.view` (zoom, rotation, pan), `harness.brush_state` (by file id),
    `harness.undo`; `probe.retention` on the bridge; `probe.preset_xml` for measurements.
  - **Capabilities:** `stroke.native_brush`, `stroke.smoothing`, `selection.enforced` since 0.9.0.
- **The adapter** (`krita_adapter/painting.py`, coordinator): the `View` setters and getters in
  K3's order, `ManagedColor` with components in B, G, R, A order (N-06 exact), `Node.paintPath`
  with mirror painting and wrap-around off and put back, the cumulative-undo setting
  (`useCumulativeUndoRedo`), `Canvas` zoom and rotation, pan through the canvas controller's scroll
  bars, the brush state by preset file id. The extension registers `paint.stroke`.
- **The server** (part 9.2, then the coordinator):
  - **`krita_paint_stroke`** (`tools/painting.py`, `strokes.py`): refusals before the journal
    (argument errors first: eraser with alpha lock, colour alpha; then `smooth` basic or
    stabilizer, `antialias: false`, the eraser, the input gate; then numbers that are not finite;
    then a stroke without length); Catmull-Rom as exact cubics; `journaled`; `resolve_update` for
    the PNGs; the receipt with `input_applied: "flat"` and an inline diff on a refusal.
  - **The schema** as PDD Part 4, `verification` copied from `krita_layer_update` by
    `amend_schemas.py`; `reach.tip` includes `unknown`.
  - **The journal is version 2:** each call's arguments go to `journal/args/<day>/<op>.json`
    (0600, written before the line names them); version 1 lines are still read.
  - **Instructions:** 3,175 characters (+265).
- **The probe** (`probe/painting.py`, coordinator): the paint checks and both benchmarks on the
  probe's own working copies, the brush state read first and written back; `write_sparse_ora`
  for the 2k and 8k masters.
- **Amendments:**
  - **The plan-time decisions above**, with the owner.
  - **R's margin** is `max(32, size × (e + 2e·s) + 2)`: the scatter moves a dab by up to its
    strength times the dab mask's width and height, which a rotated tip stretches to 2e × size,
    and the mask's whole pixels add up to 2 px. One stroke in 30 of `y) Texture Spray` at size 24
    passed the narrower margin and was caught by the ring and rolled back; 120 strokes on three
    presets passed the wider one. The session's own finding; it only widens R, as decision 2 allows.
  - **The guard ring, the witness, the fail-closed reach parse with `brush_engine`, the bounds
    skip for protected layers, the cumulative-undo refusal:** design check, amended at plan time.
  - **Any local selection mask is refused,** not only an active one: libkis does not say which is
    active. Plan time.
  - **Full scope widens an unnamed reach** (an unknown tip as √2⁄2, an unknown scatter as 5, with
    `reach.tip` `unknown`), and the ring and target-bounds checks run in region scope only. Answered
    by the coordinator to part 9.1 mid-run.
  - **The counts stay nested in `verification`,** as `krita_layer_update`'s, not at the top level;
    `protected_pixels_changed` counts the first changed protected layer, after the stroke against
    after the undo; `OUTSIDE_ALLOWED_MASK` is judged over R. Plan time.
  - **The fingerprint's two further exclusions:** the tip's angle (the brush rotation each stroke
    sets) and its layout whitespace, then the defaults Krita fills into an image tip on first load,
    then the bridge's memory of its own activations; each found live.
  - **F3's sidecar landed** (it bit by the journal's size, 180 MB a week).
  - **The parallel-parts trial,** amended at plan time with the owner; see *Parts*.
- **Measured** (Krita 5.3.4.1 on macOS, Apple Silicon):
  - **Labels:** a stroke is "Scripted Brush Stroke"; Krita's Redo action reads "Redo " and stays
    enabled even with nothing to redo.
  - **Stock presets:** `b) Basic-1` is the Quick Brush engine (`roundmarker`), so region scope
    refuses it; the probe uses `b) Basic-2 Opacity` (hard round), `b) Airbrush Soft` and
    `y) Texture Spray` (image tip, scatter 1). Of about 50 stock presets tried, the pixel
    engine's parsed and painted in region scope; Color Smudge, MyPaint, spray, deform and
    tangent-normal refused.
  - **A stroke writes into the active preset:** `OpacityValue`, `FlowValue`, and the tip's
    `diameter`, `scale` and `angle`. On a preset's first activation in a session Krita fills
    defaults into an image tip (`ColorAsMask`, `BrightnessAdjustment`, `md5sum` and others), and
    rewrites the tip's whitespace.
  - **No dab without length:** one point, two equal points and a 0.01 px segment painted nothing;
    0.5 px painted one dab.
  - **The eraser:** `eraserMode()` read false after `setEraserMode(True)` with every preset tried.
  - **Pan** is reachable through the canvas controller's scroll bars; zoom and rotation through
    `Canvas`.
  - **N-01:** p95 0.08 s (budget 1.5 s), mean 0.07 s; corner to corner 0.39–0.42 s.
  - **N-09:** p95 0.26 s (budget 3 s), mean 0.21 s; corner to corner 3.81–3.85 s.
  - **F2:** Krita 937 MB before N-01 and 1,037 MB after; the bridge held 894 operations, 890
    requests and 890 bindings after the run.
  - **F3:** before the sidecar 12.8 KB per stroke, a week 180 MB and 0.93 s (it bit); after it
    3.2 KB of lines per stroke, a week 44 MB and 0.21 s.
  - **F10:** the 8k open 4.7–5.2 s, a 268 MB baseline, Krita +300–500 MB that stayed after the
    close; no recurrence of 0.8.0's kill in six 8k opens.
  - **`probe` on the 0.9.0 build:** 95 PASS, 0 FAIL, 32 MEASURED in 70.1 s; H4 p50 4.9 ms, p95
    5.4 ms, max 39.3 ms; create and close mean 692 ms; `transfer/` and `harness/` empty,
    `plugin.log` with no warning or error.
- **Checked by hand:** `doctor` before and after each of the session's eleven Krita restarts:
  0 open, 0 unsaved, steps 1–5 PASS, step 6 FAIL "no roots".
- **Falsified:**
  - **The parts' own** (their notes): part 9.1 89 breaks, part 9.2 one per new check, each failing
    at its own test; four tests strengthened in 9.1 first.
  - **The coordinator's 23 unit breaks,** each failing at its own test with the tree unchanged:
    the eraser and lengthless refusals, each fingerprint exclusion and default, the activation
    memory (both halves), the margin's scatter term and rounding, the journal's sidecar (inline
    args, the folder's mode, the partial file, the v1 reader), the fake's snapshot order, the
    stroke's step tool, the PNG resolve, the refusal's retryable flag, the sparse writer's three
    rules. The sparse merge's test was strengthened (a transparent hole) before its break failed.
  - **Live:** one server run and three plugin builds, split so no break failed another new check
    for its own reason:
    - **server:** a sleep on 200-point strokes, `input_fallback` ignored, the eraser refusal off;
    - **build A:** the capability flag, the channel order, the local-mask refusal, the outside-mask
      refusal, the brush state not written back, the path moved by the view's rotation, a longer
      sleep for N-09;
    - **build B:** the witness off (after the probe's witness check was strengthened: two strokes,
      so the label alone cannot tell), a rollback that claims an undo;
    - **build C:** the stroke painted twice, the bridge's dedup off, the reach refusal off, the
      read-only gate off.
- **Known debt:** erasing, a single dab, region scope for other engines, not-finite numbers in
  other tools, Krita's memory after an 8k close, the preset history, and the mirror and
  wrap-around restore by hand (all in `docs/BACKLOG.md`).
- **Numbers:**
  - `verify`: 6 stages, all PASS;
  - 483 server tests passed, 0 skipped (+47);
  - 556 plugin-core tests passed, 0 skipped (+114);
  - `probe`: 95 PASS, 0 FAIL, 32 MEASURED (+20 PASS, +7 MEASURED), 70.1 s;
  - 17 registered tools (+1); 19 schema files; instructions 3,175 characters (+265).
- **Parts** (2, run in parallel with the owner's yes; merged in the order 9.1, 9.2):
  - **9.1, the plugin core.** Built as above, against the fake on 3.10; 89 breaks falsified;
    +112 plugin-core tests. It stopped three times for contract gaps, which the coordinator
    answered: full scope with an unnamed reach; the brush state keyed by file id, not name; and the
    types stage, which needed the adapter's methods, so it cherry-picked the coordinator's two work
    commits (identical patches, so the merge stayed clean). Wall time 14:00–14:32.
  - **9.2, the server tool.** Built as above; one break per new check; +35 server tests; found that
    NaN and Infinity pass the schemas. One amendment from the coordinator (the `unknown` tip).
    Wall time about 22 minutes.
  - **The coordinator,** meanwhile: the adapter, the probe and the fixtures (two work commits
    before the merges).
  - **Integration fixes:** the fake took its undo snapshot before giving a fresh document its
    pixels, and gave lazily made layers other pixels than its reads had shown, so the end-to-end
    tests' rollback and history undo failed until both were fixed (fake only; Krita always holds
    a layer's pixels). Every other failure at integration was a live fact, listed above.
  - **The counts add up:** server 436 + 3 (fixtures) + 35 (9.2) + 9 (integration) = 483;
    plugin-core 442 + 112 (9.1) + 2 (integration) = 556.
  - **Time saved:** about 45 minutes of the coding stretch (the parts ran 14:01–14:33 beside the
    coordinator's own steps, against an estimated 80 minutes one after another); integration and
    the live work, the larger part of the session, are unchanged.
  - **What the briefs missed:** the types stage on a branch without the adapter; the harness op's
    preset ids against the port's names; the unnamed reach in full scope. Each was a contract gap
    a part had to stop on.
  - **Merge trouble:** none; both merges were clean and `verify` passed on each drafted message.
- **Review (`/code-review high`), 10 findings, all fixed at the owner's request.** It covered the
  parts' commits, the merges and the session commit together.
  - **A stroke that changes no pixel sealed history silently.** Krita pushes "Scripted Brush
    Stroke" for it (measured), but that step's undo changes no pixel, so nothing could confirm it
    and sealing stays the safe course. The receipt now says so (`history_sealed`, in the schema,
    and the text line), and finding 4's refusal removes the common cause.
  - **Mirror painting could stay off** if switching wrap-around off raised before the `finally`;
    both switches now run inside it, each noting a mode before turning it off.
  - **The benchmarks understated the hashing:** the protected layers were 96 px squares, hashed
    only where they meet R. Each now covers the strokes' area and its margin. N-01 p95 0.09 s and
    N-09 p95 0.23 s, against 0.08 s and 0.26 s before: the hashing over R costs little.
  - **Sub-half-pixel strokes passed and painted nothing:** the refusal now takes the stroke's
    length, under 0.5 px (measured: 0.01 px painted nothing, 0.5 px one dab).
  - **A failed rollback reported 0 protected pixels:** it reports `null` when no confirmed undo
    brought back what they are counted against.
  - **The probe's comments cited a review finding and the plan's decision numbers,** which
    collide with `SPEC.md`'s; they now say what they mean.
  - **The image-tip defaults list** duplicated the activation memory and was tied to one Krita
    build; it is gone, and the memory carries the bridge's own first uses.
  - **Rect union and the finite-number check had several homes;** `verification.union` and
    `errors.number` now serve the core, history and the harness.
  - **`harness.undo` left the document clean;** it now marks it dirty, as any change through the
    bridge does.
  - **The journal made three folders private on every call;** each day's folder once per process.
    The argument files stay, as the journal does (PDD Part 6: permanent).
  - **Falsified:** 8 breaks, each failing its own test with the tree unchanged: the sealed flag,
    its receipt text, the length refusal, the uncounted protected change (both paths), the harness
    undo's dirt, the folders made private once, the benchmark layers' cover. The adapter's restore
    of the modes has no check: no harness op can turn them on (in `docs/BACKLOG.md`).
  - **Measured:** `probe` 95 PASS, 0 FAIL, 32 MEASURED in 70.8 s on the reviewed build.
  - **Numbers after the review:**
    - `verify`: 6 stages, all PASS;
    - 486 server tests passed, 0 skipped (+3);
    - 558 plugin-core tests passed, 0 skipped (+2);
    - `probe`: 95 PASS, 0 FAIL, 32 MEASURED, 70.8 s.

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

**Done (2026-10-25, no version).**
- **Decided with the owner in plan mode**, over the 13 findings of `REVIEW-2026-10-25.md`:
  - **F1, F2 (Medium), F5, F6, F7, F9 (Low)** become one inserted session, **10a** at 0.10.0;
    sessions 11–15 shift to 0.11.0–0.14.0.
  - **F4 (Medium)** is recorded as two measured assumptions, and 10a measures a tall image tip
    live against the margin's extent bound.
  - **F3 (Medium)** — the three hand-rolled verified-mutation skeletons — is recorded for the
    Phase 2 intake, which owns extracting one frame before any new mutating op.
  - **F8 (Low)** is recorded; nothing to do. **F10 (Info)** is already in `docs/BACKLOG.md`
    (*Undo labels in other languages*, 0.7.0). **F11, F12, F13 (Info)** are recorded.
- **The review.** `REVIEW-2026-10-25.md`: method, the baseline as found, what holds (the
  layering, the focus invariants 1, 4, 5, 6 and 13 traced to their enforcement, tests and probe
  checks, the ledger's floor arithmetic, review 6's findings' fate, the pinned constants),
  13 findings with `file:line` evidence on `dffdf73`, the drift inventory, the paint core against
  sessions 11–12 and Phases 2–3, where each finding landed, and the measurements. A second,
  independent cold read of the paint core, without the first read's notes, added F1, F2, F6 and
  F8, sharpened F4 and F5, and confirmed the floor arithmetic and the retry safety; its findings
  were verified on the code path before they were kept.
- **The plan.** The 10a block below; the table and the shift note above; the version lines of
  blocks 11, 12, 14 and 15 updated to the shifted numbers.
- **Measured** (details in the REVIEW's §7): `probe` 95 PASS, 0 FAIL, 32 MEASURED in 67.9 s on a
  first attempt (0 open, 0 unsaved); H4 p50 5.6 ms, p95 6.1 ms; create and close mean 717 ms;
  N-01 p95 0.09 s of 1.5 s, N-09 p95 0.15 s of 3 s; the bridge held 1,216 operations after N-01;
  the journal does not bite (3.2 KB of lines per stroke, first lookup 3 ms); `transfer/` and
  `harness/` empty after the run, `plugin.log` clean.
- **Checked by hand:** nothing needed checking; the session restarted nothing and the owner's
  Krita held no documents.
- **Falsified:** nothing; the review adds no check (10a falsifies the checks its fixes add).
- **Numbers** (unchanged, as found):
  - `verify`: 6 stages, all PASS;
  - 486 server tests passed, 0 skipped;
  - 558 plugin-core tests passed, 0 skipped;
  - `probe`: 95 PASS, 0 FAIL, 32 MEASURED, 67.9 s;
  - 17 registered tools; 19 schema files; instructions 3,175 characters.
- **Review (`/code-review high`), 6 findings, all fixed.** All in the documents this session
  wrote.
  - **The REVIEW's `layers.py` citations named lines past the file's end** (a concatenated read's
    numbering); they now point at the create handler and its rollback, lines 17–65.
  - **The method paragraph's counts were wrong:** the server is 31 modules, not 25, and the tests
    are 638 functions in 38 files, not 686 in 30.
  - **The settled close was attributed to 6a;** it landed in 0.7.0, as the backlog's crash entry
    records.
  - **The handoff's read order had drifted from block 10a's Read line** (an extra SPEC §1); the
    handoff copies the block's line again.
  - **Block 10a's Docs line hedged on a README version that exists;** README names 0.9.0, so the
    line says so.
  - **One spelling drift** ("journalling") joined the repo's "journaling".
  - **Falsified:** nothing; no check was added.
  - **Numbers after the review:** unchanged.

---

## 10a: Review fixes — paint safely

Inserted by review 10 (2026-10-25): the owner chose findings F1, F2, F5, F6, F7 and F9 of
`REVIEW-2026-10-25.md` as one fix session, with F4's live measurement beside them. Sessions
11–15 shift to 0.11.0–0.14.0.

**Read:** `REVIEW-2026-10-25.md` §3 (F1, F2, F4–F7, F9) and §6; `SPEC.md` §5 (invariants 5, 8);
`PDD.md` Part 4 (`krita_history_step`), Part 8 (K43, K44).

- **F1: `layer.update` closes its `BaseException` window.** Mirror the stroke's handler
  (`bridge_core/painting.py:141-145`) around the mutation phase of
  `bridge_core/layer_update.py:67-95`: seal, mark unsafe, re-raise; `_blend`'s guard
  (`:133-136`) gains the unsafe mark too.
- **F2: `history.step` holds invariant 5 on every path.** Each `move` in `step_history`
  (`bridge_core/history.py:149-163`) is wrapped so an escape marks the document unsafe; the
  region capture (`:164-171`) becomes best-effort, as `verification.files` is — the receipt
  reports the undos that ran, with `pixels: null` when the file could not be written.
- **F6: a LOST stop says so.** `stopped` distinguishes LOST from REVERSED
  (`history.py:157-162`); `krita_history_step.json`'s `stopped` enum gains the value
  (`amend_schemas.py` after the edit), and the receipt's text names the document unsafe.
- **F5: the unpinned duplicates are pinned or rehomed.** Parity tests for the stroke bounds
  (`bridge_core/painting.py:36-37` against `krita_paint_stroke.json` and
  `observe.LIMITS["stroke_points"]`), the adapter's `SRGB_PROFILE`
  (`krita_adapter/painting.py:12`, or import it from `bridge_core.documents`), and the probe's
  `LABEL` (`probe/painting.py:27` against `history.LABELS`); one home for the
  allowed-mask/canvas-size rule (`verification.py:222-225`, `protection.py:96-99`) and for
  `_refuse_reach` (`painting.py:567-575`, `layer_update.py:301-309`).
- **F7: the probe retries a `BUSY` KRA export once,** with a fresh request id
  (`probe/opening.py:100-126`).
- **F9: Krita's default undo-stack limit is measured live** and recorded in the done-note;
  `undo_limit`'s fallback (`krita_adapter/documents.py:264-271`) is set to the measured default.
- **F4's measurement: a non-square image tip against the extent bound.** On a probe document,
  a stroke with a stock preset whose image tip is markedly non-square, its actual changed bounds
  compared with R; recorded as MEASURED, with the margin's `EXTENT[IMAGE]` assumption confirmed
  or corrected.
- **Docs.**
  - `CHANGELOG.md`: 0.10.0 — the hardened failure paths (F1, F2, F6) under Fixed.
  - README: the version line (it names 0.9.0 today).
- **Ask at the start of 10a:** which stock preset carries F4's non-square image tip (the session
  proposes one from `krita_resource_list`), and whether any carries none, in which case the
  assumption is recorded as unmeasurable with stock presets.

**Gates:**
- `uv run scripts/verify.py`, with these tests: the `BaseException` paths of `layer.update`
  (a non-`Exception` raise mid-mutation seals, marks unsafe and re-raises), the wrapped `move`
  (an escape marks unsafe), the best-effort capture (an `IO_ERROR` leaves `pixels: null` on a
  truthful receipt), the LOST `stopped` value, and the F5 parity tests.
- Each new check falsified once.
- `install-plugin`, a Krita restart (the plugin changes), then `probe` green, with the F4 and F9
  measurements recorded.

**Watch for:**
- **A review fix must not loosen a refusal.** F2's best-effort capture changes only the file
  write; a failed undo still fails the op.
- **`amend_schemas.py` after any schema edit;** the `--check` test holds the files to it.
- **Restart Krita only at 0 unsaved documents** (decision 21), as ever.

**Done (2026-10-27, 0.10.0).**
- **Decided with the owner at the start:**
  - **F4's preset** is `y) Texture Wood Fiber`. Its tip, `rake_dotted.png`, is 7 × 32 px
    (4.6:1, the most extreme tall tip in the stock set). It uses the pixel engine, has scatter
    off, and turns with the drawing angle.
  - **F9:** the measuring machine's kritarc sets `undoStackLimit`, and harnesses never touch
    kritarc, so the built-in default could not be measured live. The owner chose:
    - a live check that Krita keeps exactly what `undo_limit()` reads;
    - the default cited from Krita's source;
    - the fallback set to that default.
  - **F6's value** is `stopped: "document_unsafe"`. `"unconfirmed"` stays for a step Krita did
    not take, which was put back.
- **F1: one guard around a change and its rollback.** `history.unconfirmed(handle)` is a context
  manager: it lets the op's own `BridgeError` through, and on any other raise it seals the
  ledger, marks the document unsafe and re-raises.
  - `layer_update.update` runs its mutation, verdict and `_roll_back` inside it.
  - The stroke uses it in place of its hand-written copy of the same handler.
- **F2: history holds every step it moves.**
  - `step_history` calls `move` through `_moved`. There, an `Exception` is logged, seals the
    ledger, marks the document unsafe, and comes back as LOST with `{"raised": <type>}`. Any
    other raise seals, marks unsafe and re-raises.
  - The region capture writes through `verification.write` (formerly `_write`, now the one home
    of the best-effort transfer write), so an `IO_ERROR` leaves `pixels: null` on a receipt
    whose undos ran. The composite read and a failed undo still fail the op.
- **F6:** `history.STOPPED` maps each stop to its receipt value:
  - FOREIGN `not_the_bridges_step`, REVERSED `unconfirmed`, LOST `document_unsafe`;
  - `krita_history_step.json`'s `stopped` enum gains the value (with `amend_schemas.py`);
  - `history_receipt`'s text names the document unsafe and says to reopen it.
- **F5:**
  - The stroke bounds (`MAX_POINTS`, `MIN_SIZE_PX`, `MAX_SIZE_PX`) are pinned to the schema and
    to `LIMITS["stroke_points"]`.
  - The probe's `LABEL` and `BLEND_LABEL` are pinned to `history.LABELS`.
  - The adapter imports `SRGB_PROFILE`, `COLOR_MODEL` and `DEPTH` from `bridge_core.documents`.
  - `verification.check_mask_size` is the one home of the allowed-mask/canvas-size rule
    (`allowed_rows` and `protection.protect`).
  - `verification.refuse_reach(tree, effects, layer_id, carried)` is the one home of the reach
    refusal, each caller's message kept word for word.
- **F7:** `probe/opening._harness_export` retries one `BUSY` with a fresh request id; a second
  BUSY is returned as it is.
- **F9:** `undo_limit()` falls back to `UNDO_LIMIT_DEFAULT = 200` (was 30) when kritarc sets no
  limit or an unreadable one.
- **F4:** the probe's `_tall_tip` paints the tall preset on its own 480 × 480 working copy. It
  paints three strokes (horizontal, vertical, diagonal) at 60 px with `verify: "full"`, each on
  a fresh layer, and reports a MEASURED line: each stroke's reach past the path's box against R's
  margin.
- **Amendments:**
  - **`_blend`'s guard stays seal-only;** the unsafe mark for a non-`Exception` raise comes from
    the enclosing guard. An ordinary `Exception` from `set_blend` is rolled back and confirmed,
    and marking it unsafe would contradict invariant 5's "confirmed, or unsafe". Amended at plan
    time, with the owner.
  - **An `Exception` escaping `move` is treated as LOST** (unsafe, then `document_unsafe` or the
    existing non-retryable LOST refusal). Krita may have moved, and nothing confirmed it. Plan
    time, with the owner.
  - **F5(c) also pins `probe/updates.py` `BLEND_LABEL`,** the same copy as `LABEL`. Plan time.
  - **F9 measures what Krita applies, not its default,** as decided above.
  - **The stroke's `BaseException` handler moved into `history.unconfirmed`,** so the guard has
    one home. The session's own finding.
- **Measured** (Krita 5.3.4.1, build `bd6e8d0`, on macOS, Apple Silicon):
  - **F4, the image tip's extent:** the 7 × 32 tip at 60 px reached 31 px past the path
    horizontally and vertically, and 26 px diagonally (0.52 and 0.43 × size). All three stayed
    inside R's 44.4 px margin.
    - Krita sizes an image tip by its longer side, so the tip fits a size × size square and
      `EXTENT[IMAGE] = √2⁄2` holds.
    - The two assumptions for `ARCHITECTURE.md`:
      - (a) the pixel engine displaces dabs by scatter alone. It is held by session 9's ~50
        stock presets and by the ring, which caught one scatter underestimate.
      - (b) an image tip fits a size × size square. It was measured here on the most
        non-square stock tip.
  - **F9, the undo stack:**
    - 210 layer creations on a harness working copy;
    - `krita_document_inspect` allowed 200 undos, so `undo_limit()` read 200;
    - Krita's own Undo emptied after exactly 200 presses, so Krita keeps exactly the limit the
      ledger reads;
    - `KisConfig::undoStackLimit` defaults to 200 (`libs/ui/kis_config.cc:192-195` at
      `bd6e8d0`, the running build);
    - the measuring machine's kritarc sets the same value.
  - **`probe` on 0.9.0, before the plugin changed:** 95 PASS, 0 FAIL, 33 MEASURED in 76.9 s, the
    F4 line included.
  - **`probe` on 0.10.0:**
    - 95 PASS, 0 FAIL, 33 MEASURED in 74.3 s;
    - H4 p50 4.8 ms, p95 6.7 ms;
    - create and close mean 705 ms;
    - N-01 p95 0.10 s of 1.5 s, N-09 p95 0.28 s of 3 s;
    - `transfer/` and `harness/` empty after the run, `plugin.log` clean;
    - three "pixels were taken" notes, the same three as the run on 0.9.0: two from the
      retried stroke and one in the changes checks.
  - **A live BUSY** was not forced; the retry is held by its unit test.
- **Checked by hand:** Krita was quit and relaunched once, with the owner's approval, at 0 open
  and 0 unsaved documents. `doctor` steps 1–5 PASS; step 6 is the owner's roots, as before.
- **Falsified** (each broken once; each failed at its own test, and was restored byte for byte):
  - **F1:** the guard replaced by `if True:` → the three interrupt cases and the rollback
    interrupt failed.
  - **F2:**
    - `_moved`'s `Exception` branch without the unsafe mark → both raise tests failed;
    - its `BaseException` branch without it → the interrupt test failed;
    - `verification.write` not catching `BridgeError` → the capture test failed.
  - **F6:**
    - LOST mapped to `unconfirmed` → the LOST test failed;
    - the schema enum without `document_unsafe` → the server receipt test failed;
    - the receipt text branch disabled → the same test failed on its text.
  - **F5:** `MAX_POINTS` 4095, `MAX_SIZE_PX` 999, and each probe label changed → each parity
    test failed.
  - **F7:** the retry disabled → the two BUSY cases failed.
- **Numbers:**
  - `verify`: 6 stages, all PASS;
  - 490 server tests passed (+4), 0 skipped;
  - 567 plugin-core tests passed (+9), 0 skipped;
  - `probe`: 95 PASS, 0 FAIL, 33 MEASURED (+1), 74.3 s;
  - 17 registered tools; 19 schema files; instructions 3,175 characters.
- **Review (`/code-review high`), 7 findings, all fixed.**
  - **A raise before Krita was asked to move made the document unsafe.** `move` now tells the
    two apart:
    - a raise in its pre-check propagates, and history answers REVERSED: the document is as it
      was, retryable as the first step, `stopped: "unconfirmed"` after it;
    - once Krita is asked, an `Exception` is LOST, and anything else marks it lost and
      re-raises.

    History's own `_moved` wrapper went.
  - **History's capture read could still fail an op whose steps ran.** `_capture` makes the read
    best-effort too; `pixels` is null when it raises.
  - **A raised step's messages said it "could not be put back",** though no reversal was tried.
    `_refuse` names the raise, and the `document_unsafe` text says nothing confirmed where the
    step left Krita.
  - **The guard marked an update that writes nothing unsafe** (only `active`, or every value
    unchanged). `unconfirmed(handle, changing)` arms only when there are changes.
  - **The seal-and-unsafe pair was written three times.** It is now `Handle.lost()`, used by the
    guard and by `move`.
  - **The two LOST sources left the ledger differently;** `move`'s LOST now seals as well.
  - **`_tall_tip`'s local `paths` shadowed the module;** it is `lines`.
  - **Falsified** (each broken once, failed at its own test, restored):
    - a pre-check raise mapped to LOST → both pre-check tests failed;
    - each raise message's wording → its test failed;
    - LOST without the seal → the LOST test failed;
    - the capture read not caught → its test failed;
    - the guard armed regardless → the write-nothing test failed.
  - **Measured:** `probe` 95 PASS, 0 FAIL, 33 MEASURED in 73.1 s on the reviewed build, after one
    more Krita restart with the owner's approval (0 open, 0 unsaved). The F4 line is unchanged;
    `transfer/` and `harness/` were empty after the run, and `plugin.log` was clean.
  - **Numbers after the review:**
    - `verify`: 6 stages, all PASS;
    - 490 server tests passed, 0 skipped;
    - 571 plugin-core tests passed (+4), 0 skipped;
    - `probe`: 95 PASS, 0 FAIL, 33 MEASURED, 73.1 s.

---

## 11: preview_render

**Read:** `SPEC.md` §1 (decisions 6, 31); `PDD.md` Part 1 (pillar 4), Part 4
(`krita_preview_render`), Part 5 (N-02); `REVIEW-2026-10-24.md` F5.

- **Amended by review 6 (2026-10-24), F5:** at most 300 characters net added to the
  instructions.
- **Amended by the owner in session 9 (2026-10-25), F10:** the `as_opened` baseline is written
  lazily, for the first `krita_preview_render` that needs it, rather than at every open, and
  still shows the document as it was opened (the working copy's file, which no save overwrites,
  holds that state). Session 9 measured an 8192 × 8192 working-copy open at 4.7–5.2 s with a
  268 MB baseline on disk.
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
  - `CHANGELOG.md`: 0.11.0 (0.9.0 before 6a, 0.10.0 before review 10 inserted 10a).
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

**Done (2026-10-28, 0.11.0).**
- **Decided with the owner at the start:**
  - **`integer_zoom` magnifies after.** The cell is rendered at the recipe's scale with the
    filter, then enlarged z times by pixel replication; the transform includes z, and 1 changes
    nothing. The owner left the reading to the session: replication adds no values, so nothing
    resampled is resampled, and painted art is filtered as the game draws it.
  - **Inline:** each sheet that fits goes inline at full size, in recipe order; the rest are
    path-only, named in the text line. No preview is ever returned scaled down.
  - **Tints** apply to the whole cell (art over its background), alpha kept.
  - **N-02 is gated twice:** the first render, which reads the baseline from the file, under
    2.0 s on its own, and the p95 of 20 renders after it under 2.0 s.
- **The lazy baseline.**
  - The open mints `baseline_id` and writes nothing; `resolve_open` and the open's transfer file
    went.
  - The server sends `read_baseline: true` only when it holds no `baselines/<id>.npy`. The
    plugin then checks the working copy's file still hashes to `source_sha256`, else
    `SOURCE_HASH_MISMATCH`. It opens the file again without a view (`port.open`, batch mode),
    reads its composite and closes it in the same job, through `registry.discard`: a file Krita
    keeps open is registered owned, read-only and unsafe, and the op fails naming it.
  - The server adopts the transfer file as the `.npy`, as the open did before, and crops it for
    every later render. Close and the start sweep still remove it.
- **`krita_preview_render`.**
  - Plugin op `preview.read` (`bridge_core/previews.py`): a read, with no guard or lease. Per
    source it returns the crop, the baseline when asked, and the overlays' masks (the selection
    via `selection_rect`, the allowed mask sliced from the handle), and it echoes the tool's
    arguments. `pixels._read` became the shared `read_rects`.
  - `sheets.py` (pure) holds the scale, placement, grid and composition. The tool's module is
    `tools/preview.py`, and `preview.read` is in `RECEIPTS`.
  - Order in a cell:
    1. one resample from the native crop;
    2. composite over the background (a transparent cell takes the art's bytes);
    3. tint;
    4. greyscale;
    5. a snapshot for the clean sheet;
    6. the overlays' 1-game-pixel outlines (selection magenta, allowed mask cyan);
    7. the zoom.
  - Files: `<op>-<n>.png`, `<op>-<n>.clean.png` and `<op>.json` (written last) in
    `captures/<day>/`, found before they are made, so `krita_operation_get` rebuilds the receipt.
  - The instructions gained one line (+176 characters).
- **Amendments:**
  - **One sheet per recipe; the contract's `images` and `clean_images` became `sheets[]`,** each
    with `image`, `clean_image` (null when no overlay was drawn), `inline`, the grid's `columns`
    and `rows`, and its own `recipe_sha256`. `static_only` and `source_pixels_changed` stay, as
    constants. Plan time, the session's.
  - **No text is drawn into a sheet;** the receipt's columns and rows describe the grid. Plan
    time, the session's.
  - **"Fit" keeps the aspect:** an exact-size recipe scales the crop to fit its box, and the cell
    is the box. An anchor that pushes the image out of the box is refused, never clipped.
  - **A world-unit cell is the union of the anchored images;** each anchor lands within half a
    pixel of one shared whole-pixel point, in [C − 0.5, C + 0.5).
  - **Bounds:** 8 recipes, 8 sources, 4 backgrounds, 4 tints, `integer_zoom` up to 16, a sheet at
    most 4096 px on its long edge, and at most 2 × 8192² pixels read per call (a whole 8k master
    beside its baseline). Plan time, the session's.
  - **Overlays are outlined on both columns of a source,** at game size; a mask with nothing to
    outline draws nothing.
  - **`FakePort.open` no longer brings its document to the front;** `show` does (K6), so the
    tests see the reopen leave the owner's view alone.
- **Measured** (Krita 5.3.4.1, build `bd6e8d0`, macOS, Apple Silicon):
  - **A second open of an open file** works in Krita 5.3.4.1. It opened without a view, read,
    and closed, leaving nothing in `documents()`. The lazy baseline equals the composite as
    opened, byte for byte, for PNG, ORA and KRA in both modes.
  - **N-02:**
    - the first render, with the file reopened for the baseline, 0.74 s;
    - 20 renders after it: p95 0.32 s, mean 0.31 s, max 0.32 s;
    - sheets of 2974 × 1491 and 1824 × 916, both inline.
  - **Opens without the baseline write:** the 8192² N-09 master in 0.5 s (4.7–5.2 s with its
    268 MB baseline before), the 2000² N-01 master in 0.2 s, 0 MB written to `baselines/`.
  - **`probe` on 0.11.0:**
    - 101 PASS, 0 FAIL, 33 MEASURED in 79.0 s;
    - H4 p95 5.6 ms; create and close mean 695 ms;
    - N-01 p95 0.10 s, N-09 p95 0.24 s; the F4 line unchanged;
    - `transfer/` and `harness/` empty, `plugin.log` clean;
    - the same three "pixels were taken" notes as before.
- **Checked by hand:**
  - Krita was not running at the start, and the session started it.
  - For the version bump it quit and relaunched it once, with the owner's approval, at 0 open
    and 0 unsaved documents.
  - `doctor` steps 1–5 PASS; step 6 is the owner's roots, as before.
  - An offline sheet, looked at by eye: the grid in order, and each outline whole on all four
    edges.
- **Falsified** (each broken once; each failed at its own test, and was restored from a copy):
  - **Sheets, 20 mutations:**
    - the scale formula, half-up rounding, the missing-units refusal;
    - the fit and the box overflow, the transform's zoom, the anchors' meeting;
    - the filter and the native pass-through, replication;
    - the row and column order, the tint and greyscale order, the whole-cell tint;
    - the clean sheet, the edge-only outline, the empty outline's clean sheet;
    - the sheet cap, the anchor range, the recipe hash.
  - **The tool, 14 mutations:**
    - the lazy read, the as-opened crop, the bridge's baseline match, the file hash;
    - each of the six rules before Krita;
    - `RECEIPTS`, the inline split, greyscale's sRGB check, the single document.
  - **The plugin op, 13 mutations:**
    - the crop, the reopen's close, the unclosable reopen, the failed reopen's close;
    - four source rules, the read bound, the mask slice, the cleanup part way;
    - the open writing no baseline, and the parity pin.
  - **Two checks first passed under their mutation and were fixed:**
    - the failed-reopen test set the composite failure before the current read, so the reopen
      was never reached; it now fails the reopen only;
    - the layer-baseline case was refused by the id mismatch first; it now uses the document's
      own id.
- **Numbers:**
  - `verify`: 6 stages, all PASS;
  - 523 server tests passed (+33), 0 skipped;
  - 586 plugin-core tests passed (+15), 0 skipped;
  - `probe`: 101 PASS (+6), 0 FAIL, 33 MEASURED, 79.0 s;
  - 18 registered tools (+1); 19 schema files; instructions 3,351 characters (+176 of 300).
- **Review (`/code-review high`), 10 findings, all fixed.**
  - **A baseline file that could not serve was never read again.** A mis-shaped or unreadable
    `.npy` failed every render as retryable, yet the file stayed, so each retry sent
    `read_baseline: false` and failed the same way. `_pixels` now removes it before failing, and
    the retry reads the baseline from the working copy's file again.
  - **`recipe_sha256` left out what scales a sheet.** It now covers:
    - the top-level `export_pixels_per_unit` and `master_to_export_scale`;
    - each source's crop, anchor, units and target, and whether it has a baseline.

    Which document, layer or baseline a source shows stays out.
  - **The read bound's refusal suggested a crop when only the baseline was too large.** A
    baseline is read over its whole canvas. When that alone is over the bound, the message now
    says to leave out `baseline_id`; the details split crop and baseline pixels.
  - **The clean sheet was built for every render;** it is now allocated only when an outline is
    drawn, and a cell is zoomed a second time only then.
  - **The artifact dict had two homes;** `imaging.artifact` builds it for captures and previews.
  - **A fresh render read its own PNGs back from disk;** `_write` returns the inline bytes it
    has, and only a rebuilt receipt reads them.
  - **The sheet-cell crop had four copies;** `probe.report.sheet_cell` serves the probe and the
    tool tests. `test_sheets` keeps its own, which crops an in-memory sheet.
  - **`anchor_px` was rounded to 4 decimals** beside exact transforms; both now report whole
    numbers as integers and the rest unrounded (`sheets._exact`).
  - **`previews.run` took an unused client.**
  - **`resolve_preview`'s failure branches had no tests.** They now cover a baseline file that is
    unreadable or mis-shaped, pixels already taken, and sheets another server made meanwhile.
  - **Falsified** (each broken once, failed at its own test, restored from a copy):
    - the bad file's removal, the load-error catch;
    - the hash's units, sources and identity;
    - the exact anchor, the clean sheet only with outlines;
    - the baseline-too-large message;
    - the taken pixels' retry, the shared server's sheets, the inline bytes.

    The shared-server test first stubbed `find` so the real lookup ran on its first call and
    never reached the branch; it now finds nothing on the first call.
  - **Measured:** `probe` 101 PASS, 0 FAIL, 33 MEASURED in 79.3 s on the reviewed build, after one
    more Krita restart with the owner's approval (0 open, 0 unsaved).
    - N-02: first render 0.74 s, p95 0.31 s;
    - `transfer/` and `harness/` empty, `plugin.log` clean.
  - **Numbers after the review:**
    - `verify`: 6 stages, all PASS;
    - 528 server tests passed (+5), 0 skipped;
    - 587 plugin-core tests passed (+1), 0 skipped;
    - `probe`: 101 PASS, 0 FAIL, 33 MEASURED, 79.3 s.

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
  answers within 1 s after the save, and no job is lost or duplicated. Reach the 20 s with the
  fewest layers that do it, measured first, and record Krita's memory; never dense 8k layers.
- **Docs.**
  - `CHANGELOG.md`: 0.12.0 (0.10.0 before 6a, 0.11.0 before review 10 inserted 10a).
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
  Amended by review 6 (F5): sessions 7–11 each added at most 300 characters net, so this is a
  finalisation, not a cut; the owner decides what goes if the cap still binds.
- **F-24** (a floating message while a job runs), if time allows (decision 31).
- **N-04 in the harness:** nothing is written outside the roots, the data directory, and Krita's
  own temp and autosave files.
- **Docs.**
  - `CHANGELOG.md`: 0.13.0 (0.11.0 before 6a, 0.12.0 before review 10 inserted 10a).
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
  - `CHANGELOG.md`: 0.14.0 (0.12.0 before 6a, 0.13.0 before review 10 inserted 10a).
  - The release commit carries the last done-note.
  - Then a separate `docs: close round 1` commit deletes `docs/spec/` and rewrites the handoff
    from the between-rounds template, naming the release commit.

**Gates:**
- `uv run scripts/verify.py`, and `probe` green once more, its counts going into the baseline.
- Hygiene clean across the whole history.

**Watch for:**
- **The docs describe what was built, not the plan.** Where they differ, the done-notes win.
