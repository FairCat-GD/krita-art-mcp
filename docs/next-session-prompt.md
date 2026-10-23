Read docs/spec/SPEC.md (§1 decisions 11, 19, 21–24, 30; §3; §5 invariants 6, 7, 10–12),
docs/spec/PDD.md (Part 3 *First-run experience*; Part 4 *Conventions*: envelope, errors, long
calls, `krita_server_info` and *Server instructions*; Part 6 *Files*; Part 8 *Bridge protocol*,
*Plugin internals*, K1, K14, K19, K40, K41, K48, C1, C3, C4), CLAUDE.md, then this file. Then do
Session 2 of docs/spec/SESSIONS.md: bridge alive. Session 2 has six parts:
- **the plugin:** the `.desktop` file, the extension, the loopback `ThreadingHTTPServer`, the token
  and `bridge.json`, auth, shutdown, and the log;
- **jobs:** the main-thread queue woken by a queued signal, the re-entry guard, the four
  endpoints, and the cached health answer;
- **the server:** the bridge client, the envelope and the error mapping (the envelope's shared
  shape amended in all 19 schemas), `krita_server_info` at `api_version` `"0.2.0"`, and the
  instructions started;
- **the CLI:** `install-plugin` and `doctor`;
- **the probe:** the plugin hash first, health, `krita_server_info` over stdio, H4 idle, and the
  runtime probes;
- **the owner's step:** restart, enable, restart. Every restart is the owner's until the bridge
  answers.

Release 0.2.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 and 1 are done; 2–15 remain, and 6, 10 and 13 are
  architecture reviews.
- **Session 1 is committed locally, not pushed.** Its review fixes, if any, follow it as a
  `review:` commit. `origin` is the private GitHub repository `FairCat-GD/krita-art-mcp`.
  `origin/main` holds everything through `review: restarts before the bridge go to the owner, and
  6 smaller`. List `origin/main..HEAD` before any push.
- **What Session 1 left that Session 2 builds on:**
  - **The package.**
    - `src/krita_art_mcp/__init__.py` holds `__version__`, from the package metadata.
    - `cli.py` uses argparse, with `serve` and `--version`.
    - `server.py`: `build_server()` returns `MCPServer("krita-art", version=__version__)`;
      `serve()` runs it over stdio. It has no tools and no instructions.
  - **The schemas.** `src/krita_art_mcp/schemas/krita_<tool>.json` holds 19 full tool entries
    (`name`, `description`, `inputSchema`, `outputSchema`, `annotations`, `example`), copied
    unamended. `schemas.tool_names()` and `schemas.load(name)` read them.
  - **The plugin.**
    - `plugin/krita_art_mcp_bridge/bridge_core/__init__.py` holds only
      `PLUGIN_VERSION = "0.1.0"`.
    - `krita_adapter/__init__.py` is empty.
    - There is no package `__init__.py` and no `.desktop` file yet.
  - **Tests.**
    - `tests/` (3.12): schemas and examples, C1, the version and stdio checks, and hygiene.
    - `tests/plugin/` (3.10): the version shape, and the banned-call and import scans.
    - `test_c1_error_passthrough.py` shows how to hand-build an `MCPServer` tool.
  - **`scripts/verify.py`**, in six stages:
    - `format` and `lint`;
    - `types`: three mypy runs. Strict 3.12 over `src scripts tests`; then 3.10 over
      `-p bridge_core -p krita_adapter`; then 3.10 over `tests/plugin`;
    - `tests`;
    - `plugin-tests`: an isolated uv environment on 3.10 holding only pytest at `uv.lock`'s
      version;
    - `hygiene`.
  - **`scripts/hygiene.py`** checks against the term hashes in `scripts/hygiene_terms.txt`.
- **What the spec said that turned out wrong or harder:**
  - **C1 holds.** An `is_error` `CallToolResult` with `structured_content` reaches the client
    unchanged. The server validates only against a pydantic `output_model`, and the client skips
    error results. So errors are returned that way.
  - **Hand-built tools drop their arguments.**
    - A tool that publishes the contract's own JSON Schemas must be built by hand
      (`mcp.server.mcpserver.tools.Tool` with `FuncMetadata(output_schema=…)`).
    - Its pydantic `arg_model` then filters the arguments. An empty model passes none through,
      even with `extra="allow"` (measured).
    - So Session 2 designs how the exact arguments reach a tool and are validated against its
      schema (invariant 8).
  - **mypy takes packages or files in one run, never both,** hence the three runs in `types`.
- **Decisions written down nowhere else:**
  - **To falsify the hygiene stage,** add a throwaway word in an untracked file and its hash to
    `scripts/hygiene_terms.txt`, watch the stage fail, then remove both. Hygiene also checks
    untracked files, so this works before staging.
  - **A version bump touches three places:** `pyproject.toml`, `bridge_core.PLUGIN_VERSION` (a
    test holds them equal), and `uv.lock`, which `uv lock` refreshes. Then the `CHANGELOG.md`
    entry.
  - **`gh` is authenticated** for the owner's GitHub account. The repository stays private until
    the owner publishes it.
  - **Krita on this Mac.**
    - Krita 5.3.4 is at `/Applications/krita.app`, with Python 3.13 and PyQt5 5.15.11 bundled.
    - `~/Library/Application Support/Krita/pykrita/` exists and is empty.
    - `~/Library/Preferences/kritarc` has no `[python]` section.
- **Baseline** (Session 1's done-note; ARCHITECTURE's table comes in Session 15):
  - `verify`: 6 stages, all PASS;
  - 49 server tests passed, 0 skipped;
  - 5 plugin-core tests passed, 0 skipped.
- **Not done:** the `[0.1.0]` link reference in `CHANGELOG.md`, agreed with the owner. It needs
  Session 1's commit sha, so it lands in Session 1's review commit.

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
  - Tests and mypy see `bridge_core` and `krita_adapter` as top-level packages, through
    `plugin/krita_art_mcp_bridge` on `pythonpath` and `mypy_path`.
  - Keep `bridge_core`'s own imports relative, and keep tests importing `bridge_core`, never the
    package, whose `__init__.py` will import Krita.
  - Once `__init__.py` and an adapter that imports `bridge_core` land, `-p krita_adapter` may need
    reworking. A relative `..bridge_core` reaches beyond its top level there.
- **No `tests/conftest.py`.** The 3.10 run loads every conftest from the rootdir down, and its
  environment holds only pytest.
- **A stdio test waits for each reply, and closes stdin in a `finally`.**
  - The server can exit at end of input before answering queued requests.
  - With the subprocess's own context manager, a failed assertion hung the run for 10 minutes.
- **Session 2's own traps** are in its block:
  - a plugin that fails to load says little;
  - the bindings never release the GIL;
  - a polling `QTimer` is wrong;
  - restarts follow decision 21;
  - Dock-launched apps lack `PATH`.
- **Comments state the present, briefly.** No session ids, no "used to", no review stories, no
  paragraphs.
- **Every push needs its own approval.** List `origin/main..HEAD` first, because parallel
  sessions may share this checkout.
