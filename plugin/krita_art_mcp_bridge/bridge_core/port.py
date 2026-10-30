from typing import Any, Protocol

from .errors import BridgeError


class DocumentsPort(Protocol):
    # Krita as the document ops see it; every method runs inside a job on the main thread.
    def documents(self) -> list[Any]: ...

    def refusal(self) -> BridgeError | None: ...

    # Creates, gives the document a view at once, and waits; cleans up after its own failure.
    def create(self, name: str, width: int, height: int) -> Any: ...

    # Opens in batch mode; IO_ERROR if Krita cannot. Nothing after it can strand the document.
    def open(self, path: str) -> Any: ...

    # Gives an opened document its view at once (K6), and waits.
    def show(self, document: Any) -> None: ...

    # {name, path, size_px, color_model, depth, profile_id, current_time, animated}; animated
    # says whether any node has keyframes, and is reported only when current_time is not 0.
    def describe(self, document: Any) -> dict[str, Any]: ...

    # The root's id, then each child as {id, type, opacity, active, alpha_at_origin}.
    def layers(self, document: Any) -> tuple[str, list[dict[str, Any]]]: ...

    # {root_id, active_id, nodes}: every node depth-first in Krita's child order, as Krita
    # reports it (type as Node.type(), opacity 0-255, offset_px, bounds_px).
    def tree(self, document: Any) -> dict[str, Any]: ...

    # The projection over the whole canvas, B, G, R, A for integer RGBA (K12), as a bytes-like
    # buffer.
    def composite(self, document: Any) -> Any: ...

    # The global selection's bounds {x, y, width, height} as Krita reports them, or None.
    def selection_bounds(self, document: Any) -> dict[str, int] | None: ...

    # The projection over each rect {x, y, width, height}, as composite() reads it.
    def composite_rects(self, document: Any, rects: list[dict[str, int]]) -> list[Any]: ...

    # One paint layer's own device over each rect (K12): no opacity, masks or inherit-alpha
    # clip. LAYER_NOT_FOUND for an unknown id.
    def layer_rects(
        self, document: Any, layer_id: str, rects: list[dict[str, int]]
    ) -> list[Any]: ...

    # The global selection over a rect, one byte per pixel; None when there is no selection.
    def selection_rect(self, document: Any, rect: dict[str, int]) -> Any | None: ...

    # Whether a selection mask is the active node, whose overlay would enter a composite (K46).
    def mask_active(self, document: Any) -> bool: ...

    # Makes the document's view the active one, so setActiveNode and undo act on it. Returns the
    # view it replaced, or None when nothing needs putting back.
    def bring_forward(self, document: Any) -> Any: ...

    # Puts back a view bring_forward replaced; logs a failure and never raises.
    def restore_view(self, view: Any) -> None: ...

    # The document in the active view, or None.
    def front(self) -> Any: ...

    # Makes a node the active one, in the document in front only, and waits.
    def activate(self, document: Any, node_id: str) -> None: ...

    # Adds an empty paint or group layer (kind as Node.type()) under parent_id, directly above
    # above_id or on top, in one undo step; waits, and returns its id.
    def create_layer(
        self, document: Any, parent_id: str, above_id: str | None, kind: str, name: str
    ) -> str: ...

    # Builds a selection by the recipe's steps, in order, and commits it with setSelection (one
    # undo step); a recipe of ("clear",) commits None. Waits.
    def set_selection(self, document: Any, recipe: list[tuple[Any, ...]]) -> None: ...

    # Sets a node's blend mode, a composite-op id, in one undo step that redraws it; waits.
    def set_blend(self, document: Any, layer_id: str, mode: str) -> None: ...

    # Writes a node's other properties, in Krita's terms, with no undo step and no redraw (K22,
    # K42): name, locked, alpha_locked, inherit_alpha, visible, opacity (0-255), in that order.
    def set_properties(self, document: Any, layer_id: str, values: dict[str, Any]) -> None: ...

    # Recomposes the whole projection and waits (K42).
    def refresh(self, document: Any) -> None: ...

    # {styled: ids with a layer style, clones: {clone id: source id or None}, animated: any
    # keyframes}; styles and clones, costly to read, only when reach is asked for.
    def effects(self, document: Any, reach: bool) -> dict[str, Any]: ...

    # Trigger Krita's Undo or Redo action on the document in front, wait, and let posted events
    # through, so the action's text names the new top step.
    def undo(self, document: Any) -> None: ...

    def redo(self, document: Any) -> None: ...

    # The labels the Undo and Redo actions show for the document in front, after posted events
    # are through; None for an action with no step.
    def undo_labels(self, document: Any) -> tuple[str | None, str | None]: ...

    # Harness only: the Undo and Redo actions' own text and enabled state, {undo, redo}.
    def undo_actions(self, document: Any) -> dict[str, Any]: ...

    # How many steps Krita keeps in a document's undo stack.
    def undo_limit(self) -> int: ...

    # Harness only: adds an empty layer per trial and reads the Undo label straight after the
    # wait, then after posted events are through.
    def label_timing(self, document: Any, trials: int) -> list[list[str | None]]: ...

    # Harness only: adds a local selection mask over rect to a layer and makes it the active
    # node; whether the composite over rect changed with it.
    def add_active_mask(self, document: Any, layer_id: str, rect: dict[str, int]) -> bool: ...

    # Harness only: adds a node of a harness.add_node kind for a layer; its id, and whether the
    # composite changed.
    def add_fixture_node(self, document: Any, kind: str, layer_id: str) -> tuple[str, bool]: ...

    # Applies the brush on the active view in K3's order: preset (the resource
    # ResourcesPort.preset found), size, opacity, flow, blend, eraser, alpha lock, rotation,
    # colour ([r, g, b, a] floats through ManagedColor, K18). Returns brush() afterwards, plus
    # "preset_xml", the current preset's Preset.toXML().
    def set_brush(self, document: Any, brush: dict[str, Any], preset: Any) -> dict[str, Any]: ...

    # The active view's brush as Krita holds it: the keys set_brush takes, "preset" being the
    # current preset's name.
    def brush(self, document: Any) -> dict[str, Any]: ...

    # Node.paintAbility() for the layer, with the document's view in front (K9).
    def paint_ability(self, document: Any, layer_id: str) -> str: ...

    # Mirror painting and wrap-around off, the path painted with Node.paintPath (one stroke, one
    # undo step), waitForDone, both modes put back in a finally that logs and never raises.
    # LAYER_NOT_FOUND for an unknown id; anything Krita raises passes through.
    def paint_path(self, document: Any, layer_id: str, path: dict[str, Any]) -> None: ...

    # Whether Krita merges consecutive strokes into one undo step.
    def cumulative_undo(self) -> bool: ...

    # Harness only: the view of the document in front, {zoom, rotation_deg, pan_px}; set_view
    # sets any of those keys and returns view_state() after.
    def view_state(self, document: Any) -> dict[str, Any]: ...

    def set_view(self, document: Any, view: dict[str, Any]) -> dict[str, Any]: ...

    # Harness only: brush() as "current", and under "presets", by file id,
    # each preset's {size_px, opacity, flow, blend_mode, eraser} as Krita holds them; JSON-able.
    # set_brush_state writes those presets' values back, then "current".
    def brush_state(self, document: Any, preset_ids: list[str]) -> dict[str, Any]: ...

    def set_brush_state(self, document: Any, state: dict[str, Any]) -> None: ...

    # Writes the document with Krita's own exporter, which the target's extension picks; False
    # while autosave holds it (K45). The document keeps pointing at its own file (K39).
    def export(self, document: Any, target: str) -> bool: ...

    # A node's own pixels over a rect, as pixelData reads them (a mask's are one byte each), or
    # its projection, masks applied; in document coordinates. LAYER_NOT_FOUND for an unknown id.
    def node_pixels(
        self, document: Any, node_id: str, rect: dict[str, int], projection: bool
    ) -> Any: ...

    # Waits, lets Krita's own timers run for settle_s with user input held back, clears the
    # modified flag so Krita never asks to save, then closes.
    def close(self, document: Any, settle_s: float = 0.0) -> bool: ...


class ResourcesPort(Protocol):
    # Krita's resources as resource.list sees them; every method runs inside a job.
    # Every brush preset as {name, file}, file being the resource's file name.
    def presets(self) -> list[dict[str, str]]: ...

    # Each named preset's settings as Preset.toXML() writes them; "" for one it cannot.
    def preset_xmls(self, names: list[str]) -> dict[str, str]: ...

    # The preset with this file name as {name, xml, resource}, in one walk of Krita's list; None
    # when there is none. xml is as preset_xmls gives it; resource is for set_brush and preset_xml.
    def preset(self, preset_id: str) -> dict[str, Any] | None: ...

    # A found preset's settings as they stand now.
    def preset_xml(self, resource: Any) -> str: ...

    def profiles(self, model: str, depth: str) -> list[str]: ...

    # Every palette as {name, file}.
    def palettes(self) -> list[dict[str, str]]: ...
