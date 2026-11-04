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
| R3 | Krita's own modified state, and the close guard | — (R2's review) | **0.19.0** |
| D1 | Discovery: colours, limits, ranges, finite numbers | 9, 11 | **0.20.0** |
| F1 | One verified-mutation frame, parity tests | 5, 10 | **0.20.1** |
| C1 | `krita_paint_fill` | 1, 3 | **0.21.0** |
| M1 | Transparency masks | 1, 3, 14 | **0.22.0** |
| X1 | Architecture review: the frame and its first two tools | all | — |
| E1 | Taper probe, then the proven subset | 16 | **0.23.0** |
| L1 | Layers: duplicate, reorder, remove, group | 1, 3, 13 | **0.24.0** |
| B1 | Document duplicate | 1, 3, 12 | **0.25.0** |
| T1 | Translate, on a native route or not at all | 1, 15 | **0.26.0** |
| S1 | Scale, rotate, shear; cut first if the round runs long | 1, 3 | **0.27.0** |
| X2 | Architecture review: construction | all | — |
| V1 | Re-measure, docs, full run, close the round | 18 | **0.28.0** |

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

**Done (2026-11-03, 0.18.0).**
- **Decided with the user at the start:**
  - **Whether `default_tools_approval_mode` was set:** the owner did not know. Codex's config holds
    no such key under `[mcp_servers.krita-art]`, so the gate ran under Codex's default review.
  - **The by-hand gate:** the owner would run the Codex session.
  - **The plan,** approved in plan mode, including where the clock starts.
- **Hints.** Five schema files set `destructiveHint: false`, and `HINTS` in `tests/test_tools.py`
  holds all four hints of all 19 tools.
- **Timing.**
  - `tools.build`'s `call` stamps the arrival before `CALLS`, and `Run` and `ToolCall` carry it as
    `started`.
  - `journaled` writes `elapsed_ms` through `record` and `Journal.finished`.
  - `Finished.elapsed_ms` is read with `.get`, so an older line reads `None`.
  - A line `krita_operation_get` writes, for a call that came back running, has `null`.
  - The journal's `VERSION` stays 2.
- **Hamming.**
  - `imaging.FILTERS` gains `hamming`, and so do both schemas' five `filter` enums each.
  - A test holds every enum to `FILTERS`.
  - The probe's `_hamming` renders the icon fixture with `hamming` and with `bicubic`.
- **Docs.**
  - The guide gains the hints table and Codex's setting.
  - ARCHITECTURE gains the hints, the journal's `elapsed_ms` and the filter list, and marks
    Codex's limits as measured at 0.15.0.
  - Two backlog items.
- **Amendments:**
  - **The clock starts on arrival, before the lock,** so the lock wait and the input check count.
    The block left the start open. Amended at plan time, with the user.
  - **A parity test between the filter enums and `FILTERS`,** which the block did not list. Amended
    at plan time, with the user.
  - **Codex's schema sizes are not re-measured.** They came from a scratchpad port at 0.15.0, and
    R1 had already changed every output since. They are labelled, and in the backlog. The
    session's own finding.
  - **The gate's Codex session was a long one, not a short one.** It ran on 0.18.0's code before
    the docs were written, because a client's `serve` imports this checkout as it stands. The
    session's own finding; in the backlog.
- **Measured,** on Krita 5.3.4.1 and Codex, from the client's own records and the journal, as counts
  and timings only:
  - **The calls:** 911 over about two hours. 81 went to four of the five, 695 were destructive and
    135 were reads. `krita_document_create` was not called.
  - **The four:** Codex's wall clock met the server's `elapsed_ms` within a median of 3–4 ms. They
    took 0.4 minutes of wall clock, none of it outside the server.
  - **The destructive calls:** each spent a median of 2.8–3.0 s outside the server (selections
    2.89 s, strokes 2.80 s). They took 41.9 minutes of wall clock, 2.0 of them in the server.
  - **The reads:** Codex's wall clock equals its tool time.
  - **The inference held.** Changing only the hint removed the cost from those tools. At this
    session's rate the five saved about 4 minutes; the rest is the owner's setting.
  - **The server's time:** Codex's own tool time and `elapsed_ms` agree within a few milliseconds.
  - **The probe's Hamming cell** differs from bicubic in 765 pixels of the 128 px icon, by up to
    255.
