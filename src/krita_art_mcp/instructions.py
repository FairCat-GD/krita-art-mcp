from krita_art_mcp.bridge_client import WAIT_BUDGET_S

INSTRUCTIONS = f"""\
krita-art-mcp lets you paint in the owner's running Krita through Krita's own brush engine, \
with accepted art protected.

- Call krita_server_info first; do not plan around a capability its matrix marks supported: \
false. Its limits, and each field's description, give the ranges and units calls take.
- Every result has one envelope: api_version, status (completed, queued, running, failed or \
cancelled), document_id, revision (null), operation_id, data and error.
- A failed call returns error.code, a message, retryable and details. Retry only when retryable \
is true; otherwise act on the message.
- status running means Krita was still busy when the server's {WAIT_BUDGET_S:.0f}-second wait \
ran out: call krita_operation_get with its operation_id, never repeat the call. \
krita_operation_cancel stops only a queued call.
- Give every request_id a fresh UUID. Reuse one only to retry the same call: the retry returns \
the original receipt and never runs twice. A failure's details.outcome says what happened: \
applied (never retry it), not_applied, or uncertain (inspect the document first).
- Work on your own working copy. Another agent's document answers DOCUMENT_IN_USE; documents \
the owner opened by hand are read_only.
- Open accepted art with krita_document_open, mode working_copy, and a working_dir inside one of \
the allowed_roots, never the source's own folder. The source is never written; read_only opens \
it and refuses every change.
- Every layer present at open is protected, on purpose: add a layer of your own \
(krita_layer_create) before painting. To resume your earlier layers, reopen with \
editable_layer_ids (KRA) or editable_layer_names (ORA, PNG).
- krita_document_inspect shows layers, protection, the selection and how far history goes.
- To repair several regions, allow their union once with krita_protection_set (it only \
tightens), then confine each repair with krita_selection_set. An ellipse or polygon selection \
is antialiased: keep it a pixel inside the allowed mask.
- Undo steps: layer creation, selection commits and blend changes; other property changes \
cannot be undone. krita_history_step never goes below the last protection change.
- krita_layer_update checks appearance changes over the layer's bounds and undoes a leak; if a \
filter, mask, style, clone or copy blend could spread one, use verify full. Animated documents \
are refused. To recolour a silhouette under preserve_composite_alpha, paint on a new \
inherit_alpha layer.
- krita_paint_stroke paints one stroke per call, one undo step, checked like a layer change \
and undone on a leak. A preset whose tip or scatter cannot be read needs verify full.
- krita_capture returns an image and its PNG's path: scale 1 is the native crop, any other \
scale resamples.
- After every one to three strokes, check krita_preview_render at the asset's game sizes, from \
explicit recipes; a source's baseline_id shows the document as opened beside it.
- Keep work with krita_document_save to a new .kra path (it never overwrites); it reopens the \
file to verify it and clears dirty. An .ora drops masks and adjustment layers. A save takes \
up to 67 megapixels (8192 x 8192); a larger document can be painted in region scope, never saved.
- Use krita_sample for exact colours; a sample's color goes into a stroke's brush.color \
unchanged. Never judge a colour from a capture.
- No tool writes raw pixels or runs code. The owner may be watching Krita, and must not edit \
brush presets while you paint.
"""
