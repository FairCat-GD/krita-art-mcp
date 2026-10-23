# Brief: reusable Krita MCP for 2D game art

22 October 2026 · Current and future 2D games · Requirements

**Implementation companion:** [Concrete MVP tools, schemas and example exchanges](krita-mcp-contract/README.md). It contains 27 MVP tools in build order, 42 extension tools, JSON input/output examples, project-profile fixtures, a paint-to-export sequence and failure/rollback contracts. Start there when building; this brief explains the workflow and quality requirements.

Build a dependable way for me to inspect a painting, make precise local brush edits, inspect the result at game size, and undo or save a revision. Our accepted art is the quality floor: preserve its authored shapes, materials, shading and edge pixels. Technical compliance must never turn rich paintings into simplified substitutes.

**Scope: a reusable art workstation, configured per project.** Support new drawings as well as revisions, including painted sprites, illustrations, backgrounds, tiles, UI and painted frame animation. **Pixel-art authoring stays in Aseprite.** Krita should handle painted and other non-pixel-art 2D work; do not duplicate Aseprite's pixel-grid editing or pixel-animation workflow. Aseprite exports may be used as immutable references or composition inputs. The first game is our first integration fixture, not the server's architecture. Do not hard-code its asset names, palette, outlines, camera, units, resolutions, lighting states, collision rules, directory structure or approval sequence.

Load a versioned project profile plus optional per-asset overrides. Validate and return the effective profile before work. Keep the following outside the server's generic painting core:

| Profile area | Configurable contract |
|---|---|
| Art direction | Approved references, style, brushes, palettes, colour profiles, permitted transformations |
| Coordinates | Master/export dimensions, pixel or world units, origin and axis directions, registration, pivots and attachment points |
| Display | Review sizes, viewport sizes, camera/zoom, pixel snapping, filtering, lighting and composition fixtures |
| Asset type | Sprite, tile, background, UI/icon, animation frame; type-specific metadata and validation |
| Delivery | Naming, paths, export formats, atlas rules, metadata schema and engine adapters |
| Preservation and review | Accepted baselines, editable regions, protected properties, validation commands and owner approval gates |

Asset IDs, paths and validators are supplied explicitly. Profile changes are visible, versioned changes; do not infer a new art rule or silently weaken a limit after a failed check. An unsupported capability should produce a clear limitation, not a substitute deliverable.

**1. Precise painting is the core capability.**

- Address every operation by document and stable layer ID. Supply stroke coordinates in document pixels, independent of canvas zoom, pan, rotation, window size or Retina scaling. Expose canvas origin, layer offsets and preview-to-document transforms explicitly.
- Paint with Krita’s actual brush engine. Select presets by a stable identifier or resource hash; set colour/profile, size, opacity, flow, eraser mode and supported brush parameters. Accept ordered stroke samples with pressure, and timing/tilt where supported. Report the effective settings and any unsupported input; never silently discard parameters or substitute a brush.
- Support small deliberate strokes, curves and exact pixel placement when needed. Explicitly control smoothing, spacing and antialiasing where available. Do not promise repeatability for stochastic brushes without a tested seed mechanism.
- Provide rectangular, polygonal and raster selections; add, subtract, intersect, feather and invert; expose the actual resulting mask. Support alpha lock, inheritance/clipping and separate paint layers. Selection coordinates and masks must be inspectable before painting.
- Sample colours and inspect small regions at native resolution. Return both the layer’s pixels and the visible composite, clearly distinguished.
- Create documents, reusable layer groups and reference arrangements for new artwork, with explicit dimensions, colour space and template. Support duplication and deliberate transforms for authorized construction without treating mirrored or recoloured copies as newly drawn variants.

**2. Preserve accepted layers and protected regions.**

Open accepted sources as protected baselines and create working copies. Default revisions belong on new named paint layers or masks. Give me the complete layer tree: IDs, types, ordering, visibility, opacity, blend modes, locks, masks, offsets and colour properties. Legacy flat PNG/ORA sources can become an immutable base layer with edits above it; do not invent a recovered layer structure.

Locks must be enforced by the server, including destructive operations on parent groups. Protect not only pixel content but also visibility, opacity, transforms, masks and blending when those affect the accepted appearance. Do not silently unlock, merge, flatten, recolour, resize or replace accepted layers.

