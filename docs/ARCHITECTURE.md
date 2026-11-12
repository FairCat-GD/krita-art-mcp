# krita-art-mcp — architecture, as built

This is the system as it stands at 0.28.0, in round 2, on the Phase 1 round 1 built. Every session
keeps it true, in the same commit as the change. Each section stands on its own: a session reads
the overview, the invariants and the baseline, then only the sections its work touches.
`docs/USER-GUIDE.md` is the same system from the user's side.

## Overview

krita-art-mcp lets an AI agent paint in the owner's running Krita through Krita's own brush engine.
It is for painted (non-pixel) 2D game art, run by one developer on macOS with Krita 5.3.x. The core
loop: open a working copy with every existing layer protected; inspect, capture and sample; add a
layer, select, tighten protection; paint native strokes and fills, each verified and rolled back on
a leak; soften or revise with transparency masks painted the same way; try a change on a hidden
copy of a layer, group layers by moving them, remove what is not kept; move a layer by whole
pixels through a transform mask, or scale, rotate or shear it; branch the whole document
to try an alternative beside it; preview at game size; undo or keep; save to a new KRA or ORA,
verified by reopening; close.

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
`krita_server_info`. The tool contract's `api_version`, `"0.4.0"`, in every envelope. The bridge
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
   writes no layer; an AST test holds that site and its receiver. `setSelection`, which on a mask
   adopts its argument with no undo (K50), is held to four sites the same way: the global
   selection's two commits on the document passed in, the harness's selection mask, and
   `krita_adapter.documents.create_mask`, whose receiver is bound once from
   `createTransparencyMask` and given its coverage before `addChildNode` attaches it (decision 14).
   The tool list holds the rest.
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

**The ops: 39.**

| Group | Ops |
|---|---|
| Sent by tools (25) | `server_info`, `document.list`, `document.open`, `document.create`, `document.inspect`, `document.close`, `document.save`, `document.duplicate`, `document.save_finish`, `document.duplicate_open`, `resource.list`, `capture.read`, `sample.read`, `preview.read`, `layer.create`, `layer.update`, `layer.duplicate`, `layer.reorder`, `layer.remove`, `layer.transform`, `selection.set`, `protection.set`, `history.step`, `paint.stroke`, `paint.fill` |
| Server and `doctor` (2) | `bridge.unsaved_documents`, `document.baselines` |
| Fixtures, the probe only (11) | `harness.export_kra`, `.select_mask`, `.front_document`, `.activate`, `.undo_labels`, `.label_timing`, `.add_node`, `.view`, `.brush_state`, `.preset_dirty`, `.undo` |
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
- So the same `operation_id` sent again runs afresh, which a save's finish needs: it is always
  sent under one id derived from the save's. Other arguments under it answer
  `REQUEST_ID_CONFLICT` without replacing the failure, since the finish's arguments are the
  server's own and can differ between attempts.
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

**25 tools.** Observe: `krita_server_info`, `krita_document_list`, `krita_document_open`,
`krita_document_create`, `krita_document_inspect`, `krita_resource_list`, `krita_capture`,
`krita_sample`. Paint safely: `krita_layer_create`, `krita_layer_update`, `krita_layer_duplicate`,
`krita_layer_reorder`, `krita_layer_remove`, `krita_layer_transform`, `krita_document_duplicate`,
`krita_selection_set`,
`krita_protection_set`, `krita_paint_stroke`, `krita_paint_fill`. Deliver: `krita_history_step`,
`krita_operation_get`, `krita_operation_cancel`, `krita_preview_render`, `krita_document_save`,
`krita_document_close`.

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
meaning.** Added fields and tools do not move it. At 0.22.0 `transparency_mask` went live, `coverage`,
`mask` and a capture's `mask` target were added, and a receipt's `color` reads null for mask paint;
nothing changed for a paint layer, so `api_version` stayed 0.4.0. At 0.23.0 a save whose finish
failed after the save reads `uncertain`, a rollback's failure adds `history_sealed`, and a save's
poll from another process finishes nothing: values and fields, no rename, so it stays. At 0.25.0
three layer tools were added and `krita_history_step` refuses to split an operation's steps, a
refusal it did not make before but no field or value changed, so it stays. At 0.26.0 a tool and a
handle field were added, so it stays. At 0.27.0 a tool and the layers' `translation_px` were added,
and a duplicate refuses a layer holding a transform mask, a new refusal, so it stays. At 0.28.0
`krita_layer_transform` took three operations, each with a receipt shape of its own beside the
translate's, so it stays.

**Schemas are data.** Each of the 25 `schemas/krita_<tool>.json` holds `name`, `description`,
`inputSchema`, `outputSchema`, `annotations` and `example`. `MCPServer` tools are built by hand with
`FuncMetadata`, so the contract's exact JSON Schema is published and no pydantic model filters
arguments; `ExactArguments` passes them through and the runner validates with Draft 2020-12.
`scripts/amend_schemas.py` writes the shapes the files share (the envelope with its typed error,
`guard`, `source`, the completed rule's copy of `data`, open's `layers` as inspect's and the
duplicate's, inspect's `protection` as the duplicate's, the stroke's colour as
the sample's `color` and the fill's, the stroke's mask paint as the fill's `mask`, the selection's
rect, ellipse and polygon as the fill's, layer_update's `verification` as the stroke's, the fill's
and each layer op's, and the outcome values as operation_get's `outcome`) and formats them; a test
holds the files to it.

**A field's range or unit is in its `description`.** Codex shows a property's description as a
comment and drops `minimum` and `maximum`, so every input property with both bounds, on itself or on
its items, states them as "A to B", and a test holds each description to its schema's own bounds.
Fields whose unit or rule matters say it too: `points`, the colours (sRGB 0 to 1), `verify`,
`input_fallback`, capture's two forms, and the sample's `color` and `rgba_255`. A tool's
`description` carries a short example where a shape is easy to get wrong: capture's two forms, and a
sample's `color` sent as a stroke's colour.

**Hints follow each tool's worst permitted behaviour.**
- The eight reads are `readOnlyHint: true`. One exception is written down, the owner's choice at
  X1, widened at B1: `krita_operation_get` finishes a save or a duplicate it is polled for,
  putting its file in place and opening a duplicate's branch, but only in the server process that
  made the call (*The server*). Any other poll only reads.
- Six mutating tools only add, and are `destructiveHint: false`: `krita_protection_set`,
  `krita_document_open`, `krita_document_create`, `krita_document_save`,
  `krita_layer_duplicate`, whose copy is always hidden, so the composite cannot change, and
  `krita_document_duplicate`, which writes a new file, opens it, and leaves its source as it was.
- The other eleven are destructive, because undoable is not additive. A fill overwrites what is
  there, a reorder, a remove or a translate changes what shows, a scale, rotate or shear resamples
  pixels, and `krita_layer_create` can make a mask that
  hides its whole layer, as `visible: false` would; it was additive until masks went live at
  0.22.0.
- `idempotentHint` is true and `openWorldHint` false on every tool.
- `readOnlyHint` is load-bearing. `tools.build` reads it to decide what mutates, and the
  `BOUNDED` test holds the ops to it.
- A table test in `tests/test_tools.py` holds all 25, so a new tool's hints are chosen, never
  copied.

Codex reviews every destructive call unless the owner sets the server's
`default_tools_approval_mode`; the user guide says what that removes.

**Which forms reach Codex.** Codex shows its model a TypeScript declaration, never the schema, so a
valid schema can still arrive as `unknown`. `tests/test_schemas.py` holds these forms:
- no `allOf`, no `prefixItems`, no `items: false`;
- a tuple is `items` with `minItems` equal to `maxItems`;
- a union has nothing beside it, and each branch is typed;
- a conditional sits under `dependentSchemas` on the field it reads, because an `if` passes on an
  absent field and adds a false problem; Codex drops the keyword, as it drops `if`. Preview's
  recipe keeps one `if`, on presence alone: one of two fields required, which `dependentSchemas`
  cannot say;
- "field absent" is `{"properties": {"f": {"not": {}}}}`, because a bare `false` loses the error's
  path;
- outputs are one chain written by `amend_schemas.py`: completed, else failed, else pending.