- **Checked by hand:** the owner's Codex session above.
- **Falsified:**
  - **Eight unit checks,** each failing at its own step: the hint table, the read-back, the lock
    wait, the poll's `null`, an older line, the enum parity, and the Hamming capture and preview.
  - **The probe's Hamming check,** comparing a cell with itself: it alone failed, 142 PASS, 1 FAIL.
    A first attempt met a Krita dialog left open at start, and does not count.
- **Numbers:** 739 server tests (+7), 781 plugin tests (0), probe 143 PASS (+1), 0 FAIL, 23
  MEASURED, about 122 s with 0 documents open. 19 tools, 19 schema files, 30 error codes, 31 ops,
  instructions 3,970 characters.
- **Review (`/code-review high`), 7 findings: 7 fixed and 0 skipped.**
  - **The guide's Codex snippet repeated the server's TOML table.** Pasted as shown, it would
    define `[mcp_servers.krita-art]` twice, which TOML refuses. It is now one line for the existing
    block.
  - **The guide said additive calls carried no delay in both sessions.** On 0.16.0 they were still
    destructive and carried about 2 s; it now says so.
  - **The hints table said reads change nothing.** It now says they change no document, and that
    captures and previews write PNGs.
  - **ARCHITECTURE named `_checked` as what reads `readOnlyHint`.** It is `tools.build`.
  - **A finished line's `elapsed_ms` was taken unchecked.** A value that is not a whole number now
    reads as `None`, and the line still settles.
  - **The probe opened the icon fixture twice.** The Hamming check now runs in `_icons`'s document,
    and a failed open fails both checks.
  - **The lock-wait test depended on `_client_name`'s place.** It now holds a stand-in for `CALLS`
    that says when a call starts to wait.
  - **The owner inserted R3,** from the Codex agent's report on 0.18.0: after a verified save the
    bridge says `dirty: false` while Krita's own modified flag stays set. D1 and every later
    version shift by one.
  - **The Codex agent's second report amended R3's block:** `refuse` closes over changes only
    Krita holds, because close reads the bridge's flag and then clears Krita's. The block now
    guards the close, measures PNG, KRA and ORA working copies, and asks how `refuse` changes. Two
    backlog items take the rest: wrap translation, proposed again, and target identity in
    receipts.
  - **The Codex agent's four refusals in R2's session** were all D1's ground: a sampled 0–255
    colour sent as a stroke's 0–1, a native capture given a `background` twice, and a brush size
    over 1000.
  - **Falsified:** the lock-wait test, with the clock stamped inside the lock; the bad-value read,
    with its guard removed. Each failed at its own step.
  - **Numbers after the review:** 741 server tests, 781 plugin tests, probe 143 PASS, 0 FAIL, 23
    MEASURED, about 122 s with 0 documents open.

---

## R3: Krita's own modified state

**Read:** `ARCHITECTURE.md` *Registry, lease and document state* (Dirty), *Documents*, *The save*,
and K39 and K45 in *Reference*; `docs/USER-GUIDE.md` *The core loop* (save and close).

The owner inserted this session at R2's review, from the Codex agent's report on 0.18.0. After a
verified save the bridge said `dirty: false`, and Krita then asked to save the tab. The live pixels
matched the saved KRA, so nothing was lost, but the state the agent read did not guarantee a clean
handoff. Its second report, read at the same review, added the close below and a regression matrix;
**amended at R2's review, with the owner.**

- **The cause, as R2's review read it.**
  - `dirty` is the bridge's own flag: a bridge change since the last verified save
    (`registry.py:66-68`, cleared at `saving.py:209`).
  - Krita's modified flag is another, and `exportImage` never clears it (K45). After every verified
    save the two disagree, and no tool reports Krita's.
  - A change made by hand sets Krita's flag alone.
  - The document keeps pointing at its working copy (K39), so a Krita save from that prompt writes
    the working copy, not the saved file. For a PNG working copy that would flatten the layers into
    it.
  - **The close guard reads the bridge's flag alone, then clears Krita's.** `dirty_policy:
    "refuse"` checks `handle.dirty` (`bridge_core/documents.py:67`), and `port.close` calls
    `setModified(False)` before closing (`krita_adapter/documents.py:384`). So `refuse` closes,
    silently, over any change only Krita holds. The agent saw it close a document Krita had just
    asked to save. This is the part that can lose work.
