# Krita MCP proposed tool catalogue

API proposal 0.1.0. These tools and receipts are examples, not implemented or observed Krita behavior. Fictional IDs, hashes, paths and resource URIs must be replaced by real values. See [the contract](README.md) for semantics and build order.

Inputs below are complete per-tool examples. Outputs show the `data` field of the common result envelope; complete examples and schemas are in [tools.json](tools.json). Extension schemas are draft example shapes, not final implementation contracts.

**krita_server_info · MVP-A**

Discover tested capabilities, limits and session identity.

Input:
```json
{}
```

Output data:
```json
{
  "session_id": "session-1",
  "krita_version": "detected-at-runtime",
  "plugin_version": "0.1.0",
  "profile_schema_version": "0.1.0",
  "capabilities": {
    "brush_strokes": true,
    "pressure": true,
    "tilt": false,
    "native_animation": false,
    "verified_rollback": true
  },
  "limits": {
    "stroke_points": 4096,
    "capture_pixels": 16777216,
    "edit_timeout_seconds": 120
  },
  "unsupported": [
    "native_animation",
    "tilt"
  ]
}
```

Example flags are fictional. Probe actual bindings and behavior; unsupported modules must not advertise successful tools.

**krita_project_load · MVP-A**

Validate and bind an immutable project profile.

Input:
```json
{
  "profile_path": "/projects/demo/art-profile.json",
  "expected_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "request_id": "req-profile"
}
```

Output data:
```json
{
  "project_id": "project-1",
  "profile_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "profile_version": 1,
  "effective_profile_uri": "krita-artifact://example/profile.json",
  "validator_ids": [
    "alpha-bounds",
    "source-geometry"
  ]
}
```

Resolve profile paths under configured local roots. No network downloads or arbitrary validator commands. Existing documents keep their original profile binding.

**krita_document_list · MVP-A**

List accessible documents without switching the active document.

Input:
```json
{}
```

Output data:
```json
{
  "documents": [
    {
      "document_id": "doc-1",
      "name": "hero-working.kra",
      "revision": 12,
      "dirty": true,
      "project_id": "project-1"
    }
  ]
}
```



**krita_document_open · MVP-A**

Open a baseline and return an isolated working copy.

Input:
```json
{
  "project_id": "project-1",
  "source_path": "/projects/demo/accepted/hero.kra",
  "source_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "mode": "working_copy",
  "request_id": "req-open"
}
```

Output data:
```json
{
  "working_copy": true,
  "baseline_id": "baseline-1",
  "source_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "canvas_px": [
    128,
    128
  ],
  "root_layer_id": "root-1"
}
```

Opening cannot overwrite the source. Returned document ID/revision bind all later requests. Duplicate request IDs return the same handle.

**krita_document_create · MVP-A**

Create new artwork with explicit canvas and colour settings.

Input:
```json
{
  "project_id": "project-1",
  "name": "new-icon",
  "size_px": [
    32,
    32
  ],
  "color_model": "RGBA",
  "depth": "U8",
  "profile_id": "srgb-profile-1",
  "background": "transparent",
  "request_id": "req-new"
}
```

Output data:
```json
{
  "canvas_px": [
    32,
    32
  ],
  "root_layer_id": "root-2",
  "initial_layer_id": "paint-1",
  "profile_id": "srgb-profile-1"
}
```

Reject unsupported colour depths/profile combinations. Do not inherit incidental foreground/background settings.

**krita_document_inspect · MVP-A**

Read document state, frame, layer tree, profile and protection policy.

Input:
```json
{
  "document_id": "doc-1"
}
```

Output data:
```json
{
  "canvas_px": [
    128,
    128
  ],
  "frame": 0,
  "profile_id": "srgb-profile-1",
  "project_id": "project-1",
  "dirty": true,
  "layers": [
    {
      "id": "base-1",
      "parent_id": "root-1",
      "name": "Accepted base",
      "type": "paint",
      "visible": true,
      "opacity": 1.0,
      "blend_mode": "normal",
      "locked": true,
      "alpha_locked": false,
      "offset_px": [
        0,
        0
      ]
    }
  ],
  "protection_id": "protect-1",
  "active_edit_id": null
}
```

Layer IDs are session/document scoped; return remappings after reopen. Server identity must never depend on layer names.

**krita_document_close · MVP-C**

Close a clean or explicitly checkpointed working document.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "dirty_policy": "refuse",
  "checkpoint_id": null
}
```

Output data:
```json
{
  "closed": true,
  "baseline_untouched": true
}
```

Refuse dirty documents by default. Discard requires a verified recoverable checkpoint. No close during an active edit.

**krita_resource_list · MVP-A**

Discover available brushes, profiles, palettes and blend modes.

Input:
```json
{
  "kind": "brush",
  "cursor": null,
  "limit": 20
}
```

Output data:
```json
{
  "resources": [
    {
      "id": "brush-ink-1",
      "name": "Ink",
      "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      "supported_settings": [
        "size_px",
        "opacity",
        "flow",
        "color",
        "pressure",
        "eraser",
        "smoothing",
        "antialias"
      ]
    }
  ],
  "next_cursor": null
}
```

Enumerate actual resources and hashes, not guessed preset names. Capabilities may differ per preset.

**krita_layer_create · MVP-B**

Create an editable paint/group/mask node at an explicit stack position.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "parent_id": "root-1",
  "above_id": "base-1",
  "type": "paint",
  "name": "Accessory repair"
}
```

