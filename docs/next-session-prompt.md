Read `FEATURE-recovery-and-construction.md` *The Codex agent's report* (its answers), decisions 3,
15; `ARCHITECTURE.md` *The verification core* (Reach), *The undo ledger and history*; from git
history, `git show 04e9f6c:docs/spec/PDD.md` Q13; `REVIEW-2026-11-06.md` §5 T1, F7, F8, F12; then
CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline, your block in
docs/spec/SESSIONS.md and B1's done-note, then this file, and do Session T1: translate, on a native
route or not at all. Release 0.27.0 if it ships.

## State you need that is not in the specs

- **Round 2 is recovery and construction.**
  - Done: R1, R2, R3, D1, F1, C1, M1, X1, X1a, E1, L1 and B1.
  - Remaining, in order: T1, S1, X2 and V1.
- **B1 shipped 0.26.0.** The versions stand as the table says: T1 0.27.0, S1 0.28.0 and V1 0.29.0.
  T1 without a native route ships no version, and S1 and V1 move down by one.
- **B1 and its review fixes are pushed** (9 findings, all fixed). `origin/main` holds everything
  through "review: an unsent branch open was told to reopen the file, and 8 smaller". List
  `origin/main..HEAD` before any push, and push only on the owner's approval.
- **What B1 left that later sessions meet:**
  - **38 bridge ops;** `tests/plugin/test_outcomes.py` holds the count. `BOUNDED` is 17: the
    mutating tools' ops plus `document.save_finish` and `document.duplicate_open`, the two sent
    under derived ids.
  - **The instructions are 3,322 characters,** 774 spare; `SPARE_FLOOR` holds 700, leaving 74. A
    T1 line must fit in that, or move a rule into a description first.
  - **The fake keeps a reopened KRA's pixels apart** (`FakePort.own`, `_buffers`, `_pixels`):
    route any new pixel access through those two helpers, never `self.buffers` directly.
  - **A placed file reopens in the fake** as the export that wrote its bytes (`exported`, by
    SHA-256; each zip carries a serial).
  - **`opening.opened`** is the open's shared show-and-check; **`Handle.opened_sha256`** is what
    the lazy baseline reads against.
  - **`saving.chained`** keeps a chained step's answer under the call's own ids, and
    **`saving.Caller`** names the tool a finish answers for: a new chained step uses both.
  - **A derived id reruns only after a retryable refusal;** any other failure is its answer for
    good, so a step's message must not promise a retry it cannot give.
  - **13 capabilities;** B1 added none.
- **What turned out wrong or harder:**
  - **Protection drops a protected node that has gone,** so "protection only tightens" does not
    make a later read of it at least as tight as an earlier one. B1 snapshots and unions.
  - **A random operation id alone does not defeat the bridge's dedup:** a derived step's
    `request_id` dedups it too. A falsification of a derived id must change both.
  - **The architecture's op and marker tables had drifted** since L1; B1 fixed them. Check them
    when adding ops.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call:** Opus at X1a, E1, L1 and B1. Propose one when a plan
    reworks a heavily tested path, and ask which model.
  - **Live runs** were allowed at 0 unsaved with the Codex agent paused, for B1; ask again.
- **Baseline** (ARCHITECTURE's table, v0.26.0):
  - `verify`: 6 stages, all PASS; 1119 server tests and 1065 plugin-core tests, 0 skipped;
  - `probe`: 206 PASS, 0 FAIL, 25 MEASURED, 145 s with 0 documents open, the journal check reading
    773 dispatched lines;
  - 24 tools, 24 schema files, 30 error codes, 38 bridge ops, 13 capabilities, instructions 3,322
    characters.
- **Not done:** nothing from B1's block.

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
  A test that spawns `serve` reads the files as they are mid-run: do not edit while `verify` runs.
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
  - Mind the stack earlier checks leave.
  - A stroke under `preserve_composite_alpha` must land where the composite is already opaque.
- **Falsifying by test name:** a pytest `-k` with spaces selects nothing. A mutation that leaves
  a file unparsable fails collection, not the test: check each mutation's run named its test.
- **A test that polls a save or a duplicate must poll from the server instance that made it.**
- **T1's own traps:** the block's *Watch for*. The fingerprint must see the transform mask (F8),
  and `fromXML` plus attach sits in the two-unpushed window (F7).
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
