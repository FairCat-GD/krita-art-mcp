# FEATURE: recovery and construction (round 2)

## The request, verbatim (2026-11-02)

Private details are replaced by roles, as the PDD's were.

> read the attach feedback from the Codex agent and plan round 2.
>
> Main feedback from it:
>
> My main recommendation: fix mutation recovery first, then prioritize fills, masks, expressive marks,
> branching and reversible construction. Source inspection also confirmed the receipt bug and missing
> Hamming previews. The original review and MCP repository remain unchanged.
>
> after you have a plan - request adversarial review before presenting it to me

The intake traced the bug and measured where the reported cost goes, then surveyed the contract and
Krita's API. An adversarial review attacked the plan twice. The owner then asked that the open
points be settled directly with the Codex agent, which answered from its work and acknowledged the
decisions below. The owner approved the plan on 2026-11-02.

## The Codex agent's report, summarised

The report came from a real painting session on 0.16.0: 1,356 journaled calls, 1,349 completed, on
Krita 5.3.4.1, RGBA / U8 sRGB. Its art outcomes are the owner's and stay out of this file.

- **P1, a stroke can apply and then return a failed envelope with no operation id.** It was seen
  once and confirmed by inspection. `krita_operation_get` could not recover a valid receipt either.
  An agent cannot safely equate a failed envelope with an unapplied mutation, and a client that
  retried would paint twice.
- **Regression coverage it asks for.** Strokes at each edge and corner, with and without a
  selection, within the half-brush overhang, in both scopes; empty intersections;
  `krita_operation_get` after a post-application failure; same-request replay without duplicate
  paint; alpha, protection and undo as well as the response's shape.
- **Input and schema discoverability.** `krita_sample` gives 0–255 where a stroke takes 0–1. Brush
  size tops out at 1000, a resource page at 100. A native capture refuses `background`. The
  half-brush path tolerance differs from a brush's reach. Each was a clear refusal, but the limit
  was not visible beforehand.
- **What worked, and must not change.** Working copies, explicit protection, selections with
  feathering and alpha, full verification's evidence, previews at game size, verified saves, undo,
  and resource hashes.
- **Authoring.** Broad colour planes needed oversized strokes under polygon selections. Flat
  pressure makes thin contours and tapered groups hard. Wrap work needed paired shapes at opposite
  edges.
- **Not exercised.** Queued and running cancellation, idempotent replay, timeout recovery, resource
  hash races, owner concurrency, multi-writer documents, other colour models, filters, animation,
  per-point pressure.

**Its answers at the intake,** which shaped these decisions:
- A flat antialiased fill replaces the workaround; texture stays with finishing strokes.
- Masks are for soft edges and revising silhouettes without losing colour.
- Interior control over arc length beats endpoint tapers, and a proven subset still has value.
- Branching means both a layer or group trial and a whole-document alternative.
- Layer organisation comes before transforms, and scale and rotate are useful but unproven needs.
- Wrap, direct erasing and batches can wait.

## What the intake measured

### The bug

`plugin/krita_art_mcp_bridge/bridge_core/painting.py:204-207`: in full scope, a target whose bounds
leave `target_rect` has its whole bounds unioned into `diff`. `target_rect` is clipped to the canvas
(`:108`) and Krita's layer bounds are not, so overhang above or left of the canvas gives a negative
`x` or `y`, which the output schema's `minimum: 0` refuses.

Wider than reported:
- **Not only the overhanging stroke.** A layer that already has off-canvas paint trips it on every
  later `verify: full` stroke, wherever it lands. A KRA layer that overhangs, opened with
  `editable_layer_ids`, starts broken. Of 614 strokes journaled on 0.16.0, 612 were full scope.
- **Right and bottom overhang lie silently.** The schema passes, and `changed_bounds_px` reports the
  layer's bounds, past the canvas, not what changed.
- **Identity is lost at four levels:** the gate (`tools/__init__.py:141-145`); the lookup
  (`tools/operations.py:91-93`, which never settles the journal); the journal, which stores the bad
  receipt as settled (`tools/dispatch.py:120-131`); and the catch-all (`tools/__init__.py:138-140`).
- **Applied work is turned into failure on purpose.** `tools/changes.py:247,285,383` make a
  completed selection or history step `Failed`, and `:285` says `retryable=True`: an undo step was
  pushed and the agent is told nothing changed.
- **A raise after dispatch can leave a file behind.** `finish_save` → `_merged` → `file_sha256`
  (`tools/saving.py:117`) is unguarded: an `OSError` leaves the journal unsettled, no ids, and a
  hidden `.saving.kra` beside the target.
- **`retryable ⇒ nothing changed` is false at one plugin site.** `BUSY` (`saving.py:103`) comes
  after `drop_pending_save` (`:90`), so an earlier unfinished save is already gone.

Region scope was never affected. **The failing request,** for R1's regression: a 1254 × 1254 opaque
master, a new paint layer, no selection, `b) Basic-5 Size`, 20 px, opacity and flow 1,
`catmull_rom`, `verify: full`, points (372,-8), (376,4), (398,28), (401,55), (418,78). It reported
bounds {362,-17,66,104}. The true change is {364,0,63,87}, 1,923 px, alpha unchanged.

### Where the time went

Measured read-only on 2026-11-02, from the journal and the client's own records, as counts and
timings:

| Tool | Client wall clock | Tool call alone | Server dispatch |
|---|---|---|---|
| `krita_paint_stroke`, full scope | 2.41 s | 0.216 s | 0.221 s |
| `krita_selection_set` | 2.07 s | 0.041 s | 0.027 s |
| `krita_protection_set` | 2.46 s | 0.025 s | 0.012 s |
| `krita_layer_create` | 2.13 s | 0.052 s | 0.040 s |
| `krita_preview_render` | 0.03 s | 0.033 s | not journaled |

