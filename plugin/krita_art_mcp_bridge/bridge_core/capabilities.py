from typing import Any

# The capability matrix agents adapt to. Each entry is true for this build: a capability is
# supported only once it is built and tested, and `since` names the release that built it.
_MATRIX: dict[str, tuple[bool, str | None, str]] = {
    "stroke.native_brush": (
        True,
        "0.9.0",
        "One Krita brush stroke per call (Node.paintPath, every point at pressure 1), one undo "
        "step, verified against protection and undone on a leak.",
    ),
    "paint.fill": (
        True,
        "0.21.0",
        "A flat antialiased fill of a rect, ellipse, polygon, closed curve or the selection: one "
        "native Krita fill per call (Node.paintPath with no stroke), one undo step, verified "
        "against protection and undone on a leak.",
    ),
    "mask.transparency": (
        True,
        "0.22.0",
        "Transparency masks on paint layers: made with a coverage (all, none or the selection) in "
        "one undo step, painted with reveal or hide by strokes and fills, read alone as grey, and "
        "shown or hidden; each change verified against protection and undone on a leak.",
    ),
    "stroke.dynamics": (
        True,
        "0.24.0",
        "Size and opacity along a stroke's arc length through Krita's Distance sensor, pixel "
        "brush engine only: the preset is edited in memory for that one stroke and put back, "
        "checked by its digest and dirty flag.",
    ),
    "stroke.per_point_input": (
        False,
        None,
        "Per-point pressure, tilt, rotation and timing need Krita 6.1 / 5.4.",
    ),
    "stroke.smoothing": (
        True,
        "0.9.0",
        "none and catmull_rom, applied on the server; Krita's tool smoothing is not reachable "
        "from scripts.",
    ),
    "undo.grouping": (
        False,
        None,
        "Krita's scripting API cannot group undo steps: each is its own, and a reorder takes "
        "one for the remove and one for each node it adds back, which its receipt states and "
        "history moves together.",
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
    "selection.enforced": (
        True,
        "0.9.0",
        "Strokes and fills keep to the global selection; colour paint on a layer with a local "
        "selection mask is refused, and mask paint keeps to the global selection alone.",
    ),
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
