# krita-art-mcp

An MCP server and a Krita plugin that let AI agents paint in Krita. An agent can inspect a
painting, protect accepted work, paint with Krita's own brush engine, check the result at game
size, and undo or keep it. It is for painted (non-pixel) 2D game art, run by one developer on
macOS (Apple Silicon) with Krita 5.3.x.

Machine identifiers keep their spelling even if the product is renamed, because configuration and
data live under them:
- package and CLI `krita-art-mcp`, imported as `krita_art_mcp`;
- plugin module `krita_art_mcp_bridge`, with kritarc key `enable_krita_art_mcp_bridge`;
- MCP server `krita-art`, with tools `krita_*`;
- `~/Library/Application Support/krita-art-mcp/`, `KRITA_ART_MCP_DATA_DIR` and `bridge.json`.

**`docs/ARCHITECTURE.md` is the system as built, and `docs/USER-GUIDE.md` is its behaviour from the
user's side.** Read the architecture's overview, invariants and baseline before changing code, then
the sections your work touches. Every session keeps both true, in the commit that changes what they
describe. `docs/DEVELOPMENT-WORKFLOW.md` is the session-based workflow this repo follows.
`docs/BACKLOG.md` lists what has been named but not planned.

## Working protocol

Every session runs the cycle in `docs/DEVELOPMENT-WORKFLOW.md`:
1. entry gate;
2. read order;
3. a plan agreed in plan mode;
4. the verify gate;
5. docs kept true;
6. the changelog;
7. a done-note in its `SESSIONS.md` block;
8. the handoff prompt for the next session;
9. a local commit, with `verify` run on its drafted message as the last act before it;
10. the owner's `/code-review high`, then a review-fixes commit;
11. the next session's prompt, printed as the last message.

One session per chat. A push or tag needs explicit approval, each time.

**Scope lives in `docs/spec/SESSIONS.md`**, one block per session, in order, and in the round's
spec files. Each request gets one `FEATURE-*.md`, holding the request verbatim plus the decisions
resolved at intake; it is read-only and not re-litigated.

`docs/spec/` holds only the round in progress. When a round closes, its files are deleted (git
history keeps them), and anything still open moves to `docs/BACKLOG.md`. No round is in progress
until an intake opens one. `docs/BACKLOG.md`'s header says where round 1's files are.

**State lives in `docs/next-session-prompt.md`**, rewritten by every session as its last act.

**Read order:**
1. what the session block's **Read** line names;
2. this file;
3. `docs/ARCHITECTURE.md`'s overview, invariants and baseline;
4. from `SESSIONS.md`, its header, the session's block and the previous block's done-note;
5. the prompt.

The Read line is a floor: read further where the code leads.

**Rules:**

1. `uv run scripts/verify.py` (format check, lint, typecheck, tests, plugin tests on 3.10,
   hygiene) must be green before you commit. The last run before each commit takes the drafted
   message (see *Git*).
   - Run the live harness (`uv run krita-art-mcp probe`) whenever your change could affect what
     it covers.
   - Expected results are in `docs/ARCHITECTURE.md`'s baseline table.
2. Falsify each new check once before trusting it: break the assertion, watch it fail at its own
   step, restore it. Checks that already existed are not falsified again.
3. User-visible changes get a line in `CHANGELOG.md`. Version is `major.minor.fix` in
   `pyproject.toml`, surfaced in `krita-art-mcp --version`, in the MCP `serverInfo`, and in
   `krita_server_info`.
4. If a decision is genuinely underdetermined, stop and ask rather than guessing — a guess
   becomes load-bearing for everything after it.
5. Comments state the present: why the code is shaped this way now. No session ids, no "until
   v0.x", no review stories — git history keeps those.
   - Keep comments short: one line where possible, and only where the why is not obvious from the
     code.
   - No paragraphs, and no docstrings that restate the signature.

## Invariants — these are rules, not preferences

The why for each is in `docs/ARCHITECTURE.md`, *The invariants*.

1. **No raw pixel writes, and no tool runs code.** No tool, harness operation or fixture writes
   raw pixels into a layer. *Enforced by* the plugin source scan, which bans `setPixelData`,
   `Filter.apply`, `saveAs`, `exec` and `eval`. Its one exception is
   `krita_adapter.selections._from_mask`, which loads a mask into a `Selection()` it builds (K11)
   and writes no layer; an AST test holds that site and its receiver. `setSelection` is held to
   four sites alike: the global selection's two commits, the harness's selection mask, and
   `krita_adapter.documents.create_mask`, on a transparency mask it just made, before attaching it
   (decision 14).
2. **Accepted sources are never opened for writing, and no save overwrites a file.** *Enforced
   by* working copies with hash checks, and `FILE_EXISTS`.
3. **Every path an agent names resolves (realpath) inside an allowed root,** checked on both the
   server and the plugin. *Enforced by* unit tests and the harness.
