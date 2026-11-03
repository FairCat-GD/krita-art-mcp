Read `docs/ARCHITECTURE.md` *Registry, lease and document state* (Dirty), *Documents*, *The save*,
and K39 and K45 in *Reference*; `docs/USER-GUIDE.md` *The core loop* (save and close); then
CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline, your block in
docs/spec/SESSIONS.md and R2's done-note with its Review section, then this file, and do Session R3:
Krita's own modified state. R3 has four parts:
- measure, live on harness documents, what Krita's own modified flag does around a verified save,
  for PNG, KRA and ORA working copies;
- report that flag beside the bridge's `dirty` in list, inspect and the save's receipt, with where
  the save wrote and where the live document still points;
- make `dirty_policy: "refuse"` refuse any unsaved change Krita holds, not only the bridge's;
- check by hand, with the owner, that Krita's own prompts agree with what the tools report.

Release 0.19.0. **Ask at the start of R3:**
- after a verified save, clear Krita's flag, or only report it?
- does `refuse` change meaning, so `api_version` moves to 0.3.0 here, or does a new value carry the
  native check?
- may a separately named policy close after a verified save while Krita still holds the document
  modified?

## State you need that is not in the specs

- **Round 2 is recovery and construction.** R1 and R2 are done. The owner inserted R3 at R2's
  review. R3, D1, F1, C1, M1, X1, E1, L1, B1, T1, S1, X2 and V1 remain, in that order.
- **R3 has no intake decision of its own.** It came from the Codex agent's report on 0.18.0. After
  a verified save the bridge said `dirty: false`, and Krita then asked to save the tab. The live
  pixels matched the saved KRA. The block holds the cause as the review read it: `dirty` is the
  bridge's flag, and `exportImage` never clears Krita's (K45). The agent's second report showed
  the worse half: `refuse` reads only the bridge's flag, and `port.close` clears Krita's before
  closing, so a close can drop changes only Krita holds. Its evidence bundle stays outside the
  repository, with its file names; it advises against forcing a clean flag.
- **R1, R2 and the R3 amendment are pushed,** with the owner's approval on 2026-11-03. `origin/main`
  stops at "docs: R3 takes the Codex agent's save-state report". List `origin/main..HEAD` before
  any push.
- **What R2 measured, from the owner's Codex session on 0.18.0:**
  - The five additive tools now cost their tool time and no more.
  - Every destructive call still spends about 2.8–3.0 s outside the server.
  - The trust setting, `default_tools_approval_mode`, is still not set.
  - The inference held, and decision 1 is not to be widened.
- **What R2 left for later sessions:**
  - **Every tool's hints are in a table,** `HINTS` in `tests/test_tools.py`. A new tool needs its
    row, chosen from its worst permitted behaviour (decision 1): C1, M1, L1, B1, T1 and S1 each add
    one. `readOnlyHint` stays load-bearing.
  - **A finished journal line carries `elapsed_ms`,** from the call's arrival, before `CALLS`. It
    is null on a line a poll writes, and a value that is not a whole number reads as `None`.
    Codex's records hold `started_at_ms`, `completed_at_ms` and `duration` per MCP call, which V1's
    re-measure can set beside it.
  - **Codex's schema sizes were last measured at 0.15.0,** with a scratchpad port of its renderer
    (see `docs/BACKLOG.md`). D1's gate "rendered inputs stay under Codex's limits" needs a measure
    again. Whatever D1 builds for it settles that backlog item, so move the item out if it does.
  - **D1's ground was hit again on 0.18.0:** a sampled 0–255 colour sent as a stroke's 0–1, a
    native capture given a `background`, and a brush size over 1000. Each was a clear refusal.
- **The Codex agent's other priorities stay where the intake put them.** Wrap offset is in the
  backlog (decision 18). Variable pressure is E1's probe, then Phase 6.
- **The evidence stays outside the repository.** The Codex agent holds the bundle.
- **Baseline** (ARCHITECTURE's table, v0.18.0): `verify` 6 stages, all PASS; 741 server tests and
  781 plugin-core tests, 0 skipped; `probe` 143 PASS, 0 FAIL, 23 MEASURED, about 122 s with 0
  documents open; 19 tools; 19 schema files; 30 error codes; 31 bridge ops; instructions 3,970
  characters.
- **Not done:** nothing from R2's block.

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
  must do the same: `harness.brush_state` read first, from a document in the harness folder (a
  created document has no path, so the read fails), and stop if the read fails.
- **Krita's memory grows across large opens and saves.** Restart it, at 0 unsaved, before measuring.
- **R3's own traps:**
  - **`dirty` keeps its name and meaning.** An added field moves no `api_version` (decision 9).
  - **Krita's modified flag is what `doctor`'s unsaved count and the restart rule read**
    (`krita_adapter/ops.py:15`). Clearing it after a save changes what they see, too.
  - **Measure on harness documents only.** Never save, clear or close one of the owner's.
- **The instructions have 126 characters to spare.** D1 must leave at least 500.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
