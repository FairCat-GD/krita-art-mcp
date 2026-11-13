No round is in progress. Read CLAUDE.md, docs/ARCHITECTURE.md's overview, invariants and baseline,
then this file; then the sections of docs/ARCHITECTURE.md the request touches. The next session is
an **intake**: write the owner's request down verbatim, ask what it leaves open, and plan the round
in `docs/spec/`, with a Read line in every block (see `docs/DEVELOPMENT-WORKFLOW.md`, *Rounds*).

## State you need that is not in the docs

- **krita-art-mcp 0.30.0 is released.** Round 2 (recovery and construction: R1, R2, R3, D1, F1, C1,
  M1, X1, X1a, E1, L1, B1, T1, S1, X2, X2a, V1) is closed. Its spec files are deleted; the last
  done-note is in `docs/spec/SESSIONS.md` as of the release commit (`40c7491`), and
  `docs/BACKLOG.md`'s header says how to read the rest.
- **What round 2 built,** on the Phase 1 round 1 shipped: every failed change says whether it
  applied (`details.outcome`); one verified-mutation frame under the paint and layer ops; flat
  fills; transparency masks; tapered strokes; layer duplicate, reorder and remove; a document
  branch; translate through a transform mask; scale, rotate and shear; truthful hints; and the
  discovery work on limits, colours and the forms Codex renders.
- **Push status:** `origin/main` holds everything through `e987f4a`. The release (`40c7491`), the
  close (`b078efb`) and the review commit above it wait for the next approved push; list
  `origin/main..HEAD` before it.
- **0.30.0 is installed and live.** V1 ran `install-plugin` and restarted Krita at 0 unsaved, so
  the running plugin is this checkout's. The owner's MCP client still needs its own restart to
  pick the server up.
- **Open items live in `docs/BACKLOG.md`.** Round 2 added, among others: the server-side batch with
  what V1 re-measured and what a decision still needs; the fake's pixel-step snapshot; a Krita quit
  while a taper holds a preset edited; a failed branch open naming the branch as its `document_id`;
  an undo that takes back the owner's own step; and the refusals that still say "Phase 1".
- **V1's review (`/code-review high`), 7 findings: 7 fixed.** `SESSIONS.md` was already deleted, so
  the findings and their fixes are in the review commit's message. Two of them correct V1's own
  done-note, which the release commit keeps as it was written:
  - **`doctor` did not pass 6 of 6 before the Krita restart.** That run stopped at step 1, because
    the version bump had not been installed yet; it read 0 open documents and 0 unsaved. It passed
    6 of 6 after `install-plugin` and the restart.
  - **V1 never established that the Codex agent was paused.** It checked that Krita held 0 open and
    0 unsaved documents, and nothing more.
- **Decisions written down nowhere else:**
  - **Plan reviews are the owner's call.** An adversarial review of the plan ran on Opus at X1a,
    E1, L1, B1, T1, S1 and X2a. Propose one when a plan reworks a heavily tested path, and ask
    which model.
  - **Live runs and Krita restarts** were allowed at 0 unsaved with the Codex agent paused, each
    time they were asked for; ask again.
  - **The batch question stays open.** The journal holds no session on the construction tools, so
    what fills and the layer ops already took off a batch is unmeasured.
- **Baseline** (ARCHITECTURE's table, v0.30.0, measured at V1):
  - `verify`: 6 stages, all PASS; 1177 server tests and 1223 plugin-core tests, 0 skipped;
  - `probe`: 231 PASS, 0 FAIL, 25 MEASURED, about 150 s with 0 documents open, the journal check
    reading 848 dispatched lines;
  - 25 tools, 25 schema files, 30 error codes, 39 bridge ops, 17 capabilities, 28 parity tests,
    instructions 3,371 characters, `api_version` 0.4.0;
  - Codex's renderer: the stroke's normalised input 4,378 of 5,000 bytes, 622 to spare.
- **Not done:** nothing from V1's block. The workflow re-measure ran on the journal alone, as the
  owner chose, because no session since fills exists.

## Watch for

- **The standing traps:**
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit
    with `git commit -F`, then delete the draft.
  - **Never `git checkout <path>`.** Stage explicit paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv is at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it for the project.
  - **A version bump touches `uv.lock`,** because `uv run` rebuilds the package; stage it with the
    other three version sites (`pyproject.toml`, the plugin's `PLUGIN_VERSION`, the version test).
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
- **The journal in the data folder is the owner's own work.** Read it read-only, and record counts
  and timings alone: never a document path, a layer name or a folder.
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
