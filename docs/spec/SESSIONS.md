# The session plan: round 2, recovery and construction

One chat per session. Never run two sessions in one chat: the point of the split is that no
session inherits stale context.

- **Scope** lives here, fixed in advance. The request and its resolved decisions are in
  `FEATURE-recovery-and-construction.md` beside this file, which is read-only; do not re-litigate
  them. If a session finds a block wrong, it amends the block and records the reason both in the
  block and in `docs/next-session-prompt.md`.
- **State** is `CHANGELOG.md` (what shipped) and `docs/next-session-prompt.md` (what the next
  session needs that the docs do not say). Every session rewrites the prompt as its last act.
- **When this round closes,** V1 deletes this file, the feature file and every `REVIEW-*.md`. Git
  history keeps them, and anything left open moves to `docs/BACKLOG.md`.

**Before starting**, confirm the tree is clean and that `docs/next-session-prompt.md` names the
session you are about to do. **Read** in the workflow's order (the cycle, step 2), starting with
what your block's **Read** line names. **Then plan, in plan mode,** and ask the block's *Ask at the
start* questions before any edit.

**Every session ends the same way:**
1. `uv run scripts/verify.py` green, plus the harnesses the block names.
2. Every new check falsified, once. Checks that already existed are not falsified again.
3. A `CHANGELOG.md` entry for anything user-visible, and the version bumped as the table says.
4. The docs the block names kept true, and ARCHITECTURE's baseline table updated for any count that
   moved.
5. A done-note appended to the block, then the prompt rewritten, then `uv run scripts/verify.py
   --message <draft>` run with the drafted commit message, then a local commit.
6. The owner's `/code-review high`, then a review-fixes commit.
7. The next prompt printed as the chat's last message.

Never push without being asked.

| Session | Scope | Decisions | Version |
|---|---|---|---|
| R1 | Mutation recovery | 4–9 | **0.17.0** |
| R2 | Truthful hints, timing, Hamming | 1, 2 | **0.18.0** |
| D1 | Discovery: colours, limits, ranges, finite numbers | 9, 11 | **0.19.0** |
| F1 | One verified-mutation frame, parity tests | 5, 10 | — |
| C1 | `krita_paint_fill` | 1, 3 | **0.20.0** |
| M1 | Transparency masks | 1, 3, 14 | **0.21.0** |
| X1 | Architecture review: the frame and its first two tools | all | — |
| E1 | Taper probe, then the proven subset | 16 | **0.22.0** |
| L1 | Layers: duplicate, reorder, remove, group | 1, 3, 13 | **0.23.0** |
| B1 | Document duplicate | 1, 3, 12 | **0.24.0** |
| T1 | Translate, on a native route or not at all | 1, 15 | **0.25.0** |
| S1 | Scale, rotate, shear; cut first if the round runs long | 1, 3 | **0.26.0** |
| X2 | Architecture review: construction | all | — |
| V1 | Re-measure, docs, full run, close the round | 18 | **0.27.0** |

A review session changes no product code and cuts no version; a session it inserts takes the next
version, and every later version shifts by one. E1 on a no-go and T1 without a native route ship no
version, and the later versions move down by one; the handoff says so.

---

## R1: Mutation recovery

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (P1, regression
coverage), *What the intake measured* (The bug), decisions 4–9; `ARCHITECTURE.md` *The bridge
contract* (Dedup and retention, A 404 while following a call), *The tool contract* (The envelope,
The error codes), *The data layer* (The journal), *Bridge and jobs*, *Registry, lease and document
state*, *Documents*, *The verification core*, *Painting*, *The undo ledger and history*, *The save*,
*The server*.

- **The bounds** (the bug). `bridge_core/painting.py:204-207`.
  - `changed_bounds_px` is canvas-clipped. The union with the layer's bounds runs only when the
    *clipped* bounds leave `target_rect`, so a layer with old overhang no longer trips it.
  - A nullable `layer_bounds_px` carries Krita's unclipped extent after the stroke. Its `x` and `y`
    take any integer, as inspect's `bounds_px` does.
- **The markers** (decision 5). A hand-placed marker, on the `Call`, goes before the first change of
  any kind on each path through each of the 11 mutating ops: document, protection state, file or
  registration. The brush is excluded. It is not one line per op:
  - `document.open`: `working_copy` at `files.working_copy` (`opening.py:89`), `read_only` at
    `port.open` (`:105`);
  - `document.create`: `port.create`;
  - `document.close`: `drop_pending_save` (`documents.py:73`);
  - `document.save`: `_make_folder` (`saving.py:91`), because the drop moves after the export
    (below);
  - `document.save_finish`: `handle.pending_save = None` (`saving.py:169`);
  - `protection.set`: where the handle's state is written;
  - `selection.set`: both `before_change` sites (`selections.py:77,81`);
  - `layer.update`: the changes at `:73-79`, and the `active`-only path at `port.activate` (`:114`);
  - `layer.create` and `paint.stroke`: at `before_change` (`layers.py:23`, `painting.py:133`);
  - `history.step`: inside `move()`, before `_act` (`history.py:95`), behind a flag, because `move`
    is also every other op's rollback and its `FOREIGN` raise comes first.
- **Reading the marker.** `Jobs._run` turns a raise into `details.outcome` by decision 5's order: an
  explicit value; retryable or `rollback_verified: true` is `not_applied`; before the marker is
  `not_applied`; otherwise `uncertain`. An unexpected exception is `uncertain`. Every op is classed
  read, bounded or `harness.*`, the last pinned to its prefix so no tool op hides in it.
