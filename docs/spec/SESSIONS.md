# The session plan: round 4, stable-release readiness

One chat per session. Never run two sessions in one chat: the point of the split is that no
session inherits stale context.

- **Scope** lives here, fixed in advance. The request and its resolved decisions are in
  `FEATURE-stable-release-readiness.md` beside this file, which is read-only; do not re-litigate
  them. If a session finds a block wrong, it amends the block and records the reason both in the
  block and in `docs/next-session-prompt.md`.
- **State** is `CHANGELOG.md` (what shipped) and `docs/next-session-prompt.md` (what the next
  session needs that the docs do not say). Every session rewrites the prompt as its last act.
- **When this round closes,** V1 deletes this file and the feature file. Git history keeps them,
  and anything left open moves to `docs/BACKLOG.md`.

**Before starting**, confirm the tree is clean and that `docs/next-session-prompt.md` names the
session you are about to do. **Read** in the workflow's order (the cycle, step 2), starting with
what your block's **Read** line names. **Then plan, in plan mode,** and ask the block's *Ask at the
start* questions before any edit.

**Every session ends the same way:**
1. `uv run scripts/verify.py` green, plus the harnesses the block names.
2. Every new check falsified, once. Checks that already existed are not falsified again.
3. A `CHANGELOG.md` entry for anything user-visible, and the version bumped as the table says.
4. The docs the block names kept true, and ARCHITECTURE's baseline table updated for any count that
   moved.
5. A done-note appended to the block, then the prompt rewritten, then `uv run scripts/verify.py
   --message <draft>` run with the drafted commit message, then a local commit.
6. The owner's `/code-review high`, then a review-fixes commit.
7. The one-line opener printed as the chat's last message.

Never push without being asked.

| Session | Scope | Decisions | Version |
|---|---|---|---|
| L1 | The recovery routes kept as checks: unit gaps, three live checks | 4, 7 | — |
| V1 | Setup diagnostics, the install route said plainly, the release checks and report; close | 1, 2, 3, 5, 6, 7, 8, 10 | **0.32.1**, tagged |

L1 changes tests and the probe alone, so it cuts no version: the plugin stays byte for byte the
installed one, the probe's hash check passes without `install-plugin`, and Krita needs no restart.
If L1 finds it must change the plugin or a tool, it stops and asks. V1 cuts the version, and the
plugin holds its version equal to the package's, so V1 runs `install-plugin` and needs Krita
restarted at 0 unsaved documents before its probe, and the owner's MCP client restarted after. Each
session asks the owner before any probe run, with the Codex agent paused.

---

## L1: The recovery routes kept as checks

**Read:** `FEATURE-stable-release-readiness.md` whole; `ARCHITECTURE.md` *Bridge and jobs*, *The
tool contract* (retries, outcomes and the replay paragraph), *Registry, lease and document state*
(the lease), *The save* (the finish), *The server*, *Testing strategy* (the probe's harness and the
journal check); `USER-GUIDE.md` *Retries and long calls*.

- **The unit gaps** (decision 4). Extend the tests named in the feature file's coverage table;
  do not duplicate what they already hold.
  - Cancel a queued `krita_layer_create` through `krita_operation_cancel`; `krita_operation_get`
    reads `cancelled`, `not_applied` and `receipt_valid: true`; the layer is absent; a retry under
    the same `request_id` runs once, and repeating it returns the same operation id with no second
    layer. Beside `tests/test_outcomes.py:571`; the plugin core already holds the retry
    (`tests/plugin/test_jobs.py:356`).
  - A paint whose reply came back running is recovered by a fresh server over the same journal:
    the poll reads `applied`, and a same-id retry adds no undo step. As
    `tests/test_document_tools.py:318` does for a create.
  - A save that came back running, then its server gone: a new server's poll reads `uncertain`
    with the retry guidance and finishes nothing; a same-id `krita_document_save` from the new
    server takes the lease, finishes and verifies. Beside `tests/test_save_tool.py:261` and `:285`,
    where the first process always lives.
