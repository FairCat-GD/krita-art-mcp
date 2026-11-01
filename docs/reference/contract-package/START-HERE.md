# START HERE · Krita MCP for 2D game art

Build a reusable local Krita MCP server and companion Krita plugin from this package. It must support our current and future 2D games. The first game is one example, not a set of hard-coded rules.

**Pixel-art authoring stays in Aseprite.** Build Krita support for painted and other non-pixel-art 2D work, including painted animation. Aseprite exports may be reference/composition inputs; do not recreate its pixel-art editing workflow.

The central workflow is **inspect → protect → paint precisely → inspect at game size → undo or commit → save/export and verify**. Preserve accepted artwork and make every mutation observable, bounded and recoverable.

**Read in this order** (paths below are relative to the extracted ZIP's root):

1. `krita-mcp-art-workflow-brief.md` — art requirements, preservation rules and reusable project profiles.
2. `krita-mcp-contract/README.md` — build order, shared types, coordinates, transactions, revisions, retries, failures and acceptance tests.
3. `krita-mcp-contract/mvp.tools.json` — 27 MVP tool definitions with input/output JSON Schemas.
4. `krita-mcp-contract/paint-workflow.example.json` and `errors.example.json` — complete calls/results and failure examples.
5. `krita-mcp-contract/TOOL-CATALOGUE.md` — examples for all 69 proposed tools. `tools.json` is the machine-readable catalogue.

**Build the core in three phases.**

- **MVP-A:** discover capabilities; open/create working documents; inspect actual layers/resources; return accurate crops and pixel samples.
- **MVP-B:** create editable layers and selections; checkpoint/protect accepted content; paint native brush strokes; verify commit and rollback.
- **MVP-C:** expose operation status/cancellation and history; register exports; produce game-size previews; save/reopen layered sources; export and validate. Cancellation/recovery infrastructure starts in phase A, even if its public tools arrive later.

First inspect the actual installed Krita version and bindings. Produce a capability matrix, then demonstrate protected paint corrections on a sprite and a high-resolution UI asset. Verify pressure, selection enforcement, projection completion, undo/recovery and save fidelity. Report unsupported capabilities rather than silently falling back to different painting behavior.

Use the two demo project profiles to prove that units, scales, palettes, filtering, paths and approval rules do not leak between projects. Preserve the typed interfaces and workflow guarantees; document any necessary API changes with matching schemas, examples and tests. The 42 extension tools are a roadmap for animation, tiles, backgrounds, UI, vectors, atlases, engine adapters and recovery. Their schemas are provisional example shapes; finish their contracts before exposing them.

**What this package is—and what is still to build.**

It contains a specification, schemas, example data and offline checking scripts. It does **not** contain a working MCP server, a Krita plugin, real resource IDs or runnable game assets. Sample paths, hashes, IDs and successful receipts are fictional.

`validation-report.json` records the latest offline consistency checks on the specification package. These do not establish brush fidelity, native transactions, full JSON Schema conformance, runtime integration or art acceptance. Use a complete Draft 2020-12 validator in the implementation, and add real Krita integration tests.

From the extracted root, Python 3 with the standard library is sufficient to regenerate and check the proposal:

```sh
python3 krita-mcp-contract/build_contract.py
python3 krita-mcp-contract/check_examples.py
```

`build_contract.py` regenerates tool schemas, catalogues, profiles and examples. Edit it when changing those generated files. The brief and contract README are maintained separately. Running generation/checks may update packaged files.

**Expected first delivery:** capability matrix, runnable local server/plugin, installation and connection instructions, the complete MVP loop demonstrated on world-unit painted-sprite and high-resolution UI fixtures, and integration-test results with unresolved limitations stated plainly. Keep accepted-source preservation, technical validation, owner art approval and runtime/device checks separate.
