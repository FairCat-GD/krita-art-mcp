# krita-art-mcp

An MCP server and a Krita plugin that let AI agents paint in Krita. An agent can inspect a
painting, protect accepted work, paint with Krita's own brush engine, check the result at game
size, and undo or keep it. It is for painted (non-pixel) 2D game art.

## Status

Phase 1 is being built. Version 0.3.0 connects the server to a running Krita through the plugin
and offers these tools:

- `krita_server_info`: Krita's version and what this build can do;
- `krita_document_create`, `krita_document_list` and `krita_document_close`: new transparent
  RGBA / 8-bit / sRGB canvases, every open document, and closing an agent's own documents;
- `krita_operation_get` and `krita_operation_cancel`: following a long call to its receipt, and
  cancelling one still queued.

Every change is journaled before it is sent and is safe to retry with the same `request_id`.
The painting tools arrive in the coming releases; `CHANGELOG.md` lists what each one adds.

## Requirements

- macOS on Apple Silicon.
- Krita 5.3.x.
- [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for the server, and Python 3.10 for
  the plugin's tests.

## Installing

1. From this repository, copy the plugin into Krita:

   ```bash
   uv run krita-art-mcp install-plugin
   ```

2. Quit Krita and start it again.
3. In *Configure Krita › Python Plugin Manager* (in the application menu on macOS), enable
   *Krita Art MCP Bridge*.
4. Quit Krita and start it again.
5. Check the setup. `doctor` names the first step that fails, and how to fix it:

   ```bash
   uv run krita-art-mcp doctor
   ```

To update the plugin, run `install-plugin` again and restart Krita.

## Registering the server

Apps started from the Dock do not inherit your shell's `PATH`, so both registrations use absolute
paths. Replace `/Users/<you>/.local/bin/uv` with the output of `which uv`, and
`/ABS/PATH/krita-art-mcp` with this repository's folder.

**Codex**, in `~/.codex/config.toml`:

```toml
[mcp_servers.krita-art]
command = "/Users/<you>/.local/bin/uv"
args = ["run", "--project", "/ABS/PATH/krita-art-mcp", "krita-art-mcp", "serve"]
startup_timeout_sec = 20
tool_timeout_sec = 300
```

**Claude Code**, in a `.mcp.json`:

```json
{"mcpServers": {"krita-art": {"type": "stdio", "command": "/Users/<you>/.local/bin/uv",
  "args": ["run", "--project", "/ABS/PATH/krita-art-mcp", "krita-art-mcp", "serve"],
  "timeout": 300000}}}
```

Then ask the agent to call `krita_server_info`. It returns Krita's version and the capability
matrix, or names the setup step that is missing.

## Running it

```bash
uv run krita-art-mcp --version
```

```bash
uv run krita-art-mcp serve
```

## Development

`uv run scripts/verify.py` is the gate. It runs six named stages and prints a summary:
- `format`: ruff format check;
- `lint`: ruff;
- `types`: mypy, strict for the server and run as Python 3.10 for the plugin;
- `tests`: the server tests on Python 3.12;
- `plugin-tests`: the plugin-core tests on Python 3.10, with pytest as the only package;
- `hygiene`: keeps private details and attribution out of files and commit messages.

`uv run scripts/verify.py <stage>…` runs only the stages named.

`uv run krita-art-mcp probe` is the live harness. It checks the running plugin against this
repository, then drives a real `serve` over stdio against your running Krita. It works only in
`~/Library/Application Support/krita-art-mcp/harness/`. Its document checks run only when none
of your Krita documents has unsaved changes, and close only the documents the probe made.

## Documentation

- `CLAUDE.md`: the standing rules and commands.
- `docs/DEVELOPMENT-WORKFLOW.md`: how the work is split into sessions.
- `docs/spec/`: the round in progress: its contract (`SPEC.md`), its session plan
  (`SESSIONS.md`) and the product design draft (`PDD.md`).
- `docs/BACKLOG.md`: work named but not planned.
- `CHANGELOG.md`: what each version changed.

## Licence

GPL-3.0-or-later. See `LICENSE`.
