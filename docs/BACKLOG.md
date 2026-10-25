# Backlog

Work that has been named but belongs to no session. Each item needs its own intake before it runs
(a `docs/spec/FEATURE-*.md` with the request verbatim and the decisions resolved, then a block
in `docs/spec/SESSIONS.md`; see `docs/DEVELOPMENT-WORKFLOW.md`). When an item is picked up, it
moves out of this file.

The phases below are described in full in the PDD, Part 4. That is `docs/spec/PDD.md` while round 1
runs; after it closes, read it from git history at round 1's release commit.

## Deferred

- **Phase 2, Construct.** Left out at the round 1 intake. It covers:
  - project profiles (`krita_project_load`, profile schema 0.2.0, H9);
  - explicit, profile-gated non-brush operations: `transform_apply`, `filter_apply`,
    `color_convert`, `palette_manage`, `paint_shape`, `paint_fill`, `paint_path`, `paint_clone`
    and `canvas_resize`;
  - layer management: `layer_duplicate`, `layer_reorder`, `layer_remove`, `layer_import` and
    `mask_edit`;
  - `document_duplicate`, `reference_set`, `guides_set` and `view_set`;
  - preset tuning, templates and derived copies.

  The contract's acceptance exercise 5 (two profiles, no leakage) runs here. Still open is how
  `transform_apply` translates a layer: through a transform mask, or as a journaled reverse move
  (PDD Q13).
- **Phase 3, Integrity.** Left out at the round 1 intake. Revisions and stale-edit detection
  (`expected_revision`), checkpoints, edit transactions, `diff_measure`, recovery after a crash,
  `diagnostics_get`, and `krita-artifact://` resources. Interruption recovery for exercise 4 is
  here.
- **Phase 4, Delivery.** Left out at the round 1 intake. Registration, registered PNG export,
  validation through adapters, asset metadata, batch export, atlas packing, and engine packaging
  (Unity first). Also the preview overlays `anchor`, `collision` and `envelope`. Exercise 6's PNG
  export and project checker are here.
- **Phase 5, Asset modules.** Left out at the round 1 intake. Animation, tiles and terrain,
  backgrounds and scenes, UI, part sets, and text and vector.
- **Phase 6, Input-aware strokes.** Left out at the round 1 intake. The `paintPolylineStroke`
  branch of `krita_paint_stroke` on Krita 6.1 / 5.4, with brush fade and canvas change signals.
  H2 is re-run with pressure, and the trial with real pressure.
- **Verify the plugin on Krita 6.x** (N-05, H5). Left out at the round 1 intake (SPEC decision 3);
  round 1 tests 5.3.x only. The plugin keeps its PyQt6 import path for this.
- **Probes on a Krita development build** (PDD Q9). Throwaway documents only, for early Phase 6
  capability checks. Left out at the round 1 intake.
- **The H2 sheet with sensors toggled.** Round 1 uses stock presets as shipped; turning Fade or
  Distance on and off needs preset editing (Phase 2). Left out at the round 1 intake.
- **Windows and Linux.** The code stays portable, but nothing is tested there. Left out at the
  round 1 intake.
- **A plugin zip for other users,** importable through Krita's *Import Python Plugin from File*.
  Left out at the round 1 intake; round 1 installs with `install-plugin`.
- **Layer reads of groups and masks** (0.5.0). `krita_capture` and `krita_sample` read paint
  layers only: a group has no pixels of its own, and a mask is one channel. A group could be read
  through `Node.projectionPixelData`, and a mask as a grey image.
- **Colour maths for documents outside sRGB** (0.5.0). `krita_sample` gives L\*a\*b\* and
  L\*C\*h only for Krita's sRGB profiles, and greyscale captures need them. Converting through
  the document's ICC profile would lift that.
- **Reading a frame other than the one on screen** (0.5.0). Reads refuse a document whose current
  frame is not 0, and never move the owner's timeline. `Node.pixelDataAtTime` (K32) could read a
  layer at any frame without moving it; Phase 5 decides.
- **Undo labels in other languages** (0.7.0). `krita_history_step` confirms each step by the label
  Krita's Undo action gives it, as measured in English ("Add Layer", and an unnamed step for a
  selection change). In another language every layer step reads as a step the bridge did not
  make, and history refuses it. Labels could be read from Krita's own translation, or measured at
  bridge start on a throwaway document.
- **Region checks that know a filter's kind** (0.8.0). `krita_layer_update` refuses region scope
  whenever a filter layer sits above the layer or a filter mask on it, whatever the filter. A
  per-pixel filter (levels, curves, HSV) cannot spread a change, so knowing the filter's kind
  would spare such documents `verify: "full"`.
- **Krita's memory after an 8192 × 8192 document closes** (0.9.0). Opening the N-09 master
  (30 layers) took 4.7–5.2 s and raised Krita's resident memory by 300–500 MB, which stayed after
  the close; across a probe run Krita grew from about 0.9 GB to 1.5 GB. The 0.8.0 kill while
  opening an 8k ORA did not recur in six 8k opens. Whether Krita returns the memory later, or a
  painting day accumulates it, is unmeasured.
- **Erasing** (0.9.0). `eraser: true` is refused with `UNSUPPORTED_CAPABILITY`: on Krita 5.3.4.1,
  `View.eraserMode()` read false after `setEraserMode(True)`, with `b) Basic-2 Opacity` and with
  the stock `a) Eraser Soft`, so no stroke could be confirmed to erase. The order of the brush
  setters and posted events are the first things to try.
