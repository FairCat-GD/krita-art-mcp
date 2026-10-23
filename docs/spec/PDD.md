# Product Design Document: krita-art-mcp

> **Legend:** each part carries a status tag: `[draft]`, `[in review]` or `[locked]`. **Confirmed** = the owner confirmed it (Appendix E, dated). **Proposed** = needs the owner's answer at the Session 0 intake (Appendix C). **Verified** = checked against source code, an installed package or official docs on 2026-10-22 or 2026-10-23, reference given. **To measure** = must be probed on the installed Krita before it is relied on. Parts 9 and 11 of the standard template are dropped (no telemetry, no business model).
>
> **How to read this.** This document describes the whole product, all six phases. Round 1 builds Phase 1 only (Appendix C, Q2), but every Phase 1 interface must leave room for the later phases described here. The contract package written on 2026-10-22 is the second input (Part 2). Its schemas are the starting point for every tool; this PDD lists where Phase 1 deviates from them, and **where the two disagree, this PDD wins**.

---

## Part 0: Document Control

| Field | Value |
|---|---|
| **Product name** | krita-art-mcp (Appendix E, 2026-10-23) |
| **Document owner** | The owner |
| **Version** | 0.4 |
| **Status** | Design |
| **Current focus** | Session 0 intake |
| **Last updated** | 2026-10-23 |

**Changelog**

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-22 | The owner | Initial draft: a 17-tool trial build |
| 0.2 | 2026-10-22 | The owner | Rebuilt around the contract package and the owner's decisions on it: phased roadmap, Phase 1 = its MVP minus the deferred areas, construct phase (filters, transforms, colour), Krita 6.1 input-aware strokes, full tool map; independent review fixes applied; project profiles moved to Phase 2; `paint_shape` moved to Phase 2; named krita-art-mcp |
| 0.3 | 2026-10-23 | The owner | Final pass: independent consistency and architecture reviews applied |
| 0.4 | 2026-10-23 | The owner | Contract review: verified layer property changes and history, a provable verification scope, save checks against `mergedimage.png`, per-source preview scales, one writer per document |

---

## Part 1: Vision [draft]

**Elevator pitch**

A reusable art workstation for AI agents: an MCP server and Krita plugin that let an agent inspect a painting, protect accepted work, paint with Krita's real brush engine, check the result at game size, and undo or keep it, for every 2D game the owner makes.

**Problem statement**

The owner's games use AI agents as artists. A Codex agent generates first drawings with an image model and corrects them with Python scripts (Pillow and NumPy): selections blended at partial opacity, local warps, protected edge bands. Those scripted corrections leave fringes, humps, seams and speckle that a hand-painted correction would not; The first game's art reviews kept rejecting exactly these. The review standard asks for corrections painted in the master by hand, and no agent has a brush. Beyond corrections, new drawings, painted UI, animation frames, tiles and backgrounds all need the same thing: precise, protected, reversible painting that an agent can see.

No existing Krita MCP server fits (Part 2): the ones found are 1 to 38 commits old, none reports a macOS test, and they paint with their own pixel renderers or expose raw pixel writes and arbitrary Python.

**Product pillars**

1. **Brush first; every other pixel change is explicit.** Painting goes through Krita's own brush engine. Non-brush pixel operations (filters, transforms, colour and palette conversion, imports, flat fills) exist only as named, explicitly requested operations that the project profile permits, on unprotected working layers, each one undoable and journaled. Nothing is hidden cleanup. No tool writes raw pixel bytes into a layer and no tool runs arbitrary code.
2. **Accepted art is protected.** Existing layers are protected by default. Changes outside the allowed region are detected and rolled back.
3. **Every change is observable, and reversible wherever Krita allows.** Every mutation returns where it changed and what it verified, and is journaled; its receipt states whether it is a native undo step, because a few Krita property changes are not (K22).
4. **See it at the size it will be seen.** Game-size previews use the asset's real review scales (explicit recipes in Phase 1, the project profile from Phase 2), never fit-to-window screenshots.
5. **One core, many games.** Game-specific rules live in versioned project profiles, never in the server. It behaves the same from Codex and Claude Code, and on Krita 5.3, 6.0 and later.

**Non-goals**

- Pixel-art authoring and pixel animation: those stay in Aseprite. Aseprite exports may be read as immutable references or composition inputs.
- Image generation or AI diffusion inside Krita.
- Headless operation: it drives a running Krita with its GUI.
- Remote or multi-user use: loopback only, one Krita instance, one main window.
- Engine-specific logic in the core: engines are reached through adapters (Phase 4).
- Windows and Linux before the roadmap reaches them: Phase 1 is macOS on Apple Silicon; the code stays portable.

**Target user**

AI painting agents working on painted (non-pixel) 2D game art: a Codex agent, and Claude Code sessions in the Claude desktop app, operated by one solo developer on one Mac.

**Value proposition & the hook**

An agent paints one stroke along an asset's rim with a textured Krita brush on its own layer, and the receipt says how many pixels changed outside the allowed region (zero). A preview sheet shows before and after at both game sizes over the river colour. If it is wrong, one call takes it back.

**Category**

Developer tool: a local MCP server with a companion Krita Python plugin.

**Platforms**

