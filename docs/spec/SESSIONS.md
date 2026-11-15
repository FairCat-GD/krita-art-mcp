# The session plan: round 3, what a save changed, and the knot limit

One chat per session. Never run two sessions in one chat: the point of the split is that no
session inherits stale context.

- **Scope** lives here, fixed in advance. The request and its resolved decisions are in
  `FEATURE-save-recompose-and-knot-limit.md` beside this file, which is read-only; do not
  re-litigate them. If a session finds a block wrong, it amends the block and records the reason
  both in the block and in `docs/next-session-prompt.md`.
- **State** is `CHANGELOG.md` (what shipped) and `docs/next-session-prompt.md` (what the next
  session needs that the docs do not say). Every session rewrites the prompt as its last act.
- **When this round closes,** G1 deletes this file and the feature file. Git history keeps them,
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
7. The next prompt printed as the chat's last message.

Never push without being asked.

| Session | Scope | Decisions | Version |
|---|---|---|---|
| P1 | The save reports what its own recompose changed | 1, 2, 3, 7 | **0.31.0** |
| G1 | The knot limit said plainly, transform order, the reply; release and close | 4, 5, 6, 7, 9 | **0.32.0** |

Both sessions change the plugin, so each runs `install-plugin` and needs Krita restarted at 0
unsaved documents before its probe, and the owner's MCP client restarted after. Each asks the owner
first, with the Codex agent paused.

---

## P1: The save reports what its own recompose changed

**Read:** `FEATURE-save-recompose-and-knot-limit.md` whole; `ARCHITECTURE.md` *The save*, *The
verification core*, *The tool contract* (the `api_version` rule and the replay paragraph), *Reads,
and K46*, *Testing strategy*, and the reference rows K12, K39, K42 and K45; `USER-GUIDE.md`
step 9.

- **Reproduce first** (decisions 1, 2, 7).
  - A probe check in `src/krita_art_mcp/probe/saving.py`, beside `_round_trips`, built from the
    feature file's recipe: a 768 × 640 transparent document, a group, a paint layer in it, the
    three polygon fills with `verify: "full"`; then capture, save, capture, close, reopen
    read-only, capture. Beside it the control: one polygon fill on a paint layer at the root. The
    polygons and colours are in the feature file's summary of the handoff, item 1; P1 copies them
    from the handoff's recipe as plain numbers.
  - Two checks, apart. The drift: the probe's captures before and after the save differ, under
    alpha 0 only; this one shows the case reproduces, and its counts and coordinates are recorded
    beside the handoff's seven. The receipt: it accounts for every pixel the save changed. Run
    both against the installed 0.30.0 plugin before any plugin edit: the drift check must PASS
    and the receipt check FAIL at its own step. A drift check that fails means the case did not
    reproduce, and P1 stops to say so.
  - A plugin-core test with a stale projection, through the fake's `render` and `projection`
    (`tests/fixtures/fake_krita.py:118-121`, `_redraw` at `:386`), failing on today's code.
  - Settle the intake's hypothesis: read the grouped case's paint layer itself (`krita_capture`,
    `target: "layer"`) at the changed pixels, to see whether the layer holds the first fill's
    colour under alpha 0. Record it as a K-row (K55 is next) whatever it shows.