For each edit, accept an allowed-change mask and optional invariants such as “preserve alpha,” “preserve hull exterior,” or “preserve these layers.” Check the **visible composite outside the allowed region**, as well as protected layer content. Brush scatter, blur and soft edges must not leak beyond the authorized region. On a failed invariant, roll back and return a diagnostic diff.

Use pixel/content hashes and layer-property snapshots for preservation checks. Keep original source-file hashes too, but do not equate a changed `.kra` container hash after saving with changed paint.

**3. Make every edit observable and reversible.**

Expose checkpoints, undo/redo and rollback for bounded edit batches. Mutations should require an expected document revision, so an edit based on a stale preview cannot overwrite a human change. Serialize mutations per document and use operation IDs to prevent duplicate strokes after retries.

Return completion status, new revision, affected layers, changed-pixel bounds, before/after crops, alpha changes and protected-region differences. A queued command is not a completed stroke. Wait for painting and projection updates before returning the final preview. Cancellation or partial failure must report what happened and whether rollback succeeded; retain a recoverable checkpoint if native undo is insufficient.

**4. Show the actual asset at game size.**

Take the target scale from the profile: exact screen-pixel dimensions for UI/icons, or pixels per world unit and camera zoom for sprites. Support multiple aspect ratios and viewports. A larger painting master needs its registered export transform first. For a world-unit profile, preview scale relative to export is `target pixels/unit ÷ export pixels/unit`; projects without world units should not need to invent them.

For example, the first game exports at **4 px/unit** and reviews at **2.95** and **1.8 px/unit**, or 73.75% and 45% of export size. These are profile values only. Another game might require painted UI icons and panels at several display densities.

Provide native-resolution crops and lossless, explicitly sized preview images. Report their dimensions, resampling filter, colour profile, document revision and coordinate mapping. A fit-to-window screenshot is not evidence of game size. Distinguish image pixels, CSS pixels and physical display pixels; browser or OS scaling must not silently change the claimed scale.

Build comparison sheets showing before/after, the accepted sibling and the approved references at comparable scale. Place assets in project-supplied compositions with correct anchors, overlaps and draw order. Use appropriate contexts: a sprite in a level, an icon in a HUD, a panel with sample content, a repeated tile patch or a scrolling background. Support configured lighting states and greyscale as preview-only transforms; the first game uses four states. Collision polygons, reserved envelopes, anchors and selection boundaries should be toggleable overlays, never baked into export art.

Static previews do not certify scrolling, mipmaps or physical-phone appearance. Keep those gates separate.

**5. Keep painting, registration and export distinct.**

Save layered `.kra` revisions and reopen them to verify layer structure and pixels. Import PNG/ORA sources initially, and expose further formats only when tested on the installed build. Export transparent PNGs with explicit profile, dimensions and alpha handling. Preserve hidden source layers in the native document. Save/export should not flatten the working source or overwrite the accepted baseline by default.

Expose uniform scale, subpixel translation, padding, crop and anchor metadata as explicit registration operations. Report the full master-to-export transform and filter. No automatic palette normalization, outline synthesis, contour replacement or nonuniform resizing. Projects that explicitly need palette conversion or nonuniform transforms may authorize them as separate, reviewable operations on working copies; they must never be hidden export cleanup. Collision metadata must remain separate from paint, and the server must never relax a project's checker or spec to make an asset pass.

Keep engine delivery in adapters: individual images or sprite sheets/atlases with explicit padding, edge extrusion, trim offsets, rotation permissions and metadata. Preserve stable pivots and attachment points when cropping. Declare straight versus premultiplied alpha and colour conversion. Do not assume a particular engine, packing scheme, filename convention or coordinate system. Validate exported files after writing them, including transparent edges and bounds.

An earlier correction pass of the first game is one useful fixture: three fixes changed collision only; another asset used a 99.8% uniform export and an anchor correction from its untouched master. The server should make this distinction easy to reproduce and prove.

**6. Suggested first tool surface and implementation approach.**

These are proposed MCP operations, not claims about existing Krita methods:

| Tool group | Minimum useful operations |
|---|---|
| Discover and inspect | Capabilities/version, documents, layer tree, brush resources, selection, pixel sampling, composite/crop capture |
| Prepare and protect | Working copy, checkpoint, new paint layer/mask, protected layers/regions, expected revision |
| Paint | Brush configuration, stroke samples, selection edits, bounded edit batch, operation status/cancel |
| Review | Before/after diff, preservation verification, game-size preview, sibling/board sheet, composition overlays |
| Deliver | Save revision, reopen verification, registered PNG export, transform/anchor metadata, undo/rollback |

