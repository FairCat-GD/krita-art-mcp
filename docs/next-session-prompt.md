No round is in progress. Read CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline,
then this file; then the sections of docs/ARCHITECTURE.md the request touches. The next session is
an **intake**: write the owner's request down verbatim, ask what it leaves open, and plan the round
in `docs/spec/`, with a Read line in every block (see `docs/DEVELOPMENT-WORKFLOW.md`, *Rounds*).

## State you need that is not in the docs

- **krita-art-mcp 0.32.0 is released.** Round 3 (what a save changed, and the knot limit: P1, G1)
  is closed. Its spec files are deleted; the last done-note is in `docs/spec/SESSIONS.md` as of the
  release commit (`2312d86`), and `docs/BACKLOG.md`'s header says how to read the rest.
- **What round 3 built:** a save and a duplicate report what their own recompose changed
  (`recompose`, 0.31.0), with the cause settled as K55; a list of the wrong length is refused with
  its count and bound, for every tool; `limits.dynamics_knots`; and the order to transform in, in
  the capability notes and the guide (0.32.0).
- **The reply to the Codex agent's report** went into the chat alone, by the owner's amendment of
  decision 6 at G1; no file was written outside the repository.
- **Pushed.** `origin/main` holds everything through G1's review commit ("review: the server's own
  knot rule said no count, and 6 smaller"), pushed with the owner's approval: the release
  (`2312d86`), the close (`8c0ecd3`) and that review commit. List `origin/main..HEAD` before any
  push.
- **G1's review (`/code-review high`), 7 findings: 6 fixed, 1 needing no change.** The close had
  already deleted `SESSIONS.md`, so they are recorded here and in the review commit.
  - **The server's own knot rule stated no count,** and checked no upper bound, for a caller past
    the schema such as the probe. It now says `dynamics.opacity holds 17 knots, and takes 2 to 16.`
    as the plugin does, from `limits.dynamics_knots`; the parity cases at 17 knots switch it off
    with the schema's bound.
  - **The 16-knot parity test called the plugin's `check` directly.** It now goes through the
    plugin's handler and is refused only for the missing layer.
  - **The probe's 16-knot taper was judged by the older preset check.** It now runs after it and
    checks its own preset comes back.
  - **The guide said "neither" of three transforms.**
  - **`LENGTHS` sat below its user,** mid-module; it is with the other constants now.
  - **Four knot builders** became one, `tests/fixtures/knots.py`; the probe keeps its own, since
    it cannot import from `tests/`.
  - **No change needed:** the `isinstance` on a length problem's instance looked redundant, but it
    narrows jsonschema's `Any | Unset` for mypy, which failed without it.
  - **Falsified:** the server's rule checking only the minimum (its 17-knot test failed); the
    plugin's cap at 15 through the handler (both 16-knot parity cases failed); the probe's preset
    clause, broken alone (237 PASS, 1 FAIL, exactly it). The files were restored byte for byte.
  - **Numbers after the review:** 1198 server tests (+3), 1245 plugin tests, 29 parity tests; probe
    238 PASS, 0 FAIL, 27 MEASURED in 155 s; the plugin unchanged, so no reinstall.
- **0.32.0 is installed and live.** G1 ran `install-plugin` and restarted Krita at 0 unsaved, so
  the running plugin is this checkout's. The owner's MCP client needs its own restart to pick the
  server up, and the Codex agent stays paused until it has.
- **Open items live in `docs/BACKLOG.md`,** among them what round 3 left there: recomposing before
  a change's after-read and before captures; a knot cap above 16; Krita's own close paths after a
  verified save, by hand; wrap authoring, proposed again as a change of workflow; and the
  server-side batch with timing the server's share by stage.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call.** Propose one when a plan reworks a heavily tested path,
    and ask which model. P1's, by Opus, found no blocker; G1 proposed none.
  - **Live runs and Krita restarts** were allowed at 0 unsaved with the Codex agent paused, each
    time they were asked for; ask again.
  - **The chat's last message is the workflow kit's one-line opener,** never this file's text.
- **Baseline** (ARCHITECTURE's table, v0.32.0, measured at G1):
  - `verify`: 6 stages, all PASS; 1198 server tests and 1245 plugin-core tests, 0 skipped;
  - `probe`: 238 PASS, 0 FAIL, 27 MEASURED, about 153 s with 0 documents open, the journal check
    reading 864 dispatched lines;
  - 25 tools, 25 schema files, 30 error codes, 39 bridge ops, 17 capabilities, 29 parity tests,
    instructions 3,371 characters, `api_version` 0.4.0;
  - Codex's renderer: the stroke's normalised input 4,386 of 5,000 bytes, 614 to spare.

## Watch for

- **The two traps kept here on purpose,** because they cost the most when missed:
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit
    with `git commit -F`, then delete the draft.
  - **Never `git checkout <path>`.** Stage explicit paths, and falsify a check by copying the
    file aside and back.
- **The other standing traps are in the documents,** so read `CLAUDE.md` whole before you start,
  and `ARCHITECTURE.md`'s *Testing strategy* for the three ways a falsification proves nothing.
- **A falsification can expose a test that reads the constant it checks.** G1's plugin test of 16
  knots first counted `MAX_KNOTS` itself and passed with the cap at 15. Name the number.
- **The term list is not empty.** Never assume its size, never print a term, and ask before any
  write to it.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe or measurement run.
- **The journal in the data folder is the owner's own work.** Read it read-only, and record counts
  and timings alone: never a document path, a layer name or a folder.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