4. **Protection only tightens.** *Enforced by* `protection_set` tests.
5. **Every mutation is verified inside its own main-thread job.**
   - A violation is rolled back by native undo, and the rollback is confirmed; if it can't be,
     the document is marked unsafe.
   - A rollback undoes only the steps its operation pushed.
   - *Enforced by* plugin-core tests and the harness leak tests.
6. **Every libkis call runs on Krita's main thread, one job at a time.** `waitForDone()` comes
   before any read after a paint, undo, redo or save. *Enforced by* the adapter's thread check
   and the re-entry guard.
7. **The plugin's layers stay apart.**
   - Every `krita` and PyQt import lives in `krita_adapter`.
   - `bridge_core` is pure, and valid under Python 3.10.
   - The plugin uses only the standard library, PyQt and `krita`.
   - *Enforced by* the import scan and the 3.10 test stage.
8. **Inputs are exact; results are typed and small.**
   - Inputs reject unknown fields and are never clamped, normalised or substituted.
   - Every result, errors included, validates against its output schema.
   - Errors are returned, never raised.
   - Every message stays under 6 MB.
   - *Enforced by* schema and size tests.
9. **Retries are safe.** The journal line is written before dispatch, a retried `request_id`
   never repeats work (within a Krita session; across a Krita restart, for 7 days), and an
   uncertain call is never re-sent. *Enforced by* journal and dedup tests.
10. **The capability matrix is true at every release,** and a tool is registered only once it is
    built. *Enforced by* the registered-tools test and the harness.
11. **No stale plugin.** `probe` and `doctor` refuse a plugin whose source hash differs from the
    repo's, and `serve` refuses a plugin of another version.
12. **The bridge is closed to everyone but the owner.**
    - It listens on 127.0.0.1 only and requires the token (constant-time compare, `Host` check,
      64 MB body limit).
    - The token is never logged, and `bridge.json` is 0600.
    - *Enforced by* plugin-core tests.
13. **Harnesses leave the owner's things alone.**
    - They never touch the owner's documents, files, `kritarc` or `config.json`.
    - They work only in `<data dir>/harness/`, and restore the brush state afterwards.
    - *Enforced by* the `harness.*` folder gate on every op that takes a document.
14. **Nothing private enters the repository.** *Enforced by* the hygiene stage (see below).

## `mcp` is pinned to 2.3.x: FastMCP is `MCPServer`, and errors are returned

- `mcp>=2.3,<2.4`. Import it with `from mcp.server.mcpserver import MCPServer, Image`; importing
  `mcp.server.fastmcp` raises.
- A raised exception reaches the client only as "Error executing tool X". Return
  `CallToolResult(is_error=True, …)` with the envelope instead.
- `Image` takes no `_meta`. Build `ImageContent` directly when the image needs
  `{"codex/imageDetail": "original"}`.
- Moving past 2.3 is a decision, never a routine bump.

## The plugin runs inside Krita: Python 3.10 syntax, the standard library, one thread

- **The runtime.** Krita 5.3.4 on macOS runs the plugin on its bundled Python 3.13 with PyQt5
  5.15.11. The code still targets 3.10, so other Krita builds can load it, and `verify` tests
  `bridge_core` on 3.10.
- **Imports.** PyQt goes through the shim (`try: PyQt6 … except ImportError: PyQt5 …`). Avoid Qt
  enums; the one the plugin needs, `EXCLUDE_USER_INPUT`, is resolved in the shim. Use
  `Krita.getAppDataLocation()`, not `QStandardPaths`.
- **The main thread.** The `krita` bindings never release the GIL, so the HTTP thread is silent
  during any long libkis call. The server owns the wait budget.
- **Signals.** Krita's embedded Python leaves SIGPIPE at its default, so a write to a socket whose
  client has gone kills Krita. Every bridge connection sets `SO_NOSIGPIPE`.
- **Restarts.** A changed plugin loads only after a Krita restart: run `install-plugin`, then
  restart. A session may restart Krita itself only when the bridge reports no unsaved
  documents; with no bridge answering, or any unsaved document, it asks the owner. The harness
  never quits Krita.

## This repository is public: nothing private goes in

Its whole history will be published, so every file, test, fixture, done-note, handoff and commit
message follows these rules:
- **No personal names, game names or agent personas.** Write "the owner", "the first game" and
  "the Codex agent". The one agreed exception is the owner's name on README's copyright line.
- **No home-directory paths.** Write `~`.
- **No AI attribution:** no co-author trailers, no lines saying a tool generated the work, no AI
  session links, no AI credited as author, co-author or addressee. Naming the tools is fine:
  Claude Code and Codex as the MCP clients the server supports, this file, and the workflow's
  review command.
- **Fixtures are fictional.**
- **Done-notes and handoffs never name the owner's own data:** their documents, folders, presets
  or roots. Record what was measured, not whose it was.
- **Unsure whether something is public? Ask the owner before writing it;** a word they call
  private goes on the term list.

The owner's own name, email and handle are public: they are on every commit's author line and on
GitHub. The hygiene stage of `verify` checks every file, path and commit message, the drafted one
included, against the term list in `~/.config/hygiene/terms.txt`, outside the repository (one
word per line, `#` for a comment; a missing file fails, an empty one passes), and every commit
message for AI attribution. A hit names the file and line, or the commit and message line, never the term.

