# Changelog

All notable changes to krita-art-mcp are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
`major.minor.fix`.

## [Unreleased]

## [0.30.0] — 2026-11-13

Round 2 is complete and documented: recovery that tells the truth about every failed change, flat
fills, transparency masks, tapered strokes, layer and document construction, and Krita's own
transforms. This release changes no behaviour; it corrects what the documents and one schema
example say. It still needs `install-plugin`, a Krita restart and a restart of the MCP client,
because the plugin carries the version.

### Changed

- **The user guide says what the build does, not which phase it belongs to.** It opens with what
  you can do with it, and its limits are under *What it cannot do*: the tools have grown past the
  phase the guide was first written for.
- **The README lists what the tools do now.** Fills, transparency masks, layer construction,
  transforms and document branches were missing from it, and it named an older version.
- **`krita_server_info`'s example tells the truth.** It showed fills, masks, native strokes,
  smoothing and the enforced selection as not built, and a 0.2.0 server; it now carries the
  capability matrix this release ships.

### Fixed

- **Every version in this file links to the commit that released it again.** The links stopped at
  0.16.0, so none of round 2's releases could be reached from its entry.
- **A taper's `value` range is in the guide.** It is 0 to 1, so a taper thins or fades the brush
  you give it and never swells past it; the guide now says so, and how to taper up instead.

## [0.29.0] — 2026-11-13

The fixes the construction review found. The four layer tools, `krita_layer_update` and the paint
tools judged a change against a tree read before Krita was idle, so a change landing as a call
began could have a protected layer removed, a correct undo reversed, or a leak verified clean. The
frame now proves the tree as the last act before every change and refuses retryably when anything
moved. `api_version` stays 0.4.0: nothing was renamed or removed. This release needs
`install-plugin`, a Krita restart and a restart of the MCP client.

### Fixed

- **A change landing as a call begins is refused for a retry, never judged.** Every mutating op
  passes the tree it refused and scoped from to the frame, which reads it again after the
  selection and immediately before the change; a watched field or a scoped layer's bounds that
  moved gives `INTERNAL_ERROR`, retryable, with nothing changed. `krita_layer_transform` already
  did this for itself; the stroke, the fill, `krita_layer_create`, `krita_layer_duplicate`,
  `krita_layer_reorder`, `krita_layer_remove` and `krita_layer_update` now do too.
- **A failure's `details.operation_id` is the call's own.** A save's or a duplicate's step kept
  its own id there, which `krita_operation_get` answers for no tool; the step's is now
  `step_operation_id`.
- **A failed `krita_layer_duplicate` names its copy** as `copy_id`, which the frame no longer
  overwrites with the source's id.
- **A `request_id` ending in `:finish` or `:open` is refused.** The server sends a save's and a
  duplicate's second step under an id derived that way, so an agent's own could collide with it.
- **A duplicate's open that was lost mid-call** is no longer told a retry may send it for the
  first time; only a call the bridge never registered was unsent.
- **A first translate is refused** when Krita's undo limit cannot take its two steps back at once
  (`too_many_steps`), as a reorder already was.
- **A taper refused before it painted no longer seals history**, since Krita holds no step; and an
  interrupt inside its restore now holds the preset, which no later stroke uses until it reads as
  before.
- **An undo Krita did not take stays retryable** even for a step with no name: Krita keeps Redo
  enabled as "Redo " with nothing to redo, which read as a step of the expected name.
- **A `no_change` scale, rotate or shear says the step stays.** Krita keeps its undo step and the
  offset it moved, so the receipt carries `krita_kept_step` and the document stays dirty instead
  of reading as unchanged.
- **The translate's parse refuses params carrying attributes** on `<transform_params>` or
  `<free_transform>`, which it read as a plain move.
- **A whole number sent as a float** (`1.0`) is refused by the server, as the plugin already
  refused it, and `layer_id` and `above_id` take Krita's own id form in the schemas.

### Added

- Parity cases for the taper's schema rules, a translate's and a scale's bounds and item types, a
  layer id's form and the whole-number rule; the plugin's bounds for a translate, a transform, a
  taper's knots and a layer's name are held to the schemas.