**Asset workflows the design must accommodate.** These can arrive in stages, but document/frame identity, metadata and profiles must support them from the outset:

- **Frame animation:** explicit frame identity for reads and edits, keyframes, holds/durations, frame rate, named clips, onion-skin views and playback/contact sheets. Preserve registration, pivots and attachments across frames. Export ordered frames/sheets and timing metadata; verify loop endpoints and accidental frame changes. Root-motion metadata is optional and project-defined. Native animation support must be capability-tested; a declared frame-per-document fallback is acceptable when necessary.
- **Tiles and terrain:** tile dimensions, repeat axes, wrapped painting/preview where supported, seam inspection on repeated patches, and explicit adjacency/autotile layouts. Verify joins at corners and edges without “fixing” a seam by repainting unrelated accepted tiles.
- **Backgrounds and modular scenery:** large-canvas region access, layered/parallax previews, repeat and scroll bounds, connector alignment and camera crops. Stream requested regions instead of transferring an entire huge document for each stroke.
- **UI, icons and interface parts:** native-size variants, state sets, alignment guides, safe areas, transparent padding and nine-slice margins. Inspect at intended display densities and in representative layouts. Preserve editable text/vector content when supported; disclose rasterization and keep an editable source copy when it is explicitly requested.
- **Character/object part sets:** named layers, sockets, pivots, facing variants and occlusion order for engine-side assembly. Keep metadata editable separately from painted pixels. Do not assume every asset is one flattened sprite.

Shared transforms, measurements and previews belong in the server; gameplay-specific rules and asset catalogues belong in project adapters. Do not bundle game logic into the painting interface.

Start by testing the installed Krita build and its Python bindings. Official documentation exposes plugin extensions and layer/pixel/painting APIs; newer development source also includes stroke interfaces. Availability and behavior must be probed on the actual installed version. References: [Python plugin guide](https://docs.krita.org/en/user_manual/python_scripting/krita_python_plugin_howto.html), [Node API](https://api.kde.org/legacy/krita/html/classNode.html), [upstream Node source](https://github.com/KDE/krita/blob/master/libs/libkis/Node.h).

My preferred architecture is a small local MCP bridge to a Krita plugin, with document operations dispatched through Krita’s appropriate application thread. Verify real brush behavior, selection enforcement, undo and save semantics before choosing API fallbacks. Clearly identify any UI-driven fallback. Raw pixel access is useful for inspection and checks; it must not quietly replace requested brush painting. Keep normal tools typed and narrowly scoped rather than making arbitrary script execution the main interface.

**7. First release acceptance exercises.**

1. Paint a small selected repair at two different canvas zoom/pan settings. Both land at the requested document coordinates; pressure/settings are honored or explicitly reported unsupported.
2. Add a detail on a new layer while preserving an accepted base, exterior pixels and alpha exactly. Use a cargo detail on a sprite as one fixture and a character accessory or UI icon as another. Attempted edits to the protected base are rejected.
3. Paint near a protected boundary with a soft or scattered brush. Verify zero composite changes outside the permitted mask; a violation rolls back.
4. Undo a batch, retry a completed request, and simulate interruption. No duplicated stroke or silent partial success; recovery is verifiable.
5. Load two different project profiles. Produce the first game's 2.95/1.8 px/unit comparisons, then 128×128 and 256×256 painted-icon previews for a separate high-resolution UI profile. Verify no inherited palette, filtering, unit, path or approval assumptions. Previews are fresh and overlays do not enter exports.
6. Save, close and reopen the `.kra`; verify layers, masks, visibility, profile and pixels. Export PNG and run the unchanged project checker. Report file/geometry validation, visual judgment, owner approval and runtime/device validation separately.

Before declaring the later asset modules complete, test a seamless tile patch, a short timed animation with a stable pivot, a nine-slice UI panel and an atlas trim/export round trip under their own profiles.

Deliver in stages: first the complete inspect–paint–protect–undo–preview–save loop, demonstrated on both world-unit sprite and high-resolution UI profiles; then animation, tiles, modular assets and engine export adapters. The first milestone must include a carefully painted, reversible local correction on a real working copy, accepted content preserved, and game-size evidence ready for review. Follow each project's configured approval policy; The first game's first-drawing gate is an example, not a universal hard-coded sequence. The owner remains the authority for art acceptance.
