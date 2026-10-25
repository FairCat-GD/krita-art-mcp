from krita_art_mcp.bridge_client import WAIT_BUDGET_S

INSTRUCTIONS = f"""\
krita-art-mcp lets you paint in the owner's running Krita through Krita's own brush engine, \
with accepted art protected.

- Call krita_server_info first. Its capability matrix says what this build supports; do not \
plan around a capability marked supported: false.
- Every result has one envelope: api_version, status (completed, queued, running, failed or \
cancelled), document_id, revision (null), operation_id, data and error.
- A failed call returns error.code, a message, retryable and details. Retry only when retryable \
is true; otherwise act on the message.
- status running means Krita was still busy when the server's {WAIT_BUDGET_S:.0f}-second wait \
ran out: call krita_operation_get with its operation_id, never repeat the call. \
krita_operation_cancel stops only a queued call.
- Give every request_id a fresh UUID. Reuse one only to retry the same call: the retry returns \
the original receipt and never runs twice. If a retry reports outcome uncertain, inspect the \
document first.
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
tightens), then confine each repair with krita_selection_set.
- Undo steps: layer creation, selection commits and blend changes; other property changes \
cannot be undone. krita_history_step never goes below the last protection change.
- krita_layer_update checks appearance changes over the layer's bounds and undoes a leak; a \
filter, transform mask, style or clone that may spread one needs verify full. To recolour a \
silhouette under preserve_composite_alpha, paint on a new inherit_alpha layer.
- krita_capture returns an image and its PNG's path. scale 1 is the native crop; other scales \
resample with your filter onto a background, checker by default. max_px (1600, at most 4096) \
bounds the long edge: capture tiles for more. A layer capture is the layer's own pixels, without \
its opacity, masks or inherit-alpha clip.
- Use krita_sample for exact colours (RGBA 0-255, hex, L*a*b*, L*C*h); a radius averages a disc, \
weighted by alpha. Never judge a colour from a capture.
- krita_resource_list lists brush presets (their id and sha256 are what paint calls take), \
blend modes, profiles and palettes.
- No tool writes raw pixels or runs code. The owner may be watching Krita while you work.
"""
