Read `docs/spec/FEATURE-save-recompose-and-knot-limit.md` whole; `docs/ARCHITECTURE.md` *Painting*
(the taper's rules), *The server*, *The tool contract*, *Testing strategy*; `docs/USER-GUIDE.md` step
6's dynamics, the transform section and *What it cannot do*; `docs/BACKLOG.md`; P1's done-note. Then
CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline, your block in
docs/spec/SESSIONS.md, then this file, and do Session G1: the knot limit said plainly, transform
order, the reply; release and close. G1 has four parts:
- tests first: 16 and 17 knots, 1 knot, bad ends, a falling `at` and knots too close, for `size`
  and `opacity`, on both sides;
- the message: a `maxItems` or `minItems` problem reads as its count and bound, and the plugin's
  says the count;
- discovery: `limits.dynamics_knots`, the `dynamics` description, and transform order in the
  capability notes and the guide;
- the reply outside the repository, then the release and the round's close.

Release 0.32.0.

## State you need that is not in the specs

- **Round 3 is what a save changed, and the knot limit.** P1 is done (0.31.0); G1 remains, and
  closes the round.
- **Nothing of round 3 is pushed.** `origin/main` holds everything through `aef93b3` ("docs: the
  standing traps move into the rules file"). Local: the intake, its review fixes, P1's release and
  P1's review commit. List `origin/main..HEAD` before any push.
- **P1's review (`/code-review high`)** follows this commit; its findings go in its commit message
  and the note it adds here. CHANGELOG's `[0.31.0]` link to P1's release commit is added in that
  review commit, once the hash exists.
- **P1 amended its block, with the owner:** the save takes both composite reads before the export,
  rather than reusing the read after it, so nothing extra is held through `exportImage` (256 MiB at
  8192²) and a `BUSY` refusal reports its own recompose.
- **What P1 found, for the reply** (decision 6):
  - **Fixed in 0.31.0:** the save and the duplicate report `recompose {changed_px,
    visible_changed_px, changed_bounds_px}`; `composite_preserved` stays byte-exact against the
    document as the save left it, and its description says so; nothing is cleaned.
  - **Reproduced exactly:** the same 7 pixels, `[0,0,0,0]` to `[103,97,118,0]`, none with alpha;
    the control's save moved none, while its composite holds colour under alpha 0 in 292 pixels.
  - **The cause, settled (K55):** the grouped layer itself holds the first fill's colour under
    alpha 0 at all 7 pixels; the group's updated projection shows `[0,0,0,0]` there until a
    recompose. A change's after-read still does not recompose (the backlog item).
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call.** Propose one when a plan reworks a heavily tested path,
    and ask which model. P1's, by Opus, found no blocker and eight smaller points.
  - **Live runs and Krita restarts** were allowed at 0 unsaved with the Codex agent paused, each
    time they were asked for; ask again. G1 needs one run after `install-plugin` and a restart.
  - **The chat's last message is the workflow kit's one-line opener,** never this file's text:
    `Read docs/next-session-prompt.md: no round is in progress, so the next session is an intake.`
    once G1 closes the round (CLAUDE.md step 11). This repository's copy of the workflow still
    says "print the prompt"; the kit's step 12, which CLAUDE.md follows, wins.
  - **The handoff folder's path** is G1's question at the start (its block). It never enters the
    repository.
- **Baseline** (ARCHITECTURE's table, v0.31.0):
  - `verify`: 6 stages, all PASS; 1178 server tests and 1235 plugin-core tests, 0 skipped;
  - `probe`: 235 PASS, 0 FAIL, 27 MEASURED, about 155 s with 0 documents open;
  - 25 tools, 25 schema files, 30 error codes, 39 bridge ops, 17 capabilities, 28 parity tests,
    instructions 3,371 characters, `api_version` 0.4.0;
  - Codex's renderer: the stroke's normalised input 4,378 of 5,000 bytes, 622 to spare.
- **Timing:** H4's 8192² save took 4.7 s before 0.31.0 and 4.8 s after. One probe run on a
  freshly restarted Krita was slower throughout (strokes about 50%, previews twice), so compare a
  stage against another stage of the same run.

## Watch for

- **The two traps kept here on purpose,** because they cost the most when missed:
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit
    with `git commit -F`, then delete the draft.
  - **Never `git checkout <path>`.** Stage explicit paths, and falsify a check by copying the
    file aside and back.
- **The other standing traps are in the documents,** so read `CLAUDE.md` whole before you start,
  and `ARCHITECTURE.md`'s *Testing strategy* for the three ways a falsification proves nothing.
- **The term list is not empty.** Never assume its size, never print a term, and ask before any
  write to it.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe or measurement run.
- **The journal in the data folder is the owner's own work.** Read it read-only, and record counts
  and timings alone: never a document path, a layer name or a folder.
- **A plugin edit after `install-plugin` needs another install and restart** before any live run;
  the probe refuses a changed plugin.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
