# Changelog

All notable changes to krita-art-mcp are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
`major.minor.fix`.

## [Unreleased]

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