- **Three live checks** (decision 4), in `src/krita_art_mcp/probe/saving.py`.
  - **Cancel,** behind the probe's existing long save (`_long_save`, `:647`), whose 8192² export
    keeps Krita's main thread busy for about 5 s. The layer create goes to a small document of its
    own, made by the probe's bridge client as H4's paint document is (`harness_call(client,
    "document.create", …)`). Not the working copy, which server-a leases, so the client's create
    would answer `DOCUMENT_IN_USE` and never queue; and not H4's paint document, whose check counts
    exactly one undo step (`_h4_checks`, `:751`). Cancelled while queued, the poll reads
    `cancelled` and `not_applied` with a valid receipt; once the save ends the layer is absent; the
    same-id retry runs once, and its repeat returns the same operation id. Cancelling the running
    save is `UNSUPPORTED_CAPABILITY`, `not_applied`.
  - **One server ended mid-save, holding a queued paint.** A server of the probe's own (`_server`,
    `probe/__init__.py:64`, with its own journal folder, never server-a) opens a working copy of a
    fixture of its own and saves it, and a fill on a second small document it holds is queued
    behind the save. The process is ended once, while both are pending. A new process over the
    same folder then, for the save, polls `uncertain` and finishes nothing, and the same-id save
    finishes with its file verified; for the fill, polls `applied`, and the same-id retry adds no
    undo step. That is two checks from one ended server and one save.
  - **The restart save is sized to stay running** past the server's end, and no larger: L1 measures
    the smallest recipe (from `fixtures.long_save_stack`) that does, rather than a second 8192²
    stack, and records the probe's added time and Krita's memory beside H4's MEASURED line.
  - Every check fails, never passes, when it did not see the state it is about (queued, running,
    pending at the moment the server ended).
- **Docs.**
  - `ARCHITECTURE.md`: *Testing strategy* (what the probe now holds of recovery, and that the
    lost-reply and never-sent routes are held by unit tests alone); the baseline (tests, PASS, the
    probe's time, the journal's dispatched lines).
  - `USER-GUIDE.md`: only if a check shows the guide wrong.
  - `CHANGELOG.md`: nothing of its own; the handoff names the probe's new checks, and V1's 0.32.1
    entry carries them in the user's words.
  - `docs/BACKLOG.md`: *A Krita that dies mid-call* gains what the handoff showed for an orderly
    quit, and stays for a hard one.
- **Ask at the start of L1:** how to falsify three live checks without a full probe run each
  (a temporary entry point that runs `_long_save` alone against the harness, or breaking each
  check's assertion in one combined run).

**Gates:**
- `uv run scripts/verify.py`, with these tests:
  - the three unit cases above, each failing on its own assertion when its rule is broken.
- `uv run krita-art-mcp probe`: 0 FAIL; PASS rises by the new checks; the journal check still
  passes, every ended server's call settled by its retry.

**Watch for:**
- **The lease passes on only once its holder is gone,** confirmed by `ps`. End the server's
  process and wait for it to exit before the new one mutates, or the retry answers
  `DOCUMENT_IN_USE`.
- **The journal check reads every server's folder** (`_nothing_uncertain`,
  `probe/__init__.py:262`) and fails on a request left unknown. An ended server's call must be
  settled by its retry in the new process, under the same folder.
- **The journal floor moves.** `MIN_JOURNALED` (340) is half a whole run's dispatched lines; the
  new calls raise the run's count, and the floor stays a floor, not a target.
- **A tool's operation id is not in hand while the tool awaits it.** Queue through the bridge
  client, as H4's paint does, or start the tool as a task and read the id from the journal.
- **Ending an MCP stdio client mid-call** must end the process, not only cancel the call. Check the
  pid is gone.
- **The probe's 238 PASS baseline moves by the checks added,** some of which may run in a loop;
  count from a run.

---

## V1: Setup diagnostics, the install route, the release checks; close

