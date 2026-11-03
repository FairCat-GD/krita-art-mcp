Read `FEATURE-recovery-and-construction.md` *The Codex agent's report* (Input and schema
discoverability), decisions 9, 11; `ARCHITECTURE.md` *The tool contract* (Schemas are data, Which
forms reach Codex, The instructions), *Reads, and K46* (Capture, Sample); `docs/USER-GUIDE.md`
*Phase 1's limits*; then CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline, your
block in docs/spec/SESSIONS.md and R3's done-note, then this file, and do Session D1: Discovery.
D1 has six parts:
- `krita_sample` gains `color`, the shape `brush.color` takes, and `rgba` becomes `rgba_255`;
- `LIMITS` gains the brush size range, the resource page size and the overhang rule, each held
  to its constant;
- `description`s where a range or unit matters, since Codex drops `minimum` and `maximum`;
- capture's native and resampled forms made explicit;
- not-finite numbers refused in every tool, in one place on the server;
- `krita_paint_stroke`'s refused values out of the schema (decision 11), and the instructions
  trimmed to leave at least 500 characters spare.

Release 0.20.0, with `api_version` 0.4.0.

## State you need that is not in the specs

- **Round 2 is recovery and construction.** R1, R2 and R3 are done. D1, F1, C1, M1, X1, E1, L1, B1,
  T1, S1, X2 and V1 remain, in that order.
- **`api_version` is 0.3.0 now, so D1's move is 0.4.0.** R3 changed what `refuse` means. D1's
  block is amended. `errors.API_VERSION` drives every schema's envelope through
  `scripts/amend_schemas.py`. Each schema's example and `tests/test_c1_error_passthrough.py` hold
  the literal.
- **What R3 left:**
  - **Every document now reports two flags.** `dirty` is the bridge's own changes since the last
    verified save. `krita_modified` is Krita's own flag, which a verified save leaves set.
    `refuse` reads both.
  - **A handle keeps `saved_state`,** what its last verified save compared: the composite, the
    tree's nodes and every node's own pixels. A tool that changes a document marks it through
    `before_change` as before, and needs nothing new.
  - **A property write through libkis leaves Krita's flag clear,** while `dirty` is set; it is in
    the backlog. `doctor`'s unsaved count reads Krita's flag, so a saved working copy counts as
    unsaved until it closes.
  - **`probe/modified.py`** holds the flag checks, and `opening.harness_export` is now public.
- **R1, R2 and R3 are pushed,** with the owner's approval on 2026-11-03. `origin/main` stops at
  "review: ORA saves kept no pixels for dropped masks, and 5 smaller". List `origin/main..HEAD`
  before any push.
- **What R2 left for later sessions:**
  - **Every tool's hints are in a table,** `HINTS` in `tests/test_tools.py`. A new tool needs its
    row, chosen from its worst permitted behaviour (decision 1). C1, M1, L1, B1, T1 and S1 each add
    one.
  - **A finished journal line carries `elapsed_ms`.** V1's re-measure can set it beside Codex's own
    records.
  - **Codex's schema sizes were last measured at 0.15.0,** with a scratchpad port of its renderer
    (see `docs/BACKLOG.md`). D1's gate "rendered inputs stay under Codex's limits" needs a measure
    again. Whatever D1 builds for it settles that backlog item, so move the item out if it does.
  - **D1's ground was hit again on 0.18.0:** a sampled 0–255 colour sent as a stroke's 0–1, a
    native capture given a `background`, and a brush size over 1000. Each was a clear refusal.
- **The evidence stays outside the repository.** The Codex agent holds its bundles.
- **Baseline** (ARCHITECTURE's table, v0.19.0): `verify` 6 stages, all PASS; 742 server tests and
  799 plugin-core tests, 0 skipped; `probe` 147 PASS, 0 FAIL, 24 MEASURED, about 125 s with 0
  documents open; 19 tools; 19 schema files; 30 error codes; 31 bridge ops; instructions 3,970
  characters.
- **Not done:** nothing from R3's block.

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
  - **Krita can start with a dialog open.** It refuses every document call with
    `KRITA_MODAL_DIALOG`, so a probe run fails from its first document op. Ask the owner to close
    it, then rerun.
  - **The probe refuses to run its document checks while any document is unsaved.** It touches
    nothing; ask the owner to save, then rerun.
- **The term list is not empty.** `~/.config/hygiene/terms.txt` holds 75 words. Never assume its
  size, never print a term, and ask before any write to it. Hygiene does not read old file versions.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe run: a dialog it raises refuses every call until it closes, and fails
  what the run overlaps. Done-notes record what was measured, never its work or its documents.
- **A client's `serve` runs this checkout as it stands.** A Codex session started mid-session
  imports your uncommitted code, and once the version is bumped and the plugin installed, nothing
  refuses it. Keep the tree working between edits while the owner may be painting.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor` step
  5 passes. That includes a version bump, which changes the plugin's hash, so bump before the first
  live run. **`serve` refuses a plugin of another version:** a stale plugin fails every tool with
  `PROTOCOL_MISMATCH` until Krita restarts.
- **A release restarts the MCP client too,** so tell the owner before the restart.
- **Before the probe's paint checks, the stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current brush
  and Krita's preset history. The probe saves and writes back the brush state. A scratchpad driver
  must do the same: read `harness.brush_state` first, from a document in the harness folder (a
  created document has no path, so the read fails), and stop if the read fails.
- **A scratchpad driver that leaves documents open for the owner** must not remove their folder
  until they are closed.
- **Krita's memory grows across large opens and saves.** Restart it, at 0 unsaved, before measuring.
- **D1's own traps:**
  - **Descriptions count.** They raise each rendered input. Codex compacts a normalised input over
    5,000 bytes, and a rendered one over 16,000 becomes `unknown`.
  - **The probe reads `rgba` too.** Rename it in one pass.
  - **The instructions have 126 characters to spare.** D1 must leave at least 500.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