**Codex's limits are tested.** `tests/support/codex_render.py` ports Codex's sanitizer, the struct
an input passes through and its TypeScript renderer, from `rust-v0.166.0` (the same files at main on
2026-11-04), and renders Codex's own test case as Codex's test expects. For every tool,
`test_codex_shows_every_input_and_output_whole` holds:
- the normalised input at most 5,000 bytes, past which Codex strips descriptions and then deeper
  shapes (the largest is `krita_paint_stroke`'s, 3,190);
- the rendered input at most 16,000 bytes, past which it becomes `unknown`, and with no `unknown`
  in it (the largest is 2,127);
- the rendered output at most 16,000 bytes and not `unknown` (the largest is
  `krita_preview_render`'s, 2,362).

The port follows a pinned tag, so a Codex release that changes its renderer is not seen until the
port is redone. `Array<number>` hides a tuple's length. `ALL_TOOLS` carries the declarations, so an
agent reads one by filtering for it.

**Argument errors name every problem,** up to `MAX_REPORTED_PROBLEMS` (50). The message joins them,
`details.errors` lists them and `details.omitted` counts the rest. Fields take turns over the cap, so
one repeated mistake cannot hide another; the cap keeps an answer well under Claude Code's 25,000
tokens (C4). A forbidden field reads "not allowed with these arguments".

**A number no double holds is refused in one place.** mcp's parser reads `NaN`, `Infinity` and
`1e400` as floats, and a number schema's bounds pass NaN. `_checked` walks every tool's arguments
beside the schema and reports each NaN, infinity or integer past a double's range as `<path>: not a
finite number`, among the schema's problems and under the same cap; the schema's own problem with
that number (a bound or a type) is left out, and so is a union's problem when one of its branches
failed on such numbers alone, so each is reported once. A tool's own check stays only
for a number it computes, such as a smoothed stroke's control points.

**Semantic checks stop at their first refusal.** One envelope carries one code with its own
`details`, these codes differ, and a later check can assume an earlier one held. The server's checks
that compute feed each step's result to the next. The plugin's handlers are a second line behind the
schema, where a job ends at its first raise and each check reads what the one before confirmed: the
document before the layer before the pixels.

**Argument rules are written twice on purpose.** Each side trusts no caller, and a refusal the server
makes carries no `operation_id`. Each pair is held by a parity test in `tests/test_parity.py`: 25
today, from open's format, editable lists and mode to a capture's area, a layer's coverage, a
fill's colour and area, a stroke's or fill's colour and mask paint, a taper's rules, a layer moved
inside or above itself, a copy's name, a layer's name length, a removal's `verify`, a
translate that moves nothing or past its range, and a scale, rotate or shear of nothing, past its
schema's bounds, or of another type or field. `tests/support/parity.py`'s
`refused_alike` calls the tool, turns the server's half off, and calls again, so the server's own
translation carries the same arguments to the plugin. Both must refuse with one code and one
`retryable`, the plugin before its marker.
- **A rule in a named function** is switched off by name: a stroke's colour is `_brush_rules`, a
  fill's colour and area its `_fill_rules`, a move inside or above itself `reorder_rules`.
- **A rule in the schema** is cut, by its path, from the schema a second server is built with:
  colour and mask both given, mask paint with a blend or alpha lock, `coverage` on a layer, a
  `working_dir` for a read-only open.
- **The area rule** reads one set of points on both sides: a polygon's, or a closed curve's input
  points, never its control points.
- **One asymmetry:** the schema refuses mask paint's `blend_mode` and `alpha_lock` by presence,
  and the plugin, which gets the server's defaults, any value that does something.
- **Not held:** `eraser`, which the schema takes only as `false` while the plugin keeps erasing
  for when it comes; preview's `baseline_id` on a target that is not the composite (the backlog);
  and the `frame` rule, since the server always sends 0.

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
| `DOCUMENT_DIRTY`, `DOCUMENT_UNSAFE`, `DOCUMENT_READ_ONLY`, `DOCUMENT_IN_USE` | no | plugin. `DOCUMENT_IN_USE` is retryable at a save's finish alone, so its id runs again for the lease holder; the server reports that finish `uncertain`, so no agent sees it retryable |
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
| `krita_paint_stroke` per-point pressure, tilt, rotation, tangential pressure, speed, time | `UNSUPPORTED_CAPABILITY`, unless `input_fallback: flat` | Phase 6, on Krita 6.1 / 5.4 (K30) |
| `input_fallback`, which takes only `flat` | the one value | Phase 6 |
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
| `krita_paint_stroke` `effective_brush.antialias`, `krita_paint_fill` `effective_fill.antialias` | `true` | Statement, kept: every stroke and fill is antialiased |
| `krita_paint_fill` `effective_fill.preset_id` | `c)_Pencil-3_Large_4B.kpp` | Statement, kept: the preset every fill activates (K49) |
| `krita_capture` `fresh` | `true` | No phase promises it; meaningful once reads can pin a revision (Phase 3) |
| `krita_preview_render` `static_only`, `source_pixels_changed` | `true`, `0` | Statements, kept: a preview certifies no motion and writes nothing |
| `krita_document_save` `reopened_verified`, `composite_preserved` | `true` | Statements, kept: any other outcome is an error |
| `krita_paint_stroke` and `krita_paint_fill` `protected_pixels_changed`, `changed_outside_px`, `undo_steps` | `0`, `0`, `1` | Statements, kept: on a completed stroke or fill; a leak is an error |
| `krita_protection_set` `composite_outside_mask`, `undo_steps` | `exact`, `0` | Statements, kept |
| `krita_layer_update` `undoable` | `["blend_mode"]` or empty | Statement, kept (K22) |
| `krita_layer_create` `protected`; `krita_document_create` `mode` | `false`; `new` | Statements, kept |
| `krita_layer_duplicate` `visible`, `protected` | `false`, `false` | Statements, kept: the copy is always hidden and the agent's own |

At 0.20.0 `krita_paint_stroke` dropped the refused values no phase names: `smooth: basic` and
`stabilizer`, `antialias: false` (the field takes only `true`) and `eraser: true` (still required,
it takes only `false`; erasing, when it comes, puts it back). Each now fails the schema with
`INVALID_ARGUMENT`. `krita_document_create`'s stay, since round 2 does not amend that schema.

`limits.capture_pixels` in `krita_server_info` is reported and enforced by nothing but `max_px`'s
schema maximum, of which it is the square. `brush_size_px`, `resource_page_size` and
`stroke_overhang_size_fraction` are the plugin's own bounds, each held to its constant by a test;
the overhang bounds on-curve points only, so a brush's reach can pass it.

**The capability matrix** is the one place a later feature announces itself. False today:
`stroke.per_point_input` (Phase 6), `undo.grouping` (K29), `stroke.deterministic` (stochastic
presets have no seed), `operation.cancel_running`, `color_spaces`, `filters` (Phase 2), `animation`
(Phase 5). True since 0.9.0: `stroke.native_brush`, `stroke.smoothing`, `selection.enforced`; since
0.21.0, `paint.fill`; since 0.22.0, `mask.transparency`; since 0.24.0, `stroke.dynamics`; since
0.27.0, `layer.translate`; since 0.28.0, `layer.scale`, `layer.rotate` and `layer.shear`.

**The instructions.** `instructions.py` is 3,371 of Claude Code's 4,096 characters (C4). A test
holds at least 700 spare, room for the round's later sessions. It states the rules an agent would
otherwise learn from a refusal, and leaves to the tools what belongs to one: a field's range, unit
and form to its description, and a tool's own rule to the tool's, each moved rule held there by a
test.

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
| `no_effect` | Its own attempt, the one whose operation the bridge named, and any the bridge answered under that operation |
| `not_sent`, `conflict` | Its own attempt alone |
| `unknown` | Nothing yet; an attempt unknown in another Krita session is never re-sent |

`outcome_of` makes `details.outcome` `applied` a `receipt`, and `uncertain` and `unregistered`
`unknown`. A resend needs a request proven never dispatched, a retryable failure, or a live Krita
session whose dedup state covers that exact `request_id`. Past the 7-day window nothing remembers a
request, invariant 9's stated limit.

The index also keeps each finished line by its `operation_id` and by the `bridge_operation_id` a
retry was answered under, so `krita_operation_get` can answer once Krita has moved on.
- **A `no_effect` line names its own id,** and the bridge's when it has one; an older line
  without `bridge_operation_id` settles its own attempt alone.
- **A retry that joined a running call** comes back running under the original's id. Its own
  attempt then gets an `unknown` line with no result, naming that id. It settles nothing and
  answers for its own id alone, but a `no_effect` for the original then settles it too.
- **Why not more.** A `no_effect` cannot settle every attempt with the same arguments: one sent
  after the refusal released the request may have run. An `unknown`
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

**The marker.** `Call.mark()` goes before an op's first change of any kind, on each path: document,
protection state, file or registration. The frame places it for the ops on it (see *The
verification core*); every other op places it by hand. `move()` takes it as a callback that only
`history.step` passes, because a rollback is already past its own op's marker. Two kinds of window
state are not changes here, because an op sets them before its marker:
- **The window-wide brush,** which a stroke sets.
- **K46's activation.** It moves the current node off a selection mask, so the mask's overlay
  stays out of a read. The view goes back; the active node stays on the layer, because
  `setActiveNode` cannot make the global selection's mask current again (measured).
  `krita_layer_update`'s `active` is the same call, but there the active node is what the agent
  asked for, so it is marked first. The fake's marker gate lets through only the activation off
  an active selection mask onto the layer `nodes.unmasked` names, and an armed test drives a
  stroke with each kind of mask active.

| Op | First change |
|---|---|
| `document.open` | the working folder, or `port.open` for a read-only open |
| `document.create` | `port.create` |
| `document.close` | dropping a pending save |
| `document.save`, `document.duplicate` | making the folder |
| `document.save_finish` | clearing the pending save |
| `document.duplicate_open` | `port.open` |
| `protection.set` | writing the handle's state |
| `selection.set` | `before_change` |
| `layer.create`, `layer.duplicate`, `layer.reorder`, `layer.remove`, `layer.transform`, `paint.stroke`, `paint.fill` | the frame, beside `before_change` |
| `layer.update` | the frame, or `port.activate` for `active` alone |
| `history.step` | inside `move()`, past its `FOREIGN` return |

**Every op has a class.** `READS` (9) change nothing. `BOUNDED` (18) carry a marker, and a test holds
them equal to the mutating tools' ops, `document.save_finish` and `document.duplicate_open`, the
two sent under ids derived from another call's. `harness.*` has no marker, so a
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
pending save, the last verified save's `saved_state`, and the duplicates placed but not yet opened
(`branches`). Its hashes are kept apart: `source_sha256` is the accepted source's, and
`opened_sha256` the file Krita opened, which the lazy baseline reads against. `sync()` matches wrappers by `==` (libkis compares by document), prunes documents that
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

**Duplicate.** A branch is a verified save to a new `.kra`, then that file opened as a document of
its own (decision 12). `Document.clone()` is never used: it is not added to `KisPart`, which
`Krita.documents()` reads, so `sync` would drop it. Three ops, each its own job:
- `document.duplicate` is the save's handler with `branch` set: `.kra` only (only KRA keeps the
  layer ids protection names, K39), the same guard, hidden file and compare. Its `Pending` holds
  what the branch inherits, read in that job: the protected ids, the allowed mask (the handle's
  own bytes, never changed in place), both flags and the canvas size.
- `document.save_finish` places the file as for a save, but never touches the source's `dirty` or
  `saved_state`, so the source stays as it was; it records the placed file in the source's
  `branches`, by save id.
- `document.duplicate_open {document_id, save_id}` takes no path: it opens only a file the
  bridge's own finish placed, so no client can open an arbitrary `.kra` directly through it. Before
  its marker it checks the path against the roots, the file's hash (only when its stat has moved
  since the finish placed it) and the mask's size. It then
  opens, shows and checks the file as the open does (`opening.opened`), and registers the branch
  last: the source's mode, the file as `path` and its hash as `opened_sha256`, the source's
  `source_*` fields (null for a created document's branch, so `baseline_untouched` keeps meaning),
  a new `baseline_id`, an empty ledger, the caller's lease.
- **What it inherits is the tighter of the save's snapshot and the source now:** the union of the
  protected ids, kept to the branch's own nodes; the AND of the masks; each flag's OR. Protection
  drops a protected node that has gone from the source, so the snapshot keeps a rerun from
  loosening, and a tightening since applies too.
- A failure after its marker closes the branch and keeps the file. Its `branches` entry serves a
  rerun only after a retryable refusal, which changes nothing: `Jobs` reruns a derived id after no
  other failure. An entry whose open failed for good stays unused until the source closes, and
  `krita_document_open` opens the file.

**The close.** `refuse` answers `DOCUMENT_DIRTY` while `dirty` is set, and while Krita holds the
document modified unless it still matches its last verified save: `saving.matches_saved` reads the
composite, then the tree's nodes, then every node's own pixels, and stops at the first difference.
A KRA save hashed each node already; an ORA save, which stores fewer nodes and compares projections,
hashes each node's own pixels once more for it. The save takes that state from its own read, so a
hand change before its finish is caught too. Both refusals name `dirty` and `krita_modified`, and
come before anything changes. `port.close` then clears Krita's flag, so Krita never asks: it is
reached only under `discard`, or when nothing would be lost. A hand change to guides, and perhaps to
the global selection alone, is not seen. Comparing an 8192² working copy with eight 4096² layers
took 0.4 s.

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
is native, and `background` or `greyscale` there is refused by the schema, as on a selection,
through `dependentSchemas` on `scale` and `target`. `max_px` bounds the image;
`limits.capture_source_pixels` (8192²) bounds the area read. A layer capture is that layer's own
paint device (K12), and is paint layers only. A mask capture (`target: "mask"`) is a transparency
mask's own one-byte device, sent as `A8` and drawn as a grey `L` image; like a selection's, it takes
no `background` or `greyscale`, which the schema refuses through `dependentSchemas` on `target`. A larger image goes by path with a 1600 px inline
preview. Captures are `op-<id>` files, found before they are made, so `krita_operation_get` can
rebuild a receipt.

**Sample.** `rgba_255`, `color`, hex, L\*a\*b\* and L\*C\*h, with an alpha-weighted disc for
`radius`. `color` is the stroke's `brush.color` shape: the mean divided by 255 and unrounded, so a
stored byte paints back as itself, with alpha 1, because a stroke's transparency comes from its
opacity and flow. Colour maths is sRGB only (`sRGB-elle-V2-srgbtrc.icc`, `sRGB built-in`): the
document's profile for a composite, the layer's own for a layer. Otherwise `color`, L\*a\*b\* and
L\*C\*h are null, and with no colour (alpha 0) so is the hex.

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

**Transparency masks.** `layer.create` with `type: transparency_mask` puts one on a paint layer, and
it is the one mask an agent makes. libkis builds a new mask with an empty selection, which hides its
layer (K50), so `create_mask` gives it its coverage before `addChildNode` attaches it, in Krita's one
"Add Layer" step: `all` is an empty `Selection()` inverted, which selects past the canvas too; `none`
is an empty one; `selection` is a `duplicate()` of the global selection, never the live one (K23).
`setSelection` adopts its argument with no undo, so it is never called on an attached mask.
- **Protection.** A mask changes how its layer shows without changing the layer's pixels. So
  `protection.refuse_held_line` refuses any mask change (create, paint, `visible` or `name`) while
  the mask, its layer or any group holding it is protected (decision 14), and its removal too. A
  mask in a file opened is protected like every node.
- **Bounds.** Krita reports a mask's bounds as its layer's own, and no mask moves them, its layer's
  included (measured), so `misplaced` compares a mask create's layer field by field, as it does any
  create's parent.
- **What a mask does.** The composite takes the layer by the coverage: `rint(layer × c + below ×
  (1 − c))`, c the byte over 255 (measured with a graded PNG selection).
- **The create's check.** It reads no layer pixels, only the composite, over the layer's own bounds
  when `reach` from the layer is clean and over the canvas otherwise, since the create has no
  `verify` to ask for more; the receipt's `verification.mode` says which. A leak, or alpha under
  `preserve_composite_alpha`, is `PROTECTED_REGION_CHANGED`, rolled back. Its judge then reads the
  new mask over the layer's bounds and refuses, rolled back, coverage other than what was asked.

**Layers: duplicate, reorder, remove** (`bridge_core/layers.py`, beside the create). Each runs on
the frame and pushes its steps as Krita takes them. The adapter has three calls, each one Krita step
at most: `remove_node` (`Node.remove()`, "Remove Layer"), `duplicate_node` (`Node.duplicate()`, no
step) and `attach` (`addChildNode`, "Add Layer"), which the create also uses (K52).
- **Protection is per node.** A layer that is protected, or holds a protected layer, is never moved
  or removed (`protection.refuse_held`, the update's rule); a transparency mask's removal is held to
  its line (decision 14). A node inside a protected group may still move or go, as it may be painted:
  the composite against the allowed mask is what judges it. A duplicate's source may be protected
  (decision 13), and its copies are the agent's own. A layer holding a transform mask is not
  copied (`reason: transform_mask`): undoing the attach of a copied transform mask crashes Krita
  (K53), and a rollback undoes that attach.
- **A clone's source is refused,** with `reason: clone_source` and the clones' ids, by the reorder and
  the remove: Krita's remove turns a removed layer's clones into paint layers (K52), and a move
  starts with a remove. A clone whose source Krita does not name counts as showing the node.
- **The duplicate.** The copy is named and hidden before `attach` puts it directly above its source,
  so the composite cannot change: its check reads the composite over the source's bounds, or the
  canvas when `reach` finds a spreading node, and refuses any changed pixel. Its judge pairs the
  copy's nodes with the source's depth first and builds the `id_map`.
- **The reorder** is a remove, then an add for every node of the subtree, because Krita's remove
  takes each node off its own parent (K52, measured: a group came back empty). The moved node goes
  where it was asked; each node inside it goes back on top of its own parent, which is empty until
  its children return, in child order. So a reorder is 1 + its subtree's size undo steps, each
  pushed once Krita holds it, so a rollback never has more than one step it did not push (F7).
  Between steps it reads `port.structure`, the tree's ids, parents, order, types and blends alone,
  which is all a step's state needs. It reads the whole canvas, and refuses a move into its own
  subtree, and one of more steps than one history call (50) or Krita's undo stack takes, as
  `too_many_nodes`, since nothing could then take it back whole. A node already in place moves
  nothing, takes no step, and still marks and dirties, as a clear with no selection does.
- **The remove** takes `verify` as the update does: region refuses on `reach`, full reads the
  canvas. The document keeps at least one layer.
- **Judges compare the watched fields** and each parent's children by rank, never bounds, which move
  with a group's projection: nothing but the asked node may move, and siblings keep their order.
  `nodes.found` is the one lookup that refuses the root and an unknown id, the update's too.
- **Ranks, not raw order.** Krita's child index counts the global selection's mask under the root,
  so `nodes.ranks` leaves it out, for the judges, the placements and the ledger's fingerprint.

**Transforms: translate** (`bridge_core/transforms.py`, the params in `bridge_core/translations.py`). A paint
layer or a group, pass-through or not, moves by whole pixels through a transform mask on top of its
masks, named "Translate"; the layer's own pixels never change (K53, measured).
- **The params** are Krita's own: the transform tool's free transform at identity, as a fresh mask's
  `toXML` writes it, with `transformedCenter` moved. Krita writes the attributes in a hash order that
  changes between sessions, so the plugin writes its own order and parses back by value: the mask is
  a translate's only when every other value equals the identity's and the centre is a finite whole
  pixel. Its translation is the centre, which the tree carries as `translation_px`.
- **The first translate** creates the mask (no step), attaches it on top ("Add Layer") and pushes
  that step, then sets the params (`TransformMask.fromXML`, one unnamed step, waited for). A later
  one sets the same mask's params, one step. The receipt states `undo_steps`, and history moves them
  together.
- **A params step is pushed only once its state is seen to move** and the mask parses at the new
  total; otherwise the call raises with nothing pushed. Its label is empty, like a selection's, so
  only the state can tell it; an unmoved one pushed would let a rollback undo another unnamed step
  in its place.
- **Refused:** the root and an unknown id; any type but a paint layer or a group; a protected layer,
  one holding one, or one in a protected group (decision 14's line, with the layer's own rule); more
  than one transform mask on the layer, one whose params are not a translate's, or a hidden one
  (`reason: transform_mask` or `hidden_transform_mask`); a whole translation past ±16384 px;
  cumulative undo, which would merge two moves into one step; a canvas past one read.
- **Full scope always.** The composite over the canvas against the allowed mask and
  `preserve_composite_alpha`, no target and no hashed layer, so the frame's pixel step never arms.
  The tree the judge and `back` compare against is read after the before-read has waited; one that
  differs from the refusals' read is refused retryable, before the marker.
- **The judge** holds the mask to its place and the rest of the tree to `drift`, the mask's own
  move alone allowed to change. `back` compares the watched tree, the move with it.
- **Paint lands where it is aimed, in the layer's own pixels,** and shows moved; a stroke's or a
  fill's `changed_bounds_px` and `layer_bounds_px` stay in the layer's own pixels, and `reach`
  makes region scope refuse on the layer and on anything inside a translated group. A mask added
  later sits above the transform mask and stays where it is painted.
- **Inspect, open and the branch** report each transform mask's `translation_px`, or null for params
  no translate made.

**Transforms: scale, rotate and shear** (`bridge_core/affine.py`; `transforms.py` sends each
operation type its own way). A paint layer, or a group of paint layers and groups, resampled by
Krita's own `scaleNode`, `rotateNode` or `shearNode` in one step each, about the centre of its exact
bounds (K54).
- **The operations.** A scale takes the bounds' new size and one of Krita's eight filters, checked by
  the tool against a fixed list and `Krita.filterStrategies()`, since `scaleNode` takes any other
  name as Bicubic; the pivot it passes is the bounds' `QRectF` centre. Rotate takes degrees,
  clockwise on screen, sent as radians, Bicubic; shear takes degrees on x and y, x then y,
  Bilinear (measured).
- **Refused before the marker:** the root, an unknown id or another type; a protected layer or one
  holding one (`protection.refuse_held`; a protected group above is judged by the composite, as
  painting is); a mask or another kind in the subtree (`node_type`), a transform mask in it or on a
  group holding it (`transform_mask`), a locked or alpha-locked layer, a styled one, a clone's
  source (`layers.refuse_clone_source`, fed by `effects` with reach, since Krita moves those
  clones); an empty target; a change of nothing, a scale to the bounds' own size or a shear whose
  replica of Krita's `mapRect` keeps the size (Krita then pushes no step); more than 50 nodes;
  reads past one, each layer's or all of them together; cumulative undo; a filter Krita lacks.
- **The witness.** Each paint layer in the subtree gets a rect before the change: its bounds united
  with where the operation takes them about the pivot (`affine.mapped`), widened by a filter's
  reach, three source pixels times the scale, and four more. Its bytes there are hashed before and
  after. The frame takes the op's `witness_of`, the first layer whose digest moved, as a stroke's
  frame takes its target's diff: it pushes the step with that witness, or seals when nothing moved.
  A resample leaves colour under alpha 0 outside a layer's exact bounds (measured), so only a read
  tells what a rect holds; a digest padded with the default pixel failed a rollback live.
- **The change** is the one libkis call, waited, then a refresh and the tree. **The judge**, in
  order: no node added or removed, `drift` with `offset_px` loose on the subtree (Krita moves the
  offset on a rotate or a shear); every layer's new bounds inside its rect, or `INTERNAL_ERROR`,
  rolled back by what the rect saw; a sealed step with a changed composite is `INTERNAL_ERROR`, and
  one without is `no_change`, rolled back with history sealed (a half turn of symmetric paint); a
  leak is `PROTECTED_REGION_CHANGED`. **`back`** is the watched tree, offsets loose, and every
  layer's bounds and digest as before.
- **Full scope always,** no hashed layers. The receipt gives `pivot_px`, the bounds before and
  after, the filter Krita used and `undo_steps: 1`.

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
spread a change, and a filter layer inside a closed group above cannot see below it. A transparency
mask's change is its layer's projection's, so for a mask target the walk starts at that layer: its
own spreading blend, its filter masks and clones of it count. A transparency mask elsewhere stays
bounded, since it multiplies pixel by pixel.

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

**The frame.** `bridge_core/mutation.py` holds invariant 5's sequence once, and the stroke, the
fill, `krita_layer_update` and the layer ops (create, duplicate, reorder, remove, and the
transform's translate, scale, rotate and shear) run on it;
the save keeps its own ladder, and a selection, which has no verdict, pushes its step by hand.
- **Before the change.** `verifiable` refuses a scope or target rect the reads cannot see and takes
  the allowed mask over the scope, as a `Reads`. That names the composite's scope, and optionally
  the target over its own rect, its bytes per pixel (`channels`: 4, or 1 for a mask) and each
  protected layer over its own rect. `Mutation.read` refreshes, then reads.
- **`Mutation.run`** takes the start fingerprint, then the marker and `before_change()` together,
  then, inside `unconfirmed`, the op's change, the after-read, `check`, and the op's `judge`. The
  rollback runs inside `unconfirmed` too: the op's own `BridgeError` passes through, and any other
  raise marks the document lost. The write-nothing update does not arm it.
- **Steps.** An op names its undo labels up front, one or more, and the frame refuses a change
  that took any other number; a reorder names one remove and an add per node it moves, a first
translate an add and its params change, a scale, rotate or shear its one step. An op that
  names none reads no start state, so no selection. A node change pushes each step the moment
  Krita holds it, with its state after, so at most one step is ever unpushed (F7). A pixel change's
  step is pushed by the frame after the reads, with the witness over the target's diff, or sealed
  when the diff is empty; an op whose change reaches several layers brings its own `witness_of`
  instead, the first of them that moved.
- **A problem** is a `BridgeError` from the change or the judge, keeping its code, or any other
  `Exception`, logged as `INTERNAL_ERROR`. Either is re-raised never retryable, after the rollback.
- **The rollback,** in order:
  1. A step named but never pushed is the newest Krita may hold, so it goes first. A pixel step is
     undone by a witness built from a re-read, or by the op's `witness_of`, unless the re-read
     shows the document back. A node
     step is undone by its label and state, unless the state never moved.
  2. Each pushed step is undone, newest first, through `history.move`. The first reads the state
     afresh, so a step Krita holds above the op's own is never undone in its place. The view comes
     forward (K7) only when a step may move, so a rollback that only writes values back leaves it
     alone.
  3. History is sealed below a step it never named, after the pushed steps are off the ledger, so
     the floor never stands above `applied`.
  4. The op's `compensate` writes back what no undo holds: the update's property values, because
     `set_properties` pushes no undo step (K22).
  5. The rollback is confirmed by a re-read and `same()` when the op reads pixels, and by the op's
     `back`: the stroke's target bounds, or the watched tree for the layer ops.
- **Every rollback reports alike.**
  - Confirmed: `dirty` comes back and the problem is raised with `document_id`, the op's ids,
    `rolled_back` (no move failed, and something was undone or written back),
    `rollback_verified` and `history_sealed`. An op that reads pixels adds `protected_layer_ids`,
    `protected_pixels_changed` and `target_outside_reach`, and the failed `verification`.
  - `history_sealed` is true when history stopped below the op. That happens when a step was
    named and never pushed, since Krita may hold it whether or not the state moved, or when the
    document went unsafe.
  - Not confirmed: the document is unsafe, its history sealed through `Handle.lost()`, and the
    call is `ROLLBACK_FAILED`, with `cause` and what a failed move saw.
  - `protected_pixels_changed` counts the protected layer's own bytes a pixel, read from what was
    read: four for a paint layer, one for a mask.

**`krita_layer_update`.** Only values that differ are written; the blend first, then the rest in a
fixed order, then a refresh (K42), the tree, and the check that nothing else moved, all inside its
change. An update that only sets `active` changes nothing in the document and skips the frame. A
transparency mask takes `name` and `visible` only; its scope is its own bounds, which are its
layer's, so showing what it hid is read.

## Painting

`bridge_core/painting.py`, with `brushes.py` for the reach and `krita_adapter/painting.py` for the
libkis calls. One call is exactly one Krita stroke and one undo step.

**The order inside the job.** Refusals, in order: colour space; the target (protected, type and space,
any local selection mask, since libkis does not say which is active); on-curve points past the canvas
grown by half the size; the preset by file id, with the 5 nearest; the listed fingerprint; cumulative
undo; region reach. Then, with the view in front (K2, K9): the brush set in K3's order (preset,
then size, opacity, flow, blend, eraser, alpha lock, rotation, colour) and read back, `paintAbility()`,
the reach from the effective preset's XML, R and the ring, the refusals over the scope,
`OUTSIDE_ALLOWED_MASK` over R, a refresh, the before-read, the brush read again, then the frame's
fingerprint, marker and `before_change()`, and `paint_path`. Its judge holds the target to R and
its bounds, and widens a full-scope `changed_bounds_px`.

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

**Mirror and wrap-around** go off for a stroke or a fill and back on in a `finally`, each noted before it is
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

**Rollback,** the frame's. One undo through `history.move`, or, after a raise, a re-read and an undo
only when the label and a witness built from the re-read match. It is confirmed by the re-read,
`same()` and the target's bounds; otherwise the document is unsafe and the call `ROLLBACK_FAILED`.
It is never retryable, and a `BaseException` marks the document unsafe through `unconfirmed`.
`protected_pixels_changed` is `null` when no confirmed undo brought back what it is counted against.

**The fill.** `paint.fill` shares the stroke's body from R on: one function in `painting.py` holds
the scope, the reads, `OUTSIDE_ALLOWED_MASK`, the frame, the brush re-read, the judge and `back`,
and each op brings its R, its noun and its paint call. The fill paints with `Node.paintPath(path,
"None", "ForegroundColor")`: Krita's painter fills the path, antialiased, with no paint op and so
no dab, in one "Scripted Brush Stroke" step, confined and weighted by the selection (K49).
- **The shapes** (`bridge_core/shapes.py`, pure): a rect and an ellipse take whole pixels; a polygon
  and a closed curve take 3 to 4096 points and fill even-odd. The server turns a curve's points
  into a closed uniform Catmull-Rom, exact cubics whose neighbours wrap round. The area rule (no
  shape whose points lie on one line, to a relative 1e-9, over the points it passes through and
  never a curve's control points) is a parity pair, as is the colour's
  alpha of 1.
- **Order.** Before the job: the fields, the shape and the area rule. Then the space, the target,
  the shape on the canvas (a curve by its extrema, found with the stable quadratic, not its
  control points; refused, never clipped), the fill's preset listed, cumulative undo, region reach. With the view in front: a
  selection fill reads the selection's bounds there and clips them to the canvas, since Krita's
  can run past it (an inverted selection's measured 448 × 320 on a 400 × 300 canvas); then the
  preset, opacity, flow 1, blend, eraser off, alpha lock and colour in K3's order, read back, the
  preset's XML checked, and `paintAbility()`.
- **The preset.** Every fill activates `c) Pencil-3 Large 4B`, a build-up `paintbrush` preset with
  no masking brush, and records its digest as the stroke does. Measured under one stock preset of
  each of the 16 engines: every preset fills the same visible pixels, but a wash-mode preset (most
  `b)` presets, the masked one among them) writes colour under alpha 0 up to 3 px past the shape,
  which byte-exact verification counts. A preset no longer build-up, or with a masking brush, is
  refused before painting.
- **R** is the shape's box, aligned outward, grown by 2 px; R′ is R grown by 32. Measured under the
  build-up preset, nothing changed past the aligned box, colour under alpha 0 included.
- **The receipt** has the stroke's shape, with `fill_id`, `shape`, `shape_bounds_px` and
  `effective_fill` in place of the brush.

**A mask target.** A stroke or fill on a transparency mask brings `mask: "reveal" | "hide"` in place
of a colour; the server sends `color` and `mask`, one null, and both sides want exactly one. Mask
paint takes no blend, alpha lock or eraser. The target check reads protection first, so a colour on a
protected mask is `LOCKED_TARGET`; then the paint kind, so a colour on a
mask or mask paint on a layer is `INVALID_ARGUMENT`, then the held line, then the mask's space (`A`,
`U8`). A local selection mask on the layer does not confine mask paint, so it is not refused
(measured); the global selection does. The paint is Krita's own on the mask's Alpha8 device, with
white for reveal and black for hide under `normal`: each moves coverage by the opacity, reveal 0.5
from 0 giving 128 and hide 0.5 from 255 giving 127 (measured; greys map linearly, not by
lightness, and `erase` with white hides alike). The frame reads the target one byte a pixel
(`channels=1`), so its diff, its witness and `history.move`'s witness all count bytes. A mask's
`layer_bounds_px` is its layer's, as Krita reports a mask's bounds. MyPaint presets read
`MYPAINTBRUSH_UNPAINTABLE` on a mask, and `_paintable` refuses them.

**A taper (`dynamics`).** A stroke's size and opacity along its arc length, through Krita's own
Distance sensor (K51), on the pixel engine alone. `bridge_core/dynamics.py` is pure.
- **Rules.** Each option is 2 to 16 knots `{at, value}`, at from 0 to 1 rising by 0.001 or more.
  A taper needs `preset_sha256`, colour paint, and an arc length of 1 px or more. These are
  parity pairs with the server, which measures the arc the same way.
- **Refused before any change,** after `_listed`:
  - another engine;
  - a preset held after a failed restore;
  - `useDirtyPresets` at anything but Krita's default, `true`, the only value measured;
  - a dirty flag no resource chooser reports.

  The flag read here, at A0, before the brush is set, is what the restore puts back.
- **Everything up to the brush re-read runs on the unedited preset:** the fingerprint, `set_brush`,
  `_taken`, `remember`, the reach and R. R holds because the edit sets `SizeValue` to 1 and touches
  neither the tip, the ratio nor the scatter, so no dab passes `size_px`.
- **The XML.** For each asked option, the param `<Option>Sensor` holds `distance`, with an integer
  `length` and the curve, every point a corner, so values run straight. `Pressure<Option>` and
  `<Option>UseCurve` are true and `<Option>UseSameCurve` is false. The receipt lists the sensors
  replaced, and a size strength the edit raised.
- **The origin offset (K51).** A scripted stroke's Distance sensor counts the first dab's distance
  from the canvas origin. So the length is the arc plus |start|, rounded up so no knot passes the
  curve's end, and each knot sits at (at × arc + |start|) / length, after a first corner for the first dab, which reads 0.
- **The change,** after the marker:
  - `edit_preset` (`Preset.fromXML` on the window's current preset), then a read-back of the sensor
    exactly and of the brush values;
  - then the paint;
  - then the restore: `fromXML` of the XML read after `set_brush`, then `reload_preset_action`
    when the flag was clean at A0;
  - then the check, by the stored and the view's digests, which are one object (K51), and by the
    flag against A0. After a reload, the digest before the brush was set or the listed one
    (`activated`), since a reload drops what Krita filled in on first activation.
- **A failed restore,** a raise in it included, becomes `INTERNAL_ERROR` with `preset_restored:
  false` and `outcome: uncertain`, since the window-wide preset is a change after the marker.
  - The frame still undoes the paint.
  - The preset is held beside `activated`: every stroke and fill refuses it with
    `RESOURCE_HASH_MISMATCH` (`reason: preset_held`) until its raw digest reads as before, or its
    flag reads clean, as after a reload.
  - `remember` never runs after the edit.
- **The dirty flag** is the resource model's `Dirty` column, read through the preset choosers'
  views, where two storages hold the file name, from an active preset in an active storage. The
  model is found once and kept while Krita keeps it. Only views and models whose class names a
  resource are asked: another docker's model
  crashed Krita on a stray `data()` call (measured). The probe reads it through
  `harness.preset_dirty`.

**The input gate.** Phase 1 always paints with `Node.paintPath` at pressure 1 (K4), even on a build
with `paintPolylineStroke`, because that branch cannot be tested on released Krita. The server refuses
before the journal, in order: argument errors, numbers that are not finite among them; the
colour's alpha; the input gate; smoothed control points that overflow; a stroke under half a pixel,
since Krita paints no dab for it. Erasing, the other smoothers and antialiasing off are out of the
schema. `smooth: catmull_rom` turns the points into exact cubics on the server.

## The undo ledger and history

`bridge_core/ledger.py` tracks what the bridge pushed: `Step{op, operation_id, label, before, after,
region, witness}` and `Ledger{steps, applied, floor, redo, bottom}`.

- `push` truncates the redo tail (K43). `rolled_back` pops a rollback's step and offers no redo, so
  Krita's redo of a rolled-back stroke, which it does offer, is refused.
- `seal` stops history below a step the bridge cannot name: protection changes, harness ops that
  push, a mutation that raised, a stroke that changed no pixel (`history_sealed` on its receipt).
  A rollback seals after its pushed steps are off, so an op of several steps leaves no floor above
  `applied`.
- An op may push several steps, each its own `Step` under one `operation_id`; a rollback undoes
  them newest first. `krita_history_step` moves an op's steps together: a count that would stop
  between two of them is refused before anything moves, naming `steps_needed` (`history.whole`). A
  reorder's steps and a first translate's are the cases today. When the steps it would need lie past what history
  reaches (a floor or Krita's dropped bottom), the refusal says the op can no longer be moved
  whole.
- `bottom` follows Krita's `undoStackLimit`, default 200 (`UNDO_LIMIT_DEFAULT`), measured to be exactly
  what Krita keeps.
- `undo_available = applied − max(floor, bottom)`.

**A step's identity.** A step's fingerprint is `(id, blend mode, parent, rank, translation)` for
each node, without the root's selection masks, and the SHA-256 of the selection's canvas-clipped
bounds and bytes. `translation` is the tree's `translation_px`: a translate mask's move, parsed from
its `toXML` in the tree's walk and in `structure`, one serialisation per transform mask; null on any
other node. A transform mask whose params no translate made reads null too, so a warp, a liquify or
another kind nobody measured is never compared. The rank leaves the global selection's mask out (`nodes.ranks`), since it comes and goes with
the selection: undoing a clear puts it back where it was (measured), and a layer added above it then
keeps its rank. Adds, removes and moves change the nodes' part; the blend and a translate's move
are what an undo step changes in place. `translation_px` is in `mutation.WATCHED` too, so every
node op's drift check and `back` see it, and in the save's `KRA_FIELDS`. Labels do not
identify a step, and a stroke's fingerprint does not either, so a stroke carries a **witness**: the
target's own bytes over its diff, hashed before and after, checked before and after every move.

**`history.move`** undoes or redoes one step with the document's view in front (K7): posted events
flushed, the top label naming the step and the fingerprint matching, then the opposite label and
fingerprint after. An unconfirmed move is reversed once, otherwise the document is unsafe. A raise
before Krita was asked is `REVERSED`, retryable as the first step; after it, `LOST`. `STOPPED` maps
each stop to its receipt value: `not_the_bridges_step`, `unconfirmed`, `document_unsafe`.

**Labels are English.** `history.LABELS` holds, per op, the label of each step it pushes, in order,
as Krita's actions read them on 5.3.4 in English: "Add Layer" (a transparency mask's create, a
duplicate's attach, a reorder's adds and a translate's mask too, measured), "Remove Layer" (a
remove, and a reorder's first step), "Composition Mode Change", "Scripted Brush Stroke", and an
unnamed step for a selection and for a transform mask's params (`fromXML` names its stroke after a
bare command, measured), and "Scale Layer", "Rotate Layer" and "Shear Layer", one under each of
`layer.transform.scale`, `.rotate` and `.shear` (measured). Krita's own Layer > Transform menu names
its steps the same, and the fingerprint does not see pixels, so the witness alone tells them apart:
a history move that undid such a step and could not confirm it, then put it back, stops history as
foreign, not retryable, since a retry would only undo the owner's step again. They
are read only by `move`, so on a localised Krita ordinary calls complete, `krita_history_step`
refuses every step as not the bridge's, and any change that needs a rollback ends in
`ROLLBACK_FAILED` and an unsafe document. English is a requirement until the backlog's item lands.

**Labels are read after a flush,** because straight after a push they can be stale (1 or 2 of 7 reads,
measured), with the view in front. Selection steps and a translate's params steps have an empty
label, so state alone tells them apart, and Krita keeps Redo enabled
as "Redo " with nothing to redo, so they are confirmed by state alone.

## Previews and the lazy baseline

**The lazy baseline.** The open mints `baseline_id` and writes nothing: a baseline written at open
cost 4.7–5.2 s and 268 MB on the 8k master. The server sends `read_baseline: true` only when it holds
no `baselines/<id>.npy`. The plugin then checks the file Krita opened still hashes to
`opened_sha256` (a working copy's equals its source's; a branch's is its own file's), opens it again
without a view, reads its composite and closes it in the same job. A created document has no file
and no baseline; its branch has both.
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
field (the root's own id changes; a translate mask's move among them), and each node's own pixels over the union of both bounds. ORA: nodes
by rank among stored siblings; then name, visibility, blend, edit lock, inherit-alpha, and each
layer's pixels against the live projection. Masks and adjustment layers (`node`), clone, file, vector
and fill types (`type`), `alpha_locked` and rounded opacity are listed in `expected_losses`. A lost
node never excuses a composite difference: a blur filter mask, cropped to the layer's bounds by ORA,
fails the save, and so does a translate, whose transform mask ORA drops with its move (measured).

**ORA's opacity.** Krita writes it to six significant digits and truncates on load, so 127 of the 256
values come back one lower. A visible one changes the composite, so that save fails.

`document.save_finish {save_id, merged_sha256, merged_problem}` runs under an operation id derived
from the save's (`finish_operation_id`), so every poll and retry gets the finish's own outcome, and
one refused retryably runs again under it (*The bridge contract*). Its lease refusal alone is
retryable for that, so a server that is not the holder never locks the holder's finish. It
compares the written file's inode, size and modification time with what the save took, and the server's
`mergedimage.png` hash with the live composite's. It then `os.link`s the file into place and unlinks it,
or, where links fail, checks `lexists` and renames. It clears dirt only if `Handle.changes` is
unchanged, and then keeps what the save compared as the handle's `saved_state`. A duplicate's
finish clears nothing and keeps no state: it records the placed file for `document.duplicate_open`
(*Documents*). Its receipt adds
`dirty`, `krita_modified` and `document_path`, the file the live document still points at, since
the export moves neither (K39, K45). A new verified save, a close or a document gone from `sync` drops a save never finished,
and folders the save made go with it, deepest first and only while empty.

The server's `_merged` never raises, so the finish is always sent. A problem reading the file goes to
the plugin as `merged_problem`, which discards it.

**What a failed finish says.** The save itself reached Krita and wrote its hidden file, so a
finish's failure keeps `not_applied` only on proof:
- **When it stands.** The finish states it, with `rollback_verified: true` (its own discard of the
  file and folders confirmed), in the save's own Krita session.
- **When it never stands.** A save that replaced an earlier unfinished save never keeps it, since
  that save's file went with it (`replaced_pending` in the save's own result, kept out of the
  receipt).
- **Everything else is `uncertain`, not retryable:** a refusal at job start, a restarted Krita, a
  finish that reached no bridge, a session mismatch. The hidden file then stays, the known debt
  below.
- **What a retry does.** For a finish this process sent and Krita refused retryably, the message
  says that retrying the save under its `request_id` finishes it. That retry is a same-session
  resend: the bridge dedups the save, and the finish runs again in the retrying process. A
  finish cancelled at Krita's quit, or one another process's poll reads, gets no such sentence,
  since its retry would meet a new session or another process's lease.

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
`Known(tool, receipt, resolve, finish)`, and a test holds it complete. The duplicate's first op is
`document.duplicate`, not the save's, so its receipt and finish are its own (F9). Images are found by operation
id before they are made. A second server that took part in a retry gets a null image rather than a
failure, because the first server took the pixels.

**`krita_operation_get`** adds `outcome`, `receipt_valid` and `receipt_problem`, all null while the
call is queued or running. It returns a raw receipt as data, survives one that raises, and settles the
journal on every path. When the bridge cannot answer, because Krita restarted or has gone, a finished
line answers with its own outcome; with no line it stays `uncertain`.

**A poll finishes a save or a duplicate only in the process that made the call.**
- **The record.** `BridgeClient._made` holds the id of every call this process sent with a
  `request_id`, and the id the bridge answered it under. Reads, whose ids the process mints, are
  never polled for a finish, so they stay out of it. `_sent`, which pins a running call's session, also takes ids a
  poll followed, so it cannot say who made a call.
- **The maker's poll** runs the finish, and a duplicate's open after it.
- **Any other poll only reads.** It GETs the finish's own record and reports it with the save's
  identity. If the bridge holds no finish, it reports the save `uncertain`, with a message saying
  that retrying the save under its `request_id` finishes it.
- **Why not the journal.** It cannot decide this: two servers on one data folder read the same
  lines.

**The duplicate's chain** (`tools/branching.py`). The save's finisher, given the tool's name, places
the file; then `document.duplicate_open` runs under an id derived from the duplicate's
(`open_operation_id`), and the answer keeps the duplicate's identity. Step one fails as a save
does, and step two by the finish's rule. Step three's failure is always `uncertain` and never
retryable, whatever the open states, because the file is in place; it carries `details.path` and
`sha256`, and `rollback_verified: false`, since nothing of the call was rolled back. Refused
retryably in the duplicate's Krita session, it says a retry under the same `request_id` opens the
branch, which reruns the open under its id. An open that never reached the bridge (unsent, or
`unregistered`) says the same retry opens it in this Krita session, and `krita_document_open` after
a restart. Otherwise it says `krita_document_open` opens the file. The shared rule that keeps a
chained step's answer under the call's own ids is `saving.chained`; `saving.Caller` names the tool
a finish answers for. A poll follows the save's rule: the maker of any of the three
ids places and opens; any other process reads the finish's record and the open's, and answers
`uncertain`, saying how to finish, when either was never sent.

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
| Unit (server) | `verify` | Schemas and examples, what Codex renders of them (by a port), argument rules, envelope and errors, roots, journal, client-side dedup, masks, colour maths, preview geometry, the bridge client against a fake bridge, a stdio round trip | Real Krita; a Codex renderer past the port's tag |
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
fails, and a driver must stop if it does. A created document's branch has one, its file, so the
gate takes it like any harness document. A dialog open in Krita refuses calls that read or change a
document, and fails the checks it overlaps. The stock presets `b) Basic-2 Opacity`,
`b) Airbrush Soft`, `y) Texture Spray` and `y) Texture Wood Fiber` must be listed.

**The journal check comes last.** It is the live evidence that `uncertain` stays rare.
- **What it reads.** Every line the probe's servers journaled, through the journal's own reader,
  so a line a later one settled counts as settled.
- **When it fails.** On fewer than 340 dispatched lines, about half a whole run's 753, since that
  means it read the wrong place. Or on any request left with an unknown attempt, which it names:
  uncertain, unregistered, or dispatched with no finished line.
- **What it cannot see.** Reads, harness ops and the probe's own direct bridge calls, none of which
  are journaled.

**N-04's limit.** `probe/writes.py` lists the data directory, strictly, by `DATA_FILES`, and five other
places for new names that look like ours (the cwd, the home folder, Krita's temp folder,
`~/Library/Application Support`, `~/Library/Preferences`), because other processes write in all of
them. It sees what stays after a run, not a file that came and went, and outside the data directory
only those names. `~/Desktop` and `~/Downloads` are left out, because listing them can raise a
permission prompt.

**What the probe measures and does not gate.** A MEASURED line stays only if something rests on it
and no check would notice it changing. The 25 lines:

| Lines | Why they stay |
|---|---|
| Krita's runtime; 11 stage times | The run's condition, and where its time goes |
| `Node.paintPolylineStroke` | The one reader of Phase 6's switch |
| An active selection mask's overlay | Why K46's guard is measured, not checked |
| `setActiveNode` on the global selection's mask | Why K46's global branch is unit-tested only, and why its activation is not undone |
| The tall tip against R's margin | Assumption (b) of the margin model |
| A polygon fill's call | A fill has no budget; its time is measured, not gated |
| N-01 and N-09 opening the master, and their corner-to-corner strokes | Costs no budget gates; Krita's memory is on the backlog |
| Retention after N-01; the journal after N-01 | Growth watches behind backlog items |
| H4's long save, and the refused close after it | A save has no budget, and the close re-reads what the save compared |

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
| H2 | Flat `paintPath` strokes with stock presets read as hand-painted | Passed by hand, 0.14.0: five of six usable. Tapers through `dynamics` since 0.24.0: widths and alpha follow the knots against plain reference strokes, in the probe |
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
- The save has a ladder of its own, and a selection pushes its step outside the frame, with no
  verdict.
- The journal is permanent and unbounded.
- A Krita crash mid-save, or a finish that never ran, leaves a hidden file nothing sweeps.
- A duplicate placed but never opened stays at its path, a file of the agent's; a retry or
  `krita_document_open` opens it.
- Labels are English; region scope is the pixel engine only; filters are classed by type.
- Selection steps and a translate's params steps are confirmed by state alone.
- Scale, rotate and shear take no masks and no layer kinds but paint layers and groups, are not
  limited by the selection, and stop history for good at the owner's own transform of the same name.
- Undoing the attach of a copied transform mask crashes Krita (K53), so a layer holding one is not
  duplicated. An ORA drops a translate, so such a save is refused.
- Erasing, a single dab and antialiasing off are refused.
- The global-mask branch of K46, layer styles and the mirror restore are held by unit tests or by
  nothing live.
- A taper's reload route is held by unit tests and E1's measurement. In the probe, the paint
  checks before it leave its preset dirty, so the restore there is by XML alone. Tapers are refused
  under a changed dirty-presets setting, on mask paint, and on engines other than the pixel engine.

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
| K49 | `paintPath` with stroke `None` and fill `ForegroundColor` fills the path with the painter, never the paint op; a wash-mode preset paints through an indirect device, and a masked brush paints the path into its mask painter too | `libs/libkis/PaintingResources.cpp:17-58`; `libs/image/kis_painter.cc` (`paintPainterPath`, `fillPainterPathImpl`); `libs/ui/tool/strokes/KisMaskedFreehandStrokePainter.cpp` |
| K50 | `TransparencyMask` starts from an empty selection; `KisMask::setSelection` adopts its pointer and pushes no undo; a transparency mask's bounds are its parent's; its device is Alpha8, whose composite ops are over, erase, copy, alpha-darken and multiply | `libs/libkis/TransparencyMask.cpp`; `libs/image/kis_mask.cc`; `libs/image/kis_transparency_mask.cc`; `libs/pigment/colorspaces/KoAlphaColorSpace.cpp` |
| K51 | `Preset.fromXML` edits the preset in place and sets it dirty; the view's current preset and `Preset(resource)` are one object; `reload_preset_action` reloads the current preset from storage and clears the flag; the resource model's `Dirty` column says whether a preset holds unsaved changes. The Distance sensor reads `length` as an integer, and in a scripted stroke counts the first dab's distance from the canvas origin; a curve's `is_corner` points run straight | `libs/libkis/Preset.cpp`; `libs/ui/kis_paintop_box.cc` (`slotReloadPreset`); `libs/resources/KisResourceModel.h`; `plugins/paintops/libpaintop/KisSensorData.cpp`; `libs/image/kis_painter.cc` (`paintPainterPath`); `libs/image/kis_cubic_curve.cpp`; measured |
| K52 | `Node.remove()` runs one `KisImageLayerRemoveCommand` ("Remove Layer"), which takes each node of the subtree off its own parent and turns the removed layers' clones into paint layers, undone together; `addChildNode` runs one `KisImageLayerAddCommand` ("Add Layer"), above `above` or on top; `Node.duplicate()` clones the subtree with a new uuid for every node and pushes no step; `setName` and `setVisible` on a detached node push none | `libs/libkis/Node.cpp`; `libs/image/commands/kis_image_layer_remove_command.cpp`, `kis_image_layer_remove_command_impl.cpp`, `kis_image_layer_add_command.cpp`; `libs/image/kis_base_node.cpp`, `kis_node.cpp`; measured |
| K53 | `TransformMask.fromXML` runs a `KisSimpleModifyTransformMaskCommand` under a bare `KUndo2Command` through `runSingleCommandStroke`, named after its empty text, and does not wait; a fresh mask holds the transform tool's free transform at identity; `toXML` writes attributes in a per-session hash order; an affine mask renders through its worker until a static cache rebuilt 3000 ms later; `KisRecalculateTransformMaskJob::run` uses its layer's image unchecked, and undoing the attach of a copied transform mask crashes Krita there | `libs/libkis/TransformMask.cpp`; `libs/image/kis_processing_applicator.cpp`; `libs/image/commands_new/KisSimpleModifyTransformMaskCommand.cpp`; `libs/image/kis_transform_mask.cpp`; `libs/image/kis_recalculate_transform_mask_job.cpp`; measured |
| K54 | `Node.scaleNode(origin, w, h, strategy)` scales by w and h over the exact bounds' size about `origin`, taking an unknown strategy as Bicubic; `rotateNode(radians)` turns about the exact bounds' centre, Bicubic; `shearNode(degX, degY)` shears x then y about it, Bilinear, and pushes no step when `mapRect` keeps the bounds' size; each is one processing step ("Scale Layer", "Rotate Layer", "Shear Layer") that waits and returns silently for a mask; the visitor resamples every paint device and mask selection below, maps a transform mask's params, and moves the node's clones; rotate and shear move a layer's offset; a resample leaves colour under alpha 0 outside the exact bounds | `libs/libkis/Node.cpp:695-743`; `libs/image/kis_image.cc:1078-1340`; `libs/image/processing/kis_transform_processing_visitor.cpp`; `libs/image/kis_transform_worker.cc:59-67`; measured |
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
- A fill (`paintPath(path, "None", "ForegroundColor")`), on 0.21.0's measurement under one stock
  preset of each engine: one "Scripted Brush Stroke" step that one undo takes back; nothing past
  the shape at brush size 300, while a bad style string paints its outline 134 px out; opacity 0.5
  gives alpha 128; multiply over (200, 120, 40) with (230, 60, 30) gives (180, 28, 5); alpha lock
  keeps every alpha byte; a feathered selection's coverage is the fill's alpha exactly; an
  ellipse's edge is antialiased and an integer rect's is not. Wash-mode presets differ only by
  colour under alpha 0, up to 3 px out. A fill takes under 15 ms on a 400 × 300 canvas.
- Transparency masks, on 0.22.0's measurement: `createTransparencyMask` gives an `A`/`U8` mask that
  reads all 0 and hides its layer once attached; `setSelection` before `addChildNode` lands the
  selection's bytes exactly, in one "Add Layer" step that one undo takes back, and marks Krita's
  flag. An inverted empty selection reads 255 past the canvas, a canvas rect 0. The new mask becomes
  the active node; no overlay enters a composite read. The composite is `rint(layer × c + below ×
  (1 − c))`. Paint, fills and strokes alike, follows the mask paint rule in *Painting*, one
  "Scripted Brush Stroke" step each. `setVisible` and `setName` push no step, and the composite
  shows `visible` only after a refresh (K42). A KRA save keeps a mask, its id and its bytes; an
  ORA save bakes it into its layer and lists it lost.
- A selection's bounds run past the canvas: an inverted rect's are 448 × 320 on a 400 × 300 canvas,
  and a rect grown or feathered at the corner starts at −10 or −12.
- A 20 × 16 rect grown, shrunk and feathered by 3 lands on {17, 11, 26, 22}, {23, 17, 14, 10} and
  {17, 11, 26, 22}.
- `eraserMode()` read false after `setEraserMode(True)` with every preset tried.
- No dab without length: one point, two equal points and 0.01 px painted nothing; 0.5 px painted one.
- Pan is reachable through the canvas controller's scroll bars, zoom and rotation through `Canvas`.
- Tapers, on 0.24.0's go/no-go: `fromXML` changed the preset that painted, and `Preset(resource)`
  read the same edit, so the two are one object. The dirty column read false before the brush was
  set and true after `fromXML`. `set_brush` alone dirtied a build-up and an image-tip preset, but not
  the wash one.
  - The restore, by the preset's XML then a reload when it was clean before, gave back its digest
    and flag on every case. An unsaved spacing tweak survived a taper. The preset files and bundles
    hashed the same before the edit, during it and after.
  - Without the offset, every taper on a 1500 px stroke peaked at about a quarter of its length,
    330 px late for a start 335 px from the origin. Short and curved strokes whose start lay
    farther from the origin than their length painted their end value throughout. Compensated,
    widths matched plain reference strokes at every knot, on short, long and curved strokes.
  - Krita echoes the curve string as written.
- Layers, on 0.25.0's go/no-go and probe, on harness ORAs:
  - `remove()` returned true, read "Remove Layer", and left its wrapper reading the node's name and
    id, which `_node` could no longer find. The composite showed the removal without a refresh.
  - `addChildNode` took that wrapper back, into the root and into a group, with the same id, as
    "Add Layer"; two undos gave the tree back exactly, and two redos the move. Krita's flag was set.
    Removing the active layer made the one below it active; an attach made the added node active.
  - A removed group came back empty, and its children stayed off it: Krita's remove takes each node
    off its own parent. Re-added one at a time, a group with a masked layer came back whole, its
    mask's bytes the same.
  - `duplicate()` gave a group, its layer and its mask new ids, kept names, collapsed and
    pass-through, and pushed no step; named and hidden before the attach, the copy left the
    composite unchanged, a visible opaque source included, in one "Add Layer" step that one undo
    took back. The copies' layer and mask bytes equalled the source's.
  - Removing a layer a clone shows turned the clone into a paint layer with a new id; one undo
    brought the clone back.
  - The global selection's mask goes on top of the root's children when a selection is set, a
    root layer added after it goes above it, and undoing a clear puts it back at its old index.
- A branch, on 0.26.0's probe, on a harness ORA working copy: every node kept its id and type
  through the duplicate's KRA (paint layers, a group, a transparency mask, a filter layer and mask,
  a transform mask, a clone layer, a local selection mask and the global selection's), and its
  protection. Krita opened the file the finish linked into place, and its as-opened composite
  equalled the source's composite read just after the duplicate. The source's `dirty` and
  `krita_modified` stayed as they were, and every layer's own pixels.
- Translate, on 0.27.0's go/no-go, on harness ORAs: a paint layer, a group and a pass-through group.
  - The attach is one "Add Layer" step that changes no composite byte; each `fromXML` is one step
    with an empty label, and two back to back stay two.
  - An integer move shifts the layer's or group's projection by exactly its pixels (0 bytes differ);
    the layers' own pixels never change; `finalAffineTransform` reads (1, 0, 0, 1, dx, dy).
  - Each undo and redo gives back the params' text, the composite read without a refresh, the tree
    and every node's pixels. Nothing changes 4 s later, inside a job or between jobs, when the
    3 s cache rebuild runs.
  - `toXML` is stable within a session and unchanged by a fill, a refresh, a reorder and a remove
    each undone; a duplicate's mask has its source's.
  - KRA saves within 3 s of a move, an undo or a redo verify; reopened, each mask keeps its id and
    params, a rotated one too. An ORA drops the mask, so its reopened composite is the unmoved one.
  - Undoing the attach of a copy of a layer holding a transform mask, translated or at identity,
    crashed Krita in `KisRecalculateTransformMaskJob::run` four times of four, 4.5 s after the copy
    too. Removing that copy, removing or reordering a hidden translated layer, and undoing a translate
    on a hidden layer did not.
  - A mask added after a translate sits above the transform mask and stays where it is painted.
- Scale, rotate and shear, on 0.28.0's measurement, on harness ORAs: paint layers, an isolated, a
  pass-through and a hidden group.
  - Each is one step, "Scale Layer", "Rotate Layer" or "Shear Layer"; undo, redo and a second undo
    give back every node's bounds, offset and own bytes and the composite; nothing changes 4 s later.
  - A scale lands on the size asked about the bounds' centre for every filter, on flat paint; an
    unknown filter name gave Bicubic's bytes. `filterStrategies()` lists eight.
  - Rotate turns clockwise for positive degrees; shear moves rows below the centre right for a
    positive x and columns right of it down for a positive y, x first (a shear of [-4, 3.6] on a
    12 x 8 layer at (8, 8) changed it, which any other order keeps).
  - A shear Krita's `mapRect` keeps pushed no step and changed nothing, at every threshold tried;
    the replica agreed.
  - Rotate and shear move a layer's offset; scale does not. A half turn of a flat rect changed no
    byte, bounds or composite, moved the offset, and pushed a step.
  - A group's bounds are its shown layers'; its layers, a hidden one too, turn about its centre. A
    hidden group's bounds were current after a refresh.
  - After a 30 degree turn, a layer held the marker's colour under alpha 0 a pixel outside its exact
    bounds; a witness that padded the old bytes with the default pixel failed the leak's rollback
    there.
  - A KRA save after each verified. At 4096 x 4096 each took under a second.
- Krita's memory grows across large opens and saves, to 2 GB or more in a probe run; a restart resets
  it. A Krita holding 87 documents ran document ops about three times slower, and left the paint
  benchmarks, the preview benchmark and H4 idle alone.

## Baseline (v0.28.0)

Taken on 2026-11-12 on Krita 5.3.4.1, macOS, Apple Silicon, on a Krita restarted that session, with
**0 documents open**. The probe prints the open-document count beside its time, because document ops
depend on it: 87 open documents cost about 50 s more.

| Check | Expected |
|---|---|
| `uv run scripts/verify.py` | 6 stages, all PASS |
| Server tests (3.12) | 1152 passed, 0 skipped |
| Plugin-core tests (3.10) | 1201 passed, 0 skipped |
| `uv run krita-art-mcp probe` | 226 PASS, 0 FAIL, 25 MEASURED; 257 s under a load average of 3.4, about 145 s on a quiet machine at 0.27.0; the scale, rotate and shear checks take about 4 s |
| `uv run krita-art-mcp doctor` | 6 steps, all PASS, with a root allowed |
| Registered tools | 25 |
| Schema files | 25 |
| Error codes | 30 |
| Bridge ops | 39 |
| Bridge protocol; `api_version` | 1; 0.4.0 |
| Server instructions | 3,371 of 4,096 characters, at least 700 spare |
| CLI commands | 5 |

A documentation or refactoring change should not move any of these. If one moves, that is the
finding.
