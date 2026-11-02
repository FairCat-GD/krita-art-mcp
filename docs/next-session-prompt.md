Read `docs/spec/FEATURE-recovery-and-construction.md` (*The Codex agent's report*: P1 and regression
coverage; *What the intake measured*: The bug; decisions 4–9); `docs/ARCHITECTURE.md` *The bridge
contract* (Dedup and retention, A 404 while following a call), *The tool contract* (The envelope,
The error codes), *The data layer* (The journal), *Bridge and jobs*, *Registry, lease and document
state*, *Documents*, *The verification core*, *Painting*, *The undo ledger and history*, *The save*,
*The server*; then CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline, your block
in docs/spec/SESSIONS.md, then this file, and do Session R1: mutation recovery. R1 has six parts:
- the bounds: `changed_bounds_px` canvas-clipped, and a nullable `layer_bounds_px`;
- a change marker on each path through each of the 11 mutating ops, read by `Jobs._run`;
- verified cleanups, and `BUSY` made true;
- the server keeps identity, in `_checked` and `journaled`, and at the sites that turn applied work
  into a failure;
- `details.outcome`, typed in the shared error shape;
- `krita_operation_get`'s `outcome`, `receipt_valid` and `receipt_problem`.

Release 0.17.0.

## State you need that is not in the specs

- **Round 2 is recovery and construction.** The intake is done. R1, R2, D1, F1, C1, M1, X1, E1, L1,
  B1, T1, S1, X2 and V1 remain, in that order.
- **The intake is committed locally, not pushed.** `origin/main` holds everything through "docs:
  keep history as it is, and say what it holds". List `origin/main..HEAD` before any push.
- **What the feature file does not spell out for R1:**
  - The marker lives on the `Call`, which `move()` does not take, so `history.step`'s needs a flag
    or a callback. A marker cannot simply go at `before_change`: `protection.set`, the save's file
    work and a registration never pass through it, and `move()` calls it during confirmed rollbacks.
  - An open or create that keeps a document after a failed close already sets `details.document_id`
    (`opening.py:51-54`, `documents.py:41-43`). That key is what marks it `uncertain`.
  - After the move, `BUSY`'s raise sits past the save's marker. It is `not_applied` by the retryable
    rule and the verified cleanup, not by phase.
- **The evidence stays outside the repository.** The failing request's geometry is in the feature
  file; rebuild it fictionally and copy no receipt, path or id. The Codex agent holds the bundle and
  the agreed record.
- **Decisions written down nowhere else:**
  - The working paper `docs/PHASE-2-REVIEW.md` and the shared folder are in the Trash, as the owner
    approved. The paper's review column came back empty; the agent's report and answers replaced it.
  - Whether the owner has set `default_tools_approval_mode` in Codex is open. It is theirs to
    choose, and R2 asks. The feature file says what it removes.
- **The first review of this plan rewrote it, and a second tightened it.** Their findings are in the
  decisions and the blocks. Do not reopen them: `Document.clone()`, `Node.move` as a fallback, a
  change counter as proof.
- **Baseline** (ARCHITECTURE's table, v0.16.0): `verify` 6 stages, all PASS; 670 server tests and
  665 plugin-core tests, 0 skipped; `probe` 131 PASS, 0 FAIL, 23 MEASURED, about 114 s with 0
  documents open; 19 tools; 19 schema files; 30 error codes; 31 bridge ops; instructions 3,906
  characters. R1 moves the test and probe counts and, by decision 4's typing, every schema file's
  error shape; no tool, op or error code is added.
- **Not done:** nothing from the intake. It wrote no product code.

## Watch for

- **The standing traps:**
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit
    with `git commit -F`, delete the draft.
  - **Never `git checkout <path>`.** Stage explicit paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it for the project.
  - **The owner's Krita is live.** No session touches their documents. Restart Krita only when
    `doctor` reports 0 unsaved documents, and ask the owner first. `osascript` quitting Krita
    reports "User canceled" yet Krita quits: wait for the process to go, then a few seconds more,
    because `open` straight after fails with -600.
- **The term list is not empty.** `~/.config/hygiene/terms.txt` holds 75 words. Never assume its
  size, never print a term, and ask before any write to it. Hygiene does not read old file versions.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe run: a dialog it raises refuses every call until it closes, and fails
  what the run overlaps. Done-notes record what was measured, never its work or its documents.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor` step
  5 passes. That includes a version bump, which changes the plugin's hash, so bump before the first
  live run. **`serve` refuses a plugin of another version:** a stale plugin fails every tool with
  `PROTOCOL_MISMATCH` until Krita restarts.
- **A release restarts the MCP client too,** so tell the owner before the restart.
- **Before the probe's paint checks, the stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current brush
  and Krita's preset history. The probe saves and writes back the brush state. A scratchpad driver
  must do the same: `harness.brush_state` read first, from a document in the harness folder (a
  created document has no path, so the read fails), and stop if the read fails.
- **Krita's memory grows across large opens and saves.** Restart it, at 0 unsaved, before measuring.
- **R1's own traps:**
  - **`uncertain` must stay rare.** It settles as `UNKNOWN`, skips the roots precheck on a retry and
    dedups to the same failure for the Krita session. `uncertain` on an ordinary refusal means a
    misplaced marker.
  - **`tests/fixtures/fake_krita.py` has to model bounds off the canvas,** and stays valid on 3.10.
  - **jsonschema's message quotes the whole instance,** which is how the receipt leaked into
    `reason`.
  - **`scripts/amend_schemas.py` writes the error shape.** Change it there, and run it.
- **The instructions have 190 characters to spare.** R1 may use 150; D1 frees more.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
