# krita-art-mcp user guide

krita-art-mcp is a Krita MCP server. It lets an AI agent paint in your running Krita with Krita's own
brush engine, on a copy of your work, with your accepted art protected. This guide is for the person
setting it up and for the agent using it. `docs/ARCHITECTURE.md` explains how it works.

It covers Phase 1: observing a painting, painting safely, and delivering a verified save.

## What you need

- macOS. It is tested on Apple Silicon with Krita 5.3.4.
- Krita 5.3.x, **with its interface in English.** Undo and rollback confirm each step by the English
  name Krita gives it. In another language ordinary calls work, but undo is refused, and a change
  that needs a rollback ends with the document marked unsafe.
- Krita's cumulative undo switched off. A stroke is refused while it is on, because it would merge
  strokes into one undo step.
- [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for the server, and Python 3.10 for the
  plugin's tests.
- An MCP client. Codex and Claude Code are the two it is tested with.

## Install

1. From this repository, copy the plugin into Krita:

   ```bash
   uv run krita-art-mcp install-plugin
   ```

2. Quit Krita and start it again.
3. In *Configure Krita › Python Plugin Manager* (in the application menu on macOS), enable
   *Krita Art MCP Bridge*.
4. Quit Krita and start it again.
5. Allow the folders agents may use, one command each. An agent can name no file outside them, and
   its working copies go into a folder inside them:

   ```bash
   uv run krita-art-mcp roots add /path/to/your/art
   ```

   `roots list` shows them, and `roots remove <folder>` takes one away. `roots add` refuses `/`, your
   home folder, and krita-art-mcp's own data folder, anything inside it, or any folder that holds it.
   If `config.json` already lists one of those, every path is refused until you remove it.
6. Check the setup. `doctor` names the first step that fails, and how to fix it:

   ```bash
   uv run krita-art-mcp doctor
   ```

## Register the server

Apps started from the Dock do not inherit your shell's `PATH`, so both registrations use absolute
paths. Replace `/Users/<you>/.local/bin/uv` with the output of `which uv`, and `/ABS/PATH/krita-art-mcp`
with this repository's folder.

**Codex**, in `~/.codex/config.toml`:

```toml
[mcp_servers.krita-art]
command = "/Users/<you>/.local/bin/uv"
args = ["run", "--project", "/ABS/PATH/krita-art-mcp", "krita-art-mcp", "serve"]
startup_timeout_sec = 20
tool_timeout_sec = 300
```

**Claude Code**, in a `.mcp.json`:

```json
{"mcpServers": {"krita-art": {"type": "stdio", "command": "/Users/<you>/.local/bin/uv",
  "args": ["run", "--project", "/ABS/PATH/krita-art-mcp", "krita-art-mcp", "serve"],
  "timeout": 300000}}}
```

Then ask the agent to call `krita_server_info`. It returns Krita's version and the capability
matrix, or names the setup step that is missing.

**What each tool says it can do.** MCP hints tell a client what a tool may change, and a client may
ask you before any call it calls destructive. Each tool's hints follow the worst it is allowed to
do. Undoable is not the same as additive, so a stroke stays destructive.

| Hints | Tools | Worst it can do |
|---|---|---|
| Read-only | `krita_server_info`, `krita_document_list`, `krita_document_inspect`, `krita_resource_list`, `krita_capture`, `krita_sample`, `krita_preview_render`, `krita_operation_get` | Change no document. Captures and previews write their PNGs to the data folder. One exception, chosen on purpose: `krita_operation_get` polled for a save or a duplicate that came back running finishes it, putting its file in place and opening a duplicate's branch, but only in the server process that made the call |
| Not destructive | `krita_protection_set`, `krita_document_open`, `krita_document_create`, `krita_document_save`, `krita_layer_duplicate`, `krita_document_duplicate` | Add: tighter protection, a working copy, a document, a new file, a hidden copy of a layer, a branch of a document |
| Destructive | `krita_layer_create`, `krita_paint_stroke`, `krita_paint_fill`, `krita_selection_set`, `krita_layer_update`, `krita_layer_reorder`, `krita_layer_remove`, `krita_layer_transform`, `krita_history_step`, `krita_operation_cancel`, `krita_document_close` | Change what is there: what a layer shows (a new mask can hide it, a move can cover it, a translate shifts it), pixels (a scale, rotate or shear resamples them), the selection, a layer, the layer stack, history, a queued call, or unsaved changes a close discards |

**Codex's approval setting.** By default Codex reviews every call a tool's hints call destructive.
Measured in two long sessions, each such call carried 2 to 3 s beyond the tool's own time, and each
read-only call none. From 0.18.0 to 0.21.0 the five additive tools carried none either; since 0.22.0
`krita_layer_create` is destructive again, because a mask can hide a layer. Strokes and selections
make most of those calls and stay destructive, so that saves only a few minutes in a long session.
Trusting this server outright is your choice: add one line to the `[mcp_servers.krita-art]` block
above, not a second block, since TOML refuses a table defined twice.

```toml
default_tools_approval_mode = "approve"
```

It removes Codex's review on every tool of this server, strokes and `krita_document_close`
included. The server still protects, verifies and can undo; what goes is the question before each
call.

**macOS folder access.** macOS keeps an app out of `~/Documents` until you allow it. With the
repository there, a client that cannot read it fails the server's handshake, or reports
`Operation not permitted`. Allow the app under System Settings > Privacy & Security > Files and
Folders, or open the folder in the app, then restart the app.

## Update

Run `install-plugin` again and restart Krita, then restart your MCP client. The server refuses a
plugin of another version with `PROTOCOL_MISMATCH`, so a release needs all three steps. Save your
work first: restarting Krita closes your documents.

## The core loop, from an agent's side

The server gives every agent these rules as its instructions. This is the same loop with the calls
in order.

**1. See what is there.** Call `krita_server_info` first, and do not plan around a capability marked
`supported: false`. Its `limits` give the brush size range, the resource page size and how far a
stroke may run past the canvas, and every field with a range or a unit states it in its schema
`description`, which Codex shows its model where it drops `minimum` and `maximum`.
`krita_document_list` shows what is open. Documents you opened by hand list as
`read_only`, so an agent can read them and never change them.

**2. Open a working copy.** The source is copied and never written. Every layer already in it becomes
protected.

```json
{"source_path": "/art/hero.kra", "source_sha256": "<the file's SHA-256>",
 "mode": "working_copy", "working_dir": "/art/work", "request_id": "<a fresh UUID>"}
```

`working_dir` must be inside an allowed root, and not the source's own folder. `mode: read_only` opens
the source itself and refuses every change. KRA, ORA and PNG open, RGBA 8-bit only.

**3. Look.** `krita_document_inspect` gives the layer tree, protection, the selection and how far
history goes. `krita_capture` gives an image and its PNG's path, in one of two forms: `scale: 1` is the
native crop, the stored pixels, and takes no `background` or `greyscale`; any other scale resamples
with your filter onto a background, checker by default. The filters are `nearest`, `box`,
`bilinear`, `hamming`, `bicubic` and `lanczos`, the same for previews. `krita_sample` gives exact
colours: `rgba_255` in 0–255, the hex, L\*a\*b\* and L\*C\*h, and `color`, the same colour in
the 0–1 shape a stroke's `brush.color` takes, so it paints back unchanged. `color` is always
opaque, because a stroke's transparency comes from its opacity and flow, and null where there is
no colour or the profile is not sRGB. Never judge a colour from a capture. `krita_resource_list` lists brush presets, blend
modes, profiles and palettes.

**4. Add a layer of your own.** Protected layers refuse strokes, on purpose.

```json
{"guard": {"document_id": "doc-1", "request_id": "<a fresh UUID>"},
 "parent_id": "<root_layer_id>", "above_id": null, "type": "paint", "name": "Repair"}
```

`above_id: null` puts it on top. To resume your earlier layers, reopen with `editable_layer_ids` (KRA)
or `editable_layer_names` (ORA, PNG).

**Soften an edge or revise a silhouette with a mask.** A transparency mask hides its layer where it
is black and shows it where white, without touching the layer's pixels. Add one to your paint layer,
starting from `all` (shows everything), `none` (hides everything) or `selection` (the current
selection's coverage, a feathered or PNG one included):

```json
{"guard": {"document_id": "doc-1", "request_id": "<a fresh UUID>"},
 "parent_id": "<your layer>", "above_id": null, "type": "transparency_mask", "name": "Edge",
 "coverage": "all"}
```

Then paint the mask with a stroke or a fill whose `brush.mask` (or the fill's `mask`) is `reveal` or
`hide`, in place of a colour. Each moves the coverage by the opacity: `hide` at 0.5 halves what shows.
A soft brush softens the edge, and a selection confines it as it confines colour. Mask paint takes no
`blend_mode` or `alpha_lock`. `krita_capture` with `target: "mask"` shows the mask alone in grey, and
`krita_layer_update` turns it off and on (`visible`) or renames it. The layer and every group holding
it must be unprotected, and a mask in a file you open is protected like a layer. A mask is checked
against protection like a stroke: one that would hide paint outside the allowed mask is undone. A
mask's `bounds_px` and a mask stroke's `layer_bounds_px` are its layer's, as Krita reports them.

**Try a change on a copy, group layers, remove what you do not keep.**
- **`krita_layer_duplicate`** copies a layer or group, with every layer and mask inside it, as a
  hidden layer directly above it, in one undo step. A layer holding a transform mask, such as one
  you have translated, is not copied: undoing such a copy crashes Krita. Copy first, then translate
  the copy. The source may be protected; the copies are
  yours. Nothing shows until you show the copy with `krita_layer_update` (`visible: true`), perhaps
  hiding the original, to compare. `id_map` gives each copied node's new id. An ORA reopen
  refuses a name two layers share, so name the copy apart from its source, and rename the layers
  inside a copied group with `krita_layer_update` (`name`), which keep their sources' names, or
  reopen a KRA by `editable_layer_ids`.
- **`krita_layer_reorder`** moves a layer or group, with what it holds, under the root or into a
  group, directly above `above_id`, or on top when it is null. Grouping is a reorder: create a
  group, then move layers into it. It takes one undo step for the remove and one for each node it
  adds back (Krita takes a moved group apart and the bridge puts it back), stated in `undo_steps`,
  and the whole canvas is checked against protection. A move of more steps than one undo call takes
  (50, or fewer when Krita keeps fewer undo steps) is refused as `too_many_nodes`: move fewer
  layers at a time.
- **`krita_layer_remove`** removes a layer or group with all it holds, or a transparency mask, in
  one undo step; undone, the same layers come back with the same ids.
- **What they refuse:** a protected layer, or one holding a protected layer (`LOCKED_TARGET`); a
  layer a clone layer shows, which Krita would turn into a paint layer
  (`UNSUPPORTED_CAPABILITY`, `reason: clone_source`); and removing a document's last layer.

**Move a layer by whole pixels.** `krita_layer_transform` with `operation: {type: "translate",
by_px: [x, y]}` moves a paint layer or a group, with all it holds.
- **How.** A transform mask on top of the layer's masks holds the move, so the layer's own pixels
  never change. The first translate adds the mask and moves it, in two undo steps; each later one
  moves the same mask, in one. `undo_steps` says which, and `krita_history_step` takes them back
  together. `translation_px` is the layer's whole move so far, and inspect reports it on the mask.
- **Where paint goes.** Paint, fills and selections on a translated layer act on its own pixels,
  where you aim them, and the result shows moved by `translation_px`. To paint at a place on the
  canvas, aim at that place minus `translation_px`. A stroke's or fill's `changed_bounds_px` and
  `layer_bounds_px` stay in the layer's own pixels. Region verification on the layer, or on any
  layer inside a translated group, is refused: give `verify: "full"`.
- **Masks.** A transparency mask added later sits above the transform mask and stays where it is
  painted on the canvas; one there before moves with the layer.
- **What it refuses:** a protected layer, one holding one, or one inside a protected group; any
  layer but a paint layer or a group; a layer whose transform mask a translate did not make, or
  with more than one, or whose translate mask is hidden; a move past 16384 px in all on an axis;
  and Krita's cumulative undo, which would merge two moves.
- **Saving.** A KRA keeps the move and its mask. An ORA drops the transform mask, so the reopened
  file would show the layer unmoved, and the save is refused (`SAVE_VERIFY_FAILED`).

**Scale, rotate or shear a layer.** `krita_layer_transform` with one of these operations resamples
a paint layer, or a group with every layer in it, through Krita's own Layer > Transform, in one
undo step, about the centre of the layer's bounds (for a group, its shown layers' bounds; hidden
layers inside it turn with it).
- **`{type: "scale", size_px: [w, h], filter}`** makes the bounds w × h px. `filter` is one of
  Krita's eight (`Bicubic`, the default, `Bilinear`, `BSpline`, `Bell`, `Hermite`, `Lanczos3`,
  `Mitchell`, `NearestNeighbor`); any other name is refused, since Krita would quietly use Bicubic.
  Read the bounds from `krita_document_inspect` and work out the size; where an edge is soft the
  bounds after can differ by a pixel.
- **`{type: "rotate", degrees}`**, between -360 and 360: positive turns clockwise on screen. Krita
  resamples with Bicubic.
- **`{type: "shear", degrees: [x, y]}`**, each from -45 to 45: a positive x moves the rows below the
  centre right and those above it left; a positive y moves the columns right of the centre down.
  Krita resamples with Bilinear. A shear too small to move an edge by a pixel is refused, since
  Krita would change nothing.
- **Resampling loses detail,** and undo is the only way back. To keep the original, copy the layer
  first with `krita_layer_duplicate` and transform the copy, or the original with the copy kept
  hidden.
- **What it reports:** `pivot_px`, `bounds_before_px` and `bounds_after_px`, the `filter` Krita
  used, and the whole canvas checked against protection; a leak is undone. The selection does not
  limit a transform: the whole layer turns.
- **What it refuses:** a protected layer or one holding one (`LOCKED_TARGET`); a layer holding a mask
  or a layer of another kind (`reason: node_type`); a transform mask on the layer or on a group
  holding it (`reason: transform_mask`: scale, rotate or shear before you translate); a locked or
  alpha-locked layer, which you unlock with `krita_layer_update` first; a styled layer
  (`layer_style`); a layer a clone layer shows (`clone_source`); an empty layer; a change of
  nothing (`no_change`); more than 50 layers and groups (`too_many_nodes`); reads past 8192 × 8192
  for one layer, or four times that for all of them (`too_large`); and Krita's cumulative undo. A
  layer whose bounds Krita was still settling as the call began is refused for a retry.

**Try a whole alternative on a branch.** `krita_document_duplicate` saves the document to a new
`.kra` path inside a root, verifies the file by reopening it, as a save does, and opens that file
as a document of its own. Its receipt names it `new_document_id`.
- **The branch keeps** every layer id, the protection, the allowed mask and both flags, and the
  source's mode. Its history starts empty, and it has its own `baseline_id`: the document as it was
  when you duplicated it.
- **The source stays as it was,** dirty or not; the receipt says which (`source_dirty`,
  `source_krita_modified`). Save it on its own when you want it kept.
- **Compare the two** with `krita_preview_render`, one source each, each with its own
  `baseline_id`. Reading a baseline costs its whole canvas once, so on large canvases render each
  document with its baseline on its own first; after that, both fit in one render.
- **Close what you do not keep.** A close removes that document's baseline alone.
- **`.ora` is refused** (`UNSUPPORTED_CAPABILITY`): only KRA keeps the layer ids protection names.
- **If the branch was saved but did not open,** the answer is `uncertain` and gives the file's
  `path`. When Krita refused the open at its start, or the open never reached Krita, retry with
  the same `request_id` and it opens; otherwise, or after a Krita restart, `krita_document_open`
  opens the file, with every layer protected.

**5. Say where you may work.** `krita_protection_set` only ever tightens, and it stops undo at that
point, so do it once, with the union of everything you will repair, then confine each repair with a
selection. A polygon or ellipse selection is antialiased, so keep it a pixel inside the allowed mask.

```json
{"guard": {"document_id": "doc-1", "request_id": "<a fresh UUID>"},
 "protected_layer_ids": ["<every protected layer's id>"],
 "allowed_change_mask": {"rect": {"x": 16, "y": 16, "width": 32, "height": 32}},
 "preserve_composite_alpha": true, "preserve_canvas": true}
```

```json
{"guard": {"document_id": "doc-1", "request_id": "<a fresh UUID>"}, "combine": "replace",
 "shape": {"type": "rect", "rect": {"x": 18, "y": 18, "width": 12, "height": 12}},
 "feather_px": 0, "invert": false}
```

To recolour inside a silhouette under `preserve_composite_alpha`, paint on a new layer with
`inherit_alpha` set through `krita_layer_update`.

**6. Paint one stroke per call.** Each is one undo step, checked against protection and undone if it
leaks.

```json
{"guard": {"document_id": "doc-1", "request_id": "<a fresh UUID>"}, "layer_id": "<your layer>",
 "brush": {"preset_id": "b) Basic-2 Opacity.kpp", "size_px": 6, "opacity": 1, "flow": 1,
           "color": {"space": "srgb", "rgba": [0.4, 0.3, 0.3, 1]}, "eraser": false},
 "points": [{"x": 20.5, "y": 24.5}, {"x": 32.5, "y": 30.5}, {"x": 44.5, "y": 26.5}],
 "smooth": "catmull_rom"}
```

`size_px` is 1 to 1000, `opacity` and `flow` 0 to 1, and the colour sRGB 0 to 1 with alpha 1,
not 0–255: a sample's `color` as it comes. `eraser` takes only `false`, `smooth` `none` or
`catmull_rom`, and `antialias`, if given, only `true`. `preset_id` and `preset_sha256` come from
`krita_resource_list`, and a pixel-engine preset's receipt says what Krita applied. A stroke is checked over its reach by default. A preset on another brush
engine, or a filter, mask, style or clone that could spread a change, needs `verify: "full"`, which
checks the whole canvas. A path may run half a brush past the canvas: `changed_bounds_px` is what
changed on the canvas, and `layer_bounds_px` is the layer's whole extent, past it included.

**Taper a stroke with `dynamics`.** A stroke can narrow, swell or fade along its length.

```json
"dynamics": {"size": [{"at": 0, "value": 0.1}, {"at": 0.5, "value": 1}, {"at": 1, "value": 0.1}]}
```

- **Knots.** `size` and `opacity` each take 2 to 16 knots. `at` is the fraction of the stroke's
  length, from 0 to 1, rising by at least 0.001. `value` multiplies `brush.size_px` or
  `brush.opacity` at that point. Values run in straight lines between knots, so add knots for a
  softer curve.
- **How Krita does it.** Krita's own Distance sensor drives the taper. For that one stroke it
  replaces the preset's own size or opacity sensors, and the receipt's
  `effective_brush.dynamics.replaced` names them.
- **What it needs:**
  - the pixel brush engine;
  - `brush.preset_sha256` from `krita_resource_list`;
  - a colour, not mask paint;
  - a stroke at least 1 px long.
- **What it is not.** It is not per-point pressure: every dab still paints at pressure 1, and
  `stroke.per_point_input` stays false. It is one native stroke and one undo step, never joined
  segments.
- **The preset is edited for that stroke and put back,** and the put-back is checked by its hash
  and by Krita's own dirty flag.
  - Unsaved tweaks you made to the preset in Krita survive.
  - If Krita cannot put the preset back, the stroke is undone and reported `uncertain`. Reload the
    preset in Krita's brush editor before painting with it again.
  - Krita's "save tweaks to presets temporarily" setting must stay at its default.

**Fill a flat colour plane in one call.** For a broad plane inside a shape, a fill beats a large
stroke under a selection: it is Krita's own fill, flat and antialiased, with no brush texture, and
no stroke's reach past the edge. Keep strokes for edges, texture and anything that should look
painted.

```json
{"guard": {"document_id": "doc-1", "request_id": "<a fresh UUID>"}, "layer_id": "<your layer>",
 "shape": {"type": "path", "points": [[20, 20], [50, 26], [40, 46], [18, 40]]},
 "color": {"space": "srgb", "rgba": [0.4, 0.3, 0.3, 1]}, "opacity": 1}
```

`shape` is a `rect` or `ellipse` (whole pixels), a `polygon`, a `path` (a smooth closed curve
through 3 to 4096 points, which bulges past them between points), or `{"type": "selection"}`, the
selection's part on the canvas. A shape must lie on the canvas, curve included; where it crosses
itself it fills even-odd. `blend_mode` and `alpha_lock` work as a stroke's, and the current
selection confines a fill and feathers it. Each fill makes `c) Pencil-3 Large 4B` your current
brush preset, so it does not depend on the brush you left; it needs that stock preset as Krita
ships it. A fill is checked over its shape plus 2 px, or the whole canvas with `verify: "full"`, and
as with a selection, keep an antialiased shape a pixel inside the allowed mask.

**7. Check it at game size.** After every one to three strokes, call `krita_preview_render` with
explicit recipes. A source's `baseline_id` shows the document as opened beside it.

```json
{"recipes": [{"id": "game-2.95", "target_pixels_per_unit": 2.95}], "filter": "lanczos",
 "sources": [{"document_id": "doc-1", "frame": 0, "target": "composite",
              "baseline_id": "<from the open>"}],
 "overlays": [], "backgrounds": [{"space": "srgb", "rgba": [0.19, 0.42, 0.55, 1]}],
 "export_pixels_per_unit": 4, "master_to_export_scale": 0.5}
```

**8. Undo or keep.** `krita_history_step` undoes or redoes the bridge's own steps, up to 50 a call,
never below the last protection change. Layer and mask creation, duplicates, reorders and
removals, selection commits, blend changes, strokes and fills, on layers and masks, undo; other
property changes cannot. A reorder's steps move together: a count that would split one is refused
with the count to ask for, in `details.steps_needed`. A step you make in Krita can carry the same
name as one of the bridge's, as Layer > Transform's do. When an undo or redo moved such a step of
yours and put it back, history stops there as not the bridge's (`INVALID_ARGUMENT`), with no retry
offered, since a retry would move yours again.

**9. Save to a new path.** The file is written beside the path, reopened in Krita, compared, and only
then moved into place. It never overwrites.

If that last move fails, the save answers `uncertain`, since its file was written. One exception:
when the move's own cleanup removed the file and confirmed it, the answer is `not_applied`. When
Krita refused the move at its start, a dialog open or another server holding the document, the
message says so: close the dialog, then retry with the same `request_id`, and the save finishes.

```json
{"guard": {"document_id": "doc-1", "request_id": "<a fresh UUID>"},
 "path": "/art/revisions/hero-r02.kra", "overwrite": false, "verify_reopen": true}
```

An `.ora` drops masks and adjustment layers, and lists what it lost in `expected_losses`; a visible
loss fails the save. Prefer `.kra`.

The receipt says where the file went (`path`) and where the live document still points
(`document_path`, its working copy). It also gives two flags: `dirty`, changes the bridge made since
the last verified save, and `krita_modified`, Krita's own flag, which list and inspect show too. A
save writes a copy, so Krita keeps the document marked modified and still asks to save it on a close.
Krita's own Save writes the working copy, never the saved file. On a PNG working copy it opens the
PNG export dialog, and its warning that the image will lose information means the layers are
flattened. A branch is opened from its own file, so Krita's Save on a branch writes that file, and
its baseline is then gone.

**10. Close.** `dirty_policy: "refuse"` fails with `DOCUMENT_DIRTY` while the bridge or Krita holds a
change since the last verified save. A change made by hand counts when it changes the layers, any
layer's or mask's pixels, or the composite. A hand change to guides, and perhaps to the global
selection alone, is not seen. After a verified save with nothing changed since, it closes, though
Krita still marks the document modified. `"discard"` drops everything.

## Retries and long calls

- **Give every `request_id` a fresh UUID.** Reuse one only to retry the same call: the retry returns
  the original receipt and never runs twice.
- **Retry only when `retryable` is true.** Otherwise act on the message.
- **Every failed change says whether it applied,** in `details.outcome`:

  | `outcome` | What it means | What to do |
  |---|---|---|
  | `applied` | The change is in the document. Only what the server does after it failed | Never retry. Inspect, then go on |
  | `not_applied` | Proven: the call never went out, it stopped before its first change, or its rollback or cleanup was verified | Fix the call, or retry if `retryable` |
  | `uncertain` | Nothing proves it either way | Inspect the document first. It is never sent to another Krita session |
  | `unregistered` | The bridge has no record of the call, which most likely never arrived | Retry with the same `request_id`. It is never sent to another Krita session |

  `rolled_back`, `rollback_verified` and the receipt's own `verification` are separate facts beside
  it. A rolled-back change also says `history_sealed`: true when undo can no longer reach below it,
  because Krita may hold a step the bridge cannot name.
- **`status: running` means Krita was still busy** when the server's 45-second wait ran out. Call
  `krita_operation_get` with its `operation_id`; never repeat the call.
- **`krita_operation_get` says what became of a call:** `outcome` is as above and null while the call
  is queued or running. A receipt that breaks its tool's contract still comes back, as plain data,
  with `receipt_valid: false` and `receipt_problem` naming the rule. After a Krita restart it answers
  from the journal, if the call's end was recorded, and otherwise `uncertain`.
- **A save is finished only by the server process that made the call.** Polled from another one,
  for instance after your MCP client restarted its server, `krita_operation_get` reads the save
  without finishing it. It answers `uncertain`, with a message saying that retrying
  `krita_document_save` with the same `request_id` finishes it.
- **`krita_operation_cancel` stops only a queued call.** A running Krita call cannot be interrupted.
- **A retry of an `applied` or `uncertain` failure paints nothing new.** The first returns the same
  failure from the journal, with its ids. The second goes to the same Krita session, which answers
  with what it already holds.

## Every error code

Every failure returns `error: {code, message, retryable, details}`. The table gives the usual
`retryable`; the field in the answer is what counts. A failed change also has `details.outcome` (see
*Retries and long calls*).

| Code | Retryable | What it means | What to do |
|---|---|---|---|
| `INVALID_ARGUMENT` | no | The arguments break the schema or a rule, or hold a number that is not finite (NaN, Infinity, or one past a double's range). Also an undo past the last protection change, a redo of a rolled-back stroke, or a preset that does not exist (with the 5 nearest names) | Fix the call. A schema error names every problem, in the message and in `details.errors` |
| `UNSUPPORTED_CAPABILITY` | no | Not in this build or phase, the plugin cannot bound the change's reach, cumulative undo is on, or a save of a document not in sRGB | If `details` names a reach reason, use `verify: "full"`. Otherwise do without it |
| `KRITA_NOT_RUNNING` | no | No live bridge | Follow the step in the message, or run `doctor` |
| `PROTOCOL_MISMATCH` | no | The server and the plugin are different versions | Run `install-plugin` and restart Krita. If the plugin is the newer, restart the MCP client |
| `KRITA_MODAL_DIALOG` | yes | A dialog is open in Krita | Ask the owner to close it, then retry |
| `MULTIPLE_WINDOWS` | yes | Krita has more than one main window | Ask the owner to close the extra one, then retry |
| `BUSY` | yes | An autosave holds the document during a save | Retry shortly; nothing was written |
| `TIMEOUT` | no | Reserved. Nothing produces it in Phase 1 | A long call returns `running` instead |
| `CANCELLED` | yes | A queued call was cancelled, or Krita quit first; it never ran | Send it again if you still want it |
| `REQUEST_ID_CONFLICT` | no | That `request_id` was used with other arguments | Use a fresh UUID |
| `DOCUMENT_NOT_FOUND` | no | The document was closed, or Krita restarted | List the documents, and reopen if you need it |
| `LAYER_NOT_FOUND` | no | No layer has that id here | Inspect. A reopened ORA or PNG has new ids; match by name |
| `LOCKED_TARGET` | no | The layer is protected, or holds or is a protected layer; or a mask's layer, or a group above it, is protected | Add a layer of your own, or duplicate a protected one and work on the copy |
| `LAYER_NOT_PAINTABLE` | no | The target is not a paint layer, or Krita refuses paint on it | Paint on a paint layer of your own |
| `LAYER_HAS_LOCAL_SELECTION` | no | The layer has a local selection mask, which would confine the stroke or fill | Paint on another layer |
| `PROTECTED_REGION_CHANGED` | no | The change reached protected pixels, and was undone and confirmed | Read `details.verification` and the diff image, then confine the stroke with a selection |
| `OUTSIDE_ALLOWED_MASK` | no | The stroke or fill lies entirely outside the allowed mask; nothing was painted | Move it |
| `RESOURCE_HASH_MISMATCH` | no | A preset or mask differs from the hash given | List it again, and do not edit presets during a session |
| `SOURCE_HASH_MISMATCH` | no | The source, the working copy or a branch's file differs from the hash given or kept | Hash the file again, or find what changed it |
| `COLOR_PROFILE_MISMATCH` | no | The document is not 8-bit RGBA, or this needs sRGB | Work on another document; Phase 1 does not convert |
| `DOCUMENT_DIRTY` | no | A close with `refuse` while the bridge or Krita holds a change no verified save holds; `details` names `dirty` and `krita_modified` | Save, or close with `discard` |
| `DOCUMENT_UNSAFE` | no | A rollback could not be confirmed | Close it, and reopen from your last verified save |
| `DOCUMENT_READ_ONLY` | no | The owner opened it by hand, or it opened `read_only` | Open a working copy |
| `DOCUMENT_IN_USE` | no | Another live server process holds the document | Work on your own working copy |
| `SAVE_VERIFY_FAILED` | no | The reopened file differs; `details` lists up to 20 mismatches, and the file was removed | Fix the cause. For ORA, save `.kra` instead |
| `PATH_NOT_ALLOWED` | no | The path is outside every allowed root | Use a path inside `allowed_roots` |
| `FILE_EXISTS` | no | The target exists; nothing overwrites | Pick a new path |
| `IO_ERROR` | no | A disk or format error | Read the message. Retry only if `retryable` is true |
| `ROLLBACK_FAILED` | no | A change leaked and the undo could not be confirmed; the document is now unsafe | As `DOCUMENT_UNSAFE` |
| `INTERNAL_ERROR` | no | Something unexpected. Read `details.outcome`: `applied` is done, however the answer reads; `uncertain` was sent and its fate is unknown; `unregistered` never reached the bridge and is retryable | Inspect first after `applied` or `uncertain`. Otherwise see `logs/plugin.log` |

## Phase 1's limits

**Size and format.**
- **A save takes documents of up to 8192² pixels,** that is 8192 × 8192 or any shape of the same area.
  A larger one can be opened, painted in region scope and previewed in crops, but never saved, and
  `verify: "full"` is refused on it. A baseline preview is refused once the canvas and the crop pass
  2 × 8192² pixels. Work on a smaller document if you need to keep the result.
- Documents open as RGBA 8-bit. Painting and saving need sRGB.
- Saves write KRA or ORA, never PNG. A saved file carries a `mergedimage.png`, and `krita_capture` at
  `scale: 1` gives a native PNG of any region.
- A capture's image is at most 4096 px on its long edge, from at most 8192² pixels read: tile for
  more. Layer captures and samples read paint layers only, not groups; a transparency mask is
  captured with `target: "mask"`, and samples read no mask. A native capture (`scale: 1`), a
  selection's and a mask's take no `background` or `greyscale`.

**Painting.**
- **No per-point pressure, tilt or timing.** Every point paints at pressure 1, and such input is
  refused unless `input_fallback` is `flat`. Scripted strokes hold speed sensors constant, so of six
  stock presets tried, only `j) WaterC Basic Round-Grunge` tapers by itself, and only as it starts.
  For a taper, give the stroke `dynamics`: size and opacity along its length, on the pixel brush
  engine. It is not available on mask paint, and not while Krita's "save tweaks to presets
  temporarily" setting is changed.
- **The colour's alpha must be 1.** Transparency comes from the brush's `opacity` and `flow`.
- **No erasing.** `eraser` takes only `false`.
- **No stroke under half a pixel.** Krita paints no dab for one. For a single dab, send two points
  half a pixel apart.
- **Region verification needs the pixel brush engine.** Color Smudge, the Quick Brush, MyPaint, spray,
  deform and others need `verify: "full"`.
- Stochastic presets do not repeat exactly.
- No filters, or flood fills from a seed. Translate moves by whole pixels only; scale, rotate and
  shear take paint layers and groups of them, with no masks, and pivot on the bounds' centre. A mask moves and is copied only with its layer, and a clone layer's source is neither moved
  nor removed.
- **A fill is one flat colour.** No gradients or patterns, and no fill of a shape past the canvas.
- **Masks are transparency masks on paint layers.** No masks on groups, no filter or selection
  masks made by a tool, a transform mask only as a translate's, and a mask takes only `name` and `visible` from
  `krita_layer_update`.

**Documents and history.**
- Frame 0 only. An animated document away from it is refused, and verification refuses animated
  documents.
- Protection only tightens. To edit a protected layer, save, then reopen with it editable.
- One writer per document: each agent works on its own working copy.
- `krita_history_step` goes up to 50 steps a call. A property change other than blend mode has no undo
  step.
- A retry is safe within a Krita session however old, and across a Krita restart for 7 days.

**Krita is shared.**
- The brush is window-wide: painting changes your current brush and foreground colour, and Krita
  records the presets used in its own history; a fill activates `c) Pencil-3 Large 4B`. Mirror painting
  and wrap-around go off for a stroke or a fill and come back after it.
- A stroke, an undo or a redo brings that document's tab to the front for its length, then puts yours
  back.
- Do not edit brush presets while an agent paints, or paint in the same document.
- A dialog open in Krita refuses calls that read or change a document until it closes.
- While a call changes a document, Krita shows a short floating message on that document's view, if
  it is the one in front.

**It cannot judge.** The checks prove what changed and where. Whether a stroke looks painted is for
you to say.

## Who can drive the bridge

The bridge listens on `127.0.0.1` only, and needs a token made at every Krita start, kept in
`bridge.json`, readable only by you. That keeps out other users and web pages.

It is not a wall against your own programs. Any process running as you can read `bridge.json` and call
every bridge op, the harness ops the plugin ships for its test suite among them. Those work only on
documents in the harness folder, but one sets the window's brush. Such a process could already change
your files directly, and the token is not meant to stop it.

No tool takes a URL or runs code, and nothing leaves your machine except what your MCP client sends
its own model: captures and previews reach that client as images.

## What it leaves on your computer

| Where | What | How long |
|---|---|---|
| `~/Library/Application Support/krita-art-mcp/` | The data folder, private to you | Until you delete it |
| … `config.json` | Your allowed roots | Permanent |
| … `bridge.json` | The bridge's port and token | Until Krita quits; a crash leaves it for the next start |
| … `logs/plugin.log` | Bridge events and tracebacks, never the token | Rotated at 5 MB, one backup |
| … `transfer/` | Raw pixels in transit | Milliseconds; an hour at most; swept at bridge start |
| … `captures/<day>/` | Captures, previews and diffs | 7 days |
| … `baselines/` | Documents as opened, for previews | Until the document closes |
| … `journal/` and `journal/args/` | Every journaled call with its arguments | Permanent; nothing sweeps it. About 44 MB of lines in a heavy week |
| … `harness/` | The probe's own files | A run |
| Your roots | Working copies, named `<UTC stamp>-<name>`, your saves, and your branches, each opened from its own file | Yours |
| Beside a save | A hidden `.<name>.<token>.saving.kra`, for the length of the save | A new save or a close removes one left unfinished; a Krita crash can leave one |
| `~/Library/Application Support/Krita/pykrita/` | The plugin | Until the next install |
| `~/Library/Preferences/kritarc` | The enable flag you set. Krita itself records the last preset and preset history | Krita's |

`KRITA_ART_MCP_DATA_DIR` moves `captures/`, `baselines/` and `journal/` elsewhere. The rest stays,
because Krita started from the Dock never sees the variable.

## `doctor` and troubleshooting

`uv run krita-art-mcp doctor` checks six steps in order and stops at the first that fails. If the
bridge answers, it then prints how many documents are open and unsaved, whichever step failed, so you
know whether Krita is safe to restart. A working copy an agent saved still counts as unsaved until it
is closed, because Krita keeps it marked modified.

| Step | If it fails |
|---|---|
| 1. The plugin files are installed and current | Run `install-plugin`, then restart Krita |
| 2. `kritarc` enables the plugin | Enable *Krita Art MCP Bridge* in the Python Plugin Manager, then restart Krita |
| 3. Krita is running | Start Krita |
| 4. The bridge is reachable | Follow its message; restart Krita |
| 5. The protocol and plugin hash match | Run `install-plugin`, then restart Krita |
| 6. At least one root is allowed | Run `roots add <folder>` |

**An agent lists no tools, or the handshake closes.** Check the absolute paths in the registration,
then the macOS folder access above.

**Every tool answers `PROTOCOL_MISMATCH`.** The server and the plugin are different versions. The
message names both. Finish the update: `install-plugin`, restart Krita, restart the client.

**Calls fail with `KRITA_MODAL_DIALOG`.** Close the dialog in Krita. Reading a list still answers
while one is open.

**A document is `unsafe`.** A rollback could not be confirmed, so nothing vouches for its state. Your
source and your last verified save are untouched. Close it and reopen.

**Krita feels heavy.** Its memory grows across large opens and saves, and a restart resets it.