Output data:
```json
{
  "layer_id": "repair-1",
  "parent_id": "root-1",
  "above_id": "base-1",
  "type": "paint"
}
```

Masks attach only to compatible nodes. Protected parent topology may forbid insertion. Native undo and server revision must record this change.

**krita_layer_update · MVP-B**

Set explicit layer properties without changing protected state.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "layer_id": "repair-1",
  "properties": {
    "alpha_locked": true
  }
}
```

Output data:
```json
{
  "layer_id": "repair-1",
  "effective_properties": {
    "alpha_locked": true
  }
}
```

Require at least one property. Validate advertised blend modes. Layer locks are not permission to weaken server protection; protected layers cannot be unlocked by this tool.

**krita_selection_set · MVP-B**

Create or combine an explicit document-space selection.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "combine": "replace",
  "shape": {
    "type": "rect",
    "rect": {
      "x": 16,
      "y": 16,
      "width": 32,
      "height": 32
    }
  },
  "feather_px": 0,
  "invert": false
}
```

Output data:
```json
{
  "selection_id": "selection-1",
  "mask": {
    "uri": "krita-artifact://example/selection.png",
    "mime_type": "image/png",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "bounds_px": {
    "x": 16,
    "y": 16,
    "width": 32,
    "height": 32
  },
  "selected_pixels": 1024
}
```

Mask is full-canvas linear 8-bit coverage, not colour-managed luminance. Feathering changes selection weights, never expands the separately enforced hard allowed-change mask.

**krita_capture · MVP-A**

Return a fresh lossless crop of a layer, composite or selection.

Input:
```json
{
  "source": {
    "document_id": "doc-1",
    "revision": 12,
    "frame": 0
  },
  "target": "composite",
  "layer_id": null,
  "rect": {
    "x": 16,
    "y": 16,
    "width": 32,
    "height": 32
  },
  "scale": 1,
  "filter": "nearest"
}
```

Output data:
```json
{
  "image": {
    "uri": "krita-artifact://example/preview.png",
    "mime_type": "image/png",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "output_size_px": [
    32,
    32
  ],
  "source_rect": {
    "x": 16,
    "y": 16,
    "width": 32,
    "height": 32
  },
  "source_to_image": [
    1,
    0,
    -16,
    0,
    1,
    -16
  ],
  "profile_id": "srgb-profile-1",
  "fresh": true
}
```

Require layer_id only for target=layer. Include native image content or readable resource; metadata alone is insufficient. Read revision mismatch returns STALE_REVISION, not a newer unlabelled capture.

**krita_sample · MVP-A**

Sample known pixel locations with explicit layer/composite scope.

Input:
```json
{
  "source": {
    "document_id": "doc-1",
    "revision": 12,
    "frame": 0
  },
  "target": "composite",
  "layer_id": null,
  "points": [
    [
      20,
      20
    ]
  ]
}
```

Output data:
```json
{
  "samples": [
    {
      "point_px": [
        20,
        20
      ],
      "srgb_rgba": [
        0.5,
        0.3,
        0.2,
        1.0
      ],
      "native_channels": [
        128,
        77,
        51,
        255
      ]
    }
  ],
  "native_profile_id": "srgb-profile-1",
  "native_channel_order": "RGBA"
}
```

Points address pixel cells; sample centers are (x+0.5,y+0.5). Expose actual native order/depth, never assume all Krita pixel buffers are RGBA.

**krita_checkpoint_create · MVP-B**

Snapshot content, metadata and recoverable native state.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "label": "Before accessory repair"
}
```

Output data:
```json
{
  "checkpoint_id": "cp-1",
  "content_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "recoverable": true,
  "storage_uri": "krita-checkpoint://session-1/cp-1"
}
```

Checkpoint creation does not change art/revision. Persist before claiming recoverable; report quota failure. Include layer tree, masks, frames, profile, selection and sidecars.

**krita_protection_set · MVP-B**

Bind or tighten preservation policy against a checkpoint.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "checkpoint_id": "cp-1",
  "protected_layer_ids": [
    "base-1"
  ],
  "allowed_change_mask": {
    "uri": "krita-artifact://example/allowed.png",
    "sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
  },
  "preserve_composite_alpha": true,
  "preserve_canvas": true
}
```

Output data:
```json
{
  "protection_id": "protect-1",
  "protected_layer_ids": [
    "base-1"
  ],
  "composite_outside_mask": "exact",
  "preserve_composite_alpha": true
}
```

Only initialize or tighten in MVP. Weakening requires a new explicitly authorized project policy/working copy. Protect appearance-affecting properties and ancestor operations as well as native pixels.

**krita_edit_begin · MVP-B**

