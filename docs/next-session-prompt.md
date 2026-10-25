Read docs/spec/SPEC.md §1 (decisions 6, 20) and §5 (invariants 1, 5, 6), docs/spec/PDD.md Part 4
(`krita_paint_stroke`, *States & edge cases*), Part 5 (N-01, N-06 to N-09) and Part 8 (K2 to K5,
K9, K10, K18, K21, K30, K37, K43, K44, K47), docs/spec/REVIEW-2026-10-24.md (F2, F3, F5, F10,
F19), CLAUDE.md, then this file. Then do Session 9 of docs/spec/SESSIONS.md: paint_stroke,
verified per stroke, with the N-01 and N-09 benchmarks and review 6's amendments to its block.
Release 0.9.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Sessions 0 to 8, 6a and 7a are done; 9 to 15 remain,
  releasing 0.9.0 to 0.13.0.
- **The push status.** `origin` is the private GitHub repository `FairCat-GD/krita-art-mcp`.
  `origin/main` holds everything through session 8's review commit ("review: only copy and
  destination blends refuse region, and 9 smaller"), pushed with the owner's approval; nothing
  is local. List `origin/main..HEAD` before any push.
- **What 8 built that 9 stands on** (block 8's done-note has the detail):
  - **The verification core** (`bridge_core/verification.py`), pure and tested on 3.10:
    - `reach(tree, effects, target)` lists every node that can carry a change past the target's
      bounds;
    - `scope(mode, tree, target, size)` gives the region or the canvas; a stroke passes its own
      R instead;
    - `refuse_unverifiable(info, effects, rect)` refuses animated documents, another frame and
      a scope over one read;
    - `allowed_rows(handle, size, rect)` gives the allowed mask over a scope;
    - `read(port, document, rect, target_id, hashed)` reads the composite (unmasked, K46), and
      optionally the target's own pixels and a SHA-256 per hashed paint layer;
    - `check(before, after, allowed, preserve_alpha)` gives a `Verdict` with flags, counts,
      changed bounds, `protected_changed` and `leaked`;
    - `same(before, again)` confirms a rollback byte for byte;
    - `files(...)` writes before and after (up to 2048², `MAX_IMAGE_PIXELS`) for a pass and
      before and the flags for a refusal, never failing the call.
  - **What a stroke must still wire.** `layer_update` passes no `target_id` and no `hashed`: the
    target read, the protected hashes and the target's bounds check are built and unit-tested,
    and first used by the stroke. `protected_pixels_changed` from protected layers' before and
    after buffers is not built.
  - **The rollback pattern** is `layer_update._roll_back` / `_restore`:
    - refresh, then the before-read (a stale projection would otherwise read as the change);
    - `before_change()` before the first write, and every failure after it rolled back and never
      retryable (a retryable failure makes the bridge forget the request, so a retry would paint
      again);
    - native undo through `history.move(..., known=step.after)` and `ledger.rolled_back()`;
    - a refresh, then `same()` with the before-read and the tree;
    - confirmed: `dirty = was`; otherwise `handle.unsafe` and `ROLLBACK_FAILED`.
  - **The server side** (`src/krita_art_mcp/verification.py`, `tools/changes.resolve_update`):
    - `<op>.before.png`, `<op>.after.png` and `<op>.diff.png`, each found before made through
      `verification.keep`, which the selection's mask and history's capture share; raw files stay
      until their PNG exists;
    - the diff image of offending pixels, at most 1024 px, inline in the error result when it
      fits under `INLINE_BYTES`;
    - images null when another server took the pixels, never a changed outcome;
    - the plugin computes the counts, the server only the images (owner, at plan time).
  - **The fingerprint carries each node's blend mode,** so history tells the bridge's blend step
    from a hand-made one with the same label.
  - **`harness.add_node`** adds a blur filter layer, a blur filter mask, a transform mask or a
    clone; it seals the ledger.
- **What the specs said that turned out otherwise** (block 8's amendments and measurements):
  - **Region scope is refused for more than PDD Part 4 lists:** copy and destination blends on
    the changed layers (Krita composites them past the extent), derived-bounds layer types (clone, fill, file, vector, filter as a target), filter layers
    nested in later siblings, animated documents. A stroke's R analysis should use `reach` as it
    is.
  - **Under `inherit_alpha`, Krita writes colour into fully transparent composite pixels** (1,728
    px changed, 768 visible). The checks compare every byte, so an `inherit_alpha` recolour that
    spills past a silhouette inside an allowed mask counts the invisible pixels. It is in
    `docs/BACKLOG.md`; a stroke with a selection keeps inside it, but decide with the owner if the
    N-08/H8 runs trip on it.
  - **Krita was killed opening an 8192 × 8192 two-layer ORA through the bridge,** with no crash
    report and no clean shutdown; 4096 × 4096 opened in 0.6 s. N-09 needs an 8k master with 30
    layers: open it on its own first and watch Krita's memory (F10 asks for that too), and stop
    and ask if Krita dies again.
  - **4096 × 4096 costs:** a verified layer update 0.57–0.64 s, a leak with rollback 0.79 s.
- **Baseline** (session 9 moves it only by what it adds):
  - `verify`: 6 stages, all PASS;
  - 436 server tests passed, 0 skipped;
  - 442 plugin-core tests passed, 0 skipped;
  - `probe`: 75 PASS, 0 FAIL, 25 MEASURED, about 39 s;
  - 16 registered tools; 19 schema files; instructions 2,910 characters (F5: session 9 adds at most
    300 net).
- **Not done:**
  - **The owner's roots.** `doctor` step 6 FAILs with "no roots" until the owner runs
    `roots add`. No session runs it, and the probe needs no roots.
  - **By hand** (in `docs/BACKLOG.md`): N-03 in Activity Monitor; whether a K46 switch visibly
    moves the tab; the overlay in the mask display mode; K46 with the global selection's mask; a
    layer style refusing region scope.

## Watch for

- **The standing traps:**
  - **Never `git checkout <path>`.** Stage explicit paths.
  - **Give stdin-reading commands `< /dev/null`.**
  - **The Python toolchain:** uv at `~/.local/bin/uv`; CPython 3.12 and 3.10 are uv-managed;
    `/usr/bin/python3` is 3.9.6, never use it for the project.
  - **The owner's Krita is live.** No session touches their documents. Restart Krita only when
    `doctor` reports 0 unsaved documents, and ask the owner first; another agent may be working.
    `osascript` quitting Krita reports "User canceled" yet Krita quits: wait for the process to go.
  - **Nothing private in any file or commit message.** Last before each commit: draft the
    message into `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it
    (`--message`), commit with `git commit -F`, delete the draft.
- **A stroke is the first step whose pixels change.** History's region, capture and hash have been
  unit-tested only until now (block 7's known debt): check them live.
- **The probe's update checks** set opacity values in a fixed order; a new check on those
  documents must use values no earlier call set, or a no-op will hide its break.
- **The scan bans every `.apply` attribute,** not only `Filter.apply`: name no function `apply`.
- **Every plugin change needs `install-plugin` and a Krita restart** before `probe` or `doctor`
  step 5 passes, a version bump included.
- **Falsify each new check once.** The scratchpad driver of 6a to 8 works: break one line, run
  only its test, count only a pytest exit of 1, copy the file back, compare the tree's diff hash.
  Live checks need a server break, or plugin builds with restarts: batch independent plugin breaks,
  and split builds so no break makes another check fail for its own reason.
- **The probe's export can answer `BUSY`** when Krita's autosave holds the harness document; a rerun
  passes.
- **Comments state the present.** No session ids, no "used to", no review stories, no finding
  numbers in code.
- **Every push needs its own approval.** List `origin/main..HEAD` first.
