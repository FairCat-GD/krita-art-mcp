Read `docs/spec/FEATURE-stable-release-readiness.md` whole; `docs/ARCHITECTURE.md` *Bridge and
jobs*, *The tool contract* (retries, outcomes and the replay paragraph), *Registry, lease and
document state* (the lease), *The save* (the finish), *The server*, *Testing strategy* (the probe's
harness and the journal check); `docs/USER-GUIDE.md` *Retries and long calls*. Then CLAUDE.md,
docs/ARCHITECTURE.md's overview, invariants and baseline, the header and L1's block in
docs/spec/SESSIONS.md, then this file, and do Session L1: the recovery routes kept as checks. L1
has two parts:
- the unit gaps: a queued call cancelled and retried through the tools, a paint recovered by a new
  server, a save finished by a new server after the first is gone;
- three live checks: a call queued behind the probe's long save, cancelled and retried; one server
  of the probe's own ended while its save runs with a paint queued, then the save finished and the
  paint recovered from a new process.

No release: L1 changes tests and the probe alone, so it cuts no version, and the installed plugin
stays current without a Krita restart. V1 releases 0.32.1.

## State you need that is not in the specs

- **Round 4 is stable-release readiness:** the intake is done; L1 and V1 remain.
- **Pushed.** `origin/main` holds everything through the intake's review commit ("review: L1's
  queued cancel had no document of its own, and 6 smaller"), pushed with the owner's approval:
  the intake (`ac1ccc4`) and that review commit. List `origin/main..HEAD` before any push.
- **The intake's review (`/code-review high`), 7 findings, all fixed** in the spec and the plan:
  L1's cancel check queues on a document of its own; V1 re-runs the release checks on the commit
  it tags; the two restart checks share one ended server and one save; L1 cuts no version and V1
  releases 0.32.1; V1's install steps wait on its own question about the clone URL; the feature
  file states what a missing source does to the hash check; the new by-hand items name their
  automated cover.
- **Where the round comes from.** The Codex agent ran release checks on 0.32.0 and found no
  painting, cancellation, recovery or native-close defect. The feature file summarises its handoff
  in public-safe words; the handoff itself stays outside the repository, and nothing of its
  evidence (files, paths, receipts, names of the owner's art) enters it.
- **What L1 builds on, as it is now:**
  - the probe's long save, `_long_save` in `src/krita_art_mcp/probe/saving.py:647`: an 8192²
    working copy with 8 gradient layers, about 5 s of export, a stroke queued behind it through a
    `BridgeClient` of its own (`paint_twice`), and `_h4_checks` at `:751`;
  - the probe's servers: `_server` at `probe/__init__.py:64`, each with `KRITA_ART_MCP_DATA_DIR` set
    to its own folder under the harness; `server-a` already runs three times over one folder;
  - the journal check, `_nothing_uncertain` at `probe/__init__.py:262`, with `MIN_JOURNALED = 340`;
  - `serve` builds `BridgeClient()` with no arguments (`server.py:35`); there is no injection seam,
    and decision 4 adds none;
  - the tests to extend are in the feature file's coverage table.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call.** Propose one when a plan reworks a heavily tested path,
    and ask which model. The intake proposed none.
  - **Live runs and Krita restarts** were allowed at 0 unsaved with the Codex agent paused, each
    time they were asked for; ask again.
  - **The chat's last message is the workflow kit's one-line opener,** never this file's text.
  - **L1 cuts no version.** A bump would force `install-plugin`, a Krita restart and the client's
    restart to reload an unchanged plugin, since the plugin's version is held equal to the
    package's. If L1 finds it must change the plugin or a tool, it stops and asks.
- **Baseline** (ARCHITECTURE's table, v0.32.0, unchanged by the intake):
  - `verify`: 6 stages, all PASS; 1198 server tests and 1245 plugin-core tests, 0 skipped;
  - `probe`: 238 PASS, 0 FAIL, 27 MEASURED, about 153 s with 0 documents open, the journal check
    reading 864 dispatched lines;
  - 25 tools, 25 schema files, 30 error codes, 39 bridge ops, 17 capabilities, 29 parity tests,
    instructions 3,371 characters, `api_version` 0.4.0.

## Watch for

- **The two traps kept here on purpose,** because they cost the most when missed:
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit
    with `git commit -F`, then delete the draft.
  - **Never `git checkout <path>`.** Stage explicit paths, and falsify a check by copying the
    file aside and back.
- **The other standing traps are in the documents,** so read `CLAUDE.md` whole before you start,
  and `ARCHITECTURE.md`'s *Testing strategy* for the three ways a falsification proves nothing.
- **A falsification can expose a test that reads the constant it checks.** Name the number.
- **The term list is not empty.** Never assume its size, never print a term, and ask before any
  write to it.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe or measurement run.
- **The journal in the data folder is the owner's own work.** Read it read-only, and record counts
  and timings alone: never a document path, a layer name or a folder.
- **L1's own traps are in its block:** the lease passes only once the ended process is gone; every
  ended server's call must be settled by its retry, or the journal check fails; a check that never
  saw the state it is about fails, never passes.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
