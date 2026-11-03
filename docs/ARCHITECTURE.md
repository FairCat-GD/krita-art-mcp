# krita-art-mcp — architecture, as built

This is the system as it stands at 0.19.0, in round 2, on the Phase 1 round 1 built. Every session
keeps it true, in the same commit as the change. Each section stands on its own: a session reads
the overview, the invariants and the baseline, then only the sections its work touches.
`docs/USER-GUIDE.md` is the same system from the user's side.

## Overview

krita-art-mcp lets an AI agent paint in the owner's running Krita through Krita's own brush engine.
It is for painted (non-pixel) 2D game art, run by one developer on macOS with Krita 5.3.x. The core
loop: open a working copy with every existing layer protected; inspect, capture and sample; add a
layer, select, tighten protection; paint native strokes, each verified and rolled back on a leak;
preview at game size; undo or keep; save to a new KRA or ORA, verified by reopening; close.

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

**Layout.**
- `src/krita_art_mcp/`: the CLI (`cli.py`, `install.py`, `doctor.py`, `setup_checks.py`), the MCP
  server (`server.py`, `instructions.py`, `envelope.py`, `errors.py`), one module per tool group
  (`tools/`), the bridge client, the journal, roots and paths, imaging (`imaging.py`, `sheets.py`,
  `masks.py`, `strokes.py`, `colour.py`, `verification.py`, `transfer.py`, `baselines.py`),
  `schemas/` and `probe/`.
- `plugin/krita_art_mcp_bridge.desktop` and `plugin/krita_art_mcp_bridge/`, with `bridge_core/`
  and `krita_adapter/`. `install-plugin` copies both into Krita's `pykrita/`.
