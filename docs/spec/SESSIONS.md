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
| X1a | Review fixes: the frame and the save's finish | 1, 5, 7, 10 | **0.23.0** |
| E1 | Taper probe, then the proven subset | 16 | **0.24.0** |
| L1 | Layers: duplicate, reorder, remove, group | 1, 3, 13 | **0.25.0** |
| B1 | Document duplicate | 1, 3, 12 | **0.26.0** |
| T1 | Translate, on a native route or not at all | 1, 15 | **0.27.0** |
| S1 | Scale, rotate, shear; cut first if the round runs long | 1, 3 | **0.28.0** |
| X2 | Architecture review: construction | all | — |
| X2a | Review fixes: construction | 1, 4, 5, 9, 10, 11, 13, 16 | **0.29.0** |
| V1 | Re-measure, docs, full run, close the round | 18 | **0.30.0** |

A review session changes no product code and cuts no version; a session it inserts takes the next
version, and every later version shifts by one. X1 inserted X1a, so E1 and every later version
moved up by one; X2 inserted X2a, so V1 moved up by one. E1 on a no-go and T1 without a native
route ship no version, and the later versions move down by one; the handoff says so.

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
- **Review (`/code-review high`), 8 findings: 7 fixed, 1 was not a problem.**
  - **A curve's extremum could be missed.** The textbook quadratic cancels when a cubic is almost
    a quadratic: one such curve read its top at 0.256, inside the canvas, while it turns at −0.15,
    outside. The roots now use the stable form.
  - **`selection.enforced`'s note named only strokes;** it names fills too.
  - **Nothing tested the fill's preset digest memory.** A test now has Krita move the digest on
    the fill's activation, then strokes with the listed sha256.
  - **The probe undid after a refused fill,** in the edge check and the preset check, taking back
    an earlier step. It undoes only what completed.
  - **The probe's true-bounds helper was copied** from the edge checks; both now use
    `common.held_bounds`.
  - **`held` was built twice;** `painted()` derives it from the effective brush.
  - **Not a problem: huge points called collinear.** Traced, a reach that overflows makes the first
    point's tolerance `inf × 0 = nan`, so `collinear` already answers False. The guard added for it
    was removed with its tests, which passed without it.
  - **Falsified:** the textbook roots back (the near-quadratic test failed); the fill's `remember`
    off (the digest test failed).
  - **Checked live:** `install-plugin`, a Krita restart at 0 unsaved, `doctor` 6 of 6.
  - **Numbers after the review:** 953 server tests, 880 plugin tests (+2), probe 159 PASS, 0 FAIL,
    25 MEASURED, 130.1 s with 0 documents open.

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

**Done (2026-11-05, 0.22.0).**
- **Decided with the owner in plan mode:**
  - **Mask paint is `mask: "reveal" | "hide"`, in place of the colour,** and the amount is the
    existing opacity (and a stroke's flow): reveal gives c + opacity × (1 − c), hide c × (1 −
    opacity).
  - **A mask is captured with a new `target: "mask"`,** which the schema keeps from `background`
    and `greyscale`.
  - **`krita_layer_create` becomes destructive** (decision 1's rule): a `none` mask hides its whole
    layer, as `visible: false` would.
  - **The plan,** approved after an adversarial review on Fable (2 High, 6 Medium, 6 Low, all
    folded in). Among them: compare the create's parent without bounds, read the coverage rect
    from the before tree, decide the create's and `visible`'s scope by the measured bounds, pin
    `setSelection` by name as well as by attribute, and send `color` and `mask` both, one null.
  - **The owner allowed Krita restarts when needed,** at 0 unsaved documents, for this session.
- **Measured first,** on Krita 5.3.4.1, through a temporary `harness.mask_measure` that never
  shipped, on a 64 × 48 harness ORA:
  - `createTransparencyMask` gives an `A`/`U8` mask with bounds 0 that reads all 0, and attached
    with no selection it hides its layer. `setSelection` before `addChildNode` lands the
    selection's bytes exactly (rect, inverted, empty, graded PNG, feathered), in one "Add Layer"
    step that one undo takes back. The new mask becomes active; Krita's flag is set.
  - A mask's bounds are its layer's own, and no mask, `none` included, moves the layer's. An
    inverted empty selection reads 255 past the canvas; a canvas rect reads 0 there.
  - The composite is `rint(layer × c + below × (1 − c))`, exactly, over a graded PNG mask.
  - Paint on a mask: white reveals and black hides under `normal`, by the opacity (black 0.5 from
    255 gives 127, white 0.5 from 0 gives 128); `erase` with white hides alike; greys map
    linearly (0.5 gives 127, 0.25 gives 63), not by lightness as Krita's source suggested. Fills
    and strokes (pencil, wash, soft) are each one "Scripted Brush Stroke" step. The global
    selection confines; a local selection mask on the layer does not.
  - `paintAbility()` reads `MYPAINTBRUSH_UNPAINTABLE` for MyPaint presets on a mask.
  - `setVisible` and `setName` push no step; the composite shows `visible` after a refresh.
  - A KRA save keeps masks with their ids; an ORA save lists them as lost nodes.
- **Shipped:**
  - `layer.create` takes `transparency_mask` with `coverage`, through `create_mask` in the adapter
    (`all` an inverted empty `Selection()`, `none` an empty one, `selection` a duplicate). Its
    frame reads the composite over the layer's bounds (the canvas when `reach` finds a spreading
    node), judges `misplaced`, the verdict and the coverage, and its receipt adds `coverage` and
    `verification`.
  - `protection.refuse_held_line`: the mask, its layer and every group holding it unprotected, for
    the create, paint and `visible`/`name`.
  - Strokes and fills take `mask`; the target check reads the paint kind first; the frame reads a
    mask one byte a pixel; receipts give `mask` and a null `color`.
  - `reach()` starts from a mask's layer. `krita_layer_update` takes `name` and `visible` on a
    mask. `capture.read` takes `target: "mask"` and writes `A8`.
  - `mask.transparency` in the matrix. `setSelection` joins invariant 1's scan, held to four sites.
  - Parity: `_brush_rules` (a stroke's colour or mask), and "neither" in the fill's rules.
  - `probe/transparency.py`: 12 checks, run in the paint stage after the fills.
- **Amendments:**
  - **`krita_layer_create`'s hint becomes destructive,** which decision 1's list had as additive
    before masks were live. Decided at plan time, with the owner.
  - **A capability, `mask.transparency`,** which the block did not name. At plan time, with the
    owner.
  - **The mask create reads more instead of refusing:** it has no `verify`, so a spreading node
    widens its read to the canvas. At plan time, with the owner.
  - **The intake's reading of Krita's source was half right:** colour does become coverage, but
    greys map linearly on 5.3.4.1, not by lightness. The session's own finding.
  - **The probe's leak check needed a colour unlike the layers under it:** hiding a red layer over
    red layers changed nothing visible, so its first run passed nothing it meant to test. The
    session's own finding.
- **Checked live:** `install-plugin` and a Krita restart at 0 unsaved, twice (the instrument, then
  0.22.0), `doctor` 6 of 6 each time. The first probe run had 4 FAIL, all the probe's own: its mask
  checks were wired in twice (the second run met `FILE_EXISTS`), and the leak check above. Fixed,
  the rerun held the whole baseline.
- **Falsified:**
  - **31 unit checks, each broken alone, each caught at its own test:** the mask's parent, the
    create's, paint's and update's held lines, `above_id`, coverage for a mask only (both
    halves), the selection coverage's selection, the create's leak verdict, the coverage check,
    the paint kind, one byte a pixel, colour or mask, no blend or alpha lock, hide's black, the
    receipt's mask, the mask's two properties, the mask target's type and its `A8`, `reach` from
    the layer, the server's rule, the mask capture's background, the create's resolved images,
    the capability, the scan's name ban, its attach order, its mask maker and its commit
    parameter, and the three schema rules.
  - Three first attempts proved nothing (a `-k` with spaces selected no test), and one check was
    first missed: `above_id`'s test was refused earlier for another reason. Each test was fixed
    and the check caught.
  - **The probe's 12 new checks, broken together in one run:** 159 PASS and 12 FAIL, exactly
    those. A first attempt left them broken for the rest of the run, and does not count.
- **Numbers:** 970 server tests (+17), 927 plugin tests (+47), probe 171 PASS (+12), 0 FAIL, 25
  MEASURED, 129.9 s with 0 documents open. 20 tools, 20 schema files, 30 error codes, 32 ops, 12
  capabilities, instructions 3,908 characters (+158), `api_version` 0.4.0.
- **Review (`/code-review high`), run at the owner's request while they were away, 7 findings: 7
  fixed and 0 skipped.**
  - **The parent check was loosened for every create.** `misplaced` compared the parent without its
    bounds for paint and group creates too; it does so for a mask's layer only again.
  - **A sample, a preview or a `layer_alpha` selection of a mask pointed to `target: "mask"`,**
    which none of them takes. The hint now comes from the capture alone.
  - **`check_target`'s message named a mask target for sample and preview;** it names each call's
    own targets.
  - **A mask capture's receipt said "the mask"**; it names the mask, as a layer capture names its
    layer.
  - **No test held the create's widening to the canvas, or a mask under
    `preserve_composite_alpha`;** both are tested, with a protected group's bounds on a paint create.
  - **`create_mask`'s comment was a paragraph;** it is one line.
  - **Two ancestor walks and two node lookups;** `protection.line` and `pixels._found` serve both.
  - **Falsified:** the parent strict for a layer, the capture's hint, `check_target`'s targets, the
    receipt's mask, the create's widening and its alpha check. Each failed at its own test.
  - **Checked live:** `install-plugin`; Krita's quit timed out at 0 documents open and 0 unsaved,
    and was not forced while the owner was away. The owner restarted it, `doctor` 6 of 6.
  - **Numbers after the review:** 970 server tests, 931 plugin tests (+4), probe 171 PASS, 0 FAIL,
    25 MEASURED, 132.0 s with 0 documents open.
