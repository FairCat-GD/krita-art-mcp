Read `docs/spec/FEATURE-save-recompose-and-knot-limit.md` whole; `docs/ARCHITECTURE.md` *The save*,
*The verification core*, *The tool contract* (the `api_version` rule and the replay paragraph),
*Reads, and K46*, *Testing strategy*, and the reference rows K12, K39, K42 and K45;
`docs/USER-GUIDE.md` step 9. Then CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and
baseline, your block in docs/spec/SESSIONS.md, then this file, and do Session P1: the save reports
what its own recompose changed. P1 has three parts:
- reproduce first: probe checks of the grouped three-fill case and its ungrouped control, run
  against the installed 0.30.0 plugin before any plugin edit (the drift check passing, the
  receipt check failing), and a failing plugin-core test;
- the receipt: `recompose {changed_px, visible_changed_px, changed_bounds_px}` on the save and the
  document duplicate, `composite_preserved` unchanged in meaning;
- the docs, and the cause read from the layer itself, as K55.

Release 0.31.0.

## State you need that is not in the specs

- **Round 3 is what a save changed, and the knot limit:** P1 and G1, with no architecture review.
  The intake is done; P1 and G1 remain.
- **The intake and its review fixes are committed locally, not pushed.** `origin/main` holds
  everything through `aef93b3` ("docs: the standing traps move into the rules file"). List
  `origin/main..HEAD` before any push.
- **The intake's review (`/code-review high`), 6 findings: 6 fixed** in the plan, before P1:
  - the duplicate's receipt comes from `document.duplicate_open` and its `Placed`, not from
    `write`, so P1's block now points there;
  - the reproduction is two checks, the drift itself and the receipt, so a missing field alone
    cannot pass for a reproduced case;
  - the compare reuses the read `write` already takes after the export, rather than a third
    whole-canvas read;
  - a 16-knot case gets tests of its own, since `refused_alike` asserts a refusal;
  - the latency figures: a save took about 110 ms at the client, not 3 s, in the backlog and the
    feature file.
- **What the intake found, which P1 builds on:**
  - `bridge_core/saving.py` `write` refreshes the projection inside `unmasked_view`, exports, then
    hashes the live composite (`:140-155`). The comparison is byte-exact and held; what moved is the
    live document, at the refresh.
  - The handoff's captures say so: before the save and after it, the live document differs in 7
    pixels, all alpha 0; after the save, the live document, the reopened one and the KRA's
    `mergedimage.png` are equal byte for byte.
  - The frame refreshes before a change's before-read (`mutation.py:238`) and not before its
    after-read (`:317`). Decision 3 leaves that as it is, in the backlog.
  - The duplicate's receipt is built by `document.duplicate_open` (`bridge_core/branching.py:80`)
    from a `Placed` the finish makes (`saving.py:261`), which today keeps no save fields beyond
    the path and the hash.
  - The fake already models a stale projection: `render` and `projection` by key, redrawn only by
    `refresh` (`tests/fixtures/fake_krita.py:118-121`, `_redraw` at `:386`).
  - The hypothesis to settle: the colour under alpha 0, `[103,97,118]`, is the first fill's, so
    the paint layer probably holds it itself.
- **The handoff stays outside the repository** (decision 7). Its numbers are in the feature file;
  its files, its folder and the names in it are not to be written anywhere here.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call.** None ran on this intake. Propose one when a plan
    reworks a heavily tested path, and ask which model.
  - **Live runs and Krita restarts** were allowed at 0 unsaved with the Codex agent paused, each
    time they were asked for; ask again. P1 needs two runs: the reproduction before any plugin
    edit, and the check after `install-plugin` and a restart.
- **Baseline** (ARCHITECTURE's table, v0.30.0, unchanged by the intake):
  - `verify`: 6 stages, all PASS; 1177 server tests and 1223 plugin-core tests, 0 skipped;
  - `probe`: 231 PASS, 0 FAIL, 25 MEASURED, about 150 s with 0 documents open;
  - 25 tools, 25 schema files, 30 error codes, 39 bridge ops, 17 capabilities, 28 parity tests,
    instructions 3,371 characters, `api_version` 0.4.0;
  - Codex's renderer: the stroke's normalised input 4,378 of 5,000 bytes, 622 to spare.
- **Not done:** no live run was made at the intake; its measurements are from the handoff's
  captures and the journal, read-only.

## Watch for

- **The two traps kept here on purpose,** because they cost the most when missed:
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit
    with `git commit -F`, then delete the draft.
  - **Never `git checkout <path>`.** Stage explicit paths, and falsify a check by copying the
    file aside and back.
- **The other standing traps are in the documents now,** not here, so read `CLAUDE.md` whole
  before you start: it holds the toolchain and the shell, the Krita restart quirks and the probe's
  output rule, and `ARCHITECTURE.md`'s *Testing strategy* holds the three ways a falsification
  proves nothing.
- **The term list is not empty.** `~/.config/hygiene/terms.txt` holds 75 words. Never assume its
  size, never print a term, and ask before any write to it.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe or measurement run.
- **The journal in the data folder is the owner's own work.** Read it read-only, and record counts
  and timings alone: never a document path, a layer name or a folder.
- **The probe refuses a changed plugin.** Reproduce before the first plugin edit.
- **Never normalise the evidence.** Compare the bytes raw, in tests and in the probe.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