- **Failures that never reach `Jobs._run`** state their outcome too, or every ordinary refusal would
  read `uncertain`.
  - An op that never ran is `not_applied`, set where `Jobs` finishes it: the conflict and the
    unknown op in `submit`, and `cancel` and `stop` (`jobs.py:145,158,307,317`).
  - The op stopped by an interrupt in `drain` (`jobs.py:186`) states nothing, so it is `uncertain`.
  - On the server, `_checked` fills in the rest, for mutating tools: a failure with no
    `operation_id` never went out, so it is `not_applied` (decision 8), and one with an
    `operation_id` and no statement is `uncertain`.
  - A read that leaves a document registered (`reopening.read_file`) states `uncertain`.
- **Cleanups are verified** (decision 5). Without this, `SAVE_VERIFY_FAILED`, the commonest failure
  past a marker, reads `uncertain` and the field is noise.
  - `_remove` (`saving.py:510`) and its callers check `not lexists(written)`; `_Made.undo` checks
    `kept is None`. `_unmake` (`:248`) reports what stayed, and a folder something else has filled
    counts as cleaned, since it is no longer ours to remove. Each reports `rollback_verified`.
  - `_check_writable`'s refusals (`:257`) need the folder, so they stay past the marker and depend
    on this.
  - `rollback_verified` is the one key the rule reads; `layers.py:58` adds it beside `rolled_back`.
  - The open and create discard paths (`opening.py:51-54`, `documents.py:41-43`) state `uncertain`
    when the document stays.
- **`BUSY` becomes true.** The drop at `saving.py:90` moves after a successful export, because
  `retryable ⇒ nothing changed` is false there today.
- **The server keeps identity** (decisions 6–8).
  - `_checked` (`tools/__init__.py:141-145`) carries `document_id` and `operation_id` out of a
    result that breaks its contract. A completed result from a mutating tool becomes `outcome:
    applied`. The reason stops quoting the receipt: jsonschema's message echoes the whole instance.
  - `journaled` catches any raise after dispatch, not only a receipt's, and still records.
  - `_merged` is guarded (`tools/saving.py:117`), so a finish always runs and no hidden file stays.
  - `changes.py:247,285,383` say `applied`, keep their ids, and are never retryable.
  - `outcome_of` settles `applied` as a receipt.
  - `details.outcome` is typed in the shared error shape through `scripts/amend_schemas.py`.
- **`krita_operation_get`** gains `outcome`, `receipt_valid` and `receipt_problem`. It returns the
  raw receipt as structured data (its schema is a plain object), survives a receipt that raises, and
  still settles the journal. `outcome` is null while the call is queued or running.
  - **After a Krita restart it answers from the journal** (decision 5). `bridge_client.py:166-167`
    returns `uncertain` as soon as the session differs, and `Journal.session_of` gives only a
    session, so the journal needs a lookup by operation id. A finished line answers with its own
    outcome; otherwise `uncertain`.
- **Docs.**
  - `USER-GUIDE.md`: *Retries and long calls*, *Every error code*.
  - `ARCHITECTURE.md`: *The bridge contract*, *The tool contract*, *Painting*, *The save*, *The
    server*.
  - Server instructions: the outcome rule, at most 150 characters net. D1 frees more.
  - `CHANGELOG.md`: 0.17.0.
- **If it runs long,** `krita_operation_get`'s three fields move to an inserted R1a.

**Gates:**
- `uv run scripts/verify.py`, with these tests:
  - the failing request's geometry, on a fictional opaque master;
  - each op raised on both sides of its marker, with the fake adapter refusing a mutating port call
    while no marker is set, so a misplaced marker fails on its own path;
  - every op classed; every retryable raise changing nothing;
  - `_checked`, `journaled` and `krita_operation_get` against a forced post-application failure,
    with ids, `applied`, and a settled journal;
  - decision 7's resend rule: same session, restarted session, `no_effect`, `unregistered`;
  - `not_applied` on a schema refusal, a tool's own refusal, a request conflict and a cancelled job;
  - `krita_operation_get` after a restart, with and without a finished line.
- `probe`, with these checks:
  - each edge and corner, with and without a selection, in both scopes, within the half-brush
    overhang: `changed_bounds_px` inside the canvas and true, `layer_bounds_px` reporting the
    overhang;
  - a stroke wholly in the overhang (an empty intersection): `changed_bounds_px` null, history
    sealed;
  - a full-scope stroke far from the edge, on a layer with old overhang;
  - same-request replay paints nothing;
  - alpha, protection and undo on each;
  - save and reopen after overhang.
- Each new check falsified once.

**Watch for:**
- **`uncertain` must stay rare.** It settles as `UNKNOWN` (`dispatch.py:45-46`), skips the roots
  precheck on a retry (`:93`) and dedups to the same failure for the Krita session. `uncertain` on
  an ordinary refusal means a misplaced marker.
- **The change counter is no evidence.** `move()` calls `before_change()` during confirmed rollbacks
  and `REVERSED` steps (`history.py:93`).
- **A retry of the original failing request keeps failing, now with ids.** The journal holds its
  receipt.
- **`tests/fixtures/fake_krita.py` has to model bounds off the canvas,** and stays valid on 3.10.
- **Version first.** Bump before the first live run: the plugin's hash and `serve`'s gate both read
  it.

