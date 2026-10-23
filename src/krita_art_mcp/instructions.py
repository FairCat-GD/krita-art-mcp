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
{WAIT_BUDGET_S:.0f}-second wait ran out. Call krita_operation_get with its operation_id; \
do not repeat the call. krita_operation_cancel stops only a call still queued.
- Give every call that takes a request_id a fresh UUID. Reuse one only to retry the same call \
with the same arguments: the retry returns the original receipt and never runs twice. If a \
retry reports outcome uncertain, inspect the document before deciding what to do.
- Work on your own document: one working copy per agent. Another agent's document answers \
DOCUMENT_IN_USE, and documents the owner opened by hand are read_only.
- No tool writes raw pixels or runs code. Pixels change only through Krita's brushes.
- The owner may be watching Krita while you work.
"""
