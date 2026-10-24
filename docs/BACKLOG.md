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
- **N-03 in Activity Monitor** (0.2.0). With the plugin loaded and Krita idle, Krita's CPU should
  stay under 1%. `top` measured 0.0% in six samples 5 s apart. Look at Krita's row in Activity
  Monitor for a minute while it is idle.

## Directions

- **The trial (H1, H7).** After round 1: a Codex agent and a fresh Claude Code session each fix a
  real review defect through krita-art-mcp. The owner compares the fixes with the scripted pass at
  game size, and the result shapes Phase 2's priorities.
- **Publishing the repository.** When the owner decides, with the description "MCP server that
  lets AI agents paint in Krita" and the topics `krita`, `mcp`, `model-context-protocol`,
  `krita-plugin` and `game-art`.

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
