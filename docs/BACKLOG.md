# Backlog

Work that has been named but belongs to no session. Each item needs its own intake before it runs
(a `docs/spec/FEATURE-*.md` with the request verbatim and the decisions resolved, then a block
in `docs/spec/SESSIONS.md`; see `docs/DEVELOPMENT-WORKFLOW.md`). When an item is picked up, it
moves out of this file.

The phases below are described in full in the PDD, Part 4, and the contract's draft tools are in
`docs/reference/contract-package/`. The rest of round 1's `docs/spec/` left the tree when the round
closed. Read its files from git history, at round 1's release commit:
`git show 04e9f6c:docs/spec/PDD.md`, and likewise `SPEC.md`, `SESSIONS.md`, `REVIEW-2026-10-24.md`,
`REVIEW-2026-10-25.md` and `REVIEW-2026-10-30.md`. `docs/ARCHITECTURE.md`'s overview says what "the
contract", "Phase N" and "review N" mean.

## Deferred

- **Phase 2, the rest.** Round 2 took fills, masks, tapers, branching and layer construction. It
  left:
  - project profiles (`krita_project_load`, profile schema 0.2.0, H9), with `permitted_operations`,
    which has no defined shape yet. The PDD gates every Phase 2 operation on it; the round 2 intake
    amended that, so round 2's tools ship ungated, on protection and verification alone. The
    contract's acceptance exercise 5 (two profiles, no leakage) runs with them;
  - `filter_apply`, `color_convert`, `palette_manage`, `paint_clone` and `canvas_resize`;
  - `paint_shape` and `paint_path`, which `krita_paint_stroke` and fills may already cover;
  - `layer_import`, `reference_set`, `guides_set` and `view_set`;
  - preset tuning beyond tapers, templates and derived copies.
- **A server-side batch.** Left out at the round 2 intake, with the Codex agent's agreement. `exec`
  already awaits calls and stops on a failed envelope: 1,253 of 1,377 consecutive calls were under
  0.25 s apart. One would earn its cost through shared-context enforcement, durable partial receipts
  and recovery across a client's interruption, never atomic rollback (K29). Round 2's last session
  re-measures.
- **Wrap authoring and a tiled preview.** Left out at the round 2 intake: Phase 5 owns tiling, and
  paired shapes at opposite edges were workable. A scripted stroke honours wrap-around (K47) and
  paints the opposite edge; `Canvas.setWrapAroundMode` is not axis-aware, and the actions
  `wrap_around_hv_axis`, `wrap_around_h_axis` and `wrap_around_v_axis` set the axis. Enabling wrap
  can push a "Crop Selections" undo step (`libs/image/kis_image.cc:2567-2580`). No textured
  continuity is claimed without an edge and corner probe.
  - **Proposed again after 0.18.0 by the Codex agent,** not yet decided: a protected, verified
    integer wrap translation (a half-roll) and a tiled preview. In one session, every wrapped asset
    needed a lossless half-roll made outside the tools, and a reopen. A wrap translation shares T1's
    question of a native route.
- **Target identity in receipts and guidance** (0.18.0). The Codex agent sent three strokes to the
  wrong document through its own helper's default target; the server did what it was asked. Making
  the document, layer and selection a mutation acted on prominent in each receipt, and in the
  instructions, would make such a slip visible at once. Measure before proposing a batch.
- **Flood fill from a seed.** Left out at the round 2 intake: flat fills of a shape or a selection
  replace the workaround real use needed.
- **A closed-curve selection shape.** Left out at the round 2 intake. Raw polygons work;
  `krita_paint_fill`'s closed `path` is the code to share if it is wanted.
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
- **Windows and Linux.** The code stays portable, but nothing is tested there. Left out at the
  round 1 intake. On Linux the bridge needs its own guard against SIGPIPE: `SO_NOSIGPIPE` is
  Darwin's, so a reply to a client that has gone would still kill Krita there (0.12.0).