- Probe checks for the capability matrix's `layer.translate`, `layer.scale`, `layer.rotate` and
  `layer.shear`; a visible translated layer reordered and removed, each undone (K53's ground); and
  a half turn that changes no pixel, which Krita keeps.
- `Node.remove()`, `Node.duplicate()` and `addChildNode` are pinned to their listed sites, and the
  adapter's wait rule now covers a node's geometry, so `tree` and `structure` wait.

## [0.28.0] — 2026-11-12

A paint layer, or a group of them, can be scaled, rotated or sheared. Krita's own Layer > Transform
resamples it about the centre of its bounds in one undo step, and the bridge checks the whole canvas
against protection and undoes a leak. `api_version` stays 0.4.0: operations, fields and a
capability were added, and nothing was renamed or removed. This release needs `install-plugin`, a
Krita restart and a restart of the MCP client.

### Added

- **`krita_layer_transform` scales, rotates and shears.**
  - `{type: "scale", size_px: [w, h], filter}` makes the layer's bounds w × h px, with one of
    Krita's eight filters, Bicubic by default.
  - `{type: "rotate", degrees}` turns it clockwise for positive degrees, Bicubic.
  - `{type: "shear", degrees: [x, y]}` shears x, then y, Bilinear.
  - Each pivots on the bounds' centre (a group's shown layers'), takes every layer in a group with
    it, hidden ones too, and is one undo step that `krita_history_step` undoes and redoes.
  - The receipt gives `pivot_px`, `bounds_before_px`, `bounds_after_px` and the filter Krita used.
  - Resampling loses detail: copy the layer first to keep the original.
- **What it refuses:**
  - a protected layer or one holding one;
  - a layer holding a mask or a layer of another kind;
  - a transform mask on the layer or on a group holding it (scale, rotate or shear before you
    translate);
  - a locked, alpha-locked or styled layer, or a clone layer's source;
  - an empty layer, or a change of nothing (a scale to the layer's own size, or a shear too small to
    move an edge, which Krita would skip);
  - more than 50 layers, or reads past one for a layer or four for all of them;
  - Krita's cumulative undo, or a filter Krita lacks.
- **The capabilities `layer.scale`, `layer.rotate` and `layer.shear`**, true.

### Changed

- **`krita_history_step` stops for good at the owner's own step of the bridge's name.** Krita's
  steps can carry the bridge's names, Layer > Transform's among them. When a move reversed such a
  step, history now stops there as not the bridge's, rather than asking for a retry that would move
  it again. A step Krita did not take stays retryable.
- **The server instructions** say to copy a layer before `krita_layer_transform` alters it. 3,371
  characters.

## [0.27.0] — 2026-11-11

A layer or group can be moved by whole pixels. A transform mask on top of its masks holds the move,
so the layer's own pixels never change, and every step is Krita's own and undoes. `api_version`
stays 0.4.0: a tool and a field were added, and nothing was renamed or removed. This release needs
`install-plugin`, a Krita restart and a restart of the MCP client.

### Added

- **`krita_layer_transform`** with `operation: {type: "translate", by_px: [x, y]}` moves a paint
  layer or a group, pass-through or not, with all it holds. The first translate adds a transform
  mask and moves it, in two undo steps; a later one moves the same mask, in one; `undo_steps` says
  which and `krita_history_step` takes them back together. The whole canvas is checked against
  protection and a leak is undone. `translation_px` is the layer's whole move. Paint on a
  translated layer lands where it is aimed in the layer's own pixels and shows moved. A KRA keeps
  the move; an ORA drops it, so an ORA save of a translated layer is refused. It is refused for a
  protected layer, one holding one or one inside a protected group, a layer whose transform mask a
  translate did not make, and under Krita's cumulative undo.
- **`translation_px`** on every layer entry of `krita_document_inspect`, `krita_document_open` and
  `krita_document_duplicate`: a transform mask's whole-pixel move when a translate made it, else
  null.
- **The capability `layer.translate`**, true.

### Changed

- **`krita_layer_duplicate` refuses a layer holding a transform mask** (`UNSUPPORTED_CAPABILITY`,
  `reason: transform_mask`). Undoing such a copy crashes Krita, on 0.26.0 too: copy a layer before
  translating it.
- **The undo ledger sees a translate's move,** so history and every rollback tell a translate's
  unnamed steps from a selection's, and a KRA save compares it. A transform mask no translate made
  is left uncompared.
- **The server instructions** say to copy a layer before moving it. 3,375 characters.

## [0.26.0] — 2026-11-09

A whole document can be branched: saved to a new `.kra`, verified, and opened as a document of its
own, to try an alternative beside the original and compare the two. `api_version` stays 0.4.0: a
tool and fields were added, and nothing was renamed or removed. This release needs
`install-plugin`, a Krita restart and a restart of the MCP client.

### Added

- **`krita_document_duplicate`** saves a document to a new `.kra` path inside a root, verifies the
  file by reopening it as a save does, and opens it as a branch, named by `new_document_id`. The
  branch keeps every layer id, the protection, the allowed mask, both flags and the source's mode;
  its history starts empty and it has its own `baseline_id`. The source stays as it was, its dirty
  flag included, and the receipt says how it stands (`source_dirty`, `source_krita_modified`). It
  is not destructive: it writes a new file, never over one, and opens it. `.ora` is refused, since
  only KRA keeps the layer ids protection names.
- **A branch that was saved but did not open** answers `uncertain` with the file's `path`: a retry
  under the same `request_id` opens it when Krita refused the open at its start or the open never
  reached Krita, and `krita_document_open` opens it otherwise.

### Changed

- **`krita_operation_get`** polled from the process that made a duplicate that came back running
  places its file and opens the branch, as it finishes a save; any other process only reads.
- **A document's as-opened baseline is read against the file it was opened from,** its own hash
  kept apart from the accepted source's, so a branch reads its own.
- **The server instructions** say how to try a whole alternative. 3,322 characters.

## [0.25.0] — 2026-11-07

Layers can be copied, moved and removed. A copy is hidden, so you can try a change on it and
compare; moving layers into a group is how you group them. Every step is Krita's own and undoes.
`api_version` stays 0.4.0: tools and fields were added, and nothing was renamed or removed. This
release needs `install-plugin`, a Krita restart and a restart of the MCP client.

### Added

- **`krita_layer_duplicate`** copies a layer or group, every layer and mask inside it included, as
  a hidden layer directly above it, in one undo step. A protected layer may be copied; the copies
  are yours. The receipt gives `derived_from` and an `id_map` from each source node to its copy. It
  is not destructive: the composite cannot change.
- **`krita_layer_reorder`** moves a layer or group, with what it holds, under the root or into a
  group, directly above a sibling or on top. Krita takes a moved group apart, so the bridge removes
  it and adds back each node in turn: one undo step for the remove and one per node, stated in
  `undo_steps`. The whole canvas is checked against protection, and a leak is undone. A move of
  more steps than one history call or Krita's undo stack takes is refused as `too_many_nodes`.
- **`krita_layer_remove`** removes a layer or group with everything in it, or a transparency mask,
  in one undo step, checked against protection over its bounds or the whole canvas.
- **What the three refuse:** a protected layer or one holding one (`LOCKED_TARGET`), a mask on its
  own except a transparency mask's removal, a layer a clone layer shows (`UNSUPPORTED_CAPABILITY`,
  `reason: clone_source`, since Krita would turn the clone into a paint layer), a group moved into
  itself, and a document's last layer.

### Changed

- **`krita_history_step` moves an operation's steps together.** A count that would undo or redo
  part of a reorder is refused before anything moves, with `details.steps_needed`, and says so
  when the rest of it lies past what history can reach.
- **A layer's name is bounded at 256 characters by the plugin too,** for `krita_layer_create` as
  for `krita_layer_duplicate`; a refusal names `field: name`.
- **The server instructions** say how to try a change on a copy and how to group layers; the rule
  on `krita_layer_update`'s check lives in its description. 3,149 characters.
- **`undo.grouping`'s note** says a reorder's steps and how history treats them.

## [0.24.0] — 2026-11-06

A stroke can taper. `dynamics` sets size and opacity along the stroke's length, through Krita's
own Distance sensor, on the pixel brush engine. The preset is edited in memory for that one stroke
and put back, and the put-back is checked. `api_version` stays 0.4.0: fields and a capability were
added, and nothing was renamed or removed. This release needs `install-plugin`, a Krita restart and
a restart of the MCP client.

### Added

- **`dynamics` on `krita_paint_stroke`:**
  - `size` and `opacity` are each 2 to 16 knots `{at, value}`, where `at` is the fraction of the
    stroke's arc length from 0 to 1, and `value` multiplies `brush.size_px` or `brush.opacity`.
    Values run in straight lines between knots.
  - The taper replaces the preset's own size or opacity sensors for that one stroke, and lists
    them in the receipt.
  - It needs the pixel brush engine, `brush.preset_sha256`, colour paint and a stroke at least
    1 px long. Each refusal comes before anything changes.
- **`effective_brush.dynamics` in the receipt:** the arc length, the sensor length Krita took, the
  knots, and the sensors replaced.
- **The `stroke.dynamics` capability,** true since 0.24.0.
- **The preset is put back after every taper.** It is restored from its own XML, then reloaded
  from Krita's storage when it had no unsaved change before, so unsaved tweaks survive. The
  put-back is checked by digest and by Krita's dirty flag. If it fails, the stroke is undone and
  reported `uncertain`, and no stroke or fill paints with that preset until it reads as before or
  Krita reloads it.
- **Taper refusals:**
  - with Krita's "save tweaks to presets temporarily" setting changed from its default, which no
    taper has been measured under;
  - when no preset chooser says whether the preset has unsaved changes.
- **`harness.preset_dirty`** for the live harness.

### Changed

- **The server instructions** name the taper, at 3,104 characters.

## [0.23.0] — 2026-11-06

A save's answer now says what happened to its file, and a second server can no longer break a save
it polls. The frame's rollback reads the state before its first undo. The server's instructions
moved into the tools' own descriptions, leaving room for the round's later tools. `api_version`
stays 0.4.0: values and fields changed, and nothing was renamed or removed. This release needs
`install-plugin`, a Krita restart and a restart of the MCP client.

### Changed

- **The server instructions are 2,945 characters, from 3,908.** Each rule that belongs to one
  tool now lives in that tool's or field's description: inspect, capture, the stroke's and the
  update's `verify`, `inherit_alpha`, sample, history_step and open's `mode`. They now also name
  `unregistered`.
- **A save whose finish failed reads `uncertain`, not retryable,** unless the finish's own cleanup
  removed the file and confirmed it. It used to read `not_applied`, and retryable, while its hidden
  file stayed. When Krita refused the finish at its start, a dialog or another server's lease, the
  message says that retrying with the same `request_id` finishes the save.
- **`krita_operation_get` finishes a save only in the server process that made the call.** Any
  other poll reads the save as Krita holds it, `uncertain` until it is finished, and says how to
  finish it. Its hint stays read-only.
