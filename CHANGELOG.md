# Changelog

All notable changes to krita-art-mcp are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
`major.minor.fix`.

## [Unreleased]

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

[0.1.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/6588c86b268e321401b27af53842d58c759f6b13
