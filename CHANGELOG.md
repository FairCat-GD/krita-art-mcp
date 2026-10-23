# Changelog

All notable changes to krita-art-mcp are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
`major.minor.fix`.

## [Unreleased]

## [0.3.0] — 2026-10-24

Agents can now make, list and close documents, and every change is safe to retry.

### Added

- **`krita_document_create`.** It makes a new transparent RGBA / 8-bit / sRGB canvas, opens it in
  Krita's window, and returns its id and its first paint layer. Other depths and colour profiles
  are refused with `UNSUPPORTED_CAPABILITY`.
- **`krita_document_list`.** It lists every open document with its id, name, path, size, colour
  space, whether an agent has changed it since its last save, and its mode. It never switches the
  document you are looking at. Documents you opened yourself are `read_only` to agents.
- **`krita_document_close`.** `refuse` will not close a document with unsaved agent changes;
  `discard` closes it anyway, without asking Krita to save. Documents you opened yourself are never
  closed by an agent.
- **`krita_operation_get` and `krita_operation_cancel`.** A call that comes back `running` can be
  followed to its final receipt. A call still waiting in the queue can be cancelled; one Krita is
  already running cannot.
- **Retries are safe.** Repeating a call with the same `request_id` returns the original receipt
  and never does the work twice, even through another agent's server. The same id with other
  arguments is refused with `REQUEST_ID_CONFLICT`. A call that Krita may or may not have finished
  before it quit is never sent again; it reports `outcome: "uncertain"`.
- **A journal of every change.** Each call that carries a `request_id` is written to
  `journal/YYYY-MM-DD.jsonl` in the data folder before it is sent, and again when it finishes.
- **One agent per document.** The server process that made a document holds it; another agent's
  changes to it are refused with `DOCUMENT_IN_USE` until that process has exited. Reading stays
  open to everyone.
- **Calls wait while Krita has a dialog open or more than one window,** and report
  `KRITA_MODAL_DIALOG` or `MULTIPLE_WINDOWS`. Both are retryable.

### Changed

- **`guard` is `{document_id, request_id}`** in every tool. `expected_revision` arrives with
  revisions in a later phase.
- **The instructions for agents** now cover fresh request ids, one working copy per agent, and
  following a `running` call with `krita_operation_get`.
- **`krita-art-mcp probe`** now makes and closes its own documents, including 20 create and close
  cycles. It runs those checks only when none of your documents has unsaved changes.

## [0.2.0] — 2026-10-23

The server now reaches a running Krita through a plugin, and offers its first tool.

### Added

- **The Krita plugin, Krita Art MCP Bridge.** Inside Krita it answers only this Mac, and only
  with a secret that changes every time Krita starts. It runs each request on Krita's main thread,
  one at a time. It costs no measurable CPU while Krita is idle, and it stops cleanly when Krita
  quits.
- **`krita-art-mcp install-plugin`.** It copies the plugin into Krita and says what is left to
  do: restart Krita, enable the plugin, and restart again. Run it again, then restart Krita, to
  update.
- **`krita-art-mcp doctor`.** It checks the setup in order and names the first step that fails,
  with its fix. It also says how many documents are open in Krita and how many have unsaved
  changes.
- **`krita_server_info`, an agent's first call.** It reports Krita's version, the plugin's and
  server's versions, and the capability matrix: what this build can do. Nothing beyond this call
  is supported yet. When Krita is not ready, it names the missing setup step instead. When Krita
  stays busy past the server's 45-second wait, it reports `running` instead of failing.
- **Instructions for agents.** Every client receives short rules with the server:
  - call `krita_server_info` first;
  - how errors and long calls are reported.
- **`krita-art-mcp probe`.** A live check against your running Krita. It confirms that the
  installed plugin matches the server, then measures how fast the tool answers.

### Changed

- **Every result carries contract version 0.2.0.**
  - `revision` is always `null` until revisions arrive.
  - Error codes come from a fixed list.
  - A cancelled operation reports `status: cancelled`.

## [0.1.0] — 2026-10-23

The first release is the scaffold that the Phase 1 tools are built on.

### Added

- **`krita-art-mcp serve` starts the MCP server.** It speaks over stdio as `krita-art` and
  reports its version to the client; it offers no tools yet.
- **`krita-art-mcp --version`.** It prints the installed version.

[0.2.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/6e9237f4f728f237ec855f84855f2c6eba2d077d
[0.1.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/6588c86b268e321401b27af53842d58c759f6b13