Begin one bounded, guarded paint transaction.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "protection_id": "protect-1",
  "target_layer_id": "repair-1",
  "frame": 0,
  "selection_id": "selection-1",
  "label": "Repair one material edge"
}
```

Output data:
```json
{
  "edit_id": "edit-1",
  "checkpoint_id": "cp-edit-1",
  "target_layer_id": "repair-1",
  "frame": 0,
  "state": "open"
}
```

One active edit per document. Capture rollback state before writing. Pin selection/brush context; never depend on the current UI layer. Only the allowed target/frame may change.

**krita_paint_stroke · MVP-B**

Paint one native brush stroke on the transaction target.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "edit_id": "edit-1",
  "brush": {
    "preset_id": "brush-ink-1",
    "preset_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "size_px": 2,
    "opacity": 1,
    "flow": 1,
    "color": {
      "space": "srgb",
      "rgba": [
        0.4,
        0.3,
        0.3,
        1
      ]
    },
    "eraser": false,
    "smoothing": "none",
    "antialias": true
  },
  "points": [
    {
      "x": 22.5,
      "y": 24.5,
      "pressure": 0.4,
      "time_ms": 0
    },
    {
      "x": 27.5,
      "y": 26.5,
      "pressure": 0.7,
      "time_ms": 30
    }
  ]
}
```

Output data:
```json
{
  "stroke_id": "stroke-1",
  "accepted_points": 2,
  "changed_bounds_px": {
    "x": 21,
    "y": 23,
    "width": 9,
    "height": 5
  },
  "protected_pixels_changed": 0,
  "preview": {
    "uri": "krita-artifact://example/stroke.png",
    "mime_type": "image/png",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "effective_brush": {
    "preset_id": "brush-ink-1",
    "preset_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "size_px": 2,
    "opacity": 1,
    "flow": 1,
    "color": {
      "space": "srgb",
      "rgba": [
        0.4,
        0.3,
        0.3,
        1
      ]
    },
    "eraser": false,
    "smoothing": "none",
    "antialias": true
  }
}
```

Require nondecreasing time. Unsupported settings fail preflight; never silently ignore tilt/flow/AA. Brush preset is immutable for the stroke. Repeated request_id cannot paint twice. Commit still checks the whole transaction.

**krita_edit_commit · MVP-B**

Verify and commit a paint batch or roll it back on invariant failure.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "edit_id": "edit-1"
}
```

Output data:
```json
{
  "committed": true,
  "checkpoint_id": "cp-edit-1",
  "changed_pixels": 27,
  "protected_pixels_changed": 0,
  "alpha_changed_pixels": 0,
  "diff": {
    "uri": "krita-artifact://example/diff.png",
    "mime_type": "image/png",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  }
}
```

Barrier for native paint/projection completion, then exact protected-content checks. No success until verified. A failed invariant is isError=true with rollback evidence, never a successful receipt.

**krita_edit_rollback · MVP-B**

Restore the transaction baseline and verify the restoration.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "edit_id": "edit-1"
}
```

Output data:
```json
{
  "rolled_back": true,
  "restored_checkpoint_id": "cp-edit-1",
  "restored_content_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "verified": true
}
```

Restoring old content increments revision; revisions never go backwards. If a human edited concurrently, preserve both states and return EXTERNAL_EDIT_CONFLICT instead of erasing human work.

**krita_history_step · MVP-C**

Undo or redo committed edits, or restore a named checkpoint.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "action": "undo",
  "steps": 1,
  "checkpoint_id": null
}
```

Output data:
```json
{
  "action": "undo",
  "steps_applied": 1,
  "verified": true,
  "content_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
}
```

No active transaction. checkpoint_id is required only for restore_checkpoint, which requires steps=1. Restore art/history without weakening protection policy or decrementing revision.

**krita_operation_get · MVP-C**

Read the status of a long-running operation.

Input:
```json
{
  "operation_id": "op-export-1"
}
```

Output data:
```json
{
  "operation_id": "op-export-1",
  "state": "completed",
  "progress": 1.0,
  "result_uri": "krita-artifact://example/export-receipt.json",
  "rollback_state": "not_needed"
}
```

The tool result completed means the status query completed; data.state is the operation state. Receipts are retained for a declared duration. Progress may be null/unknown in the implementation schema.

**krita_operation_cancel · MVP-C**

Request cancellation and report verified final state.

Input:
```json
{
  "operation_id": "op-paint-1",
  "request_id": "req-cancel"
}
```

Output data:
```json
{
  "operation_id": "op-paint-1",
  "state": "cancelled",
  "rollback_state": "verified",
  "checkpoint_id": "cp-edit-1"
}
```

If cancellation is pending, return queued/running instead of this completed example. Do not claim cancellation until writes stop and restoration is checked. Export cancellation deletes only its incomplete temporary output.

**krita_registration_set · MVP-C**

Set export registration metadata without changing source pixels.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "asset_id": "hero",
  "source_rect": {
    "x": 0,
    "y": 0,
    "width": 128,
    "height": 128
  },
  "uniform_scale": 0.5,
  "translation_px": [
    4,
    4
  ],
  "output_size_px": [
    72,
    72
  ],
  "anchor_px": [
    36,
    68
  ],
  "filter": "lanczos"
}
```