- **A rolled-back change reports `history_sealed`,** true when undo can no longer reach below it.
- **`selection.enforced`'s note** says mask paint keeps to the global selection alone.

### Fixed

- A finish refused at its start can run again: a retry of the save finishes it, where it used to
  get the same refusal back for the whole Krita session.
- A poll from a second server no longer takes a save's finish, which used to leave the save
  unfinished for good.
- A rollback no longer undoes a step Krita holds above the change's own, and one that fails seals
  history, so an unsafe document reports no undo left.
- A selection that raised past its marker, other than with its own refusal, marks the document
  unsafe, as every frame op does.
- Mask paint refuses `eraser`, which on Krita hides where the receipt would say reveal.
- A save whose export moved the document no longer reports its rollback verified.
- A protected mask's changed pixels are counted one byte a pixel.
- A retry that joined a running call settles with it when the call is refused and polled, so a
  later restart can still send it.
- A number that is not finite inside a union, such as a selection rect's `x`, is reported once.
- A fill's closed curve is tested for area over the same points on both sides.
- **The probe:**
  - its journal check now reads what it finds, with a floor on the lines it read;
  - three mask checks join it, a reveal stroke, a half-opacity stroke and an undone mask;
  - the mask hide stroke's check judges its own change.

## [0.22.0] — 2026-11-05

Soft edges and revised silhouettes no longer cost colour: a transparency mask hides or shows a
paint layer without changing its pixels, and strokes and fills paint the mask. `api_version`
stays 0.4.0: only fields and values were added. This release needs `install-plugin`, a Krita
restart and a restart of the MCP client.

### Added

