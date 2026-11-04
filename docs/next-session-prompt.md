Read `FEATURE-recovery-and-construction.md` *The Codex agent's report* (Authoring), decisions 1, 3;
`ARCHITECTURE.md` *The verification core*, *Protection, selections and masks*, *Painting*,
*Reference* (K2, K4, K5, K9, K10); then CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and
baseline, your block in docs/spec/SESSIONS.md and F1's done-note, then this file, and do Session
C1: `krita_paint_fill`. Measure `Node.paintPath(path, "None", "ForegroundColor")` first, in a
harness document, then build the fill on the verified-mutation frame, with the stroke's receipt
shape, version 0.21.0.

## State you need that is not in the specs

- **Round 2 is recovery and construction.** R1, R2, R3, D1 and F1 are done. C1, M1, X1, E1, L1, B1,
  T1, S1, X2 and V1 remain, in that order.
- **`api_version` is 0.4.0.** F1 added fields only. The next move is whichever session first
  removes, renames or changes the meaning of a field or an input value (decision 9).
- **F1 shipped 0.20.1, not "no version":** the owner chose one failure behaviour for every op on
  the frame, which a create that Krita raised in shows. The SESSIONS table says so; later versions
  did not move, and C1 is 0.21.0.
- **What F1 left:**
  - **The frame is `bridge_core/mutation.py`.** A fill is a stroke's shape:
    - `verifiable(...)` with the target, its `target_rect` and the protected layers' meets gives
      the `Reads`;
    - `Mutation(..., ("Scripted Brush Stroke",), reads, data, {"layer_id": ...}, "fill")`, then
      `read()`;
    - `run(change, judge, back)`: the frame pushes the witnessed step, or seals an empty diff.
  - **The stroke's judge is reusable.** `painting._verdict` holds a target to R and its bounds;
    `back` compares the target's bounds with its old ones. The full-scope widening lives in the
    stroke's judge.
  - **`Mutation.run`, not `apply`:** the source scan bans every `.apply` attribute.
  - **A new op names its undo labels up front;** the frame asserts it took exactly those.
  - **Parity:** a new rule written on both sides gets a named server function and one
    `refused_alike(world, monkeypatch, tool, arguments, (module, "name"))` case in
    `tests/test_parity.py`.
  - **`selection.set` is outside the frame** (no verdict). *Known debt* says so.
- **R1, R2, R3, D1 and F1 are pushed.** `origin/main` stops at "review: a rollback with nothing to
  move flipped the view, and 6 smaller". List `origin/main..HEAD` before any push.
- **The evidence stays outside the repository.** The Codex agent holds its bundles.
- **Baseline** (ARCHITECTURE's table, v0.20.1): `verify` 6 stages, all PASS; 897 server tests and
  804 plugin-core tests, 0 skipped; `probe` 148 PASS, 0 FAIL, 24 MEASURED, about 125 s with 0
  documents open; 19 tools; 19 schema files; 30 error codes; 31 bridge ops; instructions 3,453
  characters.
- **Not done:** nothing from F1's block.

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
  - **Krita can start with a dialog open,** and did at both D1's and F1's restarts. It refuses
    every document call with `KRITA_MODAL_DIALOG`, so a probe run fails from its first document
    op. Ask the owner to close it, then rerun.
  - **The probe refuses to run its document checks while any document is unsaved.** It touches
    nothing; ask the owner to save, then rerun.
- **The term list is not empty.** `~/.config/hygiene/terms.txt` holds 75 words. Never assume its
  size, never print a term, and ask before any write to it. Hygiene does not read old file versions.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe run: a dialog it raises refuses every call until it closes, and fails
  what the run overlaps. Done-notes record what was measured, never its work or its documents.
- **A client's `serve` runs this checkout as it stands.** A Codex session started mid-session
  imports your uncommitted code. Keep the tree working between edits while the owner may be
  painting.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor` step
  5 passes. Bump the version first: the plugin's hash and `serve`'s gate both read it.
- **Before the probe's paint checks, the stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current brush
  and Krita's preset history. The probe saves and writes back the brush state. A scratchpad driver
  must do the same: read `harness.brush_state` first, from a document in the harness folder, and
  stop if the read fails.
- **Krita's memory grows across large opens and saves.** Restart it, at 0 unsaved, before measuring.
- **C1's own traps:** the block's *Watch for* (bad style strings fall back silently; set colour,
  opacity, blend and alpha lock per call; the inset; no flood fill). Also: `paintPath` snapshots
  the view's preset, so run the measurement under three presets before deciding whether the fill
  activates one.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