Output data:
```json
{
  "registration_id": "reg-1",
  "source_to_export": [
    0.5,
    0,
    4,
    0,
    0.5,
    4
  ],
  "output_size_px": [
    72,
    72
  ],
  "anchor_px": [
    36,
    68
  ],
  "source_pixels_changed": 0
}
```

Mapping: export=(document-source_rect.origin)*scale+translation. Crop/clip and padding are explicit; reject inadvertent nontransparent clipping. Animation/frame references remain separately bound.

**krita_preview_render · MVP-C**

Render a project-defined game-size or comparison/composition recipe.

Input:
```json
{
  "project_id": "project-1",
  "recipe_id": "native-and-game-size",
  "sources": [
    {
      "asset_id": "hero",
      "source": {
        "document_id": "doc-1",
        "revision": 12,
        "frame": 0
      },
      "registration_id": "reg-1"
    }
  ],
  "baseline_id": "baseline-1",
  "overlays": [
    "anchor"
  ]
}
```

Output data:
```json
{
  "images": [
    {
      "artifact": {
        "uri": "krita-artifact://example/game-size.png",
        "mime_type": "image/png",
        "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "size_bytes": 4096
      },
      "size_px": [
        36,
        36
      ],
      "target_pixels_per_unit": 2,
      "export_pixels_per_unit": 4,
      "filter": "lanczos"
    }
  ],
  "recipe_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "static_only": true,
  "source_pixels_changed": 0,
  "clean_images": [
    {
      "uri": "krita-artifact://example/game-size-clean.png",
      "mime_type": "image/png",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "size_bytes": 4096
    }
  ]
}
```

Recipe is validated project data, not code. Include actual per-axis mapping after rounding, fixed reference hashes, display-pixel assumptions and profile. Return unoverlaid render alongside overlays. UI recipes can use fixed pixel sizes instead of world units.

**krita_document_save · MVP-C**