- **Measure first, live, on harness documents,** for PNG, KRA and ORA working copies:
  - Krita's `modified()` after a verified save, after new paint following it, and after a refused
    or failed save;
  - what a selection-only or view-only change does to each flag;
  - what a Krita save over the working copy does to the lazy baseline's hash check and to the
    handle;
  - whether any harness op can make a change only Krita sees, so the probe can test the guard.
- **Report it.**
  - Inspect and list gain Krita's own flag beside `dirty`, named so the two cannot be confused.
  - The save's receipt says where it wrote and that the live document still points at its working
    copy, and whether Krita still holds it modified. The save stays a copy (K39) unless the owner
    chooses otherwise.
- **Guard the close.** `refuse` refuses any unsaved change Krita holds, not only the bridge's.
- **Ask at the start:**
  - **After a verified save, clear Krita's flag, or only report it?** The Codex agent advises
    against forcing a clean flag: a verified copy and a clean live document are different facts.
  - **Does `refuse` change meaning, or does a new value carry the native check?** A change of
    meaning moves `api_version` to 0.3.0 here, and D1's move becomes 0.4.0 (decision 9).
  - **May a separately named policy close after a verified save** while Krita still holds the
    document modified?
- **Docs.**
  - `USER-GUIDE.md`: *The core loop* (save and close), *Every error code* if close changes.
  - `ARCHITECTURE.md`: *Registry, lease and document state* (Dirty), *The save*.
  - `CHANGELOG.md`: 0.19.0.

**Gates:**
- `uv run scripts/verify.py`, with these tests:
  - the fake models Krita's flag apart from `dirty`;
  - a verified save reports both flags as they are, and a refused or failed one clears neither;
  - a change only Krita holds shows in its flag alone, and `refuse` refuses it;
  - new paint after a save shows in both, and `refuse` refuses it.
- `probe`, with these checks:
  - a verified save, then list and inspect, report both flags as Krita holds them, for a PNG, a KRA
    and an ORA working copy;
  - `refuse` refuses a change only Krita holds, if a harness op can make one; otherwise this moves
    to *Checked by hand*.
- **By hand, with the owner, on a harness document:** after a verified save, whether a tab close,
  Close All and quit each prompt, and whether that agrees with what the tools report. Cancel every
  prompt.
- Each new check falsified once.

**Watch for:**
- **`dirty` keeps its name and meaning.** An added field moves no `api_version` (decision 9);
  changing what `dirty` means would.
- **The working copy is the agent's, never an accepted source,** so invariant 2 holds either way.
  What a hand save breaks is the baseline's hash check: measure it, do not assume it.
- **Every live run is on harness documents.** The owner's documents are never saved, cleared or
  closed.
- **The source's hash stays exact.** No path fix may redirect a write to an accepted source.
- **The agent's evidence stays outside the repository,** and so do its file and folder names.

**Done (2026-11-03, 0.19.0).**
- **Decided with the owner at the start:**
  - **Krita's flag is only reported,** never cleared after a verified save.
  - **`refuse` changes meaning,** so `api_version` moves to 0.3.0 and D1's move to 0.4.0.
  - **No new policy.** After a verified save, `refuse` closes while the live document still matches
    what that save compared, and refuses otherwise.
  - **The plan,** approved in plan mode, including the name `krita_modified`.
- **Measured first, live, on 0.18.0.** A scratchpad driver read Krita's flag as
  `bridge.unsaved_documents`' count, with one harness document open at a time:
  - **PNG, KRA and ORA working copies alike:** 0 at the open; 1 after a layer and a stroke; still 1
    after a verified save, with `dirty` false; 1 after a stroke after it, a refused save
    (`FILE_EXISTS`), a failed one (`SAVE_VERIFY_FAILED`) and a second verified save.
  - **On fresh copies:** a selection set it, with `dirty`; a view change left both clear; an opacity
    change left it clear with `dirty` set; `harness.add_node` set it alone; a layer then an undo
    cleared it, with `dirty` still set. Activating a protected layer was refused, so no cell.
  - **A created document** is not modified at birth, so a create records no state.
  - **Krita's source agrees:** `setImageModified` works the flag out from the undo stack's clean
    state, which only a real save marks clean.
- **Report.**
  - `describe` gains `modified`, and list and inspect gain `krita_modified`.
  - The finish returns `dirty`, `krita_modified` and `document_path`, and the save's data carries
    them.
