# Test fixtures

- **Fictional data only.** No real names, games, artwork or personal details, and nothing taken
  from the owner's projects.
- **Tests never read `docs/`.** Anything a test needs lives here or in the test itself, so no
  document or design asset becomes undeletable.
- **Harness data lives only under `<data dir>/harness/`,** which is always
  `~/Library/Application Support/krita-art-mcp/harness/`. The harness writes its own documents
  there at run time; nothing in this folder is opened in Krita.