**Done (2026-11-02, 0.17.0).**
- **Decided with the user at the start:**
  - The plan's amendments below, approved in plan mode.
  - The owner restarted Krita for the live run, because it held unsaved documents.
- **The bounds.** `changed_bounds_px` is canvas-clipped, and only the clipped layer bounds widen it in
  full scope. `layer_bounds_px` is new, nullable, and takes any integer `x` and `y`.
- **The rule.** `Call.mark()`, `READS`, `BOUNDED`, `HARNESS` and `jobs.stated`. `details.outcome` is
  typed through `scripts/amend_schemas.py`. `api_version` stays 0.2.0.
- **Cleanups.** `errors.cleaned`, and `files.remove`, `unmake` and `make_folder`, moved from
  `saving.py`. `_Made` undoes the folder, the copy and the document.
- **The server.** `_checked` keeps ids and fills in a statement. `journaled` catches any raise after
  dispatch. `applied_failure`, `raw_receipt` and `contract_problem` are new. `_merged` never raises.
- **`krita_operation_get`** gains `outcome`, `receipt_valid` and `receipt_problem`, returns a raw
  receipt as data, and answers from `Journal.finished_line` once the bridge cannot.
- **`probe/edges.py`** holds the block's live checks, and `_nothing_uncertain` reads the run's journals.
- **Amendments:**
  - **The open cleans up its own folder,** which the block did not list. `working_copy` hashes as it
    copies, so an ordinary wrong hash lands past the marker, and an empty folder would have stayed
    behind a claimed rollback. Amended at plan time, with the user.
  - **An earlier pending save is dropped last,** just before the new `Pending`, not right after the
    export. A failed verify then leaves it too, so `rollback_verified: true` is the whole truth.
    Amended at plan time, with the user.
  - **"The export moved the document to its file" states `uncertain`,** because removing the file
    cannot undo it. Amended at plan time, with the user.
  - **`drain` and the replaced not-JSON failure state `uncertain`** rather than nothing, so the journal
    agrees with the reply. Amended at plan time, with the user.
  - **Sites the block did not list,** at plan time, with the user: `submit`'s taken `operation_id`;
    `_bridge_error` and `_unexpected`; "The save was not finished."; a finish that says nothing;
    `operation_id` on `_uncertain` and `_unregistered`.
  - **A receipt that raises takes the raw path,** so one route serves bad and missing receipts, and
    `record` catches `Exception`, since a raise there would reach a catch-all that says `not_applied`.
    Amended at plan time, with the user.
  - **A journal check that no call in the run was left uncertain.** Amended at plan time, with the
    user.
  - **A kept document also clears `retryable`** and reports `rollback_verified: false`, at the open
    and the create. Falsification found it; the session's own finding.
- **Measured,** on Krita 5.3.4.1:
  - The failing request's geometry with `b) Basic-2 Opacity`: `changed_bounds_px` {364,0,64,87}, equal
    to the layer's own bytes; `layer_bounds_px` {362,-17,65,104}; alpha unchanged.
  - Off-canvas paint survives a KRA save and reopen, with every layer's bounds equal.
  - Under a selection, Krita can write colour under alpha 0 past its edge, so `changed_bounds_px`
    reached 2 px past a rect selection while no alpha did.
  - No call in the probe's run was left `uncertain`.
- **Falsified:**
  - 103 product mutations, one at a time, in a scratchpad driver: 100 caught at their own tests.
    The first pass found four gaps in the tests, each now covered, and the kept document's
    `retryable`, now fixed.
  - Three stay equivalent. Removing `if not sent: raise` reaches the same catch-all through a
    `KeyError`. The kept document's explicit `uncertain`, at the open and the create, repeats what
    `rollback_verified: false` past the marker already gives.
  - Every new probe check: its assertion broken in five runs, each failing at its own step.
- **Numbers:** 731 server tests (+61), 775 plugin tests (+110), probe 142 PASS (+11), 0 FAIL, 23
  MEASURED, about 120 s. Instructions 3,970 characters (+64). 19 tools, 30 error codes, 31 ops.
- **Review (`/code-review high`), 10 findings: 10 fixed and 0 skipped.**
  - **A file in a folder's path read `uncertain`.** `unmake` took `ENOTDIR` for a folder of ours that
    stayed, on an ordinary refusal.
  - **Dropping the earlier save last lost its folders.** The new `Pending` now takes them over.
  - **A read the server could not finish read `uncertain`.** `pixels.failed` now states `not_applied`.
  - **A kept reopened file claimed a clean rollback.** `read_file` now reports it as not cleaned, on
    both paths, which also clears `retryable`.
  - **An applied PNG failure left its transfer file,** which no retry adopts now. It is discarded.
  - **A hidden file that stays after placing went unreported.** It is logged; the save stands.
  - **`krita_operation_get`'s outcome enum could drift.** `amend_schemas.py` writes it.
  - **Duplication.** `identity` and `failed_after` in `dispatch.py` replace three id checks and two
    `Failed` builders, and the two `_stated` functions no longer share a name.
  - **The new tests lost dead setup and stray helpers,** including one repeated test.
  - **`krita_operation_get` read the journal twice per poll.** It reads a line only when the bridge
    cannot answer.
  - **Falsified:** the seven checks the fixes added, each failing at its own step.
  - **Numbers after the review:** 732 server tests, 781 plugin tests, probe 142 PASS, 0 FAIL, 23
    MEASURED, about 118 s on a restarted Krita.