- **Guard.**
  - `documents._refuse_unsaved` refuses on `dirty`, then on Krita's flag unless
    `saving.matches_saved` holds: composite, tree nodes, then the save's compared pixel ranges.
  - `Handle.saved_state` is the save's own read, kept when the finish clears dirt.
  - Both refusals name both flags.
- **`api_version` 0.3.0:** `errors.API_VERSION`, every schema through `amend_schemas.py`, and
  close's description.
- **Probe.**
  - `_only_ours_unsaved` counts `krita_modified`.
  - `probe/modified.py` checks each format's flags after a verified save, and a change only Krita
    holds.
  - The round-trip document's last check now expects `refuse` to refuse the filter layer only
    Krita holds.
  - H4's working copy gains a layer of its own, so its `refuse` close compares 8192², timed as
    MEASURED.
  - `opening.harness_export` is public, for the new module.
- **Docs.**
  - ARCHITECTURE gains Krita's flag, the close and the saved state, the measured facts, and the
    baseline.
  - The guide gains the receipt's fields, the close, the `DOCUMENT_DIRTY` row and doctor's count.
  - Two backlog items.
- **Amendments:**
  - **D1's `api_version` move is 0.4.0,** as R3's block said it would be; recorded in D1's block.
  - **The probe tests the guard.** `harness.add_node` makes a change only Krita holds, so nothing
    moved to *Checked by hand*.
  - **A property write leaves Krita's flag clear.** The session's own finding; in the backlog,
    since marking the flag is a different choice from reporting it.
- **Checked by hand, with the owner, on harness documents:**
  - **After a verified save:** a tab close, Close All, and quit with three documents open each asked
    to save. Each was cancelled. The tools said `krita_modified: true`.
  - **Krita's own Save on a KRA working copy** saved with no dialog and a `~` backup. The handle kept
    its path, with `dirty` true and `krita_modified` false. The working copy no longer hashed to
    its source, so the lazy baseline answered `SOURCE_HASH_MISMATCH`. `refuse` refused on `dirty`,
    and `discard` closed it with `baseline_untouched: true`.
  - **Save on a PNG working copy** opened the PNG export dialog: it warned that the image would
    lose information, with "Also save as a Krita file" ticked. Cancelled.
  - **Two attempts do not count.** In the first sitting, the documents were closed before the quit.
    A driver run then removed its own folder with documents open. Each was redone.
- **Falsified:**
  - **The close guard turned off:** the Krita-only test, the four hand-change cases and the
    before-finish test failed.
  - **Each comparison removed in turn:** its own case alone failed, the composite with the layer
    style, the tree with the new node, the pixels with the hidden stroke.
  - **Seven more unit checks, each failing at its own step:**
    - the details without `krita_modified`;
    - the finish reporting the flag false;
    - a failed finish clearing dirt;
    - `refuse` never refusing;
    - the state read at the finish;
    - the state kept when dirt stays;
    - the receipt's text.
  - **The sweep counting `dirty`:** the saved case failed.
  - **The probe's five new or changed checks, broken together:** 142 PASS and 5 FAIL, exactly those.
- **Numbers:** 742 server tests (+1), 791 plugin tests (+10), probe 147 PASS (+4), 0 FAIL, 24
  MEASURED (+1), about 125 s with 0 documents open. 19 tools, 19 schema files, 30 error codes, 31
  ops, instructions 3,970 characters. The 8192² comparison took 0.4 s.
- **Review (`/code-review high`), 6 findings: 6 fixed and 0 skipped.**
  - **An ORA save kept no pixels for what ORA drops.** Its state held only the stored layers'
    projections, so a hand edit to a hidden layer's mask closed under `refuse`. An ORA save now
    hashes every node's own pixels; a KRA save already did.
  - **The guide said `refuse` catches any hand change.** It now names what the close compares, and
    that guides, and perhaps the global selection alone, are not seen.
  - **H4's save changed its conditions unannounced.** Its MEASURED line now names the agent's empty
    layer.
  - **No unit test held the ORA compare.** The hand-change cases now run for KRA and ORA, with a
    mask edit, and a saved KRA and ORA close under `refuse`.
  - **`Pending` kept the composite's hash twice.** It now lives in the state alone.
  - **`probe/modified.py` repeated the list lookup.** `common.listed_entry` serves it and
    `document_dirty`.
  - **Falsified:** the ORA state limited to its pairs, where only the ORA mask case failed; the
    close never matching, where both saved closes failed.
  - **Numbers after the review:** 742 server tests, 799 plugin tests, probe 147 PASS, 0 FAIL, 24
    MEASURED, about 125 s with 0 documents open.

