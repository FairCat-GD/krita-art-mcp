# FEATURE: stable-release readiness (round 4)

## The request, verbatim (2026-11-16)

The handoff's path is replaced by what it is, as round 3's request was.

> [the Codex agent's stable-release handoff of 2026-11-15, attached]
> Read docs/next-session-prompt.md: no round is in progress, so the next session is an intake.
> Review codex agent findings and plan the improvements

The intake read the handoff whole (its README, spec, test matrix, reproduction notes, drivers and
evidence), traced each finding through the code, and mapped what the unit tests and the probe
already hold of the recovery routes it ran. It wrote no product code. The owner settled five
questions in plan mode and approved the plan on 2026-11-16.

## The handoff, summarised

The Codex agent ran release checks on 0.32.0 (`96032fa`, Krita 5.3.4.1, macOS Apple Silicon,
`api_version` 0.4.0), at the owner's request, after round 3 closed. It edited no source and made
no commit. The owner's production art was unchanged, checked by hash before and after, and none of
it was used as a test canvas. Its own words: no new painting, cancellation, recovery or
native-close defect was found.

1. **The gates.** `verify`: six stages, 1,198 server and 1,245 plugin-core tests. `probe`: 238
   PASS, 0 FAIL, 27 MEASURED, 159.5 s. `doctor`: six steps pass.
2. **Cancellation, live.** A layer create queued behind a long fill was cancelled: polled
   `cancelled` and `not_applied` with a valid receipt, the layer absent; its same-id retry ran
   once, and repeating that retry returned the same operation id. Cancelling the running fill was
   `UNSUPPORTED_CAPABILITY`; cancelling a finished call reported `completed`.
3. **Recovery, live, with one injected transport fault per server.** A disposable server subclassed
   the bridge client to drop one reply after dispatch, or to fail before sending, with a 10 ms
   budget for that one call; Krita and the plugin ran unchanged. Fourteen assertions passed:
   - a lost fill reply comes back running with its operation id, the poll recovers it, a same-id
     retry adds no undo step, and other arguments under the id are `REQUEST_ID_CONFLICT`;
   - a failure before sending polls `unregistered`, and its same-session retry runs once;
   - a lost paint reply, then a new server process: the poll reads `applied`, the retry adds
     nothing;
   - a lost save reply: the same process's poll finishes and verifies the save;
   - a lost save reply, then a new server process: the poll reads `uncertain` and finishes
     nothing, and retrying the save under its `request_id` finishes and verifies the file.
4. **A Krita restart.** With a receipt left unsettled, then an orderly quit and relaunch, the poll
   and the retry stay `uncertain` and nothing is sent to the new session; a settled receipt answers
   from the journal. The drawing was checkpointed and closed before the quit: this is not a crash
   or power-loss test.
5. **Krita's own close paths, through its real UI,** on KRA working copies after a verified save:
   - a tab's close: Cancel keeps it open; Save writes the working file, with a `~` backup, and its
     merged pixels equal the verified save's;
   - Close All on two modified documents: Cancel keeps both, every file unchanged; then Save for
     one writes it, and Discard for the other leaves its file unchanged;
   - Quit: Cancel keeps the session; Save and Discard each end Krita's process, confirmed by its
     id and `bridge.json` gone before anything reactivated the app, and Krita relaunched cleanly;
   - a hand edit after the save (a layer's opacity, in the Layers docker): `dirty` stays false,
     `krita_modified` true, and a `refuse` close answers `DOCUMENT_DIRTY`, `not_applied`; Krita's
     Save on quit kept the edit exactly.
6. **From a fresh checkout:** a locked install, `install-plugin` into an empty test folder (56
   files exact, the `.desktop` present, another plugin left alone), and first-run guidance with no
   `kritarc` or `config.json` that created neither.
7. **From built packages, two confirmed problems.** `uv build` makes a wheel and an sdist, each with
   the 25 schemas and no plugin, no `.desktop` and no docs. The installed wheel's `install-plugin`
   exits 1 ("no plugin source … run it from the repo"), and its `doctor`, with a plugin already in
   Krita, raises `FileNotFoundError` reading the absent source `.desktop`. Its `serve` lists the 25
   tools and answers reads against the installed plugin.
8. **Not run:** first activation on a fresh Krita profile (the plugin listed in the Plugin Manager,
   enabled, restarted, `doctor` passing, a client registered). It needs a new user account, and
   `KRITA_ART_MCP_DATA_DIR` relocates only the server's data.
9. **Its limits, in its words:** the faults were injected, not a natural 45-second wait; no kill
   mid-write or power loss; KRA working copies only, not PNG or ORA export dialogs or every mixed
   Close All order; no other platform.
10. **Its recommendation:** keep the checkout as the one install route for a first public source
    release; fix the diagnostic; say plainly that a wheel or sdist alone cannot install the plugin;
    keep the missing recovery routes as regressions without fault code in production; no change to
    cancellation, the modified flag, roots or the painting design.

## What the intake found in the code

- **The doctor crash is confirmed:** `setup_checks.plugin_installed` (`setup_checks.py:41-42`)
  reads the source `.desktop` with no check. Two more of the same family:
  - `install.run` (`install.py:10`) checks only the source's package folder, so a source without
    its `.desktop` copies the package in, retires the old one, and then raises at
    `plugin_files.py:50`, leaving the plugin's folder new and its `.desktop` old;
  - `plugin_files.source_hash` of a missing folder is the empty digest, so a missing source and a
    missing install compare equal. `plugin_current` (`setup_checks.py:77-84`), which `doctor` and
    the probe's first check both call, hashes the source with no check.
- **The package gap matches the layout:** `uv_build` with `src/` packs `src/krita_art_mcp/` only,
  and `paths.plugin_source()` (`paths.py:55-57`) is the checkout's `plugin/`. ARCHITECTURE
  *Packaging* already says there is no PyPI package; README and the guide imply a checkout without
  saying how to get one.
- **What already holds the recovery routes:**

  | Route | Unit tests | Probe |
  |---|---|---|
  | Cancel a queued call | Partly: `tests/test_outcomes.py:571`, a stroke through the client, no `receipt_valid` | No |
  | Retry after a cancel | Partly: `tests/plugin/test_jobs.py:356`, in the plugin core only | No |
  | Cancel a running or a finished call | Yes: `tests/test_document_tools.py:392` | Finished only: `probe/__init__.py:387` |
  | A lost reply, a poll, a conflict | Yes: `tests/test_document_tools.py:318`, `tests/test_outcomes.py:545` | Partly: H4's queued retry (`probe/saving.py:774`) |
  | Never sent, `unregistered` | Yes: `tests/test_document_tools.py:699` | No |
  | A new server recovers a paint | Partly: `tests/test_document_tools.py:318` does it for a create | No |
  | The same process finishes a save | Yes: `tests/test_save_tool.py:245` | No |
  | A new server, after the first is gone, finishes a save | Partly: `tests/test_save_tool.py:261`, `:285`; the first process always lives | No |
  | A Krita restart | Yes: `tests/test_outcomes.py:439`, `:456` | No |

- **The lease passes on once its holder is gone,** which `ps` confirms (ARCHITECTURE *Registry,
  lease and document state*), so a new server can finish a dead one's save.
- **No injection seam:** `serve` builds `BridgeClient()` with no arguments (`server.py:35`), and
  nothing in the probe drops a reply. The probe's servers are separate processes with their own
  journal folders (`probe/__init__.py:64`).

## Resolved decisions (2026-11-16, at intake)

1. **Checkout only.** The supported install is a checkout of a tagged release, on macOS, Apple
   Silicon, Krita 5.3.x, as the guide already describes. No packaging change. A wheel or an sdist
   alone is unsupported, and the README, the guide, `install-plugin` and `doctor` say so: run from
   a checkout.
2. **One payload check.** The plugin's source (its package folder, `__init__.py` and `.desktop`)
   is checked present and readable before anything is compared, hashed or copied, by
   `install-plugin`, `doctor`'s first and fifth steps, and the probe's first check. `doctor`'s step
   1 tells apart nothing installed, an installed copy that differs, no source beside this copy, and
   a source it cannot read. It exits 1, never with a traceback. The stale-plugin gate (invariant
   11) is not weakened, a missing source never matches, a partial install never happens, and no
   diagnostic touches a plugin, `kritarc` or `config.json`.
3. **First activation on a fresh Krita profile goes to the backlog,** under *Not yet checked by
   hand*, with the handoff's sequence in public-safe words. The readiness report says it is
   unverified.
4. **Recovery: the unit gaps, and three live checks.**
   - Unit: cancel a queued call through the tool, then retry it and repeat the retry; a paint
     recovered by a new server; a save finished by a new server after the first is gone.
   - Live, behind the probe's existing long save: cancel a queued call and retry it; end a server
     mid-save and finish the save from a new one; end a server with a paint queued and recover it
     from a new one.
   - No fault-injection code, in the probe or in production. The never-sent route and a Krita
     restart stay held by unit tests, with the handoff's live run as their evidence.
5. **The handoff settles "Krita's own close paths after a verified save".** It is recorded in
   ARCHITECTURE as measured on 5.3.4.1, and leaves the backlog's *Not yet checked by hand*; what
   the handoff did not try stays there.
6. **The round ends on a tag.** Its last session cuts 0.32.2 and asks before tagging it `v0.32.2`
   locally. Pushing the tag and making the repository public are separate approvals, outside this
   round.
7. **Fixtures are recipes,** and nothing of the handoff's evidence enters the repository: no file,
   no path, no receipt, and no name of the owner's art.
8. **The readiness report** (the install route, the final commit, version and archive hash, the
   gates' counts, what stays unverified, a stable or not-stable call for that scope) goes into the
   chat alone.
9. **The sessions, in order:** L1 (0.32.1), the recovery routes kept as checks; V1 (0.32.2,
   tagged), setup diagnostics, the install route, the release checks, the report and the close.
   Two sessions place no architecture review.
10. **Out of this round,** each in `docs/BACKLOG.md`:
    - a standalone package with the plugin bundled as package resources;
    - the lost-reply and never-sent routes run live through a probe-only fault server;
    - first activation on a fresh Krita profile (decision 3);
    - Krita's PNG and ORA export dialogs, and mixed Close All orders, on close.