---

## R2: Truthful hints, timing, Hamming

**Read:** `FEATURE-recovery-and-construction.md` *What the intake measured* (Where the time went),
decisions 1, 2; `ARCHITECTURE.md` *The tool contract*, *The data layer* (The journal), *Reads, and
K46* (Capture), *Previews and the lazy baseline*.

- **Ask at the start of R2:** has the owner run a Codex session with `default_tools_approval_mode`?
  Its numbers decide what this session's gate can show.
- **Hints** (decision 1). The five `annotations` flip to `destructiveHint: false`. A table test
  beside `tests/test_tools.py:83` holds every tool's hints, so none drifts.
- **Timing.** A `finished` journal line carries the server's own `elapsed_ms`, so tool time and a
  client's wall clock can be told apart.
- **Hamming.** `hamming` joins `imaging.FILTERS` (`imaging.py:23`) and both schemas' `filter` enums,
  in capture and preview, inputs and outputs.
- **Docs.**
  - `USER-GUIDE.md`: *Register the server*: what the Codex setting does and what it removes
    (decision 2). The hints table.
  - `ARCHITECTURE.md`: *The tool contract*, *The data layer*.
  - `CHANGELOG.md`: 0.18.0.

**Gates:**
- `uv run scripts/verify.py`, with these tests: the hint table, the journal's new field read back by
  the index, and a Hamming render on capture and preview.
- `probe`: a Hamming preview, by a check that it differs from bicubic on a fixture.
- **By hand:** the owner's short Codex session, compared from the client's own records as counts and
  timings only. Tool time should meet wall clock on the five. Record the numbers in the done-note,
  and whether the inference held.
- Each new check falsified once.

**Watch for:**
- **The five buy little by themselves,** about 4 of 47 minutes. Say so; do not report it as the fix.
- **If the 2 s stays on the five,** the inference was wrong. Stop and report; do not widen decision
  1.
- **The journal reader accepts version 2 only.** Check that an added field needs no version.

---

## D1: Discovery

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (Input and schema
discoverability), decisions 9, 11; `ARCHITECTURE.md` *The tool contract* (Schemas are data, Which
forms reach Codex, The instructions), *Reads, and K46* (Capture, Sample); `docs/USER-GUIDE.md`
*Phase 1's limits*.

- **Colours.** `krita_sample` gains `color`, the exact shape `brush.color` takes, and `rgba` becomes
  `rgba_255`. `api_version` moves to 0.3.0 (decision 9). A sample-to-stroke example in the schema.
- **Limits.** `LIMITS` (`tools/observe.py:9`) gains the brush size range, the resource page size and
  the overhang rule, each held equal to its enforcing constant by a test.
- **Ranges where the agent reads them.** Codex renders a property's `description` as a comment and
  drops `minimum` and `maximum` (`codex-rs/code-mode-protocol/src/json_schema_types.rs`). Add
  `description`s wherever a range or unit matters: `brush.color.rgba`, `size_px`, `opacity`, `flow`,
  the page `limit`, `points`.
- **Capture's two forms.** Native and resampled made explicit in the schema and its examples, within
  the forms `tests/test_schemas.py` holds.
- **Not-finite numbers** are refused in every tool, in one place on the server. `NaN`, `Infinity`
  and `1e400` pass a `number` schema's bounds.
- **Refused values** (decision 11), for `krita_paint_stroke`, the schema this session amends. No
  phase names these: `smooth: basic|stabilizer` and `antialias: false` leave the schema, and
  `brush.eraser`, still required, becomes the constant `false`. Erasing, when it comes, puts it
  back. This shares D1's `api_version` move. `krita_document_create`'s refused values stay: this
  round does not amend that schema.
- **The instructions.** Move what descriptions now carry out of `instructions.py`, because 190
  characters are spare and every later session needs some. Leave at least 500 spare.
- **Docs.**
  - `USER-GUIDE.md`: *The core loop*, *Phase 1's limits*.
  - `ARCHITECTURE.md`: *The tool contract* with its placeholder tables, the baseline's instructions
    count.
  - `CHANGELOG.md`: 0.19.0.

**Gates:**
- `uv run scripts/verify.py`, with these tests: `color` round-trips into a stroke; each limit equals
  its constant; every tool refuses a not-finite number; each removed value answers
  `INVALID_ARGUMENT`; rendered inputs stay under Codex's limits.
- `probe`: a colour sampled and painted back lands exactly (extends H6).
- Each new check falsified once.

**Watch for:**
- **Descriptions count.** They raise each rendered input; Codex compacts a normalised input over
  5,000 bytes, and a rendered one over 16,000 becomes `unknown`.
- **The probe reads `rgba` too.** Rename it in one pass.

---

## F1: One verified-mutation frame

**Read:** `FEATURE-recovery-and-construction.md` decisions 5, 10; `ARCHITECTURE.md` *Bridge and
jobs*, *Registry, lease and document state*, *The verification core*, *Painting*, *The undo ledger
and history*, *Testing strategy*; from git history, `git show
04e9f6c:docs/spec/REVIEW-2026-10-25.md` F3 and `git show 04e9f6c:docs/spec/REVIEW-2026-10-30.md` F19
and §8.8 items 6, 8.

