# Krita MCP build contract · proposed API 0.1.0

Use this alongside the [workflow brief](../krita-mcp-art-workflow-brief.md). It defines **27 MVP tools** and **42 extension tools**, with example inputs and outputs. These are proposed interfaces, not a working server or evidence that a particular Krita build supports them. The catalogue aims to cover our foreseeable 2D workflows; keep capability discovery and versioned extensions so new needs do not require a redesign.

**Division of tools:** Pixel-art authoring and pixel animation belong in Aseprite. This Krita server handles painted/non-pixel-art work, including painted frame animation. It may inspect or compose Aseprite exports as immutable inputs, but does not need pixel-write tools or a pixel-art profile.

**Start here.** [MVP tool definitions](mvp.tools.json) contain input/output JSON Schemas suitable for adapting into MCP tool registration. [The complete catalogue](TOOL-CATALOGUE.md) is readable tool-by-tool. [tools.json](tools.json) includes phase, notes and complete example receipts for all 69 tools. Only MVP schemas are the initial implementation target; extension schemas describe draft example shapes and need their final unions, enums and constraints before exposure.

[paint-workflow.example.json](paint-workflow.example.json) shows a complete request/result sequence. [errors.example.json](errors.example.json) shows six failure responses. The [world-unit painted sprite](painted-demo.profile.json) and [high-resolution UI](ui-demo.profile.json) profile fixtures use this [starter profile schema](profile.schema.json). The schema deliberately starts small; expand it with versioned reference, scene and adapter schemas as those modules arrive. Fixture paths, resource IDs, hashes and measurements are fictional. Replace them with discovered values and generated receipts; never copy them as actual preservation evidence.

**Build order and tool list.**

| Phase | Tools, with `krita_` prefix | Deliverable |
|---|---|---|
| MVP-A: observe | `server_info`, `project_load`, `document_list`, `document_open`, `document_create`, `document_inspect`, `resource_list`, `capture`, `sample` | Open a working copy; inspect actual layer IDs; return a fresh crop and pixel samples with correct coordinates/profile |
| MVP-B: paint safely | `layer_create`, `layer_update`, `selection_set`, `checkpoint_create`, `protection_set`, `edit_begin`, `paint_stroke`, `edit_commit`, `edit_rollback` | Native-brush repairs on a sprite and a painted UI asset, with enforced protection and verified rollback |
| MVP-C: deliver | `history_step`, `operation_get`, `operation_cancel`, `registration_set`, `preview_render`, `document_save`, `asset_export`, `validation_run`, `document_close` | Game-size review, layered save/reopen, registered PNG/metadata, immutable validation receipt and recoverable close |

Do not postpone operation status and cancellation plumbing until the final phase: all phases need it internally. Expose long operations through `operation_get`/`operation_cancel` as soon as they exist. Finish the whole MVP before claiming the core workflow is usable.

**Shared request and result rules.**