- **Saving a document over 8192 × 8192 pixels** (review 13, F4). The save verifies by reading
  the whole live composite, the whole reopened composite and every node's pixels unbanded, so
  `krita_document_save` refuses a larger canvas with `UNSUPPORTED_CAPABILITY` while open, paint
  and preview take it. Banding the save's reads and hashes, as the stroke's compares are banded,
  lifts the bound; Phase 2's whole-canvas filters need the same banded reads (review 10, F13).
- **A retention rule for the journal** (review 13, §8.8 item 9). The journal is permanent and
  unbounded (PDD Part 6): about 44 MB a heavy week of strokes, read in full by the first lookup
  of each server process (3 ms today). Fine for round 1; a painting year wants a rule.
- **Sweeping a save a Krita crash interrupted** (0.12.0). `krita_document_save` writes a hidden
  `.<name>.<token>.saving.kra` (or `.ora`) beside its path and moves it into place once verified.
  A new save or a close of the document removes one never finished, but a Krita crash between
  the export and the finish leaves it, and nothing sweeps the owner's folders.
- **A plugin zip for other users,** importable through Krita's *Import Python Plugin from File*.
  Left out at the round 1 intake; round 1 installs with `install-plugin`.
- **Layer reads of groups and of masks in `krita_sample`** (0.5.0). `krita_capture` and `krita_sample`
  read paint layers only, and round 2 adds masks to `krita_capture`. A group has no pixels of its own,
  and could be read through `Node.projectionPixelData`.
- **Colour maths for documents outside sRGB** (0.5.0). `krita_sample` gives L\*a\*b\* and
  L\*C\*h only for Krita's sRGB profiles, and greyscale captures need them. Converting through
  the document's ICC profile would lift that.
- **Reading a frame other than the one on screen** (0.5.0). Reads refuse a document whose current
  frame is not 0, and never move the owner's timeline. `Node.pixelDataAtTime` (K32) could read a
  layer at any frame without moving it; Phase 5 decides.
- **Undo labels in other languages** (0.7.0). `history.move` confirms each step by the label Krita's
  Undo action gives it, as measured in English ("Add Layer", and an unnamed step for a selection
  change). In another language ordinary calls complete, but every layer step reads as a step the
  bridge did not make: `krita_history_step` refuses it, and a leak's rollback ends in
  `ROLLBACK_FAILED` and an unsafe document. Until this lands, the guide and the README require
  Krita's interface in English. Labels could be read from Krita's own translation, or measured at
  bridge start on a throwaway document.
- **Region checks that know a filter's kind** (0.8.0). `krita_layer_update` refuses region scope
  whenever a filter layer sits above the layer or a filter mask on it, whatever the filter. A
  per-pixel filter (levels, curves, HSV) cannot spread a change, so knowing the filter's kind
  would spare such documents `verify: "full"`.
- **Krita's memory after an 8192 × 8192 document closes** (0.9.0). Opening the N-09 master (30
  layers) took 4.7–5.2 s and raised Krita's resident memory by 300–500 MB, which stayed after the
  close; across a probe run Krita grew from about 0.9 GB to 1.5 GB. The 0.8.0 kill while opening an
  8k ORA did not recur in six 8k opens. By the end of a probe run Krita holds about 2.5 GB, and a
  restart resets it. Whether Krita returns the memory later, or a painting day accumulates it, is
  unmeasured.
- **Erasing** (0.9.0). `eraser` takes only `false` (out of the schema since 0.20.0): on Krita 5.3.4.1,
  `View.eraserMode()` read false after `setEraserMode(True)`, with `b) Basic-2 Opacity` and with the
  stock `a) Eraser Soft`, so no stroke could be confirmed to erase. The order of the brush setters
  and posted events are the first things to try. Left out at the round 2 intake: real use wants it
  for transparent edges, because undo and painting over do not remove alpha, but masks cover the
  immediate need. Preserve-alpha must go on refusing it.
