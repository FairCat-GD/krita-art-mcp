Read `docs/spec/FEATURE-recovery-and-construction.md` (*What the intake measured*: Where the time
went; decisions 1, 2); `docs/ARCHITECTURE.md` *The tool contract*, *The data layer* (The journal),
*Reads, and K46* (Capture), *Previews and the lazy baseline*; then CLAUDE.md, docs/ARCHITECTURE.md's
overview, invariants and baseline, your block in docs/spec/SESSIONS.md and R1's done-note, then this
file, and do Session R2: truthful hints, timing, Hamming. R2 has three parts:
- hints: the five `annotations` flip to `destructiveHint: false`, with a table test;
- timing: a `finished` journal line carries the server's own `elapsed_ms`;
- Hamming: `hamming` joins `imaging.FILTERS` and both schemas' `filter` enums.

Release 0.18.0. **Ask at the start of R2:** has the owner run a Codex session with
`default_tools_approval_mode`?

## State you need that is not in the specs

- **Round 2 is recovery and construction.** R1 is done. R2, D1, F1, C1, M1, X1, E1, L1, B1, T1, S1,
  X2 and V1 remain, in that order.
- **Nothing from R1 is pushed.** `origin/main` stops at "review: a branch could not read its own
  baseline, and 9 smaller". List `origin/main..HEAD` before any push.
- **What R1 left for later sessions:**
  - **A new mutating op goes in `jobs.BOUNDED`,** with a `call.mark()` before its first change on
    every path. A test holds the set to the tools' `readOnlyHint`. F1 makes the markers structural.
  - **`readOnlyHint` is now load-bearing.** `_checked` reads it to decide what is mutating, and R2
    changes the neighbouring `destructiveHint`. Leave `readOnlyHint` alone.
  - **The journal's finished line is read back** by `Journal.finished_line`. An added field needs no
    version, but check the reader, as the block says.
  - **`changed_bounds_px` counts bytes,** so it can pass a selection's edge by colour under alpha 0,
    while no alpha does. The probe holds alpha to the selection.
- **The evidence stays outside the repository.** The Codex agent holds the bundle.
- **Decisions written down nowhere else:** whether the owner has set `default_tools_approval_mode` in
  Codex is open, and R2 asks.
- **Baseline** (ARCHITECTURE's table, v0.17.0): `verify` 6 stages, all PASS; 731 server tests and 775
  plugin-core tests, 0 skipped; `probe` 142 PASS, 0 FAIL, 23 MEASURED, about 120 s with 0 documents
  open; 19 tools; 19 schema files; 30 error codes; 31 bridge ops; instructions 3,970 characters.
- **Not done:** nothing from R1's block.

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
- **R2's own traps:**
  - **The five hints buy little by themselves,** about 4 of 47 minutes. Say so.
  - **If the 2 s stays on the five,** the inference was wrong. Stop and report; do not widen decision
    1.
  - **The journal reader accepts version 2 only.** Check that an added field needs no version.
- **The instructions have 126 characters to spare.** D1 frees more.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
