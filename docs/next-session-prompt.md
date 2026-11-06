Read `FEATURE-recovery-and-construction.md` *The Codex agent's report* (its answers), decisions 1,
3, 13; `ARCHITECTURE.md` *The invariants* (4, 5), *Registry, lease and document state*,
*Protection, selections and masks*, *The verification core*, *The undo ledger and history*,
*Reference* (K22, K42); `REVIEW-2026-11-06.md` §5 L1, F7, F8, F10, F12, F13, F22, F25, F26; then
CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline, your block in
docs/spec/SESSIONS.md and E1's done-note, then this file, and do Session L1: layers (duplicate,
reorder, remove, group). Release 0.25.0.

## State you need that is not in the specs

- **Round 2 is recovery and construction.**
  - Done: R1, R2, R3, D1, F1, C1, M1, X1, X1a and E1.
  - Remaining, in order: L1, B1, T1, S1, X2 and V1.
- **E1 went: 0.24.0 shipped `dynamics`.** The versions stand as the table says: L1 0.25.0, B1
  0.26.0, T1 0.27.0, S1 0.28.0 and V1 0.29.0.
- **E1 is committed locally, with its review commit.** `origin/main` ends at X1a's review. List
  `origin/main..HEAD` before any push, and push only on the owner's approval.
- **What E1 left that L1 meets:**
  - **The hold.** `held` sits beside `activated` in `painting.handlers`. A preset a taper could
    not put back is refused by every stroke and fill until its digest reads as before.
  - **The fake.** `FakePort.resources` links the fake port to `FakeResources`, as the view's preset
    and the stored one are one object (K51). `restore_keeps_edit` and `fail["edit_preset"]` /
    `fail["restore_preset"]` inject faults.
  - **33 bridge ops**, `harness.preset_dirty` the new one. `harness.handlers` takes an optional
    `ResourcesPort`. `tests/plugin/test_outcomes.py` holds the count: each new op moves it.
  - **The instructions are 3,104 characters,** 992 spare. `SPARE_FLOOR` holds 700, leaving 292 for
    the four sessions after E1, so keep L1's line short or move a rule into a description.
  - **13 capabilities.** `tests/plugin/test_bridge_core.py` and `krita_server_info.json`'s enum
    list them.
- **What turned out wrong or harder:**
  - **Krita's Distance sensor counts from the canvas origin** in a scripted stroke. Every taper is
    shifted by |start| (K51).
  - **A data() call on another docker's Qt model crashed Krita.** Ask only resource views and
    models, by class name.
  - **`set_brush` alone dirties some stock presets** (a build-up and an image tip), not others.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call:** Opus at X1a and E1. Propose one when a plan reworks a
    heavily tested path, and ask which model. L1's reorder reworks the frame's two-step path.
  - F28 stays a fix, with `api_version` 0.4.0.
- **Baseline** (ARCHITECTURE's table, v0.24.0):
  - `verify`: 6 stages, all PASS; 1033 server tests and 972 plugin-core tests, 0 skipped;
  - `probe`: 182 PASS, 0 FAIL, 25 MEASURED, 138 s with 0 documents open, the journal check reading
    713 dispatched lines;
  - 20 tools, 20 schema files, 30 error codes, 33 bridge ops, 13 capabilities, instructions 3,104
    characters.
- **Not done:** nothing from E1's block. What is left of tapers is on `BACKLOG.md`: other sensors,
  combining with a preset's own, mask paint, the other dirty-presets setting, and a probe check of
  the reload route.

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
    documents like `harness.*`.
  - Its driver opens an ORA fixture under `<data dir>/harness/` through a stdio `serve`, and keeps
    that `serve`'s data dir out of any folder it deletes.
  - A capture over 1600 px needs `max_px`.
  - Never run it alongside the probe, which sweeps the harness folder.
- **Before the probe's paint checks, these stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber` and
  `c) Pencil-3 Large 4B`.
- **Brush state is window-wide (K3).** A scratchpad driver must read `harness.brush_state` first,
  from a document in the harness folder, with every preset it will activate, and write it back.
  Writing it back can leave a preset dirty in memory; a Krita restart clears that.
- **Probe checks:**
  - Clear a selection only after any undo the check makes. Otherwise the undo takes back the
    clear, and the selection confines every later check.
  - A check that compares a composite needs a layer unlike what lies under it, or hiding it
    changes nothing visible.
  - A check that reads a stroke's middle must name the row it stroked along. A median of the
    changed rows can land on the antialiased edge, one row off.
  - A refusal check must name the rule's own detail. E1's engine refusal first passed on region
    scope's own refusal, with the same code.
- **Falsifying by test name:** a pytest `-k` with spaces selects nothing, and "no tests ran" reads
  as a failure. Use parametrize ids without spaces, and check each run selected a test.
- **A test that polls a save must poll from the server instance that made it.** Each
  `world.server()` is a new process to the poll rule, so a second instance only reads.
- **L1's own traps:** the block's *Watch for*.
  - Two undo steps from one op: a failure between them must still confirm.
  - `setChildNodes` has no undo. Never use it for a reorder.
  - Measure that `addChildNode` takes a detached node's wrapper back after `remove`.
  - A copied group's masks are the agent's own as copies.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
