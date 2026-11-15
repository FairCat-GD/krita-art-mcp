# FEATURE: what a save changed, and the knot limit (round 3)

## The request, verbatim (2026-11-15)

Private details are replaced by roles, and the handoff's path by what it is, as round 2's request
was.

> Read the Codex agent's follow-up handoff of 2026-11-14 (its README) and use its bundled fixtures
> to address the remaining Krita MCP issues. Prioritize the transparent-RGB save/reopen
> discrepancy and unclear dynamics-knot limit. Reproduce before fixing, add regression tests, and
> report what is fixed versus still unverified. Respect the settled backlog and leave production
> artwork unchanged.

The intake read the handoff and its evidence, traced both findings through the code, compared the
handoff's own captures pixel by pixel, and read one day of the journal for timings. It wrote no
product code. The owner settled three questions in plan mode and approved the plan on 2026-11-15.

## The handoff, summarised

The Codex agent ran a scratch drawing study on 0.30.0 (Krita 5.3.4.1, `api_version` 0.4.0): 124
recorded calls, none on the owner's production art, which its own checks found unchanged.

1. **Colour under alpha 0 differs after a grouped save and reopen.** Steps: a transparent
   768 × 640 RGBA / U8 / sRGB document; a group with one paint layer in it; three opaque polygon
   fills, `verify: "full"`; capture; save with verified reopen; reopen read-only; capture. Seven
   pixels go from `[0,0,0,0]` to `[103,97,118,0]`: (402,500) to (402,503), (521,493), (521,494) and
   (521,519). No pixel with alpha above 0 differs, and alpha is exact. The save reported
   `reopened_verified`, `layers_preserved` and `composite_preserved` all true, with no expected
   losses. One polygon fill on a layer at the root changed nothing across the round trip, though it
   already held colour under alpha 0: the negative control. The agent's acceptance criteria: choose
   and document the contract. If it is visible equality, say so, and report the raw difference
   apart, so no client infers byte equality. Add the case and the control as regression tests. Any
   cleanup of colour under alpha 0 must be explicit.
2. **The knot limit is not in the error.** A 16-knot size curve paints; a 17-knot one is refused
   before dispatch (`operation_id` null, `not_applied`, no canvas change), with a message that
   quotes a truncated array and never states the count or the maximum. Asked: confirm the limit,
   expose it in discovery and guidance, say it plainly, keep the refusal before dispatch, check
   opacity and both sides, and test 16, 17, bad order, missing endpoints and spacing apart.
3. **Routes that worked:** a branch with painted layers and a transparency mask; translating a
   group holding a partly painted mask, and its KRA; the refusal of an undo that splits an
   operation, and the undo with its `undo_steps`; scale, rotate and shear, each undone exactly; a
   translate leak outside an allowed rectangle rolled back and `not_applied`; a mask hidden and
   half revealed; size and opacity dynamics with the presets' hashes unchanged; a guarded save and
   close.
4. **Guidance.** Transform order (duplicate before resampling; scale, rotate and shear before
   masks and translation; translate last) belongs in discovery. Calls took about 3 s at the client;
   measure before any batch. Wrap authoring and per-point pressure stay as the backlog has them.
5. **The earlier save-state incident.** `dirty` and `krita_modified` are reported apart, and a
   guarded close after a verified save succeeded. Krita's own tab close, Close All, quit, and a
   hand edit after the save were not exercised. Confirm what `refuse` means when a verified save
   exists and Krita's flag stays set.

## What the intake measured

- **The save moves the live composite, then compares it.** `bridge_core/saving.py` `write`
  recomposes the projection (`port.refresh`) before `exportImage`, then hashes the live composite
  and compares it with the reopened file. So `composite_preserved` holds of the document as the
  save left it, and it held. Measured on the handoff's captures:
  - the capture before the save and the capture of the same live document after it differ in
    exactly the 7 reported pixels, all alpha 0 on both sides;
  - the capture after the save, the reopened capture and the KRA's `mergedimage.png` are equal
    byte for byte.
- **The paint frame does the same, half the time.** `Mutation.read` refreshes before a change's
  before-read (`bridge_core/mutation.py:238`); the after-read (`:317`) does not. The second fill's
  after-read and the third fill's before-read differ in 5 pixels, all alpha 0. Captures never
  recompose. So a change's `changed_px` can count such pixels, which the existing backlog item on
  changes under alpha 0 already allows for.
- **Neither state is free of colour under alpha 0:** 285 such pixels before the save, 292 after.
- **Not established:** why Krita's incremental projection differs from a recompose. The colour,
  `[103,97,118]`, is the first fill's, so the paint layer probably holds it under alpha 0 itself.
  P1 reads the layer to settle it.
- **The knot cap is 16 on both sides:** `maxItems` in `krita_paint_stroke.json` and
  `MIN_KNOTS, MAX_KNOTS = 2, 16` in `bridge_core/dynamics.py`, the count E1 proved live. The
  server's message is jsonschema's, which quotes the instance first, and `tools/__init__.py`
  `_short` cuts it at 200 characters, before "is too long". The cap is in the user guide, not in
  `limits` or the field's description.
- **Latency.** For that day's calls, the journal gives medians inside the server of 146 ms a fill,
  136 ms a stroke, 50 ms a layer create and 124 ms a save, where the agent's client saw about 3 s.
  The time is the client's, as the batch item in the backlog already says.
- **`refuse` after a verified save** is documented alike in the guide (step 10) and the close
  tool's description: it closes while nothing changed since, though Krita's flag stays set.
- **Transform order** is in `krita_layer_transform`'s description, not in the capability matrix.
- **Server instructions** have 25 characters spare above their 700-character floor.

## Resolved decisions (2026-11-15, at intake)

1. **`composite_preserved` stays byte-exact:** the reopened file equals the live document as the
   save left it. Its meaning does not change, so `api_version` stays 0.4.0.
2. **The save and the document duplicate report their own recompose,** as
   `recompose {changed_px, visible_changed_px, changed_bounds_px}`: how many composite pixels the
   save's recompose changed in the live document, how many of them had alpha above 0 before or
   after, and where.
3. **Nothing is cleaned, normalised or refused for it.** Recomposing before every after-read, and
   recomposing captures, are left out and go to the backlog.
4. **The knot cap stays 2 to 16 per option.** A refusal states the field, the count and the cap,
   and stays before dispatch. `krita_server_info`'s `limits` and the `dynamics` description state
   the cap.
5. **Transform order goes into discovery,** in the capability matrix's notes and the user guide,
   not the server instructions, which have no room.
6. **The fixed-versus-unverified report** goes into a reply file in the handoff's folder, outside
   the repository, and into the chat. The folder's path never enters the repository.
7. **Fixtures are recipes.** The probe and the tests rebuild the handoff's cases from their sizes,
   polygons, colours and knot arrays. No file of the handoff, nor its path, enters the repository.
8. **The sessions, in order:** P1 (0.31.0), the save's recompose; G1 (0.32.0), the knot limit,
   transform order, the reply, the release and the close. Two sessions place no architecture
   review.
9. **Out of this round,** each in `docs/BACKLOG.md`:
   - recomposing before a change's after-read, and before captures (decision 3);
   - a knot cap above 16;
   - Krita's own close paths after a verified save, a check by hand;
   - wrap authoring, proposed again as a workflow change, not a regression;
   - a server-side batch, and timing the server's share by stage, while that share stays small.