---

## D1: Discovery

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (Input and schema
discoverability), decisions 9, 11; `ARCHITECTURE.md` *The tool contract* (Schemas are data, Which
forms reach Codex, The instructions), *Reads, and K46* (Capture, Sample); `docs/USER-GUIDE.md`
*Phase 1's limits*.

- **Colours.** `krita_sample` gains `color`, the exact shape `brush.color` takes, and `rgba` becomes
  `rgba_255`. `api_version` moves to 0.4.0 (decision 9). A sample-to-stroke example in the schema.
  **Amended at R3, with the owner:** R3 changed what `refuse` means and took 0.3.0.
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
  - `CHANGELOG.md`: 0.20.0.

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

**Done (2026-11-04, 0.20.0).**
- **Decided with the owner in plan mode:**
  - **`color`'s alpha is always 1.** It is the paintable colour; `rgba_255` keeps the sampled
    alpha. `color` is null with no colour (alpha 0) or outside sRGB, as `hex` and `lab` are.
  - **Codex's limits are measured by a port of its renderer in `tests/support`,** pinned to a Codex
    tag. This reverses 14a's "no port in the repository", because this block's gate asks `verify`
    to test the limits.
  - **The plan,** approved in plan mode, including the limits' names.
- **Colours.** `colour.disc` gives `rgba_255` and `color`, `{space: srgb, rgba: [r/255, g/255, b/255,
  1]}` from the unrounded alpha-weighted mean. The sample schema, its example and the tool
  description carry both.
- **Limits.** `LIMITS` gains `brush_size_px` `{min: 1, max: 1000}`, `resource_page_size` 100 and
  `stroke_overhang_size_fraction` 0.5. The plugin's `_on_canvas` now reads the new
  `OVERHANG_OF_SIZE`, and a test holds each limit to its plugin constant and its schema bound.
- **Descriptions.** Every input property with both bounds (20, across eight tools) states them as
  "A to B", held by a test. `points`, `rotation_deg`, `cursor`, `input_fallback`, `smooth`,
  `verify`, the presets and capture's fields have theirs too, as do the new outputs.
- **Capture's two forms.** `dependentSchemas.scale` refuses `background` and `greyscale` at scale
  1, and the selection rule nests in the target rule's `else`. `_capture_rules` loses those two
  branches. The tool description gives one example of each form.
- **Not-finite numbers.** `_checked` walks every tool's arguments beside the schema, with
  `dispatch.finite` and `not_finite`. The stroke's `_unbounded` and preview's whole-argument check
  went; the stroke keeps its check on smoothed control points, and preview its echo check.
  - **Measured:** mcp's stdio parser reads `NaN`, `Infinity` and `1e400` as floats, and a 400-digit
    literal as an int.
- **Refused values.** `smooth` is `none | catmull_rom`, `antialias` `const: true` and `eraser`
  `const: false`; `_refusal` lost the four branches behind them.
- **Instructions.** 3,970 to 3,453 characters, 643 spare.
- **Codex's limits.** `codex_render.py` ports `sanitize_json_schema`, the schema struct's keep-list
  and `JsonSchemaTypeRenderer`, work budget included, from the Rust source at `rust-v0.166.0`.
  - **Measured at 0.20.0:** largest normalised input 2,948 bytes (`krita_paint_stroke`); largest
    rendered input 1,909 (the same); largest rendered output 2,362 (`krita_preview_render`). No input
    renders an `unknown`; two outputs hold an open object's `[key: string]: unknown`, as they should.
  - The backlog item "Codex's renderer is not re-measured" left.
- **Probe.** H6 gains a check: each of the 10 colours' sampled `color` equals the brush colour sent,
  and painted back unchanged it samples as the same bytes. The eraser and stabilizer refusals now
  expect `INVALID_ARGUMENT`.
- **Amendments:**
  - **Descriptions reach every bounded input field,** not only the block's six, so one test can hold
    them all. Decided at plan time, with the owner.
  - **No test holds the 500 spare characters,** because later sessions spend them.
  - **The block said 190 characters were spare;** R3 had left 126. D1 left 643.
