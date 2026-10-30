# krita-art-mcp — the round 1 contract

Read-only from the first line of Session 1. Session 0 derived it on 2026-10-23 from
`docs/spec/PDD.md` (v0.4, frozen) and the contract package in `docs/spec/reference/contract-package/`.
The PDD states intent and this file is the contract: where they differ, this file wins, and §7
lists every place they do. Where the package and the PDD differ, the PDD wins. "The owner" is the
person this project belongs to (the workflow's "user").

## 1. Resolved decisions (2026-10-23, at intake)

Decisions 1–3, 5–16 and 19–21 were answered by the owner at intake. Decisions 4, 17, 18 and 22–31
were proposed by the intake from the PDD and approved with the Session 0 plan. Decision 32 collects
what round 1 leaves out. None is re-litigated by an implementing session; a change is added beside
the decision as an **Amended <date> by the owner** note.

1. **Round 1 builds PDD Phase 1.** Its 19 tools, the Krita plugin, the CLI (`serve`,
   `install-plugin`, `roots`, `doctor`, `probe`) and the live harness. Phases 2–6 are later
   rounds, each with its own intake. The H1/H7 trial runs after the round closes and feeds the
   Phase 2 intake.
2. **Fifteen sessions** (`SESSIONS.md`): twelve build sessions releasing 0.1.0 to 0.12.0, and
   three architecture reviews (sessions 6, 10 and 13) after the milestones *observe*, *paint
   safely* and *every tool built*, placed at the owner's request.
   - A review reads the code cold against this file: layering, the invariants and how each is
     enforced, duplication and drift, debt, whether tests cover the invariants, harness health,
     and fit for Phases 2–6.
   - It writes `docs/spec/REVIEW-<date>.md`, findings only: no product code, no version, no
     CHANGELOG entry.
   - The owner picks which findings become scope, in that session's plan mode. Each becomes an
     amendment to a later block or an inserted fix session, which takes the next version (later
     versions shift, and the handoff says so).
3. **Krita 5.3.x only in round 1.** This amends the PDD's 2026-10-22 decision to support 5.3 and
   6.0 from day one. The plugin keeps the PyQt5/PyQt6 import shim and avoids Qt enums, so a later
   round can verify 6.x cheaply. N-05, H5 and 6.x verification go to the backlog.
4. **Stack, as PDD Part 8.**
   - Server: Python 3.12 (`.python-version`) via uv; `mcp>=2.3,<2.4`, Pillow 13.x, NumPy 2.x,
     `jsonschema` (Draft 2020-12); dev: pytest 9.x, ruff 0.17.x, mypy 2.x.
   - Plugin: Python 3.10 syntax; the standard library, PyQt and the `krita` module only.
   - Plugin-core tests run on CPython 3.10 (uv-managed). The shipped runtime is the Python inside
     Krita (3.13 in 5.3.4 on macOS); the live harness is the check in that runtime.
5. **Schemas.** Session 1 copies the 19 Phase 1 input and output schemas and their examples from
   `mvp.tools.json` / `tools.json`, unamended. Each tool's session amends its own schema and
   example to §3 and the PDD's Part 4 deviations.
   - Shared shapes (`guard` without `expected_revision`, `source` without `revision`, the result
     envelope) are amended once, across all 19 schemas, by the first session that serves a tool
     using them, with a test that every copy of a shared shape is identical.
   - Later-phase output fields are removed (`project_id`, `protection_id`, `active_edit_id`,
     `rollback_state`, inline paint previews); the envelope keeps `revision`, always `null`.
   - The server lists only tools that are built and tested.
6. **Budgets are gates.** N-01 and N-09 become harness benchmarks in session 9, N-02 in session 11,
   each failing over budget. A miss stops the session for the owner's call; no budget is relaxed
   quietly. N-03 (idle CPU) is checked by hand.
7. **Each build session is a release** (PDD Q4), with its CHANGELOG entry and version.
8. **`krita_document_close` stays** unless the harness reproduces a crash in 20 open/close cycles
   (Q5), measured in session 3.
9. **Working copies go to an explicit `working_dir`** per open (Q6).
10. **Capture defaults:** `max_px` 1600, background `checker` (Q10).
11. **Distribution.** The server runs as `uv run --project <repo> krita-art-mcp serve` (Q11); no
    PyPI package, no app bundle. `install-plugin` copies the plugin into Krita's `pykrita/`
    folder; updating is `install-plugin` again and a Krita restart. The owner enables the plugin
    once in Krita's Python Plugin Manager.
12. **The contract package** lives in `docs/spec/reference/contract-package/` (Q12), the starting
    point for every schema, never the contract.
13. **Inputs are scrubbed.** The PDD and the package are frozen as received except that private
    details are replaced by roles ("the owner", "the Codex agent", "the first game"), lines
    crediting or addressing an AI tool are removed, and the package's historical fixtures and
    checksum file are left out. The originals are not in the repository.
14. **This repository is public from its first commit.** No file or commit message holds a
    personal name, a game name, an agent persona, a home-directory path (write `~`), or AI
    attribution (co-author trailers, "generated with" lines, session links, an AI credited as
    author, co-author or addressee). Naming the tools themselves is fine: Claude Code and Codex
    as supported MCP clients, `CLAUDE.md`, and the workflow's mention of the review command. The
    hygiene stage of `verify` enforces the names and the trailers.
    **Amended 2026-10-24 by the owner, in session 7a:** the owner's own name, email and handle
    are public, on every commit's author line and on GitHub, so they are not private terms;
    files still write "the owner". The private terms live outside the repository, in
    `~/.config/hygiene/terms.txt`, one word per line; the repository holds neither them nor
    their hashes. The stage runs as the last act before each commit, the drafted message
    included, and its attribution patterns name the AI tools.
15. **Licence: GPL-3.0-or-later** for the whole repository (`LICENSE`, session 1). Code borrowed
    from MIT or CC0 projects keeps its attribution.
16. **Commits** use the owner's global git identity. Subjects are typed and plain, at most 72
    characters; bodies are short; review subjects read `review: <main finding>, and <n> smaller`.
17. **No remote yet.** A private GitHub repository is created only when the owner asks. Until
    then `CHANGELOG.md` has no link references. Tags mark milestones only, each with approval.
18. **Data as PDD Part 6.** `config.json` and every journal line carry a schema version; readers
    accept older versions and refuse newer ones with a clear error (forward-only). No backups:
    sources are never written, and working copies belong to the project that made them.
19. **Machine identifiers, never renamed:** package, CLI and repository `krita-art-mcp`; Python
    import `krita_art_mcp`; plugin module `krita_art_mcp_bridge` and kritarc key
    `enable_krita_art_mcp_bridge`; MCP server name `krita-art` and tool names `krita_*`; data
    directory `~/Library/Application Support/krita-art-mcp/`; `KRITA_ART_MCP_DATA_DIR`;
    `bridge.json`; bridge protocol `1`.
20. **Fixtures that no tool can build come from harness-only bridge operations.** A closed
    `harness.*` namespace in the plugin creates filter layers, filter and transform masks, clone
    layers, local selection masks, an active selection mask, and view zoom, pan and rotation. It
    never writes pixels, is never an MCP tool, and refuses any document outside
    the harness folder (decision 25). Pixel content comes from ORA files the server writes into
    that folder and the harness opens with `krita_document_open`.
21. **A session may restart Krita** (quit and relaunch it to load a reinstalled plugin) only when
    no open document has unsaved changes, as the bridge reports from each document's modified
    flag; otherwise it asks the owner. Until the bridge answers (the first restarts of session 2,
    or a plugin that fails to load), the session cannot see unsaved changes and always asks the
    owner to restart. The harness never quits Krita.
22. **Where the version shows:** `krita-art-mcp --version` and the MCP `serverInfo.version` from
    session 1; `krita_server_info` (`plugin_version` beside the server's) from session 2.
23. **Three version numbers, kept apart:** the package version (`0.N.0`, `pyproject.toml`, the
    plugin's copy held equal by a test); the tool contract's `api_version` (`"0.2.0"` for the
    amended Phase 1 contract; the package's was `"0.1.0"`); the bridge protocol (`1`).
    **Amended 2026-10-30 by the owner, in review 13:** the bridge protocol stays `1` while the
    server and the plugin are released together. From 13a, `serve` refuses a plugin whose
    version is not the server's (`PROTOCOL_MISMATCH`, with the install step as the fix), so an
    op or a field added under one number can never meet a plugin that lacks it; `ephemeral`,
    optional since 6a, becomes a required call field without a new number
    (`REVIEW-2026-10-30.md` F1, F10).
24. **Commands:** `verify` is `uv run scripts/verify.py`; the live harness is
    `uv run krita-art-mcp probe`. The harness drives `serve` over stdio as a real MCP client and
    uses `harness.*` only to build fixtures.
25. **`KRITA_ART_MCP_DATA_DIR` moves only what the server owns** (captures, baselines, journal),
    because Krita launched from the Dock never sees the variable. `bridge.json`, `transfer/`,
    `logs/` and `config.json` stay in the default data directory, and so does the harness
    folder: `~/Library/Application Support/krita-art-mcp/harness/` whatever the variable says,
    because the plugin must see it. Wherever this spec writes `<data dir>/harness/`, it means that
    folder. Both sides always allow it; the harness never edits `config.json`.
26. **Masks travel server → plugin as raw 8-bit files** in `transfer/` with their SHA-256. The
    plugin never decodes PNG.
27. **Definitions.** A document is *dirty* after any successful guarded call except
    `krita_protection_set` and a `krita_layer_update` that only sets `active`, until its next
    verified save. Duplicate names in `editable_layer_names` are `INVALID_ARGUMENT`.
28. **The H2 preset sheet uses stock presets as shipped.** Turning sensors on and off needs preset
    editing, which is Phase 2.
29. **Checked by unit tests only:** the uncertain outcome (Krita dying mid-call) and autosave
    `BUSY` during a save. Both are listed under *Not yet checked by hand*.
30. **Server instructions** (the MCP `instructions` text, PDD Part 4) start in session 2, gain each
    tool's rules in its session, and are finalised in session 14. A test holds them at or under
    4,096 characters from the start.
31. **Scope cuts, first first:** F-24 (Krita floating message), then preview tints. Nothing else
    is cut without the owner. F-20 (`document_close`) is not a cut: the harness needs it.
32. **Out of v1** (each in `docs/BACKLOG.md`): Phases 2–6 (profiles, construct operations,
    revisions, transactions, checkpoints, registration, PNG export, validation, asset modules,
    input-aware strokes); Krita 6.x verification (N-05, H5); probes on a Krita development build
    (Q9); the H1/H7 trial; Windows and Linux; a plugin zip for other users; H2 with sensors
    toggled. F-24 and tints join the backlog only if a session cuts them.

## 2. What v1 is, and is not

**v1 is** an MCP server and a Krita plugin that let an agent run the core loop on a working copy:
open (existing layers protected) → inspect, capture, sample → add a layer, select, tighten
protection → paint native brush strokes, each verified and rolled back on a leak → preview at
game size → undo or keep → save to a new KRA or ORA, verified by reopening → close. Every Phase 1
tool from PDD Part 4 (A: `server_info`, `document_list`, `document_open`, `document_create`,
`document_inspect`, `resource_list`, `capture`, `sample`; B: `layer_create`, `layer_update`,
`selection_set`, `protection_set`, `paint_stroke`; C: `history_step`, `operation_get`,
`operation_cancel`, `preview_render`, `document_save`, `document_close`), the CLI, and the
harness that proves them on Krita 5.3.x on macOS (Apple Silicon).

**v1 is not:** a pixel-art editor (Aseprite keeps that); headless; remote or multi-user; any
Phase 2–6 tool; a PNG exporter; per-point pressure (refused, or flattened on request, until
Phase 6); tested on Krita 6.x, Windows or Linux; a judge of whether strokes look painted (people
judge that).

## 3. Architecture

```
MCP client (Codex, Claude Code) ──stdio──▶ server: src/krita_art_mcp/   (Python 3.12)
                                              │ HTTP/1.1 + JSON, 127.0.0.1, bearer token;
                                              │ pixels as files in <data dir>/transfer/
                                              ▼
                              plugin: plugin/krita_art_mcp_bridge/  (inside Krita, 3.10 syntax)
                                bridge_core   HTTP, auth, jobs, dedup, registry, policy
                                krita_adapter every krita and PyQt call, on Krita's main thread
                                              ▼
                                       Krita's Python API (libkis)
```

**Layout** (session 1 creates it; names below are fixed, files inside are each session's):
- `src/krita_art_mcp/`: the CLI, the MCP server and its instructions, one module per tool group,
  the bridge client, the journal, roots and paths, imaging (mask rasterising, colour maths,
  previews, transfer files), `schemas/` (the tool JSON Schemas), and `probe/` (the live harness).
- `plugin/krita_art_mcp_bridge.desktop` and `plugin/krita_art_mcp_bridge/` with `bridge_core/`
  and `krita_adapter/`; `install-plugin` copies both into `pykrita/`.
- `tests/` (server, CPython 3.12), `tests/plugin/` (plugin core, CPython 3.10, no third-party
  packages but pytest), `tests/fixtures/`.
- `scripts/verify.py`.

**Boundaries.**
- The server never imports the plugin's adapter and reaches Krita only through the bridge
  protocol. Constants both sides need (protocol version, error codes, plugin version) are
  defined in `bridge_core` and in the server; a server test imports `bridge_core` and asserts
  the copies agree.
- `bridge_core` imports nothing from `krita` or PyQt. `krita_adapter` is the only place that
  does, and the only code that runs on Krita's main thread.
- Tool modules never speak HTTP; the bridge client does. Tool modules validate arguments against
  the tool's schema, apply the semantic checks, call the bridge, and build the envelope.
- Pixel buffers cross only as transfer files; JSON carries path, size and format.
- Document state (handles, protection, leases, undo ledger) lives in the plugin's registry, so
  every client and server process sees one state (PDD Part 8).

**Protocol, threading, verification and every Krita fact** are as PDD Part 8 (*Bridge protocol*,
*Plugin internals*, K1–K48, C1–C5); this file does not restate them.

**Pins** (dated 2026-10-23): as decision 4. Measured on the owner's Mac: Krita 5.3.4 at
`/Applications/krita.app`, bundling Python 3.13 and PyQt5 5.15.11 (QtNetwork included; the stdlib
HTTP thread stays, because Krita's main thread is busy during every job); uv 0.12.3; CPython
3.12.13 uv-managed.

## 4. Data model

**Entities** (PDD Part 6): Bridge `{port, token, pid, protocol, plugin_version, plugin_hash,
krita_version, qt_major}` (`plugin_hash` added, invariant 11); Document handle (plugin registry);
Operation `{operation_id, request_id, tool, args_sha256, status, result | error}` (bridge, per
Krita session); Journal entry `{v, ts, client, request_id, operation_id, tool, canonical args,
phase: dispatched | finished, result summary, document path, layer names}`; Config
`{v, roots: [absolute paths]}`. Project (profiles) is Phase 2.

**Files** as PDD Part 6, with decision 25: `config.json` (permanent), `bridge.json` (0600,
atomic, removed on quit), `captures/YYYY-MM-DD/` (7 days), `baselines/` (removed on close,
orphans swept at server start), `transfer/` (deleted after reading, swept at bridge start),
`journal/YYYY-MM-DD.jsonl` (permanent), `logs/plugin.log` (rotated at 5 MB), `harness/` (the
harness's own; swept at its start), working copies in each open's `working_dir`.

**Evolution.** No database. File formats carry a version (`v`) and evolve forward-only
(decision 18). The bridge protocol changes only with a new number, and a mismatch is
`PROTOCOL_MISMATCH`.

**Formats:** KRA (full fidelity), ORA (exchange; masks and adjustment layers are lost and
reported as `expected_losses`), PNG (read as one layer). Saves never write PNG in Phase 1.

## 5. Invariants

Each is a rule, not a preference. *Enforced by* names what fails when it breaks.

1. **No tool, harness operation or fixture writes raw pixels into a layer, and no tool runs
   code.** *Why:* scripted pixel edits caused the defects this product exists to fix (pillar 1).
   *Enforced by* a source scan in `verify` banning `setPixelData`, `Filter.apply`, `saveAs`,
   `exec` and `eval` in the plugin, and the tool list.
   **Amended 2026-10-24 by the owner, in review 6:** the wording stands; the scan gains one
   exception, decided for session 7 (`REVIEW-2026-10-24.md` F1). `Selection.setPixelData` loads
   a server-rasterised mask into a selection (PDD K11), which writes no layer. It may be called
   in one adapter function only, on a receiver that function built with `Selection()`; an AST
   test holds the receiver's origin and that no other call site exists.
2. **Accepted sources are never opened for writing, and no save overwrites a file.** *Why:*
   accepted art is the quality floor. *Enforced by* working-copy opens with hash checks,
   `FILE_EXISTS`, and harness checks that the source hash is unchanged.
3. **Every path an agent names resolves (realpath) inside an allowed root, and nothing is
   written outside the roots, the data directory and Krita's own temp and autosave files.**
   *Why:* agents must not reach the owner's other files (N-04). *Enforced by* checks on both
   sides, unit tests, and the harness.
4. **Protection only tightens in Phase 1.** *Why:* loosening is how accepted art gets damaged.
   *Enforced by* `protection_set` tests; reopening with `editable_layer_ids` is the only route.
5. **Every mutation is verified inside its own main-thread job; a violation is rolled back by
   native undo and the rollback confirmed, or the document is marked unsafe.** A rollback undoes
   only the steps that operation pushed (counted, and the top undo label checked). *Why:*
   nothing may land between a change and its check (PDD Part 8). *Enforced by* plugin-core tests
   against a fake adapter and harness leak tests.
6. **Every libkis call runs on Krita's main thread, one job at a time, and `waitForDone()` comes
   before any read after a paint, undo, redo or save.** *Why:* libkis is not thread-safe, and
   painting is asynchronous (K5, K41). *Enforced by* the adapter asserting its thread, the
   re-entry guard, and harness timing checks.
7. **Layering.** Every `krita` and PyQt import lives in `krita_adapter`; `bridge_core` is pure
   and valid under 3.10; the plugin uses only the standard library, PyQt and `krita`. *Why:* the
   core must be testable outside Krita and portable across Krita builds. *Enforced by* an
   import-scan test and the 3.10 test environment.
8. **Every input rejects unknown fields and is never clamped, normalised or substituted; every
   result, errors included, validates against its output schema; errors are returned, never
   raised; every message stays under 6 MB.** *Why:* agents depend on exact, typed answers, and
   Codex drops the connection above 8 MB (C1, C5). *Enforced by* schema tests over every tool's
   success and error results, and a size test.
9. **The journal line is written before dispatch; a retried `request_id` never repeats work; an
   uncertain call is never re-sent.** *Why:* a duplicated stroke is a silent defect. *Enforced
   by* journal and dedup tests on both sides.
   **Amended 2026-10-24 by the owner:** within one Krita session the bridge deduplicates however
   old the `request_id`; across a Krita restart only the server's journal can, and it reads the
   last 7 days of journal files. A retry of an open or a create more than 7 days later, after a
   Krita restart, would run again.
10. **The capability matrix is true at every release, and a tool is registered only once built.**
    *Why:* agents adapt to capabilities, not versions. *Enforced by* a test comparing registered
    tools to the built list, and harness checks of each capability.
11. **No stale plugin.** The plugin reports a hash of its own source; `probe` and `doctor` refuse
    a mismatch with the repository. *Why:* the version changes once per session, the code more
    often. *Enforced by* the probe's first check.
12. **The bridge listens on 127.0.0.1 only and requires the token** (constant-time compare,
    `Host` check, 64 MB body limit); the token is never logged or returned; `bridge.json` is
    0600. *Why:* other users and browsers stay out. *Enforced by* plugin-core tests.
13. **Harnesses never touch the owner's documents, files, `kritarc` or `config.json`;** they work
    in `<data dir>/harness/`, close what they open, sweep leftovers at start, and save and restore
    the window's brush state. *Why:* the owner's Krita is live while sessions run. *Enforced by*
    the harness structure and the `harness.*` folder gate.
14. **Nothing private enters the repository** (decision 14). *Why:* the history will be public.
    *Enforced by* the hygiene stage: hashed private terms against every tracked text file, and
    attribution trailers against every commit message.
    **Amended 2026-10-24 by the owner, in session 7a:** *Enforced by* the hygiene stage, run with
    the drafted commit message. It checks the owner's term list (missing fails, empty passes)
    against the paths and contents of tracked, untracked and staged text files and against every
    commit message, the draft included, and checks the messages for AI attribution.

## 6. Verification strategy

**`verify` = `uv run scripts/verify.py`**, named stages, each failing on its own, then a summary:
ruff format check; ruff; mypy (strict for the server; the plugin core checked as 3.10); pytest on
3.12; plugin-core pytest on 3.10; hygiene. Green before every commit. `docs/` is outside every
stage but hygiene.

| Layer | Runs | Covers | Cannot see |
|---|---|---|---|
| Unit (server) | `verify` | Schemas and examples (Draft 2020-12), argument rules, envelope and errors, roots, journal, dedup client side, mask rasterising, colour maths (PDD Part 12 fixtures, tolerance 0.05), preview geometry, the bridge client against a fake bridge, an in-process MCP stdio round trip | Real Krita |
| Unit (plugin core) | `verify`, on 3.10 | HTTP, auth, jobs and re-entry, dedup, registry and policy (protection, lease, undo ledger, dirty), verification logic against a fake adapter | libkis behaviour |
| Hygiene | `verify` | Private terms in tracked files; attribution in commit messages | Images and binaries |
| Live harness (`probe`) | Every session that touches the plugin, the protocol or a Krita-facing tool | Every built tool on its own documents through stdio MCP: colour exactness, verification and rollback, refusals, selection enforcement, view independence, undo and redo, retries, save fidelity, the capability matrix, runtime probes | Whether strokes look painted; Krita 6.x; other machines |
| Benchmarks | Inside `probe` from sessions 9 and 11 | N-01, N-09, N-02 against their budgets, failing over them | Machines other than the owner's |
| Architecture reviews | Sessions 6, 10, 13 | Code against this file | Runtime behaviour |
| By hand | Recorded in done-notes | The plugin-enable flow, H2's sheet, H3 in Codex, N-03 | Anything not written down; unchecked items go to the backlog |

**Amended 2026-10-24 by the owner, in session 7a:** hygiene cannot see images and other
binaries, their metadata included; a term joined to another word inside one lowercase run; or
attribution in files, which is checked in messages only.

**Falsification.** Each check a session adds is falsified once: break what it guards, watch it
fail at its own step, restore by editing or copying the file back. Existing checks are not
falsified again.

## 7. PDD amendments

| PDD place | PDD says | This spec | Decision |
|---|---|---|---|
| Part 1 *Platforms*; Appendix E (2026-10-22) | Krita 5.3 and 6.0 from day one | 5.3.x only in round 1 | 3 |
| Part 5 N-05; Part 12 H5 | Plugin passes on both builds | Backlog | 3, 32 |
| Part 5 *Constraints* | Bundled Python ≥ 3.10, to measure | Measured 3.13 (5.3.4, macOS); the 3.10 floor stays | 4 |
| Part 5 *Non-functional* | Session 1 measures the budgets; the intake confirms | Gated where the path is built | 6 |
| Part 8 *Stack* table | QtNetwork: no evidence Krita bundles it | Measured: it does; the stdlib HTTP thread stays | §3 |
| Part 6 *Files* | `KRITA_ART_MCP_DATA_DIR` overrides for the harness | Moves server-owned files only | 25 |
| Part 12 H2 | Fade/Distance sensors on and off | Stock presets as shipped | 28 |
| Part 12 *Harness rules* | Krita running with the plugin enabled | Sessions may restart Krita when safe; `harness.*` builds fixtures | 20, 21 |
| Part 4 *Server instructions* | "The session writes it" | Started in 2, finalised in 14 | 30 |
| Part 13 slices 1–7 | Seven sessions | Fifteen, with three reviews | 2 |
| Part 13 slice 1 | Version in `krita_server_info`; amended examples | `serverInfo.version` first; examples copied unamended | 5, 22 |
| Part 13 *Scope cuts* | F-24, tints, F-20 | F-24, then tints; F-20 stays | 31 |
| Part 4 envelope | `api_version` `"0.1.0"` (package) | `"0.2.0"` | 23 |
| Part 2; Appendix C Q12 | Copy the package unchanged | Copied scrubbed | 13 |

## 8. Traceability

| Requirement | Session |
|---|---|
| F-01 server info and capabilities; F-23 `doctor` | 2 (roots checks join in 4) |
| F-04 create; F-16 operations; F-20 close; F-21 idempotent and journaled | 3 |
| F-03 open; F-05 inspect; N-04 roots (unit) | 4 |
| F-06 resources; F-07 capture; F-08 sample | 5 |
| F-09 `layer_create`; F-10 selections; F-11 protection; F-15 undo and redo | 7 |
| F-09 `layer_update` | 8 |
| F-12 stroke; F-13 input gate; N-01, N-06, N-07, N-08, N-09; H6, H8 | 9 |
| F-17 preview; N-02 | 11 |
| F-18 save; F-19 `mergedimage.png`; H4 long save | 12 |
| F-22 no raw writes or code | 1 onwards (invariant 1) |
| F-24 floating message (Could); H2; H3; N-03; N-04 (harness); the contract's exercises | 14 |
| H4 idle latency | 2 |
| N-05, H5; H1, H7; H9 | Backlog; after the round; Phase 2 |

## 9. Definition of done for v1

1. Every block in `SESSIONS.md` has its done-note and Review section; every inserted session and
   amendment is logged with its reason.
2. All 19 tools are registered with amended schemas; every example and every result validates.
3. `verify` is green, and the full harness passes on Krita 5.3.x, with its counts in
   `ARCHITECTURE.md`'s baseline.
4. N-01, N-02 and N-09 pass their benchmarks, or the owner's recorded decision says otherwise.
5. H3, H4, H6 and H8 hold, and the contract's acceptance exercises pass as scoped in PDD Part 12
   (exercise 5 renders the 2.95 / 1.8 px-per-unit and 128 / 256 px previews from explicit
   recipes; profiles, PNG export, the project checker and interruption recovery are later
   phases).
6. Every invariant's enforcement exists and is described in `ARCHITECTURE.md`.
7. `docs/ARCHITECTURE.md`, `docs/USER-GUIDE.md` and a truthful README exist; `CLAUDE.md` points at
   them.
8. Everything still open is in `docs/BACKLOG.md`, and `docs: close round 1` has emptied
   `docs/spec/`.
9. The trial and making the repository public are the owner's separate steps, not part of done.