## Commands

| Command | Does |
|---|---|
| `uv run scripts/verify.py [--message <draft>]` | The gate, in six stages: `format`, `lint`, `types`, `tests` (3.12), `plugin-tests` (3.10, pytest only) and `hygiene`. It then prints a summary and exits 1 if any stage failed. `--message` gives `hygiene` the drafted commit message to check too. |
| `uv run scripts/verify.py <stage>…` | Runs only the named stages; `--message` needs `hygiene` among them. |
| `uv run scripts/amend_schemas.py [--check]` | Writes the shapes the tool schemas share (the envelope, `guard`, `source`, the completed rule's copy of `data`, inspect's `layers`, the sample's and the fill's `color`, the fill's selection shapes, the paint receipts' `verification`) and formats the files. A tool session edits its schema's input, `data` and example, then runs it. `--check` changes nothing; a test holds the files to it. |
| `uv run krita-art-mcp --version` | Prints the package version. |
| `uv run krita-art-mcp serve` | Runs the MCP server `krita-art` over stdio; the clients start it this way. |
| `uv run krita-art-mcp install-plugin [--krita-data-dir DIR]` | Copies the plugin into Krita's `pykrita/` (default `~/Library/Application Support/Krita`) and prints the steps left. It never edits `kritarc`. |
| `uv run krita-art-mcp roots add <dir>` / `list` / `remove <dir>` | Edits `config.json`: the folders an agent may name. `add` refuses `/`, the home folder, and any folder equal to, holding or inside a data folder; such a root already in `config.json` makes both sides refuse every path until it is removed. Only the owner runs it; no session or harness does. |
| `uv run krita-art-mcp doctor` | Checks the setup in six ordered steps and names the first one that fails, with its fix; the sixth needs a root. Then it prints Krita's open and unsaved document counts, which the restart rule reads. |
| `uv run krita-art-mcp probe` | The live harness: plugin hash first, then health, `krita_server_info` over stdio, H4 idle, the runtime facts, then its own documents and fixture files, then a leftover check before its final sweeps. Prints PASS, FAIL or MEASURED per check, then the counts, the wall time and Krita's open documents; exits 1 on any FAIL. |

**What only the live harness can see.** The unit tests never touch Krita. `uv run krita-art-mcp
probe` drives a real `serve` over stdio against the owner's running Krita 5.3.x. It needs the
plugin installed, enabled and current.

**How it treats the owner's data.** The harness works only in `<data dir>/harness/`, sweeps
leftovers at start, closes what it opened, and restores the brush state. No test or harness
touches the owner's documents or `config.json`.

## Git

- Commit locally; a push or tag needs explicit approval, each time.
  - Before any push, list `git log origin/main..HEAD`; parallel sessions may share this checkout.
  - `origin` is the private GitHub repository; it stays private until the owner publishes it.
- Stage explicit paths, never `git add -A`. Never undo with `git checkout <path>`.
- **Last before each commit,** after the done-note and the handoff: write the message fresh into
  `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `uv run scripts/verify.py --message` with it,
  commit with `git commit -F` from it, then delete it. The message is checked before it exists
  in history.
  - The review commit goes the same way. A push note puts the last commit's message
    (`git log -1 --format=%B`) into the draft, runs only
    `uv run scripts/verify.py hygiene --message` with it, then amends: the note changes the
    handoff alone, which only hygiene reads.
  - A message never quotes an attribution form, even to describe the rule; describe it in words.
- **Subjects.** Typed (`feat:`, `fix:`, `refactor:`, `docs:`, `review:`), in plain words, at most
  72 characters, ending `(x.y.z)` when the commit cuts a version.
- **Bodies.** Short, wrapped at 72: what changed and why.
- **Review commits.** `review: <main finding>, and <n> smaller`.
- **Attribution and identity.** No trailers. Commits use the owner's global git identity.

## Do not

- Write raw pixels, call `setPixelData` (outside `_from_mask`), `Filter.apply` or `saveAs`, call
  `setSelection` outside its four sites or on an attached mask, or add anything that runs code.
- Call libkis off Krita's main thread or outside a job, or read after a mutation without
  `waitForDone()`.
- Touch the owner's documents, files, `kritarc` or `config.json` from a test or harness, or
  restart Krita while a document has unsaved changes.
- Edit `docs/spec/` beyond what the workflow gives your session: your block's done-note and
  logged amendments; in a review session, its `REVIEW-<date>.md` and the amendments or inserted
  blocks the owner chose; in the round's last session, the close.
- Edit `docs/reference/`: the contract package is frozen.
- Loosen a schema to make an example pass, or relax a budget to make a benchmark pass.
- Upgrade a pinned dependency in passing, or rename a machine identifier.
- Put anything private in a file or a commit message.
- Finish with `uv run scripts/verify.py` red, or with user-visible changes missing from
  `CHANGELOG.md`.