- **`bridge_core/mutation.py`.** One frame: scope, reads, marker and `before_change`, `unconfirmed`,
  the change, the verdict, the ledger, rollback, the receipt.
  - It takes a channel count, because a mask reads one byte per pixel (M1).
  - It takes one or more undo steps per op (L1).
  - R1's markers become structural here.
- **`paint.stroke`, `layer.update` and `layer.create` move onto it.** The save keeps its ladder.
- **Parity tests for the six argument pairs** (decision 10), and a helper for each new pair.
- **Docs.** `ARCHITECTURE.md`: *The tool contract* (its note naming this session), *The verification
  core*, *Painting*, *Known debt*. No `CHANGELOG.md` entry and no version: nobody can see it.

**Gates:**
- `uv run scripts/verify.py`: every existing test, with no count moved but the parity tests.
- `probe`: the whole baseline, unchanged.
- Each new check falsified once.

**Watch for:**
- **This rewrites the most-tested path in the product.** The ledger's witness, the ring, the
  rollback's re-read and `history_sealed` are not incidental. Move them, do not simplify them.
- **A frame nobody can extend is the failure mode.** Check it against C1, M1 and L1 before writing
  it.
- **The plugin's hash changes with no version bump,** so `install-plugin` and a Krita restart still
  apply.

---

## C1: Fills

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (Authoring), decisions
1, 3; `ARCHITECTURE.md` *The verification core*, *Protection, selections and masks*, *Painting*,
*Reference* (K2, K4, K5, K9, K10).

- **Measure first,** in a harness document: `Node.paintPath(path, "None", "ForegroundColor")`. It
  should be a painter fill with no dabs, one undo step labelled "Scripted Brush Stroke", confined by
  the selection, honouring opacity and blend. Sources: `libs/libkis/PaintingResources.cpp:17-58`,
  `libs/image/kis_painter.cc:1380-1386,1470-1555`,
  `libs/ui/tool/strokes/kis_painter_based_stroke_strategy.cpp:404-465`,
  `libs/ui/tool/kis_resources_snapshot.cpp:213-214,322-327`.
- **If it disappoints,** the fallback is `fill_selection_foreground_color_opacity`
  (`libs/ui/kis_selection_manager.cc:149-164`): one step, "Flood Fill Layer", on the active node,
  with no selection filling the whole image.
- **`krita_paint_fill`**, on the frame: a `selection`, `rect`, `ellipse`, `polygon` or closed
  `path`; colour, opacity, blend, alpha lock, verify.
  - Feathered selection coverage holds; a fill over a selection's bounds is confined by it (K10).
  - A shape off the canvas is refused, never clipped. `selection` with no selection is refused.
  - The current preset stays only if the measurement shows it cannot matter: run the fill under a
    `paintbrush`, a MyPaint and a masked-brush preset, because `paintPath` snapshots the view's
    preset. If the result differs, the fill activates one fixed stock preset, in K3's order, and
    says so.
  - The reach is the shape's bounds plus an antialias margin.
  - The receipt has the stroke's shape: `changed_bounds_px`, `layer_bounds_px`, `verification`, one
    undo step.
  - A `paint.fill` capability, and a `destructiveHint: true`: a fill overwrites.
- **Docs.**
  - `USER-GUIDE.md`: *The core loop*; a line on when a fill beats a stroke.
  - `ARCHITECTURE.md`: *Painting*, the matrix, the baseline.
  - Server instructions, the README's tool list, `CHANGELOG.md`: 0.20.0.

**Gates:**
- `uv run scripts/verify.py`, with these tests: every shape, the refusals, the reach, both scopes,
  and the output schema over an edge fill.
- `probe`: a polygon fill under a feathered selection; a leak refused and undone under a binary
  allowed mask; opacity and blend applied; alpha lock inside a silhouette; one undo step; the edges
  as in R1; the same fill under a second preset, with equal bytes.
- Each new check falsified once.

**Watch for:**
- **Bad style strings fall back silently** (`PaintingResources.cpp:17-58`). Read the effect, not the
  call.
- **Set colour, opacity, blend and alpha lock per call** (K3), without activating a preset.
- **The inset still applies:** an antialiased shape on an allowed mask's own edge touches forbidden
  pixels.
- **Flood fill from a seed is out** (decision 18).

---

## M1: Transparency masks

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (its answers), decisions
1, 3, 14; `ARCHITECTURE.md` *The invariants* (1, 4, 5), *Documents*, *Reads, and K46*, *Protection,
selections and masks*, *The verification core*, *Painting*, *The undo ledger and history*, *The
save*.

- **Measure first,** in a harness document: what a new mask starts as
  (`libs/libkis/TransparencyMask.cpp:20-23` suggests empty, hiding the layer), that `paintPath`
  paints on one (`libs/libkis/Node.cpp:849-859`, `libs/image/kis_mask.cc:223`), that white reveals
  (`libs/image/kis_pixel_selection.cpp:103`), and what `Node.pixelData` returns on a mask.
- **`krita_layer_create type: transparency_mask`** goes live, with `coverage` `all`, `none` or
  `selection`, set before attaching, so it is one undo step. `setSelection` has no undo and adopts
  its object uncopied: pass a duplicate, and never call it on an attached mask. `None` crashes
  (`libs/image/kis_mask.cc:252-259`).
  - The parent is a paint layer, and it and every ancestor are unprotected (decision 14).
