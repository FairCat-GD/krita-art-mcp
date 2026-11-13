Read `FEATURE-recovery-and-construction.md` decision 18; `ARCHITECTURE.md` whole;
`docs/USER-GUIDE.md`; `docs/BACKLOG.md`; every done-note in `docs/spec/SESSIONS.md`; then CLAUDE.md,
docs/ARCHITECTURE.md's overview, invariants and baseline, your block in docs/spec/SESSIONS.md and
X2a's done-note, then this file, and do Session V1: re-measure, docs, full run, close the round.

## State you need that is not in the specs

- **Round 2 is recovery and construction.**
  - Done: R1, R2, R3, D1, F1, C1, M1, X1, X1a, E1, L1, B1, T1, S1, X2 and X2a.
  - Remaining: V1 alone, which closes the round.
- **X2a shipped 0.29.0.** V1 cuts 0.30.0 and is the round's release, followed by the close commit.
- **X2a is pushed.** `origin/main` holds everything through "review: a probe check could not
  fail on the flag it named, and 1 more". List `origin/main..HEAD` before any push, and push
  only on the owner's approval.
- **What X2a left V1:**
  - `REVIEW-2026-11-12.md`'s F21 items are all taken: the Codex sizes, the two ops outside
    `RECEIPTS`, the journal check's count, the `no_change` transform, the held preset's order, the
    parity paragraph, "Not held", the guide's unfinished-save line and step 8, and the backlog's
    "or stroke". Only the re-measure and the read-through remain.
  - **The baseline gained two rows,** the capability count and the parity count, as X2's block
    asked. Every count in it was measured at 0.29.0.
  - **Re-measure the Codex sizes again:** every schema description X2a moved changed them, and the
    stroke's normalised input now has 622 bytes of its 5,000 to spare.
- **What turned out wrong or harder:**
  - **The review's own remedy for F1 was not enough.** Putting the re-read in each op leaves the
    window open, because the frame reads the selection after it, and that waits. The check lives
    in `Mutation.run` instead, as the last read before the marker. An adversarial plan review
    found it before any code was written.
  - **Two probe checks of X2a's were wrong on the first live run,** not the product: a reorder of
    a translated layer takes three undo steps, and the affine refusals leave their layer holding a
    transform mask. Both are fixed; the lesson is that a probe check added beside existing ones
    inherits their leftovers.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call:** Opus at X1a, E1, L1, B1, T1, S1 and X2a. Propose one
    when a plan reworks a heavily tested path, and ask which model.
  - **Live runs** were allowed at 0 unsaved with the Codex agent paused, for X2a's gate; ask again.
  - **What the frame still does not watch,** recorded under *Known debt*: `port.effects`,
    `port.describe` and the selection, which is read just before the tree.
- **Baseline** (ARCHITECTURE's table, v0.29.0, measured at X2a):
  - `verify`: 6 stages, all PASS; 1176 server tests and 1223 plugin-core tests, 0 skipped;
  - `probe`: 231 PASS, 0 FAIL, 25 MEASURED, about 155 s with 0 documents open, the journal
    check reading 846 dispatched lines;
  - 25 tools, 25 schema files, 30 error codes, 39 bridge ops, 17 capabilities, 28 parity tests,
    instructions 3,371 characters;
  - Codex's renderer: the stroke's normalised input 4,378 of 5,000 bytes, 622 to spare.
- **Not done:** nothing from X2a's block.

## Watch for

- **A retryable refusal is a change of nothing,** proven at its raise: the AST scan finds each new
  one, and `tests/plugin/test_outcomes.py` pins it in `RETRYABLE` with its own test.
- **The standing traps:**
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit
    with `git commit -F`, then delete the draft.
  - **Never `git checkout <path>`.** Stage explicit paths.
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
  - **Read a probe run from a file, not a pipe.** `probe | tail` throws away the FAIL lines and
    the exit code; write the whole run to a file and grep it.
- **The term list is not empty.** `~/.config/hygiene/terms.txt` holds 75 words. Never assume its
  size, never print a term, and ask before any write to it.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe or measurement run.
- **A client's `serve` runs this checkout as it stands.** Do not edit while `verify` runs: a test
  that spawns `serve` reads the files as they are mid-run.
- **Brush state is window-wide (K3).** A scratchpad driver must read `harness.brush_state` first,
  from a document in the harness folder, with every preset it will activate, and write it back.
- **Falsifying by test name:** a pytest `-k` with spaces selects nothing. A mutation that leaves
  a file unparsable fails collection, not the test: check each mutation's run named its test.
  A mutation that a second rule also catches proves nothing about the first.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
- **A release restarts the MCP client too.** Tell the owner before the restart.