- **Checked live:** `install-plugin`, a Krita restart at 0 unsaved, `doctor` 6 of 6. The first probe
  run met a dialog Krita opened at start (16 PASS, 15 FAIL, all `KRITA_MODAL_DIALOG`, nothing
  touched); the owner closed it and the rerun passed.
- **Falsified:**
  - **Sixteen unit checks, each failing at its own test:** `color` rounded to 2 decimals; `color`
    with the sampled alpha; each of the three limits drifted; the finite walk off; the walk missing
    big integers; `smooth: basic` back; `eraser` a boolean again; the overflow check off; a
    description's range drifted; the scale rule off; the selection rule off; an input padded past
    5,000 normalised bytes; an output padded past 16,000 rendered bytes; the port's comment form.
  - **The probe's new and changed checks, broken together:** 146 PASS and 2 FAIL, exactly those.
- **Numbers:** 879 server tests (+137), 799 plugin tests (+0), probe 148 PASS (+1), 0 FAIL, 24
  MEASURED, 125.5 s with 0 documents open. 19 tools, 19 schema files, 30 error codes, 31 ops,
  instructions 3,453 characters, `api_version` 0.4.0.
- **Review (`/code-review high`), run at the owner's request, 7 findings: 7 fixed and 0 skipped.**
  - **The sample's `color` was a hand copy of the stroke's colour shape.** `amend_schemas.py` now
    writes it from `brush.color`, and the drift test covers it.
  - **`stroke_op` raised on a huge point from a direct caller,** such as the probe. `_path` now
    answers an overflow in smoothing with its refusal.
  - **A number that is not finite was reported twice,** as out of bounds or of the wrong type, and
    as not finite. The schema's own problem with such a number is now left out.
  - **The probe's paint-back strokes ran past the canvas** and over the first strokes; they now run
    from y 70 to 90.
  - **The Codex gate would have failed on the word "unknown" in a description;** it now reads only
    the type lines.
  - **The probe sampled the layer and the composite through one loop variable;** they are two calls.
  - **The port's header comment was a paragraph;** it is two lines.
  - **Falsified:** the stroke's colour changed without the sample's (the amendment test failed); the
    schema's problem kept beside not-finite; the overflow left raising; an untyped input field
    (the Codex gate failed). Each failed at its own test.
  - **Numbers after the review:** 883 server tests, 799 plugin tests, probe 148 PASS, 0 FAIL, 24
    MEASURED, 127.3 s with 0 documents open.

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

**Done (2026-11-04, 0.20.1).**
- **Decided with the owner in plan mode:**
  - **One failure behaviour, the stroke's.** A create Krita raised in used to seal history and pass
    the raise on (`uncertain`, the document still usable), and a raise in its rollback escaped. Now
    every op on the frame is rolled back and confirmed, or the document is unsafe. Fields were
    only added, so `api_version` stays 0.4.0.
  - **So F1 ships 0.20.1,** with a `Fixed` entry.
  - **The plan,** approved in plan mode, after an independent attack on the frame against C1, M1,
    L1 and the pinned tests.
- **`bridge_core/mutation.py`.**
  - **`Reads` and `verifiable`:** the scope, the allowed mask, and optionally the target over its
    own rect with its `channels` (4, or 1 for a mask) and the protected layers over theirs. The
    refusals keep the stroke's order.
  - **`Steps`:** labels declared up front, one or more. A node step is pushed as Krita holds it; a
    pixel step is pushed after the reads with its witness, or sealed when its diff is empty. The
    frame asserts the op took exactly its labels.
  - **`Mutation.run`:** the fingerprint, the marker and `before_change()` together, then, inside
    `unconfirmed`, the change, the after-read, `check`, the pixel step and the op's `judge`.
  - **The rollback, inside `unconfirmed` too,** in this order:
    1. a step named but never pushed: by witness from a re-read, or by label and state;
    2. the pushed steps, newest first;
    3. the seal, after them, so the floor never stands above `applied`;
    4. the op's `compensate`;
    5. the re-read and the op's `back`.
  - **`unconfirmed`** moved here from `history.py`. `WATCHED` moved here from `layer_update.py`.
    `verification.changes` and `crop` take `channels`.
