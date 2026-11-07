Read `FEATURE-recovery-and-construction.md` decisions 1, 3, 12; `ARCHITECTURE.md` *The
invariants* (2, 3, 4), *Documents*, *Registry, lease and document state*, *Previews and the lazy
baseline*, *The save*, *The server*; `REVIEW-2026-11-06.md` §5 B1, F1, F4, F5, F6, F9, F26; then
CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline, your block in
docs/spec/SESSIONS.md and L1's done-note, then this file, and do Session B1: document duplicate.
Release 0.26.0.

## State you need that is not in the specs

- **Round 2 is recovery and construction.**
  - Done: R1, R2, R3, D1, F1, C1, M1, X1, X1a, E1 and L1.
  - Remaining, in order: B1, T1, S1, X2 and V1.
- **L1 shipped 0.25.0.** The versions stand as the table says: B1 0.26.0, T1 0.27.0, S1 0.28.0
  and V1 0.29.0.
- **L1 and its review fixes are pushed** (8 findings, all fixed). `origin/main` holds everything
  through "review: a large group's move could never be undone, and 7 smaller". List
  `origin/main..HEAD` before any push, and push only on the owner's approval.
- **What L1 left that later sessions meet:**
  - **A reorder is 1 + its subtree's size undo steps.** Krita's "Remove Layer" takes each node of
    a subtree off its own parent, so `addChildNode` brings back the top alone (measured). The
    reorder re-adds each node, pushing each step as Krita takes it, reading `port.structure`
    between steps. A move of more steps than `min(50, undoStackLimit)` is refused as
    `too_many_nodes`.
  - **History moves an operation's steps together** (`history.whole`): a count that would split
    one is refused with `steps_needed`. T1's and S1's multi-step ops get this for free.
  - **The fingerprint is `(id, blend, parent, rank)`;** ranks leave the global selection's mask
    out (`nodes.ranks`). T1's transform mask still needs its own digest (F8).
  - **`history.LABELS` is one tuple per op,** a label per step (F12).
  - **The fake's adds and removes are commands acting by id;** selections and strokes are still
    snapshots. Its remove dismantles a subtree as Krita's does.
  - **36 bridge ops;** `tests/plugin/test_outcomes.py` holds the count.
  - **The instructions are 3,149 characters,** 947 spare; `SPARE_FLOOR` holds 700, leaving 247.
  - **13 capabilities;** L1 added none.
- **What turned out wrong or harder:**
  - **The fake hid the dismantling.** Unit tests passed a group move that real Krita broke; the
    probe caught it. Teach the fake what Krita does before trusting a green suite.
  - **An existing edge check's top-left stroke once painted nothing,** in one probe run of three.
    Untouched by L1; on the backlog.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call:** Opus at X1a, E1 and L1. Propose one when a plan reworks
    a heavily tested path, and ask which model.
  - **B1's hint is proposed additive;** confirm at plan time, as the block says.
- **Baseline** (ARCHITECTURE's table, v0.25.0):
  - `verify`: 6 stages, all PASS; 1084 server tests and 1039 plugin-core tests, 0 skipped;
  - `probe`: 195 PASS, 0 FAIL, 25 MEASURED, 136 s with 0 documents open, the journal check reading
    753 dispatched lines;
  - 23 tools, 23 schema files, 30 error codes, 36 bridge ops, 13 capabilities, instructions 3,149
    characters.
- **Not done:** nothing from L1's block. What is left of layers is on `BACKLOG.md`: several ids per
  call, masks moved on their own, clone sources, `derived_from` in inspect, a copy placed elsewhere,
  a move of more than 49 nodes.

## Watch for

- **The standing traps:**
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit
    with `git commit -F`, then delete the draft.
  - **Never `git checkout <path>`.** Falsify by copying the file aside and back. Stage explicit
    paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv is at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it for the project.
  - **The owner's Krita is live.** No session touches their documents.
    - Restart Krita only when `doctor` reports 0 unsaved documents, and ask the owner first.
    - `osascript` quitting Krita reports "User canceled" yet Krita quits. Wait for the process to
      go, then a few seconds more, because `open` straight after fails with -600.
    - After a crash, Krita came back within seconds without being asked. Check `pgrep -x krita`
      before starting it.
  - **Krita can start with a dialog open.** It then refuses every document call with
    `KRITA_MODAL_DIALOG`; ask the owner to close it, then rerun.
  - **The probe refuses to run its document checks while any document is unsaved.** Ask the
    owner to save, then rerun.
- **The term list is not empty.** `~/.config/hygiene/terms.txt` holds 75 words. Never assume its
  size, never print a term, and ask before any write to it.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe or measurement run.
- **A client's `serve` runs this checkout as it stands.** Keep the tree working between edits.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor` step
  5 passes. Bump the version first: the plugin's hash and `serve`'s gate both read it.
- **A measurement instrument:**
  - It is easiest as a temporary op in the handlers that have what it needs, gated to harness
    documents like `harness.*`, calling the adapter methods that will ship.
  - Its driver opens an ORA fixture under `<data dir>/harness/` through a stdio `serve`, and keeps
    that `serve`'s data dir out of any folder it deletes.
  - A capture over 1600 px needs `max_px`.
  - Never run it alongside the probe, which sweeps the harness folder.
- **Before the probe's paint checks, these stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber` and
  `c) Pencil-3 Large 4B`.
- **Brush state is window-wide (K3).** A scratchpad driver must read `harness.brush_state` first,
  from a document in the harness folder, with every preset it will activate, and write it back.
- **Probe checks:**
  - Clear a selection only after any undo the check makes.
  - A check that compares a composite needs a layer unlike what lies under it.
  - A refusal check must name the rule's own detail.
  - Mind the stack earlier checks leave: L1's leak check first moved a layer whose change an
    earlier move had already covered.
- **Falsifying by test name:** a pytest `-k` with spaces selects nothing. A mutation that leaves
  a file unparsable fails collection, not the test: check each mutation's run named its test.
- **A test that polls a save must poll from the server instance that made it.**
- **B1's own traps:** the block's *Watch for*. The save's finisher, `RECEIPTS` keyed by op, and the
  derived ids all widen; the source's dirt must stay as it was.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