- **A single dab** (0.9.0). Krita paints no dab for a stroke without length: one point, two equal
  points and a 0.01 px segment each painted nothing; a 0.5 px segment painted one dab. A stroke
  shorter than half a pixel is refused; an agent wanting a dab sends two points half a pixel
  apart.
- **Region scope for other brush engines** (0.9.0). Region scope needs the pixel engine
  (`paintbrush`); Color Smudge, the Quick Brush (the stock `b) Basic-1`), MyPaint, spray, deform,
  tangent-normal and others need `verify: "full"`, since their reach is not parsed. Each engine
  could be measured and allowed as its reach is shown.
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
- **Selection steps are confirmed by state alone** (0.7.0). Their Undo label is empty, and Krita
  keeps Redo enabled as "Redo " with nothing to redo. A named step on top still stops history.
- **A job interrupted before it runs** (0.6.0). An interrupt landing between taking a job and
  running it fails that job, but the jobs queued behind it wait for the next call to wake the queue.
- **A server killed mid-write** (0.6.0) leaves a `.mask-*.tmp` in `transfer/`, which only the
  bridge's start sweeps.
- **The credit patterns name nine tools** (hygiene). A tool missing from them passes a "generated"
  line in a commit message.
- **A replayed receipt loses its inline diff.** A retried failed stroke returns the artifact's path
  and the counts, but not the image the first call carried. Cosmetic.
- **The reach analysis over-refuses a filter layer inside a closed group above the target,** which
  cannot see below its own group. It is safe, and costs such a document `verify: "full"`.
- **Bounded growths, accepted.** The bridge's dedup state grows for the Krita session, about 1,000
  operations a probe run. History's region capture and a refusal's diff are bounded by the canvas,
  not by the read limit.
- **A create's other colour models are refused twice,** by the schema's enum and by the plugin.
  Harmless.
- **`limits.capture_pixels` is reported, and enforced only by `max_px`'s schema maximum.** It is
  that maximum squared.
- **`effects` serialises every layer style on each region-scope call,** the only way libkis tells
  whether a style exists. It is inside N-09's budget with 30 layers.
- **`Registry.sync` compares every handle with every document on each lookup.** Unmeasured as a cost
  at 87 documents; a Krita holding hundreds may feel it.
- **`Jobs.follow` and `wait` take their deadline from `time.monotonic()`,** where every other time
  in the class comes from the injectable clock. Nothing is wrong; it is the one seam.
- **Test fixtures are repeated.** Eighteen test files define their own `world` around
  `running_world`, `_render`, `_pixels` and `_document` appear four times each, and there is no
  `conftest.py`.
- **The plugin's eraser plumbing is unreachable** while the schema takes only `false`, and
  `schemas.tool_names` is reached by tests only.
- **A client's `serve` runs this checkout as it stands** (0.18.0). Both registrations run
  `uv run --project <repo>`, so an MCP client started mid-session imports that session's uncommitted
  code. Once the version is bumped and the plugin installed, nothing refuses it. R2's Codex session
  ran that way, on finished code. A released copy to serve from would keep a client off work in
  progress.
- **A property write leaves Krita's flag clear.** A name, opacity, visibility or alpha-lock change
  through libkis is no undo step (K22), so Krita does not mark the document modified, and a tab
  close would drop it without asking; the bridge's `dirty` still holds it. Marking Krita's flag after
  such a write is a separate choice from the one R3 made, which only reports it.

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
- **A hand change only to what no save compares** (0.19.0). After a verified save, `refuse` closes
  while the composite, the layer tree and the compared pixels match. A hand change to guides, or to
  the global selection where no layer holds it, should still close under `refuse`; no harness op
  makes one.
- **A layer style spreading a change** (0.8.0). No harness op can add a layer style, so unit
  tests hold the `layer_style` reason. Add a drop shadow by hand to a layer of an agent's working
  copy, then change its opacity with `krita_layer_update`: region scope should be refused, naming
  `layer_style`, and `verify: "full"` should pass.