macOS (Apple Silicon, the owner's Mac). Krita 5.3.x (Qt 5) and 6.0.x (Qt 6) now; Krita 6.1 / 5.4 when released (Phase 6). MCP clients: Codex (`~/.codex/config.toml`) and Claude Code (desktop app; `.mcp.json` or user scope).

**Usage shape**

Bursts during art production: an agent session of 10 to 300 tool calls on one to five documents, a few times a week. The owner watches Krita while it works and does not paint in it at the same time.

---

## Part 2: Inputs and prior art [draft]

**The contract package (2026-10-22), the main requirements input**

Contents: a workflow brief, a contract README, 27 MVP tool definitions with input and output JSON Schemas (`mvp.tools.json`), a 69-tool catalogue (`tools.json`, `TOOL-CATALOGUE.md`), a paint-to-export example, six error examples, a starter profile schema with two demo profiles (world-unit painted sprite; high-resolution UI), offline consistency scripts, and an earlier correction pass of the first game as historical context. It contains no server, plugin or real assets. Session 0 copies it unchanged into the repo under `docs/spec/reference/contract-package/` (Appendix C, Q12).

What this PDD does with it:
- **Adopted:** the workflow (inspect → protect → paint precisely → inspect at game size → undo or keep → save and verify), the tool names, the request and result envelope, the coordinate and colour conventions, protection-by-default, request IDs, capability reporting, the acceptance exercises, project profiles (moved to Phase 2 by the owner), and the whole extension catalogue as the roadmap. Where this PDD places the contract's extension tools in Phases 2 to 5 is itself a proposal (Appendix G).
- **Deferred to later phases by the owner (2026-10-22):** document revisions and stale-edit detection, edit transactions and checkpoints (Phase 3); registration, export and validation (Phase 4); project profiles (Phase 2, ruled the same day).
- **Amended:** wherever a verified Krita fact (Part 8) contradicts an assumption in the package, for example per-point pressure on released Krita, tool-level smoothing, undo grouping, cancelling a running operation.

**Prior art: existing Krita MCP servers** (read from each GitHub README on 2026-10-22; borrow code only from MIT or CC0 projects, with attribution)

| Project | Licence | Platform tested | Take | Avoid |
|---|---|---|---|---|
| nanayax3/krita-mcp (35 stars, 1 commit) | MIT | Win/Linux/macOS paths listed | Plugin layout: HTTP on loopback, main-thread queue | Its stroke uses its own pixel renderer |
| AleisterCodely/krita-mcp (fork) | MIT | not stated | Native-brush stroke path; Codex `tool_timeout_sec = 300` | 2 commits |
| fanzhuyifan/krita6-mcp (38 commits) | MIT | Linux, Krita 6.0.3; "Independent of KDE/Krita" | Timeout reconciliation; `doctor`; root allow-lists | Early alpha; Krita 6 only; macOS untested |
| cyyprezz/krita-codex-mcp (v0.2.0) | MIT | Windows only | Token-authenticated loopback bridge; no arbitrary-code tool | Windows-only bridge |
| SanSaSane/krita-mcp | CC0 | Windows, Krita 5.3.3 | Bridge discovery via a port-and-token file; `krita_busy` instead of hanging | `close_document` crashes Krita about 1 in 5 at the end of long sessions (its README) |
| zfd0/krita-canvas-mcp | unknown | Krita 6.0.4 | Ideas only | Exposes `write_pixels`; licence unknown, copy nothing |

None is official: there is no KDE/Krita MCP server.

---

## Part 3: Users & Jobs [draft]

**Personas (ranked; the first wins conflicts)**

1. **The painting agent.** A Codex agent or a Claude Code session. Sees the canvas only through captures and previews, places strokes by coordinates, works from written reviews that name exact defects, and also builds new drawings.
2. **The reviewing agent.** Uses only tools that change no pixels: inspection, capture, sample, preview, read-only opens.
3. **The owner.** Installs it, approves profiles and permissions, watches Krita while an agent works, owns art acceptance. Uses the desktop apps, never a terminal.

**Jobs to be done**

- When a review names a defect in an accepted master, the painting agent wants to paint the fix on its own layer with a real brush, with the accepted pixels provably untouched.
- When it has painted, it wants before and after at every game size of that project, over the game's backgrounds, so it judges the fix as the player will see it.
- When a stroke is wrong, it wants one call to take it back exactly; when a retry happens after a timeout, it wants no second stroke.
- When it builds a new asset, it wants documents, layer groups, references, guides, and later explicit transforms and filters, inside the same protections.
- When it works on another game, it wants that game's units, scales, palette and permissions loaded from a profile, with nothing leaking from the last project (Phase 2; until then it passes those values explicitly).
- When reviewing, the reviewing agent wants exact colour readings (hex, L\*a\*b\*, L\*C\*h) and native-resolution crops.

**First-run experience (the owner, once)**

1. A coding agent clones the repo and runs `krita-art-mcp install-plugin`, which copies the plugin into Krita's `pykrita` folder.
2. Restart Krita, enable the plugin in *Configure Krita › Python Plugin Manager* (on macOS, Configure Krita is in the application menu), restart Krita again (Krita's documented flow).
3. A coding agent runs `krita-art-mcp roots add <path>` for each folder agents may touch.
4. Register the server in Codex and Claude Code (Part 8).
5. Ask an agent to call `krita_server_info`. It returns Krita's version and the capability matrix, or names the exact missing step.

---

## Part 4: Core Experience [draft]

**Core loop (per change)**

`krita_document_open` (working copy, existing layers protected) → inspect (`krita_document_inspect`, `krita_capture`) → prepare (`krita_layer_create`, `krita_selection_set`, `krita_protection_set`) → `krita_paint_stroke` (verified per stroke, auto-undone on violation) → `krita_preview_render` at game size → keep or `krita_history_step` → `krita_document_save` (verified by reopening).

### The phases (the whole picture)

| Phase | Theme | Tools (all with `krita_` prefix) | Depends on |
|---|---|---|---|
| **1** | **MVP: observe, paint safely, deliver** (the contract's MVP-A/B/C minus the deferred areas) | A: `server_info`, `document_list`, `document_open`, `document_create`, `document_inspect`, `resource_list`, `capture`, `sample`. B: `layer_create`, `layer_update`, `selection_set`, `protection_set`, `paint_stroke`. C: `history_step`, `operation_get`, `operation_cancel`, `preview_render`, `document_save`, `document_close` (19) | |
| **2** | **Construct:** project profiles, explicit non-brush operations and layer management for new artwork | `project_load`, `paint_shape`, `transform_apply`, `filter_apply`, `color_convert`, `palette_manage`, `paint_fill`, `paint_path`, `paint_clone`, `canvas_resize`, `layer_duplicate`, `layer_reorder`, `layer_remove`, `layer_import`, `mask_edit`, `document_duplicate`, `reference_set`, `guides_set`, `view_set` | 1 |
| **3** | **Integrity:** revisions, stale-edit detection, transactions, checkpoints, recovery | `checkpoint_create`, `edit_begin`, `edit_commit`, `edit_rollback`, `diff_measure`, `recovery_list`, `recovery_open`, `diagnostics_get`; `expected_revision` on every guard | 1, 2 |
| **4** | **Delivery:** registration, registered export, validation, engine handoff | `registration_set`, `asset_export`, `validation_run`, `asset_metadata_set`, `export_batch`, `atlas_pack`, `engine_package` | 1, 2, 3 |
| **5** | **Asset modules:** animation, tiles, backgrounds, UI, text and vector | `animation_inspect`, `animation_frame_edit`, `animation_clip_set`, `animation_preview`, `animation_export`, `tile_configure`, `tile_preview`, `tileset_export`, `scene_render`, `background_preview`, `ui_preview`, `text_edit`, `vector_edit` | 1, 2, 4 |
| **6** | **Input-aware strokes on Krita 6.1 / 5.4:** per-point pressure, tilt, rotation and timing in one stroke | No new tools: `paint_stroke` gains the `stroke.per_point_input` capability; `view_set` gains canvas change signals | 1 (and 2 for `view_set`); Krita 6.1 / 5.4 released |

Every one of the contract's 69 tools is placed in Appendix G. Phases 2 to 6 each become their own round under the development workflow, with their own intake; this part gives each enough shape that Phase 1 does not paint them into a corner.

**Design-for-later rules Phase 1 must follow**

- Tools take explicit values (scales, backgrounds, working folder) in Phase 1, in exactly the shape a Phase 2 profile will later supply, so profiles become defaults rather than a new code path.
- Document reads carry `frame` (Phase 1 accepts only 0) so animation needs no breaking change.
- Every `paint_stroke` point already carries every field of Krita 6.1's `StrokePoint`, so Phase 6 adds no fields.
- The result envelope keeps a `revision` field, always `null` until Phase 3.
- The job system reports long blocking Krita calls honestly: libkis saves are synchronous [K14, K45], so a later `checkpoint_create` runs as a budgeted blocking job that reports `running`, never as background work.
- The capability matrix in `krita_server_info` is the single place a later feature announces itself; tools never probe Krita versions on their own.

### Conventions (all phases)

- **Coordinates:** document pixels, top-left origin, x right, y down, independent of zoom, pan, rotation, window size and Retina scaling. Rectangles are `{x, y, width, height}`, half-open. Brush points are continuous; a one-pixel dab at cell `(x, y)` is centred at `(x + 0.5, y + 0.5)`. Layer offsets are reported, never silently applied.
- **Affine arrays:** six numbers, row-major `[m00, m01, m02, m10, m11, m12]`, `x' = m00·x + m01·y + m02`, `y' = m10·x + m11·y + m12`.
- **Colour:** `{"space": "srgb", "rgba": [r, g, b, a]}`, straight alpha, floats 0 to 1. Converted once into the document's profile. Phase 1 paints only RGBA / U8 / sRGB documents and requires `a = 1` (transparency comes from brush opacity).
- **IDs:** `document_id` is assigned by the plugin per open document and valid until it closes or Krita restarts; documents the owner opened by hand get ids too, but are read-only for agents. Layer ids are Krita's `Node.uniqueId()` as lowercase UUIDs without braces. KRA saves and restores them, so they survive a KRA round trip [K39]; ORA and PNG do not store them, so a reopened ORA or PNG gets new ids, and agents match its layers by name and order. Layer names are otherwise labels.
- **Guard:** every mutating call carries `guard: {document_id, request_id}`. Opens, creates, profile loads and file writes carry `request_id` too. `expected_revision` arrives in Phase 3; until then it is rejected as an unknown field.
- **One writer per document (Phase 1):** the first server process to mutate a document holds its writer lease (process id and start time, sent with every bridge call). Mutations from any other live server process fail with `DOCUMENT_IN_USE`; reads stay open to everyone. The lease passes on once its holder's process has exited, so a restarted server takes over its own work. Serialising jobs alone would not stop two agents interleaving "set selection, then paint"; until Phase 3, each agent works on its own working copy.
- **Request IDs:** a retry with the same `request_id` and canonical arguments returns the original receipt without repeating the work. The same id with different arguments fails with `REQUEST_ID_CONFLICT`. Deduplication happens in the bridge, which maps `request_id` to its operation for the whole Krita session, so a retry is safe across server restarts and between clients. The server journals each call as dispatched before sending it and as finished afterwards; a call whose Krita session ended mid-flight fails on retry with `INTERNAL_ERROR`, `retryable: false`, `details: {outcome: "uncertain"}`, and is never re-sent. Agents use a fresh UUID per logical call.
- **Envelope:** every tool returns `structuredContent` matching its output schema, `{api_version, status, document_id, revision, operation_id, data, error}`, plus one short text line. `status`: `completed`, `queued`, `running`, `failed`, `cancelled`. Images come back as MCP image content with `_meta: {"codex/imageDetail": "original"}`, capped so one result stays under 6 MB on the wire, because Codex closes the whole MCP connection when a message exceeds 8 MB [C5]; a larger image is returned as a path with a 1600 px inline preview. Mutation receipts carry artifact paths, not inline images, except one capped diff image on failure, and every artifact in `data` is the contract's `{uri, mime_type, sha256, size_bytes}` plus `path` and `retention_days`. Until Phase 3, every `uri` and `mask_uri`, in inputs and outputs, is an absolute file path inside an allowed root (an output's `uri` equals its `path`); Phase 3 adds `krita-artifact://` resource URIs and keeps accepting paths.
- **Errors:** MCP `isError: true` with the envelope's `error: {code, message, retryable, details}` and a one-line text summary. Validation findings are successful calls with failing checks in `data`. Codes: `INVALID_ARGUMENT`, `UNSUPPORTED_CAPABILITY`, `KRITA_NOT_RUNNING`, `PROTOCOL_MISMATCH`, `KRITA_MODAL_DIALOG`, `MULTIPLE_WINDOWS`, `BUSY`, `TIMEOUT`, `CANCELLED`, `REQUEST_ID_CONFLICT`, `DOCUMENT_NOT_FOUND`, `LAYER_NOT_FOUND`, `LOCKED_TARGET`, `LAYER_NOT_PAINTABLE`, `LAYER_HAS_LOCAL_SELECTION`, `PROTECTED_REGION_CHANGED`, `OUTSIDE_ALLOWED_MASK`, `RESOURCE_HASH_MISMATCH`, `SOURCE_HASH_MISMATCH`, `COLOR_PROFILE_MISMATCH`, `DOCUMENT_DIRTY`, `DOCUMENT_UNSAFE`, `DOCUMENT_READ_ONLY`, `DOCUMENT_IN_USE`, `SAVE_VERIFY_FAILED`, `PATH_NOT_ALLOWED`, `FILE_EXISTS`, `IO_ERROR`, `ROLLBACK_FAILED`, `INTERNAL_ERROR`. Phase 2 adds `PROFILE_INVALID`; Phase 3 adds `STALE_REVISION` and `EXTERNAL_EDIT_CONFLICT`; Phase 4 adds `EXPORT_CLIPS_ART`.
- **Strictness:** every input schema rejects unknown fields. Never clamp coordinates, normalise colours, ignore an unsupported setting or substitute a resource: fail with the precise code, or apply and report the effective value when Krita adjusts it. Points outside the canvas grown by half the brush size are `INVALID_ARGUMENT`; canvas growth is never automatic. No tool relaxes a project's profile, limits or checker to make an asset pass.
- **Long calls:** every call runs as a job. If it has not finished within the wait budget (default 45 s, under Codex's default 60 s tool timeout), the tool returns `status: running` with an `operation_id`; the agent calls `krita_operation_get`. The server enforces the budget itself, because the bridge cannot answer while a Krita call holds Python's GIL [K40].

### Phase 1 tool contract

Each tool starts from the contract's `mvp.tools.json` schema; the deviations listed here win. "Krita" names the calls behind it (Part 8 facts in brackets).

**A. Observe**

- **`krita_server_info`**: Krita version, Qt major, plugin and protocol versions, allowed roots, and the **capability matrix**: `stroke.native_brush`, `stroke.per_point_input` (always false in Phase 1; Phase 6 turns it on [K30]), `stroke.smoothing` (`none`, `catmull_rom`; Krita's tool smoothing is not reachable from scripts), `undo.grouping` (false [K29]), `stroke.deterministic` (false for stochastic presets: no seed control), `operation.cancel_running` (false), `selection.enforced`, `color_spaces`, `filters` (Phase 2), `animation` (Phase 5). Each entry: `{supported, since, notes}`. No writes.
- **`krita_document_list`**: open documents with id, path, size, colour space, `dirty` (a bridge mutation since the last verified save, as `krita_document_close` uses [K45]), mode. Documents not opened through `krita_document_open` are listed with `mode: read_only`, and every mutation on them fails with `DOCUMENT_READ_ONLY`.
- **`krita_document_open`** `{source_path, source_sha256, mode, request_id, working_dir?, editable_layer_ids?, editable_layer_names?}` (deviations: the contract's `project_id` arrives with profiles in Phase 2; `working_dir`, `editable_layer_ids` and `editable_layer_names` added):
  - `mode: working_copy` requires `working_dir` (inside an allowed root, never the source's own folder) and copies the source into `<working_dir>/<UTC timestamp>-<file name>` (Appendix C, Q6), verifies the source and copy hashes (`SOURCE_HASH_MISMATCH`), and opens the copy; the source is never opened for writing. `mode: read_only` opens the source and refuses every mutation on it with `DOCUMENT_READ_ONLY`.
  - Formats: `.kra`, `.ora`, `.png` (other formats only after a harness test on the installed build).
  - Every existing layer becomes **protected**, except those listed in `editable_layer_ids` (KRA, whose ids persist) or `editable_layer_names` (ORA and PNG), used when an agent resumes its own earlier work. Protection is plugin state (the document handle, Part 6), shared by every client, and never changes Krita's own lock flags. Returns the contract's fields (including the `baseline_id` of the `as_opened` composite) plus the layer tree.
  - Captures an `as_opened` composite baseline for `krita_preview_render`.
  - Krita: `Krita.openDocument` with batch mode, then `Window.addView` at once, holding the wrapper [K6, K14].
- **`krita_document_create`** `{name, size_px, color_model, depth, profile_id, background, request_id}` (the contract's `project_id` arrives in Phase 2): Phase 1 accepts `RGBA` / `U8` / sRGB and a transparent background; other depths answer `UNSUPPORTED_CAPABILITY`. Krita: `Krita.createDocument`, then `addView`.
- **`krita_document_inspect`** `{document_id, frame}` (deviation: `frame` added, 0 in Phase 1): layer tree (id, name, type, order, visibility, opacity, blend, locks, inherit-alpha, alpha lock, offsets, bounds, colour space, children, `protected`), active layer, selection bounds and coverage, protection state, allowed-change mask summary, mode.
- **`krita_resource_list`** `{kind, cursor, limit}`: `brush` returns presets with `preset_id` (the resource file name), name, engine, and `preset_sha256` (SHA-256 of `Preset(resource).toXML()`, to measure [K36]); `blend_mode` returns the plugin's whitelist; `profile` and `palette` return what Krita reports.
- **`krita_capture`** `{source: {document_id, frame}, target, layer_id, rect, scale, filter, background?, greyscale?, max_px?}` (deviations from the contract's schema: `revision` removed from `source`; `background`, `greyscale` and `max_px` added): `target` is `composite`, `layer` or `selection`. Native crop at `scale: 1`; otherwise resampled with the named filter (Pillow) after compositing on the background (`checker`, `transparent` or a colour; named profile backgrounds arrive in Phase 2). Result: image content, file path, the exact rect, output size, filter, colour profile and the document-to-image transform. A layer capture is that layer's raw paint device: no layer opacity, masks or inherit-alpha clip [K12]. `max_px` defaults to 1600 and caps at 4096 on the long edge; larger asks must tile. Above the inline limit the full image is returned as a path with a 1600 px inline preview [C5].
- **`krita_sample`** `{source, target, layer_id, points, radius?}` (deviations: `source` as in `krita_capture`, without `revision`; `radius` added): per point, straight-alpha RGBA (0 to 255), hex, CIE L\*a\*b\* D65 and L\*C\*h; with `radius > 0` an alpha-weighted disc mean plus `stdev_L` and pixel count. Composite and layer values are labelled as such.

**B. Paint safely**

- **`krita_layer_create`** `{guard, parent_id, above_id, type, name}`: Phase 1 types `paint` and `group`; `transparency_mask` moves to Phase 2 with `mask_edit`. New layers are editable. Refused inside a protected group only if the group's appearance-affecting properties would change (adding a child is allowed; the per-stroke composite check guards the rest). One undo step [K22].
- **`krita_layer_update`** `{guard, layer_id, properties, verify?}` (deviation: `verify` added, as in `krita_paint_stroke`): `name`, `visible`, `opacity`, `blend_mode` (whitelist), `inherit_alpha`, `alpha_locked`, `locked` (Krita's user lock, editable layers only), plus `active` (krita-art-mcp addition; it only changes which layer the owner sees selected, and no tool's target depends on it). `LOCKED_TARGET` on a protected layer or any ancestor of one. The result states which changes are undoable: only `blend_mode` is [K22]. Opacity, visibility and inherit-alpha changes do not redraw the composite by themselves [K42], so the job ends with `Document.refreshProjection()` and `waitForDone()`. Appearance changes (`visible`, `opacity`, `blend_mode`, `inherit_alpha`) are verified like a stroke, in the same job: the composite is read before and after over the node's exact bounds (or the whole canvas, under the same bounding rule as `krita_paint_stroke`), must not change where the allowed mask is 0, and under `preserve_composite_alpha` must keep every alpha byte. On a violation the plugin restores the previous values (native undo for `blend_mode`, the old values for the rest), refreshes, confirms the composite matches the before-read, and fails with `PROTECTED_REGION_CHANGED`; an unconfirmed restoration is `ROLLBACK_FAILED`. `name`, `locked`, `alpha_locked` and `active` do not change the composite.
- **`krita_selection_set`** `{guard, combine, shape, feather_px, invert, grow_px?, shrink_px?}`: shapes `rect`, `ellipse`, `polygon`, `raster` `{mask_uri, mask_sha256, origin_px}` as in the contract's schema (in Phase 1 `mask_uri` is an absolute path to an 8-bit single-channel PNG inside an allowed root; a hash mismatch is `RESOURCE_HASH_MISMATCH`), `layer_alpha` (from a named layer; folds in the contract's `selection_from_alpha`), `all`, `none` (folds in `selection_clear`). The server rasterises antialiased masks (Pillow, 4× supersampling). The plugin builds on `doc.selection().duplicate()` or a fresh `Selection()`, never mutates the live one, commits with `Document.setSelection` (one undo step) [K8, K11, K23]. Returns the contract's `selection_id` and `mask` artifact, plus bounds and coverage. Deviations: `ellipse`, `layer_alpha`, `all`, `none`, `grow_px` and `shrink_px` added.
- **`krita_protection_set`** `{guard, protected_layer_ids, allowed_change_mask, preserve_composite_alpha, preserve_canvas}`: tightens only; nothing in Phase 1 loosens protection (reopening with `editable_layer_ids` is the explicit route). Each call also sets the document's undo floor and clears its redo allowance, so `krita_history_step` never undoes or redoes a step made under looser protection. To repair several regions, set the allowed mask to their union once and confine each repair with `krita_selection_set`; for a separately scoped correction, save, reopen the saved file with `editable_layer_ids`, and set the new mask. `allowed_change_mask` keeps the contract's `{uri, sha256}` form (a binary 0/255 PNG) or `null` for the whole canvas; krita-art-mcp also accepts `{rect}` and `{polygon}` and rasterises them. `preserve_composite_alpha` makes every paint call also fail if the composite's alpha changes anywhere, inside the allowed mask included (colour may change there, the silhouette may not; the contract's exercise 2); `preserve_canvas` refuses canvas-size changes (Phase 2 tools). The contract's `checkpoint_id` field is removed until Phase 3.
- **`krita_paint_stroke`** `{guard, layer_id, brush, points, smooth?, input_fallback?, verify?}`:
  - `brush`: `preset_id`, `preset_sha256` (optional; mismatch is `RESOURCE_HASH_MISMATCH`), `size_px` (1 to 1000), `opacity`, `flow`, `color`, `eraser`, `blend_mode` (whitelist: `normal`, `multiply`, `screen`, `overlay`, `soft_light_svg`, `darken`, `lighten`, `color`, `luminize`, `behind`), `alpha_lock`, `rotation_deg`. The contract's `smoothing` field becomes `smooth: none | catmull_rom` (server-side); `basic` and `stabilizer` answer `UNSUPPORTED_CAPABILITY`. `antialias` must be omitted or `true` in Phase 1 (to measure per engine). `eraser` with `alpha_lock` is `INVALID_ARGUMENT` [K37]. Spacing and other preset parameters come from the preset and are reported; tuning them is Phase 2. Stochastic presets are not repeatable (`stroke.deterministic`).
  - `points`: 1 to 4096 `{x, y, pressure?, time_ms?, tilt_x?, tilt_y?, rotation_deg?, tangential_pressure?, speed?}`. Deviations from the contract's schema: `pressure` and `time_ms` become optional (defaults 1.0 and none); `rotation_deg`, `tangential_pressure` and `speed` are added so the contract already carries every Krita 6.1 `StrokePoint` field; tilt stays ±90 degrees; the contract's `edit_id` is replaced by an explicit `layer_id` (Phase 3 adds `edit_id`, whose pinned target must equal `layer_id`); `blend_mode`, `alpha_lock` and `rotation_deg` are added to the contract's brush. On released Krita the contract's own example (pressure 0.4) therefore fails unless `input_fallback: "flat"` is given, which is intended.
  - **Input capability:** Phase 1 always paints with `Node.paintPath` at pressure 1.0 [K4] and reports `stroke.per_point_input: false`, even on a Krita build that has `Node.paintPolylineStroke`: that branch cannot be tested on released Krita, so it is built in Phase 6. If any point carries pressure other than 1, tilt, rotation, tangential pressure, speed or timing, the call fails with `UNSUPPORTED_CAPABILITY` unless `input_fallback: "flat"` was given; the receipt then says `input_applied: "flat"`.
  - Applies the brush inside the same main-thread job in a fixed order: preset first (activating a preset resets the composite op), then size, opacity, flow, blend, eraser, alpha lock, rotation, colour [K3]. Reads the brush back and reports the effective values.
  - `layer_id` names the target; libkis paints on that node directly (`libs/libkis/Node.cpp:926-935`), never on Krita's active layer. It must be an editable layer of type `paintlayer` with `paintAbility() == "PAINT"`, without an active local selection mask [K9, K10]; otherwise `LOCKED_TARGET`, `LAYER_NOT_PAINTABLE` or `LAYER_HAS_LOCAL_SELECTION`. Mirror painting and wrap-around mode are switched off for the job and restored [K2, K47].
  - **Per-stroke verification** runs inside the plugin, in the same main-thread job as the stroke, so nothing can land between a stroke and its check or rollback. Region R is the path bounds grown by `max(32, size_px × (0.5 + s))`, clipped, where `s` is the effective preset's maximum scatter (0 without scatter, up to 5 [K44]). R must bound the stroke's whole effect on the target layer and the composite, and the plugin uses it only when it can show that: it parses the preset's reach, and nothing between the target and the composite spreads a change spatially (a filter mask, filter layer or layer style on the target, on an ancestor group or above it in the stack; a transform mask; a clone layer of the target). Otherwise the call answers `UNSUPPORTED_CAPABILITY`, naming the reason, unless `verify: "full"` is given. `verify` is `region` (the default, checks R) or `full` (checks the whole canvas). Before painting, the plugin reads the composite and the target layer in R and hashes every protected layer's pixels in R. After `waitForDone()` it reads them again and checks that no composite byte changed where the allowed mask is 0, that every protected layer's hash is unchanged, that with `preserve_composite_alpha` no composite alpha byte changed anywhere in R, and that the target layer's exact bounds did not grow beyond its earlier bounds plus R. The checks use whole-buffer byte operations, never per-pixel Python loops (masking through `int.from_bytes` takes about 40 ms for an 11 MB region in stdlib Python). On a violation the plugin steps native undo once, waits, re-reads the same scope, confirms that the composite, the target layer's pixels and its exact bounds match the before-read, and the call fails with `PROTECTED_REGION_CHANGED` (`details: changed_outside_px, protected_pixels_changed, rolled_back, rollback_verified`). A failed rollback is `ROLLBACK_FAILED`; the document is marked unsafe and later paint calls on it fail with `DOCUMENT_UNSAFE` until it is reopened. The before, after and diff buffers reach the server as transfer files (Part 8), and the server computes the receipt's counts and images. For a protected layer whose hash changed, the plugin also writes that layer's R before the stroke and after the undo as transfer files, from which the server counts `protected_pixels_changed`. A stroke whose geometry lies entirely outside the allowed mask is refused before painting with `OUTSIDE_ALLOWED_MASK`.
  - Receipt: `stroke_id`, `accepted_points`, `input_applied`, effective brush, `changed_bounds_px` (from the target layer diff in R), `changed_outside_px: 0`, `protected_pixels_changed: 0`, `alpha_changed_px`, `verify_scope` (`{mode, rect}` actually checked), undo label, and paths to before and after native captures of R (not inline). A failure also returns a diff image of the offending pixels, inline and at most 1024 px on the long edge.
  - One call is exactly one Krita stroke and one undo step.

**C. Deliver**

- **`krita_history_step`** `{guard, action, steps}`: `undo` or `redo`, 1 to 50, on that document's view [K7]. Deviations: the contract's required `checkpoint_id` is removed and `restore_checkpoint` arrives in Phase 3; `steps` is capped at 50. Returns the contract's `verified` and `content_sha256` (hash of the composite over the last changed region after the step), and the path of a fresh capture of that region. Every undo or redo is followed by `waitForDone()` before any read, because an undo is itself a stroke. A redo that would re-apply a stroke rolled back by verification is refused with `INVALID_ARGUMENT` [K43]: the plugin counts the redo steps available above the last rollback (an agent undo adds its steps, a redo spends them, any new undo step resets the count to 0). Undo never crosses the undo floor set by the last `krita_protection_set`; a deeper undo is refused with `INVALID_ARGUMENT`. Every step above the floor was either verified under the current protection or changes no pixels, so undoing it changes only pixels the current allowed mask permits. The plugin counts the undo steps each of its operations pushes; the harness confirms each count.
- **`krita_operation_get`** `{operation_id}` and **`krita_operation_cancel`** `{operation_id, request_id}`: state, progress where known, final receipt. Cancel works only for queued jobs; a running Krita call cannot be interrupted, so cancel then answers `UNSUPPORTED_CAPABILITY` with the job's state.
- **`krita_preview_render`** `{recipes, filter, sources, overlays, backgrounds, export_pixels_per_unit?, master_to_export_scale?, tints?, greyscale?}` (deviation: until profiles arrive in Phase 2, the contract's `project_id` and `recipe_id` are replaced by explicit `recipes: [{id, target_pixels_per_unit | target_size_px, integer_zoom?}]`, `filter` (`nearest`, `box`, `bilinear`, `bicubic`, `lanczos`, as in the contract's profile schema), `backgrounds` and `tints`; the contract's top-level `baseline_id` moves into each source): a comparison sheet for each given recipe, at each recipe's scale, over each review background, optionally tinted and in greyscale.
  - `sources[]`: `{document_id, frame, target, layer_id?, baseline_id?, crop_rect?, anchor_px?, export_pixels_per_unit?, master_to_export_scale?}`. Per-source values override the top-level defaults, so a 2× working master (`master_to_export_scale: 0.5`) and an export-resolution sibling (1) sit correctly on one sheet. `baseline_id` pairs a source with its own `as_opened` baseline, shown beside its current state; sources without one, such as accepted siblings, show their current state only. `crop_rect` limits a source to a document rectangle; `anchor_px` is the document point placed on the cells' shared anchor, so siblings line up (centred when absent). The contract's `asset_id` and `registration_id` arrive in Phase 4.
  - World-unit recipes need a `master_to_export_scale` for every source, given per source or as the top-level default (1 when the document is already at export resolution), until registration exists in Phase 4. Scale = `target_pixels_per_unit / export_pixels_per_unit × master_to_export_scale`, per source; exact-size recipes fit `target_size_px`. Recipes with `integer_zoom` render at that zoom with nearest-neighbour sampling. Never resamples an already resampled image.
  - Overlays in Phase 1: `selection` and `allowed_mask` (an addition); `anchor`, `collision` and `envelope` need Phase 4 metadata. Overlays never enter exports.
  - Output: image, path, and per cell the exact document-to-cell transform after rounding, scale, filter, source and baseline.
- **`krita_document_save`** `{guard, path, overwrite: false, verify_reopen: true}`: `.kra` or `.ora` to a new path inside an allowed root; never overwrites in Phase 1. Writes with `Document.exportImage(path, …)` in batch mode, because `Document.saveAs` repoints the working document at the new file [K39]; `exportImage` runs the same KRA export filter as a normal save, `mergedimage.png` included, but never clears Krita's modified flag, and returns false while an autosave holds the document, which maps to `BUSY`, retryable [K45]. Before writing, a selection mask is never left as the active node [K46]. Then verifies, comparing straight-alpha RGBA U8 bytes in the document's sRGB profile (Phase 1 saves only the RGBA / U8 / sRGB documents it paints; others answer `UNSUPPORTED_CAPABILITY`). The live composite, the composite of the saved file reopened read-only in Krita, and the file's `mergedimage.png` decoded by the server without colour conversion must be identical, because `mergedimage.png` is what the downstream pipeline consumes in Phase 1 [K45]. For KRA it also compares image size and profile, the node hierarchy, and per node its type, name, order, visibility, opacity, blend, offsets, inherit-alpha, alpha lock and pixel hashes (computed inside the plugin), masks included. For ORA it compares what ORA stores and lists the nodes ORA cannot store (masks, adjustment layers [Part 6]) as `expected_losses`; a lost node never excuses a composite difference. Any mismatch is `SAVE_VERIFY_FAILED`. Returns the contract's `reopened_verified`, `layers_preserved` (false whenever anything was lost) and `baseline_untouched` (the source file's hash is unchanged), plus `composite_preserved` and `expected_losses` (additions). Saving never changes which file the working document points at.
- **No PNG export in Phase 1.** The owner deferred export to Phase 4. Saved ORA and KRA files carry a `mergedimage.png` that the existing asset pipeline can read, and `krita_capture` at `scale: 1` gives a native PNG of any region for review.
- **`krita_document_close`** `{guard, dirty_policy}`: `refuse` (fails with `DOCUMENT_DIRTY` if any mutation reached the document through the bridge after its last verified save; Krita's own modified flag is not used [K45]) or `discard` (an addition: agents only ever modify working copies, so no source is at risk); the contract's required `checkpoint_id` is removed and `discard_with_checkpoint` arrives in Phase 3. Kept only if the live harness shows no crash in 20 open/close cycles (Appendix C, Q5).

### Phase 2: Construct (planned; tools take the contract's draft shapes as their starting point)

**Project profiles** (moved here from Phase 1 by the owner, 2026-10-22). `krita_project_load` `{profile_path, expected_sha256, request_id}`: loads a profile file inside an allowed root, checks its hash (`SOURCE_HASH_MISMATCH`), validates it against the krita-art-mcp profile schema 0.2.0 (`PROFILE_INVALID`; later phases add sections to the schema, never reinterpret existing ones) and returns the effective profile and `project_id`. Schema 0.2.0 is the contract's `profile.schema.json` 0.1.0 plus the fields below; the contract's schema forbids extra fields, so 0.1.0 files load and are upgraded in memory, and the contract's demo profiles gain no backgrounds until someone adds them. Profiles are immutable once loaded; a changed file is a new version. Phase 2 uses: `working_roots` (each must sit inside a globally allowed root), `art_mode` (`painted` and `high_resolution_ui`; `mixed_raster` answers `UNSUPPORTED_CAPABILITY`), `export_pixels_per_unit`, `filter`, `review_recipes`, `defaults`. It stores and returns but does not act on `color_profile_id`, `palette_id`, `validator_ids`, `approval_policy_id` until their phases. Additions in 0.2.0: `review_backgrounds` (named colours), `review_tints` (optional named per-channel multiply and add, preview-only), `permitted_operations` (the allow-list every operation below checks), and `asset_overrides` (per-asset overrides of review recipes, export pixels per unit and permitted operations, keyed by asset id; stored and returned in Phase 2, applied from Phase 4, when previews and exports carry an asset id). Two projects loaded at once never share state. With profiles, `krita_document_open` and `krita_document_create` take the contract's `project_id`, working copies default to the profile's first working root, `krita_preview_render` takes the contract's `project_id` and `recipe_id`, and capture backgrounds can be named. The contract's acceptance exercise 5 (two profiles, no leakage) and H9 run in this phase.

Rules for every Phase 2 operation: allowed only where the project profile's `permitted_operations` lists it; only on editable layers; bounded by the current selection where Krita honours one; one or more native undo steps, stated in the receipt; journaled with full parameters; never applied automatically as cleanup. The first game's profile, for example, can forbid colour filters entirely, because its art rule is that colour fixes are repainted by hand.

| Tool | Behaviour | Krita basis | Notes |
|---|---|---|---|
| `transform_apply` | Scale, rotate, shear, crop, mirror, translate an editable layer; filter named | `Node.scaleNode`, `rotateNode`, `shearNode`, `cropNode` (image-level operations [K25]); actions `mirrorNodeX` / `mirrorNodeY` on the active node [K26]; `Node.move` | `Node.move` is not undoable [K25]: translate either via a transform mask or by recording the old offset in the journal and offering a reverse move. Decide at Phase 2 intake |
| `filter_apply` | Named filter with explicit configuration on an editable layer, inside the selection | `Krita.filter(name)`, `Filter.setConfiguration`, **`Filter.startFilter`** only [K24] | `Filter.apply` bypasses undo and the stroke system [K24] and is never used. Allow-list from the profile; available names from `Krita.filters()` at runtime [K28] |
| `color_convert` | Convert an authorised working copy to a target colour space or profile, or recolour an editable layer to a project palette | `Document.setColorSpace` / `Node.setColorSpace` [K27]; palette mapping through the `palettize` / `indexcolors` filters via `startFilter` [K24, K28] | Undo behaviour to measure. Never on an accepted source |
| `palette_manage` | Read or create a versioned project palette | Krita palette resources; `Palette` class | Exact colour values and transparency rules belong to the profile |
| `paint_shape` | Outline of a rect, ellipse or polygon with the brush | `paintRectangle` / `paintEllipse` / `paintPolygon` with `fillStyle: None` | Same verification as `paint_stroke`; in Phase 1 a closed `paint_stroke` polyline draws any outline |
| `paint_fill` | Fill the selection, a contiguous region, or a shape (flat, non-brush [K38]) | Selection fill actions or `paintPolygon` fill; to probe | Contiguous-region fill needs a probe of what scripts can reach |
| `paint_path` | Bezier path painted with the native brush | `QPainterPath.cubicTo` + `paintPath`, or `paintPolylineStroke` on 6.1 | Same verification as `paint_stroke` |
| `paint_clone` | Clone from an explicit immutable source | Clone-engine presets need a source point that scripts may not set: to probe | May stay unsupported; report so |
| `canvas_resize` | Change canvas bounds without scaling paint | `Document.resizeImage` | Refused while the document's protection has `preserve_canvas: true`, and unless the profile's `permitted_operations` lists it |
| `layer_duplicate`, `layer_reorder`, `layer_remove` | Duplicate, move, remove editable nodes | `Node.duplicate`, `addChildNode` (undoable [K22]), `remove` | Removal of protected nodes or their ancestors is refused |
| `layer_import` | Import an authorised raster or vector file as a new positioned layer | `Document.createFileLayer` or open and copy; to probe | Imported pixels are content from a named file, not agent pixel writes; journaled with the file hash |
| `mask_edit` | Create and paint transparency masks | `Document.createTransparencyMask`; painting on masks via the stroke tools | Masks are never saved to ORA [Part 6]; KRA only |
| `document_duplicate` | Fork a working branch | `Document.clone()` [K35] | |
| `reference_set` | Register approved references for preview sheets | Server-side only | References never enter the document |
| `guides_set` | Guides, grid, snapping | `GuidesConfig`, `GridConfig` [K33] | |
| `view_set` | Zoom, pan, rotation, mirror of the canvas view | `Canvas` setters, to probe; 6.1 adds change signals [K31] | Never changes document coordinates; harness proves strokes land identically at any view |

Also in Phase 2: **preset tuning** (spacing and other parameters edited on a temporary copy of a preset through `Preset.toXML` / `fromXML`, to probe, never on the owner's own presets); **templates** (`document_create` gains `template_path`, and `layer_import` can import a reusable layer group from a template file); **derived copies** (duplicated, mirrored or recoloured layers are journaled with `derived_from` and marked as derived in receipts, never presented as new drawings).

### Phase 3: Integrity (revisions, transactions and checkpoints deferred here by the owner; the other tools placed here are proposed)

- **Revisions and stale-edit detection.** A per-document revision advances on every art, selection, protection or metadata change, including undo. Because Krita emits no per-edit signal and has no undo-grouping API [K29], detecting the owner's own edits needs a state fingerprint (layer tree plus per-layer pixel hashes) at every mutation boundary. Every guard gains `expected_revision`; reads may pin a revision. Not claimed until the harness demonstrates it on real edits.
- **Checkpoints.** `checkpoint_create` saves a copy of the working document into the data dir; restoring opens that copy as a new working document (no raw pixel writes into the live document).
- **Edit transactions.** `edit_begin` pins target layer, frame, selection, profile and protection; strokes inside it are verified individually as in Phase 1; `edit_commit` re-verifies the whole edit; `edit_rollback` steps native undo back to the transaction start and verifies, falling back to the checkpoint. One transaction per document at a time. A batch is still several native undo steps [K29].
- **Diff and recovery.** `diff_measure` compares any two snapshots (layer, composite, checkpoint); `recovery_list` / `recovery_open` expose checkpoints and interrupted branches after a crash; `diagnostics_get` returns bounded plugin errors and capability probe reports.
- **Artifacts as MCP resources:** `krita-artifact://` and `krita-checkpoint://` (the contract's names) URIs with MIME type, size, hash and retention.

### Phase 4: Delivery (registration, export and validation deferred here by the owner; the other tools placed here are proposed)

Moves game export out of the existing Pillow pipeline into the server, as a separate migration with its own acceptance:
- `registration_set`: uniform scale, sub-pixel translation, crop, padding and anchor per asset; returns the full master-to-export transform after rounding; explicit filter. Formula: `export = (document - source_rect.origin) × uniform_scale + translation`. Nonuniform transforms and palette conversion only as separate, profile-authorised operations.
- `asset_export`: registered PNG plus metadata (pivots, sockets, collision, nine-slice), straight or premultiplied alpha declared, validated after writing.
- `validation_run`: runs project validator adapters chosen by id (never shell commands) on immutable inputs; returns findings, never edits, and never relaxes a project's checker or spec. File and geometry validation, visual judgement, owner approval and runtime or device checks are reported separately; static previews never certify scrolling, mipmaps or device appearance.
- `asset_metadata_set`, `export_batch`, `atlas_pack` (trim, padding, edge extrusion, rotation rules), `engine_package` through registered engine adapters (Unity first, since the owner builds in Unity).
- Preview overlays `anchor`, `collision`, `envelope` become available.

### Phase 5: Asset modules (planned)

- **Animation:** frame identity on every read and edit; keyframes, holds, frame rate, named clips, onion skins, contact sheets, timed playback; export ordered frames and timing metadata; pivots and attachments preserved across frames. Krita basis: `Document.currentTime` / `setCurrentTime`, `animationLength`, `framesPerSecond`, clip ranges, `importAnimation`; `Node.animated`, `enableAnimation`, `hasKeyframeAtTime`, `pixelDataAtTime` [K32]. Painting at a given frame is to probe; a declared frame-per-document fallback is acceptable.
- **Tiles and terrain:** tile size, repeat axes, adjacency and autotile layouts; repeated-patch seam previews (server-side compositing); wrapped painting through Krita's wrap-around mode, which scripted strokes honour [K47].
- **Backgrounds and scenes:** large-canvas region access, parallax and repeat previews at camera positions, connector alignment; regions streamed, never the whole document per stroke.
- **UI:** native-size variants, states, safe areas, nine-slice margins; previews at several display densities.
- **Character and object part sets:** named layers, sockets, pivots, facing variants and occlusion order for engine-side assembly, kept as Phase 4 metadata separate from paint.
- **Text and vector:** editable text and vector shapes when supported, never rasterised silently. Krita basis: `VectorLayer`, `Shape`, `GroupShape` [K34]; editability through scripts is to probe.

### Phase 6: Input-aware strokes on Krita 6.1 / 5.4 (planned; the contract is ready from Phase 1)

Krita's development branch added `Node.paintPolylineStroke(QList<StrokePoint>)` on 2026-07-25: one undoable freehand stroke with per-point position, pressure, x and y tilt, rotation, tangential pressure, time and speed, and with spacing and distance sensors continuous across segments [K30]. It is not on the 6.0 release branch, so it ships with Krita 6.1 / 5.4, not with 6.0.5 / 5.3.5. Work for this phase:
1. No new tools: `paint_stroke` already carries every `StrokePoint` field from Phase 1.
2. Build the `paintPolylineStroke` branch of `paint_stroke`. The capability turns on when `hasattr(Node, "paintPolylineStroke")` is true (master called it `paintStroke` from 2026-07-25 to 2026-10-05; that name is not accepted) and a harness probe confirms pressure changes dab size or opacity with a pressure-sensitive preset.
3. Re-run the preset sheet (H2) with pressure ramps, and re-run the correction trial (H1) with real pressure.
4. Add an optional `fade` to the brush object (`View.setBrushFade`) and canvas change signals to `view_set`, a Phase 2 tool [K31]. Both are additive.
5. Optional early lane: a Krita development build of master on the Mac, used only for capability probes on throwaway documents (Appendix C, Q9).

### States & edge cases

| Situation | Behaviour |
|---|---|
| Krita closed, plugin disabled, stale bridge file | `KRITA_NOT_RUNNING` with the missing step |
| Plugin and server protocol differ | `PROTOCOL_MISMATCH`: reinstall the plugin, restart Krita |
| A modal dialog is open in Krita | `KRITA_MODAL_DIALOG` (`QApplication.activeModalWidget()`) |
| More than one main window | `MULTIPLE_WINDOWS` |
| The owner closed the document by hand | `DOCUMENT_NOT_FOUND` (registry re-checked before every call) |
| Target is protected / not a paint layer / has a local selection mask | `LOCKED_TARGET` / `LAYER_NOT_PAINTABLE` / `LAYER_HAS_LOCAL_SELECTION` |
| Preset missing or changed | `INVALID_ARGUMENT` with up to 5 nearest preset names / `RESOURCE_HASH_MISMATCH` |
| Document not 8-bit sRGB RGBA | `COLOR_PROFILE_MISMATCH` |
| Stroke leaked outside the allowed region | Auto-undo, verified; `PROTECTED_REGION_CHANGED` |
| Rollback could not be verified | `ROLLBACK_FAILED`; document marked unsafe until reopened |
| Client timeout, then retry | Same `request_id` returns the original receipt |
| Huge document | Regions only; captures above 4096 px must tile |
| Mutation on a `read_only` document (opened by hand in Krita, or with `mode: read_only`) | `DOCUMENT_READ_ONLY` |
| Unknown layer id | `LAYER_NOT_FOUND` |
| Same `request_id`, different arguments | `REQUEST_ID_CONFLICT` |
| Feature this Krita build or phase lacks (per-point input without `input_fallback`, `krita_document_create` with a depth other than U8, `smooth: stabilizer`, saving a document that is not RGBA / U8 / sRGB) | `UNSUPPORTED_CAPABILITY` |
| Stroke or property change whose effect the plugin cannot bound, without `verify: "full"` | `UNSUPPORTED_CAPABILITY`, with the reason |
| Undo past the last protection change, or redo of a rolled-back stroke | `INVALID_ARGUMENT` |
| Mutation from a second live server process | `DOCUMENT_IN_USE` |
| A queued job is cancelled | `CANCELLED` |
| Unexpected plugin exception | `INTERNAL_ERROR`, traceback in `plugin.log` |
| Retry of a call whose Krita session ended mid-flight | `INTERNAL_ERROR`, outcome uncertain; never re-sent |
| Source or profile hash differs | `SOURCE_HASH_MISMATCH` |
| Profile fails its schema (Phase 2) | `PROFILE_INVALID` |
| Path outside every allowed root | `PATH_NOT_ALLOWED` |
| Target file exists | `FILE_EXISTS` |
| Disk or format error | `IO_ERROR` |
| Stroke geometry entirely outside the allowed mask | `OUTSIDE_ALLOWED_MASK`, refused before painting |
| Closing with `refuse` after a bridge mutation since the last verified save | `DOCUMENT_DIRTY` |
| Reopened save differs from the document | `SAVE_VERIFY_FAILED` |
| Painting on a document whose rollback failed | `DOCUMENT_UNSAFE` |
| Bridge queue full, or an autosave holding the document during a save | `BUSY`, retryable |
| Operation exceeds its hard limit | `TIMEOUT` |

### Server instructions (the MCP `instructions` text, at most 4,096 characters; the session writes it)

Must cover: a fresh UUID for every `request_id`; one working copy per agent; open with `working_copy` and a working folder; existing layers are protected and that is deliberate; add a layer before painting; to recolour inside a silhouette under `preserve_composite_alpha`, paint on a new `inherit_alpha` layer; to repair several regions, allow their union once and select each region; one stroke per call; `input_fallback` and what flat strokes mean; check `krita_preview_render` at the asset's game sizes (explicit recipes until Phase 2) after every one to three strokes; undo steps include selection commits, layer creation and blend changes, while other layer property changes cannot be undone; there is no raw pixel tool; the owner may be watching and must not edit brush presets while an agent paints.

---

## Part 5: Requirements [draft]

**Functional requirements (Phase 1)** (F-02, project profiles, and F-14, shapes, moved to Phase 2 with their tools)

| ID | Requirement | Priority |
|---|---|---|
| F-01 | `krita_server_info` reports versions and the capability matrix, or the exact missing setup step | Must |
| F-03 | Documents open as working copies or read-only, with existing layers protected by default | Must |
| F-04 | Documents can be created at explicit size and colour space | Must |
| F-05 | The full layer tree, selection and protection state can be inspected | Must |
| F-06 | Presets, blend modes, profiles and palettes can be listed, presets with id and fingerprint | Must |
| F-07 | Native and resampled captures of composite, layer or selection, with explicit transform, filter and background | Must |
| F-08 | Exact colour samples at points or discs, composite and layer distinguished | Must |
| F-09 | Paint and group layers can be created and updated; protected layers and their ancestors refuse changes | Must |
| F-10 | Selections from rect, ellipse, polygon, raster mask, layer alpha, all, none; combine, feather, grow, shrink, invert | Must |
| F-11 | Protection can be tightened with protected layers and a binary allowed-change mask | Must |
| F-12 | One native brush stroke per call, effective settings reported, per-stroke verification with verified auto-undo | Must |
| F-13 | Per-point input is accepted by the contract; Phase 1 refuses it or flattens it explicitly, and Phase 6 applies it where Krita supports it | Must |
| F-15 | Undo and redo per document | Must |
| F-16 | Long calls return an operation id; queued operations can be cancelled | Must |
| F-17 | Preview sheets at every requested review recipe, baseline beside current, backgrounds, tints, greyscale, selection and mask overlays | Must |
| F-18 | Save to KRA or ORA at a new path, verified by reopening | Must |
| F-19 | Saved ORA and KRA files carry `mergedimage.png` for the existing asset pipeline; no PNG export tool until Phase 4 | Must |
| F-20 | Close with refuse or discard | Should |
| F-21 | Every mutating call is idempotent by `request_id` and journaled | Must |
| F-22 | No tool writes raw layer pixels or runs code | Must |
| F-23 | `krita-art-mcp doctor` names the first failing setup step | Must |
| F-24 | Krita shows a floating message while an agent job runs (`View.showFloatingMessage`) | Could |

**Non-functional requirements** (budgets proposed; Session 1 measures on the owner's Mac and the intake confirms)

| ID | Requirement | Target | How verified |
|---|---|---|---|
| N-01 | `paint_stroke` round trip including verification, 200 points, 40 px brush, 2000×2000 document with 20 protected layers | p95 < 1.5 s | Live harness |
| N-02 | `preview_render`, two recipes, 2000×2000 master | p95 < 2.0 s | Live harness |
| N-03 | Krita idle CPU added by the plugin | < 1% | By hand |
| N-04 | Nothing written outside allowed roots, the data dir, and Krita's own temp and autosave files | 0 | Unit tests + harness |
| N-05 | Plugin runs unchanged on 5.3.x and 6.0.x | Both pass | Harness on both |
| N-06 | A hard round brush at opacity 1 paints the requested colour exactly at the stroke centre | Equal bytes | Harness |
| N-07 | A stroke lands on the same document pixels at two zoom, pan and rotation settings | Equal hashes | Harness |
| N-08 | A soft or scatter brush next to a binary selection changes zero pixels outside it | 0 | Harness in `verify: region` and `verify: full` |
| N-09 | `paint_stroke` round trip, 200 points, 40 px brush, 8192×8192 document with 30 protected layers | p95 < 3 s | Live harness |

**Constraints & assumptions**

- **Verified:** Krita's scripting API as in Part 8.
- **To measure:** 5.3 and 6.0 on macOS share `~/Library/Preferences/kritarc` and the resource folder, so one plugin install serves both, but they cannot run at the same time.
- **To measure:** the bundled Python is 3.10 or newer; plugin code targets 3.10 syntax and the standard library only.
- **Constraint:** the plugin uses only the standard library, PyQt5 or PyQt6, and the `krita` module.
- **Constraint:** apps launched from the Dock do not inherit `PATH` or shell variables; client configs use absolute paths.
- **Assumption:** The owner does not paint in Krita while an agent works, and each agent writes only to its own working copy (the writer lease enforces one agent per document) until Phase 3.

---

## Part 6: Data & files [draft]

**Entities**

- **Bridge:** `{port, token, pid, protocol, plugin_version, krita_version, qt_major}`.
- **Project:** `{project_id, version, profile_path, profile_sha256, effective_profile}` (Phase 2).
- **Document handle** (held by the plugin, so every client and server process sees one state): `document_id` → Krita `Document` wrapper, mode, project, working and source paths, source hash, protected layer ids, allowed-change mask path and hash, preservation flags, unsafe flag, `as_opened` baseline path, saved marker, undo floor, redo allowance, writer lease.
- **Operation:** `{operation_id, request_id, tool, args_sha256, status, result | error}`, held by the bridge for the Krita session and keyed by `request_id` (the server mints one for calls that carry none); a duplicate with a different `args_sha256` fails with `REQUEST_ID_CONFLICT`; `operation_id` is minted by the server.
- **Journal entry:** `{ts (ISO 8601 UTC), client (MCP clientInfo name), request_id, tool, canonical args, result summary, document path, layer names}`. Point arrays stored in full.
- **Config:** `{roots: [absolute paths]}`.

**Files on disk**

| Path (default; `KRITA_ART_MCP_DATA_DIR` overrides for the harness) | Written by | Contents | Lifetime |
|---|---|---|---|
| `~/Library/Application Support/krita-art-mcp/config.json` | `krita-art-mcp roots` | Globally allowed roots | Permanent |
| `…/krita-art-mcp/bridge.json` | plugin | Bridge entity, mode 0600, atomic write | Removed on Krita quit |
| `…/krita-art-mcp/captures/YYYY-MM-DD/` | server | Captures, previews, masks | Pruned after 7 days |
| `…/krita-art-mcp/baselines/` | server | `as_opened` composites | Removed when the document closes; orphans swept at server start |
| `…/krita-art-mcp/transfer/` | plugin | Raw pixel buffers for the server | Deleted by the server after reading; swept at bridge start |
| `…/krita-art-mcp/journal/YYYY-MM-DD.jsonl` | server | Journal and request-id records | Permanent |
| `…/krita-art-mcp/logs/plugin.log` | plugin | Tracebacks, bridge events; never the token | Rotated at 5 MB |
| `<working_dir>/` (from Phase 2, the profile's first working root by default) | server | Working copies | Owned by the project |

Roots are enforced on `realpath`, by both server and plugin, and a profile's working roots must sit inside the global roots.

**Formats**

- **KRA:** full-fidelity working format: masks, adjustment layers, animation.
- **ORA:** the exchange format of the first game's current masters. Krita's ORA exporter writes paint, group, generator, clone, file and vector layers (vector and file layers rasterised) with name, opacity, visibility, position, `edit-locked` and composite op; each layer's projection, so mask effects are baked in while mask nodes are dropped; inherit-alpha as `svg:src-atop` (or `alpha-preserve` for non-normal blends), read back as inherit-alpha; a `mergedimage.png`. Adjustment layers are dropped. RGBA and GrayA at 8 and 16 bits; Krita's ORA loader builds an 8-bit RGBA image. (`plugins/impex/ora/kis_open_raster_stack_save_visitor.cpp:100-106,159-165,193`, `…save_visitor.h:45-61`, `libs/image/kis_layer.cc:826-832`, `…load_visitor.cpp:96,136-138`, `ora_export.cc:82-85`, `ora_converter.cpp:101`.)
- **Consequence for the asset pipeline:** downstream tools read `mergedimage.png` or the exported PNG and never re-composite ORA layers, because a correction layer saved with inherit-alpha is stored as `src-atop`. An older checker of the first game recomposites ORA layers with plain alpha-over, so it would misjudge such a layer and cannot be reused unchanged.
- **PNG:** import as a single layer; PNG export arrives in Phase 4.

**What is never written:** raw pixel bytes into a layer; any file outside allowed roots, the data dir, and Krita's own temp and autosave files; an accepted source file.

---

## Part 7: Agent interface design [draft]

1. **Stateless paint calls.** Brush, colour and opacity are window-wide resources shared with the owner [K3]. Every paint call sets the full brush inside the job that paints, in a fixed order, and reports what Krita applied. Exception, stated in the server instructions: if the owner has unsaved edits to the same preset in memory, those carry over [K3].
2. **One paint call, one undo step, one journal line.** Other calls say whether they are undoable [K22].
3. **Every mutation returns where it changed and what it verified.**
4. **The tool set shapes behaviour.** Protection is on by default and pixels change only through the brush or a named, permitted operation.
5. **Typed errors with one-line hints and `retryable`.**
6. **Short tool descriptions; rules in the server instructions.** Claude Code truncates upfront tool descriptions and server instructions at 4,096 characters [C4].
7. **Capabilities, not version checks.** Agents read `krita_server_info` and adapt; unsupported input is refused or explicitly flattened, never silently dropped.

---

## Part 8: Technical [draft]

**Stack & architecture**

```
Codex / Claude Code  ──stdio (MCP)──▶  krita-art-mcp server (Python 3.12, uv, mcp 2.3.x, Pillow, NumPy)
                                          │  HTTP/1.1 + JSON on 127.0.0.1, bearer token
                                          ▼
                                   krita_art_mcp_bridge plugin (inside Krita, its Python)
                                          │  job queue → queued Qt signal → Krita's main thread
                                          ▼
                                   Krita Python API (libkis)
```

| Bet | Chosen | Rejected, and why |
|---|---|---|
| Plugin ↔ server transport | HTTP/JSON on loopback, ephemeral port, bearer token, stdlib `http.server.ThreadingHTTPServer` on a daemon thread | QtNetwork on the main thread: no evidence Krita bundles it. Raw TCP: no gain, harder to debug |
| Executing Krita calls | `queue.Queue` drained on the main thread, woken by a queued Qt signal from the HTTP thread; a `job_active` flag makes the drain return at once when a job's own nested event loop (inside `waitForDone` or a save) re-enters it [K41] | libkis from the HTTP thread: not thread-safe. A 10 ms polling `QTimer`: fires inside `waitForDone`, starting a second job mid-stroke, and costs idle CPU |
| Long calls | Every request is a job; the server owns the wait budget and polls the bridge with short timeouts, because the bridge cannot answer while a Krita call holds the GIL [K40] | Synchronous calls: client timeouts on large saves. A wait budget inside the bridge: it cannot run during the call it is timing |
| Pixel transfer | Raw `pixelData` (BGRA for RGBA U8) written by the plugin to a file in `transfer/`; the JSON carries path, size and format; the server memory-maps it with NumPy and deletes it | zlib and base64 inside JSON: the encoding runs inside Krita under the GIL and is about 680 MB per stroke on an 8k master with 30 protected layers. `QImage` from `projection()`: converts through a profile |
| Image work, masks, colour maths | Server side with Pillow and NumPy, except the per-stroke protection checks | Inside Krita: no Pillow there |
| Verification | Inside the plugin, in the stroke's own job: region read before and after, byte-level checks, protected layers compared by hash, native undo as rollback | In the server: a second job could land between the stroke and its rollback, and every protected layer would cross the bridge. Pixel restore from snapshots: breaks pillar 1 |
| Document state | In the plugin's registry, shared by every client | In each MCP server process: Codex and Claude Code each start their own, so state would split between them and vanish on a server restart |
| Server SDK | `mcp` 2.3.x, `MCPServer` | 1.x: superseded; `FastMCP` is renamed [C1] |
| Brush state | Set per call | A persistent brush tool: hidden shared state |
| Schemas | The contract's `mvp.tools.json` with this PDD's amendments, validated with a full Draft 2020-12 validator | Hand-written ad hoc validation |

**Bridge protocol (version 1)**

- `POST /v1/call` `{op, args, request_id, operation_id, client: {pid, started_at}, wait_s}` with `Authorization: Bearer <token>` → `{status: done, result}` | `{status: error, error}` | `{status: queued, operation_id}` | `{status: running, operation_id}`.
- The server mints `operation_id` and journals the call as dispatched before sending it. The bridge answers at enqueue whenever the main thread is free, and keys jobs by `request_id` for the Krita session: a duplicate returns the existing operation.
- `GET /v1/operations/<id>?wait_s=` → same shape. `POST /v1/operations/<id>/cancel` → cancels a queued job only.
- The server polls with `wait_s` of about 2 s and a socket timeout a few seconds longer. A connected but silent bridge means Krita is busy inside a call: the tool returns `running` with the operation id after the wait budget. `KRITA_NOT_RUNNING` only when the connection is refused and `bridge.json` names no live Krita.
- `GET /v1/health` → `{protocol, plugin_version, krita_version, qt_major, capabilities}`, cached on the main thread at bridge start.
- Refuses a wrong token (constant-time compare), bodies over 64 MB, and `Host` headers other than `127.0.0.1:<port>` or `localhost:<port>`.
- The server re-reads `bridge.json` on every call. Each server process serialises its own calls; the plugin runs one job at a time for every client.

**Plugin internals**

- **Layout:** `pykrita/krita_art_mcp_bridge.desktop` (`[Desktop Entry]`, `Type=Service`, `ServiceTypes=Krita/PythonPlugin`, `X-KDE-Library=krita_art_mcp_bridge`, `Name=Krita Art MCP Bridge`) and `pykrita/krita_art_mcp_bridge/`. `__init__.py` calls `Krita.instance().addExtension(KritaArtMcpExtension(Krita.instance()))`; the extension starts the bridge in `setup()`. Krita loads it only if `kritarc [python] enable_krita_art_mcp_bridge=true` (`plugins/extensions/pykrita/plugin/PythonPluginManager.cpp:265-301`).
- **Two layers:** `bridge_core` (pure Python: HTTP, auth, jobs, validation, dispatch; tested outside Krita) and `krita_adapter` (every `krita` and PyQt import).
- **PyQt shim:** `try: from PyQt6… except ImportError: from PyQt5…`, as Krita's own plugins do (`plugins/python/exportlayers/uiexportlayers.py:5-13`). Avoid Qt enums; use `Krita.getAppDataLocation()` instead of `QStandardPaths`.
- **Capabilities:** probed once at bridge start (`Krita.filters()`, colour models; from Phase 6 also `hasattr(Node, "paintPolylineStroke")`) and reported by `/v1/health`.
- **Document registry:** holds the document handles (Part 6) and enforces mode, protected targets, the unsafe flag, the undo floor, the redo allowance and the writer lease in every op, so all clients and server processes see one state; strong references to every opened wrapper; `addView` right after `openDocument` [K6]; re-checked against `Krita.instance().documents()` before each call.
- **Before every document-scoped job:** at job start only, refuse on a modal dialog or multiple windows (Krita's own busy dialog during a job's `waitForDone` is expected [K41]); if the active node is a selection mask, activate its parent layer, so the selection overlay never enters reads or saves [K46]; activate the document's view with `Window.showView` [K2, K7] (may not bring its tab to the front, to measure); for paint jobs switch mirror painting off through `hmirror_action` / `vmirror_action` and wrap-around through `Canvas.setWrapAroundMode`, and restore both afterwards; only then call `paintAbility()` [K9].
- **After every paint, undo, redo, filter or transform job and before any read, save or export:** `doc.waitForDone()` [K5].
- **Shutdown and single instance:** on `notifier().applicationClosing`, stop accepting, fail queued jobs with `CANCELLED`, call `shutdown()` and `server_close()` on the HTTP server, then delete `bridge.json`, all before Python is finalised [K48]. Refuse to start if `bridge.json` names another live process whose executable is Krita; a reused pid after a crash does not count.

**Verified Krita facts** (github.com/KDE/krita at tag `v6.0.4.1`, whose tree builds 5.3.4.1 when `BUILD_WITH_QT6` is off, `CMakeLists.txt:133-145`; K30 and K31 from `master` at `b5b6dd3`, 2026-10-22; K40 to K48 from the independent architecture review, 2026-10-23)

| # | Fact | Reference | Consequence |
|---|---|---|---|
| K1 | 5.3 and 6.0 are one codebase; only Qt/PyQt differ. CMake calls the Qt 6 build "not yet production-ready"; krita.org says "for real work, please use 5.3" | `CMakeLists.txt:14,133-145,374-380`; krita.org 5.3.0 notes | One plugin, two PyQt imports; develop on 5.3.x, verify on 6.0.x |
| K2 | Paint calls take brush, colours, opacity, blend, alpha lock and mirror settings from `currentMainwindow()->activeView()`'s canvas resources | `libs/libkis/PaintingResources.cpp:36`; `libs/ui/tool/kis_resources_snapshot.cpp:135-156` | Activate the target view; mirror off via its actions; one main window |
| K3 | Those resources are window-wide: `View` setters change the owner's brush. `setCurrentBrushPreset` does nothing if the preset is already current and reloads from disk only when dirty presets are off; activating a preset resets the composite op | `View.sip`; `libs/ui/kis_paintop_box.cc:621-651,731-732` | Stateless paint calls in a fixed order; warn the human |
| K4 | Each libkis paint call is one stroke ended in its helper's destructor, labelled "Scripted Brush Stroke". `paintPath` gives every point pressure 1.0 and shares one `KisDistanceInformation` across all elements | `libs/ui/tool/kis_figure_painting_tool_helper.cpp:41,94-98`; `libs/libkis/PaintingResources.cpp:61`; `libs/image/kis_painter.cc:1380-1425`; `libs/global/kis_global.h:97-99` | One call = one stroke = one undo step; per-point pressure impossible before K30; one polyline per call |
| K5 | Painting is asynchronous; `Document.waitForDone()` waits | `kis_figure_painting_tool_helper.cpp:41,96-98`; `libs/libkis/Document.cpp:824-829` | Wait before any read, save or export |
| K6 | `Krita.openDocument()` returns an owning wrapper (deleted with it); `Window.addView` hands ownership to Krita; no view is added by `openDocument` | `libs/libkis/Document.cpp:87-92`; `libs/libkis/Window.cpp:82-92`; `libs/libkis/Krita.cpp:339-350` | Hold the wrapper; `addView` at once |
| K7 | Undo and redo act on the active view's document; standard action `edit_undo` / `edit_redo` | `libs/ui/KisMainWindow.cpp:1538-1548,3063` | Activate the view first; confirm the action name by probe |
| K8 | `Document.setSelection(sel)` and `setSelection(None)` push undo commands | `libs/libkis/Document.cpp:361-371` | Undo can step back a selection change |
| K9 | `paintLine(QPoint, QPoint, …)` takes integer points; `paintPath(QPainterPath, …)` floats; `paintAbility()` returns `PAINT` for any node with a paint device, masks and fill/filter layers included, and dereferences the active view without a null check | `plugins/extensions/pykrita/sip/krita/Node.sip:85-90`; `libs/libkis/Node.h:575-691`; `libs/libkis/Node.cpp:830-863` | Strokes via `paintPath`; also require `type() == "paintlayer"`; call `paintAbility()` only after activating a view |
| K10 | Painting is confined by the global selection unless the target layer has an active local selection mask, which wins | `kis_resources_snapshot.cpp:312-334`; `libs/image/kis_layer.cc:509-522` | `LAYER_HAS_LOCAL_SELECTION` |
| K11 | `Selection.setPixelData` reads w×h bytes, one per pixel; `Selection` has `select`, `feather`, `grow`, `shrink`, `invert`, `add`, `subtract`, `intersect`, `replace`, `duplicate` | `libs/libkis/Selection.h:213-228`; `Selection.sip` | Server-rasterised masks |
| K12 | `Document.pixelData` reads the projection; for integer RGBA the order is B, G, R, A. `Node.pixelData` is the raw paint device | `libs/libkis/Document.cpp:472-484`; Node docs | BGRA swap in the server; layer captures exclude opacity, masks, clip |
| K13 | `setInheritAlpha` = clip to below; `setAlphaLocked` = the layer's own alpha lock; `View.setGlobalAlphaLock` = brush-level | `libs/libkis/Node.cpp:168-175,402-407` | Distinct fields |
| K14 | `Krita.setBatchmode` affects `openDocument` and `Node.save`; `Document.setBatchmode` suppresses dialogs on save and export; `exportImage` is synchronous | `libs/libkis/Krita.cpp:129-137,339-350`; `Node.cpp:668`; `Document.cpp:112-116,519-527` | Batch mode around every open, save and export |
| K15 | PNG export defaults: `alpha=true`, `compression=3`, `forceSRGB=true`, `saveSRGBProfile=false`, `storeMetaData=false`, `storeAuthor=false` | `plugins/impex/png/kis_png_export.cc:89-109` | Pass explicitly |
| K16 | CLI options include `--export`, `--export-filename`, `--nosplash`, `--resource-location`, `--new-image`, `--template`; no option runs a Python script | `libs/ui/KisApplicationArguments.cpp:69-99,193` | Harness can use a temp resource folder; `kritarc` is not redirected |
| K17 | `Krita.resources("preset")` returns `{name: Resource}`; `View.setCurrentBrushPreset(Resource)` | `libs/libkis/Krita.cpp:251-292`; `View.sip` | Preset listing |
| K18 | `ManagedColor.fromQColor(QColor, canvas=None)`; `ManagedColor(model, depth, profile)` + `setComponents` (Krita channel order) | `ManagedColor.sip` | Exactness to measure (N-06) |
| K19 | macOS resource folder: `~/Library/Application Support/Krita/`; plugins in its `pykrita/` | docs.krita.org, Resource Management | Installer default; `doctor` compares with `getAppDataLocation()` |
| K20 | Current releases 5.3.4 and 6.0.4 (Sept 2026); latest tag `v6.0.4.1` (2026-09-30) | krita.org 2026-09-15; GitHub tags | Session 1 records installed versions |
| K21 | `View.setCurrentBlendingMode` stores any string; an unknown composite-op id silently paints `normal` | `libs/libkis/View.cpp:235-239`; `libs/pigment/KoColorSpace.cpp:371-386` | Whitelist, ids from `libs/pigment/KoCompositeOpRegistry.h` |
| K22 | Undo steps: every paint call, every `setSelection`, `addChildNode`, `setBlendingMode`. Not undoable: `setName`, `setOpacity`, `setVisible`, `setInheritAlpha`, `setAlphaLocked` | `libs/libkis/Node.cpp:168-175,185-194,265-281,402-407,432-451,537-541` | Receipts state undoability; too many undos can remove the agent's own layer |
| K23 | `Document.selection()` wraps the live global selection; combine and modify calls change it in place; a committed `Selection` is kept by Krita | `libs/libkis/Document.cpp:353-359`; `libs/libkis/Selection.cpp:207-295`; `kis_set_global_selection_command.cpp:30-38` | Always `duplicate()` or a fresh `Selection()` |
| K24 | `Filter.apply` calls `filter->process` directly on the paint device: no stroke, no undo, no selection. `Filter.startFilter` runs a `KisFilterStrokeStrategy` stroke with the active document's view resources, ends it and waits | `libs/libkis/Filter.cpp:85-99,101-141` | Phase 2 uses `startFilter` only, after activating the target view |
| K25 | `Node.scaleNode`, `rotateNode`, `shearNode`, `cropNode` delegate to `KisImage::scaleNode` etc. and wait; `Node.move` sets x and y directly | `libs/libkis/Node.cpp` (those methods; `move` at 619-624) | Image-level transforms (undo to confirm by probe); `move` has no undo |
| K26 | Actions `mirrorNodeX`, `mirrorNodeY`, `mirrorAllNodesX`, `mirrorAllNodesY` exist | `krita/krita.action:3248,3260,3344,3356` | Mirror via actions on the active node |
| K27 | `Document.setColorSpace` calls `KisImage::convertImageColorSpace`; `Node.setColorSpace` exists for layers | `libs/libkis/Document.cpp:223-228`; `libs/libkis/Node.cpp:347-348` | `color_convert` basis; undo to measure |
| K28 | Filter plugins in the tree include blur, colors, colorsfilters, convolutionfilters, gaussianhighpass, indexcolors, levelfilter, palettize, posterize, unsharp, threshold, and more | `plugins/filters/` | Registry names come from `Krita.filters()` at runtime |
| K29 | `Notifier` emits only application, image created/saved/closed, view and window, and configuration signals; libkis exposes no per-edit signal and no undo-grouping API | `libs/libkis/Notifier.h:41-106` | Phase 3 needs fingerprints; batches are several undo steps |
| K30 | Krita master (6.1.0 / 5.4.0 pre-alpha) adds `Node.paintPolylineStroke(QList<StrokePoint>, strokeStyle)`: one undoable freehand stroke, spacing and distance sensors continuous, per-point position, pressure, x/y tilt, rotation, tangential pressure, time (ms), speed; one point paints one dab. Added 2026-07-25 as `paintStroke` (`961b654`) and renamed `paintPolylineStroke` on 2026-10-05 (`c7b0560`), so the API is still settling. Absent from the `krita/6.0` branch (6.0.5 / 5.3.5 pre-alpha) | master `libs/libkis/Node.h:594-608`, `Node.cpp:887-923`, `plugins/extensions/pykrita/sip/krita/StrokePoint.sip` | Phase 6 builds it; the contract carries its fields from Phase 1 |
| K31 | Master also adds `View.brushFade` / `setBrushFade`, `View.brushPosition`, and `Canvas` signals for zoom, offset, rotation, mirror and size changes | master `View.sip`, `Canvas.sip` (diff against v6.0.4.1) | Phase 6 additions |
| K32 | Animation API: `Document.currentTime`, `setCurrentTime`, `animationLength`, `framesPerSecond`, clip range setters, `importAnimation`; `Node.animated`, `enableAnimation`, `hasKeyframeAtTime`, `pixelDataAtTime` | `libs/libkis/Document.h:825-892`; `Node.sip` | Phase 5 basis; painting at a frame to probe |
| K33 | `Document.guidesConfig` / `setGuidesConfig`, `gridConfig` / `setGridConfig` | `libs/libkis/Document.h:960-1018` | `guides_set` |
| K34 | `VectorLayer`, `Shape`, `GroupShape` classes; `Document.createVectorLayer` | `libs/libkis/Document.h:650`; `VectorLayer.sip`, `Shape.sip` | Phase 5 basis |
| K35 | `Document.clone()` | `libs/libkis/Document.h:79` | `document_duplicate` |
| K36 | `Resource` exposes `type`, `name`, `setName`, `filename`, `image`, `setImage` to Python: no id or hash. `Preset(resource).toXML()` returns the full settings | `Resource.sip`; `libs/libkis/Preset.h:37-62` | `preset_id` = file name; fingerprint = SHA-256 of `toXML()` (to measure) |
| K37 | With eraser on, global alpha lock is ignored ("erasing takes priority") | `libs/ui/tool/kis_resources_snapshot.cpp:154-156` | Reject the combination |
| K38 | A shape fill is a flat foreground fill through a mask, not brush dabs | `libs/image/kis_painter.cc:1470-1530` | Fills are Phase 2 |
| K39 | `Document.saveAs` calls `setFileName(filename)` first, so the open document then points at the new file; `Document.exportImage` writes without repointing. KRA saves and restores layer UUIDs | `libs/libkis/Document.cpp:519-527,597-607`; `plugins/impex/libkra/` (UUID attribute in the KRA save visitor and loader) | `document_save` uses `exportImage`; layer ids survive KRA round trips |
| K40 | The `krita` Python bindings never release the GIL: the SIP template sets no `release-gil` and no `.sip` file carries `/ReleaseGIL/`, so a long libkis call (`exportImage`, `openDocument`, `waitForDone`, large `pixelData`) blocks every Python thread, the bridge's HTTP thread included. Krita releases the GIL while idle | `cmake/modules/pyproject.toml.in`; `cmake/modules/SIPMacros.cmake:154-158`; `plugins/extensions/pykrita/sip/`; `plugins/extensions/pykrita/plugin/utilities.cpp:444-447` | The server owns the wait budget; the bridge deduplicates by request id |
| K41 | `Document.waitForDone` reaches `KisDelayedSaveDialog::blockIfImageIsBusy`, which runs `processEvents(ExcludeUserInputEvents)` for 1 s and then `exec()`s a modal dialog; timers and queued signals fire inside both | `libs/image/kis_image.cc:1954-1959`; `libs/image/KisBusyWaitBroker.cpp:45-63`; `libs/ui/KisPart.cpp:136-143,171`; `libs/ui/dialogs/kis_delayed_save_dialog.cpp:87-112` | The job drain guards against re-entry; strokes over 1 s show Krita's busy dialog |
| K42 | `Node.setOpacity`, `setVisible` and `setInheritAlpha` change the property without marking the projection dirty | `libs/libkis/Node.cpp:402,445,537`; `libs/image/kis_base_node.cpp:117-121,253-265` | `layer_update` ends with `Document.refreshProjection()` (`Document.cpp:837`) |
| K43 | An undone command stays on the stack above the index until the next push deletes it, so redo re-applies it | `libs/command/kundo2stack.cpp:740-741` | Redo must not cross a verification rollback |
| K44 | Scatter strength ranges 0 to 5 and offsets each dab by up to strength × dab diameter on each axis | `plugins/paintops/libpaintop/KisScatterOptionData.cpp:33`; `KisScatterOption.cpp:39-46` | The verification region grows with the preset's scatter |
| K45 | `Document.exportImage` calls `exportDocumentSync`, which runs the normal export filter (KRA with `mergedimage.png`), never clears the modified flag, writes a temp file under `QDir::tempPath()`, and returns false while autosave holds the saving lock | `libs/libkis/Document.cpp:519-526`; `libs/ui/KisDocument.cpp:572-580,1334-1358`; `plugins/impex/kra/kra_export.cpp:48`; `plugins/impex/libkra/kis_kra_saver.cpp:654-659`; `libs/ui/KisImportExportManager.cpp:831,931` | KRA through `exportImage` keeps full fidelity; close uses a saved marker; autosave collisions are `BUSY` |
| K46 | When a selection mask is the view's current node, Krita draws it as an overlay into the image; a normal save strips it from its copy, `exportImage` saves the live image | `libs/ui/kis_selection_decoration.cc:106-116`; `libs/ui/KisDocument.cpp:1417-1419` | Activate a non-mask node before reads and saves |
| K47 | Scripted strokes honour wrap-around mode | `libs/ui/tool/strokes/freehand_stroke.cpp:110,296-303` | Switch it off for the stroke |
| K48 | `aboutToQuit` fires after documents and windows close; pykrita then finalises Python and unloads the plugin | `libs/libkis/Notifier.cpp:23`; `plugins/extensions/pykrita/plugin/utilities.cpp:99-106` | Stop the HTTP thread on `applicationClosing` |

**Verified client facts**

| # | Fact | Reference | Consequence |
|---|---|---|---|
| C1 | PyPI `mcp` 2.3.0 (Python ≥ 3.10). `FastMCP` is renamed `MCPServer` (`from mcp.server.mcpserver import MCPServer, Image`); importing `mcp.server.fastmcp` raises. A tool returning `[Image(...), "text"]` yields image + text content. `Image` takes no `_meta`; an `ImageContent` built directly with `_meta` reaches the client. A raised exception yields only "Error executing tool X"; returning `CallToolResult(is_error=True, content=[…])` yields exactly the content given | Installed and probed 2026-10-22 | Pin `mcp>=2.3,<2.4`; return errors, don't raise. To verify in Session 1: an error result carrying `structured_content` passes the SDK's output-schema handling |
| C2 | Codex passes MCP image content to image-capable models; honours `_meta: {"codex/imageDetail": …}` (`original` downgraded to `high` where unsupported); has a built-in `view_image` tool | openai/codex `codex-rs/core/src/mcp_tool_call.rs`, `codex-rs/protocol/src/models.rs`, `codex-rs/tools/src/image_detail.rs:23-38`, main @ 2026-10-22 | Images inline plus file path |
| C3 | Codex MCP config: `[mcp_servers.<name>]` with `command`, `args`, `env`, `cwd`, `startup_timeout_sec` (default 10), `tool_timeout_sec` (default 60), `enabled`, `supports_parallel_tool_calls` | `codex-rs/config/src/mcp_types.rs:375-415` | Snippet below |
| C4 | Claude Code: `claude mcp add [--scope user] <name> -- <command>`, or `.mcp.json` with per-server `timeout` (ms). MCP images shown inline (maybe downscaled) and saved to a file. Output limit 25,000 tokens by default, images included. Server instructions and upfront tool descriptions truncated at 4,096 characters | code.claude.com/docs/en/mcp | Captures ≤ 1600 px by default |
| C5 | Codex closes the MCP stdio transport when one message line exceeds 8 MiB on its 2026-07-28 protocol path; the legacy initialize-handshake path uses rmcp's own framing | `codex-rs/rmcp-client/src/bounded_stdio_transport.rs:22,63-65`; `codex-rs/rmcp-client/src/local_stdio_transport.rs:52-56` (openai/codex at `9a8a85b`, 2026-10-22) | Every result stays under 6 MB; large images go as paths |

**Security & privacy**

- Loopback only, ephemeral port, 32-byte token regenerated at every Krita start, `bridge.json` at mode 0600.
- Roots enforced on `realpath` on both sides; accepted sources opened read-only or copied.
- The bridge is not a boundary against the same user's own processes, which can already write the files directly; the token keeps out other users and browsers (the `Authorization` header forces a CORS preflight). Protection lives in the plugin so that every client sees the same state.
- No tool takes a URL or runs code. Nothing leaves the machine; logs never contain the token.

**Build, install & operations**

- Own repository `krita-art-mcp`, outside every game folder, private until publication (Appendix E).
- Server: Python 3.12 (`.python-version`) via `uv`; pins current on 2026-10-22: `mcp` 2.3.x, Pillow 13.x, NumPy 2.x, `jsonschema` (Draft 2020-12), pytest 9.x, ruff 0.17.x, mypy 2.x. Plugin: Python 3.10 syntax, standard library only; `verify` runs plugin tests under 3.10 in a separate pytest-only environment (Pillow 13 needs ≥ 3.11 and NumPy 2.5 ≥ 3.12).
- CLI `krita-art-mcp`: `serve` (MCP stdio), `install-plugin [--krita-data-dir]`, `roots add|list|remove`, `doctor`, `probe` (live harness).
- Codex registration (absolute paths):
  ```toml
  [mcp_servers.krita-art]
  command = "/Users/<you>/.local/bin/uv"
  args = ["run", "--project", "/ABS/PATH/krita-art-mcp", "krita-art-mcp", "serve"]
  startup_timeout_sec = 20
  tool_timeout_sec = 300
  ```
- Claude Code registration:
  ```json
  {"mcpServers": {"krita-art": {"type": "stdio", "command": "/Users/<you>/.local/bin/uv",
    "args": ["run", "--project", "/ABS/PATH/krita-art-mcp", "krita-art-mcp", "serve"], "timeout": 300000}}}
  ```
- Tools appear to agents as `mcp__krita-art__krita_<tool>`. No CI.

**Technical risks**

| Risk | Fallback |
|---|---|
| Flat `paintPath` strokes do not read as painted | Preset sensors (Fade, Distance) measured in H2; Phase 6 brings real pressure; a Krita development build can test it early |
| Per-stroke verification is too slow on big documents | Region verification by default, full only on request; protected layers compared by hash inside the plugin; measure N-01 and N-09 |
| A preset's reach cannot be bounded | `verify: "full"` required for it; H8 compares region and full verdicts |
| The bridge is silent while a Krita call holds the GIL (certain [K40]) | Server-owned wait budget, short polls, request-id map in the bridge; H4 measures recovery after a long save |
| `document_close` crashes | Drop the agent-facing tool. Save verification and the harness also close documents internally, so a reproduced crash must be fixed or avoided there, for example by verifying ORA saves from the file's `stack.xml` and layer PNGs in the server instead of reopening in Krita |
| A PyQt6 difference breaks the plugin | Harness on both builds whenever the plugin changes |
| The Codex build in use predates MCP image passing | File paths in every image result |
| Phase 3 fingerprinting is too slow to run at every boundary | Fingerprint only protected layers and the composite at reduced resolution; decide at Phase 3 intake |

---

## Part 10: Licensing [draft]

| Component | Licence |
|---|---|
| Krita as shipped | GPL-3.0 (`COPYING`); most `libs/libkis` files LGPL-2.0-or-later (SPDX headers) |
| `mcp` SDK | MIT |
| Pillow | MIT-CMU |
| NumPy | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| `jsonschema` | MIT |

The plugin runs inside GPL-3.0 Krita and imports its module. **Proposed:** keep the repository private; decide its licence (GPL-3.0-or-later for the plugin is the safe choice) before any publication (Appendix C, Q3).

---

## Part 12: Validation & Quality Plan [draft]

**Key hypotheses**

| ID | Hypothesis | How we test it | Success signal | Status |
|---|---|---|---|---|
| H1 | An agent painting through krita-art-mcp fixes a real review defect better than a scripted correction | **The trial, after Phase 1:** copies of a real asset's master from the first game (a review item: rim 2.2 px where siblings carry 4.4 to 5.1; broad splinters at the ends). A Codex agent and a fresh Claude Code session each fix it through krita-art-mcp. The owner compares with the scripted pass at 2.95 and 4 px per unit beside the accepted siblings | At least one krita-art-mcp fix judged equal or better, no fringe, seam or speckle at 4 px per unit | Open |
| H2 | Flat `paintPath` strokes with stock presets can taper and read as hand-painted | Harness sheet: 6 stock presets × Fade/Distance sensors on and off | At least 2 presets usable for rims and seams | Open |
| H3 | Codex shows MCP images to the model | The Codex agent describes a capture of a known test pattern | Correct | Open |
| H4 | The bridge stays responsive while Krita is idle and recovers after a blocking call | 500 `server_info` calls; then a 20 s save with a retried paint call queued behind it | p95 < 50 ms idle; answers within 1 s after the save; no duplicate or lost job | Open |
| H5 | The plugin runs unchanged on 5.3.x and 6.0.x | Harness on both | All pass | Open |
| H6 | Requested colours paint exactly | 10 colours incl. `#A7C284` | Exact | Open |
| H7 | Claude Code can do the repaints (the owner's question: a Codex agent draws once, Claude Code repaints) | H1's Claude Code half | Passes H1's bar | Proposed |
| H8 | Per-stroke verification catches every leak | Harness: scatter and soft presets next to binary masks, in `verify: region` and `verify: full` | Every leak rolled back and verified; both modes give the same verdict | Open |
| H9 | Profiles keep projects apart (Phase 2) | Load the painted-sprite and high-resolution UI profiles together; render the first game's 2.95 / 1.8 px/unit comparisons and 128×128 / 256×256 icon previews | No inherited palette, filter, unit, path or approval value | Open |

**Quality strategy**

| Layer | Runs | Covers | Cannot see |
|---|---|---|---|
| `verify` (ruff format check, ruff, mypy, pytest on 3.12; plugin tests on 3.10) | Every commit | Schemas (full Draft 2020-12 validation of the `tools.json` examples of the 19 Phase 1 tools, as amended), argument rules, path roots, request-id journal, mask rasterising, colour maths, preview geometry, protocol client against a fake bridge, plugin core against a fake adapter | Real Krita |
| Live harness (`krita-art-mcp probe`) | Whenever a change touches the plugin, protocol or a Krita-facing tool; on both Krita builds | Every Phase 1 tool on temp documents: colour exactness, verification and rollback, protection refusals, selection enforcement, zoom and pan independence, undo and redo, retry idempotency, save-reopen fidelity, capability matrix, timings | Whether strokes look painted |
| The contract's acceptance exercises 1 to 6 | End of Phase 1 | The brief's §7; exercise 5 (two profiles) moves to Phase 2, exercise 6's PNG export and project checker to Phase 4, and exercise 4's interruption recovery to Phase 3. Phase 1 still renders the first game's 2.95 / 1.8 px/unit and 128 / 256 px icon previews from explicit recipes | |
| The trial (H1) | After Phase 1 | Whether agent corrections meet the art bar | |

Harness rules: Krita must be running with the plugin enabled; the harness opens only its own temp documents, never the owner's files; closes what it opened; deletes its temp folder and sweeps leftovers at start; saves and restores the window's brush state.

Rim fixture (required, because an opaque-interior fixture alone does not prove the rim-repair workflow): an antialiased, partly transparent edge over an accepted base. A colour correction painted on a new `inherit_alpha` layer under `preserve_composite_alpha` passes with every composite alpha byte unchanged and the base untouched; the same stroke on a normal layer is rolled back. Scope fixtures: a scatter preset in `verify: region` and `verify: full` reaches the same verdict, and a filter layer above the target makes region mode answer `UNSUPPORTED_CAPABILITY`.

Colour-maths fixtures (sRGB → CIE L\*a\*b\* D65 with the 7-digit matrix 0.4124564 / 0.3575761 / 0.1804375 … and white 0.95047 / 1.0 / 1.08883; tolerance 0.05):

| Colour | L\*a\*b\* |
|---|---|
| `#FFFFFF` | 100.00, 0.00, 0.00 |
| `#808080` | 53.59, 0.00, 0.00 |
| `#FF0000` | 53.24, 80.09, 67.20 |
| `#A7C284` | 75.12, -19.96, 28.26 (C\* 34.6) |

**Definition of "validated" for Phase 1:** H3, H4, H5, H6 and H8 hold, the contract's exercises pass as scoped above, and the trial has been run with its result recorded. The trial result informs Phase 2 priorities; it does not by itself stop the roadmap (Appendix E, 2026-10-22).

---

## Part 13: Production [draft]

**Scope statement**

Six phases covering the contract's 69 catalogue tools. Phase 1: 19 tools, one plugin, one CLI with five commands, one live harness. Solo developer, one session per chat under `DEVELOPMENT-WORKFLOW.md`; each phase is its own round with its own intake.

**Team & roles**

- **The owner:** decisions, reviews, profile approval, the plugin-enable step, art acceptance.
- **The Codex agent:** first user, trial painter.
- **A Claude Code session:** trial painter.

**Suggested Phase 1 slices** (Session 0 turns these into `SESSIONS.md`; slices follow build order, not the contract's A/B/C letters)

1. Scaffold: repo, `verify`, version in `krita-art-mcp --version` and `krita_server_info`, CHANGELOG, fixtures (the Phase 1 tool examples, amended; the contract's `paint-workflow.example.json` and demo profiles stay reference-only until Phases 2 to 4), README, Commands table (0.1.0).
2. Bridge end to end: plugin load, `bridge.json`, health and capabilities, operations and `operation_get` / `operation_cancel`, request-id journal, `server_info`, `doctor`, `install-plugin`, `roots`; runtime probes (Python version, bridge latency during a long save, kritarc sharing, `edit_undo` name) (0.2.0).
3. MVP-A observe: `document_list`, `document_open`, `document_create`, `document_inspect`, `resource_list`, `capture`, `sample` (0.3.0).
4. MVP-B paint safely: `layer_create`, `layer_update`, `selection_set`, `protection_set`, `paint_stroke` with verification and the input capability gate, `history_step` (0.4.0).
5. MVP-C deliver: `preview_render`, `document_save` with reopen verification, `document_close` (0.5.0).
6. Harness on both Krita builds; H2 preset sheet; the contract's exercises as scoped in Part 12; server instructions finalised (0.6.0).
7. Documentation pass, round close; the trial follows.

**Scope cuts (first cut first, Phase 1)**

F-24, `preview_render` tints, F-20.

**Risks & mitigations:** Part 8, *Technical risks*.

---

## Appendices

Appendices A, B and D of the template are not used.

**C. Open questions for the intake** (each with a recommendation; Q1, Q7 and Q14 are resolved in Appendix E)

| # | Question | Recommendation | Why |
|---|---|---|---|
| Q2 | What round 1 covers | Phase 1 only; Phase 2 is round 2 right after the trial | Phase 1 alone is 7 sessions; the trial's result should shape Phase 2's priorities |
| Q3 | Licence | Decide before publication; GPL-3.0-or-later for the plugin is the safe choice (Part 10) | The repository itself is decided (Appendix E, 2026-10-23) |
| Q4 | Release cadence | Per session (workflow default) | |
| Q5 | Keep `document_close` | Yes, unless the harness reproduces a crash in 20 cycles | Prior-art crash report |
| Q6 | Where working copies go | An explicit `working_dir` per open in Phase 1; the profile's first working root from Phase 2 | Never next to accepted sources |
| Q8 | Krita builds on the Mac | Both 5.3.x and 6.0.x installed; daily use on 5.3.x | K1 |
| Q9 | A Krita development build for early Phase 6 probes | Yes, for capability probes on throwaway documents only | Real pressure is the biggest look risk (H2) |
| Q10 | Capture defaults | `max_px` 1600, background `checker` | Claude Code's inline image limits; visible alpha |
| Q11 | Server run mode | `uv run --project <repo>`; no `uv tool install` | Each session's change is live |
| Q12 | The contract package in the repo | Copy unchanged to `docs/spec/reference/contract-package/`; this PDD wins where they differ | Its schemas are the starting point, not the contract |
| Q13 | Translate in `transform_apply` (Phase 2) | Decide at Phase 2 intake: transform mask, or journaled reverse move | `Node.move` has no undo (K25) |

**E. Decision log**

| Date | Decision | Rationale | Alternatives considered |
|---|---|---|---|
| 2026-10-22 | Krita is the 2D non-pixel editor for all games; pixel art stays in Aseprite | Best brush engine among free tools; opens ORA natively | GIMP 3.2, Aseprite family, Inkscape, Blender |
| 2026-10-22 | Our own MCP server, written from scratch (patterns and attributed code only from MIT or CC0 projects), reusable across games | Existing servers are young, untested on macOS, expose pixel writes or code | Adopt or fork |
| 2026-10-22 | Krita 5.3 and 6.0 supported from day one | 6.0 becomes Krita's main line | 5.3 only |
| 2026-10-22 | Long operations return an operation id | Client timeouts are the recurring prior-art failure | Synchronous calls |
| 2026-10-22 | Own repository, outside any game folder | Serves every game | Inside the first game's repository |
| 2026-10-22 | Brushes, selections and layers; pixel reads, no raw pixel writes | Scripted pixel edits caused the review findings | `Node.setPixelData` / arbitrary Python |
| ~~2026-10-22~~ | ~~Small first version, proven on one real correction before more investment~~ **Superseded the same day by the owner:** The contract's MVP scope; the PDD carries every planned phase; the trial stays as a milestone after Phase 1 | "Let's make it bigger"; "MVP is just one phase; the implementer must understand the whole picture" | The 17-tool trial build |
| 2026-10-22 | Phase 1 = the contract's MVP-A/B/C minus the deferred areas below | The owner's choice of the contract's scope | Our 17-tool v1 |
| 2026-10-22 | Defer revisions and stale-edit detection to Phase 3 | Krita has no per-edit signal; fingerprinting is costly and unproven; the owner does not paint while an agent works | In Phase 1 |
| 2026-10-22 | Defer edit transactions and checkpoints to Phase 3 | Protection by default, per-stroke verification and native undo cover single corrections; the contract's pixel-restore rollback breaks the no-pixel-writes rule | In Phase 1 |
| 2026-10-22 | Defer registration, export and validation to Phase 4; Phase 1 has no PNG export tool | The existing Pillow pipeline works and reads the `mergedimage.png` in saved files; moving it is a separate migration | In Phase 1 |
| 2026-10-22 | `paint_shape` moves to Phase 2 | The owner: in Phase 1 only if needed; it isn't, because a closed `paint_stroke` polyline draws any outline | Outline-only `paint_shape` in Phase 1 |
| 2026-10-22 | Project profiles move to Phase 2 | The owner: "do we need this for the phase 1? if not - move to phase 2"; Phase 1 tools take explicit values, and profiles are first needed to gate Phase 2 operations | Profiles in Phase 1 |
| 2026-10-22 | Plan and build filters, transforms, colour and palette conversion (Phase 2), explicit and profile-gated | The owner: "if it makes sense let's plan and do it"; needed for new artwork; the profile keeps per-game rules such as the first game's hand-repaint rule | Never |
| 2026-10-22 | Plan for Krita 6.1 / 5.4 input-aware strokes (Phase 6); the Phase 1 contract accepts per-point input and gates it by capability | `paintPolylineStroke` exists on Krita master, not in released builds | Ignore until released |
| 2026-10-23 | Name: **krita-art-mcp**. Package, CLI and repository `krita-art-mcp` (Python import `krita_art_mcp`), Krita plugin module `krita_art_mcp_bridge`, MCP server name `krita-art`, data dir `~/Library/Application Support/krita-art-mcp/` | The name must be clear and searchable for anyone looking for a Krita MCP; one name for repo, package and command leaves nothing to keep in sync | - |
| 2026-10-23 | The GitHub repository `krita-art-mcp` stays private until publication. At publication: description "MCP server that lets AI agents paint in Krita" and topics `krita`, `mcp`, `model-context-protocol`, `krita-plugin`, `game-art` | GitHub search ranks on description and topics | - |

**F. Graveyard**

| Date | Idea | Why it was cut | Could return if |
|---|---|---|---|
| 2026-10-22 | Tapered strokes by chaining `paintLine` segments | Separate strokes and undo steps, joins overlap, integer points (K4, K9) | Never: Phase 6 does it properly |
| 2026-10-22 | `run_python` / `write_pixels` tools | Breaks pillar 1 | Never |
| 2026-10-22 | A persistent `set_brush` tool | Hidden window-wide state (K3) | Never |
| 2026-10-22 | Rollback by writing snapshot pixels back | Breaks pillar 1; native undo and checkpoint reopen replace it | Never |
| 2026-10-22 | `Filter.apply` | No undo, no stroke, ignores selection (K24) | Never: `startFilter` instead |
| 2026-10-22 | Tool-level smoothing (`basic`, `stabilizer`) | Krita's smoothing belongs to the freehand tool, which scripts bypass | Krita exposes it to scripts |

**G. Tool map: the contract's 69 tools** (placements beyond the owner's rulings are proposals)

| Tool (`krita_` prefix) | Contract phase | krita-art-mcp phase | Note |
|---|---|---|---|
| server_info, document_list, document_open, document_create, document_inspect, resource_list, capture, sample | MVP-A | 1 | Amendments in Part 4 |
| project_load | MVP-A | 2 | Moved by the owner |
| layer_create, layer_update, selection_set, protection_set, paint_stroke | MVP-B | 1 | Amendments in Part 4 |
| checkpoint_create, edit_begin, edit_commit, edit_rollback | MVP-B | 3 | Deferred by the owner |
| history_step, operation_get, operation_cancel, preview_render, document_save, document_close | MVP-C | 1 | `restore_checkpoint` and `discard_with_checkpoint` in Phase 3 |
| registration_set, asset_export, validation_run | MVP-C | 4 | Deferred by the owner |
| selection_query | Extension | 1 (folded) | Into `document_inspect` and `capture` with `target: selection` |
| selection_clear, selection_from_alpha | Extension | 1 (folded) | Into `selection_set` (`none`, `all`, `layer_alpha`) |
| paint_shape, document_duplicate, layer_duplicate, layer_reorder, layer_remove, layer_import, mask_edit, paint_path, paint_fill, paint_clone, transform_apply, canvas_resize, filter_apply, palette_manage, color_convert, reference_set, guides_set, view_set | Extension | 2 | Construct |
| diff_measure, recovery_list, recovery_open, diagnostics_get | Extension | 3 | Integrity |
| asset_metadata_set, export_batch, atlas_pack, engine_package | Extension | 4 | Delivery |
| animation_inspect, animation_frame_edit, animation_clip_set, animation_preview, animation_export, tile_configure, tile_preview, tileset_export, scene_render, background_preview, ui_preview, text_edit, vector_edit | Extension | 5 | Asset modules |
