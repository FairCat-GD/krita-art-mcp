No round is in progress. Read CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and
baseline, then this file; then the sections of docs/ARCHITECTURE.md the request touches. The
next session is an **intake**: write the user's request down verbatim, ask what it leaves open,
and plan the round in `docs/spec/`, a Read line in every block (see
`docs/DEVELOPMENT-WORKFLOW.md`, *Rounds*).

## State you need that is not in the docs

- **krita-art-mcp 0.16.0 is released.** Round 1 (the Phase 1 build: sessions 0 to 15) is closed. Its
  spec files are deleted; the last done-note is in `docs/spec/SESSIONS.md` as of the release commit
  (`04e9f6c`), and `docs/BACKLOG.md`'s header says how to read them. The owner kept the contract
  package in the tree at the close: it moved to `docs/reference/contract-package/`, frozen, because
  Phase 2 starts from its draft shapes.
- **History is not rewritten.** The owner decided against it at round 1's close, as
  `docs/BACKLOG.md`'s *Publishing the repository* item says. The GitHub topics and description are set.
- **Round 1's last review** (`/code-review high`), 9 findings, 9 fixed, no version: the handoff and
  backlog name the rewrite; the instructions and the save's refusal state the bound as 67 megapixels,
  and that a larger document paints in region scope only; the selection check compares pixel counts,
  because grow and feather share their bounds; ARCHITECTURE says nothing re-checks the preset
  fingerprint across restarts; `CLAUDE.md` records the copyright line; the journal measurement's label
  is true; `_private_file` says what guards an older log; the `[0.16.0]` link; the journal refuses a
  float version. Falsified: the float version, and feather sent as grow, live. The baseline holds at
  670 server tests, 665 plugin-core tests, `probe` 131 PASS, 0 FAIL, 23 MEASURED, 113.6 s, 0 documents
  open.
- **The review changed the plugin,** so the MCP client needs one more restart.
- **Push status:** `origin/main` holds everything, through "docs: keep history as it is, and say what
  it holds". `origin/main..HEAD` is empty. List it before any push.
- **Open items live in `docs/BACKLOG.md`,** including what this round added: the findings the owner
  did not take, the debts only done-notes held, and *Not yet checked by hand*.
- **The trial and publishing** are the owner's, after the round.
- **Baseline** (ARCHITECTURE's table, v0.16.0): `verify` 6 stages, all PASS; 670 server tests and 665
  plugin-core tests, 0 skipped; `probe` 131 PASS, 0 FAIL, 23 MEASURED, about 114 s with 0 documents
  open; 19 tools; 19 schema files; 30 error codes; 31 bridge ops; instructions 3,906 characters.

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
    `doctor` reports 0 unsaved documents, and ask the owner first. `osascript` quitting Krita reports
    "User canceled" yet Krita quits: wait for the process to go, then a few seconds more, because
    `open` straight after fails with -600.
- **The term list is not empty.** `~/.config/hygiene/terms.txt` holds 75 words. Never assume its size,
  never print a term, and ask before any write to it. Hygiene does not read old file versions.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe run: a dialog it raises refuses every call until it closes, and fails
  what the run overlaps. Done-notes record what was measured, never its work or its documents.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor`
  step 5 passes. That includes a version bump, which changes the plugin's hash, so bump before the
  first live run. **`serve` refuses a plugin of another version:** a stale plugin fails every tool with
  `PROTOCOL_MISMATCH` until Krita restarts.
- **A release restarts the MCP client too,** so tell the owner before the restart.
- **Before the probe's paint checks, the stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current brush and
  Krita's preset history. The probe saves and writes back the brush state. A scratchpad driver must do
  the same: `harness.brush_state` read first, from a document in the harness folder (a created
  document has no path, so the read fails), and stop if the read fails.
- **Krita's memory grows across large opens and saves.** Restart it, at 0 unsaved, before measuring.
- **The instructions have 190 characters to spare.**
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