**46.8 minutes of wall clock, 3.1 minutes of tool calls.** Every tool annotated `destructiveHint:
true` carries about 2 s whatever it does, and every read-only tool carries none. Codex's
`requires_mcp_tool_approval` returns true for any destructive tool
(`codex-rs/core/src/mcp_tool_call.rs`), and those turns ran with `approvals_reviewer: auto_review`.

That auto_review itself spends the 2 s is **inferred** from the code path and a perfect correlation,
not observed. The Codex agent saw no denial or rewritten call, and cannot attribute it either.

**Honest hints alone buy little:** strokes and selections are 981 of about 1,150 destructive calls
and stay destructive, so decision 1 removes about 4 of the 47 minutes. The rest is the owner's
client setting (decision 2).

1,253 of 1,377 consecutive calls were under 0.25 s apart: the agent already scripts sequences
client-side, and `exec` stops on a failed envelope.

## Resolved decisions (2026-11-02, at intake)

1. **Hints follow each tool's worst permitted behaviour.** `destructiveHint: false` on the five that
   are honestly additive: `krita_layer_create`, `krita_protection_set`, `krita_document_open`,
   `krita_document_create`, `krita_document_save`. All other existing mutating tools remain
   destructive; existing read-only tools retain their truthful hints. New tools are audited against
   their worst permitted behaviour before hints are assigned. `readOnlyHint` stays false on every
   mutation. Undoable is not additive.
2. **Trusting this server in a client is the owner's setting, not a product hint.** The guide
   documents Codex's per-server approval mode, `default_tools_approval_mode = "approve"` under
   `[mcp_servers.krita-art]`, and what it removes: the review on every tool of this server, strokes
   and close included.
3. **No profile gate this round.** Every new tool goes through protection and verification.
   `permitted_operations` has no defined shape yet, and the framework stays in the backlog. **This
   amends the PDD's rule that every Phase 2 operation needs a profile's permission.**
4. **`details.outcome` says whether a failure applied:** `applied`, `not_applied`, `uncertain`,
   `unregistered`. One home, already read by the journal, passed through by Codex, and typed in the
   shared error schema.
5. **The authority is the bridge's operation record, and `uncertain` is the default.** `applied`
   means the handler returned and the bridge holds it `done`; nothing else may say it. A failure is
   `not_applied` only on proof: it raised before its op's change marker, or a rollback or cleanup
   was verified, or it is retryable, a rule tested at every retryable raise. Everything else is
   `uncertain`: an unexpected exception, an op with no marker, a discard that leaves a document
   registered. A change counter proves nothing either way. The window-wide brush is not a change
   here: a stroke sets it before its marker. After a Krita restart the journal's finished line
   answers, else `uncertain`.
6. **Application, rollback, verification and receipt validity stay separate fields:** `outcome`;
   `rolled_back` and `rollback_verified`; the receipt's `verification`; `receipt_valid` and
   `receipt_problem`.
7. **`applied` is never retryable,** and settles the journal as a receipt. `unregistered` means the
   bridge has no entry. A resend needs a request proven never dispatched, a retryable failure, which
   changed nothing, or a live Krita session whose dedup state covers that exact `request_id`; the
   same id alone is not enough. Unknown or restarted state stays `uncertain`, with no resend. Past
   the journal's 7-day window nothing remembers a request, so a retry reads as new: invariant 9's
   stated limit, unchanged. A finished line keeps its outcome, session and request; "finished" alone
   never means applied.
8. **`operation_id` exists from dispatch on.** A refusal before dispatch has none and is
   `not_applied`. A raw receipt comes back as structured data, not an exception string.
9. **`api_version` moves when a field or an input value is removed or renamed, or a field changes
   meaning.** Added fields and tools do not move it.
10. **Argument rules stay on both sides,** each pair held by a parity test. It settles the backlog's
    choice between one validator and parity tests.
11. **A refused value stays advertised only if a named phase will make it live.** It settles the
    backlog's question on schemas that advertise refusals, for the schemas this round amends.
12. **Branching a document is a verified save plus a reopen,** to a new `.kra` path, with its own
    baseline, inheriting the source's protection, allowed mask and flags. `Document.clone()` is not
    used: it is never added to `KisPart`, which `Krita.documents()` reads, so `Registry.sync` would
    drop it.
13. **A protected layer may be duplicated.** The original does not change. The copy is hidden by
    default, is the agent's own, and carries `derived_from`; a copied group reports the whole
    descendant tree in an `id_map`. The allowed mask and preserve-alpha still judge the composite.
14. **A mask may start from the current selection, even one from a PNG.** A mask is coverage, not
    paint; no layer pixel is written and the composite is checked. Its parent and every ancestor
    must be unprotected. Invariant 1's text and scan are extended to name this.
15. **Translate ships only on a native route, or not at all.** T1 probes a transform mask first. If
    a native route gives one undo step, a confirmed rollback and a KRA round trip, it ships. If not,
    translate waits for Phase 3's checkpoints, and T1 ships no version: a non-undoable move
    compensated inside one call is not recovery. This settles PDD Q13.
16. **Tapers are a bounded native probe with an explicit unsupported result.** No joined segments or
    flat shapes are labelled as strokes. `stroke.per_point_input` stays false either way.
17. **This file quotes the owner's request, with roles for private details, and summarises the
    agent's report.** No art subjects, pass numbers, inventory counts, project folders or evidence
    paths.
18. **Out of this round,** each moved to or kept in `docs/BACKLOG.md` with its reason: a server
    batch, wrap authoring and a tiled preview, direct erasing, profiles, filters, `canvas_resize`,
    `layer_import`, `paint_clone`, references, templates, flood fill, a closed-curve selection
    shape.