- **Strokes and fills take a mask target,** with `reveal` or `hide` and an amount for partial
  coverage, in place of a colour.
- **`krita_capture` reads a mask alone,** as a grey image. The composite is read as it is today.
- **`krita_layer_update`** takes `visible` and `name` on masks (`layer_update.py:278-281` refuses
  them today), so a mask can be disabled and enabled.
- **Invariant 1.** Its text in `CLAUDE.md` and `ARCHITECTURE.md`, and the scan in
  `tests/plugin/test_source_scans.py`, name the mask's one `setSelection` site. The name alone
  cannot hold it: `Document.setSelection` (`krita_adapter/selections.py:13,40`) and the harness's
  mask (`krita_adapter/documents.py:304`) use it too. So the AST test holds the function and its
  receiver, as it does for `_from_mask`, with the other sites listed.
- **Docs.**
  - `CLAUDE.md`: invariant 1.
  - `USER-GUIDE.md`: *The core loop*, the limits.
  - `ARCHITECTURE.md`: the invariants, *Protection, selections and masks*, the placeholder tables,
    the baseline.
  - Server instructions, `CHANGELOG.md`: 0.21.0.

**Gates:**
- `uv run scripts/verify.py`, with these tests: coverage, the protected-ancestor refusals, the
  channel count through the frame, a mask read, and the scan for the mask's site and its receiver.
- `probe`: a mask from a selection; reveal and hide, partial, by stroke and fill; a mask-only
  capture; the composite beside it; disable and enable; a leak undone; one undo step each; a KRA
  round trip; an ORA save listing the mask in `expected_losses`.
- Each new check falsified once.

**Watch for:**
- **A mask reads one byte per pixel.** Every BGRA assumption is a bug here: `verification.changes`,
  `crop`, the witness.
- **`selection()` is live,** so an edit through it bypasses undo. Never hold it.
- **Existing masks are protected at open** (`opening.py:120`), and that must stay true.
- **MyPaint presets refuse non-RGBA devices** (`libs/libkis/Node.cpp:852-856`). A fill on a mask
  must not depend on whichever preset the owner left current; C1's measurement decides how.
- **`reach()` counts a transparency mask as bounded;** confirm it, because a mask's own change now
  has a target.

---

## X1: Architecture review: the frame and its first two tools

**Read:** everything: every session's code and tests so far, cold, against the feature file and this
plan.

- Write `docs/spec/REVIEW-<date>.md` from the workflow's template: findings only, no product code,
  no version. The read is done twice, the second time cold, and a finding is kept only once verified
  on the code path.
- **Attack in particular:** the markers against what each op really does; whether `uncertain` stays
  rare in the probe's own runs; the frame against E1, L1, B1, T1 and S1; the instructions' budget.
- In plan mode the owner picks which findings become scope: an amendment to a later block, or an
  inserted session.

**Gates:** `verify` and `probe` as found, recorded in the review's baseline.

**Watch for:** a review is evidence, and a block is scope. Neither is the other.

---

## E1: Tapers

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (Authoring, its
answers), decision 16; `ARCHITECTURE.md` *Painting*, *Reads, and K46* (Resources), *Testing
strategy* (Hypotheses), *Reference* (K3, K4, K30, K36).

- **The go/no-go,** on a throwaway document, before any product code. Activate a preset, then
  `fromXML` with a Distance curve on size, paint, restore. Run short, long and curved strokes.
  **Go** requires all of:
  - the taper is real, in the pixels, at both ends and at an interior knot;
  - the preset comes back, by digest;
  - the dirty flag clears (`reload_preset_action` is the likely route; `Preset::fromXML` sets it and
    libkis cannot clear it);
  - no resource file moves on disk;
  - the owner's brush state comes back whole.

  Sources: `libs/libkis/Preset.cpp:35-46`, `libs/image/brushengine/kis_paintop_preset.cpp:323-364`,
  `libs/ui/kis_paintop_box.cc:634-641` (activate first: a different preset reloads from disk),
  `libs/libkis/Resource.cpp:118`. The XML:
  `plugins/paintops/libpaintop/KisKritaSensorPack.cpp:239-271`, a `SizeSensor` param holding
  `<params id="distance" periodic="0" length="300"><curve>0,1;1,0;</curve></params>`, with
  `PressureSize`, `SizeUseCurve` and `SizeUseSameCurve`. Distance accumulates across one `paintPath`
  (`libs/image/kis_painter.cc:1390`).
- **On go:** `dynamics` on `krita_paint_stroke`: size and opacity curves over normalised arc length,
  with interior knots. `length` comes from the path's arc length. `paintbrush` engine only, reported
  in the receipt. A `stroke.dynamics` capability.
- **On no-go:** `stroke.dynamics` stays false, the limitation is published, the sensors go to the
  backlog, and the session ships documentation alone, with no version.
- **Either way:** `stroke.per_point_input` stays false. No joined segments or flat shapes are
  labelled as strokes (decision 16).
- **Docs.**
  - `USER-GUIDE.md`: what `dynamics` is and is not.
  - `ARCHITECTURE.md`: *Painting*, the matrix, H2's row, *Reference*.
  - Server instructions, `CHANGELOG.md`: 0.22.0 on go.

**Gates:**
- `uv run scripts/verify.py`, with these tests: curve shapes, the XML edit and its restore, the
  refusals by engine, the receipt.
