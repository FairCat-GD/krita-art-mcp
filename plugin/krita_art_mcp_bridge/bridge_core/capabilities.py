from typing import Any

# The capability matrix agents adapt to. Each entry is true for this build: a capability is
# supported only once it is built and tested, and `since` names the release that built it.
_MATRIX: dict[str, tuple[bool, str | None, str]] = {
    "stroke.native_brush": (False, None, "Native brush strokes are not built in this release."),
    "stroke.per_point_input": (
        False,
        None,
        "Per-point pressure, tilt, rotation and timing need Krita 6.1 / 5.4.",
    ),
    "stroke.smoothing": (
        False,
        None,
        "Server-side smoothing (none, catmull_rom) comes with native brush strokes.",
    ),
    "undo.grouping": (
        False,
        None,
        "Krita's scripting API cannot group undo steps; each change is its own step.",
    ),
    "stroke.deterministic": (
        False,
        None,
        "Stochastic presets have no seed control, so their strokes do not repeat exactly.",
    ),
    "operation.cancel_running": (
        False,
        None,
        "A running Krita call cannot be interrupted; only queued operations can be cancelled.",
    ),
    "selection.enforced": (False, None, "Selections are not built in this release."),
    "color_spaces": (
        False,
        None,
        "Documents are created RGBA / U8 / sRGB and opened RGBA / U8; others are refused.",
    ),
    "filters": (False, None, "Filters arrive in Phase 2."),
    "animation": (False, None, "Animation arrives in Phase 5."),
}


def matrix() -> dict[str, dict[str, Any]]:
    return {
        name: {"supported": supported, "since": since, "notes": notes}
        for name, (supported, since, notes) in _MATRIX.items()
    }