- **The floating message** (0.14.0). No harness op can see the widget, and no failure reached
  `plugin.log` across the probe runs; the owner did not catch it by eye. Have an agent paint on the
  document in front, and look for "krita-art-mcp: an agent is working on this document" on the
  canvas. Krita's *Show on-canvas popup messages* setting can hide it.
- **N-03 in Activity Monitor** (0.2.0). With the plugin loaded and Krita idle, Krita's CPU should
  stay under 1%. `top` measured 0.0% in six samples 5 s apart. Look at Krita's row in Activity
  Monitor for a minute while it is idle.
- **A Krita that dies mid-call** (0.3.0). Unit tests hold the uncertain outcome, and each of the
  deaths found in 0.12.0 came back `INTERNAL_ERROR` with `outcome: uncertain`, but nobody has forced
  one on purpose. Quit Krita hard during a long save through the tool, restart it, and retry with
  the same `request_id`: expect `uncertain`, with nothing sent again.
- **A lazy baseline from a file saved with a selection mask active** (0.11.0). The baseline is
  read from the working copy's file, opened again without a view, so Krita should draw no mask
  overlay into it (K46); the probe's fixtures never save one. Save a KRA by hand with a local
  selection mask as the active node, open it as a working copy, and render it with its
  `baseline_id`: the as-opened cell should match the current one.
- **An autosave holding a document during a save** (0.12.0). Krita's `exportImage` returns false
  while an autosave holds the document, and the save answers `BUSY`, retryable, leaving nothing on
  disk; unit tests hold that (decision 29). One unforced `BUSY` came during a measurement, on a
  fresh working copy, and did not repeat. Set Krita's autosave to every minute, change a working
  copy by hand, and save it through the tool as the autosave starts: expect `BUSY`, nothing beside
  the path, and a retry that succeeds.
- **A document closed by hand during a save's finish** (0.13.0). The bridge drops the save's
  hidden file when it finds the document gone; unit tests hold that, and the window is a few
  seconds. Save a large working copy through the tool, close its document in Krita before the save
  returns, and check that nothing hidden is left beside the path.
- **Mirror painting and wrap-around put back after a stroke** (0.9.0). The adapter switches both off
  for the stroke and back on in a `finally`; no harness op turns them on, so the probe never sees
  the restore. With either on in Krita, paint one stroke and check both are on afterwards. With wrap
  on and a selection held, also check `krita_history_step` still undoes that stroke: enabling wrap
  can push a "Crop Selections" step, read from source at the round 2 intake, not seen.

## Directions

- **The trial (H1, H7).** After round 1: a Codex agent and a fresh Claude Code session each fix a
  real review defect through krita-art-mcp. The owner compares the fixes with the scripted pass at
  game size, and the result shapes Phase 2's priorities.
- **Publishing the repository.** When the owner decides, with the description "MCP server that lets
  AI agents paint in Krita" and the topics `krita`, `krita-mcp`, `krita-plugin`, `mcp`,
  `mcp-server`, `model-context-protocol`, `ai-agents`, `game-art` and `digital-painting`, both set
  on the repository already. Turn on private vulnerability reporting once it is public, since the
  README sends security reports there.
  - **History stays as it is,** by the owner's decision on 2026-11-01, since none of it is a secret.
    It holds SHA-256 hashes of seven words the hygiene stage once checked, from the root (`98db9f5`)
    until they were deleted, five of them the owner's public identifiers and two never identified;
    one personal folder's name; a machine inventory; and a note on app permissions. Every old file
    version and commit message scanned clean against the term list on that date. Hygiene reads no
    old file versions, so repeat that scan just before publishing if the list has grown.

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
- `Document.clone()` for branching: it is never added to `KisPart`, which `Krita.documents()` reads,
  so the registry would drop its handle. A verified save and a reopen give a real path and a
  baseline.
- Translate by a compensated `Node.move`: it has no undo, and putting it back inside one call is not
  recovery. A native route ships, or translate waits for Phase 3's checkpoints.