- `tests/` (server, CPython 3.12), `tests/plugin/` (plugin core, CPython 3.10), `tests/fixtures/`
  (shared by both, so valid on 3.10) and `tests/support/` (the server's).
- `scripts/`: `verify.py`, `hygiene.py`, `amend_schemas.py`.
- `docs/reference/contract-package/`: the frozen contract. Nothing reads it, and every `verify` stage
  but hygiene skips it.

**Three version numbers, kept apart.** The package version (`pyproject.toml`, with the plugin's
copy held equal by a test), shown by `--version`, in the MCP `serverInfo` and by
`krita_server_info`. The tool contract's `api_version`, `"0.3.0"`, in every envelope. The bridge
protocol, `1`. The protocol stays 1 while the server and the plugin are released together, because
`serve` refuses a plugin of any other version (see *The bridge contract*).

**Terms these documents use.**
- **The PDD:** the product design draft round 1 started from. It describes all six phases in full.
- **The contract:** the draft tool schemas and acceptance exercises that came with the PDD, for all
  69 planned tools. They were the starting point for every schema here, never the authority, and
  Phase 2 starts from their draft shapes. It is frozen, and kept in `docs/reference/contract-package/`.
- **Phase N:** the PDD's roadmap. Phase 1 is built. Phases 2 to 6 are construct, integrity,
  delivery, asset modules and input-aware strokes, each its own round.
- **Review N and F-numbers:** the three architecture reviews of round 1, named for their sessions
  (6, 10, 13), and their findings.
- `docs/spec/` held the PDD, the round's plan and the reviews. `docs/BACKLOG.md`'s header says how to
  read them from git history.

## The invariants

Rules, not preferences. `CLAUDE.md` states them for every session; this section adds why each
exists and what fails when it breaks.

1. **No raw pixel writes, and no tool runs code.** *Why:* scripted pixel edits caused the defects
   this product exists to fix. *Enforced by* the AST scan in `tests/plugin/test_source_scans.py`,
   which bans `setPixelData`, `saveAs`, every `.apply` attribute, `exec`, `eval`, `compile`,
   `__import__`, computed attribute access and the code modules. Its one exception is
   `krita_adapter.selections._from_mask`, which loads a mask into a `Selection()` it built (K11) and
   writes no layer; an AST test holds that site and its receiver. The tool list holds the rest.
2. **Accepted sources are never opened for writing, and no save overwrites a file.** *Why:* accepted
   art is the quality floor. *Enforced by* `files.working_copy`, which copies under `O_EXCL` while
   hashing and re-hashes the copy; `read_only` mode, which refuses every mutation; `exportImage`,
   never `saveAs` (K39); a save that links its hidden file into place only if nothing is there;
   `FILE_EXISTS`; and the probe's source-hash checks.
3. **Every path an agent names resolves (realpath) inside an allowed root,** on both the server and
   the plugin, and nothing is written outside the roots, the data directory and Krita's own temp and
   autosave files. *Why:* agents must not reach the owner's other files. *Enforced by* `roots.py`
   on each side, a test that both give the same answers, and the probe's escapes and N-04.
4. **Protection only tightens.** *Why:* loosening is how accepted art gets damaged. *Enforced by*
   `protection.protect`, which refuses dropped ids, cleared flags and any mask allowing a pixel the
   current one does not. Reopening with `editable_layer_ids` or `editable_layer_names` is the only
   route to edit a protected layer.
5. **Every mutation is verified inside its own main-thread job.** A violation is rolled back by
   native undo and the rollback confirmed; if it cannot be, the document is marked unsafe. A rollback
   undoes only the steps its operation pushed. *Why:* nothing may land between a change and its check.
   *Enforced by* plugin-core tests against a fake adapter, and the probe's leak checks.
6. **Every libkis call runs on Krita's main thread, one job at a time,** and `waitForDone()` comes
   before any read after a paint, undo, redo or save. *Why:* libkis is not thread-safe and painting is
   asynchronous (K5, K41). *Enforced by* `Jobs.drain`, which refuses other threads and re-entry, and
   an AST rule that every pixel read in the adapter waits first.
7. **The plugin's layers stay apart.** Every `krita` and PyQt import lives in `krita_adapter`;
   `bridge_core` is pure and valid under 3.10; the plugin uses only the standard library, PyQt and
   `krita`. *Why:* the core must be testable outside Krita, and portable across Krita builds.
   *Enforced by* the import scan and the 3.10 test stage.
8. **Inputs are exact; results are typed and small.** Inputs reject unknown fields and are never
   clamped, normalised or substituted. Every result, errors included, validates against its output
   schema. Errors are returned, never raised. Every message stays under 6 MB. *Why:* agents depend on
   exact, typed answers, and Codex drops the connection above 8 MiB (C1, C5). *Enforced by* schema
   and size tests over every tool.
9. **Retries are safe.** The journal line is written before dispatch, a retried `request_id` never
   repeats work (within a Krita session, however old; across a Krita restart, for 7 days), and an
   uncertain call is never re-sent. A retry of an open or a create more than 7 days later, after a
   Krita restart, would run again. *Why:* a duplicated stroke is a silent defect. *Enforced by*
   journal and dedup tests on both sides.
10. **The capability matrix is true at every release,** and a tool is registered only once it is
    built. *Why:* agents adapt to capabilities, not versions. *Enforced by* a test comparing the
    registered tools to the built list, and the probe's checks of the matrix.
11. **No stale plugin.** The plugin reports a hash of its own source. `probe` and `doctor` refuse a
    hash other than the repository's, and `serve` refuses a plugin of another version. *Why:* an op
    or a field added in one release must never meet a plugin that lacks it. *Enforced by*
    `setup_checks.plugin_current` and the version gate in `BridgeClient._open`.
12. **The bridge is closed to everyone but the owner.** It listens on 127.0.0.1 only and requires
    the token (constant-time compare, `Host` check, 64 MB body limit). The token is never logged, and
    `bridge.json` is 0600. *Why:* other users and browsers stay out. It is not a boundary against the
    owner's own processes, which can already write the files directly. *Enforced by* plugin-core
    tests.
13. **Harnesses leave the owner's things alone.** They never touch the owner's documents, files,
    `kritarc` or `config.json`, they work only in `<data dir>/harness/`, and they restore the brush
    state afterwards. *Why:* the owner's Krita is live while sessions run. *Enforced by* the
    `harness.*` folder gate on every op that takes a document, and the probe's structure.
14. **Nothing private enters the repository.** *Why:* its whole history is meant to be public.
    *Enforced by* the hygiene stage (see *Testing strategy*).

## The bridge contract

The server reaches Krita only through this protocol, and the plugin keeps all document state, so
every client and server process sees one state.

**Transport.** HTTP/1.1 and JSON on `127.0.0.1`, on an ephemeral port, with a 32-byte token made at
every Krita start. `bridge.json` publishes `port`, `token`, `pid`, `protocol`, `plugin_version`,
`plugin_hash`, `krita_version`, `qt_major` and `session_id`, written 0600 through a temp file and
`os.replace`, and deleted on quit only if it is this instance's. A second Krita refuses to start a
bridge while the file names a live process that is Krita; a stale file is taken over.

**Refusals, in order:** the `Host` header, the token (as bytes, with `hmac.compare_digest`), 503
while stopping, then the body: 411 with no length or when chunked, 413 over 64 MB, before reading.

**Endpoints.**

| Endpoint | Does |
|---|---|
| `POST /v1/call` | `{op, args, request_id, operation_id, client: {pid, started_at}, wait_s, ephemeral}` |
| `GET /v1/operations/<id>?wait_s=` | The same reply shape, for a call left running |
| `POST /v1/operations/<id>/cancel` | Cancels a queued job only |
| `GET /v1/health` | Protocol, versions and capabilities, cached on the main thread at bridge start |

Every operation reply carries `session_id`, `operation_id`, `request_id` and `op`; health and
refusals leave out `op`. One error body serves every refusal. `wait_s` is capped at 10 s. `ephemeral` is required on every call.

**The ops: 31.**

| Group | Ops |
|---|---|
| Sent by tools (18) | `server_info`, `document.list`, `document.open`, `document.create`, `document.inspect`, `document.close`, `document.save`, `document.save_finish`, `resource.list`, `capture.read`, `sample.read`, `preview.read`, `layer.create`, `layer.update`, `selection.set`, `protection.set`, `history.step`, `paint.stroke` |
| Server and `doctor` (2) | `bridge.unsaved_documents`, `document.baselines` |
| Fixtures, the probe only (10) | `harness.export_kra`, `.select_mask`, `.front_document`, `.activate`, `.undo_labels`, `.label_timing`, `.add_node`, `.view`, `.brush_state`, `.undo` |
| A measurement, the probe only (1) | `harness.retention` |

**The harness ops' reach.** Any client with the token can call them, and they bypass protection, on
owned documents whose file lies inside `harness/` only; `harness.retention` and
`harness.front_document` take no document. They
ship in every user's plugin because there is one plugin. A process that has the token could already
do more through the owner's own files.

**Versions.** `BridgeClient._open` refuses a `plugin_version` other than the server's with
`PROTOCOL_MISMATCH`, naming both versions and both fixes, because a running `serve` older than the
plugin meets this at every release and `install-plugin` cannot cure that: the MCP client must
restart. `doctor` and `probe` pass `any_plugin=True`, which skips the gate and the protocol number,
so the unsaved-documents count still works on a stale plugin, the one moment it is read. Both
refuse by hash instead, a stricter test.

**Waits.** The bindings never release the GIL (K40), so the HTTP thread is silent during a long
libkis call, and the server owns the wait budget: 45 s (`WAIT_BUDGET_S`), under Codex's 60 s default.
It polls with 2 s waits and a socket timeout 3 s longer, and after the budget returns
`status: running` with the `operation_id`.

**Dedup and retention.**
- A `request_id` names one operation for the Krita session. Its hash is SHA-256 of canonical
  `{op, args}`. A duplicate returns the original operation, and its own `operation_id` becomes an
  alias of it; other arguments answer `REQUEST_ID_CONFLICT`.
- A retryable failure releases the id but keeps its hash bound. *Retryable means the op changed
  nothing,* a rule the outcome rule (see *Bridge and jobs*) reads and a test holds at every
  retryable raise.
- Finished operations keep their results and drop their arguments. Requests an agent named stay for
  the session. Reads, which the server names itself, are `ephemeral`: pruned at most once a minute,
  10 minutes after delivery or an hour after finishing undelivered.

**A 404 while following a call.** A prompt 404 for 2 s (`REGISTER_GRACE_S`) before the bridge has
said `running` ends the follow with `outcome: "unregistered"`, retryable. A timeout, a reset or a
reply slower than 0.5 s restarts the window, because a POST stuck behind a long Krita call does
register later. `unregistered` means the bridge has no entry, and it says nothing of the call's
arrival, so the journal keeps the attempt unsettled.

**One lock in each server.** `tools.CALLS` serialises every tool call in a server process, so a
client cannot inspect while its own 45-second save runs. That is right for one agent making
sequential calls; revisit it when a client runs tools in parallel. The bridge serialises jobs across
all clients regardless.

**One op outside `RECEIPTS`.** `document.save_finish` is reached only through the save's `finish`
hook, so a poll of its own id answers "That operation belongs to no tool". Agents are only ever given
the save's id. The completeness test scans tool functions for `call("…")` literals, so the next
two-op tool should know its reach.

## The tool contract

**19 tools.** Observe: `krita_server_info`, `krita_document_list`, `krita_document_open`,
`krita_document_create`, `krita_document_inspect`, `krita_resource_list`, `krita_capture`,
`krita_sample`. Paint safely: `krita_layer_create`, `krita_layer_update`, `krita_selection_set`,
`krita_protection_set`, `krita_paint_stroke`. Deliver: `krita_history_step`, `krita_operation_get`,
`krita_operation_cancel`, `krita_preview_render`, `krita_document_save`, `krita_document_close`.

**The envelope.** Every tool returns `structuredContent` matching its output schema:
`{api_version, status, document_id, revision, operation_id, data, error}`, plus one short text line.
`status` is `completed`, `queued`, `running`, `failed` or `cancelled`. Images are MCP image content
with `_meta: {"codex/imageDetail": "original"}` (C2), so they are built directly, since `mcp`'s
`Image` takes no `_meta`. Errors come back as `CallToolResult(is_error=True, …)` with the envelope,
because a raised exception reaches the client only as "Error executing tool X" (C1).

**`details.outcome` says whether a failure applied.** It is typed in the shared error shape, and its
values are `applied`, `not_applied`, `uncertain` and `unregistered`.
- Application, rollback, verification and receipt validity are separate fields: `outcome`;
  `rolled_back` and `rollback_verified`; the receipt's `verification`; `receipt_valid` and
  `receipt_problem`.
- `applied` means the handler returned and the bridge holds it `done`, and nothing else may say it.
  It is never retryable.
- A failure is `not_applied` only on proof, and `uncertain` is the default (see *Bridge and jobs*).
- `operation_id` exists from dispatch on, so a refusal before dispatch has none and is `not_applied`.
- A read's failure from the bridge or from the server's work on its pixels states it too, always
  `not_applied` unless a file stayed open. A refusal the server makes itself leaves it out.

**`api_version` moves when a field or an input value is removed or renamed, or a field changes
meaning.** Added fields and tools do not move it.

**Schemas are data.** Each of the 19 `schemas/krita_<tool>.json` holds `name`, `description`,
`inputSchema`, `outputSchema`, `annotations` and `example`. `MCPServer` tools are built by hand with
`FuncMetadata`, so the contract's exact JSON Schema is published and no pydantic model filters
arguments; `ExactArguments` passes them through and the runner validates with Draft 2020-12.
`scripts/amend_schemas.py` writes the shapes the files share (the envelope with its typed error,
`guard`, `source`, the completed rule's copy of `data`, inspect's `layers`) and formats them; a test
holds the files to it.

**Hints follow each tool's worst permitted behaviour.**
- The eight reads are `readOnlyHint: true`.
- Five mutating tools only add, and are `destructiveHint: false`: `krita_layer_create`,
  `krita_protection_set`, `krita_document_open`, `krita_document_create` and `krita_document_save`.
- The other six are destructive, because undoable is not additive.
- `idempotentHint` is true and `openWorldHint` false on every tool.
- `readOnlyHint` is load-bearing. `tools.build` reads it to decide what mutates, and the
  `BOUNDED` test holds the ops to it.
- A table test in `tests/test_tools.py` holds all 19, so a new tool's hints are chosen, never
  copied.

Codex reviews every destructive call unless the owner sets the server's
`default_tools_approval_mode`; the user guide says what that removes.

**Which forms reach Codex.** Codex shows its model a TypeScript declaration, never the schema, so a
valid schema can still arrive as `unknown`. `tests/test_schemas.py` holds these forms:
- no `allOf`, no `prefixItems`, no `items: false`;
- a tuple is `items` with `minItems` equal to `maxItems`;
- a union has nothing beside it, and each branch is typed;
- a conditional sits under `dependentSchemas` on the field it reads, because an `if` passes on an
  absent field and adds a false problem; Codex drops the keyword, as it drops `if`;
- "field absent" is `{"properties": {"f": {"not": {}}}}`, because a bare `false` loses the error's
  path;
- outputs are one chain written by `amend_schemas.py`: completed, else failed, else pending.

Codex's limits, measured at 0.15.0 with a scratchpad port of its renderer:
- a normalised input over 5,000 bytes is compacted (the largest was 2,135);
- a rendered input or output over 16,000 bytes becomes `unknown` (the largest was 2,294);
- `Array<number>` hides a tuple's length.

Nothing re-measures these. Every later schema change has been small beside the margins. `ALL_TOOLS` carries the declarations, so an agent reads one
by filtering for it.

**Argument errors name every problem,** up to `MAX_REPORTED_PROBLEMS` (50). The message joins them,
`details.errors` lists them and `details.omitted` counts the rest. Fields take turns over the cap, so
one repeated mistake cannot hide another; the cap keeps an answer well under Claude Code's 25,000
tokens (C4). A forbidden field reads "not allowed with these arguments".

**Semantic checks stop at their first refusal.** One envelope carries one code with its own
`details`, these codes differ, and a later check can assume an earlier one held. The server's checks
that compute feed each step's result to the next. The plugin's handlers are a second line behind the
schema, where a job ends at its first raise and each check reads what the one before confirmed: the
document before the layer before the pixels.

**Argument rules are written twice on purpose.** Each side trusts no caller, and a refusal the server
makes carries no `operation_id`. Six such pairs have no parity test yet; round 2's F1 adds them.

**The error codes: 30.** The default `retryable` is the server's; a site may override it, and
`docs/USER-GUIDE.md` says what an agent should do with each.

| Code | Default retryable | Raised by |
|---|---|---|
| `INVALID_ARGUMENT` | no | schema; both sides' rules |
| `UNSUPPORTED_CAPABILITY` | no | both sides |
| `KRITA_NOT_RUNNING` | no | bridge client, with the missing step; plugin, a 503 while it stops |
| `PROTOCOL_MISMATCH` | no | bridge client |
| `KRITA_MODAL_DIALOG`, `MULTIPLE_WINDOWS` | yes | plugin, at job start only |
| `BUSY` | yes | plugin: an autosave holding a document during a save |
| `TIMEOUT` | no | **reserved: nothing produces it.** Phase 1 has no hard limit; a long call returns `running` |
| `CANCELLED` | yes | plugin: a queued job cancelled, or stopped at quit |
| `REQUEST_ID_CONFLICT` | no | both sides |
| `DOCUMENT_NOT_FOUND`, `LAYER_NOT_FOUND` | no | plugin |
| `LOCKED_TARGET`, `LAYER_NOT_PAINTABLE`, `LAYER_HAS_LOCAL_SELECTION` | no | plugin |
| `PROTECTED_REGION_CHANGED`, `OUTSIDE_ALLOWED_MASK` | no | plugin |
| `RESOURCE_HASH_MISMATCH` | no | both sides |
| `SOURCE_HASH_MISMATCH` | no | plugin |
| `COLOR_PROFILE_MISMATCH` | no | both sides |
| `DOCUMENT_DIRTY`, `DOCUMENT_UNSAFE`, `DOCUMENT_READ_ONLY`, `DOCUMENT_IN_USE` | no | plugin |
| `SAVE_VERIFY_FAILED` | no | plugin |
| `PATH_NOT_ALLOWED` | no | both sides |
| `FILE_EXISTS` | no | plugin (retryable when a working copy's name collides) |
| `IO_ERROR` | no | both sides (retryable when a transfer file or mask is gone) |
| `ROLLBACK_FAILED` | no | plugin; the document is then unsafe |
| `INTERNAL_ERROR` | no | anywhere; `details.outcome` is `uncertain` or `unregistered` for a call whose fate is unknown, and `applied` for a finished call whose answer failed |

**The contract's placeholders.** Phase 1 keeps the contract's shape, and the PDD wants refusals typed
rather than fields hidden. So the schemas admit inputs that always refuse, and outputs carry fields
with one value. A refused value stays advertised only if a named phase will make it live, decided at
the round 2 intake for the schemas that round amends.

| Input | Today | Becomes live |
|---|---|---|
| `krita_layer_create` `type: transparency_mask` | `UNSUPPORTED_CAPABILITY` | Round 2's M1 |
| `krita_paint_stroke` per-point pressure, tilt, rotation, tangential pressure, speed, time | `UNSUPPORTED_CAPABILITY`, unless `input_fallback: flat` | Phase 6, on Krita 6.1 / 5.4 (K30) |
| `input_fallback`, which takes only `flat` | the one value | Phase 6 |
| `smooth: basic`, `stabilizer` | `UNSUPPORTED_CAPABILITY` | Never: decided against; they belong to Krita's freehand tool |
| `antialias: false` | `UNSUPPORTED_CAPABILITY` | No phase names it; to measure per engine |
| `eraser: true` | `UNSUPPORTED_CAPABILITY`; the plugin keeps the plumbing | The backlog's *Erasing* |
| Every read's `frame` other than 0 | `UNSUPPORTED_CAPABILITY` | Phase 5 |
| `krita_document_create` depths other than `U8` | `UNSUPPORTED_CAPABILITY` | No phase names it |
| `krita_document_create` `color_model: RGBA`, `background: transparent` | the one value | No phase names it |
| `krita_document_save` `overwrite: false`, `verify_reopen: true` | required constants | No phase names a change |
| `krita_protection_set` `preserve_canvas` | stored and reported; nothing in Phase 1 changes a canvas | Phase 2, with `canvas_resize` |

| Output | Today | Becomes live |
|---|---|---|
| `revision` in every envelope | `null` | Phase 3 |
| `uri` in every artifact | equal to `path` | Phase 3, `krita-artifact://` |
| `krita_paint_stroke` `input_applied` | `flat` | Phase 6 |
| `krita_paint_stroke` `effective_brush.antialias` | `true` | When `antialias: false` does |
| `krita_capture` `fresh` | `true` | No phase promises it; meaningful once reads can pin a revision (Phase 3) |
| `krita_preview_render` `static_only`, `source_pixels_changed` | `true`, `0` | Statements, kept: a preview certifies no motion and writes nothing |
| `krita_document_save` `reopened_verified`, `composite_preserved` | `true` | Statements, kept: any other outcome is an error |
| `krita_paint_stroke` `protected_pixels_changed`, `changed_outside_px`, `undo_steps` | `0`, `0`, `1` | Statements, kept: on a completed stroke; a leak is an error |
| `krita_protection_set` `composite_outside_mask`, `undo_steps` | `exact`, `0` | Statements, kept |
| `krita_layer_update` `undoable` | `["blend_mode"]` or empty | Statement, kept (K22) |
| `krita_layer_create` `protected`; `krita_document_create` `mode` | `false`; `new` | Statements, kept |

`limits.capture_pixels` in `krita_server_info` is reported and enforced by nothing but `max_px`'s
schema maximum, of which it is the square.

**The capability matrix** is the one place a later feature announces itself. False today:
`stroke.per_point_input` (Phase 6), `undo.grouping` (K29), `stroke.deterministic` (stochastic
presets have no seed), `operation.cancel_running`, `color_spaces`, `filters` (Phase 2), `animation`
(Phase 5). True since 0.9.0: `stroke.native_brush`, `stroke.smoothing`, `selection.enforced`.

**The instructions.** `instructions.py` is 3,970 of Claude Code's 4,096 characters (C4), held by a
test, and states every rule an agent would otherwise learn from a refusal.

## The data layer

No database. Everything is a file with a known owner and lifetime. `KRITA_ART_MCP_DATA_DIR` moves only
what the server owns, because Krita launched from the Dock never sees the variable.

| Path | Written by | Holds | Lifetime |
|---|---|---|---|
| `~/Library/Application Support/krita-art-mcp/` | `private_dir` | The data folder, 0700 | Permanent |
| `config.json` | `krita-art-mcp roots` | `{v, roots}` | Permanent |
| `bridge.json` | plugin | The bridge entity, 0600 | Removed on quit; a crash leaves it for the next start |
| `logs/plugin.log` | plugin | Tracebacks and bridge events, never the token | Rotated at 5 MB, one backup |
| `transfer/` | plugin's reads, server's masks | Raw `BGRA8` and `A8` buffers | Deleted after reading; an hour at most; swept at bridge start |
| `harness/` | probe | Its fixtures and its servers' data | A run; swept at start and end |
| `captures/YYYY-MM-DD/` | server (moves with the variable) | Captures, previews, masks, diffs | 7 days |
| `baselines/` | server (moves) | `.npy` composites as opened | Removed on close; orphans swept at server start |
| `journal/YYYY-MM-DD.jsonl` | server (moves) | One line per attempt | Permanent |
| `journal/args/<day>/<op>.json` | server (moves) | Each call's arguments | Permanent |
| `<working_dir>/<UTC stamp>-<name>` | plugin | Working copies | The agent's |
| `.<stem>.<token>.saving.<ext>` beside a save | plugin | The save's hidden file | Until the finish, or a new save or close |

**Evolution is forward-only.** `config.json` and every journal line carry a version `v`. The config
reader accepts its version; the journal reader accepts version 2 only, and refuses any other with a
message naming both cures. A line it skipped could let a retry repeat its work. No journal line older
than 0.9.0 can fall inside the 7-day window.

**The journal.** `journal.py` writes a day file, 0600 in a 0700 folder, each line in one `os.write`
under `flock`, after a newline if a crashed writer left a partial line. Only calls that carry a
`request_id` are journaled; reads are not. Arguments go to a sidecar written before the line that
names them, so a lookup never decodes point arrays. The index holds the last 7 UTC days and follows
lines other processes append. Each attempt's outcome is one of:

| Outcome | Settles |
|---|---|
| `receipt` | Every attempt the bridge deduplicated in that session |
| `no_effect` | Its own attempt, and the one whose operation the bridge named |
| `not_sent`, `conflict` | Its own attempt alone |
| `unknown` | Nothing yet; an attempt unknown in another Krita session is never re-sent |

`outcome_of` makes `details.outcome` `applied` a `receipt`, and `uncertain` and `unregistered`
`unknown`. A resend needs a request proven never dispatched, a retryable failure, or a live Krita
session whose dedup state covers that exact `request_id`. Past the 7-day window nothing remembers a
request, invariant 9's stated limit.

The index also keeps each finished line by its `operation_id` and by the `bridge_operation_id` a
retry was answered under, so `krita_operation_get` can answer once Krita has moved on. An `unknown`
line never replaces a settled one, and "finished" alone never means applied: the line keeps its
outcome, session, request and result.

**A finished line carries `elapsed_ms`,** the server's own time on the call.
- **Where the clock runs.** From the call's arrival at the tool, before `CALLS`, to the line. The
  lock wait and the input check count, so a client's wall clock minus it is time outside the
  server.
- **When it is `null`.** On a line a later `krita_operation_get` writes for a call that came back
  running, because no one call spans it.
- **Older lines.** A line written without the field reads as `null`. The reader takes fields by
  name, so the added field moves no version.

A heavy week is about 44 MB of lines, read by the first lookup of each server process; the probe
watches it, and the backlog holds the retention rule.

**Transfer.** Pixels cross only as files; JSON carries `{path, size_px, format}`. The plugin writes
0600 in a 0700 folder. The server reads with `O_NOFOLLOW`, checks the folder and the size, and swaps
BGRA to RGBA (K12). Masks travel the other way as raw 8-bit files with their SHA-256, named
`mask-<16 hex of SHA-256(request_id)>-<sha256>.a8`, one per request, because the plugin never decodes
PNG.

**Roots.** Both sides read `config.json` on every check and compare realpaths, and always allow the
harness folder. `allowed_roots` leaves that folder out, so agents never work where the probe sweeps.
`roots add` refuses `/`, the home folder, and any folder equal to, holding or inside a data folder. A
too-wide root already in the file makes both sides refuse every path until it is removed.

## Bridge and jobs

**Threads.** A `ThreadingHTTPServer` on `127.0.0.1:0` takes calls on daemon threads. Jobs run on
Krita's main thread, woken by a queued Qt signal, which costs nothing while idle where a polling
timer would fire inside `waitForDone` and start a second job (K41). `Jobs.drain` carries the
`job_active` re-entry guard and refuses to run off the main thread.

**A raise in a job.** `_run` fails its op on any `BaseException`. `drain` fails an op it popped but
never finished. `drain_in_slot` swallows and logs anything still escaping, because an exception
escaping a PyQt5 slot, `SystemExit` included, ends Krita with the owner's unsaved work.

**What a raise proves.** `jobs.stated` turns a `BridgeError` into `details.outcome`, in this order:
1. an explicit value stands;
2. retryable, or `rollback_verified: true`, is `not_applied`;
3. a read, or a bounded op before its marker, is `not_applied`;
4. anything else is `uncertain`.

An unexpected exception is always `uncertain`, and so is a failure `drain` makes up for an op that
never finished. A change counter proves nothing either way: `history.move` calls `before_change()`
during confirmed rollbacks and reversed steps.

**The marker.** `Call.mark()` goes by hand before an op's first change of any kind, on each path:
document, protection state, file or registration. The window-wide brush is not a change here, because
a stroke sets it before its marker. `move()` takes it as a callback that only `history.step` passes,
because a rollback is already past its own op's marker.

| Op | First change |
|---|---|
| `document.open` | the working folder, or `port.open` for a read-only open |
| `document.create` | `port.create` |
| `document.close` | dropping a pending save |
| `document.save` | making the folder |
| `document.save_finish` | clearing the pending save |
| `protection.set` | writing the handle's state |
| `selection.set`, `layer.create`, `paint.stroke` | `before_change` |
| `layer.update` | `before_change`, or `port.activate` for `active` alone |
| `history.step` | inside `move()`, past its `FOREIGN` return |

**Every op has a class.** `READS` (9) change nothing. `BOUNDED` (11) carry a marker, and a test holds
them equal to the mutating tools' ops and `document.save_finish`. `harness.*` has no marker, so a
raise from one proves nothing, and the test pins each by name so no tool op hides under the prefix.
An op in no class is `uncertain` too, so a new op that forgets its class fails safe.

**Failures that never reach `_run`** state their own outcome where `Jobs` finishes them. A conflict,
an unknown op, a taken `operation_id`, a cancel and a stop never ran, so they are `not_applied`.

**A verified cleanup** reports through `errors.cleaned`, the one writer of `rollback_verified` for a
cleanup, which also clears `retryable` when something stayed. `files.remove` checks that nothing is
left, and `files.unmake` that no folder of ours stays; a folder something else has filled is no longer
ours to remove. A rollback writes the key itself.

**A result must survive `json.dumps(allow_nan=False)`.** It is stored as that snapshot, and an error
body that cannot be sent becomes a plain `INTERNAL_ERROR`, so a bad result fails rather than loops.

**SIGPIPE.** Krita's embedded Python leaves it at its default, so a write to a socket whose client
has gone kills Krita with no crash report. `BridgeHTTPServer.get_request` sets `SO_NOSIGPIPE`
(Darwin's 0x1022, which Python does not name) on every connection. On Linux the bridge would need
its own guard.

**Shutdown.** On `notifier().applicationClosing` it stops accepting, fails queued jobs with retryable
`CANCELLED`, and stops the server, all before Python is finalised (K48). The Notifier must be
activated first, or the signal never fires. `shutdown()` runs only while the serve thread lives,
because it would otherwise wait forever on Python 3.13.

**Logging.** `log.py` redacts the token from formatted text. A client that left before its reply is
logged at debug, so polls that time out during a long call do not flood the log.

## Registry, lease and document state

`bridge_core/registry.py` holds one `Handle` per open document: a random `doc-` id, a strong
reference to the wrapper (K6), `owned`, `mode` (`new`, `working_copy`, `read_only`), `dirty`,
`unsafe`, `lease`, paths and hashes, `protected`, `allowed_mask`, the flags, the ledger, any
pending save and the last verified save's `saved_state`. `sync()` matches wrappers by `==` (libkis compares by document), prunes documents that
are gone, and gives the owner's documents `read_only` handles.

**`guarded()` runs in one order:** the job-start refusal (a modal dialog or several windows), the
lookup, `DOCUMENT_READ_ONLY`, `DOCUMENT_UNSAFE`, the lease, the handler. The job-start refusal comes
only at the start, because Krita's own busy dialog inside a job is expected (K41).

**The lease.** The first server process to mutate a document holds it, by `{pid, started_at}`; a
create is that first mutation. Mutations from another live process answer `DOCUMENT_IN_USE`. Reads
stay open. It passes on only once the holder is gone, which `ps` confirms, with `LC_ALL=C TZ=UTC` so
both sides format start times alike. Serialising jobs alone would not stop two agents interleaving
"set selection, then paint".

**Dirty.** A document is dirty after any bridge mutation until its next verified save, except
`krita_protection_set` and a `krita_layer_update` that only sets `active`. `Handle.before_change()`
marks it before a handler's first libkis mutation, so an exception afterwards leaves it dirty, and
stamps `changed_at`. It also announces the change with a low-priority floating message, which never
raises and never fails a call. `Handle.lost()` seals the ledger and marks the document unsafe.

**Krita's flag.** Krita keeps its own modified flag, which list and inspect report as
`krita_modified` beside `dirty`. It follows Krita's undo stack, clean at the open or the create:
every undo step sets it, an undo back to the open clears it, and no export clears it (K45). So after
a verified save `dirty` is false and `krita_modified` stays true. A property write through libkis
(K22) is no undo step and leaves it clear while `dirty` is set; a change made by hand sets it alone.
The bridge reads it and never clears it, except in the close itself. `doctor`'s unsaved count and
the restart rule read it too, so a saved working copy counts as unsaved until it closes.

## Documents

**Open.** `opening.py` runs a fixed order: the argument rules and the roots; the working folder and
the copy, or the read-only hash; `port.open`; the show step (`addView`, under the core's cleanup); the
colour space; the shown frame; K46; the tree; the editable lists; the baseline id; registering it,
last. A failure closes the document and removes the copy and any folder the open made, each checked,
so an ordinary refusal such as a wrong hash reads `not_applied`. A document that cannot be closed
after a failure stays owned and unsafe rather than stranded, and the failure reads `uncertain`. Editable lists are tied to the
format: ids for KRA, whose layer ids persist (K39), names for ORA and PNG, whose ids are new at every
open. Only RGBA / U8 opens; any RGB profile is accepted.

**Create.** `Krita.createDocument` makes an opaque white "Background" layer, so the plugin replaces it
with a new paint layer through `Node.setChildNodes`, which pushes no undo step, and checks the layer's
opacity, its alpha and that it is active.

**The close.** `refuse` answers `DOCUMENT_DIRTY` while `dirty` is set, and while Krita holds the
document modified unless it still matches its last verified save: `saving.matches_saved` reads the
composite, then the tree's nodes, then each pixel range that save compared, and stops at the first
difference. The save takes that state from its own read, so a hand change before its finish is
caught too. Both refusals name `dirty` and `krita_modified`, and come before anything changes.
`port.close` then clears Krita's flag, so Krita never asks: it is reached only under `discard`, or
when nothing would be lost. A hand change to what no save compares, such as guides, is not seen.
Comparing an 8192² working copy with eight 4096² layers took 0.4 s.

**The settled close.** On Krita 5.3.4.1, closing a document within about half a second of a selection
change crashes in `KisNodeModel::processUpdateQueue`, a null pointer from the layer docker's update
timer. A close of the document in front always waits `SETTLE_S` (0.5 s), one behind only within
that long of a change, with user input held back. It is why a create and close cycle costs about
700 ms, and it is upstream's bug (see the backlog).

**`baseline_untouched`.** The source's stat, ctime included, is taken before its hash at open; a later
save or close compares the stat and hashes only if it moved. A whole-file hash costs about 0.4 s per
GB inside Krita.

## Reads, and K46

**K46.** When a selection mask is the view's current node, Krita can draw it as an overlay into the
image. `nodes.unmasked` picks the node to activate, and `nodes.unmasked_view` brings an agent's own
document forward, activates, confirms and restores. An owner's document in that state is refused with
`DOCUMENT_READ_ONLY` (`reason: selection_mask_active`) and left alone. Every other read touches no
view. Inspect reads no composite, so it never switches. With marching ants, Krita's default display,
no overlay enters the bytes, so the probe measures the overlay rather than checking it, and the guard
stays for the mask display mode.

**Capture.** Resample, then composite: a checker composited first averages to flat grey at small
scales. The filters are Pillow's `nearest`, `box`, `bilinear`, `hamming`, `bicubic` and `lanczos`,
for previews too; `imaging.FILTERS` is the list, and a test holds every `filter` enum to it. Scale 1
is native, and `background` or `greyscale` there is refused. `max_px` bounds the image;
`limits.capture_source_pixels` (8192²) bounds the area read. A layer capture is that layer's own
paint device (K12), and is paint layers only. A larger image goes by path with a 1600 px inline
preview. Captures are `op-<id>` files, found before they are made, so `krita_operation_get` can
rebuild a receipt.

**Sample.** RGBA, hex, L\*a\*b\* and L\*C\*h, with an alpha-weighted disc for `radius`. Colour maths
is sRGB only (`sRGB-elle-V2-srgbtrc.icc`, `sRGB built-in`): the document's profile for a composite,
the layer's own for a layer. Otherwise those fields are null.

**Frames.** Reads refuse an animated document away from frame 0, and never move the owner's timeline.
A still document whose timeline was scrubbed shows the same picture at every frame, and reads.

**Resources.** `preset_id` is the resource's file name (K36). The fingerprint is SHA-256 of `toXML()`
canonicalised with C14N 2.0, leaving out what every stroke sets: opacity, flow, blend, eraser, and the
tip's diameter, scale and angle. The raw XML digest changed at every restart measured and the canonical
one held, on 5.3.4.1; nothing re-checks that now, because a probe run lists and paints within one
Krita session. If it stopped holding, an agent's `preset_sha256` from an earlier session would answer
`RESOURCE_HASH_MISMATCH`.

## Protection, selections and masks

**Protection** is plugin state, shared by every client, and never touches Krita's lock flags.
`protected_layer_ids` is the whole set, so it must keep every protected layer that still exists. The
allowed mask lives in memory on the handle, one byte per canvas pixel, 0 or 255, with its summary.
Tightening is checked over whole buffers with `int.from_bytes` (`new & ~cur`). Each call seals the
ledger, so history never crosses a protection change.

**Selections.** `recipe()` fixes the order: shape, grow, shrink, feather, invert, combine, commit.
The plugin builds on `duplicate()` or a fresh `Selection()`, never the live one (K23), and commits
with `Document.setSelection`, one undo step (K8). `subtract` and `intersect` with no selection are
refused. Shapes off the canvas are refused, never clipped.

**Masks.** The server samples NumPy masks at 4 × 4 sub-pixel centres in bands of 64 rows, polygons
even-odd with edges half-open in y; antialiased values are `(k·255 + 8) // 16`, and binary allowed
masks take k ≥ 8. The plugin takes a mask straight after its argument checks, before any other
refusal, and the server removes a request's masks after any final outcome, never while it is pending.

**The inset.** A polygon or ellipse selection is antialiased and the allowed mask is binary, so a
selection on the mask's own edge paints pixels the mask forbids: 58 px with a soft brush and 67 with a
scatter brush, each refused and rolled back. A selection 1 px inside changes none. The instructions
say so.

## The verification core

`bridge_core/verification.py` is pure. Every appearance change and every stroke goes through it.

**Reach.** `reach(tree, effects, target)` lists every node that can carry a change past the target's
bounds: a filter, transform or colorize mask or a filter layer on the target, inside it or on an
ancestor; a layer style there; a blend of `copy`, `destination-in` or `destination-atop` on the target
or its subtree (`SPREADING_BLENDS`, the only ones that composite past a layer's extent); a layer type
whose bounds are derived; a filter layer anywhere in a later sibling's subtree, of the target or of
an ancestor; a clone of either, or with no source Krita names. Any of these refuses region scope, by
reason, unless `verify: "full"` is asked. It over-refuses on purpose: a per-pixel filter cannot
spread a change, and a filter layer inside a closed group above cannot see below it.

**Scope and read.** `scope` is the union of the exact bounds of the target and its descendants,
clipped to the canvas, or the canvas for `full`. The projection is refreshed before the before-read,
so a write elsewhere that Krita has not drawn yet (K42) is not read as this change. `read` takes the
composite inside `unmasked_view`.

**Check.** `check` works in bands of 2²⁰ pixels. Per pixel it makes a flags byte (1 changed, 2
outside the mask, 4 alpha changed) from `int.from_bytes` XORs over strided slices and `translate`
tables, and counts with `translate` and `count`: whole-buffer byte operations, never per-pixel Python.
The checks are byte-exact, so a colour change under alpha 0 counts (see the backlog).

**The plugin computes the counts, the server makes the images,** so a second server that shares a
retry still gets the counts. A pass sends before and after, up to 2048²; a refusal sends before and
the flags. The diff draws offending pixels red over the scope as it was, faded toward white, at most
1024 px long, block-reduced so none vanishes, and goes inline only under the size bound.

**`krita_layer_update`.** Only values that differ are written; the blend first, then the rest in a
fixed order, then a refresh (K42). `set_properties` pushes no undo step (K22), so a rollback restores
old values and undoes the blend through `history.move`, then confirms the tree and the scope.
`history.unconfirmed(handle, changing)` wraps the change and its rollback: the op's own `BridgeError`
passes through, and any other raise marks the document lost. The write-nothing case does not arm it.

## Painting

`bridge_core/painting.py`, with `brushes.py` for the reach and `krita_adapter/painting.py` for the
libkis calls. One call is exactly one Krita stroke and one undo step.

**The order inside the job.** Refusals, in order: colour space; the target (protected, type and space,
any local selection mask, since libkis does not say which is active); on-curve points past the canvas
grown by half the size; the preset by file id, with the 5 nearest; the listed fingerprint; cumulative
undo; region reach. Then, with the view in front (K2, K9): the brush set in K3's order (preset,
then size, opacity, flow, blend, eraser, alpha lock, rotation, colour) and read back, `paintAbility()`,
the reach from the effective preset's XML, R and the ring, the refusals over the scope,
`OUTSIDE_ALLOWED_MASK` over R, a refresh, the before-read, the brush read again, the fingerprint,
`before_change()`, `paint_path`.

**Stateless brushes.** The brush is window-wide (K3), so every call sets all of it and reports what
Krita applied. A stroke writes `OpacityValue`, `FlowValue` and the tip's size fields into the active
preset, which is why the fingerprint leaves them out. The bridge remembers its own first activations
for the Krita session, the digest a preset had before by the digest it has after, so a preset Krita
fills in on first load keeps its listed hash and any other change still mismatches.

**Two bounds.** `changed_bounds_px` is what changed on the canvas, inside it always; a full-scope
stroke widens it only when the layer's *clipped* bounds leave what was read, so old overhang costs
nothing. `layer_bounds_px` is Krita's unclipped extent after the stroke, or null for an empty layer.
Its `x` and `y` take any integer, because a dab past the canvas is kept. A stroke wholly past the
canvas changes nothing on it: `changed_bounds_px` is null and history stops there. Like the diff it
comes from, `changed_bounds_px` counts every byte, and Krita can write colour under alpha 0 past a
selection's edge, so it can run a dab's box past the selection while no visible paint does. The
probe holds alpha to the selection.

**Mirror and wrap-around** go off for the stroke and back on in a `finally`, each noted before it is
turned off (K2, K47).

**R, the margin and the ring.** R is the path's bounds grown by `max(32, size × (e + 2e·s) + 2)`,
where `e` is 0.5 for a round auto tip and √2⁄2 for square and image tips, and `s` is the effective
scatter. Scatter moves a dab by up to its strength times the dab mask's width and height, which a
rotated tip stretches to 2e × size, and the mask's whole pixels add up to 2 px. Region scope needs
the pixel engine (`paintbrush`) and a readable tip and scatter; the parse fails closed. Full scope
widens an unnamed reach instead: an unknown tip as √2⁄2, an unknown scatter as 5. R′, one ring wider,
is where the target is read, so a dab outside R inside the layer's old bounds is seen.

**The margin rests on two measured assumptions.** Region scope's last line of defence is this model:
a change beyond R′ inside the target's old bounds is read nowhere.
- (a) The pixel engine displaces dabs by scatter alone. It is held by about 50 stock presets measured
  at 0.9.0, and by the ring, which caught one real scatter underestimate there.
- (b) An image tip fits a size × size square. Krita sizes an image tip by its longer side. The probe
  re-measures the most non-square stock tip every run: `y) Texture Wood Fiber`, 7 × 32 px, reached
  0.52 × size against a margin of 0.74 × size at 60 px.

**The checks.** The composite; every protected paint layer's bounds and hash, over its bounds ∩ the
scope; in region scope, the target's diff inside R and its bounds inside its old bounds ∪ unclipped
R′. A protected layer that shares no pixel with the scope is skipped once its bounds are compared.

**Rollback.** One undo through `history.move`, or, after a raise, a re-read and an undo only when the
label and a witness built from the re-read match. It is confirmed by the re-read, `same()` and the
bounds; otherwise the document is unsafe and the call `ROLLBACK_FAILED`. It is never retryable, and a
`BaseException` marks the document unsafe through `history.unconfirmed`. `protected_pixels_changed`
is `null` when no confirmed undo brought back what it is counted against.

**The input gate.** Phase 1 always paints with `Node.paintPath` at pressure 1 (K4), even on a build
with `paintPolylineStroke`, because that branch cannot be tested on released Krita. The server refuses
before the journal, in order: argument errors; `smooth` basic or stabilizer, `antialias: false`, the
eraser, the input gate; numbers that are not finite; a stroke under half a pixel, since Krita paints
no dab for it. `smooth: catmull_rom` turns the points into exact cubics on the server.

## The undo ledger and history

`bridge_core/ledger.py` tracks what the bridge pushed: `Step{op, operation_id, label, before, after,
region, witness}` and `Ledger{steps, applied, floor, redo, bottom}`.

- `push` truncates the redo tail (K43). `rolled_back` pops a rollback's step and offers no redo, so
  Krita's redo of a rolled-back stroke, which it does offer, is refused.
- `seal` stops history below a step the bridge cannot name: protection changes, harness ops that
  push, a mutation that raised, a stroke that changed no pixel (`history_sealed` on its receipt).
- `bottom` follows Krita's `undoStackLimit`, default 200 (`UNDO_LIMIT_DEFAULT`), measured to be exactly
  what Krita keeps.
- `undo_available = applied − max(floor, bottom)`.

**A step's identity.** A step's fingerprint is `(id, blend mode)` for each node, without the root's
selection masks, and the SHA-256 of the selection's canvas-clipped bounds and bytes. Labels do not
identify a step, and a stroke's fingerprint does not either, so a stroke carries a **witness**: the
target's own bytes over its diff, hashed before and after, checked before and after every move.

**`history.move`** undoes or redoes one step with the document's view in front (K7): posted events
flushed, the top label naming the step and the fingerprint matching, then the opposite label and
fingerprint after. An unconfirmed move is reversed once, otherwise the document is unsafe. A raise
before Krita was asked is `REVERSED`, retryable as the first step; after it, `LOST`. `STOPPED` maps
each stop to its receipt value: `not_the_bridges_step`, `unconfirmed`, `document_unsafe`.

**Labels are English.** `history.LABELS` holds what Krita's actions read on 5.3.4 in English: "Add
Layer", "Composition Mode Change", "Scripted Brush Stroke", and an unnamed step for a selection. They
are read only by `move`, so on a localised Krita ordinary calls complete, `krita_history_step`
refuses every step as not the bridge's, and any change that needs a rollback ends in
`ROLLBACK_FAILED` and an unsafe document. English is a requirement until the backlog's item lands.

**Labels are read after a flush,** because straight after a push they can be stale (1 or 2 of 7 reads,
measured), with the view in front. Selection steps have an empty label and Krita keeps Redo enabled
as "Redo " with nothing to redo, so they are confirmed by state alone.

## Previews and the lazy baseline

**The lazy baseline.** The open mints `baseline_id` and writes nothing: a baseline written at open
cost 4.7–5.2 s and 268 MB on the 8k master. The server sends `read_baseline: true` only when it holds
no `baselines/<id>.npy`. The plugin then checks the working copy's file still hashes to
`source_sha256`, opens it again without a view, reads its composite and closes it in the same job.
The server adopts the transfer file as the `.npy` and crops it for every later render. A baseline
file that cannot serve is removed, so the retry reads it again. Baselines are `.npy` because a PNG
encode of an 8k master could push a reply past the client's timeout.

**`krita_preview_render`** is one op, `preview.read`, a read with no guard or lease, and `sheets.py`,
which is pure. One sheet per recipe; each sheet carries `image`, `clean_image` (null when no overlay
was drawn), `inline`, `columns`, `rows` and its own `recipe_sha256`. No text is drawn into a sheet.

**Order in a cell:** one resample from the native crop; composite over the background; tint;
greyscale; a snapshot for the clean sheet; the overlays' 1-game-pixel outlines (selection magenta,
allowed mask cyan); the zoom. `integer_zoom` magnifies after, by pixel replication, so nothing
resampled is resampled, and painted art is filtered as the game draws it.

**Geometry.** "Fit" keeps the aspect; an anchor that pushes the image out of its box is refused,
never clipped. A world-unit cell is the union of the anchored images; each anchor lands within half a
pixel of one shared whole-pixel point. Sizes round half up. Bounds: 8 recipes, 8 sources, 4
backgrounds, 4 tints, `integer_zoom` up to 16, a sheet at most 4096 px on its long edge, and at most
2 × 8192² pixels read per call. Each sheet that fits goes inline at full size, in recipe order; the
rest go by path. No preview is returned scaled down.

## The save

Nothing lands unverified, and the document keeps pointing at its own file (K39). The save is two
plugin ops, because the server must decode `mergedimage.png` and Krita has no Pillow.

`document.save` checks the path and the space, and refuses a canvas of more than 8192² pixels,
whatever its shape, with `UNSUPPORTED_CAPABILITY` before writing, since it reads the whole composite twice and every node
unbanded. Inside `unmasked_view` it recomposes the projection, because after a stroke the projection
can differ from a fresh recomposite of the same layers, then `exportImage`s to
`<dir>/.<stem>.<token>.saving<ext>`. `False` is `BUSY`, with nothing left (K45). It reopens the
written file with `reopening.read_file`, shared with the lazy baseline, and compares. A mismatch
removes the file and is `SAVE_VERIFY_FAILED`, with up to 20 mismatches. Otherwise an earlier
unfinished save is dropped, last, so a save that fails leaves it as it was, and the handle keeps a
`Pending` save, which takes over any folders the dropped one made. Each failure past the folder reports its cleanup, and reads `not_applied` only if
nothing of the save stays. An export that moved the document reads `uncertain`, however clean its
file.

**What is compared.** Both formats: size, colour space, the composite. KRA: nodes by id, every `tree`
field (the root's own id changes), and each node's own pixels over the union of both bounds. ORA: nodes
by rank among stored siblings; then name, visibility, blend, edit lock, inherit-alpha, and each
layer's pixels against the live projection. Masks and adjustment layers (`node`), clone, file, vector
and fill types (`type`), `alpha_locked` and rounded opacity are listed in `expected_losses`. A lost
node never excuses a composite difference: a blur filter mask, cropped to the layer's bounds by ORA,
fails the save.

**ORA's opacity.** Krita writes it to six significant digits and truncates on load, so 127 of the 256
values come back one lower. A visible one changes the composite, so that save fails.

`document.save_finish {save_id, merged_sha256, merged_problem}` runs under an operation id derived
from the save's (`finish_operation_id`), so every poll and retry gets the finish's own outcome. It
compares the written file's inode, size and modification time with what the save took, and the server's
`mergedimage.png` hash with the live composite's. It then `os.link`s the file into place and unlinks it,
or, where links fail, checks `lexists` and renames. It clears dirt only if `Handle.changes` is
unchanged, and then keeps what the save compared as the handle's `saved_state`. Its receipt adds
`dirty`, `krita_modified` and `document_path`, the file the live document still points at, since
the export moves neither (K39, K45). A new verified save, a close or a document gone from `sync` drops a save never finished,
and folders the save made go with it, deepest first and only while empty.

The server's `_merged` never raises, so the finish always runs and no hidden file stays. A problem
reading the file goes to the plugin as `merged_problem`, which discards it.

## The server

**`tools/dispatch.py`** checks a journaled call in order: a conflict; a receipt, answered from the
journal; an attempt unknown under another Krita session, checked in `before_send`; otherwise it
journals and sends. The journal line is written inside `before_send`, after the bridge is pinned and
before the POST.

**A raise after dispatch keeps the call's identity.** `journaled` catches it and still records. With
nothing sent it re-raises, and the catch-all's answer is true. With no outcome yet the call is
`uncertain`, with its `operation_id`. A `Done` whose receipt raised goes on as `raw_receipt`, the
bridge's own result in a completed envelope, so one route serves a bad receipt and a missing one.

**`_checked` is the last gate.**
- A result that breaks its contract keeps its `document_id` and `operation_id`, and a completed one
  from a mutating tool becomes `outcome: applied`. "Mutating" is `readOnlyHint: false`.
- The reason names the rule and its path, never jsonschema's message, which quotes the whole instance.
- A mutating failure with no statement gets one: no `operation_id` means it never went out, so it is
  `not_applied`, and an `operation_id` means `uncertain`.

So a retry of a stroke whose receipt was bad keeps failing, now with ids: the journal holds that
receipt, and nothing is painted twice. Applied work the server cannot finish (a selection's mask, a
step's capture) is `applied_failure`: ids kept, never retryable.

**`bridge_client.py`** re-reads `bridge.json` on every call and pins it for that call. It returns
`Done`, `Failed` or `Pending`. A refused connection is retryable; after a send, a lost bridge is
`INTERNAL_ERROR` with `outcome: "uncertain"`.

**Resolvers.** Transfer files become data before a receipt, so a receipt stays a pure function of
the outcome, and `krita_operation_get` can rebuild one. `RECEIPTS` maps each op to
`Known(tool, receipt, resolve, finish)`, and a test holds it complete. Images are found by operation
id before they are made. A second server that took part in a retry gets a null image rather than a
failure, because the first server took the pixels.

**`krita_operation_get`** adds `outcome`, `receipt_valid` and `receipt_problem`, all null while the
call is queued or running. It returns a raw receipt as data, survives one that raises, and settles the
journal on every path. When the bridge cannot answer, because Krita restarted or has gone, a finished
line answers with its own outcome; with no line it stays `uncertain`.

**Serve.** Orphaned baselines are swept on a daemon thread under `CALLS`, with a 2 s budget, so a busy
Krita never delays the client's handshake.

## The CLI

`serve`, `install-plugin`, `roots add|list|remove`, `doctor`, `probe`. `install-plugin` never edits
`kritarc`: enabling the plugin is the owner's step. `doctor` names the first failing step of six, with
its fix: the plugin files installed and current; `kritarc` enables the plugin; Krita running; the
bridge reachable; the protocol and plugin hash; at least one root. Whenever the bridge answers, it
prints Krita's open and unsaved counts, whichever step failed, because that check matters most when
the plugin is stale, and a session reads them before it restarts Krita.

## Testing strategy — six layers, and what each cannot see

| Layer | Runs | Covers | Cannot see |
|---|---|---|---|
| Unit (server) | `verify` | Schemas and examples, argument rules, envelope and errors, roots, journal, client-side dedup, masks, colour maths, preview geometry, the bridge client against a fake bridge, a stdio round trip | Real Krita |
| Unit (plugin core) | `verify`, on 3.10 | HTTP, auth, jobs and re-entry, dedup, registry, protection, the ledger, verification against `tests/fixtures/fake_krita.py` | libkis behaviour |
| Source scans | `verify` | Invariants 1, 6 and 7, by AST | What a name hides at run time |
| Hygiene | `verify` | Private terms and AI attribution | See below |
| Live harness (`probe`) | Whenever a change touches the plugin, the protocol or a Krita-facing tool | Every tool on its own documents through stdio MCP, the six exercises, the budgets | Whether strokes look painted; Krita 6.x; other machines |
| By hand | Recorded in `docs/BACKLOG.md` when undone | What a person must see | Anything not written down |

The adapter has no unit tests: libkis is out of reach, so logic with branches moved into the core
(`nodes.unmasked`), and the probe reaches the rest.

**`verify`** runs `format`, `lint`, `types`, `tests`, `plugin-tests` and `hygiene`, each whatever the
others do. `types` runs mypy three times, strict on 3.12 over `src`, `scripts` and `tests`, and as
3.10 over the plugin and `tests/plugin`, because mypy takes packages or files in one run. A stage
that cannot start fails on its own. There is no CI: the session holds the gate.

**Hygiene.** `scripts/hygiene.py` reads one word per line from `~/.config/hygiene/terms.txt`, outside
every repository, so no repository holds the terms or their hashes. A missing file fails, so a new
machine cannot pass by accident; an empty file is a valid answer. It checks the contents and paths of
tracked, untracked and staged text files, and every commit message, the draft included. Lines are NFC
normalised and split into runs of letters, digits and combining marks, with the camel-case words and
digit groups inside each. A hit names the file and line, never the term. No test can read the owner's
list: an autouse fixture points it at a missing file. **It cannot see** images and binaries or their
metadata, a term joined inside one lowercase run, attribution in files (messages only), or a tool
missing from its nine names.

**Falsification.** Each new check is broken once, watched fail at its own step, and restored; a
check that already exists is not falsified again.

**The probe's harness.** It checks the plugin hash first, then health, stdio, H4 idle and the runtime
facts, then its document checks, which run only when no Krita document has unsaved changes. It works
in `harness/`, sweeps at start and end, and closes only what it opened. It reads the brush state from
a document in the harness folder and writes it back: a created document has no path, so that read
fails, and a driver must stop if it does. A dialog open in Krita refuses calls that read or change a
document, and fails the checks it overlaps. The stock presets `b) Basic-2 Opacity`,
`b) Airbrush Soft`, `y) Texture Spray` and `y) Texture Wood Fiber` must be listed.

**N-04's limit.** `probe/writes.py` lists the data directory, strictly, by `DATA_FILES`, and five other
places for new names that look like ours (the cwd, the home folder, Krita's temp folder,
`~/Library/Application Support`, `~/Library/Preferences`), because other processes write in all of
them. It sees what stays after a run, not a file that came and went, and outside the data directory
only those names. `~/Desktop` and `~/Downloads` are left out, because listing them can raise a
permission prompt.

**What the probe measures and does not gate.** A MEASURED line stays only if something rests on it
and no check would notice it changing. The 23 lines:

| Lines | Why they stay |
|---|---|
| Krita's runtime; 11 stage times | The run's condition, and where its time goes |
| `Node.paintPolylineStroke` | The one reader of Phase 6's switch |
| An active selection mask's overlay | Why K46's guard is measured, not checked |
| `setActiveNode` on the global selection's mask | Why K46's global branch is unit-tested only |
| The tall tip against R's margin | Assumption (b) of the margin model |
| N-01 and N-09 opening the master, and their corner-to-corner strokes | Costs no budget gates; Krita's memory is on the backlog |
| Retention after N-01; the journal after N-01 | Growth watches behind backlog items |
| H4's long save | A save has no budget |

A line can also appear as a skip: "paths outside every root" when a root covers them, or the tall tip
when its preset is missing. The journal line takes the fastest of five lookups, because one read in
the probe's large process can carry a collection of its whole heap, and the week scales what it
measures.

**The six exercises** in `probe/acceptance.py` run every time: a selected repair at two views; a
detail that keeps the base and every alpha byte; soft and scatter brushes beside a boundary; undo and
retry of a batch; previews from explicit recipes; a `.kra` saved, closed and reopened.

**Hypotheses.**

| Id | Hypothesis | Outcome at 0.16.0 |
|---|---|---|
| H1 | An agent fixes a real review defect better than a scripted correction | Open: the trial, after the round |
| H2 | Flat `paintPath` strokes with stock presets read as hand-painted | Passed by hand, 0.14.0: five of six usable; the taper is round 2's E1 |
| H3 | Codex shows MCP images to the model | Holds: its agent described a known pattern from the image alone, 0.14.0 and 0.15.0 |
| H4 | The bridge answers while idle and recovers after a blocking call | Holds: idle p95 under 50 ms; a 5 s gradient save, chosen by the owner against the 20 s target, measured, with a queued retry run once |
| H5 | The plugin runs on 5.3.x and 6.0.x | Backlog |
| H6 | Requested colours paint exactly | Holds, in the probe |
| H7 | Claude Code can do the repaints | Open: H1's other half |
| H8 | Verification catches every leak | Holds, in the probe, in both scopes |
| H9 | Profiles keep projects apart | Phase 2 |

**Budgets.**

| Id | Requirement | Budget | Measured |
|---|---|---|---|
| N-01 | A stroke, 200 points, 40 px brush, 2000² with 20 protected layers | p95 < 1.5 s | 0.10 s; 0.09 s under a canvas-wide selection |
| N-02 | `preview_render`, two recipes, 2000² master | p95 < 2.0 s | 0.33 s; first render 0.73 s |
| N-03 | Idle CPU added by the plugin | < 1% | 0.0% in `top`; the look in Activity Monitor is on the backlog |
| N-04 | Nothing written outside the roots, the data dir and Krita's own files | 0 | 0, within its limit above |
| N-05 | Plugin unchanged on 5.3.x and 6.0.x | Both | Backlog |
| N-06 | A hard round brush paints the requested colour exactly | Equal bytes | Holds |
| N-07 | A stroke lands alike at two zoom, pan and rotation settings | Equal hashes | Holds |
| N-08 | A soft or scatter brush beside a binary selection changes nothing outside it | 0 | Holds, in both scopes |
| N-09 | A stroke, 200 points, 40 px brush, 8192² with 30 protected layers | p95 < 3 s | 0.23 s; 0.28 s under a canvas-wide selection |

N-01, N-02 and N-09 are checks in the probe, which fail rather than warn. A miss stops the session
for the owner's call, and no budget is relaxed to pass.

## Packaging

The server runs as `uv run --project <repo> krita-art-mcp serve`. There is no PyPI package and no app
bundle. `mcp` is pinned to 2.3.x, where `FastMCP` is `MCPServer` and `mcp.server.fastmcp` raises;
moving past it is a decision. The plugin uses Python 3.10 syntax, the standard library and the PyQt
shim, and ships with the repository; the runtime is Krita's bundled Python 3.13 with PyQt5 5.15.11.
`uv_build` and the `src/` layout build the package, and schemas are package data.

## Deliberate decisions

These span subsystems. A decision about one subsystem is in its section.

- **Verification lives in the plugin, in the stroke's own job.** In the server, a second job could
  land between a stroke and its rollback, and every protected layer would cross the bridge.
- **Document state lives in the plugin's registry.** Each client starts its own server, so state in
  a server would split between them and vanish on its restart.
- **Rollback is native undo, never pixels written back.** A snapshot restore would break invariant
  1, and native undo keeps Krita's own history true.
- **Pixels cross as files.** zlib and base64 inside JSON would run inside Krita under the GIL, about
  680 MB per stroke on an 8k master with 30 protected layers.
- **Refuse, never adjust.** Coordinates are never clamped, colours never normalised, resources never
  substituted, and canvases never grown. When Krita adjusts a value, the receipt reports it.
- **Protection is on by default.** Every layer present at open is protected, because the tool set
  shapes behaviour: an agent adds a layer of its own before it can paint.
- **Brush state is set per call, never held.** A persistent brush tool would hide window-wide state
  the owner shares (K3).
- **One plugin, on Krita's own Python.** The bridge needs nothing installed into Krita. The cost is
  hand-written ops and a stdlib HTTP server.
- **Harness ops ship in the plugin.** A closed namespace, gated to its own folder, beats a second
  extension to install and keep current.

## Known debt, deliberately deferred

Each has its detail in `docs/BACKLOG.md`, or in `docs/spec/SESSIONS.md` where round 2 takes it up.

- The save reads whole canvases unbanded, so it stops at 8192² pixels.
- Three verified-mutation sequences are hand-rolled, and the save has a ladder of its own.
- Six argument rules are written on both sides with no parity test.
- The journal is permanent and unbounded.
- A Krita crash mid-save leaves a hidden file nothing sweeps.
- Labels are English; region scope is the pixel engine only; filters are classed by type.
- Selection steps are confirmed by state alone.
- Erasing, a single dab and antialiasing off are refused.
- Not-finite numbers reach the plugin in some tools' inputs.
- The global-mask branch of K46, layer styles and the mirror restore are held by unit tests or by
  nothing live.

## Reference: the ids the code cites

Krita sources are at tag `v6.0.4.1`, whose tree builds 5.3.4.1, unless noted. Facts the code does not
cite stay in the PDD, in git history.

| Id | Fact | Source |
|---|---|---|
| K2 | Paint calls take brush, colours, opacity, blend, alpha lock and mirror settings from the active view's canvas resources | `libs/libkis/PaintingResources.cpp:36`; `libs/ui/tool/kis_resources_snapshot.cpp:135-156` |
| K3 | Those resources are window-wide. `setCurrentBrushPreset` does nothing if the preset is already current. Activating a preset resets the composite op | `View.sip`; `libs/ui/kis_paintop_box.cc:621-651,731-732` |
| K4 | Each paint call is one stroke, "Scripted Brush Stroke"; `paintPath` gives every point pressure 1.0 | `libs/ui/tool/kis_figure_painting_tool_helper.cpp:41,94-98`; `libs/libkis/PaintingResources.cpp:61` |
| K5 | Painting is asynchronous; `Document.waitForDone()` waits | `kis_figure_painting_tool_helper.cpp:41,96-98`; `libs/libkis/Document.cpp:824-829` |
| K6 | `openDocument` returns an owning wrapper and adds no view; `Window.addView` hands ownership to Krita | `libs/libkis/Document.cpp:87-92`; `libs/libkis/Window.cpp:82-92` |
| K7 | Undo and redo act on the active view's document (`edit_undo`, `edit_redo`) | `libs/ui/KisMainWindow.cpp:1538-1548,3063` |
| K8 | `Document.setSelection` pushes an undo command | `libs/libkis/Document.cpp:361-371` |
| K9 | `paintLine` takes integers, `paintPath` floats; `paintAbility()` says `PAINT` for any node with a paint device, and dereferences the active view unchecked | `Node.sip:85-90`; `libs/libkis/Node.cpp:830-863` |
| K10 | Painting is confined by the global selection unless the target has an active local selection mask | `kis_resources_snapshot.cpp:312-334`; `libs/image/kis_layer.cc:509-522` |
| K11 | `Selection.setPixelData` reads w×h bytes, one per pixel | `libs/libkis/Selection.h:213-228` |
| K12 | `Document.pixelData` reads the projection, B, G, R, A for integer RGBA; `Node.pixelData` is the raw paint device | `libs/libkis/Document.cpp:472-484` |
| K14 | `setBatchmode` keeps dialogs away around opens, saves and exports; `exportImage` is synchronous | `libs/libkis/Krita.cpp:129-137`; `Document.cpp:112-116,519-527` |
| K18 | `ManagedColor` takes components in Krita's channel order | `ManagedColor.sip` |
| K21 | `setCurrentBlendingMode` stores any string; an unknown id silently paints `normal` | `libs/libkis/View.cpp:235-239`; `libs/pigment/KoColorSpace.cpp:371-386` |
| K22 | Undo steps: paint calls, `setSelection`, `addChildNode`, `setBlendingMode`. Not: name, opacity, visible, inherit-alpha, alpha lock | `libs/libkis/Node.cpp` |
| K23 | `Document.selection()` wraps the live selection, and combine calls change it in place | `libs/libkis/Document.cpp:353-359`; `libs/libkis/Selection.cpp:207-295` |
| K29 | `Notifier` has no per-edit signal, and libkis no undo grouping | `libs/libkis/Notifier.h:41-106` |
| K30 | Master (6.1 / 5.4 pre-alpha) adds `Node.paintPolylineStroke` with per-point input | master `libs/libkis/Node.h:594-608`, at `b5b6dd3`, 2026-10-22 |
| K36 | `Resource` exposes no id or hash; `Preset(resource).toXML()` returns the settings | `Resource.sip`; `libs/libkis/Preset.h:37-62` |
| K37 | With eraser on, the global alpha lock is ignored | `kis_resources_snapshot.cpp:154-156` |
| K39 | `saveAs` repoints the document; `exportImage` does not. KRA keeps layer UUIDs | `libs/libkis/Document.cpp:519-527,597-607` |
| K40 | The `krita` bindings never release the GIL during a call | `cmake/modules/SIPMacros.cmake:154-158`; `plugins/extensions/pykrita/sip/` |
| K41 | `waitForDone` runs `processEvents` for 1 s, then a modal dialog; timers and queued signals fire inside both | `libs/image/KisBusyWaitBroker.cpp:45-63`; `libs/ui/dialogs/kis_delayed_save_dialog.cpp:87-112` |
| K42 | `setOpacity`, `setVisible` and `setInheritAlpha` do not mark the projection dirty | `libs/libkis/Node.cpp:402,445,537` |
| K43 | An undone command stays above the index until the next push, so redo re-applies it | `libs/command/kundo2stack.cpp:740-741` |
| K44 | Scatter runs 0 to 5, offsetting each dab by up to strength × diameter per axis | `plugins/paintops/libpaintop/KisScatterOption.cpp:39-46` |
| K45 | `exportImage` runs the normal export filter, never clears the modified flag, and returns false while autosave holds the lock | `libs/libkis/Document.cpp:519-526`; `libs/ui/KisDocument.cpp:1334-1358` |
| K46 | A selection mask that is the current node is drawn as an overlay into the image; `exportImage` saves the live image | `libs/ui/kis_selection_decoration.cc:106-116`; `libs/ui/KisDocument.cpp:1417-1419` |
| K47 | Scripted strokes honour wrap-around mode | `libs/ui/tool/strokes/freehand_stroke.cpp:110,296-303` |
| K48 | `aboutToQuit` fires after documents and windows close; pykrita then finalises Python | `libs/libkis/Notifier.cpp:23` |
| C1 | `mcp` 2.3.0: `FastMCP` is `MCPServer`; `Image` takes no `_meta`; a raised exception yields only "Error executing tool X" | Probed 2026-10-22 |
| C2 | Codex passes MCP images to image-capable models and honours `codex/imageDetail` | openai/codex `codex-rs/core/src/mcp_tool_call.rs` |
| C4 | Claude Code: output limit 25,000 tokens; instructions and descriptions truncated at 4,096 characters | code.claude.com/docs/en/mcp |
| C5 | Codex closes the stdio transport when one message exceeds 8 MiB | `codex-rs/rmcp-client/src/bounded_stdio_transport.rs:22,63-65` |

**Measured on Krita 5.3.4.1, macOS, Apple Silicon.** Checks hold most of these, and the rest are why
the code is shaped as it is.
- `createDocument` makes an opaque white "Background"; a new document's profile is
  `sRGB-elle-V2-srgbtrc.icc`.
- A PNG opens as one layer named "Background". Krita's ORA loader sets the layer offset. A fresh open
  is not marked modified, and has no selection.
- Krita's flag, measured on PNG, KRA and ORA working copies: a layer, a stroke, a selection and a
  `harness.add_node` set it; a view or opacity change and every save, verified, refused or failed,
  leave it; an undo back to the open clears it. A created document is not modified.
- After a verified save, a tab close, Close All and quit each ask to save. Krita's own Save on a KRA
  working copy writes it with a `~` backup beside it and clears the flag, `dirty` stays, and the
  lazy baseline then answers `SOURCE_HASH_MISMATCH`. On a PNG working copy, Save opens the PNG
  export dialog, which warns that the image loses information.
- `addChildNode` puts a node on top when `above_id` is `None`, and makes it active.
- `setActiveNode` on the global selection's own mask leaves the previous layer active.
- Preset XML: the raw digest changed at every restart, across six runs; the canonical one held. No
  run repeats this.
- 144 stock presets, 21 RGBA / U8 profiles, 13 palettes.
- A 20 × 16 rect grown, shrunk and feathered by 3 lands on {17, 11, 26, 22}, {23, 17, 14, 10} and
  {17, 11, 26, 22}.
- `eraserMode()` read false after `setEraserMode(True)` with every preset tried.
- No dab without length: one point, two equal points and 0.01 px painted nothing; 0.5 px painted one.
- Pan is reachable through the canvas controller's scroll bars, zoom and rotation through `Canvas`.
- Krita's memory grows across large opens and saves, to 2 GB or more in a probe run; a restart resets
  it. A Krita holding 87 documents ran document ops about three times slower, and left the paint
  benchmarks, the preview benchmark and H4 idle alone.

## Baseline (v0.19.0)

Taken on 2026-11-03 on Krita 5.3.4.1, macOS, Apple Silicon, on a Krita restarted that session, with
**0 documents open**. The probe prints the open-document count beside its time, because document ops
depend on it: 87 open documents cost about 50 s more.

| Check | Expected |
|---|---|
| `uv run scripts/verify.py` | 6 stages, all PASS |
| Server tests (3.12) | 742 passed, 0 skipped |
| Plugin-core tests (3.10) | 791 passed, 0 skipped |
| `uv run krita-art-mcp probe` | 147 PASS, 0 FAIL, 24 MEASURED; about 125 s |
| `uv run krita-art-mcp doctor` | 6 steps, all PASS, with a root allowed |
| Registered tools | 19 |
| Schema files | 19 |
| Error codes | 30 |
| Bridge ops | 31 |
| Bridge protocol; `api_version` | 1; 0.3.0 |
| Server instructions | 3,970 of 4,096 characters |
| CLI commands | 5 |

A documentation or refactoring change should not move any of these. If one moves, that is the
finding.