- `probe`: width measured along a tapered stroke, short, long and curved; an interior knot; the
  preset's digest and dirty state after; the brush state after; a leak undone with the preset
  restored.
- Each new check falsified once.

**Watch for:**
- **This path must not feed `activated`,** which would vouch for a bad restore forever
  (`painting.py:86-88,551`).
- **The fingerprint and `_taken` run on a preset this path changes.** Order them so the checks still
  mean something.
- **The owner must not edit presets while an agent paints,** and now the agent's stroke does, in
  memory. Keep the window as short as one job.
- **A Krita crash mid-stroke leaves only an in-memory change;** nothing on disk moved. Confirm it.
- **Dirty presets differ by setting.** Krita's "save dirty presets" option changes what activation
  reloads.
- **The bounded probe stays bounded.** A no-go is a result.

---

## L1: Layers

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (its answers), decisions
1, 3, 13; `ARCHITECTURE.md` *The invariants* (4, 5), *Registry, lease and document state*,
*Protection, selections and masks*, *The verification core*, *The undo ledger and history*,
*Reference* (K22, K42).

- **`krita_layer_duplicate`,** layers and groups, by `Node.duplicate()` (`libs/libkis/Node.cpp:645`;
  `clone()` at `:150` gives a node with no image) and `addChildNode`, one undo step. Hidden by
  default, set before attaching, so the composite does not change.
  - A protected source is allowed (decision 13). The copy carries `derived_from`; a group reports an
    `id_map` of every copied node.
  - Proposed hint: `destructiveHint: false`, additive. Confirm at plan time.
- **`krita_layer_reorder`,** `remove` then `addChildNode`, two undo steps, stated in the receipt.
  Into a group too, which is how grouping works. Verified over the full composite.
  - Refused for a node that is protected or holds a protected descendant.
  - Proposed hint: `destructiveHint: true`.
- **`krita_layer_remove`,** unprotected nodes only, one undo step, verified. Proposed hint:
  `destructiveHint: true`.
- **Docs.**
  - `USER-GUIDE.md`: *The core loop*.
  - `ARCHITECTURE.md`: *The undo ledger and history*, the matrix, the baseline.
  - Server instructions, the README's tool list, `CHANGELOG.md`: 0.23.0.

**Gates:**
- `uv run scripts/verify.py`, with these tests: each refusal, parity for each new pair, `id_map`
  over a nested group, and a two-step rollback.
- `probe`: duplicate, trial and remove on a harness document; a reorder that would change the
  composite outside the allowed mask, refused and undone; a group built by reorder;
  `krita_history_step` over each; protected layers' bytes unchanged throughout.
- Each new check falsified once.

**Watch for:**
- **Two undo steps from one op.** "A rollback undoes only the steps its operation pushed": a failure
  between them must still confirm, and `history.LABELS` needs each English label, measured.
- **`setChildNodes` has no undo.** Never use it for a reorder
  (`libs/image/kis_node_facade.cpp:92-125`).
- **A detached node's wrapper.** Measure that `addChildNode` takes it back after `remove`.
- **A copied group's masks** are protected at open in their source, and are the agent's own as
  copies.

---

## B1: Document duplicate

**Read:** `FEATURE-recovery-and-construction.md` decisions 1, 3, 12; `ARCHITECTURE.md` *The
invariants* (2, 3, 4), *Documents*, *Registry, lease and document state*, *Previews and the lazy
baseline*, *The save*, *The server*.

- **`krita_document_duplicate`** to a new `.kra` path inside a root. `.ora` is refused: ids do not
  persist (K39).
  - A verified save, through the save's own two ops.
  - The placed file opened directly, so a branch is one file. `source_path`, `source_sha256` and
    `source_stat` come from the original, so `baseline_untouched` keeps meaning.
  - Protection, the allowed mask and the flags are copied equal, never looser. History starts empty.
  - Its own baseline: `resolve_close` removes a baseline (`tools/documents.py:173-176`). The lazy
    baseline hashes `handle.path` against `handle.source_sha256` (`previews.py:115-120`), which
    would refuse a branch, because its file is not the source. So `Handle` keeps the opened file's
    own hash apart from the source's, and `_as_opened` reads that one.
  - A branch of a created document has no source: both source fields stay null, the opened file's
    hash serves the baseline, and `_as_opened` stops requiring a source.
  - Proposed hint: `destructiveHint: false`, additive. Confirm at plan time.
- **Comparing branches** needs no new tool: `krita_preview_render` takes a `document_id` per source.
- **Docs.**
  - `USER-GUIDE.md`: *The core loop*.
  - `ARCHITECTURE.md`: *Documents*, *The save*, *The server*, the matrix, the baseline.
  - Server instructions, the README's tool list, `CHANGELOG.md`: 0.24.0.

**Gates:**
- `uv run scripts/verify.py`, with these tests: inheritance, each refusal, the `.ora` refusal, each
  op's failure with its outcome, and a branch's baseline read, from a working copy and from a
  created document.
- `probe`: a branch painted differently from its source; both in one preview, each with its own
  `baseline_id`; each closed without touching the other's baseline; protection inherited and
  unloosened; invariant 2's hash checks.
- Each new check falsified once.

**Watch for:**
- **It is a three-op tool, and the finish is server-side,** so the reopen is its own job.
  `RECEIPTS`' completeness test and the derived-id scheme (`tools/saving.py:100-102`) widen. A crash
  between ops reports `uncertain`.
