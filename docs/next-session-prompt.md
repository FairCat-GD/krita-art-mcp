Read docs/spec/SPEC.md §1 (decisions 20, 27) and §5 (invariants 5, 6), docs/spec/PDD.md Part 4
(`krita_layer_update`; `krita_paint_stroke`, *Per-stroke verification*) and Part 8
(*Verification*, K13, K22, K42, K43, K44), docs/spec/REVIEW-2026-10-24.md (F5, F19, F25),
CLAUDE.md, then this file. Then do Session 8 of docs/spec/SESSIONS.md: the verification core, and
layer_update, with review 6's amendments to its block. Release 0.8.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 7 and 6a are done; 8 to 15 remain, releasing
  0.8.0 to 0.13.0.
- **The push status.** `origin` is the private GitHub repository `FairCat-GD/krita-art-mcp`.
  `origin/main` holds everything through session 6a's review commit (`524775d`); session 7's two
  commits (`d188986` and its review commit) are local. List `origin/main..HEAD` before any push.
- **What 7 built that 8 stands on** (block 7's done-note has the detail):
  - **The ledger** (`bridge_core/ledger.py`): `Step{op, operation_id, label, before, after,
    region}`, `Ledger.push(step, limit)`, `rolled_back()`, `seal()`, `undo_available()`, and
    `fingerprint(port, document)` (node ids without the root's selection masks, plus the
    selection's hash). `region` is the canvas rect a step changed; strokes are the first steps to
    set it, and history already reads and hashes it.
  - **The rollback primitive** (`bridge_core/history.py`): inside `in_front(port, document)`,
    `move(port, handle, step, UNDO)` checks the top label and the fingerprint, undoes, and confirms
    by the Redo label and the fingerprint; it reverses once, else marks the handle unsafe.
    `layer.create` shows the whole pattern: push the step, `move` it back, `rolled_back()`, restore
    `dirty` from `before_change()`'s return on a confirmed rollback, `ROLLBACK_FAILED` otherwise.
    Block 8's F25 contract is built: a handler calls `handle.before_change()` right before its first
    libkis mutation (it also stamps `changed_at` through `touched()`), and `guarded` has no
    `dirties`.
  - **Labels** (`history.LABELS`, measured on 5.3.4.1): "Add Layer" for `addChildNode`; `""` for
    `setSelection`, which pushes an unnamed step. Krita keeps Redo enabled as "Redo " even with
    nothing to redo, so an empty label confirms nothing by itself. Read a label only after
    `_flush()` (`QCoreApplication.sendPostedEvents()`) with the document's view in front: straight
    after a push it was stale in 1 of 7 reads. `harness.undo_labels` returns the raw action texts,
    for measuring `setBlendingMode`'s label.
  - **The allowed mask** is `Handle.allowed_mask`: bytes, one per canvas pixel, 255 where changes
    are allowed, or None for the whole canvas; `allowed_summary`, `preserve_composite_alpha` and
    `preserve_canvas` sit beside it. The core reads a region of it by row slices.
  - **K46:** `nodes.unmasked_view(port, document)` wraps any composite read or export.
  - **Masks from the server** are one per request (`mask-<request key>-<sha256>.a8`), taken by the
    plugin before any refusal (`bridge_core/masks.py`) and discarded by the server after any final
    outcome (`tools/changes.settle_masks`).
  - **F2:** reads carry `ephemeral`, but only to a bridge whose `bridge.json` says
    `ephemeral_reads: true`.
- **What the specs said that turned out otherwise** (block 7's amendments):
  - `addChildNode(node, None)` puts the node on top, so `above_id: null` means on top.
  - `addChildNode` makes the new layer active.
  - A script cannot make the global selection's own mask active (`setActiveNode` leaves the layer
    active), so K46's global branch is held by unit tests.
  - **Krita crashes when a document closes within about 0.5 s of a node change** (a selection
    change, at least): `KisNodeModel::processUpdateQueue`, a null pointer from the layer docker's
    update timer, at the first iteration of two loops. `bridge_core/closing.py` decides the wait:
    `SETTLE_S` (0.5 s) for the document in front (the one the docker shows) or a failing op's
    discard, else what is left of it since `changed_at`. The adapter's `_settle` lets Krita's
    timers run with user input held back (the shim's `EXCLUDE_USER_INPUT` is the plugin's one Qt
    enum). The probe checks five quick closes, and now takes about 38 s, since each close of a
    document in front waits.
- **Baseline** (session 8 moves it only by what it adds):
  - `verify`: 6 stages, all PASS;
  - 410 server tests passed, 0 skipped;
  - 364 plugin-core tests passed, 0 skipped;
  - `probe`: 66 PASS, 0 FAIL, 21 MEASURED, about 38 s;
  - 15 registered tools; 19 schema files; instructions 2,620 characters (F5: session 8 adds at most
    300 net).
- **Not done:**
  - **The owner's roots.** `doctor` step 6 FAILs with "no roots" until the owner runs
    `roots add`. No session runs it, and the probe needs no roots.
  - **By hand** (in `docs/BACKLOG.md`): N-03 in Activity Monitor; whether a K46 switch visibly
    moves the tab; the overlay in the mask display mode; K46 with the global selection's mask.

## Watch for

- **The standing traps:**
  - **Never `git checkout <path>`.** Stage explicit paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it for the project.
  - **The owner's Krita is live.** No session touches their documents. Restart Krita only when
    `doctor` reports 0 unsaved documents, and ask the owner first; another agent may be working.
  - **Nothing private in any file or commit message** (`CLAUDE.md`).
- **layer_update changes nodes, and a close straight after a node change crashed Krita.** Every
  handler that changes a node calls `before_change()` (a harness op, `touched()`), so the close's
  settle covers a document behind too. Watch for any other path that removes a document's view
  soon after a change.
- **The scan bans every `.apply` attribute,** not only `Filter.apply`: name no function `apply`.
- **Krita's cumulative undo setting** (off by default) would merge steps; history would then refuse
  them as steps the bridge did not make. Measure it if blend changes behave oddly.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor`
  step 5 passes, a version bump included.
- **Falsify each new check once.** The scratchpad driver of 6a and 7 works: break one line, run
  only its test, count only a pytest exit of 1, copy the file back. A live check needs a server
  break, or a plugin build and a restart; batch independent plugin breaks into one build, and
  order probe checks so one check's side effects (a harness op that seals history) cannot mask
  another's break.
- **The probe's export can answer `BUSY`** when Krita's autosave holds the harness document; a rerun
  passes.
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
