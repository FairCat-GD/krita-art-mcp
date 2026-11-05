# krita-art-mcp

A Krita MCP server: an MCP server and a Krita plugin that let AI agents paint in Krita. An agent can
inspect a painting, protect accepted work, paint with Krita's own brush engine, check the result at
game size, and undo or keep it. It is for painted (non-pixel) 2D game art.

## What it does

Phase 1 is complete, and round 2 has reached 0.22.0, with 20 tools.

- **Works on a copy.** A document opens as a working copy with every existing layer protected, and
  the source is never written.
- **Paints with Krita's brushes.** One stroke per call, one undo step, with a preset you already have.
  There is no tool that writes raw pixels or runs code.
- **Checks every stroke.** Each change is compared with what protection allows, inside the same job,
  and undone if it leaks.
- **Shows the result at game size.** Comparison sheets put the document as opened beside its current
  state, at the asset's own sizes and over review backgrounds.
- **Saves without overwriting.** A save goes to a new KRA or ORA, and counts only once the file,
  reopened in Krita, matches the document.
- **Is safe to retry.** Every change is journaled before it is sent, and a retried `request_id` never
  runs twice.

It does not judge whether strokes look painted. That stays with you.

## Requirements

- macOS. It is tested on Apple Silicon with Krita 5.3.4.
- Krita 5.3.x, with its interface in English, because undo and rollback confirm each step by its
  English name, and with cumulative undo off.
- [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for the server, and Python 3.10 for the
  plugin's tests.

## Quick start

Copy the plugin into Krita:

```bash
uv run krita-art-mcp install-plugin
```

Restart Krita, enable *Krita Art MCP Bridge* in *Configure Krita › Python Plugin Manager*, and restart
it again. Then allow a folder agents may use, and check the setup:

```bash
uv run krita-art-mcp roots add /path/to/your/art
```

```bash
uv run krita-art-mcp doctor
```

Register the server with your MCP client, then ask the agent to call `krita_server_info`.
[The user guide](docs/USER-GUIDE.md) has the registration for Codex and Claude Code, what to do when a
client cannot read the repository, and how to update.

## Documentation

- [`docs/USER-GUIDE.md`](docs/USER-GUIDE.md): setup, the core loop call by call, every error code and
  what to do, Phase 1's limits, and what it leaves on your computer.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): the system as built, its invariants, and the
  baseline counts.
- [`docs/BACKLOG.md`](docs/BACKLOG.md): what has been named but not planned, the later phases among
  it.
- [`docs/reference/contract-package/`](docs/reference/contract-package/): the frozen draft contract
  for all 69 planned tools, where later phases start.
- [`CHANGELOG.md`](CHANGELOG.md): what each version changed.
- [`docs/DEVELOPMENT-WORKFLOW.md`](docs/DEVELOPMENT-WORKFLOW.md) and [`CLAUDE.md`](CLAUDE.md): how the
  work is split into sessions, and the standing rules.

## Development

`uv run scripts/verify.py` is the gate. It runs six named stages and prints a summary:
- `format`: ruff format check;
- `lint`: ruff;
- `types`: mypy, strict for the server and run as Python 3.10 for the plugin;
- `tests`: the server tests on Python 3.12;
- `plugin-tests`: the plugin-core tests on Python 3.10, with pytest as the only package;
- `hygiene`: keeps private words and AI attribution out of files and commit messages.

On a fresh clone `hygiene` fails until its word list exists, so make it first. It lives outside the
repository, one word per line, and an empty file is valid:

```bash
mkdir -p ~/.config/hygiene && touch ~/.config/hygiene/terms.txt
```

`uv run scripts/verify.py <stage>…` runs only the stages named. `--message <file>` gives `hygiene` a
drafted commit message to check before the commit is made.

`uv run krita-art-mcp probe` is the live harness. It checks the running plugin against this repository,
then drives a real `serve` over stdio against your running Krita. It works only in
`~/Library/Application Support/krita-art-mcp/harness/`, where it writes its own fictional ORA, KRA and
PNG files, and it never changes your roots. Its document checks run only when none of your Krita
documents has unsaved changes, and close only the documents the probe made. They include the
contract's six acceptance exercises and a check that a run leaves nothing outside that data folder and
Krita's own files. Leave Krita alone while it runs: a dialog open in Krita refuses calls that read or
change a document until it closes, and fails the checks it overlaps. It needs the stock presets
`b) Basic-2 Opacity`, `b) Airbrush Soft`, `y) Texture Spray` and `y) Texture Wood Fiber`. The probe ends
with its PASS, FAIL and MEASURED counts and how long it ran.

## Licence and support

Copyright (C) 2026 Svyat Marutyak. GPL-3.0-or-later; see `LICENSE`.

One developer builds this, for painted game art on macOS, so no support is promised. Issues are
welcome. Report a security problem through GitHub's private vulnerability reporting, on the
repository's Security tab, rather than in a public issue.