- **Transparency masks from `krita_layer_create`:** `type: "transparency_mask"` on a paint layer,
  with `coverage` `all` (shows everything), `none` (hides everything) or `selection` (copies the
  current selection's coverage, a feathered or PNG one included), as one undo step. The new mask
  is checked against protection over the composite, like a stroke, and undone on a leak. The
  layer and every group holding it must be unprotected.
- **Mask paint:** `krita_paint_stroke`'s `brush.mask` and `krita_paint_fill`'s `mask` take
  `reveal` or `hide` in place of a colour. Each moves the mask's coverage by the opacity, so 0.5
  goes halfway, and a soft brush or a feathered selection softens it. Receipts give `mask`, with
  `color` null.
- **`krita_capture` `target: "mask"`:** a transparency mask's coverage alone, as a grey image.
- **`krita_layer_update` on masks:** a transparency mask takes `name` and `visible`, so it can be
  turned off and on, checked like any appearance change.
- **`mask.transparency` in the capability matrix,** supported since 0.22.0.

### Changed

- **`krita_layer_create` is now marked destructive** (`destructiveHint: true`). A mask with
  coverage `none` hides its whole layer, as `visible: false` would. Codex therefore reviews each
  create, unless the owner sets the server's approval mode.

## [0.21.0] — 2026-11-04

Broad colour planes no longer need oversized strokes under a selection: `krita_paint_fill` fills a
shape with one flat antialiased colour, checked like a stroke. This release needs
`install-plugin`, a Krita restart and a restart of the MCP client.

### Added

- **`krita_paint_fill`:** one flat antialiased fill of a rect, an ellipse, a polygon, a closed
  curve through points, or the current selection, on a paint layer, as one undo step. It takes a
  colour, an opacity, a blend mode and alpha lock. It is Krita's own fill, with no brush dabs, and
  it follows a feathered selection's coverage. It is checked against protection over the shape and
  a 2 px margin (`verify: "region"`) or the whole canvas (`"full"`), and undone on a leak. A
  shape past the canvas is refused, never clipped; a selection fill takes the selection's part on
  the canvas.
- **The fill activates the stock preset `c) Pencil-3 Large 4B` first, and says so.** Every preset
  fills the same visible pixels, but a wash-mode preset also writes colour under alpha 0 up to
  3 px past the shape. The preset becomes the window's current brush, as a stroke's does; a fill
  refuses with `UNSUPPORTED_CAPABILITY` when Krita lacks it or it no longer builds up without a
  masking brush.
- **`paint.fill` in the capability matrix,** supported since 0.21.0; `selection.enforced` now says
  fills keep to the selection too.

## [0.20.1] — 2026-11-04

Strokes, layer changes and new layers now share one verified sequence, so a failure that is rolled
back reads the same whichever of them it came from. This release needs `install-plugin`, a Krita
restart and a restart of the MCP client.

### Fixed

- **A layer Krita fails while adding is now undone and confirmed, as a failed stroke is.** The
  failure says `not_applied` once the document is shown to be as it was, and marks the document
  unsafe when it cannot be shown. Before, it read `uncertain`, and the document stayed open to
  changes.
- **Every rolled-back change reports the same fields:** `document_id`, `rolled_back` and
  `rollback_verified`, and, when the rollback fails, `cause` and what Krita's history showed.

## [0.20.0] — 2026-11-04

Limits an agent used to learn from a refusal are now visible before the call: a sample gives the
colour a stroke takes, `krita_server_info` reports the brush and page limits, and every field with
a range or unit states it in its description, which Codex shows. `api_version` is now 0.4.0. This
release needs `install-plugin`, a Krita restart and a restart of the MCP client.

### Added

- **`color` in each `krita_sample` sample:** the same colour in the 0–1 sRGB shape
  `krita_paint_stroke`'s `brush.color` takes, opaque, so it paints back unchanged. It is null where
  there is no colour or the profile is not sRGB.
- **Three limits in `krita_server_info`:** `brush_size_px` (1 to 1000), `resource_page_size` (100)
  and `stroke_overhang_size_fraction` (0.5, how far past the canvas a stroke's on-curve points may
  lie, as a share of its size).
- **Descriptions on every field with a range or a unit,** and examples of capture's two forms and of
  a sample sent as a stroke's colour, in the tool descriptions.

### Changed

- **A sample's `rgba` is now `rgba_255`,** named for its 0–255 range.
- **Every tool refuses a number that is not finite** (NaN, Infinity, or one past a double's range)
  with `INVALID_ARGUMENT`, naming each such field once as "not a finite number", beside any other
  problem.
- **A native capture, or a selection's, refuses `background` and `greyscale` in its schema,** so
  the error names the field.
- **The server's instructions are shorter,** leaving ranges and forms to the fields' descriptions.

### Removed

- **`krita_paint_stroke` no longer advertises values it always refused:** `smooth: basic` and
  `stabilizer`, `antialias: false`, and `eraser: true` (`eraser` stays required, as `false`). Each
  now answers `INVALID_ARGUMENT` instead of `UNSUPPORTED_CAPABILITY`.

## [0.19.0] — 2026-11-03

`krita_document_close` with `refuse` no longer closes over changes that only Krita holds, and the
tools now report Krita's own modified flag beside `dirty`. `api_version` is now 0.3.0. This release
needs `install-plugin`, a Krita restart and a restart of the MCP client.

### Added

- **`krita_modified` in `krita_document_list` and `krita_document_inspect`:** Krita's own modified
  flag, beside the bridge's `dirty`. A verified save clears `dirty` and leaves Krita's flag set,
  because it writes a copy and the document keeps pointing at its working copy.
- **The save's receipt gives `dirty`, `krita_modified` and `document_path`,** the file the live
  document still points at.

### Changed

- **`refuse` refuses any change Krita holds that no verified save holds,** a change made by hand
  included. After a verified save with nothing changed since, it still closes, because the close
  compares the document with what that save verified. Its error names both flags. This changes
  what `refuse` means, so `api_version` moves to 0.3.0.

### Fixed

- **The probe's leftover sweep counts Krita's flag,** so a document a dead run saved no longer
  stops it.

## [0.18.0] — 2026-11-03

Five tools that only add no longer say they are destructive, the journal records the server's own
time on each call, and captures and previews take the Hamming filter. This release needs
`install-plugin`, a Krita restart and a restart of the MCP client.

### Added

- **The `hamming` filter** for `krita_capture` and `krita_preview_render`.
- **`elapsed_ms` on each finished journal line:** the server's time on the call, from its arrival
  to its record, so a client's wall clock can be told from the tool's own time. It is null on a
  line written by a later `krita_operation_get` for a call that came back running.
- **The user guide explains Codex's approval setting for this server,** what it removes, and each
  tool's hints.

### Changed

- **`krita_layer_create`, `krita_protection_set`, `krita_document_open`, `krita_document_create` and
  `krita_document_save` set `destructiveHint: false`.** Each only adds: a layer, tighter protection,
  a working copy, a document or a new file. A client that asks before every destructive call stops
  asking for these. Strokes, selections and the other changes stay destructive, so most of a
  session's approvals remain.

## [0.17.0] — 2026-11-02

A stroke that applied can no longer come back as a failure with no ids, and every failed change now
says whether it applied. This release needs `install-plugin`, a Krita restart and a restart of the
MCP client.

### Added

- **`details.outcome` on every failed change:** `applied`, `not_applied`, `uncertain` or
  `unregistered`. `not_applied` is said only on proof, and `applied` is never retryable.
- **`layer_bounds_px` on a stroke's receipt.** It carries Krita's own extent, which can run past the
  canvas.
- **`outcome`, `receipt_valid` and `receipt_problem` on `krita_operation_get`.** A receipt that
  breaks its contract comes back as plain data, and the journal is settled either way.
- **`krita_operation_get` answers after a Krita restart,** from the journal, when the call's end was
  recorded.
- **The probe paints past every edge and corner,** with and without a selection, in both scopes. It
  also checks a stroke wholly off the canvas, old overhang, same-request replay, and a save and
  reopen after overhang, and that no call in its run was left uncertain.

### Fixed

- **A stroke past the top or left edge applied and then reported failure.** `changed_bounds_px` took
  Krita's unclipped layer bounds, which broke its own schema, so the receipt, its ids and the
  journal's record were lost. A layer that already held off-canvas paint failed the same way on
  every later full-scope stroke, wherever it landed.
- **Past the right or bottom edge, `changed_bounds_px` reported the layer's bounds** rather than what
  changed. It is now always inside the canvas and true.
- **A receipt that breaks its contract keeps the call's `document_id` and `operation_id`,** and a
  completed change says `applied`. The error no longer quotes the whole receipt.
- **Applied work is no longer reported as a plain failure.** A selection whose mask could not be made
  and a history step whose capture could not be made say `applied`, keep their ids and are never
  retryable. One of them used to say retry, though the undo step had already been pushed.
- **`BUSY` from a save now changes nothing.** An earlier unfinished save used to be dropped first. It
  now stays until a new save has verified.
- **A raise after a call went out keeps its identity,** and the journal still records it.
- **A failure reading a saved file no longer leaves its hidden file behind.**

### Changed

- **A refused open removes the working folder it made,** so a wrong hash leaves nothing.

## [0.16.0] — 2026-11-01

Phase 1 is complete and documented. This release needs `install-plugin`, a Krita restart and a
restart of the MCP client.

### Added

- **A user guide.** It covers setup, the core loop call by call, every error code and what to do
  about it, Phase 1's limits, who can drive the bridge, and what the tool leaves on your computer.
- **An architecture document.** It describes the system as built, the invariants and how each is
  enforced, the Krita facts the code rests on, and the baseline a change is measured against.
- **The probe checks that a selection grows, shrinks and feathers** to the bounds Krita gives each.
  It was the only live run of those calls, and until now only printed them.

### Changed

- **The README is short and says what is true.** Setup moved to the user guide. The requirements now
  say that Krita's interface must be in English, because undo and rollback confirm each step by its
  English name.
- **The probe prints only what no check would notice.** It reports 23 MEASURED lines, down from 47,
  and each one that stays has its reason in the architecture document.
- **The probe's journal measurement stopped crying wolf.** It takes the fastest of five reads, because
  one read could carry a garbage collection of the probe's own process and report that the journal
  bites when it does not.

### Fixed

- **The save's limit is stated as what it is.** It is a pixel count, 67 megapixels, not a side of
  8192, so a long narrow document saves. Agents are also told that a larger document can be painted
  only in region scope.

### Removed

- **Journal lines from before 0.9.0 are no longer read.** None can fall inside the 7-day window. A
  server that meets a line of another version refuses it with a clear error naming both cures.

## [0.15.0] — 2026-11-01

An agent's first calls now work in Codex, without learning the arguments from refusals. This release
needs `install-plugin`, a Krita restart and a restart of the MCP client.

### Fixed

- **Codex sees every tool's whole schema.** It reached `krita_capture`, `krita_sample` and
  `krita_document_open` as `args: unknown`, lost two fields of `krita_preview_render`, showed every
  fixed-length list as a list of strings, and lost every tool's result. Each rule now has a form
  Codex renders. Every tool accepts and refuses exactly what it did.
- **An argument error names every problem in one answer,** up to 50, with fields taking turns so one
  repeated mistake cannot hide another. `details` lists them, and `omitted` counts any beyond that.
- **A file opened in Krita lists under its file's name.** Krita leaves such a document's title
  empty, so `krita_document_list` showed an empty `name`.

## [0.14.0] — 2026-11-01

Phase 1 meets the contract's acceptance exercises, and the agent instructions are final. This
release needs `install-plugin`, a Krita restart and a restart of the MCP client.

### Added

- **Krita says when an agent is at work.** A call about to change a document shows a short
  floating message on that document's view. A refused call shows none, and a message never fails a
  call. It shows only while the document is the one in front.
- **The probe runs the contract's six acceptance exercises** on fictional sprite and icon
  fixtures: a selected repair at two zoom and pan settings; a detail that keeps the base, the
  exterior and every alpha byte; soft and scatter brushes beside a boundary; undo and retry of a
  batch; previews from explicit recipes; and a `.kra` saved, closed and reopened.
- **The probe checks N-04.** A run must leave nothing outside the data folder and Krita's own
  temp and autosave files. It lists those places before and after, so it sees what stays, not a
  file that came and went.
- **The probe gates strokes under a canvas-wide selection** at N-01's and N-09's budgets, and
  prints each stage's time.

### Changed

- **The agent instructions are final.** They now name the save's 8192 x 8192 bound, that erasing
  and a stroke under half a pixel are refused, when a preset needs `verify` full, and that an
  ellipse or polygon selection must sit a pixel inside the allowed mask, because its antialiased
  edge reaches past a mask drawn on the same line.

### Fixed

- **The probe sweeps its own leftovers.** A run that died with its documents unsaved used to stop
  the next run at the unsaved-documents check, before the sweep that would have closed them. It now
  closes them first, when they are the only unsaved documents in Krita.

## [0.13.0] — 2026-10-30

A stale plugin now says so, the calls an agent makes most got lighter, and a failed save leaves
nothing behind. This release needs `install-plugin`, a Krita restart and a restart of the MCP
client.

### Changed

- **The server refuses a plugin of another version.** Every tool answers `PROTOCOL_MISMATCH` and
  names both versions and the fix: `install-plugin` and a Krita restart, or a restart of the MCP
  client when the plugin is the newer. Before, a plugin one release behind answered each new tool
  with "Unknown op", which read as a bad call. `doctor` and `probe` still reach the plugin and
  judge it by its hash, so `doctor` can always report Krita's unsaved documents.
- **`krita_document_inspect` counts its selection in the plugin.** The selection no longer crosses
  to the server as a file on every inspect, up to 64 MB on an 8k master, to give two numbers. What
  inspect reports is unchanged.
- **Saves and closes no longer hash the source every time.** `baseline_untouched` compares the
  file's stat with the one taken at the open and hashes only when that moved, which costs about
  0.4 s per GB. A source rewritten in place is still reported, even with its modification time put
  back.
- **A stroke costs less.** It walks Krita's preset list once and serialises the preset three
  times, not four; a layer update reads the layer tree once per phase. Every check stays, except
  that the check just before painting compares the brush's fields, not its full settings.
- **The probe prints Krita's open documents beside its time,** since its document checks run about
  three times slower on a Krita holding 87 documents.

### Fixed

- **No hidden save file is left behind.** A save whose written file changed before the finish
  checked it, and one whose document was closed by hand during the finish, each left a hidden
  `.saving` file beside the target. Both now remove it and any folder the save made.

## [0.12.0] — 2026-10-28

Agents can now keep their work. A save is written by Krita's own exporter to a new file, and it
counts only once that file, reopened, matches the document.

### Added

- **`krita_document_save`.** Saves the document to a new `.kra` or `.ora` path inside an allowed
  root, never over an existing file.
  - Krita writes a hidden file beside the path. It is reopened in Krita and compared with the
    document: the size, profile and composite for both formats, and for a KRA every layer's id,
    fields and pixels, masks and the selection included. Its `mergedimage.png` is decoded without
    colour conversion and compared with the composite too. Only then is it put at the path; any
    difference is `SAVE_VERIFY_FAILED`, and nothing is left behind.
  - A KRA keeps everything. An ORA lists what it cannot keep in `expected_losses`: masks,
    adjustment layers, alpha lock, the type of clone, file and vector layers, and an opacity
    Krita's ORA writer brings back one step lower (127 of the 256 values, 50% among them). A loss
    never excuses a composite difference, so a visible layer whose opacity drifts fails the save.
  - A verified save clears the document's `dirty`, so `krita_document_close` with `refuse`
    succeeds; a change made while the save ran keeps it dirty. The document keeps pointing at its
    own file, and neither the working copy nor the source is written.
  - The receipt gives the path, the file's SHA-256, `reopened_verified`, `layers_preserved`,
    `baseline_untouched` (null for a document that was created, not opened),
    `composite_preserved` and `expected_losses`.
  - Before writing, the projection is recomposed and no selection mask is left active, so the
    file and its `mergedimage.png` show the layers, with no selection overlay.
  - `BUSY`, retryable, when an autosave holds the document. A save that runs past the server's
    wait is finished by `krita_operation_get`, which also gives a finished save's own receipt,
    failed or not, even once its file has moved.
  - Refused before anything is written: a canvas over 8192 × 8192 pixels
    (`UNSUPPORTED_CAPABILITY`), a file name too long for the save's hidden file beside it
    (`INVALID_ARGUMENT`), and a folder that cannot be written (`IO_ERROR`). A failed save removes
    any folder it made for its path.

### Fixed

- **A client that gave up on a long call could make Krita quit.** When a call ran past a
  client's wait, the bridge's later reply to the closed connection raised SIGPIPE, which Krita's
  embedded Python does not ignore, and Krita quit with no crash report, losing any unsaved work.
  The bridge's connections now let such a write fail quietly instead.

## [0.11.0] — 2026-10-28

Agents can now see their work at the size the game shows it, beside the document as it was
opened, instead of judging a capture scaled to fit.

### Added

- **`krita_preview_render`.** Comparison sheets at explicit review recipes, one sheet per recipe.
  - A recipe is world units (`target_pixels_per_unit`, scaled by each source's
    `export_pixels_per_unit` and `master_to_export_scale`, given on the source or as a default)
    or an exact box (`target_size_px`, which the image fits inside). `integer_zoom` enlarges the
    finished cell by whole pixels, adding no new values.
  - Each source is a document's composite or one paint layer, optionally cropped. A
    `baseline_id` puts the document as it was opened beside its current state. `anchor_px`
    lines siblings up.
  - Rows cover each review background (a colour, `checker` or `transparent`), each tint (a
    per-channel multiply and add over the whole cell), and greyscale (CIE L\*).
  - The `selection` and `allowed_mask` overlays are outlined in the sheet only. A clean sheet
    without them is written beside it, and nothing is drawn into the document.
  - Every cell is resampled once from Krita's native pixels with the given filter. The receipt
    gives each column's exact document-to-cell transform after rounding, its scale, filter and
    source, and each row's background and treatment.
  - Each sheet's `recipe_sha256` names everything that decides it beside its pixels: the recipe,
    filter, backgrounds, tints, greyscale and overlays, the unit defaults, and each source's crop,
    anchor and units.
  - Sheets are PNGs kept 7 days. Each one that fits is returned inline at full size, in recipe
    order; the rest are named by path, never shown scaled down.
  - Refused rather than shrunk or clipped: a sheet over 4096 px on its long edge, an image pushed
    out of its box by its anchor, a world-unit recipe without both units, a layer source with a
    baseline, and greyscale on a document that is not sRGB.

### Changed

- **Opening no longer writes the `as_opened` baseline.** The first preview that asks for it
  reads it from the working copy's file, which no save overwrites, so an 8192 × 8192 master
  opens in about half a second instead of five, with no 268 MB file. If that file has changed
  since the open, the preview answers `SOURCE_HASH_MISMATCH`; a kept baseline the server cannot
  read is dropped, and the next render reads it from the file again.

## [0.10.0] — 2026-10-27

The paint-safely tools now either confirm every change or mark the document unsafe, however the
call fails, and history's receipts say which.

### Fixed

- **An interrupt during `krita_layer_update`** (mid-change, or mid-rollback) marks the document
  unsafe and stops history below the change, as a stroke's already did. Before, the half-applied
  change was left unverified, and the document was not marked.
- **`krita_history_step` holds every step it moves.**
  - A step whose undo or redo raises in Krita marks the document unsafe and stops history.
  - When that happens after the first step, the receipt reports the steps that ran with
    `stopped: "document_unsafe"`. Its text says the document is unsafe and must be reopened.
  - A step that moved Krita and could neither be confirmed nor put back was reported as
    `stopped: "unconfirmed"`. It now says `"document_unsafe"`; `"unconfirmed"` is kept for a
    step Krita did not take, which leaves the document as it was.
- **A history step whose capture cannot be written** still returns its receipt, with `capture`
  and `content_sha256` null. Before, it failed, though its undos had run.
- **When Krita's settings name no undo limit,** history now offers Krita's own default of 200
  steps instead of assuming 30.

## [0.9.0] — 2026-10-25

Agents can now paint: one native Krita brush stroke per call, checked against protection inside
Krita in the same call, and undone by Krita's own undo if it reaches where protection forbids.

### Added

- **`krita_paint_stroke`.** One stroke with a Krita brush preset on a paint layer of the agent's
  own, as one undo step named "Scripted Brush Stroke".
  - The brush is set in full on every call: preset, size, opacity, flow, blend mode, alpha lock,
    rotation and colour. The receipt reports each as Krita then holds it, with the preset's
    engine, spacing and reach.
  - `smooth: "catmull_rom"` curves the path on the server; `none` paints straight segments.
  - Per-point pressure, tilt, rotation, tangential pressure, speed or timing is refused unless
    `input_fallback: "flat"`, which paints every point at pressure 1 (`input_applied: "flat"`).
  - Refused before anything is painted: a protected layer (`LOCKED_TARGET`); a group, a mask, or
    a layer Krita cannot paint (`LAYER_NOT_PAINTABLE`); a layer with a local selection mask
    (`LAYER_HAS_LOCAL_SELECTION`); a document that is not RGBA / U8 / sRGB
    (`COLOR_PROFILE_MISMATCH`); a point outside the canvas grown by half the brush; an unknown
    preset, with the nearest names; a preset whose settings changed since it was listed
    (`RESOURCE_HASH_MISMATCH`); a stroke wholly outside the allowed mask
    (`OUTSIDE_ALLOWED_MASK`); Krita's cumulative undo switched on; the eraser, the eraser with
    alpha lock, a stroke shorter than half a pixel (Krita paints no dab for it), `smooth` `basic`
    or `stabilizer`, `antialias: false`, and numbers that are not finite.
  - Mirror painting and wrap-around are switched off for the stroke and put back after it.
- **Verified strokes.** Each stroke is checked inside Krita in the same call:
  - over its reach R, the path's bounds grown by the brush's size and scatter (`verify:
    "region"`, the default), or over the whole canvas (`verify: "full"`);
  - no composite byte may change where the allowed mask is 0, no protected layer's pixels may
    change, and under `preserve_composite_alpha` no alpha value may change;
  - in region scope the preset's reach must be one the plugin can name (the pixel engine, a
    round, square or image tip, and its scatter), the layer may change only inside R, and a
    filter, mask, style, clone or copy blend that could spread the stroke is refused with
    `UNSUPPORTED_CAPABILITY`; `verify: "full"` paints them;
  - a stroke that breaks protection is undone by native undo and the undo confirmed byte for
    byte; the call fails with `PROTECTED_REGION_CHANGED`, its counts and an inline image of the
    offending pixels. An undo that cannot be confirmed is `ROLLBACK_FAILED` and marks the document
    unsafe. A rolled-back stroke is never redone.
  - A passing stroke reports the layer's changed bounds and keeps PNGs of R before and after.
  - A stroke that changes none of the layer's pixels cannot be told apart from another by
    history, so history stops at it; its receipt says so (`history_sealed: true`).
- **History tells strokes apart by their pixels.** `krita_history_step` undoes and redoes
  strokes, and stops at a stroke undone by hand or one it did not make.
- **`krita_server_info`** reports `stroke.native_brush`, `stroke.smoothing` and
  `selection.enforced` as supported since 0.9.0.
- **The server instructions** cover painting, and ask that the owner not edit brush presets
  while an agent paints.

### Changed

- **A preset's `sha256` in `krita_resource_list`** leaves out what every stroke sets (opacity,
  flow, blend, eraser, and the tip's size and rotation), so painting with a preset never changes
  the fingerprint the next stroke is checked against. A preset Krita fills in when the bridge
  first uses it in a session keeps the hash it was listed with.
- **The journal keeps each call's arguments in a file of its own** (`journal/args/`), so a server
  starting up reads only small lines. Journal lines are now version 2; version 1 lines are still
  read.

## [0.8.0] — 2026-10-25

Agents can now change a layer's properties, and every change that shows in the composite is
checked against protection and undone if it reaches where protection forbids.

### Added

- **`krita_layer_update`.** It sets a layer's name, visibility, opacity, blend mode, Krita lock,
  alpha lock, inherit-alpha, or makes it the active layer.
  - Protected layers, and groups that hold one, are refused with `LOCKED_TARGET`. Masks and the
    root are not layers it changes.
  - Opacity is Krita's 0–255, rounded half up; the receipt reports each value as Krita now holds
    it.
  - Only a blend change is an undo step; the receipt names the changes history can undo. The
    other properties cannot be undone.
  - Making a layer active and nothing else leaves the document unchanged for closing.
- **Verified appearance changes.** A change of visibility, opacity, blend mode or inherit-alpha
  is checked inside Krita in the same call:
  - The composite is compared before and after over the layer's bounds (`verify: "region"`, the
    default) or the whole canvas (`verify: "full"`). Nothing may change where the allowed mask is
    0, and under `preserve_composite_alpha` no alpha value may change.
  - A filter layer above the layer, a filter, transform or colorize mask, a layer style, a clone
    of the layer, or a copy or destination blend on it could carry the change past its bounds.
    Region checks are then refused with `UNSUPPORTED_CAPABILITY`, naming every such node, and
    `verify: "full"` works.
  - A change that breaks protection is undone, Krita's native undo for a blend change and the
    old values for the rest, and the undo is confirmed byte for byte. The call then fails with
    `PROTECTED_REGION_CHANGED`, its counts, and an image of the offending pixels, saved, and
    inline when it fits the message. A rolled-back blend change is never redone.
  - An undo that cannot be confirmed fails with `ROLLBACK_FAILED` and marks the document unsafe;
    later changes to it answer `DOCUMENT_UNSAFE` until it is reopened.
  - A passing change reports how many pixels changed and where, and keeps PNGs of the layer's
    region before and after (up to 2048 × 2048).
  - Animated documents are refused, since only frame 0 is checked.
