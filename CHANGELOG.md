# Changelog

All notable changes to krita-art-mcp are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
`major.minor.fix`.

## [Unreleased]

## [0.5.0] — 2026-10-24

Agents can now see pixels: capture any part of a document as an image, sample exact colours, and
list the brushes, blend modes, profiles and palettes Krita has.

### Added

- **`krita_capture`.** It returns a part of a document as an image, shown to the agent and saved
  as a PNG whose path comes with it.
  - It captures the composite, one paint layer's own pixels (without the layer's opacity, masks or
    inherit-alpha clip), or the selection as a grey mask.
  - At `scale: 1` it is the native crop, alpha included. Any other scale is resampled with the
    named filter onto a background: a checker by default, `transparent`, or a colour. It can also
    show values in greyscale.
  - `max_px` (1600 by default, 4096 at most) bounds the image's long edge, and one capture reads at
    most 8192 × 8192 pixels. Larger areas are captured in tiles; nothing is clamped.
  - The result gives the exact rect, the size, the filter, the colour profile, and the transform
    from document to image pixels.
  - An image too large to send whole is shown as a preview of at most 1600 px, made from the
    native pixels; the full image is at its path.
  - Captures are kept 7 days.
  - A document whose animation is showing a frame other than the first is refused, and its
    timeline is never moved; a still document reads wherever its timeline stands.
  - A capture never shows a selection mask's red overlay. For an agent's own document, its view is
    brought forward for the read and yours is put back. One of your own documents in that state
    is never changed: the read is refused until you select a layer.
- **`krita_sample`.** It reads the colour at given pixels, from the composite or one layer: RGBA
  0–255, hex, CIE L\*a\*b\* (D65) and L\*C\*h. A radius averages a disc, weighted by alpha, and
  adds the spread of its lightness and its pixel count. L\*a\*b\* is given for sRGB documents
  only.
- **`krita_resource_list`.** It lists brush presets, with each one's file name, engine and a
  fingerprint of its settings; the blend modes paint calls accept; and Krita's RGBA / 8-bit
  profiles and its palettes. Long lists come in pages.

### Changed

- **`krita_server_info`** reports `capture_source_pixels`, the largest area one capture reads.
- **`krita_operation_get`** shows the line and the image the call it follows would have shown.
- **A document's `source`** in `krita_capture`, `krita_sample` and `krita_preview_render` is
  `{document_id, frame}`; `revision` is refused until revisions exist.
- **The instructions for agents** cover capturing, sampling and the resource lists.
- **`krita-art-mcp probe`** also checks captures, samples and resource lists on documents of its
  own, and that a capture of a document behind, with a selection mask active, puts your view back.

## [0.4.0] — 2026-10-24

Agents can now open your accepted art safely: as a working copy in a folder you allow, with every
existing layer protected, and look inside it.

### Added

- **`krita-art-mcp roots add`, `list` and `remove`.** You name the folders agents may use. An
  agent can open no file, and make no working copy, outside them; a link or a `..` that leads out
  of them is refused with `PATH_NOT_ALLOWED`. The server and the plugin each check.
- **`krita_document_open`.** It opens a KRA, ORA or PNG in Krita's window.
  - `working_copy` copies the file into the `working_dir` you give, as
    `<UTC time>-<file name>`, and opens the copy; your file is never opened for writing. The
    working folder must lie inside a root, never in the source's own folder.
  - `read_only` opens the file itself, and every change to it is refused.
  - The file must match the `source_sha256` given, and so must the copy, or the open is refused
    with `SOURCE_HASH_MISMATCH`.
  - Every layer that exists at open is protected. An agent resuming its own earlier layers names
    them with `editable_layer_ids` (KRA, which keeps layer ids) or `editable_layer_names` (ORA and
    PNG, which do not). A name shared by several layers is refused.
  - Documents that are not RGBA / 8-bit are refused with `COLOR_PROFILE_MISMATCH`, and other
    formats with `UNSUPPORTED_CAPABILITY`.
  - The document as it opened is kept as a baseline for later previews, and removed when the
    document closes.
- **`krita_document_inspect`.** It reports a document's layer tree with every layer's type, order,
  visibility, opacity, blend mode, locks, inherit-alpha, offset, bounds, colour space and
  protection, plus the active layer, the selection's bounds and coverage, and the protection
  settings. It reads frame 0 only, and never changes which document or layer you are looking at.

### Changed

- **`krita_server_info`** lists the allowed roots.
- **`krita_document_close`** says whether the file a document came from is unchanged.
- **`krita-art-mcp doctor`** checks six steps; the sixth needs at least one root that is still a
  folder.
- **The instructions for agents** now cover opening with a working copy and a working folder, and
  why existing layers are protected.
- **`krita-art-mcp probe`** now also opens fictional ORA, KRA and PNG files of its own, written
  into its harness folder.

### Fixed

- **A file Krita opened but could not show is never stranded.** If giving it its view fails and
  Krita will not close it, it stays the agent's, marked unsafe, so a `discard` close ends it.
- **A source that cannot be read no longer leaks a file handle inside Krita.**
- **A full disk while pixels are handed to the server is `IO_ERROR`,** not an unexpected error.
- **The baseline is kept quickly,** so opening a large file no longer risks the client's timeout
  after the server's 45-second wait.
- **Pixels handed over but never collected are removed after an hour,** instead of waiting for
  Krita to restart.
- **`doctor`'s fix for a broken `config.json`** now says to fix or delete it, not to run
  `roots add`, which refuses to touch it.

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
- **Calls are refused at once while Krita has a dialog open or more than one window,** with
  `KRITA_MODAL_DIALOG` or `MULTIPLE_WINDOWS`. Both are retryable: close the dialog or the extra
  window, then retry.

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

[0.4.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/c081c59ff54e38b9a8799fa0a78955146745174c
[0.3.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/ef279d377f4aa515edb0ef36a69d60654f9744d1
[0.2.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/6e9237f4f728f237ec855f84855f2c6eba2d077d
[0.1.0]: https://github.com/FairCat-GD/krita-art-mcp/commit/6588c86b268e321401b27af53842d58c759f6b13
