Read docs/spec/SPEC.md (§1 decisions 4, 5, 14–17, 19, 22–24; §3; §5; §6), docs/spec/PDD.md (Part
8), CLAUDE.md, then this file, and do Session 1 of docs/spec/SESSIONS.md: the scaffold. Session 1
has five parts:
- the uv project and the layout of SPEC §3;
- `uv run scripts/verify.py`, with six named stages, hygiene among them;
- `krita-art-mcp --version`, and `serve` with the version in `serverInfo`;
- the 19 schemas copied unamended with their example test, and the C1 error check;
- `LICENSE`, `CHANGELOG.md`, README, `tests/fixtures/`, and the Commands table in `CLAUDE.md`.

Release 0.1.0.

## State you need that is not in the specs

- **Round 1 is the Phase 1 build.** Session 0, the intake, is done. Sessions 1–15 remain, and
  6, 10 and 13 are architecture reviews.
- **There is no remote, and nothing has been pushed** (decision 17). The intake commit,
  `docs: open round 1 — krita-art-mcp`, is local only.
- **What exists is documents only:**
  - `docs/spec/`: `SPEC.md`, `SESSIONS.md`, and `PDD.md` (scrubbed);
  - `docs/spec/reference/contract-package/` (scrubbed; its historical fixtures and checksum file
    were left out);
  - `CLAUDE.md`, `docs/BACKLOG.md`, `docs/DEVELOPMENT-WORKFLOW.md` and `.gitignore`.

  There is no `pyproject.toml` and no code.
- **What the spec said that turned out wrong or harder:** nothing yet. One thing is uncertain: the
  package's examples have passed only the package's own subset checker, never a full Draft
  2020-12 validator.
- **Decisions written down nowhere else:**
  - **The hygiene term hashes.** Each is the SHA-256 of a lowercase term's UTF-8 bytes. They go
    into one data file under `scripts/`. The terms themselves are never written into the
    repository.
    ```
    7879acd0c06ad5508da8bd92f64eae02ea49d8681bc7ba9d6b7692a2cffed4b4
    3d63a063d40fd1c12ed33a4646c93a46a92b63b2514d7d048cf567fe193e465f
    bbeecfb575fb00c6cd1c207fef73046db883ecdfcee36977c67dccf040a53284
    36d0d93528bc79cd69ea96893aea78115ab4bc5cc56216bc58aaaf82b70333fc
    dbf2a89b11004ff7f063b1f68bb09bee706f08b25591048d0f7eda30ad0366f5
    693b286515bd1dd00865e7b60e4e53556537bbe4b1cc90ab608d94eb7c56fdc6
    ef7f91a0a1a9ca33056b5c2599d1fcf280ea84cf8cded8f28583b555e5ed786b
    ```
  - **To falsify the hygiene stage,** add a throwaway word and its hash, watch the stage fail, then
    remove both.
  - **`gh` is authenticated** for the owner's GitHub account. Create no repository until the owner
    asks.
  - **Krita on this Mac.**
    - Krita 5.3.4 is at `/Applications/krita.app`, with Python 3.13 and PyQt5 5.15.11 bundled.
    - `~/Library/Application Support/Krita/pykrita/` exists and is empty.
    - `~/Library/Preferences/kritarc` has no `[python]` section.
    - Session 1 needs no Krita.
- **Baseline:** none yet. Session 1 records the first counts in its done-note: tests passed and
  skipped, and verify stages.
- **Not done:** nothing.

## Watch for

- **The standing traps:**
  - **Never `git checkout <path>`.** Falsify by copying the file aside and back.
  - **Stage explicit paths.**
  - **Give stdin-reading commands `< /dev/null`.** A bare `cat > file` with no heredoc hangs.
  - **The Python toolchain.**
    - uv is at `~/.local/bin/uv` (0.12.3), and CPython 3.12.13 is uv-managed.
    - uv fetches CPython 3.10 on first use.
    - `/usr/bin/python3` is 3.9.6: never use it.
  - **`docs/spec/reference/` holds Python scripts and JSON.** Keep `docs/` out of ruff, mypy and
    pytest collection.
  - **The owner's Krita is live, with their documents open.** No session touches them, and none
    restarts Krita while a document has unsaved changes.
  - **Nothing private in any file or commit message** (`CLAUDE.md`, *This repository is public*).
- **Session 1's own traps** are in its block:
  - full Draft 2020-12 validation may reject examples: fix the example, never the schema;
  - the hygiene stage must not flag its own source;
  - `mcp` 2.3's `MCPServer` rename;
  - no dependency before it is used.
- **Comments state the present, briefly.** No session ids, no "used to", no review stories, no
  paragraphs.
- **Every push needs its own approval.** There is no remote yet.