- **`krita_history_step`** undoes and redoes blend changes, told apart from a blend change made
  by hand by the layers' blend modes.

### Changed

- **The server instructions** say which changes are undo steps, when to use `verify: "full"`,
  and how to recolour inside a silhouette: paint on a new `inherit_alpha` layer.

## [0.7.0] — 2026-10-24

Agents can now prepare a change: add a layer of their own, select where to work, tighten what is
protected, and undo or redo their own steps.

### Added

- **`krita_layer_create`.** It adds an empty paint or group layer under the root or a group:
  directly above a sibling, or on top when `above_id` is null. The new layer is the agent's to
  change, and Krita makes it the active one. A protected group may take a new layer. The call is
  one undo step.
- **`krita_selection_set`.** It sets the selection from a rect, an ellipse, a polygon, an 8-bit
  greyscale PNG inside an allowed root (checked by its SHA-256), a layer's alpha, everything, or
  nothing.
  - Rects, ellipses and polygons are antialiased at 4 × 4 samples per pixel.
  - The shape is grown, shrunk, feathered and inverted in that order, then combined with the
    current selection: replace, add, subtract or intersect.
  - A shape that leaves the canvas is refused, never clipped.
  - The receipt gives the selection's id, bounds, selected pixels and a PNG of its mask. The call
    is one undo step.
