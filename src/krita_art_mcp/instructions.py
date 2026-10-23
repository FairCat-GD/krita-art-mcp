from krita_art_mcp.bridge_client import WAIT_BUDGET_S

INSTRUCTIONS = f"""\
krita-art-mcp lets you paint in the owner's running Krita through Krita's own brush engine, \
with accepted art protected.

- Call krita_server_info first. Its capability matrix says what this build supports; a \
capability marked supported: false is not available, so do not plan around it.
- Every result carries the same envelope: api_version, status, document_id, revision (always \
null for now), operation_id, data and error. status is completed, queued, running, failed or \
cancelled.
- A failed call returns error.code, a one-line message, retryable and details. Retry only when \
retryable is true; otherwise act on the message, for example by asking the owner to start Krita.
- status running means Krita was still busy with the call when the server's \
{WAIT_BUDGET_S:.0f}-second wait ran out. Wait, then call again.
- No tool writes raw pixels or runs code. Pixels change only through Krita's brushes.
- The owner may be watching Krita while you work.
"""