- **The three ops on it.**
  - **The stroke** keeps its refusals, brush, reach, R, ring and `target_rect`. Its judge is
    `_verdict`, its bounds and the full-scope widening; its `back` is its target's bounds.
  - **The update's** change ends with the refresh, the tree and `_moved`, as before. Its
    `compensate` writes the old values back, and its `back` compares the watched tree.
  - **The create** reads no pixels; its judge is `misplaced`, its `back` the watched tree.
- **Parity.**
  - The server's half of each pair is a named function: `_create_rules`, `_working_dir_rule`,
    `_save_rules` and `_clear_rules` are new, beside `_open_rules` and `_capture_rules`.
  - `tests/support/parity.py`'s `refused_alike` calls the tool, turns the server's function off,
    and calls again. Both refusals must share a code and `retryable`, with the plugin's
    `not_applied`.
  - `tests/test_parity.py` holds 14 cases across the six pairs.
- **Amendments:**
  - **A version and a `CHANGELOG.md` entry,** which the block ruled out: the unified failure path
    is visible. Decided at plan time, with the owner.
  - **Two tests changed their expectation, not their count:**
    - `test_a_layer_krita_refused_is_uncertain` became `…_is_confirmed_not_applied`;
    - the create-raises test now has Krita add the layer, then raise. That covers the frame's new
      undo by label and state, without adding a test.
  - **The update's `set_blend` compensation went:** an unpushed blend step is undone like any
    other node step.
  - **An update that only sets `active` skips the frame.** Its `_moved` check compared two reads
    around no write.
  - **`rolled_back` now means one thing for every op:** no move failed, and something was undone
    or written back. An update that wrote nothing before failing now reports `false`.
  - **`selection.set` stays outside the frame,** having no verdict; *Known debt* says so.
- **Checked live:** `install-plugin`, a Krita restart at 0 unsaved, `doctor` 6 of 6. The first
  probe run met a dialog Krita opened at start (16 PASS, 15 FAIL, all `KRITA_MODAL_DIALOG`, nothing
  touched); the owner closed it and the rerun held the whole baseline.