- **Layer ids persist through KRA only (K39).** Confirm it for every node type protection names.
- **The source stays dirty as it was.** A branch must not clear its source's dirt.

---

## T1: Translate

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (its answers), decisions
3, 15; `ARCHITECTURE.md` *The verification core* (Reach), *The undo ledger and history*; from git
history, `git show 04e9f6c:docs/spec/PDD.md` Q13.

- **The bounded probe, first, on a throwaway document.** `createTransformMask` and
  `TransformMask.fromXML` exist in the 5.3.4.1 stubs (`krita.pyi:174,540-543`). `fromXML` runs its
  own command stroke, attached or not (`libs/libkis/TransformMask.cpp:75-115`), and `addChildNode`
  pushes another, so expect two undo steps, stated in the receipt as L1's reorder does (decision
  15). It does not wait, so `waitForDone()` follows it. A native route must show native undo of
  every step, a confirmed rollback and a KRA round trip.
- **If it holds,** `krita_layer_transform` with a `translate` operation, on unprotected layers,
  verified in full. Proposed hint: `destructiveHint: true`.
- **If it does not,** translate waits for Phase 3's checkpoints, it goes to the backlog with what
  was measured, and T1 ships no version. A non-undoable `Node.move` compensated inside one call is
  not recovery.
- **Docs.** `USER-GUIDE.md`; `ARCHITECTURE.md`: *The verification core*, the matrix, the baseline;
  server instructions; `CHANGELOG.md`: 0.25.0 if it ships.

**Gates:**
- `uv run scripts/verify.py`, with tests for the route chosen.
- `probe`: a translate, its leak undone, its undo, a KRA round trip, an ORA save's
  `expected_losses`.
- Each new check falsified once.

**Watch for:**
- **A stroke under a translating transform mask lands displaced.** The receipt and the guide must
  say where paint goes.
- **`transform_mask` is a reach reason** (`bridge_core/verification.py:34`), so such a layer needs
  `verify: "full"`. Real use already paints in full scope.
- **ORA bakes or drops mask nodes.** It must fail or be listed, never pass silently.
- **`Node.move` has no undo,** and masks may not move with it. It is not the fallback.

---

## S1: Scale, rotate, shear

Cut first if the round runs long: useful, not yet proven by real use.

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (its answers), decisions
1, 3; `ARCHITECTURE.md` *The verification core*, *The undo ledger and history*.

- **`krita_layer_transform`,** created here, or extended if T1 shipped it, on unprotected layers,
  one operation per call, one undo step, verified in full: `scaleNode`, `rotateNode`, `shearNode`
  (`libs/libkis/Node.cpp:695-743`, `libs/image/kis_image.cc:1000-1296`). Proposed hint:
  `destructiveHint: true`; resampling loses pixels.
- **The filter name is validated by the tool,** because `scaleNode` silently falls back to Bicubic.
- **The guide names duplicating first** (L1) as the reversible route.
- **Docs.** `USER-GUIDE.md`; `ARCHITECTURE.md`: *The undo ledger and history*, the matrix, the
  baseline; server instructions; `CHANGELOG.md`: 0.26.0.

**Gates:**
- `uv run scripts/verify.py`, with these tests: each refusal, parity, and the filter whitelist.
- `probe`: each operation, a leak undone, `krita_history_step` over each, protected bytes unchanged.
- Each new check falsified once.

**Watch for:**
- **Sizes are relative to exact bounds** (`Node.cpp:704`), and rotation pivots on their centre
  (`kis_image.cc:1145-1167`).
- **These are silent no-ops on masks.** Refuse a mask target.
- **`history.LABELS` needs each English label,** measured.

---

## X2: Architecture review: construction

**Read:** everything: every session's code and tests so far, cold, against the feature file and this
plan.

- Write `docs/spec/REVIEW-<date>.md`, as X1 did: findings only, no product code, no version.
- **Attack in particular:** every new tool against invariants 1, 2, 4, 5 and 9; each op's marker;
  hints against each new tool's worst behaviour; the capability matrix; the instructions' budget.
- In plan mode the owner picks which findings become scope.

**Gates:** `verify` and `probe` as found, recorded in the review's baseline.

**Watch for:** X1's findings the owner left open; check they still hold.

---

## V1: Re-measure, docs, full run, close the round

**Read:** `FEATURE-recovery-and-construction.md` decision 18; `ARCHITECTURE.md` whole;
`docs/USER-GUIDE.md`; `docs/BACKLOG.md`; every done-note in this file.

- **Re-measure representative workflows** after the hints and fills, from the journal and the
  client's own records, as counts and timings. That reopens or closes the batch question (decision
  18).
- **Docs.** `ARCHITECTURE.md` and `USER-GUIDE.md` read through whole; "Phase 1" language corrected
  where it is no longer true; the README; `CHANGELOG.md`: 0.27.0; the baseline.
- **The close,** as the workflow says: the release commit with the last done-note, then
  `docs: close round 2` deleting `docs/spec/`'s files, and the handoff says no round is in progress.
- **The backlog.** Anything left open moves there, with checks nobody did by hand.

**Gates:**
- `uv run scripts/verify.py`.
- `probe`, on a freshly restarted Krita, with 0 documents open, and the whole baseline recorded.

**Watch for:**
- **The review follows the close,** so its findings go in the review commit's message and the
  handoff.
- **A release restarts the MCP client too.** Tell the owner before the restart.