- **`krita_protection_set`.** It tightens protection and never loosens it.
  - It sets the whole set of protected layers, which must keep every layer protected now.
  - It sets the canvas mask outside which nothing may change, as a 0/255 PNG of the canvas's
    size, a rect or a polygon.
  - It turns on keeping the composite's alpha and the canvas size.
  - Undo never goes below the last protection change.
- **`krita_history_step`.** It undoes or redoes up to 50 of the steps the bridge made: layer
  creations and selection changes.
  - Each step is checked before and after, by Krita's Undo label and by the document's layers and
    selection. A step the bridge did not make, such as an edit by hand, stops history there.
  - Redo goes only as far as history undid.
- **`krita_document_inspect`** reports the allowed mask's bounds and size, and how many steps can
  be undone and redone.

### Changed

- **The server instructions** say to add a layer before painting, to allow several regions' union
  once and select each, and how far undo goes; the rest is shorter.
- **The bridge forgets a read ten minutes after answering it**, instead of keeping every read for
  as long as Krita runs. Calls that carry an agent's `request_id` are still kept for the whole
  Krita session.
- **A mask the server hands Krita** belongs to one request, so two calls with the same mask never
  share its file, and no call leaves its mask behind.
- **A document is marked as changed as soon as a change begins,** so a call that fails part-way
  still counts as a change when the document is closed with `refuse`.

