# krita-art-mcp

An MCP server and a Krita plugin that let AI agents paint in Krita. An agent can inspect a
painting, protect accepted work, paint with Krita's own brush engine, check the result at game
size, and undo or keep it. It is for painted (non-pixel) 2D game art.

## Status

Phase 1 is being built. Version 0.1.0 is the scaffold: `krita-art-mcp serve` starts an MCP server
named `krita-art` over stdio, which reports its version and offers no tools yet. The Krita plugin,
installation and client registration arrive in the coming releases; `CHANGELOG.md` lists what each
one adds.

## Requirements

- macOS on Apple Silicon.
- Krita 5.3.x.
- [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for the server, and Python 3.10 for
  the plugin's tests.

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

## Documentation

- `CLAUDE.md`: the standing rules and commands.
- `docs/DEVELOPMENT-WORKFLOW.md`: how the work is split into sessions.
- `docs/spec/`: the round in progress: its contract (`SPEC.md`), its session plan
  (`SESSIONS.md`) and the product design draft (`PDD.md`).
- `docs/BACKLOG.md`: work named but not planned.
- `CHANGELOG.md`: what each version changed.

## Licence

GPL-3.0-or-later. See `LICENSE`.
