Read `docs/spec/FEATURE-stable-release-readiness.md` whole; `docs/ARCHITECTURE.md` *The CLI*,
*Packaging*, *Testing strategy*, *Registry, lease and document state* (Krita's flag), invariant 11
and the reference rows K45 and K55; `docs/USER-GUIDE.md` *What you need*, *Install*, *Register the
server*, *Update*, *`doctor` and troubleshooting*; README; `docs/BACKLOG.md`'s header and *Not yet
checked by hand*. Then read:
- CLAUDE.md;
- docs/ARCHITECTURE.md's overview, invariants and baseline;
- the header and V1's block in docs/spec/SESSIONS.md, with L1's done-note;
- this file.

Then do Session V1: setup diagnostics, the install route, the release checks, the report and the
round's close. V1 has four parts:
- one payload check for the plugin's source, used by `install-plugin`, `doctor`'s first and fifth
  steps, and the probe's first check;
- the install route said plainly, in README, the guide and ARCHITECTURE;
- Krita's close paths, recorded as K56;
- the release checks, the readiness report in the chat, the `v0.32.1` tag asked for, and the
  close.

Release 0.32.1, tagged locally once the owner approves the tag.

## State you need that is not in the specs

- **Round 4 is stable-release readiness:** L1 is done, and V1 remains.
- **Pushed.** `origin/main` holds everything through L1's review commit ("review: H4's end was
  stamped after its cancels, and 6 smaller"), pushed with the owner's approval: L1 (`f0a377b`)
  and that review commit. List `origin/main..HEAD` before any push.
- **What L1 left that V1 builds on:**
  - **Probe checks for V1's 0.32.1 entry.** L1 wrote no CHANGELOG line, so V1 says these in the
    user's words:
    - **Two beside H4's long save.** A layer create queued behind the save is cancelled, polled
      `not_applied` with a valid receipt, and absent afterwards, while cancelling the running
      save is refused. Its same-id retry runs once.
    - **Two from a server of the probe's own ended mid-save.** First the precondition: the pid
      gone, the save still running, its journal line unsettled. Then a new server finishes that
      save and verifies it.
    - **One MEASURED line** for the restart save.
  - **Three unit tests for V1's entry.** A queued layer create cancelled through the tools and
    retried once; a paint recovered by another server over the same journal; a save finished by
    a new server once its first is gone.
  - **The probe's plumbing:**
    - `probe/common.stdio_server` (was `probe/__init__._server`);
    - `painting.run(…, serve)`;
    - `saving.run(report, a, b, client, harness, hard, serve)`;
    - server-c's journal folder, under the harness, which the journal check reads.
- **What the spec said that turned out wrong:** L1's block had one server hold a save and a fill
  both pending. One `serve` runs one tool call at a time (`tools.CALLS`), so that cannot happen.
  - On Fable's advice, the owner amended decision 4: one server ended mid-save, no live paint
    recovery.
  - The paint route stays with its unit test and the Codex agent's run.
  - The amendment is dated in the feature file and logged in L1's block.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call.** Propose one when a plan reworks a heavily tested
    path, and ask which model.
  - **Live runs and Krita restarts** were allowed at 0 unsaved with the Codex agent paused, each
    time they were asked for; ask again.
  - **The chat's last message is the workflow kit's one-line opener,** never this file's text.
  - **V1's version bump needs a restart.** The plugin holds its version equal to the package's,
    so V1 runs `install-plugin` and needs Krita restarted at 0 unsaved before its probe. The
    owner's MCP client restarts after; say so before restarting anything.
  - **Krita's memory after L1's runs.** Krita reached about 2.6 GB over L1's driver and probe
    runs, since each large save keeps memory. Then macOS swapped about 3 GB, and the last probe
    took 205 s against the baseline's 163 s. V1's restart clears it before the release probe;
    read a slow probe beside `sysctl vm.swapusage`.
- **Baseline** (ARCHITECTURE's table, v0.32.0, as L1 left it):
  - `verify`: 6 stages, all PASS; 1200 server tests and 1245 plugin-core tests, 0 skipped;
  - `probe`: 242 PASS, 0 FAIL, 28 MEASURED, about 163 s with 0 documents open, the journal check
    reading 870 dispatched lines;
  - 25 tools, 25 schema files, 30 error codes, 39 bridge ops, 17 capabilities, 29 parity tests,
    instructions 3,371 characters, `api_version` 0.4.0.
- **Not done:** nothing in L1's scope. The live paint recovery was dropped by the amendment, not
  skipped.

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
- **A server holds one call at a time** (`tools.CALLS`). A check that needs two calls in flight
  at once needs two senders.
- **In zsh, an unquoted variable is one word.** A loop that passes `$spec` meaning three
  arguments passes one; split it first.
- **V1's own traps are in its block:**
  - no test reads the owner's Krita folder or `kritarc`;
  - the stale-plugin gate stays as strict;
  - nothing from the handoff's evidence enters the repository;
  - a tag is not a push.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