- **Second review (the owner's `/code-review high`), 5 findings: 5 fixed and 0 skipped.**
  - **`protection.line` rebuilt the node map on every call,** once per protected id in an update;
    it takes the map, built once.
  - **A layer capture read the tree twice;** the mask hint is `paint_layer`'s, given by the capture
    alone, so one read serves.
  - **The mask create's layer was compared without its bounds,** guarding a hypothesis the
    measurement disproved; every create's parent is compared field by field again.
  - **The mask tests copied the fill tests' helper;** `paint_world.fill_args` serves both.
  - **The probe built mask paint as a colour fill and deleted the colour;** it builds it directly.
  - **Falsified:** the capture's hint, off; its test failed. The rest are refactors under existing
    tests.
  - **Checked live:** `install-plugin`, a Krita restart at 0 unsaved, `doctor` 6 of 6.
  - **Numbers after the second review:** 970 server tests, 931 plugin tests, probe 171 PASS, 0
    FAIL, 25 MEASURED, 132.1 s with 0 documents open.

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

**Done (2026-11-06, no version).**
- **Decided with the owner in plan mode:**
  - The probe ran for the baseline, and the owner's journal was counted read-only, as counts.
  - The product fixes land in an inserted **X1a**, before E1; every later version shifts by one.
  - **F6:** a poll finishes a save only from the process that made the call; `krita_operation_get`
    keeps `readOnlyHint: true`, with the exception written down.
  - **F28** is recorded as a fix that leaves the contract alone; `api_version` stays 0.4.0.
- **The review.** `REVIEW-2026-11-06.md`: 28 findings (2 High, 9 Medium, 17 Low) and 11 Info,
  each verified on the code path at `189ba26`; §2 holds every invariant to its enforcing site and
  test; §5 reads the frame forward against E1, L1, B1, T1 and S1. The read ran twice, by six
  independent readers in two waves of three, the second without the first's notes; each
  substantive finding was found by both reads of its area.
- **The findings that matter most.** A save whose finish never ran says `not_applied`, retryable,
  with its hidden file in place (F1); the instructions have 188 characters for five sessions' lines
  (F2); a rollback's first undo skips the state check (F3); a finish refused retryably is stuck
  under its derived id (F4), and a second process's poll kills a save (F5); the frame recovers one
  unpushed step and cannot name a detached node (F7); the ledger's fingerprint sees only blend and
  membership (F8); `RECEIPTS` is keyed by op (F9); parity does not hold schema-side rules and the
  area rule differs between the sides (F10); the probe's journal check can pass on nothing (F11).
- **Amendments:**
  - **X1a inserted**, 0.23.0, with the fixes the owner chose; E1 0.24.0, L1 0.25.0, B1 0.26.0,
    T1 0.27.0, S1 0.28.0, V1 0.29.0. Decided at plan time, with the owner.
  - **E1, L1, B1, T1 and S1 amended** from the findings, each saying so under its Read line;
    X2's watch-for names what to re-check. Decided at plan time, with the owner.
  - **The review's method widened** from one second read to three readers a wave, so each area's
    second read was cold and whole. The session's own choice.
- **Measured,** on Krita 5.3.4.1, commit `189ba26`:
  - `verify` as found: 6 stages PASS; tests 183.3 s, plugin-tests 26.9 s.
  - `probe` as found: 171 PASS, 0 FAIL, 25 MEASURED in 134.1 s with 0 documents open; no call left
    uncertain. `doctor` 6 of 6, 0 open documents, 0 unsaved.
  - The owner's journal, counts only: 2,105 calls over three days, all finished as receipts, 3
    `INVALID_ARGUMENT` failures from before the outcome field, 0 `unknown`, 0 unfinished.
  - Codex's renderer: the stroke's input 3,154 normalised and 2,091 rendered bytes; the preview's
    output 2,362.
  - The fill's area rule, one seeded generator: 22 of 30,000 and 266 of 300,000 near-flat closed
    paths refused by the server alone, none by the plugin alone.
  - Eleven simulations on the test worlds, each written under its finding.
- **Falsified:** nothing; a review adds no check.
- **Numbers:** 970 server tests (+0), 931 plugin tests (+0), probe 171 PASS (+0), 0 FAIL, 25
  MEASURED, 134.1 s with 0 documents open. 20 tools, 20 schema files, 30 error codes, 32 ops, 12
  capabilities, instructions 3,908 characters, `api_version` 0.4.0.
- **Review (`/code-review high`), 5 findings: 5 fixed and 0 skipped.**
  - **X1a's poll rule named a lease check the server cannot make.** The server's one record of
    which process followed a call is `BridgeClient._sent`; the block now names it, says a retry
    of the save under its `request_id` finishes it, and why the journal cannot decide.
  - **X1a's session check named no mechanism.** The finish's `Done` or submitted `Failed` already
    carries its bridge session; the block now says to compare it with the save's.
  - **The handoff dropped five standing traps, or cut them short:** the measurement instrument,
    the unlike layer, and the reasons on the selection-clear and `-k` traps. Restored verbatim.
  - **The area rule's large counts were a reader's, from another generator.** This session
    reran it seeded: 266 of 300,000 refused by the server alone, none by the plugin alone. The
    review and this note cite those, and say the plugin-only direction was not reproduced.
  - **The review cited line ranges with no file** in the invariant 5 row and six other places;
    each names its file.
  - **Falsified:** nothing; the fixes are to documents.
  - **Numbers after the review:** unchanged.

---

## X1a: Review fixes — the frame and the save's finish

Inserted by the owner at X1's plan mode, 2026-11-06, from `REVIEW-2026-11-06.md`: the product
fixes the review found, before E1 builds on the frame and before the instructions run out. The
owner chose the inserted session over spreading the fixes across E1, L1 and B1, and chose for F6
that a poll finishes a save only from the process that made the call.

**Read:** `REVIEW-2026-11-06.md` whole (F1–F6, F10, F11, F13–F21, F23–F25, F27 are its scope);
`FEATURE-recovery-and-construction.md` decisions 1, 5, 7, 10; `ARCHITECTURE.md` *The tool contract*
(Hints, The instructions, Argument rules are written twice), *Bridge and jobs*, *The verification
core* (The frame, The rollback), *The undo ledger and history*, *The save*, *The server*, *Testing
strategy*.

- **The save's finish tells the truth** (F1, F5, F6; decisions 5, 7).
  - `finish_save` (`src/krita_art_mcp/tools/saving.py:104-107`) keeps a stated `not_applied` only
    when the finish's `details.rollback_verified` is true (its own discard paths); any other
    failure after a completed save is `uncertain`, not retryable. So is a finish whose session
    differs from the save's: the finish's `Done` or submitted `Failed` carries the bridge session
    it ran in (`bridge_client.py:315-325`), so compare it with `outcome.session_id` before the
    identity is replaced (`:93-115`); a `Failed` with no session never reached a bridge.
  - A poll finishes a save only from the process that made the call. The server's one record of
    that is `BridgeClient._sent`, which holds every op this process followed past its wait
    (`bridge_client.py:96,261`): `krita_operation_get` runs `Known.finish` only for an op found
    there, and any other poll reports the save as the bridge holds it, with no finish, and says
    that a retry of the save under its `request_id` finishes it (that retry's `journaled` path
    resends, the bridge dedups to the finished save, and the finish runs in the retrying
    process). The journal cannot decide this: two servers on one data folder read the same
    lines. The hint stays `readOnlyHint: true`; the exception is written in the hints table and
    the guide.
- **A retryable failure under a derived id runs again** (F4). `Jobs.submit` (`jobs.py:185-188`)
  treats a known op that failed retryably, whose request was released, as a new submission under
  the same id.
- **The rollback's first undo reads the state** (F3). `_restore` passes `known` as it is
  (`mutation.py:372`), or seeds it from the state `_unnamed`'s move confirmed.
- **The instructions move** (F2). Into tool and field descriptions: the inspect line, the capture
  line, the stroke line, the layer_update line's tail (a `verify` description, which the field
  lacks, and `inherit_alpha`'s), the fill's first clause, the sample line but "Never judge a colour
  from a capture.", the "Undo steps" line into `history_step`'s description, open's "The source is
  never written…" into `mode`'s. Leave at least 700 characters spare, and keep the two pinned
  phrases (`tests/test_envelope.py:185,188-192`). A test holds the spare floor this time, because
  the five sessions' lines are known: E1 about 145, L1 185, B1 140, T1 130, S1 130.
- **Parity holds schema-side rules too** (F10; decision 10). `refused_alike` gains a way to turn a
  schema rule off, or to send the translated op straight to the bridge; cases for the stroke's
  colour alpha, colour and mask both given, mask paint with a blend or alpha lock, `coverage` on
  the wrong type, open's mode against `working_dir`. One area rule on both sides, over the
  on-curve points (`shapes.points`, `tools/painting.py` `_fill_rules`), with a near-flat case.
  `ARCHITECTURE.md:320-327` then says what is held.
- **The probe's journal check sees what it reads** (F11, F24). `_nothing_uncertain` asserts a
  minimum line count and reports dispatched lines with no finish, and says which calls are outside
  it. `transparency.py:301` compares against the stroke's own change; a reveal stroke, a partial
  stroke and an undo of a mask create join the mask checks.
- **The small fixes.** `_counted` takes the channel count per hashed id (F13); the unsafe exit of
  `_roll_back` calls `lost()` (F14); a confirmed rollback whose unnamed step never moved does not
  seal, or the failure reports `history_sealed` (F15); `selection.set` calls `lost()` on a
  non-`BridgeError` after its marker (F16); `unmasked_view` puts the active node back, or K46's
  activation is named as excluded in decision 5's table, the fake and an armed test with a mask
  active (F17); the moved-document save writes `rollback_verified: false` (F18); the retryable
  scan reads keyword and computed flags (F19); `no_effect` settles the attempts in that session
  with the same digest dispatched before the line (F20); `_check_mask_paint` refuses `eraser`
  with mask paint (F21); a composition problem whose subtree holds a not-finite path is dropped
  (F23); `selection.enforced`'s note names mask paint (F25); `test_schemas.py` walks nested
  objects for `additionalProperties: false` (F27).
- **Docs** (F27, F6). `ARCHITECTURE.md`: the Codex sizes, "the paint kind first", "The 23 lines"
  and the fill's time, the `amend_schemas` list, the hints' exception, the parity paragraph, the
  finish's rule in *The save* and *The server*; `CLAUDE.md`'s `amend_schemas` row;
  `USER-GUIDE.md`: the hints table's exception, `LOCKED_TARGET`'s held line, the save's and the
  poll's new wording; `instructions.py` names `unregistered`; `BACKLOG.md:165,168-169`;
  `CHANGELOG.md`: 0.23.0.

**Gates:**
- `uv run scripts/verify.py`, with these tests:
  - a finish refused before its marker after a completed save reads `uncertain`, not retryable;
    one whose own discard verified keeps `not_applied`; a session mismatch reads `uncertain`;
  - a poll from a process that did not dispatch the save finishes nothing and says so; the
    owning process's finish still runs;
  - a finish refused at job start, the dialog closed, then a retry of the save that completes;
  - the stranger step: an unseen "Add Layer" on top is `ROLLBACK_FAILED` with no move;
  - the instructions' spare floor; each moved sentence found in its description;
  - the new parity cases, and the near-flat path refused alike;
  - each small fix, at its own test.
- `probe`: the whole baseline, with the journal check's minimum and the three new mask checks.
- Each new check falsified once.

**Watch for:**
- **Decision 7 stands.** A same-session resend of a save is still allowed; only what the finish
  says about a completed save changes.
- **The two-step tests** (`tests/plugin/test_mutation.py:66,82`) pin the rollback's order; the
  `known` change must leave them green and fail the stranger test alone.
- **The hidden file after an `uncertain` finish** stays, as known debt says; the fix changes what
  is said, not what is swept.
- **Version first.** The plugin's hash and `serve`'s gate both read it; `install-plugin` and a
  Krita restart before the probe.
- **The instructions are user-visible,** so the move is a `Changed` entry.

**Done (2026-11-06, 0.23.0).**
- **Decided with the owner at the start:**
  - **F20 takes the alias line,** not the block's rule. The block's rule settles every
    same-session, same-digest attempt dispatched before a `no_effect` line. That includes one sent
    after the bridge released the request but before the line was written, which may have run, and
    after a Krita restart could be resent.
  - **The save's finish refuses its lease retryably,** so a second server's retry under the
    holder's `request_id` never locks the holder's finish.
  - **`install-plugin`, a Krita restart and the probe** ran once `verify` was green, with 0 unsaved
    documents.
  - **An adversarial review of the plan ran on Opus,** at the owner's request. It found three design
    faults and five smaller gaps, all folded into the plan before approval (see *Amendments*).
- **The save's finish** (`tools/saving.py`).
  - **The call and its shared tail.** `finish_save` sends the finish, and `_as_save` gives the
    answer the save's identity.
  - **When `not_applied` stands.** A failed finish keeps it only when it states `not_applied` with
    `rollback_verified: true`, in the save's own Krita session, for a save that replaced no earlier
    unfinished one. The save op's result gains `replaced_pending`, kept out of the receipt.
    Anything else is `uncertain`, not retryable.
  - **The retry sentence.** A finish refused retryably says that retrying the save under its
    `request_id` finishes it. For the lease, it names the holder's pid.
  - **The poll.** `poll_finish` is the save's `Known.finish`. It finishes only when
    `BridgeClient.made()` holds the save's or the finish's id. Otherwise it GETs the finish's
    record, or answers `uncertain`, saying how to finish it.
  - **The client.** `BridgeClient._made` records every id this process sent and the id it was
    answered under. `operation()` takes a `budget_s`.
  - **The plugin.** `Registry.guarded(lease_retryable=True)` is used for the finish alone.
- **A retryable failure runs again under its own id** (`Jobs.submit`). The rerun falls through the
  bound check and the `_requests` check. Its conflict leaves the old failure in place, so the id
  stays rerunnable.
- **The frame** (`mutation.py`).
  - The first undo reads the state.
  - The unsafe exit calls `Handle.lost()`.
  - Every rollback's details carry `history_sealed`.
  - `_counted` takes its bytes a pixel from the read.
- **The selection** (`selections.py`): a non-`BridgeError` past the marker calls `lost()`.
- **K46** is named as window state, not a change. The fake's gate lets an activation off a
  selection mask through, and an armed test drives a stroke with a global and a local mask active.
- **The smaller plugin fixes.**
  - Mask paint refuses `eraser`.
  - The moved-document save writes `rollback_verified: false`.
  - `selection.enforced`'s note names mask paint.
  - `shapes.points` gives on-curve points only.
- **The server's smaller fixes.**
  - **F20.** A retry that comes back running under another id writes an `unknown` alias line with
    no result. `journal._index` keeps the alias on the attempt, a `no_effect` settles it, and the
    line answers for its own id alone.
  - **F23.** `_not_finite_alone` also drops a union's problem when one branch failed on not-finite
    numbers alone.
  - **F27.** The schema test walks every nested input object.
  - **F19.** The retryable scan reads keyword and computed flags.
- **The instructions** moved into seven tool and field descriptions, and name `unregistered`:
  2,945 characters, 1,151 spare. A test holds 700 spare and each moved phrase in its description.
- **Parity.**
  - `refused_alike(…, schema=path)` cuts one keyword from a second server's schema.
  - **Five new pairs:** the stroke's colour alpha; colour and mask, blend or alpha lock with mask
    paint, on stroke and fill; `coverage` on a layer; a read-only open's `working_dir`; a
    near-flat closed curve from a seeded search.
- **The probe.**
  - **The journal check** reads through `Journal`. It fails under 340 dispatched lines or on any
    unsettled request, and names each.
  - **The mask checks.** Reveal, half-opacity and hide strokes are each judged on their own change
    and centre row, and a mask create is undone.
- **Docs:** `ARCHITECTURE.md`, `USER-GUIDE.md`, `CLAUDE.md`'s and the script's `amend_schemas`
  text, `BACKLOG.md`, `CHANGELOG.md` 0.23.0, `README.md`'s version.
- **Amendments:**
  - **The poll's record is `_made`, not `_sent`.**
    - `_sent` is also written by a poll whose wait runs out, so a second server that polled a
      running save would count as its maker. It also misses a save and finish that both answered
      within the budget.
    - The block's intent (the process that made the call) holds. Found by the plan review, decided
      at plan time, with the owner.
  - **A poll from another process reads the finish's record** before saying the save is
    unfinished. Without that, a re-poll of a finished save, or the existing test of a poll after a
    failed finish, would read "not finished". The session's own design, approved at plan time.
  - **The retry sentence goes only on a finish refused retryably.** A non-retryable refusal would
    get the same failure back. Found by the plan review.
  - **A save that replaced an unfinished one never keeps `not_applied`.** Found by the plan review.
  - **The rerun's conflict leaves the derived id rerunnable.** Found by the plan review.
  - **F20's alias line answers for its own id alone,** so `krita_operation_get` of the original
    after a restart reads as before. Found by the plan review.
  - **F23 drops a union's problem only when one branch failed on not-finite numbers alone,** so a
    second, real problem is never hidden. Found by the plan review.
  - **Where three either/or fixes went.** F3 passes `known` as it is. F15 reports `history_sealed`
    rather than not sealing, since a step that never moved the fingerprint can still be on Krita's
    stack. F17 names the exclusion rather than restoring the node, since the global selection's
    mask cannot be made current again (measured). The session's choices, in the approved plan.
  - **Left, to `BACKLOG.md`:** F16's `transfer.write` tail, which decision 5 lets read only
    `uncertain`; F24's edge checks under a selection and `edges.py`'s replay; F10's preview
    `baseline_id` pair.
  - **The probe's partial stroke** is a hide stroke at opacity 0.5. It measured 127 at its
    centre, under the wash-mode `b) Basic-2 Opacity`.
- **Measured,** on Krita 5.3.4.1, macOS, Apple Silicon:
  - `probe`: 174 PASS, 0 FAIL, 25 MEASURED in 136.5 s with 0 documents open. The journal check read
    682 dispatched lines, all settled.
  - Mask strokes: reveal 255 and hide 0 at their centres, a half-opacity hide 127, each changed byte
    inside its reported bounds and moved one way. A mask create is undone in one step.
  - Codex's renderer: the stroke's input 3,190 normalised and 2,127 rendered bytes. The preview's
    output is 2,362; the longest description is 448 (the fill).
  - The area rule, seeded: near-flat closed paths the server refused and the old plugin rule
    passed were found within the first few trials. One is the new parity case.
  - `doctor` 6 of 6 after the restart, 0 open documents, 0 unsaved.
- **Falsified,** each once, each failing at its own test, the tree restored byte for byte:
  - **The plugin:** the rerun, its conflict, the finish's lease, `replaced_pending`, F3, F14, F15,
    F13, F16, F17, F21, F18 and F19 (a keyword flag).
  - **The server:** the finish's outcome rule, the maker's poll, `made()`, the lease end to end,
    the dialog-then-retry, F20's settling and its alias index, F23, F27, the spare floor and a moved
    phrase, the schema switch (eight cases), the stroke's alpha pair and the area rule.
  - **The probe:** the reveal, half-opacity and hide strokes, the undone create and the journal
    floor, all broken in one run that failed those five alone.
- **Numbers:** 1006 server tests (+36), 944 plugin tests (+13), probe 174 PASS (+3), 0 FAIL, 25
  MEASURED, 136.5 s with 0 documents open. 20 tools, 20 schema files, 30 error codes, 32 ops, 12
  capabilities, instructions 2,945 characters, `api_version` 0.4.0.
- **Review (`/code-review high`), 6 findings: 6 fixed and 0 skipped.**
  - **A `no_effect` line with no `bridge_operation_id` settled every attempt of its request.**
    An older line's missing id put `None` among the ids it names, which matched every attempt
    with no alias. Such an attempt may have run after the release. `named` now holds strings
    alone.
  - **The retry sentence was promised where a retry cannot finish:** on a finish another
    process's poll reads, and on one cancelled at Krita's quit. Both now go without it.
  - **The fake's K46 exemption let every activation through while a mask was active.** It now
    passes only the activation onto the layer `nodes.unmasked` names.
  - **`_made` grew with every call, reads included.** It now records only calls with a
    `request_id`.
  - **The probe's `_left_as` parsed an outcome by hand.** It uses `operations.said`, made public
    and safe on loose data.
  - **Two comments cited a version and planned sessions.** Reworded to the present.
  - **Falsified:** the line naming no bridge operation, both cases of no retry sentence, the
    fake's narrow exemption, reads not recorded as made, and `said` on loose data. Each failed at
    its own test, the tree restored byte for byte.
  - **Numbers after the review:** 1013 server tests (+7), 945 plugin tests (+1), probe 174 PASS,
    0 FAIL, 25 MEASURED, 139.3 s with 0 documents open; the journal check read 682 lines.

---

## E1: Tapers

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (Authoring, its
answers), decision 16; `ARCHITECTURE.md` *Painting*, *Reads, and K46* (Resources), *Testing
strategy* (Hypotheses), *Reference* (K3, K4, K30, K36); `REVIEW-2026-11-06.md` §5 E1, F2, F26 and
the Info on the brush exclusion.

**Amended at X1 (2026-11-06), with the owner.** The block's pointers `painting.py:86-88,551` are
stale (F26): the digest memory is `activated` and `remember` (`painting.py:69-76`, called at
`:186` and `:258`), and `_listed`'s lookup is at `:588`. Decision 5's brush exclusion does not
cover a `fromXML` edit, which Krita's "save dirty presets" setting can write to disk: mark before
the edit, run `remember` before it and never after, and restore inside the change, checked by
digest. Whether `Preset(resource).toXML()` differs from the view's preset after a `fromXML` is
unverified; measure it first. E1 ships 0.24.0 on go, after X1a.

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
  - Server instructions, `CHANGELOG.md`: 0.24.0 on go.

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

**Done (2026-11-06). Go, 0.24.0.**

- **Decided with the owner in plan mode:**
  - Straight lines between knots, by Krita's corner points.
  - The Distance curve replaces the preset's own size and opacity sensors for that one stroke.
  - Krita restarts were allowed this session, at 0 unsaved documents, with the Codex agent paused.
  - An adversarial plan review by Opus. 12 of its 13 findings went into the plan. The main one:
    restore by the preset's own XML, and reload from storage only when it was clean before the
    brush was set, so an unsaved tweak survives. The one declined: a quit with an edited preset, to
    confirm the crash case. A quit may run save paths a crash never would, so the disk listings
    during the edit confirm it instead.
- **Decided with the owner at the go/no-go:**
  - **Go, with the origin offset compensated** (below).
  - **Krita's other dirty-presets setting was left unmeasured,** and refused.
- **The go/no-go,** through a temporary `harness.taper_measure` that never shipped, on a harness
  ORA, under three stock `paintbrush` presets (wash, build-up, image tip). Three driver runs, about
  40 paint calls with the references.
  - **The dirty flag.** The resource model's `Dirty` column (role 256 + 12) read false before the
    brush was set and true after `fromXML`. `set_brush` alone dirtied the build-up and the
    image-tip preset, not the wash one.
  - **One object.** `Preset(resource)` read every edit of the view's preset.
  - **The restore,** by XML then a reload when clean before, gave back the digest and the flag on
    every case. The reload brought an activated preset back to its listed digest. An unsaved
    spacing tweak survived a taper. The brush-state write-back was exact.
  - **Nothing on disk moved.** The preset files and bundles hashed alike before, during and after
    every edit. That is what a crash mid-stroke would leave.
  - **The origin offset, the round's surprise.** A scripted stroke's Distance sensor counts the
    first dab's distance from the canvas origin. Uncompensated, a 0.1 → 1 → 0.1 taper peaked a
    quarter of the way along a 1500 px stroke, 330 px late for a start 335 px from the origin.
    Short and curved strokes starting farther out than their length painted their end value
    throughout. A stroke from near the origin peaked mid-way.
  - **Compensated,** with the length set to arc + |start| and the knots moved to match, widths
    matched plain reference strokes at every knot on short, long and curved strokes, and alpha
    did for opacity.
  - Corner points ran straight between knots; smooth points bowed. Krita echoed the curve string
    as written. `_current` was unmoved by the edit.
  - **Five conditions:** all held, with the compensation, under Krita's default setting.
- **The instrument crashed Krita once.** Its first dirty read asked every item model in the window,
  and the animation curves docker's model segfaulted on `data()`. No document of the owner's was
  open and no preset had been touched. The shipped read asks only resource views and models. A
  second crash, earlier, came from Krita's QML UI before any instrument call.
- **Shipped:**
  - `dynamics` on `krita_paint_stroke`: `size` and `opacity` knots, the origin offset
    compensated, the pixel engine only, `preset_sha256` required, mask paint refused.
  - `bridge_core/dynamics.py`, pure.
  - The restore rule, and the hold on a preset left edited, for stroke and fill.
  - `effective_brush.dynamics` in the receipt.
  - `stroke.dynamics`, true since 0.24.0, and `harness.preset_dirty`.
  - Parity pairs for the knot rules, the sha, mask paint and the 1 px floor.
  - `probe/dynamics.py`: eight checks.
- **Amendments:**
  - **The curve is shifted by the origin offset,** which the block's XML did not foresee. The
    owner's call, at the go/no-go.
  - **A changed `useDirtyPresets` is refused** rather than measured by a hand toggle. The owner's
    choice, at the go/no-go.
  - **The resource database was not read for version rows.** Every version of a preset is a file,
    so the file listing covers it, and the database's times were reported only. The session's own
    finding.
  - **The probe's preset meets the tapers already dirty,** so the live probe exercises the
    restore by XML. The reload route is held by unit tests and the go/no-go, and is on the backlog.
  - **`harness.preset_dirty` is a new op (33).** The block named the probe check, not the op.
  - **The block's "`stroke.dynamics` stays false" on a no-go** did not arise.
- **Checked live:** Krita restarted at 0 unsaved six times (the instrument twice, cleaning up the
  edited presets, 0.24.0, the falsification build, 0.24.0 again), with `doctor` 6 of 6 each time.
- **Falsified,** each once, the tree restored byte for byte:
  - **37 unit checks,** each failing at its own test: the knot rules (start, gap, count, range,
    fields, none named), sha, mask, floor, the arc, the curve's first point, the edit's params and
    raised strength, `took`, the reload in both directions, `remember` after the edit, the three
    refusals, the restore's check and its raise, the read-back, the fill's hold and its clearing,
    the harness gate, the matrix, the server's rules, op args, arc and schema, and two parity
    pairs.
  - **Strengthened when they first passed:** the 1-knot case was caught by the end rule, so a
    17-knot case was added. The engine refusal was masked by region scope's own refusal, so both
    the test and the probe now require the engine in the details.
  - **The probe:** one build with four mutations (the capability's `since`, no offset, no engine
    check, always reload with the flag ignored) failed the eight new checks and no others.
- **Numbers:** 1033 server tests (+20), 972 plugin tests (+27), probe 182 PASS (+8), 0 FAIL, 25
  MEASURED, 137.9 s with 0 documents open; the journal check read 713 dispatched lines. 20 tools,
  20 schema files, 30 error codes, 33 ops (+1), 13 capabilities (+1), instructions 3,104
  characters, `api_version` 0.4.0.
- **Review (`/code-review high`), 8 findings: 7 fixed and 1 needing no change.**
  - **The sensor length rounded half up,** so knots near the end of a short stroke could land past
    the curve's end and collapse onto it. It now rounds up.
  - **A reload was checked against one digest,** A0's, so a preset Krita filled in on first
    activation could come back from storage as listed, be called lost, and stay held. It now
    accepts A0's digest or the listed one.
  - **A held preset could stay held after the reload its message asks for,** when it held a tweak.
    The hold now also clears once the preset reads clean.
  - **An explicit `useDirtyPresets=true`,** which is Krita's default (`KisConfig`), was refused as
    changed. Now only another value is refused.
  - **The server's taper rules raised on knots past the schema,** through `stroke_op`. They now
    refuse.
  - **The arc was measured three times a stroke,** and `took` now reads `edited`'s numbers.
  - **The dirty read rescanned every widget,** and took the first row with the file name. It now
    keeps one model, and prefers an active preset in an active storage.
  - **No change: a stale A0 flag after activation reloads the preset.** That happens only with
    dirty presets off, and Krita's default is on (`KisConfig::useDirtyPresets`); off is refused.
  - **Falsified:** the round-up, the listed digest, the hold's clean release and the server's
    guard. Each failed at its own test, the tree restored byte for byte. The guard's first
    mutation removed one clause the others still caught; the whole condition, broken, failed.
  - **Checked live:** `install-plugin`, a Krita restart at 0 unsaved, `doctor` 6 of 6.
  - **Numbers after the review:** 1036 server tests (+3), 974 plugin tests (+2), probe 182 PASS,
    0 FAIL, 25 MEASURED, 135.9 s with 0 documents open; the journal check read 713 lines.

---

## L1: Layers

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (its answers), decisions
1, 3, 13; `ARCHITECTURE.md` *The invariants* (4, 5), *Registry, lease and document state*,
*Protection, selections and masks*, *The verification core*, *The undo ledger and history*,
*Reference* (K22, K42); `REVIEW-2026-11-06.md` §5 L1, F7, F8, F10, F12, F13, F22, F25, F26.

**Amended at X1 (2026-11-06), with the owner.** The frame recovers one unpushed step and the
adapter cannot name a detached node across two port calls (F7), so the reorder pushes between its
steps: a port method that calls back after the remove, so the core pushes `steps.of(port.tree())`
on the real intermediate tree, or one that returns a detached handle. `history.LABELS` becomes one
label per step (F12), each measured. `ledger.node_states` gains `parent_id` and `order` (F8), and
its comment changes. The create's `misplaced` cannot take a group's `id_map` (`layers.py:197-205`);
the reorder needs a judge of its own, since siblings' `order` shifts under both parents. Protected
masks never join `hashed` without per-layer channels (F13). The fake learns remove, re-add and
duplicate with a per-command undo, not a snapshot (F22). A duplicate is `destructiveHint: false`
only if the copy is always hidden; a visible option makes it destructive, as M1's `none` mask did
for the create. `undo.grouping`'s note is reworded (F25). "The README's tool list" is struck: README
has none (F26). L1 ships 0.25.0.

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
  - Server instructions, `CHANGELOG.md`: 0.25.0.

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

**Done (2026-11-07, 0.25.0).**
- **Decided with the owner in plan mode:**
  - **The copy is always hidden,** so `krita_layer_duplicate` is additive; no `visible` field.
  - **`derived_from` is in the receipt only,** with the `id_map`; inspect's is on the backlog.
  - **Krita restarts and live runs** were allowed at 0 unsaved, with the Codex agent paused.
  - **A clone's source is refused** by the reorder and the remove, as `clone_source` (Krita's
    source says its clones become paint layers; X1's §5 had assumed full scope would do).
  - **History moves an operation's steps together;** a split is refused with `steps_needed`.
  - **An adversarial review by Opus** found 9 problems, all folded in. The main one: the
    fingerprint takes ranks that leave the global selection's mask out. Others: a hidden copy that
    changed any pixel is refused; the no-op reorder marks and dirties; the clone scan always reads
    clones; the fake's every add is a command acting by id; the reorder's argument twin runs before
    `guarded`; judges compare watched fields, never bounds.
- **Decided with the owner mid-session:** the reorder re-adds each node (below).
- **The go/no-go,** through a temporary `harness.layer_measure` that never shipped, on a harness
  ORA: go. `remove()` read "Remove Layer" and left a wrapper `addChildNode` took back, same id, as
  "Add Layer"; two undos and two redos were exact. `duplicate()` gave new ids throughout, kept
  names, collapsed and pass-through, pushed no step, and its hidden attach left the composite
  unchanged. A clone's source removed turned the clone into a paint layer, undone together. Undoing
  a clear put the selection's mask back at its old index, not on top, as the review had guessed.
- **Shipped:**
  - `krita_layer_duplicate`, `krita_layer_reorder`, `krita_layer_remove`; ops `layer.duplicate`,
    `layer.reorder`, `layer.remove`, `BOUNDED`.
  - Port `remove_node` (each detached node by id), `duplicate_node`, `attach` (the create uses it).
  - `history.LABELS` per step (F12); `node_states` with parent and rank (F8); `nodes.ranks`,
    `children`, `subtree`; `protection.refuse_held`; `history.whole`.
  - `undo.grouping`'s note (F25); a scan holding `setChildNodes` to the create.
  - The fake: command undo for every add and remove, Krita's dismantling remove, ids never reused,
    `copy_visible`, masks shown only through shown layers (F22).
  - `probe/layers.py`, 13 checks, run inside the paint stage under its brush write-back.
- **Amendments:**
  - **A reorder is 1 + its subtree's size steps, not two.** The first live probe found Krita's
    remove takes each node off its own parent: a moved group came back empty, rolled back and
    confirmed by the judge. The owner chose re-adding each node, all native, ids kept. The fake had
    hidden it until it learned the same dismantling.
  - **The duplicate places its copy directly above its source,** with a required `name`; the
    block named no place.
  - **The remove takes `verify`,** as the update does, and keeps the document's last layer.
  - **The probe's checks run in the paint stage,** not a stage of their own, so the MEASURED count
    stays 25.
  - **`api_version` stays 0.4.0;** only tools, fields and a refusal were added.
  - **CHANGELOG's `[0.23.0]` header,** dropped by E1's commit, is restored.
- **Checked live:** Krita restarted at 0 unsaved five times (the instrument, 0.25.0, the dismantling
  fix, the final build twice), `doctor` 6 of 6 each time.
- **Probe runs:** 194 and 1 FAIL (the reorder, before the fix); then one run with an existing edge
  check's top-left stroke painting nothing, 194 and 1 FAIL, untouched by L1 and passing on rerun
  (on the backlog); then 195 PASS twice.
- **Falsified,** each once, the tree restored byte for byte:
  - **48 unit mutations,** 37 in product code (the fingerprint's rank, the global mask in ranks,
    the split rule both ways, the copy's hide, change and leak checks, its placement and id map, the
    held, self and clone refusals, the no-op's marker, the push between steps, the re-adds, the
    judges and leaks of move and removal, the mask, last-layer and reach rules, the root, argument
    and label rules, the fake's undo, a second `setChildNodes`, the server's twins, `STEP_TOOLS`,
    `RECEIPTS`, update's moved phrase) and 11 by breaking the assertion of a test no product
    mutation reached. Every new test failed at its own check at least once.
  - **Two first passed:** the move's judge (no test placed a move elsewhere, so one now does) and
    the reach refusal (its mutation did not parse); both then failed at their own tests.
  - **The probe:** one run with the 13 new assertions broken failed those 13 and no others.
- **Numbers:** 1082 server tests (+46), 1035 plugin tests (+61), probe 195 PASS (+13), 0 FAIL, 25
  MEASURED, 136.3 s with 0 documents open; the journal check read 753 dispatched lines. 23 tools,
  23 schema files, 30 error codes, 36 ops (+3), 13 capabilities, instructions 3,149 characters,
  `api_version` 0.4.0.
- **Review (`/code-review high`), 8 findings: 8 fixed.**
  - **A large group's move could never be undone.** Its 1 + n steps passed history's 50 a call,
    which the split rule then refused at any count, and past Krita's undo stack its rollback could
    not reach its first step. A reorder of more steps than `min(50, undoStackLimit)` is now
    refused as `too_many_nodes`, before anything changes.
  - **A split whose rest lay past history's reach** named a `steps_needed` the next call refused
    too. The refusal now says the op can no longer be moved whole.
  - **A copied group's layers keep their names,** so the guide's advice for an ORA reopen fell
    short. The guide and the duplicate's description now say to rename them, or reopen by KRA ids.
  - **The name's 256-character bound was the schema's alone.** The plugin holds it for the
    duplicate and the create, with a parity pair each.
  - **The reorder walked the whole tree after each add.** It now reads `port.structure`, the
    tree's shape alone, between steps.
  - **The root and not-found refusals were written twice;** `nodes.found` serves the layer ops and
    the update.
  - **Child maps were rebuilt several times per op;** each tree's is computed once and passed on.
  - **A test helper's `or` let its exact clause go unchecked;** it compares the watched fields.
  - **Falsified:** the cap, the unreachable split, the structure reads and the name bound, each
    failing at its own test, the tree restored byte for byte. The rest are refactors under
    existing tests.
  - **Checked live:** `install-plugin`, a Krita restart at 0 unsaved, `doctor` 6 of 6.
  - **Numbers after the review:** 1084 server tests (+2), 1039 plugin tests (+4), probe 195 PASS,
    0 FAIL, 25 MEASURED, 137.3 s with 0 documents open; the journal check read 753 lines.

---

## B1: Document duplicate

**Read:** `FEATURE-recovery-and-construction.md` decisions 1, 3, 12; `ARCHITECTURE.md` *The
invariants* (2, 3, 4), *Documents*, *Registry, lease and document state*, *Previews and the lazy
baseline*, *The save*, *The server*; `REVIEW-2026-11-06.md` §5 B1, F1, F4, F5, F6, F9, F26.

**Amended at X1 (2026-11-06), with the owner.** B1 runs on the save's finisher, which X1a
reshapes first (F1, F4, F5, F6): the finisher's rule says `uncertain` for any failure after an op
that changed something, a finish runs only from the process that made the call, and a retryable
refusal under a derived id runs again. `RECEIPTS` is keyed by bridge op, one tool per op, and the
completeness test holds that (F9): the duplicate takes a distinct first plugin op, or `RECEIPTS`
is keyed by the journal's tool; `Known.finish` becomes a chain (the finish, then the reopen),
each step under its own derived id and keeping the save's identity, and the reopen op joins
`document.save_finish` in the class test (`tests/test_outcomes.py:185`). "A crash between ops
reports `uncertain`" is true only once F1 lands. Its hint is additive only if its finish never
clears the source's `dirty` or `saved_state`, which the save's does (`saving.py:215-218`). "The
README's tool list" is struck (F26). B1 ships 0.26.0.

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
  - Server instructions, `CHANGELOG.md`: 0.26.0.

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

**Done (2026-11-09, 0.26.0).**
- **Decided with the owner in plan mode:**
  - **The hint is additive** (`destructiveHint: false`).
  - **A branch takes its source's mode:** `working_copy` stays `working_copy`, `new` stays `new`.
  - **The maker's poll opens the branch too.** F6's written exception widens from "finishes a
    save" to "finishes a save or a duplicate, placing its file and opening the branch".
  - **Krita restarts and live runs** were allowed at 0 unsaved, with the Codex agent paused.
  - **An adversarial review by Opus** found 3 design faults, 5 gaps and 4 nits, all folded in. The
    main ones: reading protection at the reopen alone could loosen it, since protection drops a
    protected node that has gone; the fake kept layer pixels by id alone, so a branch would share
    its source's; a poll that opens a document needed the owner's word. Others: the open's own
    `not_applied` must never stand; the source's composite may be recomposed by the save's refresh;
    the instructions must not promise both baselines in one render; four docs became false.
- **Shipped:**
  - `krita_document_duplicate`; ops `document.duplicate` (the save's handler with `branch`, F9's
    distinct first op) and `document.duplicate_open`, both `BOUNDED`; the finish reused.
  - `Pending.branch`: what the branch inherits, read in the job that writes the file. The finish
    for a branch clears nothing and records the placed file in `Handle.branches`.
  - `document.duplicate_open {document_id, save_id}` takes no path, so no client can open an
    arbitrary `.kra` directly through it. It inherits the tighter of the snapshot and the source
    now: the union of protected ids within the branch's nodes, the AND of the masks, each flag's
    OR.
  - `Handle.opened_sha256`; the lazy baseline reads against it and no longer needs a source.
  - `opening.opened`, shared by the open and the branch; `opening.Made` made public.
  - The server's `tools/branching.py`: the chain, its own mapper for the open's failure (always
    `uncertain`, with the file's path and hash), the poll; `saving.py`'s finisher takes the tool's
    name and noun, and `derived_operation_id` serves both derived ids.
  - The fake: a reopened KRA keeps its pixels apart from its source's; a placed file reopens as the
    export that wrote its bytes.
  - `probe/branching.py`, 11 checks in the save stage; the read-only refusal check covers the
    duplicate.
- **Amendments:**
  - **The reopen takes a `save_id`, not a path,** and opens only a file the bridge's own finish
    placed. The block named no inputs; a path would have let any client open a `.kra` directly.
    The session's design, approved at plan time.
  - **Inheritance is snapshotted at the save and tightened at the reopen,** not read at the reopen
    alone. Found by the plan review.
  - **The envelope's `document_id` is the source's,** as the contract's draft has it; the branch is
    `data.new_document_id`. The receipt also says the source's `dirty` and `krita_modified`.
  - **The review's large-baseline test was not added.** The preview's pixel budget is existing
    behaviour, held by `test_previews`' two budget tests; only the guide's and the instructions'
    wording follow it.
  - **The bridge contract's op table** was stale at 33 ops and missed L1's three; it now lists 38.
    The marker table gains L1's ops too.
  - **`api_version` stays 0.4.0;** a tool and fields were added.
- **Checked live:** `install-plugin`, Krita restarted at 0 unsaved once, `doctor` 6 of 6.
- **Probe runs:** 206 PASS, 0 FAIL, 25 MEASURED in 147.2 s with 0 documents open. Every node type
  kept its id through the branch: paint, group, transparency mask, filter layer and mask,
  transform mask, clone, local and global selection masks. The journal check read 775 dispatched
  lines.
- **Falsified,** each once, the tree restored byte for byte:
  - **37 unit mutations,** 34 in product code or the fake (the format rule both sides and its
    twin, the guard, the snapshot, the source's dirt from plugin and server, the placed record, the
    flags, the tighter union, the single open, the placed hash, the mask size, the failed open's
    close and its kept file, the fake's apart pixels, the baseline's own hash and its no-source
    rule, the open's hash, the source fields, a save replacing a duplicate, both markers, the
    retry's dedup, own baselines, the created mode, the maker's poll, another's read, the retry
    hint, the open's mapper, the finish's naming, the read's mapping, the unopened receipt) and 3
    by breaking the assertion of a test no product mutation reached (the rerun under its id, the
    kept branch, never overwriting). Every new test failed at its own check.
  - **One first passed:** the retry's dedup, whose random open id the bridge still deduped by the
    open's `request_id`; randomising both, it failed at its own test.
  - **The probe:** one run with the 12 new assertions broken failed those 12 and no others.
- **Numbers:** 1117 server tests (+33), 1063 plugin tests (+24), probe 206 PASS (+11), 0 FAIL, 25
  MEASURED, 147.2 s with 0 documents open; the journal check read 775 dispatched lines. 24 tools,
  24 schema files, 30 error codes, 38 ops (+2), 13 capabilities, instructions 3,322 characters,
  `api_version` 0.4.0.
- **Review (`/code-review high`), 9 findings: 9 fixed.**
  - **An open that never reached the bridge was told to use `krita_document_open`,** though a
    retry under the same `request_id` would open the branch with its protection. An unsent or
    `unregistered` open now says that retry opens it in this Krita session, and
    `krita_document_open` after a restart.
  - **The docs promised a rerun after a failed open that `Jobs` never allows:** a derived id runs
    again only after a retryable refusal. The docs now say so, and a test holds that a failure past
    the marker is the answer for good.
  - **The failed-open test reopened outside `Jobs`,** asserting what the real path cannot do; it
    now checks the close and the kept file alone.
  - **The open's mapped failure kept `rollback_verified: true`** beside a file that stays; it is
    now false.
  - **`source_dirty` was described as "before the call";** both source flags now say they are
    read as the branch opens.
  - **The open hashed the placed file again in full;** `Placed` takes its stat once in place, and
    the open hashes only if it moved.
  - **The identity rule was written twice;** `saving.chained` serves the finish and the open.
  - **The tool and its noun travelled as two loose strings;** `saving.Caller` holds them.
  - **The probe closed two documents twice;** each closes once.
  - **Falsified:** the unsent retry, `rollback_verified` false, the stat skip and the no-rerun
    rule, each failing at its own test, the tree restored byte for byte. The rest are refactors
    and wording under existing tests.
  - **Checked live:** `install-plugin`, a Krita restart at 0 unsaved, `doctor` 6 of 6.
  - **Numbers after the review:** 1119 server tests (+2), 1065 plugin tests (+2), probe 206 PASS,
    0 FAIL, 25 MEASURED, 144.9 s with 0 documents open; the journal check read 773 lines, the two
    double closes gone.

---

## T1: Translate

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (its answers), decisions
3, 15; `ARCHITECTURE.md` *The verification core* (Reach), *The undo ledger and history*; from git
history, `git show 04e9f6c:docs/spec/PDD.md` Q13; `REVIEW-2026-11-06.md` §5 T1, F7, F8, F12.

**Amended at X1 (2026-11-06), with the owner.** The ledger's fingerprint sees only `(id,
blend_mode)` and the selection (F8), so `fromXML`'s own step reads as never pushed: a raise after
it ends `rollback_verified: true` with the step on Krita's stack, or `FOREIGN` and unsafe when the
attach was pushed first. The native route therefore needs the fingerprint to see the mask: a
transform mask's `toXML()` digest read in `_walk` and added to `node_states`, or a projection
witness, and Krita's top label recorded at the start so an unseen step can be told. `fromXML`
plus attach in one port method sits in the two-unpushed window (F7): push between them. Labels
per step (F12), measured. T1 ships 0.27.0 on a native route.

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
  server instructions; `CHANGELOG.md`: 0.27.0 if it ships.

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

**Done (2026-11-11). Go, 0.27.0.**
- **Decided with the owner in plan mode:**
  - **Live runs and Krita restarts** were allowed at 0 unsaved, with the Codex agent paused.
  - **Paint layers and groups,** groups shipping only if they passed every condition. They did,
    pass-through groups too.
  - **X1's top-label record is replaced.** `fromXML`'s step is unnamed, as a selection's is, so its
    label cannot tell the two apart. A params step is instead pushed only once its state is seen to
    move, and cumulative undo is refused.
  - **Inspect reports `translation_px`.**
  - **An adversarial plan review by Opus** found 4 design faults, 9 gaps and 8 nits, all folded in.
    The main ones:
    - a params step pushed without its state moving could undo a selection's step in its place;
    - cumulative undo would merge two translates into one step;
    - `KRA_FIELDS` and `WATCHED` would drift from the params;
    - tree reads before the wait;
    - the go conditions missed the paths the new watched field touches;
    - protection must follow decision 14's line;
    - the instrument needed a redo;
    - a no-go must reinstall the plugin.
- **Decided with the owner at the go/no-go:** go, with `krita_layer_duplicate` refusing a layer
  that holds a transform mask.
- **The go/no-go** ran through a temporary `harness.transform` (make, set, undo, redo, settle,
  read) that never shipped, on harness ORAs through a stdio `serve`.
  - **G1 to G6 held** on a paint layer, a group and a pass-through group: 53 conditions, none failed.
  - **The steps.** The attach is one "Add Layer" step that changes no composite byte. Each
    `fromXML` is one step labelled `""`, and two back to back stay two.
  - **Exact pixels.** A move shifts the projection exactly, with 0 bytes differing. The matrix reads
    (1, 0, 0, 1, dx, dy), and the layers' own pixels never change.
  - **Undo and redo** give back the params' text, the composite (read without a refresh), the tree
    and every node's pixels.
  - **No late change.** Nothing moved 4 s later, inside a job or between jobs.
  - **`toXML` is stable** and unchanged by a fill, a refresh, the cache rebuild, a reorder and a
    remove. A duplicate's mask equals its source's, ours and a rotated one alike.
  - **KRA.** Saves within the 3 s window verify, and the close guard reads the document as saved
    4.5 s later. Reopened, every mask keeps its id and params, and a further move works.
  - **Two surprises.**
    - **Attribute order.** Qt writes `toXML`'s attributes in a hash order that changes per Krita
      session, so the params are parsed by value.
    - **A Krita crash.** Undoing the attach of a copy of a layer holding a transform mask crashes
      Krita in `KisRecalculateTransformMaskJob::run`: 4 times of 4, translated or at identity, and
      after a 4.5 s wait too. 0.26.0 could reach it.
    - Measured safe: removing that copy; removing, or reordering and undoing, a hidden translated
      layer; undoing a translate on a hidden layer.
  - **Recorded:**
    - an ORA drops the mask, so its reopened composite is the unmoved one;
    - a fill lands displaced, with `changed_bounds_px` in the layer's own pixels;
    - a mask added later stays where it is painted;
    - a rotated mask's `toXML` is 932 characters.
  - **Krita crashed 4 times** while the crash was traced. No document of the owner's was open, and
    Krita came back by itself each time.
- **Shipped:**
  - `krita_layer_transform` with `translate`, op `layer.transform` (`BOUNDED`).
  - `bridge_core/transforms.py` (the handler and its judge) and `bridge_core/translations.py` (the
    measured params, written in a fixed order and parsed by value).
  - Ports `create_transform`, `set_transform` and `transform_xml`.
  - `transform_sha256` on every tree node, in the fingerprint, `WATCHED` and `KRA_FIELDS`.
  - `translation_px` on the layer entries of open, inspect and the branch.
  - `layer.translate`, true; the duplicate's `reason: transform_mask`.
  - The fake taught transform masks, their unnamed step, an inert step and a refused one.
  - `probe/transforms.py`, 10 checks; the read-only refusal check covers the translate.
- **Amendments:**
  - **The top-label record is replaced,** on the owner's word (above).
  - **`idempotentHint` is true,** as on every tool, since a retried `request_id` never repeats
    work. The plan said false.
  - **The cumulative-undo refusal moved into `history.py`** and takes a noun. `transforms` importing
    `painting` made an import cycle through `documents`.
  - **The probe's KRA field list leaves the params' hash out.** Inspect, which it compares, reports
    `translation_px` instead.
  - **The block's ORA gate** asserts a refused save, not `expected_losses`. ORA drops the move, so
    the composite check refuses the save (measured).
  - **The duplicate refuses a layer holding a transform mask.** The owner's choice at the
    go/no-go, from the crash.
- **Checked live:**
  - `install-plugin`, then Krita restarted at 0 unsaved: once for the instrument, once for 0.27.0;
  - Krita came back by itself after each crash;
  - `doctor` 6 of 6.
- **Probe runs:**
  - 216 PASS, 0 FAIL, 25 MEASURED in 142.4 s with 0 documents open; the journal check read 795
    dispatched lines.
  - The first run failed 3 checks on the probe's own bug: two fills shared one `request_id`.
- **Falsified,** each once, the tree restored byte for byte:
  - **31 unit mutations in product code:**
    - the moved-state push;
    - the parse's values and numbers;
    - the protected line both ways;
    - two masks, a hidden mask, the total bound, cumulative undo, the types and groups taken;
    - zero and range on the plugin, zero on the server;
    - the judge's drift;
    - the digest in `WATCHED`, the fingerprint and `KRA_FIELDS`;
    - inspect's translation;
    - the duplicate guard, and the guard too wide;
    - the document changed as it began;
    - the own mask found, animated, the labels, the XML's centre;
    - the bounded op, the receipt known, the marker, the confirmed rollback, read-only.
  - **One by breaking an assertion:** the scan's pinned sites.
  - Every one failed at its own test.
  - **The probe:** one run with its 10 new assertions inverted failed those 10 and no others.
- **Numbers:**
  - 1135 server tests (+16), 1125 plugin tests (+60);
  - probe 216 PASS (+10), 0 FAIL, 25 MEASURED, 142.4 s with 0 documents open;
  - 25 tools, 25 schema files, 30 error codes, 39 ops (+1), 14 capabilities (+1);
  - instructions 3,375 characters; `api_version` 0.4.0.
- **Review (`/code-review high`), 6 findings: 6 fixed.**
  - **The params hash compared kinds nobody measured.** `transform_sha256` sat in the fingerprint,
    `WATCHED` and `KRA_FIELDS`, so a warp or liquify mask whose `toXML` round trip differs could
    have failed an owner's save, the close guard or any node op's drift check.
    - The tree now carries `translation_px`: a translate mask's move, parsed by value, and null on
      any other node, a transform mask no translate made included.
    - The fingerprint, `WATCHED`, `KRA_FIELDS` and the probe's KRA list hold it. The port's
      `transform_xml` is gone, and so is the second read of the params.
  - **The parse raised on an `inf` or `nan` centre;** it now refuses one as not a translate's.
  - **The duplicate guard scanned the tree once per node of the subtree;** it builds one map.
  - **The guard spelled the mask's type;** it uses `TRANSFORM_MASK`.
  - **Inspect, open and the branch serialised each mask twice;** they read the tree's
    `translation_px`.
  - **A test's flag was named `hidden`** for the foreign and two-mask cases; it is `two`.
  - **Falsified:** the finiteness check, the move in the fingerprint, `WATCHED`, `KRA_FIELDS` and
    inspect, the guard's map, the tree-read move check and the tree-read own mask. Each failed at
    its own test, the tree restored byte for byte.
  - **Checked live:** `install-plugin`, a Krita restart at 0 unsaved, `doctor` 6 of 6.
  - **Numbers after the review:**
    - 1135 server tests, 1127 plugin tests (+2);
    - probe 216 PASS, 0 FAIL, 25 MEASURED, 144.7 s with 0 documents open;
    - the journal check read 795 lines.

---

## S1: Scale, rotate, shear

Cut first if the round runs long: useful, not yet proven by real use.

**Read:** `FEATURE-recovery-and-construction.md` *The Codex agent's report* (its answers), decisions
1, 3; `ARCHITECTURE.md` *The verification core*, *The undo ledger and history*;
`REVIEW-2026-11-06.md` §5 S1, F8, F10, F12.

**Amended at X1 (2026-11-06), with the owner.** A transform's one step moves bounds and
`offset_px`, which neither the fingerprint nor `watched` sees (F8). It runs as the frame's pixel
step: the target read over the canvas and its old bounds with a witness (`mutation.py:280-293`
supports it), `back` over the watched tree plus bounds, `_moved` allowing `offset_px` on the named
node and its descendants for a group, a mask target refused, its own labels (F12). Its parity gate
uses X1a's helper for schema-side rules (F10). S1 ships 0.28.0.

- **`krita_layer_transform`,** created here, or extended if T1 shipped it, on unprotected layers,
  one operation per call, one undo step, verified in full: `scaleNode`, `rotateNode`, `shearNode`
  (`libs/libkis/Node.cpp:695-743`, `libs/image/kis_image.cc:1000-1296`). Proposed hint:
  `destructiveHint: true`; resampling loses pixels.
- **The filter name is validated by the tool,** because `scaleNode` silently falls back to Bicubic.
- **The guide names duplicating first** (L1) as the reversible route.
- **Docs.** `USER-GUIDE.md`; `ARCHITECTURE.md`: *The undo ledger and history*, the matrix, the
  baseline; server instructions; `CHANGELOG.md`: 0.28.0.

**Gates:**
- `uv run scripts/verify.py`, with these tests: each refusal, parity, and the filter whitelist.
- `probe`: each operation, a leak undone, `krita_history_step` over each, protected bytes unchanged.
- Each new check falsified once.

**Watch for:**
- **Sizes are relative to exact bounds** (`Node.cpp:704`), and rotation pivots on their centre
  (`kis_image.cc:1145-1167`).
- **These are silent no-ops on masks.** Refuse a mask target.
- **`history.LABELS` needs each English label,** measured.

**Done (2026-11-12). 0.28.0.**
- **Decided with the owner in plan mode:**
  - **Scale takes `size_px`,** the new size of the exact bounds, about their centre.
  - **Targets:** a paint layer, or a group of paint layers and groups. Any mask in the subtree is
    refused, to the backlog: the bridge reads a mask's bounds as its layer's, and its selection can
    run past them.
  - **Live runs and Krita restarts** at 0 unsaved, with the Codex agent paused.
  - **An adversarial plan review by Opus** found 7 design faults, 17 gaps and 11 nits, all folded
    in. The main ones:
    - the receipt would have failed its own schema, since `amend_schemas` copied one `data` branch;
    - a mask's own extent is invisible to the bridge;
    - an offset-only no-op would have marked the document unsafe;
    - a fixed filter margin would have failed large upscales;
    - a shear Krita skips would have sealed history;
    - Krita's own menu pushes the bridge's labels;
    - the total read was unbounded;
    - clones were never fed to the refusal, the tree was read before the wait, and nothing
      refreshed after the call.
- **The measurement** ran through a temporary `harness.reshape` (transform, state, read, undo,
  redo, filters) that never shipped, on harness ORAs through a stdio `serve`:
  - **Steps:** each operation is one step, "Scale Layer", "Rotate Layer" or "Shear Layer"; undo,
    redo and a second undo gave back every node's bounds, offset, own bytes and the composite, in
    15 single-layer cases, 6 group cases and 2 under translate masks. Nothing changed 4 s later.
  - **Sense:** positive degrees turn clockwise; a positive x shear moves rows below the centre
    right, a positive y columns right of it down.
  - **The no-op shear:** a shear Krita's `mapRect` keeps pushed no step and changed nothing, at 7
    thresholds; the replica agreed at each.
  - **Offsets:** rotate and shear move a layer's offset, scale does not. A half turn of a flat rect
    changed no byte, bounds or composite, moved the offset and pushed a step.
  - **Bounds:** a scale lands on `size_px` about the centre for all 8 filters on flat paint; an
    unknown filter name gave Bicubic's bytes.
  - **Groups:** a group's bounds are its shown layers'; its layers, a hidden one too, turn about
    its centre. Pass-through and hidden groups held every condition.
  - **KRA:** a verified save after each operation completed. At 4096 x 4096 each operation took
    under a second, a read and hash of 16 Mpx about 0.04 s.
- **Shipped:**
  - `krita_layer_transform` with `scale`, `rotate` and `shear`; `bridge_core/affine.py` (the rules,
    the refusals, the witness rects, the judge and `back`); `transforms.py` sends each type its way.
  - Ports `filter_strategies` and `transform_node`, each libkis call pinned to its one site.
  - `Mutation.run`'s `witness_of`: an op's own pixel witness, pushed or sealed where a target's
    diff is, and used for an unpushed step's rollback.
  - `history.LABELS` keys `layer.transform.scale`, `.rotate` and `.shear`, and a `REVERSED` move of
    one of them stops history as foreign.
  - `layers.refuse_clone_source`, shared and given what Krita does.
  - The receipt's `data` as a flat `anyOf` of four shapes; `amend_schemas` and the copy test take
    every branch. The server sends `filter` "Bicubic" when it is left out.
  - `layer.scale`, `layer.rotate` and `layer.shear`, true.
  - The fake taught the three operations (nearest-pixel remap about the pivot, offsets, labelled
    step, inert, silent no-op) and off-canvas reads.
  - `probe/affine.py`, 10 checks; the read-only refusal check takes a scale too.
- **Amendments:**
  - **The witness is the op's, through a frame callback,** not the frame's one target read over the
    canvas and old bounds: a group's or a layer's own bytes can stay the same while another layer
    or the bounds move, and a rollback would then find no witness and go unsafe.
  - **The witness rect is fixed before the change,** where the plan had none predicted. The first
    probe run failed the leak's rollback on a layer an earlier check had turned: a Bicubic resample
    leaves colour under alpha 0 outside a layer's exact bounds (sampled live: the marker's blue at
    alpha 0 a pixel above them), so the plan's digest, the kept bytes padded with the default pixel,
    was not what a read gives. Each layer's rect is now its bounds and where the operation takes
    them, widened by three source pixels times the scale and four more, read before and after; the
    judge refuses, rolled back, a layer whose new bounds leave it. The sense, order and factor it
    needs are measured.
  - **Hidden groups are taken,** where the plan refused them: their bounds were current after the
    frame's refresh, which comes before the pivot is read.
  - **A `REVERSED` history move of a transform label is foreign** (the review).
  - **The capability set grows by three,** one per operation.
  - **The frame's witness callback is tested through `test_affine.py`** (pushed, sealed, an
    unpushed step's rollback, a raise in the rollback), not apart in `test_mutation.py`.
- **Checked live:**
  - `install-plugin` and a Krita restart at 0 unsaved four times: the instrument, 0.28.0, the
    witness fix, and a comment that moved the source hash;
  - `doctor` 6 of 6.
- **Probe runs:**
  - The first: 224 PASS, 2 FAIL (the leak's rollback after a turn, and its `uncertain` journal
    line), 25 MEASURED.
  - After the witness fix: 226 PASS, 0 FAIL, 25 MEASURED in 257.4 s with 0 documents open; the
    journal check read 841 dispatched lines.
  - The affine checks alone took 3.7 s. The machine ran at a load average of about 3.4, a browser
    renderer near 60% of a core, through both runs; the benchmark and save stages, which S1 does
    not touch, took most of the extra time.
- **Falsified,** each once, the tree restored byte for byte:
  - **42 mutations in product code and the probe's constants:**
    - the rules: the size's minimum, the filter list, rotate and shear of nothing, the type
      dispatch;
    - the refusals: a transform mask in the subtree and on a group above, other kinds, the lock
      flags, styles, clone sources, empty bounds, the same size, cumulative undo, a filter Krita
      lacks, too many nodes, too large;
    - Krita's arithmetic: the `mapRect` rounding and the shear's cross term;
    - the call's start: the bounds compared, and the refusal retryable;
    - the frame: the witness pushed, the unpushed step taken as a pixel one, the re-witness;
    - the judge: offsets loose, the escape, a composite change no layer shows, a sealed step's
      `no_change`, the leak;
    - `back`: the bytes, the offsets loose; the witness rect's reach; the before digest read with
      colour under alpha 0;
    - the history rule, a capability, the marker;
    - on the server: rotate and shear of nothing, the filter default, a schema bound, `amend_schemas`'
      branches, the probe's labels.
  - **One by breaking an assertion:** the scan's pinned sites.
  - Every one failed at its own test.
  - **The probe:** one run with its 10 new assertions inverted failed those 10 and no others.
- **Numbers:**
  - 1152 server tests (+17), 1201 plugin tests (+74);
  - probe 226 PASS (+10), 0 FAIL, 25 MEASURED, 257.4 s with 0 documents open;
  - 25 tools, 25 schema files, 30 error codes, 39 ops, 17 capabilities (+3);
  - instructions 3,371 characters (-4); `api_version` 0.4.0.
- **Review (`/code-review high`), 8 findings: 8 fixed.**
  - **Bounds-dependent refusals read the unwaited first tree,** so a layer Krita was still settling
    could be refused `empty` or `no_change`, not retryable. They now read the tree taken after the
    before-read; bounds that moved since the first read are refused for a retry.
  - **The total read cap guarded bytes no longer kept.** All witness rects together may now take
    four reads (`MAX_TOTAL_PIXELS`), seconds at the measured 0.04 s per 16 Mpx; each still one.
  - **The history rule was a list of three labels.** It is general now: a move reversed after Krita
    named the step as expected on its other side moved another step of that name, so it is foreign,
    not retryable. A step Krita did not take shows another name and stays retryable. A first form,
    any reversed witnessed step, broke that retryable case and was dropped.
  - **The guide misstated what that rule changed;** it says it now.
  - **The fake's `crop` had two paths;** it has one.
  - **The probe's undo-label helper was copied;** `probe/common.py` holds `undo_labels`.
  - **A needless copy of the operation and a wrapped condition** are gone.
  - **Paragraph comments** in `affine.py`, the probe and the fake are one line each.
  - **Falsified:** the refusal on the unwaited read, the total cap, the rule for a stroke and for a
    transform. Each failed at its own test, the tree restored byte for byte.
  - **Checked live:** `install-plugin`, a Krita restart at 0 unsaved, `doctor` 6 of 6.
  - **Numbers after the review:**
    - 1152 server tests, 1204 plugin tests (+3);
    - probe 226 PASS, 0 FAIL, 25 MEASURED, 149.6 s with 0 documents open; the journal check read
      841 lines. The 257 s runs before it were the machine's load.

---

## X2: Architecture review: construction

**Read:** everything: every session's code and tests so far, cold, against the feature file and this
plan.

- Write `docs/spec/REVIEW-<date>.md`, as X1 did: findings only, no product code, no version.
- **Attack in particular:** every new tool against invariants 1, 2, 4, 5 and 9; each op's marker;
  hints against each new tool's worst behaviour; the capability matrix; the instructions' budget.
- In plan mode the owner picks which findings become scope.

**Gates:** `verify` and `probe` as found, recorded in the review's baseline.

**Watch for:** X1's findings the owner left open (its Info items, and F28); check they still
hold. Name functions, not lines, in the amendments: X1 found every line pointer in the later
blocks moved under it (F26).

**Done (2026-11-12, no version).**
- **Decided with the owner in plan mode:**
  - `doctor` and the probe ran for the baseline, at 0 unsaved with the Codex agent paused.
  - The product fixes land in an inserted **X2a**, before V1: X2a 0.29.0, V1 0.30.0. Every finding
    goes there but F10, the fake's per-command pixel undo, which goes to the backlog.
- **The review.** `REVIEW-2026-11-12.md`: 21 findings (1 High, 2 Medium, 18 Low) and 10 Info, each
  verified on the code path at `ac27e19`; §2 holds every invariant to its enforcing site and test;
  §5 reads construction forward against X2a and V1. The read ran twice, by six independent readers
  in two waves of three, the second without the first's notes, but for two exceptions its method
  states.
- **The findings that matter most.**
  - L1's four layer ops and `layer_update` refuse, scope and judge from a tree read before Krita is
    idle (F1). With a change landing at the first wait, a remove takes a protected layer and its
    rollback reverses a correct undo, a duplicate's rollback undoes the attach of a copied transform
    mask (K53's crash), and a region-scope leak is verified. Reproduced on the fake.
  - Parity gaps for the new tools' rules behind the documents' claim (F2).
  - A failure's details name a derived step id `krita_operation_get` refuses (F3).
- **Amendments:**
  - **X2a inserted**, 0.29.0, with the fixes the owner chose; V1 0.30.0, amended. Decided at plan
    time, with the owner.
  - **Two exceptions to the cold second read,** stated in the review: the second outcomes brief
    added three questions from the first wave, and a second frame brief that leaked the first
    wave's questions was stopped and relaunched verbatim. The session's own.
- **Measured,** on Krita 5.3.4.1, commit `ac27e19`:
  - `verify` as found: 6 stages PASS; tests 232.1 s, plugin-tests 28.0 s.
  - `probe` as found: 226 PASS, 0 FAIL, 25 MEASURED in 150.1 s with 0 documents open; the journal
    check read 841 dispatched lines, all settled. `doctor` 6 of 6, 0 open documents, 0 unsaved.
  - Codex's renderer: the stroke's input 4,339 normalised and 2,902 rendered bytes; the
    transform's output 4,975; the longest description 1,103 (the transform).
  - The scale's reads through `affine._rects`, and simulations on the test worlds, each written
    under its finding; a fault injection of 210 raises over the construction ops, all confirmed.
- **Falsified:** nothing; a review adds no check.
- **Numbers:** 1152 server tests (+0), 1204 plugin tests (+0), probe 226 PASS (+0), 0 FAIL, 25
  MEASURED, 150.1 s with 0 documents open. 25 tools, 25 schema files, 30 error codes, 39 ops, 17
  capabilities, instructions 3,371 characters, `api_version` 0.4.0.
- **Review (`/code-review high`), 4 findings: 4 fixed and 0 skipped.**
  - **X2a's gates tested F9 "as chosen",** though F9 is not among its questions. The gate now
    names F9's fixed remedy: an unnamed undo Krita did not take stays retryable.
  - **The table gave X2a fewer decisions than its Read line;** it names 13 and 16 too.
  - **The review used F21 for two findings in one paragraph,** X1's and its own; each is
    qualified.
  - **The session F1 and the finding F1 sat side by side** in the review's preamble; the
    session is named as the frame session.
  - **Falsified:** nothing; the fixes are to documents.
  - **Numbers after the review:** unchanged.

---

## X2a: Review fixes — construction

Inserted by the owner at X2's plan mode, 2026-11-12, from `REVIEW-2026-11-12.md`: the product
fixes the review found, before V1 closes the round. The owner chose the inserted session over
folding the fixes into V1, and sent F10 alone to the backlog.

**Read:** `REVIEW-2026-11-12.md` whole (F1–F9 and F11–F21 are its scope);
`FEATURE-recovery-and-construction.md` decisions 1, 4, 5, 9, 10, 11, 13, 16; `ARCHITECTURE.md` *The
tool contract* (Argument rules are written twice, Codex's limits), *The verification core*, *The
undo ledger and history*, *Painting* (a taper), *The save*, *The server*, *Testing strategy*, and
*Reference* K22, K51, K53, K54.

**Ask at the start of X2a:**
- **F4:** an integral float such as `1.0` refused on the server too, or taken by the plugin as the
  whole number it is.
- **F7:** a taper refused before any paint: keep the seal and say so, or let the change tell the
  frame that nothing began.
- **F16:** a `no_change` transform Krita kept as a step: keep `dirty` and say the step stays, or
  another outcome.
- **F20:** new output fields optional, or the replay rule written beside decision 9.

- **The idle tree** (F1). `layers.create`, `layers.duplicate`, `layers.reorder`, `layers.remove`
  and `layer_update.update` take S1's pattern from `affine.run` and `transforms.translate`: the
  before-read first (a paint-layer create, which has none, refreshes first), the tree read again, a
  retryable refusal if anything watched or a scoped bound moved, and the waited tree passed as
  `before` and to `Mutation.run(tree=...)`. A wait inside `KritaDocuments.tree` is the other route;
  the done-note says which was taken and why. The stroke's and the fill's refusals and scope read
  the same tree, and follow.
- **Parity** (F2, F4). A `refused_alike(..., schema=path)` row for each pair F2 lists;
  `test_the_plugins_bounds_are_the_schemas_limits` takes `MAX_TRANSLATE`, `MAX_SIZE`, `MAX_SHEAR`,
  the knot bounds and `MAX_NAME`; F4's two rules as the owner chose, or listed under "Not held".
- **The chain's details** (F3, F13, F14, F15). `saving.chained` puts the call's own id in
  `details.operation_id` and keeps the step's under another key; a failed layer duplicate names its
  copy; derived request ids take a form no tool input admits, or such agent ids are refused;
  `branching._open_error` reads only `_unregistered` and pre-send failures as unsent.
- **The frame and history** (F5, F7, F9, F16). A first translate refused before its marker when its
  steps pass Krita's undo limit, as the reorder is; F7 and F16 as the owner chose; the fake models
  Krita's empty "Redo ", and `history.step`'s foreign rule takes it into account.
- **Tapers** (F6, F8). `put_back` holds the preset on any raise, `BaseException` included; the
  fake's `edit_preset` and `restore_preset` pass the marker gate; the armed world runs a tapered
  stroke.
- **The scan and the parse** (F11, F12). `Node.remove()` and `Node.duplicate()` pinned to their one
  site each, the `addChildNode` sites listed; the tree's reads under the wait rule;
  `translations.translation` refuses attributes on its outer elements.
- **The probe** (F17). A matrix check for `layer.translate` in `probe/transforms.py` and for
  `layer.scale`, `.rotate` and `.shear` in `probe/affine.py`; a reorder and a remove of a visible
  translated layer, each undone.
- **Descriptions and documents** (F18, F19, F21). The transform's description says where paint
  lands on a translated layer; `size_px` takes the guide's wording; `krita_history_step`'s
  description and the guide's step 8 name the transforms and a first translate's two steps; the
  taper's knots start at 0 and end at 1; `krita_layer_duplicate`'s description names the
  transform-mask refusal; `ARCHITECTURE.md`'s Codex sizes, the ops outside `RECEIPTS`, the journal
  check's 841, the `no_change` transform, the held preset before `_listed`, the parity paragraph and
  "Not held"; `USER-GUIDE.md`'s unfinished-save line; `BACKLOG.md`'s "or stroke", and F10 added.
  CHANGELOG 0.28.0's count stays, since an entry's content is never rewritten.
- **Docs.** `ARCHITECTURE.md`, `USER-GUIDE.md`, `BACKLOG.md`, the server instructions if a line
  moves, `CHANGELOG.md`: 0.29.0, the baseline.

**Gates:**
- `uv run scripts/verify.py`, with these tests:
  - for each of the five ops, a change landing at the first wait refused retryably, changing
    nothing, and the region leak refused;
  - each new parity row, and the bounds test's new constants;
  - the call's own id in a lost finish's and open's details; the copy's id in a failed duplicate;
  - the taper held on an interrupt in its restore; the armed tapered stroke;
  - the translate refused past the undo limit; F7 and F16 as chosen; an unnamed undo Krita did
    not take, under its empty "Redo ", left retryable (F9);
  - the new pins and the wait rule over the tree.
- `probe`: the whole baseline, with F17's checks.
- Each new check falsified once.

**Watch for:**
- **A retryable refusal is a change of nothing,** proven where it is raised: the AST scan finds each
  new one, and `tests/plugin/test_outcomes.py` pins it in `RETRYABLE` with its own test, as S1's two
  are.
- **X1a's two-step tests** (`tests/plugin/test_mutation.py`) pin the rollback's order; they stay
  green.
- **Every schema change moves the Codex sizes.** The stroke's normalised input has 661 bytes before
  Codex strips descriptions; `amend_schemas.py` runs after each.
- **Version first.** The plugin's hash and `serve`'s gate both read it; `install-plugin` and a Krita
  restart at 0 unsaved, the Codex agent paused, before the probe; ask the owner.

**Done (2026-11-13, 0.29.0).**
- **Decided with the owner at the start.** The owner left the block's four questions to this
  session, took the adversarial plan review on Opus, and chose F11's wait inside
  `KritaDocuments.tree` over recording the gap as debt. The live run was approved once the code
  was green.
  - **F4:** both rules tighten on the server. Invariant 8 says inputs are exact and never
    normalised, and decision 10 keeps a rule on both sides, so the server grew the rules the
    plugin already had rather than the plugin losing one.
  - **F7:** the change says nothing began. The taper's two raises come after the preset edit and
    before the paint call, so Krita holds no step; X1's F15 chose the seal for an unnamed step
    that *may* hold, which this is not.
  - **F16:** `dirty` is kept and the receipt says the step stays. Krita keeps "Rotate Layer" and
    the offset it moved, so the bridge's state now agrees with Krita's; the alternative reworks
    how an affine step is classed inside the frame, which X1a's and S1's tests pin.
  - **F20:** the replay rule is written down rather than every new output field going in optional,
    which is what catches a plugin that omits one. Confirmed on the code: a failure's `details` is
    an open object, so F13's and F16's new keys cannot break a replay.
- **What shipped.** Every finding of `REVIEW-2026-11-12.md` but F10, which went to `BACKLOG.md`.
  - **F1, the High.** `mutation.steady` reads the tree again and refuses retryably when anything
    watched or a scoped bound moved, and `Mutation.run` calls it as the last act before the
    marker, after the selection. The five ops, both transform ops and the stroke and fill pass
    the tree they judged by and the ids whose bounds they used. `tree` and `structure` now wait.
  - F2 and F4: parity rows for the taper's schema rules, the translate's and the affine bounds and
    item types, a layer id's form and the whole-number rule; the bounds test took `MAX_TRANSLATE`,
    `MAX_SIZE`, `MAX_TURN`, `MAX_SHEAR`, the knot bounds and `MAX_NAME`.
  - F3, F13, F14, F15: the call's own id in a chained failure's details with the step's beside it,
    the copy named `copy_id`, a derived `request_id` form no agent may send, and an uncertain open
    no longer read as unsent.
  - F5 to F9 and F16: the translate's undo-limit guard, `put_back` holding on any raise, a change
    that never began, the fake's marker gates and its empty "Redo ", a foreign move that needs the
    state to have moved, and a kept `no_change` step.
  - F11, F12: the node calls pinned by site, the wait rule over a node's geometry, and the
    translate's parse refusing attributes on its outer elements.
  - F17: the matrix checks, a visible translated layer reordered and removed with each undone, and
    live cover for F16.
  - F18, F19, F21: the descriptions and every document line F21 named, but CHANGELOG 0.28.0's
    count, which an entry never rewrites.
- **Amendments,** each decided in plan mode with the owner:
  - **F1's check went into the frame, not into each op.** The block and the review put the re-read
    in the five ops. That leaves the window open: `Mutation.run` builds the start fingerprint
    before the marker, and `ledger.fingerprint` reads the selection, which waits, so a change can
    land after an op's own re-read. One place closes it and covers the stroke and the fill too,
    which the block's bullet also names. The adversarial plan review found this in the first draft.
  - **F14's refusal is the server's alone,** so it has no parity row: the plugin receives the
    server's own `:finish` and `:open` ids through the same field and cannot tell them from an
    agent's. Named under *Not held*.
  - **F16's signal is `applied.steps.sealed`,** not the layer's offset: a scale never moves the
    offset (K54), and the fake hard-codes a move for every other kind, so an offset assertion
    would have proved the fake. The step-free affine cases are all refused before the marker.
  - **An extra probe check** gives F16 live cover, since the matrix checks alone would have
    shipped the new `dirty` rule on unit tests.
- **Measured,** on Krita 5.3.4.1, macOS, Apple Silicon, on a Krita restarted that session:
  - `probe`: 231 PASS, 0 FAIL, 25 MEASURED in 153.0 s with 0 documents open; the journal check
    read 846 dispatched lines, all settled. `doctor` 6 of 6, 0 open, 0 unsaved.
  - The waits added to `tree` and `structure` cost nothing a budget sees: H4 idle p95 7.0 ms,
    N-01 p95 0.10 s, N-02 p95 0.32 s, N-09 p95 0.24 s; the paint stage 35.1 s against 33.8 s.
  - F16 live: a half turn of flat paint reads `INVALID_ARGUMENT`, `no_change`, `krita_kept_step`,
    Krita's top step "Rotate Layer", the document dirty, the composite as before.
  - Codex's renderer: the stroke's normalised input 4,378 of 5,000 bytes and rendered 2,941; the
    transform's rendered output 4,975; the longest description 1,202 (the transform).
  - Two probe runs were needed: the first found three checks of this session wrong, not the
    product. A reorder of a translated layer takes three steps, not two, and the affine refusals
    leave their layer holding a transform mask, so the kept-step check now runs before them.
- **Falsified:** all 18 new checks, each broken once and watched fail at its own step. Sixteen by
  a scripted mutation of the site each rests on; two by hand, a stray node copy in the adapter and
  the taper's preset edit moved before the marker.
- **Numbers:** 1176 server tests (+24), 1222 plugin tests (+18), probe 231 PASS (+5), 0 FAIL, 25
  MEASURED, 153.0 s with 0 documents open. 25 tools, 25 schema files, 30 error codes, 39 ops, 17
  capabilities, 28 parity tests (+3 functions), instructions 3,371 characters, `api_version` 0.4.0.

---

## V1: Re-measure, docs, full run, close the round

**Read:** `FEATURE-recovery-and-construction.md` decision 18; `ARCHITECTURE.md` whole;
`docs/USER-GUIDE.md`; `docs/BACKLOG.md`; every done-note in this file.

**Amended at X2 (2026-11-12), with the owner.** X2a comes before it, so V1 cuts 0.30.0. Its
read-through takes `REVIEW-2026-11-12.md` F21's items no X2a change touched; its re-measure reads
the Codex sizes again; the baseline table gains the capability count.

- **Re-measure representative workflows** after the hints and fills, from the journal and the
  client's own records, as counts and timings. That reopens or closes the batch question (decision
  18).
- **Docs.** `ARCHITECTURE.md` and `USER-GUIDE.md` read through whole; "Phase 1" language corrected
  where it is no longer true; the README; `CHANGELOG.md`: 0.30.0; the baseline.
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