- **The receipt** (decisions 1–3).
  - `bridge_core/saving.py` `write` (`:140-155`): inside the existing `unmasked_view`, read the
    composite before `port.refresh`, and compare it with the composite after. `write` already
    reads the whole composite after the export to hash it (`:155`), and the export does not move
    the projection, so one read after the refresh serves both the compare and the hash. Add a
    pure helper to `bridge_core/verification.py`, beside `changes()`, that also counts the pixels
    with alpha above 0 on either side. A canvas is up to 8192² × 4 bytes (`_check_size`), so never
    hold more than the two reads at once, and drop the first once compared; if that is too much
    at 8192², compare band by band through `composite_rects`.
  - The save's result and receipt gain `recompose {changed_px, visible_changed_px,
    changed_bounds_px}`; `Pending.receipt` carries it to the finish.
  - The duplicate's receipt is not the finish's: `document.duplicate_open` builds it
    (`bridge_core/branching.py:80`) from a `Placed`, which the finish makes from the pending save
    (`saving.py:261`) and which keeps only the path, the hash and the inheritance. `Placed` carries
    `recompose` from the save, and the open's result returns it.
  - Server: `tools/saving.py` `SAVE_DATA` and the receipt's text (a count, only when not zero);
    `tools/branching.py` `DUPLICATE_DATA`; both output schemas, the field required, with
    descriptions that state the contract. `composite_preserved` is byte-exact against the document
    as the save left it; `recompose` is what the save's own recompose changed in the live document
    first. Run `scripts/amend_schemas.py` if the shape joins its shared list.
  - `composite_preserved` keeps its meaning, so `api_version` stays 0.4.0.
  - Nothing is cleaned, normalised or refused for it (decision 3).
- **Docs.**
  - `ARCHITECTURE.md`: *The save* (the recompose and its count); K55; the `api_version`
    paragraph (0.31.0 adds a field, so it stays); the baseline.
  - `USER-GUIDE.md` step 9: what `composite_preserved` and `recompose` promise, and that a capture
    taken before a save can differ from the saved file in colour under alpha 0.
  - `CHANGELOG.md`: 0.31.0. `BACKLOG.md`: what P1 learned of the cause, in the item on a change's
    after-read.

**Gates:**
- `uv run scripts/verify.py`, with these tests:
  - the helper: changes under alpha 0 only, visible changes, none, an empty rect, a band boundary;
  - a save over a stale projection reports what the recompose changed and still compares
    byte-exact; a save over a current one reports zeros;
  - the duplicate's open returns it from its `Placed`, and the finish's receipt carries the
    save's;
  - both tools' server receipts, and each schema's example.
- `probe`, on the owner's yes with the Codex agent paused:
  - before the fix, the drift check PASSes and the receipt check FAILs;
  - after `install-plugin` and a Krita restart at 0 unsaved, it PASSes: the receipt's counts
    equal the probe's own diff of its captures before and after the save, the capture after the
    save equals the reopened one byte for byte, and the control reports 0 while it holds colour
    under alpha 0;
  - the counts and coordinates are MEASURED, and so is a save of an 8192² document, timed before
    and after the change.

**Watch for:**
- **The probe refuses a changed plugin** (invariant 11). Run the reproduction before the first
  plugin edit; after it, nothing live runs until `install-plugin` and a Krita restart.
- **A receipt the journal replays is checked against today's schema** (*The tool contract*). A
  required `recompose` turns a retry across the release into `INTERNAL_ERROR`, `applied`, which is
  the documented trade. Never loosen the schema for it.
- **The frame's after-read does not recompose** (`bridge_core/mutation.py:317`), while its
  before-read does (`:238`), so the same pixels show inside a change's own verification. Leave it:
  decision 3 put it in the backlog.
- **Never normalise in a test or the probe.** The finding is the bytes, compared raw.
- **The handoff's files stay outside the repository.** The fixtures are recipes (decision 7), and
  no name from the handoff enters a file or a message.

---

## G1: The knot limit said plainly, transform order, the reply; release and close

**Read:** `FEATURE-save-recompose-and-knot-limit.md` whole; `ARCHITECTURE.md` *Painting* (the
taper's rules), *The server*, *The tool contract*, *Testing strategy*; `USER-GUIDE.md` step 6's
dynamics, the transform section and *What it cannot do*; `docs/BACKLOG.md`; P1's done-note.

- **Tests first** (decision 4), each failing on today's code where it should:
  - for `size` and for `opacity`, each alone: 17 knots, 1 knot, a first `at` other than 0, a
    last `at` other than 1, an `at` that falls, and two knots under 0.001 apart are each refused,
    on both sides, through `refused_alike` in `tests/test_parity.py`, which today holds
    `knots-start` and `knots-apart`, and `too-many-knots` for size alone;
  - 16 knots, for each option, pass the server's rules and the plugin's `dynamics.check` alike:
    tests of their own, since `refused_alike` asserts that both sides refuse;
  - the 17-knot refusal has a null `operation_id`, reads `not_applied`, writes no journal line,
    and sends nothing to the bridge;
  - its message names the field, the count and the cap, within `MAX_MESSAGE_CHARS`.
- **The message.**
  - `tools/__init__.py` `_said` (`:295`): a `maxItems` or `minItems` problem reads as its count and
    bound, from `problem.instance` and `validator_value`, never the quoted array. It serves every
    tool.
  - `bridge_core/dynamics.py` `_check_knots` (`:44`) says the count it got.
  - `refused_alike` compares the code, `retryable` and the outcome, not the wording, so the two
    messages may differ.
- **Discovery.**
  - `limits.dynamics_knots {min, max}` in `tools/observe.py` `LIMITS` and
    `krita_server_info.json`, held by a test to `dynamics.MIN_KNOTS` and `MAX_KNOTS` and to the
    stroke schema's `minItems` and `maxItems`, as `tests/test_envelope.py:142-146` holds the
    brush's.
  - The `dynamics` description says 2 to 16 knots. Codex's renderer has 622 bytes to spare on the
    stroke.
  - The instructions stay as they are: 25 characters above their floor.
- **Transform order** (decision 5): the notes of `layer.translate`, `layer.scale`,
  `layer.rotate` and `layer.shear` in `bridge_core/capabilities.py` say it (copy first; scale,
  rotate or shear before adding masks or translating; translate last), and so does the guide's
  transform section.
- **The reply** (decision 6), after the release commit: a file in the handoff's folder, outside
  the repository, and the same in chat.
  - Fixed, with versions.
  - Measured and left in the backlog, with the reason.
  - Still unverified: Krita's own close paths after a verified save, cancellation and timeout
    paths, the recompose's cause if P1 did not settle it, a cap above 16.
  - `refuse` after a verified save, answered from the guide and the close tool as they stand.
- **Release 0.32.0, then close the round,** as the workflow says: the release commit with the
  last done-note, then `docs: close round 3` deleting `docs/spec/`'s files, the handoff saying no
  round is in progress, and BACKLOG's header naming round 3's release commit.
- **Docs.** `USER-GUIDE.md` (the knots, `limits`, transform order); `ARCHITECTURE.md` *Painting*,
  *The server* and the baseline; `README.md` if a count it states moves; `CHANGELOG.md`: 0.32.0;
  `docs/BACKLOG.md`.
- **Ask at the start of G1:** the handoff folder's path for the reply. It never enters the
  repository.

**Gates:**
- `uv run scripts/verify.py`, with the tests above.
- `probe`, on the owner's yes with the Codex agent paused, after `install-plugin` and a Krita
  restart at 0 unsaved: a 17-knot stroke refused with its count and cap, before dispatch, the
  canvas unchanged; a 16-knot stroke paints; `limits.dynamics_knots` matches.
- `doctor`: 6 of 6.

**Watch for:**
- **`_said` serves every tool,** so every `minItems` and `maxItems` problem gets the new wording.
  Run the message tests in `tests/test_tools.py` (`:160-262`) and the size test for Claude Code's
  token limit.
- **The review follows the close,** so its findings go in the review commit's message and the
  handoff.
- **A release restarts the MCP client too.** Tell the owner before the restart.
- **The reply lives outside the repository,** so it may name what the repository cannot. Nothing
  from it comes back in.
