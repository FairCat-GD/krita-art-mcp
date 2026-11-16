No round is in progress. Read CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline,
then this file; then the sections of docs/ARCHITECTURE.md the request touches. The next session is
an **intake**: write the owner's request down verbatim, ask what it leaves open, and plan the round
in `docs/spec/`, with a Read line in every block (see `docs/DEVELOPMENT-WORKFLOW.md`, *Rounds*).

## State you need that is not in the docs

- **krita-art-mcp 0.32.1 is released.** Round 4 (stable-release readiness: L1, V1) is closed. Its
  spec files are deleted. The last done-note is in `docs/spec/SESSIONS.md` as of the release
  commit (`1b357de`), and `docs/BACKLOG.md`'s header says how to read the rest.
- **What round 4 built:**
  - the probe keeps the recovery routes as live checks: a cancel behind H4's save, and a server
    ended mid-save whose save a new server finishes;
  - one payload check of the plugin's source, before `install-plugin`, `doctor` and the probe
    compare, hash or copy anything;
  - the install route said plainly: a checkout of a release tag;
  - Krita's close paths after a verified save, recorded as K56.
- **The release checks and the readiness report.** V1 ran the release checks on the release tree
  and recorded them in its done-note. The readiness report went into the chat alone (decision 8).
- **Tag status:** `v0.32.1` is asked for once the review commit exists and the checks have run
  again on it. Pushing the tag and making the repository public are separate approvals.
- **Push status:** `origin/main` holds everything through L1's review commit (`3ec6e4f`). The
  release (`1b357de`), this close and the review commit that follows wait for the next approved
  push; list `origin/main..HEAD` before it.
- **0.32.1 is installed and live.** V1 ran `install-plugin` and restarted Krita at 0 unsaved, so
  the running plugin is this checkout's. The owner's MCP client needs its own restart to pick the
  server up, and the Codex agent stays paused until it has.
- **Open items live in `docs/BACKLOG.md`,** among them what round 4 left there:
  - a standalone package with the plugin bundled;
  - the lost-reply and never-sent routes run live;
  - first activation on a fresh Krita profile;
  - Krita's export dialogs and mixed Close All orders on close;
  - a Krita that dies hard mid-call.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call.** Propose one when a plan reworks a heavily tested path,
    and ask which model.
  - **Live runs and Krita restarts** were allowed at 0 unsaved with the Codex agent paused, each
    time they were asked for; ask again.
  - **The chat's last message is the workflow kit's one-line opener,** never this file's text.
- **Baseline** (ARCHITECTURE's table, v0.32.1, measured at V1 on a restarted Krita):
  - `verify`: 6 stages, all PASS; 1213 server tests and 1245 plugin-core tests, 0 skipped;
  - `probe`: 242 PASS, 0 FAIL, 28 MEASURED, about 163 s with 0 documents open, the journal check
    reading 870 dispatched lines;
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
- **The term list is not empty.** Never assume its size, never print a term, and ask before any
  write to it.
- **Another agent works in Krita.** The Codex agent paints the owner's art through this server. Ask
  the owner before any probe or measurement run.
- **The journal in the data folder is the owner's own work.** Read it read-only, and record counts
  and timings alone: never a document path, a layer name or a folder.
- **Krita's memory grows across a probe** (about 3.7 GB after H4 at V1), and macOS swap slows
  saves; read a slow probe beside `sysctl vm.swapusage`.
- **Comments state the present.** No session ids, no "used to", no review stories.
- **Every push and every tag needs its own approval.** List `origin/main..HEAD` first.