### Fixed

- **Krita no longer crashes when a document closes straight after a selection change.** Krita's
  layer docker updated the changed node from a timer and crashed if the document had closed by
  then. Closing the document in front, or one changed in the last half second, now waits half a
  second for that update, so such a close takes about 0.5 s longer.

## [0.6.0] — 2026-10-24

Fixes from the architecture review after the first seven tools: lost calls end, cancelled calls
can be retried, Krita survives an interrupt, and a few files and folders are now private.

### Changed

- **A call that never reached Krita now ends after a few seconds,** instead of being reported
  `running` for ever, with every `krita_operation_get` on it waiting the full 45 seconds. It fails
  as retryable, with `outcome: "unregistered"`: retry it with the same `request_id`, which can
  never run it twice. A call queued behind a long Krita call is still waited for.
- **A cancelled call can be retried.** `CANCELLED` is now retryable: the call never ran, so a
  retry with its `request_id` runs it.
- **`krita-art-mcp roots add` refuses folders that reach too far:** `/`, your home folder, and
  krita-art-mcp's own data folders or any folder that holds one, each with the reason. Such a root
  already in `config.json` is refused too: opens fail until you remove it, and `doctor` names it
  in step 6.
- **`krita-art-mcp probe`** ends with its PASS, FAIL and MEASURED counts and how long it ran. Before
  cleaning up, it checks that it left no document open and no pixels in the transfer folder. It no
  longer opens a throwaway document to read Krita's Undo label, so outside its document checks it
  leaves your view alone. Files another program hands through the transfer folder meanwhile are
  not counted as its leftovers.

### Fixed

- **A result or error the plugin cannot send fails the call at once** with `INTERNAL_ERROR`,
  instead of leaving it running until the server's wait ran out.
- **An interrupt inside Krita's Python fails only the call it hit,** and the next calls still run.
  It no longer takes Krita down with your unsaved work.
- **Masks the server hands Krita are removed after an hour** if no call took them. A call whose
  mask is gone is retryable, and the retry sends it again.
- **Reading the selection waits for Krita to finish painting first.**
- **A retry still running is never marked settled** when an earlier, refused attempt of the same
  `request_id` is read late, so a Krita restart can never run it twice. A refusal that a retry
  shared with the call it joined still settles both.
- **The plugin's log and the probe's folder are private** (`0600` and `0700`), like the rest of
  the data folder, and the log stays private when it rotates.
- **The server's start-up cleanup of baselines takes its turn** with tool calls instead of
  reaching Krita beside them, and gives up after 2 seconds when Krita is busy.
- **The plugin's log survives being deleted while Krita runs:** the next rotation starts a fresh,
  private one.
- **Every folder the server makes in the data folder is private,** including ones an older
  version made with the default mode.

## [0.5.0] — 2026-10-24

Agents can now see pixels: capture any part of a document as an image, sample exact colours, and
list the brushes, blend modes, profiles and palettes Krita has.

### Added

- **`krita_capture`.** It returns a part of a document as an image, shown to the agent and saved
  as a PNG whose path comes with it.
  - It captures the composite, one paint layer's own pixels (without the layer's opacity, masks or
    inherit-alpha clip), or the selection as a grey mask.
  - At `scale: 1` it is the native crop, alpha included. Any other scale is resampled with the
    named filter onto a background: a checker by default, `transparent`, or a colour. It can also
    show values in greyscale.
  - `max_px` (1600 by default, 4096 at most) bounds the image's long edge, and one capture reads at
    most 8192 × 8192 pixels. Larger areas are captured in tiles; nothing is clamped.
  - The result gives the exact rect, the size, the filter, the colour profile, and the transform
    from document to image pixels.
  - An image too large to send whole is shown as a preview of at most 1600 px, made from the
    native pixels; the full image is at its path.
  - Captures are kept 7 days.
  - A document whose animation is showing a frame other than the first is refused, and its
    timeline is never moved; a still document reads wherever its timeline stands.
  - A capture never shows a selection mask's red overlay. For an agent's own document, its view is
    brought forward for the read and yours is put back. One of your own documents in that state
    is never changed: the read is refused until you select a layer.
- **`krita_sample`.** It reads the colour at given pixels, from the composite or one layer: RGBA
  0–255, hex, CIE L\*a\*b\* (D65) and L\*C\*h. A radius averages a disc, weighted by alpha, and
  adds the spread of its lightness and its pixel count. L\*a\*b\* is given for sRGB documents
  only.
- **`krita_resource_list`.** It lists brush presets, with each one's file name, engine and a
  fingerprint of its settings; the blend modes paint calls accept; and Krita's RGBA / 8-bit
  profiles and its palettes. Long lists come in pages.

### Changed

- **`krita_server_info`** reports `capture_source_pixels`, the largest area one capture reads.
- **`krita_operation_get`** shows the line and the image the call it follows would have shown.
- **A document's `source`** in `krita_capture`, `krita_sample` and `krita_preview_render` is
  `{document_id, frame}`; `revision` is refused until revisions exist.
- **The instructions for agents** cover capturing, sampling and the resource lists.
- **`krita-art-mcp probe`** also checks captures, samples and resource lists on documents of its
  own, and that a capture of a document behind, with a selection mask active, puts your view back.

## [0.4.0] — 2026-10-24

Agents can now open your accepted art safely: as a working copy in a folder you allow, with every
existing layer protected, and look inside it.

### Added

- **`krita-art-mcp roots add`, `list` and `remove`.** You name the folders agents may use. An
  agent can open no file, and make no working copy, outside them; a link or a `..` that leads out
  of them is refused with `PATH_NOT_ALLOWED`. The server and the plugin each check.
- **`krita_document_open`.** It opens a KRA, ORA or PNG in Krita's window.
  - `working_copy` copies the file into the `working_dir` you give, as
    `<UTC time>-<file name>`, and opens the copy; your file is never opened for writing. The
    working folder must lie inside a root, never in the source's own folder.
  - `read_only` opens the file itself, and every change to it is refused.
  - The file must match the `source_sha256` given, and so must the copy, or the open is refused
    with `SOURCE_HASH_MISMATCH`.
  - Every layer that exists at open is protected. An agent resuming its own earlier layers names
    them with `editable_layer_ids` (KRA, which keeps layer ids) or `editable_layer_names` (ORA and
    PNG, which do not). A name shared by several layers is refused.
  - Documents that are not RGBA / 8-bit are refused with `COLOR_PROFILE_MISMATCH`, and other
    formats with `UNSUPPORTED_CAPABILITY`.
  - The document as it opened is kept as a baseline for later previews, and removed when the
    document closes.
- **`krita_document_inspect`.** It reports a document's layer tree with every layer's type, order,
  visibility, opacity, blend mode, locks, inherit-alpha, offset, bounds, colour space and
  protection, plus the active layer, the selection's bounds and coverage, and the protection
  settings. It reads frame 0 only, and never changes which document or layer you are looking at.

### Changed

- **`krita_server_info`** lists the allowed roots.
- **`krita_document_close`** says whether the file a document came from is unchanged.
- **`krita-art-mcp doctor`** checks six steps; the sixth needs at least one root that is still a
  folder.
- **The instructions for agents** now cover opening with a working copy and a working folder, and
  why existing layers are protected.