- Document reads use `{document_id, revision, frame}`. `document_inspect` discovers the current revision. A static document uses frame 0; MVP rejects other frames until animation support is verified. A pinned read must return that exact snapshot or `STALE_REVISION`; it cannot silently inspect whatever is active.
- Mutations use `guard: {document_id, expected_revision, request_id}`. `request_id` identifies the intended operation, while a server-generated `operation_id` identifies asynchronous execution. Profile loads, opens, creates and file exports also require request IDs even when they do not modify existing pixels.
- A retry with the same request ID and canonical arguments returns the same receipt/operation. A different payload using that ID fails with `REQUEST_ID_CONFLICT`. Check the deduplication journal before the revision check: a successful retry must not become a stale-revision failure. Record the session/recovery lifetime; after an unrecoverable restart, never blindly replay an uncertain stroke.
- Revisions increase for art, selection, protection, registration and relevant metadata changes, including undo/rollback. Creating a checkpoint, reading, previewing, saving and exporting do not change the content revision. All writes within a paint transaction also advance revision; callers use each returned revision for the next call. UI-only zoom/pan has separate view state.
- Use actual document/node IDs and hashes. Detect deleted/invalid handles; layer names are labels. Reopening can create new IDs, so return an explicit mapping. Human changes must invalidate stale requests. If native change notifications are insufficient, use a verified state fingerprint at mutation boundaries and stage edits in isolated copies; do not claim robust conflict detection until demonstrated.
- Every tool returns `structuredContent` conforming to its output schema, plus a short readable text result. Captures/previews also return native image content or a readable artifact resource. The common envelope is `{api_version,status,document_id,revision,operation_id,data,error}`. `completed` means the tool finished; queued/running operations return `data:null` and a non-null `operation_id` until their final typed receipt is available.
- Tool execution failures use MCP `isError:true` and a structured error. Validation findings are successful execution with failing checks in `data`; they are not transport failures. `operation_get` may itself complete while its `data.state` says the observed operation is still running or failed. Do not confuse these two states. See the official [MCP tools/result specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
- Every schema must reject unknown input fields. Apply JSON Schema validation plus semantic checks for resource existence, current revision, profile compatibility, coordinate bounds, brush support, operation ordering and cross-field constraints. Never clamp coordinates, normalize paint colours, ignore unsupported brush settings or silently substitute resources.

The `outputSchema` includes normal and failure paths. Treat tool annotations as descriptive hints, not enforcement. A mutation marked idempotent still needs the request journal and protection checks. Only advertise tools actually implemented and tested; publish capability changes when available tooling changes.

**Coordinate, colour and artifact contracts.**

Document-space coordinates use top-left origin, x right, y down. Rectangles are `{x,y,width,height}` with half-open bounds. Brush points use continuous coordinates and a one-pixel dab at cell `(x,y)` is centered at `(x+0.5,y+0.5)`. Layer offsets, negative bounds and transformed parents must be accounted for. Reject points outside the allowed working bounds unless a profile explicitly permits growth.

Six-number affine arrays are row-major `[m00,m01,m02,m10,m11,m12]`, mapping `x'=m00*x+m01*y+m02`, `y'=m10*x+m11*y+m12`. Registration maps `export=(document-source_rect.origin)*uniform_scale+translation`. Export crop, transparent padding and anchor are explicit. Use declared output dimensions and pixel-center resampling, with a named filter/backend; include the actual transform after rounding. Never produce the final game-size image by resizing a preview that has already been resized.

MVP brush colours are normalized, straight-alpha sRGB RGBA. Convert once into the document's actual profile, or fail when unsupported. Native pixel reads identify channel order, depth, stride and profile; do not assume Krita buffers are RGBA. Selection/allowed-change masks are linear single-channel 8-bit coverage. The hard allowed-change mask is binary (0 or 255); any weighted feathering belongs to a separate selection. A profile's palette references exact colour values and transparency rules.

`krita-artifact://…` and `krita-checkpoint://…` are proposed server-owned identifiers, not assumed existing protocols. Implement artifact reads through MCP resources, with MIME type, dimensions where applicable, hash, byte size and retention lifetime. Inputs can reference only resolvable artifacts or authorized local files. Publish a retained local output path when the client cannot read a resource URI. Do not put megabytes of base64 pixels into text receipts. Tile/crop large images and bound output sizes; do not silently lower resolution.

**Transaction and preservation state machine.**

1. Open a working copy and create a checkpoint. Add an editable layer; inspect and bind a selection. Establish the preservation policy against an explicit checkpoint. Initialization/tightening is allowed; ordinary editing tools cannot weaken it.
2. `edit_begin` pins target layer, frame, selection, profile and protection policy and creates a recoverable transaction checkpoint. States are `open → committing → committed`, or `open/committing → rolling_back → rolled_back`; failure/conflict states retain recovery information. Only one transaction may own a document at a time.
3. Each stroke applies explicit brush resources/settings to the pinned target. Check supported brush behavior before writing. Brush operations may update the working preview but cannot save/export as an accepted result while uncommitted. Per-stroke protection checks reduce damage; the commit check is still mandatory.
4. Commit waits for paint/projection completion, then checks protected layer pixels and appearance-affecting properties, full composite outside the allowed mask, canvas/alpha invariants and untouched frames. Default protected comparison is exact native pixels/properties, plus a fixed-profile lossless composite; tolerances exist only when the profile explicitly defines them. No “visually close” substitute for byte equality.
5. If protection fails, restore and verify the checkpoint, advance revision, return `isError:true` and a diff/report. Rollback is not complete until restoration is checked. If a human changed the document concurrently, preserve the human state and transaction branch, return a conflict, and do not overwrite either.
6. One committed batch should be one native undo unit where possible. If Krita APIs cannot provide that reliably, use the tested server checkpoint restore path and declare the limitation. On cancellation or crash, retain the last verified checkpoint and operation journal. Interrupted output files remain temporary, never a final deliverable.

Protection spans ancestors: deleting/reordering a group, changing opacity/blend mode, adding a mask, transforming a parent or flattening must not circumvent a protected child. Protect hidden source layers too. A new overlay can change the visible protected area even if the original layer bytes remain identical; this is why composite comparison is required.

**A concrete paint-to-export exchange.**

The JSON workflow file assumes an opened `doc-1` at revision 12 with a protected base, a resolved brush, an sRGB profile and an opaque repair region. IDs shown there are example responses; a real client must bind every later ID/hash to its corresponding earlier response. Independent examples in the tool catalogue are not a sequential script.

| Step | Input | Required output/use |
|---|---|---|
| Inspect/checkpoint | `document_inspect(doc-1)`, then `checkpoint_create` at r12 | Current tree and `cp-1`; art stays at r12 |
| Prepare | `layer_create` r12, `selection_set` r13, `protection_set` r14 | New repair layer, mask artifact/hash, protected baseline; r15 |
| Paint | `edit_begin` r15, `paint_stroke` r16 | Edit ID, effective brush settings and fresh crop; r17 |
| Inspect/commit | `capture` r17, `edit_commit` r17 | Exact protected/alpha diff counts and verified commit; r18 |
| Register/review | `registration_set` r18, `preview_render` r19 | Master-to-export matrix, anchor, unoverlaid game-size proof; r19 |
| Deliver | `document_save`, `asset_export`, `validation_run` | Reopened native source, PNG and metadata hashes, separate validation results |

For example, the native-brush request explicitly contains pressure and colour, without relying on the active UI brush:

```json
{
  "name": "krita_paint_stroke",
  "arguments": {
    "guard": {"document_id":"doc-1","expected_revision":16,"request_id":"repair-stroke-001"},
    "edit_id":"edit-1",
    "brush": {
      "preset_id":"brush-ink-1",
      "preset_sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      "size_px":2,"opacity":1,"flow":1,
      "color":{"space":"srgb","rgba":[0.4,0.3,0.3,1]},
      "eraser":false,"smoothing":"none","antialias":true
    },
    "points":[
      {"x":22.5,"y":24.5,"pressure":0.4,"time_ms":0},
      {"x":27.5,"y":26.5,"pressure":0.7,"time_ms":30}
    ]
  }
}
```

An expected successful receipt has r17, `accepted_points:2`, actual changed bounds, `protected_pixels_changed:0`, the effective brush settings and a fresh preview artifact. A protection failure instead returns a result like:

```json
{
  "isError":true,
  "content":[{"type":"text","text":"Commit rejected; changes escaped the allowed mask. Rollback verified."}],
  "structuredContent":{
    "api_version":"0.1.0","status":"failed","document_id":"doc-1",
    "revision":18,"operation_id":null,"data":null,
    "error":{
      "code":"PROTECTED_REGION_CHANGED","message":"Two pixels changed outside the allowed mask.",
      "retryable":false,
      "details":{"changed_pixels_outside":2,"rolled_back":true,"rollback_verified":true,"checkpoint_id":"cp-edit-1"}
    }
  }
}
```

Failed operations must distinguish no writes, partial writes, verified rollback and unresolved recovery. Other required error codes include `INVALID_ARGUMENT`, `STALE_REVISION`, `REQUEST_ID_CONFLICT`, `DOCUMENT_NOT_FOUND`, `LAYER_NOT_FOUND`, `LOCKED_TARGET`, `OUTSIDE_ALLOWED_MASK`, `UNSUPPORTED_CAPABILITY`, `RESOURCE_HASH_MISMATCH`, `COLOR_PROFILE_MISMATCH`, `EXPORT_CLIPS_ART`, `FILE_EXISTS`, `BUSY`, `TIMEOUT`, `CANCELLED`, `ROLLBACK_FAILED`, `EXTERNAL_EDIT_CONFLICT` and `IO_ERROR`. Report actionable details and current revision, without exposing unrelated files or secrets.

**Future capability map.**

| Module | Tools in the extension catalogue |
|---|---|
| Document and layers | duplicate document/layers, reorder/remove/import layers, mask edits |
| Painting and selections | selection query/clear/from-alpha, brush paths, fills, clone painting, shapes |
| Construction and colour | transform masks/affine edits, canvas resize, explicit filters, palette management/profile conversion |
| Inspection and composition | exact diffs/measurements, reference sets, guides, UI view controls, asset metadata |
| Animation | inspect, edit frames, define clips/timing, onion skins/playback/contact sheets, export |
| Tiles and backgrounds | configure repeat/wrap, seam previews, tileset export, scene and parallax previews |
| UI and editable content | UI/state/nine-slice preview, editable text and vector operations |
| Delivery and recovery | atlas packing, batch export, engine packaging, interrupted-state discovery/recovery, diagnostics |

Larger future additions can include perspective/warp controls, rig/mesh adapter metadata, depth/normal/material maps, localization/font proofs and external reference-board adapters. Add each through a versioned capability with its own typed schema and acceptance fixtures. Never route an unsupported typed operation through a hidden arbitrary-code fallback. No finite list guarantees every future need; the stable document/coordinate/protection/revision contracts are what make extensions safe.

**Implementation and verification requirements.**

Use a local MCP process and a Krita plugin with a bounded, authenticated local IPC channel. Keep native document operations on the appropriate application thread and use supported API completion mechanisms without deadlocking it. Krita documents expose methods such as `refreshProjection`, `waitForDone` and node lookup by unique ID; probe their behavior on the installed version rather than assuming they provide complete transaction semantics. [Official Document API](https://api.kde.org/legacy/krita/html/classDocument.html). Retain source and checkpoint backups independently of native undo.

Before implementation, report a capability matrix for the actual installed build: native brush/pressure/settings, mask enforcement, selection behavior, reliable completion, native undo grouping, save/reopen fidelity and animation support. A missing feature should identify a declared fallback or remain unsupported. Configured validator adapters receive immutable inputs; requests select adapter IDs, never shell commands. Keep engine-specific logic in adapters, outside the paint core.

The MVP acceptance suite must cover: pressure/coordinate consistency across zoom/pan/rotation; painted UI at multiple display densities; protection against parent/property/mask changes; edge bleed; selection feathering; undo/rollback; retries after success and after timeout; request-ID reuse with different input; external edits; stale capture; native completion barriers; crash/cancel recovery; save/reopen of hidden layers and masks; alpha/profile/channel-order correctness; subpixel registration and clipping; straight-alpha PNG round trip; and two different project profiles without leaking state between them. Later modules add frame timing/pivot, tile seam, nine-slice and atlas trim round-trip tests.

This package's example checks validate the proposal's data shape and internal consistency only. They do not test Krita, rendering, brush fidelity, runtime integration or owner art acceptance. Run `build_contract.py` to regenerate schemas/catalogue/examples, then `check_examples.py` to verify them.