Save a new layered revision and verify it by reopening a copy.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "path": "/projects/demo/revisions/hero-r02.kra",
  "overwrite": false,
  "verify_reopen": true
}
```

Output data:
```json
{
  "path": "/projects/demo/revisions/hero-r02.kra",
  "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "reopened_verified": true,
  "layers_preserved": true,
  "baseline_untouched": true
}
```

Atomic write to a new path. Refuse active/uncommitted edits. Verification must include layer tree, masks, frames, profiles and pixels; reopening verification must not replace the live document.

**krita_asset_export · MVP-C**

Export a registered transparent PNG and metadata from a pinned revision.

Input:
```json
{
  "source": {
    "document_id": "doc-1",
    "revision": 12,
    "frame": 0
  },
  "registration_id": "reg-1",
  "output_path": "/projects/demo/exports/hero.png",
  "profile_id": "srgb-profile-1",
  "alpha_mode": "straight",
  "overwrite": false,
  "request_id": "req-export"
}
```

Output data:
```json
{
  "path": "/projects/demo/exports/hero.png",
  "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "size_px": [
    72,
    72
  ],
  "alpha_mode": "straight",
  "metadata": {
    "uri": "krita-artifact://example/hero.json",
    "mime_type": "application/json",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "source_unchanged": true
}
```

PNG MVP must support straight alpha; reject premultiplied requests until a tested project adapter explicitly supports and labels that convention. Never flatten the live source. Fail on profile mismatch/clipping; never auto-fix art.

**krita_validation_run · MVP-C**

Run registered validators against immutable revision/export snapshots.

Input:
```json
{
  "project_id": "project-1",
  "validator_ids": [
    "alpha-bounds",
    "source-geometry"
  ],
  "artifact_uri": "krita-artifact://example/hero.json",
  "artifact_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
```

Output data:
```json
{
  "checks": [
    {
      "id": "alpha-bounds",
      "status": "pass"
    },
    {
      "id": "source-geometry",
      "status": "pass"
    }
  ],
  "report": {
    "uri": "krita-artifact://example/validation.json",
    "mime_type": "application/json",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "art_approval": "unreviewed",
  "runtime_validation": "not_run"
}
```

Validation failure is data in checks, not a server execution failure. Execution errors use isError. Validators are separately registered local adapters, not arbitrary shell commands supplied by a tool caller.

**krita_document_duplicate · EXTENSION**

Fork a working branch including project metadata.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "name": "hero-option-b"
}
```

Output data:
```json
{
  "new_document_id": "doc-2",
  "new_revision": 1,
  "baseline_id": "baseline-1",
  "source_unchanged": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_layer_duplicate · EXTENSION**

Duplicate selected editable nodes and return ID mapping.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "layer_ids": [
    "repair-1"
  ],
  "destination_parent_id": "root-1"
}
```

Output data:
```json
{
  "id_map": {
    "repair-1": "repair-2"
  }
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_layer_reorder · EXTENSION**

Move editable nodes without changing their pixel data.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "layer_id": "repair-1",
  "parent_id": "root-1",
  "above_id": "base-1"
}
```

Output data:
```json
{
  "effective_order": [
    "base-1",
    "repair-1"
  ]
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Verify protected composite after reordering.

**krita_layer_remove · EXTENSION**

Remove editable nodes through a verified checkpoint.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "layer_ids": [
    "unused-1"
  ],
  "checkpoint_id": "cp-1"
}
```

Output data:
```json
{
  "removed": [
    "unused-1"
  ],
  "protected_nodes_unchanged": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_layer_import · EXTENSION**

Import local raster/vector content as a new explicitly positioned layer.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "path": "/projects/demo/parts/hat.png",
  "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "origin_px": [
    0,
    0
  ],
  "as_type": "paint"
}
```

Output data:
```json
{
  "layer_id": "hat-1",
  "source_size_px": [
    32,
    32
  ],
  "rasterized": false
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Report any conversion; preserve SVG source when rasterization is authorized.

**krita_mask_edit · EXTENSION**

Create or edit a mask with explicit selection/brush semantics.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "edit_id": "edit-1",
  "mask_layer_id": "mask-1",
  "operation": "fill_selection",
  "coverage": 128
}
```

Output data:
```json
{
  "mask_layer_id": "mask-1",
  "changed_pixels": 120,
  "protected_pixels_changed": 0
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_selection_query · EXTENSION**

Read a selection mask, bounds and coverage histogram.

Input:
```json
{
  "source": {
    "document_id": "doc-1",
    "revision": 12,
    "frame": 0
  }
}
```

Output data:
```json
{
  "selection_id": "selection-1",
  "mask": {
    "uri": "krita-artifact://example/selection.png",
    "mime_type": "image/png",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "nonzero_pixels": 1024
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_selection_clear · EXTENSION**

Clear or select the full canvas explicitly.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "mode": "clear"
}
```

Output data:
```json
{
  "selection_active": false
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_selection_from_alpha · EXTENSION**

Derive a selection from a known layer alpha.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "layer_id": "repair-1",
  "threshold": 128,
  "combine": "replace"
}
```

Output data:
```json
{
  "selection_id": "selection-alpha",
  "selected_pixels": 200
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Never confuse selection-generation with changing the painted contour.

**krita_paint_path · EXTENSION**

Paint a controlled Bezier path with the native brush.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "edit_id": "edit-1",
  "brush_id": "brush-ink-1",
  "path": [
    {
      "command": "move",
      "point": [
        10,
        10
      ]
    },
    {
      "command": "cubic",
      "control1": [
        15,
        10
      ],
      "control2": [
        20,
        20
      ],
      "point": [
        25,
        20
      ]
    }
  ]
}
```

Output data:
```json
{
  "changed_pixels": 37,
  "preview": {
    "uri": "krita-artifact://example/path.png",
    "mime_type": "image/png",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  }
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Include full immutable brush settings in the finalized schema, as in paint_stroke.

**krita_paint_fill · EXTENSION**

Fill a bounded selection or contiguous region.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "edit_id": "edit-1",
  "mode": "selection",
  "color": {
    "space": "srgb",
    "rgba": [
      0.4,
      0.3,
      0.2,
      1
    ]
  },
  "respect_alpha_lock": true
}
```

Output data:
```json
{
  "filled_pixels": 200,
  "outside_allowed_mask_changed": 0
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Contiguous fill needs explicit tolerance, reference scope, expansion and feather parameters.

**krita_paint_clone · EXTENSION**

Clone from an explicit immutable source with bounded brush input.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "edit_id": "edit-1",
  "source": {
    "document_id": "doc-1",
    "revision": 12,
    "frame": 0
  },
  "source_layer_id": "base-1",
  "source_offset_px": [
    -12,
    0
  ],
  "points": [
    {
      "x": 30.5,
      "y": 20.5,
      "pressure": 0.5,
      "time_ms": 0
    }
  ]
}
```

Output data:
```json
{
  "changed_pixels": 15,
  "source_unchanged": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Finalize brush settings and source snapshot behavior; no active-tool state dependence.

**krita_paint_shape · EXTENSION**

Draw a deliberate shape as paint or editable vector content.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "edit_id": "edit-1",
  "shape": "ellipse",
  "rect": {
    "x": 16,
    "y": 16,
    "width": 32,
    "height": 32
  },
  "stroke_width_px": 1,
  "fill": "none",
  "output": "vector"
}
```

Output data:
```json
{
  "layer_id": "shape-1",
  "editable": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Explicit construction tool, never automatic replacement of an accepted silhouette.

**krita_transform_apply · EXTENSION**

Apply a requested transform to an editable target or transform mask.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "layer_id": "repair-1",
  "matrix": [
    1,
    0,
    2,
    0,
    1,
    0
  ],
  "filter": "nearest",
  "mode": "transform_mask"
}
```

Output data:
```json
{
  "transform_mask_id": "transform-1",
  "source_pixels_unchanged": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Handle rotation, mirror, perspective and warp as declared capabilities; disclose rasterization and clipping.

**krita_canvas_resize · EXTENSION**

Change working canvas bounds without silently scaling paint.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "new_size_px": [
    160,
    160
  ],
  "content_offset_px": [
    16,
    16
  ],
  "clip_policy": "reject_nontransparent"
}
```

Output data:
```json
{
  "size_px": [
    160,
    160
  ],
  "anchor_delta_px": [
    16,
    16
  ]
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Requires project policy permitting canvas changes; update offsets and sidecars together.

**krita_filter_apply · EXTENSION**

Apply an explicitly requested bounded adjustment or filter.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "layer_id": "repair-1",
  "filter_id": "gaussian-blur",
  "parameters": {
    "radius_px": 1
  },
  "mode": "filter_mask",
  "selection_id": "selection-1"
}
```

Output data:
```json
{
  "filter_mask_id": "filter-1",
  "outside_allowed_mask_changed": 0
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Discover supported parameter schemas. Exact preservation after projection, including filter halo. No automatic cleanup.

**krita_palette_manage · EXTENSION**

Read or create a versioned project palette.

Input:
```json
{
  "project_id": "project-1",
  "operation": "create",
  "name": "eight-colour",
  "colors": [
    "#102030",
    "#80A060"
  ],
  "request_id": "req-palette"
}
```

Output data:
```json
{
  "palette_id": "palette-2",
  "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "entries": 2
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Changing a palette does not recolour existing pixels. Colour conversion is a separate explicit operation.

**krita_color_convert · EXTENSION**

Explicitly convert an authorized working copy to a target colour profile.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "target_profile_id": "srgb-profile-1",
  "intent": "relative_colorimetric",
  "black_point_compensation": true,
  "checkpoint_id": "cp-1"
}
```

Output data:
```json
{
  "converted": true,
  "profile_id": "srgb-profile-1",
  "report": {
    "uri": "krita-artifact://example/color-diff.json",
    "mime_type": "application/json",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  }
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Differentiate assign-profile from convert-profile; never silently substitute one.

**krita_diff_measure · EXTENSION**

Compare layer/native/composite snapshots and quantify differences.

Input:
```json
{
  "before_checkpoint_id": "cp-1",
  "after": {
    "document_id": "doc-1",
    "revision": 12,
    "frame": 0
  },
  "scope": "composite",
  "metric": "exact_rgba",
  "region": {
    "x": 16,
    "y": 16,
    "width": 32,
    "height": 32
  }
}
```

Output data:
```json
{
  "changed_pixels": 27,
  "alpha_changed_pixels": 0,
  "diff": {
    "uri": "krita-artifact://example/diff.png",
    "mime_type": "image/png",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "bounds_px": {
    "x": 16,
    "y": 16,
    "width": 32,
    "height": 32
  }
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Also support palette occupancy, alpha topology, bounds and optional colour metrics with explicit units.

**krita_reference_set · EXTENSION**

Register approved references and board crops without painting them into art.

Input:
```json
{
  "project_id": "project-1",
  "references": [
    {
      "path": "/projects/demo/board.png",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "role": "approved-board",
      "crop_px": [
        0,
        0,
        512,
        512
      ]
    }
  ],
  "request_id": "req-ref"
}
```

Output data:
```json
{
  "reference_set_id": "refs-1",
  "count": 1
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_guides_set · EXTENSION**

Set document guides, grid and snapping as explicit working state.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "grid_px": [
    8,
    8
  ],
  "origin_px": [
    0,
    0
  ],
  "snap": true,
  "horizontal": [
    32
  ],
  "vertical": [
    32
  ]
}
```

Output data:
```json
{
  "grid_px": [
    8,
    8
  ],
  "snap": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_view_set · EXTENSION**

Set UI zoom/pan/rotation without changing document-coordinate semantics.

Input:
```json
{
  "document_id": "doc-1",
  "zoom": 4,
  "pan_px": [
    0,
    0
  ],
  "rotation_degrees": 0,
  "request_id": "req-view"
}
```

Output data:
```json
{
  "zoom": 4,
  "document_pixels_per_device_pixel": 0.25,
  "art_changed": false
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Report actual display scale; UI viewport state has its own revision and must not masquerade as document paint.

**krita_asset_metadata_set · EXTENSION**

Edit typed pivots, sockets, collision or nine-slice metadata separately.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "asset_id": "hero",
  "schema_id": "sprite-metadata-v1",
  "metadata": {
    "pivot_px": [
      64,
      120
    ],
    "sockets": {
      "hand": [
        82,
        64
      ]
    },
    "collision": {
      "type": "polygon",
      "vertices": [
        [
          40,
          40
        ],
        [
          80,
          40
        ],
        [
          80,
          100
        ],
        [
          40,
          100
        ]
      ]
    }
  }
}
```

Output data:
```json
{
  "metadata_id": "meta-1",
  "source_pixels_changed": 0,
  "validation_status": "pass"
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. No automatic enlargement of limits; project adapters own semantic rules.

**krita_animation_inspect · EXTENSION**

Read layers, clips, keyframes, holds and timing.

Input:
```json
{
  "source": {
    "document_id": "doc-1",
    "revision": 12,
    "frame": 0
  }
}
```

Output data:
```json
{
  "fps": 12,
  "clips": [
    {
      "id": "idle",
      "start": 0,
      "end_exclusive": 4
    }
  ],
  "keyframes": [
    {
      "layer_id": "body-1",
      "frame": 0,
      "hold_frames": 2
    }
  ]
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_animation_frame_edit · EXTENSION**

Insert, duplicate, move or delete explicit keyframes.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "layer_id": "body-1",
  "operation": "duplicate",
  "from_frame": 0,
  "to_frame": 2
}
```

Output data:
```json
{
  "layer_id": "body-1",
  "created_frame": 2,
  "other_frames_unchanged": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Mutations must be frame-specific and protect unrequested frames. Final schema discriminates operations.

**krita_animation_clip_set · EXTENSION**

Define clips and timing without changing frame pixels.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "clip_id": "idle",
  "start": 0,
  "end_exclusive": 4,
  "fps": 12,
  "loop": true
}
```

Output data:
```json
{
  "clip_id": "idle",
  "duration_seconds": 0.3333333333,
  "pixels_changed": 0
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_animation_preview · EXTENSION**

Render onion skins, contact sheets or timed playback.

Input:
```json
{
  "source": {
    "document_id": "doc-1",
    "revision": 12,
    "frame": 0
  },
  "clip_id": "idle",
  "mode": "contact_sheet",
  "scale": 2,
  "filter": "nearest",
  "show_pivot": true
}
```

Output data:
```json
{
  "sheet": {
    "uri": "krita-artifact://example/idle-sheet.png",
    "mime_type": "image/png",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "frames": 4,
  "durations_ms": [
    83.333333,
    83.333333,
    83.333333,
    83.333333
  ],
  "runtime_verified": false
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Playback mode returns timed media with exact rational timing metadata and reports dropped preview frames.

**krita_animation_export · EXTENSION**

Export ordered frame images and clip metadata.

Input:
```json
{
  "source": {
    "document_id": "doc-1",
    "revision": 12,
    "frame": 0
  },
  "clip_id": "idle",
  "registration_id": "reg-1",
  "destination": "/projects/demo/exports/idle",
  "request_id": "req-anim"
}
```

Output data:
```json
{
  "frames_exported": 4,
  "metadata": {
    "uri": "krita-artifact://example/idle.json",
    "mime_type": "application/json",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "pivot_stable": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Declare crop policy and offsets; retain frame rate/holds and optional project root motion.

**krita_tile_configure · EXTENSION**

Bind repeat axes, tile size, adjacency and wrap painting behavior.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "tile_size_px": [
    32,
    32
  ],
  "repeat_axes": [
    "x",
    "y"
  ],
  "wrap_paint": true
}
```

Output data:
```json
{
  "tile_id": "tile-1",
  "wrap_paint": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Check native wrap support. Never fake wrapped paint with only a repeated preview.

**krita_tile_preview · EXTENSION**

Render repeated patches and measure shared seams/corners.

Input:
```json
{
  "source": {
    "document_id": "doc-1",
    "revision": 12,
    "frame": 0
  },
  "repeat": [
    3,
    3
  ],
  "filter": "nearest",
  "seam_policy": "matching-edge-pixels"
}
```

Output data:
```json
{
  "image": {
    "uri": "krita-artifact://example/tile-patch.png",
    "mime_type": "image/png",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "edge_mismatches": 0,
  "corner_mismatches": 0
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Seam policy is project-specific; exact opposite-edge equality is not a universal definition of seamless art.

**krita_tileset_export · EXTENSION**

Export a declared tile/adjoining-variant layout.

Input:
```json
{
  "project_id": "project-1",
  "layout_id": "terrain-16",
  "source_ids": [
    "tile-1",
    "tile-2"
  ],
  "destination": "/projects/demo/exports/terrain",
  "request_id": "req-tiles"
}
```

Output data:
```json
{
  "tile_count": 2,
  "layout": {
    "uri": "krita-artifact://example/terrain.json",
    "mime_type": "application/json",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "missing_slots": [
    "slot-3"
  ]
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Report missing variants; never invent art to fill slots.

**krita_scene_render · EXTENSION**

Compose immutable assets with explicit transforms and draw order.

Input:
```json
{
  "project_id": "project-1",
  "scene_id": "level-proof",
  "viewport_px": [
    640,
    360
  ],
  "camera_px": [
    0,
    0
  ],
  "lighting_id": "noon",
  "asset_revisions": {
    "hero": 12
  }
}
```

Output data:
```json
{
  "image": {
    "uri": "krita-artifact://example/scene.png",
    "mime_type": "image/png",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "viewport_px": [
    640,
    360
  ],
  "missing_assets": [],
  "static_only": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Scene manifests pin source revision/hash, registration, clip frame, anchor, z/order and profile.

**krita_background_preview · EXTENSION**

Preview parallax/repeat layers at camera positions.

Input:
```json
{
  "project_id": "project-1",
  "scene_id": "parallax-proof",
  "camera_positions_px": [
    [
      0,
      0
    ],
    [
      320,
      0
    ]
  ],
  "viewport_px": [
    640,
    360
  ]
}
```

Output data:
```json
{
  "frames": [
    {
      "uri": "krita-artifact://example/camera-0.png",
      "mime_type": "image/png",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "size_bytes": 4096
    },
    {
      "uri": "krita-artifact://example/camera-1.png",
      "mime_type": "image/png",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "size_bytes": 4096
    }
  ],
  "seam_report": {
    "uri": "krita-artifact://example/background-seams.json",
    "mime_type": "application/json",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  }
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Offscreen preview is evidence of composition, not engine/device performance.

**krita_ui_preview · EXTENSION**

Render UI assets at native sizes, states and nine-slice stretches.

Input:
```json
{
  "project_id": "project-1",
  "layout_id": "hud-proof",
  "display_scale": 1,
  "panel_sizes_px": [
    [
      160,
      48
    ],
    [
      240,
      64
    ]
  ],
  "state_ids": [
    "normal",
    "pressed"
  ]
}
```

Output data:
```json
{
  "image": {
    "uri": "krita-artifact://example/hud.png",
    "mime_type": "image/png",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "nine_slice_checks": "pass",
  "native_pixel_sizes_preserved": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_text_edit · EXTENSION**

Create or update editable text when supported.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "layer_id": "text-1",
  "text": "PLAY",
  "font_resource_id": "font-1",
  "size_px": 16,
  "bounds_px": {
    "x": 16,
    "y": 16,
    "width": 32,
    "height": 32
  }
}
```

Output data:
```json
{
  "editable": true,
  "missing_glyphs": [],
  "font_substitution": false
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Reject unknown fonts rather than substituting. Report shaping and rasterization limits; never claim editable text after flattening.

**krita_vector_edit · EXTENSION**

Edit declared vector shapes without silently rasterizing them.

Input:
```json
{
  "guard": {
    "document_id": "doc-1",
    "expected_revision": 12,
    "request_id": "req-001"
  },
  "layer_id": "shape-1",
  "operation": "set_path",
  "svg_path": "M 0 0 L 16 0 L 8 16 Z",
  "fill": "#80A060"
}
```

Output data:
```json
{
  "editable": true,
  "rasterized": false
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Parse bounded SVG input; reject external resource links and unsupported constructs.

**krita_atlas_pack · EXTENSION**

Pack existing exports with explicit trim, padding and rotation rules.

Input:
```json
{
  "project_id": "project-1",
  "asset_manifest_uri": "krita-artifact://example/assets.json",
  "max_size_px": [
    1024,
    1024
  ],
  "padding_px": 2,
  "extrude_px": 1,
  "trim": true,
  "allow_rotation": false,
  "destination": "/projects/demo/exports/atlas",
  "request_id": "req-atlas"
}
```

Output data:
```json
{
  "pages": 1,
  "metadata": {
    "uri": "krita-artifact://example/atlas.json",
    "mime_type": "application/json",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "pivot_roundtrip_verified": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Preserve trim offsets, source hashes and anchors. Packing cannot repaint source assets.

**krita_export_batch · EXTENSION**

Export an explicit bounded set using per-asset registrations.

Input:
```json
{
  "project_id": "project-1",
  "items": [
    {
      "asset_id": "hero",
      "source": {
        "document_id": "doc-1",
        "revision": 12,
        "frame": 0
      },
      "registration_id": "reg-1"
    }
  ],
  "destination": "/projects/demo/exports/batch",
  "request_id": "req-batch"
}
```

Output data:
```json
{
  "succeeded": [
    "hero"
  ],
  "failed": [],
  "manifest": {
    "uri": "krita-artifact://example/batch.json",
    "mime_type": "application/json",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  }
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Explicit per-item results. Do not claim cross-document atomicity unless implemented; temporary outputs must not look like committed delivery.

**krita_engine_package · EXTENSION**

Build an engine-specific handoff through a registered adapter.

Input:
```json
{
  "project_id": "project-1",
  "adapter_id": "engine-json-v1",
  "manifest_uri": "krita-artifact://example/batch.json",
  "destination": "/projects/demo/handoff",
  "request_id": "req-package"
}
```

Output data:
```json
{
  "package_uri": "krita-artifact://example/package.zip",
  "manifest": {
    "uri": "krita-artifact://example/handoff.json",
    "mime_type": "application/json",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "size_bytes": 4096
  },
  "runtime_import_test": "not_run"
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. No game deployment or automatic import into a live project; capability-test each adapter separately.

**krita_recovery_list · EXTENSION**

List recoverable checkpoints and interrupted edit branches.

Input:
```json
{
  "project_id": "project-1"
}
```

Output data:
```json
{
  "recoveries": [
    {
      "id": "recovery-1",
      "document_name": "hero-working",
      "last_verified_revision": 12,
      "state": "interrupted"
    }
  ]
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_recovery_open · EXTENSION**

Open a recoverable state as a separate working document.

Input:
```json
{
  "recovery_id": "recovery-1",
  "request_id": "req-recover"
}
```

Output data:
```json
{
  "document_id": "doc-recovered",
  "revision": 1,
  "verified": true,
  "original_untouched": true
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. 

**krita_diagnostics_get · EXTENSION**

Retrieve bounded plugin errors and capability probe reports.

Input:
```json
{
  "operation_id": "op-export-1",
  "max_events": 20
}
```

Output data:
```json
{
  "events": [
    {
      "severity": "info",
      "message": "Export completed"
    }
  ],
  "probe_report_uri": "krita-artifact://example/probes.json"
}
```

Draft example shape; formal enum/range/union constraints must be finalized before exposure. Redact credentials and unrelated document paths; report API fallback and latency, not full image buffers.