- **Falsified:**
  - **The six pairs, broken together** (each plugin side's code changed): all 14 parity cases
    failed at the helper's code comparison.
  - **The frame's undo by label and state, turned off:** the changed create test failed.
  - **Create's watched-tree check, turned off:** both changed tests failed, with three other
    create rollback tests.
- **Numbers:** 897 server tests (+14), 799 plugin tests (+0), probe 148 PASS (+0), 0 FAIL, 24
  MEASURED, 125.6 s with 0 documents open. 19 tools, 19 schema files, 30 error codes, 31 ops,
  instructions 3,453 characters, `api_version` 0.4.0.
- **Review (`/code-review high`), run at the owner's request, 7 findings: 7 fixed and 0 skipped.**
  - **A rollback brought the view forward with no step to move.** A property-only update or a
    create that failed before Krita changed anything flipped the owner's view, and a failure to
    bring it forward would turn a clean rollback into `ROLLBACK_FAILED`. The view now comes
    forward only around a step that may move; a node step not pushed is checked by state first.
  - **Every op read the selection for its start state,** a property-only update included. An op
    that names no undo step now reads none.
  - **The step-count check was a bare `assert`,** gone under `-O`. It is now an `INTERNAL_ERROR`
    refusal, rolled back like any other.
  - **The frame's paths for L1 and M1 had no test.** `tests/plugin/test_mutation.py` holds two
    steps undone newest first, a raise between two steps (the floor stays at `applied`, so the
    next op's step can be undone), the step-count refusal, the view and the selection left alone,
    and one-byte pixels counted and cropped.
  - **The changed create test checked the surviving step's label;** it now checks Krita's undo
    and redo labels.
  - **Two comments ran to paragraphs:** `Mutation.run`'s, which restated its parameters, and the
    parity helper's. Each is one line, or gone.
  - **Falsified:** the view always brought forward and the start state always read (the view
    test failed for each); the step-count check off; the seal moved before the undo (the raise
    test failed at its floor); the steps undone oldest first; the channels ignored. Each failed
    at its own test.
  - **Checked live:** `install-plugin`, a Krita restart at 0 unsaved, `doctor` 6 of 6.
  - **Numbers after the review:** 897 server tests, 804 plugin tests (+5), probe 148 PASS, 0 FAIL,
    24 MEASURED, 127.2 s with 0 documents open.

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
  - Server instructions, the README's tool list, `CHANGELOG.md`: 0.21.0.

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

**Done (2026-11-04, 0.21.0).**
- **Decided with the owner in plan mode:**
  - **The closed `path` is a curve through points,** `{"type": "path", "points": [[x, y], …]}`,
    3 to 4096, a closed uniform Catmull-Rom the server turns into exact cubics.
  - **The plan,** approved after an adversarial review of it. Its findings went in: flow set per
    fill, the full set run under every preset, a selection's bounds clipped to the canvas.
- **Measured first,** in a harness document, through a temporary `harness.fill` op that never
  shipped, under one stock preset of each of the 16 engines, a wash preset at flow 0.3, and eraser
  mode left on:
  - `paintPath(path, "None", "ForegroundColor")` is a painter fill. It made one "Scripted Brush
    Stroke" step, which one undo took back. Nothing changed past the shape at brush size 300, while
    a bad style string painted its outline 134 px out.
  - Opacity 0.5 gave alpha 128, and multiply gave the product. Alpha lock kept every alpha byte, and
    a feathered selection's coverage was the fill's alpha exactly. An ellipse's edge is antialiased;
    an integer rect's is not.
  - **The preset matters, invisibly.** Every preset filled the same visible pixels, but wash-mode
    presets (most `b)`, the masked brush among them) wrote colour under alpha 0 up to 3 px past the
    shape. Build-up, MyPaint, smudge and the others wrote none. Byte-exact verification counts
    that, so by the block's rule the fill activates one fixed preset, `c) Pencil-3 Large 4B`.
  - A selection's bounds run past the canvas: an inverted rect's are 448 × 320 on a 400 × 300
    canvas, and one grown at the corner starts at −10.
  - The fallback was not needed.
- **Shipped:**
  - `krita_paint_fill` / `paint.fill`, on the frame. The stroke's body from R on is one shared
    function, with the stroke's order and wording unchanged.
  - The shapes are `bridge_core/shapes.py`: exact fields, the area rule, and a curve's box by its
    extrema. A shape off the canvas is refused; a selection fill takes the selection's part on it.
  - R is the shape's aligned box plus 2 px, and R′ is R plus 32. The preset's XML is checked
    (build-up, no masking brush), and its digest is kept in the stroke's map.
  - The receipt has the stroke's shape, and the capability is `paint.fill`.
  - **Parity:** `_fill_rules` (alpha 1; points on one line), three cases.
  - The plugin tests' world moved to `tests/fixtures/paint_world.py`, shared by the stroke and fill
    tests.
- **Amendments:**
  - **The fill activates a preset,** which the block allowed only if the measurement showed it
    mattered. It did, under alpha 0 only; the owner's rule ("any difference") decided it.
  - **The margin is 2 px,** the plan's floor. The build-up preset touched nothing past the aligned
    box.
- **Checked live:** `install-plugin` and a Krita restart at 0 unsaved, twice (the instrument, then
  0.21.0), with `doctor` 6 of 6 each time. The first probe run had 7 FAIL, all in the fill group:
  its own check cleared the selection before its undo, which then undid the clear instead and left
  the selection on. Reordered, the rerun held the whole baseline.
- **Falsified:**
  - 13 new unit checks, each broken alone, each caught by its own test: the off-canvas rule, both
    halves of the area rule (the plugin's through parity), the extrema, the margin, the selection's
    clip and refusal, the taken check, the preset check, the curve's wrap, the overflow check, and
    both halves of the alpha rule.
  - The 11 new probe checks, broken together in one run: 11 FAIL, each at its own line.
- **Numbers:** 953 server tests (+56), 878 plugin tests (+74), probe 159 PASS (+11), 0 FAIL, 25
  MEASURED (+1), 130.0 s with 0 documents open. 20 tools, 20 schema files, 30 error codes, 32 ops,
  instructions 3,750 characters, `api_version` 0.4.0.

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
  - Server instructions, `CHANGELOG.md`: 0.22.0.

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
  - Server instructions, `CHANGELOG.md`: 0.23.0 on go.

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
  - Server instructions, the README's tool list, `CHANGELOG.md`: 0.24.0.

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
  - Server instructions, the README's tool list, `CHANGELOG.md`: 0.25.0.

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
  server instructions; `CHANGELOG.md`: 0.26.0 if it ships.

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
  baseline; server instructions; `CHANGELOG.md`: 0.27.0.

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
  where it is no longer true; the README; `CHANGELOG.md`: 0.28.0; the baseline.
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