- **A single dab** (0.9.0). Krita paints no dab for a stroke without length: one point, two equal
  points and a 0.01 px segment each painted nothing; a 0.5 px segment painted one dab. A one-point
  stroke is refused; an agent wanting a dab sends two points half a pixel apart.
- **Region scope for other brush engines** (0.9.0). Region scope needs the pixel engine
  (`paintbrush`); Color Smudge, the Quick Brush (the stock `b) Basic-1`), MyPaint, spray, deform,
  tangent-normal and others need `verify: "full"`, since their reach is not parsed. Each engine
  could be measured and allowed as its reach is shown.
- **Not-finite numbers in other tools' inputs** (0.9.0). The MCP server accepts `NaN`, `Infinity`
  and `1e400`, and a `number` schema's `minimum` and `maximum` let NaN through. Only
  `krita_paint_stroke` refuses them on the server; `krita_layer_update`'s `opacity` and the other
  number inputs reach the plugin with them.
- **Krita's preset history** (0.9.0). Activating a preset, through the bridge or the probe, makes
  Krita record it in `kritarc` (`LastPreset`, `presethistory`). The probe puts the owner's current
  preset back; the history keeps the presets it used. Accepted by the owner and recorded; a
  separate resource folder would avoid it.
- **Changes under alpha 0** (0.8.0). The checks compare every composite byte, so a colour change
  in fully transparent pixels counts. Showing an `inherit_alpha` layer over a silhouette changed
  the colour bytes of every transparent pixel under it (1,728 px changed, 768 of them visible).
  Under an allowed mask that would refuse an invisible change. `krita_paint_stroke` counts them
  too (0.9.0): the checks stay byte-exact.
- **Composite reads in two Krita states** (0.5.0). "Isolate active layer" mode changes the
  composite a read sees, and a document with two views reports the first view's active node. Both
  are untested.

## Not yet checked by hand

Checks that need a person at the machine. Each has an automated check covering most of it;
these are the parts only a person can see.

- **The selection overlay K46 guards against** (0.5.0). With marching ants, Krita's default
  selection display, an active selection mask changed no composite byte, so the probe measures the
  overlay rather than checking it. With the mask display mode on, a capture should still show no
  overlay; the harness never changes display settings, so only a person can try it.
- **Whether a capture's K46 switch visibly moves the tab** (0.5.0). The probe confirms that
  Krita makes the document's view active and puts the previous one back; whether the tab bar shows
  it is for a person to see.
- **K46 with the global selection's own mask active** (0.7.0). A script cannot make the root's
  selection mask the active node (`setActiveNode` leaves the layer active), so the probe checks a
  local mask only, and the choice of the top-most layer for the global mask is held by unit tests.
  With *Show Global Selection Mask* on in the Layers docker, select that mask by hand, then capture
  the document: the capture should match, and the top-most layer become active.
- **A layer style spreading a change** (0.8.0). No harness op can add a layer style, so unit
  tests hold the `layer_style` reason. Add a drop shadow by hand to a layer of an agent's working
  copy, then change its opacity with `krita_layer_update`: region scope should be refused, naming
  `layer_style`, and `verify: "full"` should pass.
- **N-03 in Activity Monitor** (0.2.0). With the plugin loaded and Krita idle, Krita's CPU should
  stay under 1%. `top` measured 0.0% in six samples 5 s apart. Look at Krita's row in Activity
  Monitor for a minute while it is idle.

- **Mirror painting and wrap-around put back after a stroke** (0.9.0). The adapter switches both
  off for the stroke and back on in a `finally`; no harness op turns them on, so the probe never
  sees the restore. With either on in Krita, paint one stroke and check both are on afterwards.

## Directions

- **The trial (H1, H7).** After round 1: a Codex agent and a fresh Claude Code session each fix a
  real review defect through krita-art-mcp. The owner compares the fixes with the scripted pass at
  game size, and the result shapes Phase 2's priorities.
- **Publishing the repository.** When the owner decides, with the description "MCP server that
  lets AI agents paint in Krita" and the topics `krita`, `mcp`, `model-context-protocol`,
  `krita-plugin` and `game-art`.
  - **First, decide whether to rewrite history** (deferred by the owner in session 7a). SHA-256
    hashes of seven words the hygiene stage once checked are in every commit from the root
    (`98db9f5`) until session 7a deleted them. Five are the owner's own public identifiers; two
    were never identified. A hash of a short word can be reversed by guessing, so the question
    is whether those two can be. A rewrite needs a force push, and changes every commit's sha,
    including those the CHANGELOG links and the reviews cite.

- **Report Krita's layer-docker crash upstream.** On 5.3.4.1, closing a document within about
  half a second of a selection change crashes Krita in `KisNodeModel::processUpdateQueue`, a null
  pointer from the docker's update timer. The plugin works around it (a close lets Krita's own
  timers run first, 0.7.0); a person closing a document by hand that fast could still hit it.

## Decided against

- Tapered strokes by chaining `paintLine` segments: they become separate strokes and undo steps,
  and the joins overlap.
- `run_python` or `write_pixels` tools: they break the brush-first rule.
- A persistent `set_brush` tool: it hides window-wide shared state.
- Rollback by writing snapshot pixels back: native undo and checkpoint reopen replace it.
- `Filter.apply`: no undo, no stroke, and it ignores the selection; `startFilter` instead.
- Tool-level smoothing (`basic`, `stabilizer`): it belongs to Krita's freehand tool, which scripts
  bypass.
- A separate private repository for the process documents: one repository, with private details
  kept out of it, decided at the round 1 intake.