- **`krita-art-mcp probe`** now also opens fictional ORA, KRA and PNG files of its own, written
  into its harness folder.

### Fixed

- **A file Krita opened but could not show is never stranded.** If giving it its view fails and
  Krita will not close it, it stays the agent's, marked unsafe, so a `discard` close ends it.
- **A source that cannot be read no longer leaks a file handle inside Krita.**
- **A full disk while pixels are handed to the server is `IO_ERROR`,** not an unexpected error.
- **The baseline is kept quickly,** so opening a large file no longer risks the client's timeout
  after the server's 45-second wait.
- **Pixels handed over but never collected are removed after an hour,** instead of waiting for
  Krita to restart.
- **`doctor`'s fix for a broken `config.json`** now says to fix or delete it, not to run
  `roots add`, which refuses to touch it.

## [0.3.0] — 2026-10-24

Agents can now make, list and close documents, and every change is safe to retry.

### Added

- **`krita_document_create`.** It makes a new transparent RGBA / 8-bit / sRGB canvas, opens it in
  Krita's window, and returns its id and its first paint layer. Other depths and colour profiles
  are refused with `UNSUPPORTED_CAPABILITY`.
- **`krita_document_list`.** It lists every open document with its id, name, path, size, colour
  space, whether an agent has changed it since its last save, and its mode. It never switches the
  document you are looking at. Documents you opened yourself are `read_only` to agents.
- **`krita_document_close`.** `refuse` will not close a document with unsaved agent changes;
  `discard` closes it anyway, without asking Krita to save. Documents you opened yourself are never
  closed by an agent.
- **`krita_operation_get` and `krita_operation_cancel`.** A call that comes back `running` can be
  followed to its final receipt. A call still waiting in the queue can be cancelled; one Krita is
  already running cannot.
- **Retries are safe.** Repeating a call with the same `request_id` returns the original receipt
  and never does the work twice, even through another agent's server. The same id with other
  arguments is refused with `REQUEST_ID_CONFLICT`. A call that Krita may or may not have finished
  before it quit is never sent again; it reports `outcome: "uncertain"`.
- **A journal of every change.** Each call that carries a `request_id` is written to
  `journal/YYYY-MM-DD.jsonl` in the data folder before it is sent, and again when it finishes.
- **One agent per document.** The server process that made a document holds it; another agent's
  changes to it are refused with `DOCUMENT_IN_USE` until that process has exited. Reading stays
  open to everyone.
- **Calls are refused at once while Krita has a dialog open or more than one window,** with
  `KRITA_MODAL_DIALOG` or `MULTIPLE_WINDOWS`. Both are retryable: close the dialog or the extra
  window, then retry.

### Changed

- **`guard` is `{document_id, request_id}`** in every tool. `expected_revision` arrives with
  revisions in a later phase.
- **The instructions for agents** now cover fresh request ids, one working copy per agent, and
  following a `running` call with `krita_operation_get`.
- **`krita-art-mcp probe`** now makes and closes its own documents, including 20 create and close
  cycles. It runs those checks only when none of your documents has unsaved changes.

## [0.2.0] — 2026-10-23

The server now reaches a running Krita through a plugin, and offers its first tool.

### Added

- **The Krita plugin, Krita Art MCP Bridge.** Inside Krita it answers only this Mac, and only
  with a secret that changes every time Krita starts. It runs each request on Krita's main thread,
  one at a time. It costs no measurable CPU while Krita is idle, and it stops cleanly when Krita
  quits.
- **`krita-art-mcp install-plugin`.** It copies the plugin into Krita and says what is left to
  do: restart Krita, enable the plugin, and restart again. Run it again, then restart Krita, to
  update.
- **`krita-art-mcp doctor`.** It checks the setup in order and names the first step that fails,
  with its fix. It also says how many documents are open in Krita and how many have unsaved
  changes.
- **`krita_server_info`, an agent's first call.** It reports Krita's version, the plugin's and
  server's versions, and the capability matrix: what this build can do. Nothing beyond this call
  is supported yet. When Krita is not ready, it names the missing setup step instead. When Krita
  stays busy past the server's 45-second wait, it reports `running` instead of failing.
- **Instructions for agents.** Every client receives short rules with the server:
  - call `krita_server_info` first;
  - how errors and long calls are reported.
- **`krita-art-mcp probe`.** A live check against your running Krita. It confirms that the
  installed plugin matches the server, then measures how fast the tool answers.

### Changed

- **Every result carries contract version 0.2.0.**
  - `revision` is always `null` until revisions arrive.
  - Error codes come from a fixed list.
  - A cancelled operation reports `status: cancelled`.

## [0.1.0] — 2026-10-23

The first release is the scaffold that the Phase 1 tools are built on.

### Added

- **`krita-art-mcp serve` starts the MCP server.** It speaks over stdio as `krita-art` and
  reports its version to the client; it offers no tools yet.
- **`krita-art-mcp --version`.** It prints the installed version.

[0.30.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/40c74913f515a8797e72dbaa1e3bfed4a2ae32ea
[0.29.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/fa949c0c14a81cb7b71e90f81e8292ed59077c16
[0.28.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/dd3569d7daec92cbf3ff559ee3c17d99e5417fc8
[0.27.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/ff567d74585aabf4165d9a18989b13805ce21b84
[0.26.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/ecad8041866c7be2b13bdf010101f80d2448441f
[0.25.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/214d844aec766320b16e7e7c733a69294a4378d7
[0.24.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/7f246cdb92f8728005c414f8b3ebf0acc15d7e2a
[0.23.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/93fc88369721081e577f58ebe8af91551818d7aa
[0.22.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/6e182147307f08f099f106890c9f1c6b3fe0c96a
[0.21.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/4a559271a339e74fb9e819f2a9cfba2aae631628
[0.20.1]: https://github.com/FairCat-GD/krita-art-mcp/commit/6455008884b2836846ca176da90647f052d299b3
[0.20.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/93760dfdb13fb022f478636c576f5c11f2a0ceb3
[0.19.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/cbbc8fcb48fe0502db1dbdbacec9219a3e4f38df
[0.18.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/a55cc4f0167700909c37bc0034800be26ff3d2bc
[0.17.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/c12b8f0b5e56e5906640842ab613a37256461de4
[0.16.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/04e9f6c5a91819ffa7452eef97fb53f400f8d207
[0.15.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/52113ab900602e3a85faa6fad2ddffadaca627a3
[0.14.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/9b6c6ccc10ae0fca01b5322850ed69f1cb9fa128
[0.13.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/61d3d861b8fa050329b66234052f6817a46a9701
[0.12.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/7d18a6a767f5ca3db9ff435b14aaafc5c84bd346
[0.11.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/0611f50b9f2a180e531c7152ab46dfa91eb777ab
[0.10.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/ffbad0e6e39d2bea0be68001183dcddcc2f9c971
[0.9.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/04a86abd869aae2deea4326f17acbaf159efef3b
[0.8.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/16ca9eaff39736ed752f9c03577cbe6fefdaaa3f
[0.7.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/d188986373e1e4975dcfc5d1412e862f12566b14
[0.6.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/b1c679e85ab9632372ea4114a8718e6a2a5328cc
[0.5.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/5ead34bc4e5624e92165b211d1daa2f66ed95fb1
[0.4.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/c081c59ff54e38b9a8799fa0a78955146745174c
[0.3.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/ef279d377f4aa515edb0ef36a69d60654f9744d1
[0.2.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/6e9237f4f728f237ec855f84855f2c6eba2d077d
[0.1.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/6588c86b268e321401b27af53842d58c759f6b13