**Read:** `FEATURE-stable-release-readiness.md` whole; `ARCHITECTURE.md` *The CLI*, *Packaging*,
*Testing strategy*, *Registry, lease and document state* (Krita's flag), invariant 11 and the
reference rows K45 and K55; `USER-GUIDE.md` *What you need*, *Install*, *Register the server*,
*Update*, *`doctor` and troubleshooting*; README; `docs/BACKLOG.md`'s header and *Not yet checked
by hand*.

- **One payload check** (decision 2), with one home in `src/krita_art_mcp/plugin_files.py`: the
  source's package folder, its `__init__.py` and its `.desktop` exist and can be read. Its users:
  - `setup_checks.plugin_installed` (`setup_checks.py:35-49`), before the `.desktop` compare and
    the hashes. Step 1 says which of four it is: nothing installed; the installed copy differs; no
    plugin source beside this copy of the server; a source it cannot read. A source problem is
    checked first, and its fix says to run from a checkout, never `install-plugin`.
  - `setup_checks.plugin_current` (`:77-84`), `doctor`'s step 5 and the probe's first check
    (`probe/__init__.py:76`), so a missing source never hashes as the empty digest.
  - `install.run` (`install.py:9-12`), before anything is copied, so a source without its
    `.desktop` changes nothing in Krita's folder.
  - `doctor` stays six steps, and exits 1 with no traceback.
- **The install route said plainly** (decision 1).
  - README *Quick start* and `USER-GUIDE.md` *Install*: clone the repository at the release tag
    (named as the *Ask at the start* settles), `cd` into it, then the existing steps. A wheel or
    an sdist alone cannot install the plugin. *Update*: fetch the next tag, then the existing three
    steps.
  - `ARCHITECTURE.md` *Packaging*: the checkout is the one install route; what a built package
    holds and lacks; *The CLI*: the payload check.
  - No change to `pyproject.toml`'s build.
- **Krita's close paths, recorded** (decision 5): a K-row (K56) in `ARCHITECTURE.md`, as the
  handoff measured them on 5.3.4.1 (item 5 of its summary), and a line in *Registry, lease and
  document state* beside Krita's flag. The intake already took the item out of
  `docs/BACKLOG.md`.
- **The release checks, by hand** (decisions 6, 8), run on the release commit and recorded in the
  done-note, then run again on the commit to be tagged once the review commit exists, and recorded
  in the handoff, since the close has deleted the done-note's file by then. A review that changes
  only documents needs only the archive check again; one that changes code needs all of them:
  - `verify`, `probe` and `doctor`, with their counts;
  - `git archive` of the commit, unpacked in a scratch folder outside the checkout: it holds
    `plugin/` with its `.desktop`, `src/` with the 25 schemas, `pyproject.toml`, `uv.lock`,
    `LICENSE` and every document README links; `uv sync --locked` and `install-plugin
    --krita-data-dir <empty scratch folder>` work from there; its sha256 goes in the report;
  - a wheel built into a scratch folder and installed into a scratch environment answers
    `install-plugin` and `doctor` with the new message and exit 1, no traceback.
- **The readiness report** (decision 8), in the chat alone.
- **The tag** (decision 6): asked for after the review commit and the checks run again on it, made
  locally as `v0.32.1` on that commit, the one the checks describe, and never pushed without its own
  approval. `CHANGELOG.md`'s 0.32.1 link names the tag, and `[Unreleased]` compares it with `HEAD`.
- **The close:** the release commit carries the done-note; then `docs: close round 4` deletes
  `docs/spec/`'s files, `docs/BACKLOG.md`'s header names round 4's release commit beside rounds
  1 to 3, and the handoff says no round is in progress.
- **Docs.**
  - `USER-GUIDE.md`: *Install*, *Update*, *`doctor` and troubleshooting* (step 1's new failures).
  - `ARCHITECTURE.md`: *The CLI*, *Packaging*, K56, the header's version line, the baseline.
  - README: *Quick start*.
  - `CHANGELOG.md`: 0.32.1, with L1's probe checks beside V1's own changes.
  - `docs/BACKLOG.md`: the header, at the close; the round's left-out items stay as the intake
    wrote them.
- **Ask at the start of V1:** whether the README names the clone URL while the repository is still
  private, or says "the repository" until it is published.

**Gates:**
- `uv run scripts/verify.py`, with these tests in `tests/test_setup_commands.py`, on fictional
  temporary folders:
  - no plugin installed; an installed plugin with no source folder; a source folder without its
    `.desktop`; a `.desktop` without its package; a source it cannot read, where the platform
    enforces it; an installed `.desktop` that differs; a plugin hash that differs; an exact match;
  - `install-plugin` with a source missing its `.desktop` leaves Krita's folder unchanged;
  - `plugin_current` with no source fails;
  - the CLI's exit code and no traceback, run as a subprocess from a copy of the package with no
    `plugin/` beside it and `HOME` in a temporary folder.
- `uv run krita-art-mcp probe` and `doctor`: unchanged counts except what V1 moves.
- The release checks above.

**Watch for:**
- **No test reads the owner's Krita folder or `kritarc`.** `paths` defaults to the home folder;
  every test passes its folders in, and the subprocess case sets `HOME`.
- **The stale-plugin gate must stay as strict.** A friendlier message for a missing source must
  not let a differing hash pass. `test_doctor_finds_a_stale_installed_copy` and
  `test_doctor_and_the_probe_reach_a_stale_plugin_to_judge_it_by_hash` pass unchanged.
- **Nothing from the handoff's evidence enters the repository,** and the readiness report names no
  folder of the owner's.
- **A tag is not a push.** Ask before tagging; the tag and the repository's visibility each need
  their own approval.
