Read `FEATURE-recovery-and-construction.md` decisions 5, 10; `ARCHITECTURE.md` *Bridge and jobs*,
*Registry, lease and document state*, *The verification core*, *Painting*, *The undo ledger and
history*, *Testing strategy*; from git history, `git show
04e9f6c:docs/spec/REVIEW-2026-10-25.md` F3 and `git show 04e9f6c:docs/spec/REVIEW-2026-10-30.md` F19
and §8.8 items 6, 8; then CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline, your
block in docs/spec/SESSIONS.md and D1's done-note, then this file, and do Session F1: One
verified-mutation frame. F1 has three parts:
- `bridge_core/mutation.py`, one frame for scope, reads, marker and `before_change`,
  `unconfirmed`, the change, the verdict, the ledger, rollback and the receipt, taking a channel
  count (M1) and one or more undo steps per op (L1);
- `paint.stroke`, `layer.update` and `layer.create` moved onto it, the save keeping its ladder;
- parity tests for the six argument pairs (decision 10), and a helper for each new pair.

No version and no `CHANGELOG.md` entry: nobody can see it.

## State you need that is not in the specs

- **Round 2 is recovery and construction.** R1, R2, R3 and D1 are done. F1, C1, M1, X1, E1, L1, B1,
  T1, S1, X2 and V1 remain, in that order.
- **`api_version` is 0.4.0.** D1 renamed `rgba` to `rgba_255` and took three refused values out of
  `krita_paint_stroke`. The next move is whichever session first removes, renames or changes the
  meaning of a field or an input value (decision 9).
- **What D1 left:**
  - **A field's range or unit lives in its `description`.** `test_a_bounded_input_states_its_range_
    where_codex_shows_it` holds every input property with both bounds to a description stating
    them as "A to B". A new tool's bounded field needs one, or the test fails.
  - **Codex's limits are tested.** `tests/support/codex_render.py` ports Codex's sanitizer and
    renderer at `rust-v0.166.0`, and `test_codex_shows_every_input_and_output_whole` holds every
    tool: normalised input at most 5,000 bytes (the largest, the stroke's, is 2,948), rendered input
    and output at most 16,000 and whole. A new tool's schema is measured the moment it exists.
  - **Not-finite numbers are refused in `tools/__init__.py:_checked`,** for every tool, before any
    tool runs. A tool needs its own check only for a number it computes.
  - **The server's six argument pairs are unchanged by D1.** The capture's background and greyscale
    rules moved into its schema (`dependentSchemas`), and the stroke's eraser, smooth and antialias
    refusals left with their values; none of those was one of F19's six.
  - **A sample's `color` is a shared shape.** `amend_schemas.py` writes it from the stroke's
    `brush.color`, so a change to the stroke's colour reaches the sample through the script.
  - **The instructions are 3,453 characters, 643 spare.** No test holds the spare; later sessions
    spend it.
- **R1, R2, R3 and D1 are pushed,** with the owner's approval on 2026-11-04. `origin/main` stops at
  "review: the sample's color is a shared shape, and 6 smaller". List `origin/main..HEAD` before
  any push.
- **The evidence stays outside the repository.** The Codex agent holds its bundles.
- **Baseline** (ARCHITECTURE's table, v0.20.0): `verify` 6 stages, all PASS; 883 server tests and
  799 plugin-core tests, 0 skipped; `probe` 148 PASS, 0 FAIL, 24 MEASURED, about 125 s with 0
  documents open; 19 tools; 19 schema files; 30 error codes; 31 bridge ops; instructions 3,453
  characters.
- **Not done:** nothing from D1's block.

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
  imports your uncommitted code. Keep the tree working between edits while the owner may be
  painting.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor` step
  5 passes, F1's included: the plugin's hash changes with no version bump.
- **Before the probe's paint checks, the stock presets must be listed in Krita:**
  `b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray`, `y) Texture Wood Fiber`.
- **Brush state is window-wide (K3).** Any live run that paints changes the owner's current brush
  and Krita's preset history. The probe saves and writes back the brush state. A scratchpad driver
  must do the same: read `harness.brush_state` first, from a document in the harness folder, and
  stop if the read fails.
- **Krita's memory grows across large opens and saves.** Restart it, at 0 unsaved, before measuring.
- **F1's own traps:**
  - **This rewrites the most-tested path in the product.** The ledger's witness, the ring, the
    rollback's re-read and `history_sealed` are not incidental. Move them, do not simplify them.
  - **A frame nobody can extend is the failure mode.** Check it against C1, M1 and L1 first.
  - **No count moves but the parity tests,** and the probe's whole baseline holds unchanged.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
