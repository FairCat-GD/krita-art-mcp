import binascii
import copy
import math
import os
import struct
import threading
import zipfile
import zlib
from typing import Any

from bridge_core import documents, history, nodes, saving, shapes
from bridge_core.bridge import Bridge
from bridge_core.errors import BridgeError

# Krita as the registry sees it, for the plugin-core tests on 3.10 and the server's tool tests.
SPACE = ("RGBA", "U8", documents.SRGB_PROFILE)
# A paint layer with no pixels of its own reads as this, B, G, R, A.
UNREAD = bytes([30, 20, 10, 255])
MASK = "transparencymask"


class FakeDocument:
    # Like libkis's wrapper: a new object per lookup, equal by document, unhashable.
    __hash__ = None  # type: ignore[assignment]

    def __init__(self, key: int) -> None:
        self.key = key

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FakeDocument) and other.key == self.key


def layer_id(key: int, index: int) -> str:
    return f"00000000-0000-4000-8000-{key:06d}{index:06d}"


def fake_node(key: int, index: int, name: str, parent_id: str, order: int, **changes: Any) -> Any:
    # A node as the port reports it: Krita's type names, opacity 0-255.
    return {
        "id": layer_id(key, index),
        "parent_id": parent_id,
        "name": name,
        "type": "paintlayer",
        "order": order,
        "visible": True,
        "opacity": 255,
        "blend_mode": "normal",
        "locked": False,
        "alpha_locked": False,
        "inherit_alpha": False,
        "offset_px": [0, 0],
        "bounds_px": {"x": 0, "y": 0, "width": 0, "height": 0},
        "color_model": "RGBA",
        "depth": "U8",
        "profile_id": documents.SRGB_PROFILE,
        **changes,
    }


def bgra(width: int, height: int) -> bytes:
    # A composite whose blue and red differ everywhere, so a missed channel swap shows.
    return bytes((index * 7 + 3) % 256 for index in range(width * height * 4))


class FakePort:
    def __init__(self) -> None:
        self.live: dict[int, dict[str, Any]] = {}
        self.next_key = 1
        self.refuse: BridgeError | None = None
        self.space = SPACE
        self.layer = {"type": "paintlayer", "opacity": 255, "active": True, "alpha_at_origin": 0}
        self.close_works = True
        self.closed: list[int] = []
        self.settled: list[float] = []
        self.created = 0
        self.on_create: list[Any] = []
        # What a file opens as, by path: size_px, space, names (top-level layers), selection,
        # active_mask. Anything else opens as an 8 x 4 document with one layer.
        self.files: dict[str, dict[str, Any]] = {}
        self.opened: list[str] = []
        self.on_open: list[Any] = []
        self.fail: dict[str, BaseException] = {}
        # Krita's undo stack per document: undo and redo act on the document in front (K7).
        self.limit = 30
        self.undo_works = True
        # The selection steps the adapter ran, in order.
        self.recipes: list[list[tuple[Any, ...]]] = []
        # Changes a create makes beside adding the layer, to test the verification.
        self.on_layer: list[Any] = []
        self.export_works = True
        # What each export wrote, by path: an open of that path reads it back. Hooks change what
        # is written, as a format or a fault would; merged_change alters only mergedimage.png.
        self.saved: dict[str, dict[str, Any]] = {}
        self.on_export: list[Any] = []
        self.merged_change: Any = None
        # A reopened document's node pixels, canvas-sized, by (key, node id).
        self.node_canvas: dict[tuple[int, str], bytes] = {}
        # The document whose view is active; a new or opened document comes to the front.
        self.front_key: int | None = None
        # Each floating message's document, and the document in front when it was asked for.
        self.announced: list[tuple[int, int | None]] = []
        # The order of the K46 steps and reads.
        self.calls: list[str] = []
        # One BGRA pixel per layer id; a layer reads as that pixel everywhere.
        self.layer_pixels: dict[str, bytes] = {}
        self.overlay = True
        # A document's composite, by key, in place of bgra(); and hooks run at each read.
        self.canvas: dict[int, bytes | bytearray] = {}
        self.on_read: list[Any] = []
        # A document's composite as a function of its tree, by key: reads show it as of the last
        # refresh or blend change, as Krita's projection does (K42).
        self.render: dict[int, Any] = {}
        self.projection: dict[int, bytes] = {}
        # What effects() reports, by key; and hooks run after each property write.
        self.reach: dict[int, dict[str, Any]] = {}
        self.on_properties: list[Any] = []
        # A layer's own pixels, canvas-sized BGRA, by layer id; a layer without one reads as its
        # layer_pixels everywhere. A stroke writes them and the composite in canvas.
        self.buffers: dict[str, bytearray] = {}
        # The window's brush (K3), each preset's XML by name, and each preset's values by file id.
        self.brush_now: dict[str, Any] = dict(BRUSH)
        self.preset_xml: dict[str, str] = {name: xml for _, name, xml in [*PRESETS, FILL_PRESET]}
        self.preset_state: dict[str, dict[str, Any]] = {}
        self.brush_order: list[str] = []
        # Brush fields Krita does not take, values it adjusts, and a change the next brush()
        # read finds, as if something set the brush in between.
        self.ignore_brush: set[str] = set()
        self.adjust: dict[str, Any] = {}
        self.brush_drift: dict[str, Any] = {}
        self.ability: dict[str, str] = {}
        self.cumulative = False
        self.views: dict[int, dict[str, Any]] = {}
        # Rects a stroke also paints, as a leak or a reach past R would; hooks run after it.
        self.stray: list[dict[str, int]] = []
        self.on_paint: list[Any] = []
        # The resources whose presets the view's preset is one object with (K51), once linked;
        # each XML a taper's edit and restore set, and a restore that leaves the edit in place.
        self.resources: FakeResources | None = None
        self.preset_edits: list[str] = []
        self.restore_keeps_edit = False
        self.paths: list[dict[str, Any]] = []
        self.shapes: list[dict[str, Any]] = []
        # The call whose marker every mutating call here answers to, once a test sets it.
        self.marker: Any = None

    def _marked(self) -> None:
        if self.marker is not None and not self.marker.changing:
            raise AssertionError("a mutating port call came before the op's marker")

    def open_by_hand(self, name: str) -> int:
        key = self._add(name, 640, 480)
        self.live[key]["path"] = f"/owner/{name}.kra"
        return key

    def _add(self, name: str, width: int, height: int) -> int:
        key, self.next_key = self.next_key, self.next_key + 1
        self.live[key] = {"name": name, "path": None, "size_px": [width, height]}
        self.front_key = key
        return key

    def documents(self) -> list[Any]:
        return [FakeDocument(key) for key in self.live]

    def refusal(self) -> BridgeError | None:
        return self.refuse

    def create(self, name: str, width: int, height: int) -> Any:
        self._marked()
        self.created += 1
        for hook in self.on_create:
            hook()
        return FakeDocument(self._add(name, width, height))

    def open(self, path: str) -> Any:
        self._marked()
        for hook in self.on_open:
            hook()
        self._maybe_fail("open")
        if path in self.saved:
            return self._reopen(path)
        spec = self.files.get(path, {})
        width, height = spec.get("size_px", [8, 4])
        # openDocument adds no view (K6), so the document in front stays until show().
        front = self.front_key
        key = self._add(os.path.basename(path), width, height)
        self.front_key = front
        names = spec.get("names", ["Layer"])
        root = f"root-{key}"
        nodes = [fake_node(key, i, name, root, i) for i, name in enumerate(names)]
        self.live[key].update(
            path=path,
            space=spec.get("space", self.space),
            tree={"root_id": root, "active_id": nodes[-1]["id"], "nodes": nodes},
            selection=spec.get("selection"),
            current_time=spec.get("current_time", 0),
            animated=spec.get("animated", False),
        )
        if spec.get("active_mask"):
            self.mask(key)
        self.opened.append(path)
        return FakeDocument(key)

    def paint_by_hand(self, key: int, layer_id: str, box: dict[str, int], pixel: bytes) -> None:
        # The owner paints a layer in Krita: one undo step the bridge never sees.
        self.paintable(key, None)
        before = self._state(key)
        node = self._layer(key, layer_id)
        size = self.live[key]["size_px"]
        _fill(self.buffers[layer_id], size, box, pixel)
        if node["visible"]:
            composite = self.canvas[key]
            assert isinstance(composite, bytearray)
            _fill(composite, size, box, pixel)
        node["bounds_px"] = _span([node["bounds_px"], box])
        self._push(key, "Freehand Brush Stroke", before)

    def mask(self, key: int, layer: str | None = None) -> str:
        # Makes a selection mask the active node: local on a layer (the top one by default), or
        # the global selection's, a child of the root, when layer is the root's id.
        tree = self._tree(key)
        roots = [node for node in tree["nodes"] if node["parent_id"] == tree["root_id"]]
        parent = layer or max(roots, key=lambda node: node["order"])["id"]
        index = len(tree["nodes"]) + 900
        order = sum(1 for node in tree["nodes"] if node["parent_id"] == parent)
        node = fake_node(key, index, "mask", parent, order, type="selectionmask")
        tree["nodes"].append(node)
        tree["active_id"] = node["id"]
        return str(node["id"])

    def show(self, document: Any) -> None:
        self._maybe_fail("show")
        self.front_key = document.key

    def describe(self, document: Any) -> dict[str, Any]:
        info = self.live[document.key]
        model, depth, profile = info.get("space", self.space)
        return {
            "name": info["name"],
            "path": info["path"],
            "size_px": info["size_px"],
            "color_model": model,
            "depth": depth,
            "profile_id": profile,
            "current_time": info.get("current_time", 0),
            "animated": info.get("animated", False),
            # Krita's own flag follows its undo stack, which is clean at the open or create; an
            # export and a property write leave it alone (measured on Krita 5.3.4.1).
            "modified": info.get("index", 0) != 0,
        }

    def tree(self, document: Any) -> dict[str, Any]:
        self._maybe_fail("tree")
        tree = copy.deepcopy(self._tree(document.key))
        bounds = {node["id"]: node["bounds_px"] for node in tree["nodes"]}
        for node in tree["nodes"]:
            # A transparency mask's bounds are its layer's (measured on Krita 5.3.4.1).
            if node["type"] == MASK and node["parent_id"] in bounds:
                node["bounds_px"] = dict(bounds[node["parent_id"]])
        return tree

    def _tree(self, key: int) -> dict[str, Any]:
        info = self.live[key]
        if "tree" not in info:
            node = fake_node(key, 0, "Layer 1", f"root-{key}", 0)
            info["tree"] = {"root_id": f"root-{key}", "active_id": node["id"], "nodes": [node]}
        tree: dict[str, Any] = info["tree"]
        return tree

    def activate(self, document: Any, node_id: str) -> None:
        # K46's activation, off a selection mask onto the layer that stands in for it before a
        # read, is window state, not a change; any other activation is.
        if not (self.mask_active(document) and node_id == nodes.unmasked(self.tree(document))):
            self._marked()
        # setActiveNode acts on the document in front only.
        self.calls.append("activate")
        if self.front_key == document.key:
            self._tree(document.key)["active_id"] = node_id

    def composite(self, document: Any) -> bytes:
        self._maybe_fail("composite")
        return self._composite(document.key)

    def _composite(self, key: int) -> bytes:
        width, height = self.live[key]["size_px"]
        if key in self.render:
            found = self.projection.setdefault(key, self.render[key](self._tree(key)))
        else:
            found = bytes(self.canvas.get(key) or bgra(width, height))
        return self._masked(key, found)

    def _masked(self, key: int, composite: bytes) -> bytes:
        # Each shown transparency mask scales the composite's alpha where its layer has paint.
        masks = [
            node
            for node in self._tree(key)["nodes"]
            if node["type"] == MASK and node["visible"] and node["id"] in self.buffers
        ]
        if not masks:
            return composite
        out = bytearray(composite)
        for mask in masks:
            layer = self.buffers.get(mask["parent_id"])
            if layer is None:
                continue
            cover = self.buffers[mask["id"]]
            for index, value in enumerate(cover):
                if value != 255 and layer[index * 4 + 3]:
                    out[index * 4 + 3] = out[index * 4 + 3] * value // 255
        return bytes(out)

    def selection_bounds(self, document: Any) -> dict[str, int] | None:
        found = self.live[document.key].get("selection")
        return None if found is None else dict(found[0])

    def composite_rects(self, document: Any, rects: list[dict[str, int]]) -> list[bytes]:
        self._maybe_fail("composite")
        for hook in self.on_read:
            hook()
        self.calls.append("read")
        width = self.live[document.key]["size_px"][0]
        canvas = self._composite(document.key)
        return [crop(canvas, width, rect, 4) for rect in rects]

    def _redraw(self, key: int) -> None:
        if key in self.render:
            self.projection[key] = self.render[key](self._tree(key))

    def layer_rects(self, document: Any, layer_id: str, rects: list[dict[str, int]]) -> list[bytes]:
        self.calls.append("read")
        if layer_id not in {node["id"] for node in self.tree(document)["nodes"]}:
            raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.")
        if layer_id in self.buffers:
            width = self.live[document.key]["size_px"][0]
            depth = 1 if self._layer(document.key, layer_id)["type"] == MASK else 4
            return [crop(bytes(self.buffers[layer_id]), width, rect, depth) for rect in rects]
        pixel = self.layer_pixels.get(layer_id, UNREAD)
        return [pixel * (rect["width"] * rect["height"]) for rect in rects]

    def selection_rect(self, document: Any, rect: dict[str, int]) -> bytes | None:
        found = self.live[document.key].get("selection")
        if found is None:
            return None
        bounds, data = found
        width, height = self.live[document.key]["size_px"]
        canvas = bytearray(width * height)
        for row in range(bounds["height"]):
            start = (bounds["y"] + row) * width + bounds["x"]
            canvas[start : start + bounds["width"]] = data[
                row * bounds["width"] : (row + 1) * bounds["width"]
            ]
        return crop(bytes(canvas), width, rect, 1)

    def is_masked(self, key: int) -> bool:
        return self.mask_active(FakeDocument(key))

    def mask_active(self, document: Any) -> bool:
        tree = self._tree(document.key)
        active = next((n for n in tree["nodes"] if n["id"] == tree["active_id"]), None)
        return active is not None and active["type"] == "selectionmask"

    def bring_forward(self, document: Any) -> Any:
        self.calls.append("forward")
        if self.front_key == document.key:
            return None
        previous, self.front_key = self.front_key, document.key
        return previous

    def restore_view(self, view: Any) -> None:
        self.calls.append("restore")
        self.front_key = view

    def front(self) -> Any:
        key = self.front_key
        return None if key is None or key not in self.live else FakeDocument(key)

    def announce(self, document: Any) -> None:
        self.announced.append((document.key, self.front_key))

    def add_active_mask(self, document: Any, layer_id: str, rect: dict[str, int]) -> bool:
        if layer_id not in {node["id"] for node in self.tree(document)["nodes"]}:
            raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.")
        before = self._state(document.key)
        self.mask(document.key, layer_id)
        self._push(document.key, "Add Layer", before)
        return self.overlay

    def create_layer(
        self, document: Any, parent_id: str, above_id: str | None, kind: str, name: str
    ) -> str:
        self._marked()
        self._maybe_fail("create_layer")
        key = document.key
        before = self._state(key)
        tree = self._tree(key)
        siblings = [node for node in tree["nodes"] if node["parent_id"] == parent_id]
        above = next((node for node in siblings if node["id"] == above_id), None)
        # Krita puts a layer added above nothing on top.
        order = len(siblings) if above is None else above["order"] + 1
        for node in siblings:
            if node["order"] >= order:
                node["order"] += 1
        node = fake_node(key, len(tree["nodes"]) + 100, name, parent_id, order, type=kind)
        tree["nodes"].append(node)
        for hook in self.on_layer:
            hook(tree, node)
        self._push(key, history.LABELS["layer.create"], before)
        return str(node["id"])

    def create_mask(
        self, document: Any, parent_id: str, above_id: str | None, name: str, coverage: str
    ) -> str:
        self._marked()
        self._maybe_fail("create_mask")
        key = document.key
        self.paintable(key, None)
        before = self._state(key)
        tree = self._tree(key)
        width, height = self.live[key]["size_px"]
        if coverage == "selection":
            found = self.selection_rect(document, _whole(width, height))
            if found is None:
                raise BridgeError("INVALID_ARGUMENT", "There is no selection to start from.")
            cover = bytearray(found)
        else:
            cover = bytearray((b"\xff" if coverage == "all" else b"\x00") * (width * height))
        siblings = [node for node in tree["nodes"] if node["parent_id"] == parent_id]
        above = next((node for node in siblings if node["id"] == above_id), None)
        order = len(siblings) if above is None else above["order"] + 1
        for node in siblings:
            if node["order"] >= order:
                node["order"] += 1
        node = fake_node(
            key,
            len(tree["nodes"]) + 100,
            name,
            parent_id,
            order,
            type=MASK,
            color_model="A",
            depth="U8",
            profile_id="default",
        )
        tree["nodes"].append(node)
        self.buffers[node["id"]] = cover
        for hook in self.on_layer:
            hook(tree, node)
        self._push(key, history.LABELS["layer.create"], before)
        return str(node["id"])

    def set_selection(self, document: Any, recipe: list[tuple[Any, ...]]) -> None:
        self._marked()
        self._maybe_fail("set_selection")
        key = document.key
        self.recipes.append(recipe)
        before = self._state(key)
        width, height = self.live[key]["size_px"]
        found = self.live[key].get("selection")
        current = None if found is None else self.selection_rect(document, _whole(width, height))
        shape: bytearray | None = None
        for step in recipe:
            if step[0] == "clear":
                self._select(key, None)
                self._push(key, history.LABELS["selection.clear"], before)
                return
            if step[0] == "mask":
                shape = bytearray(width * height)
                rect, data = step[1], step[2]
                for row in range(rect["height"]):
                    start = (rect["y"] + row) * width + rect["x"]
                    shape[start : start + rect["width"]] = data[
                        row * rect["width"] : (row + 1) * rect["width"]
                    ]
            elif step[0] == "all":
                shape = bytearray(b"\xff" * (width * height))
            elif step[0] == "layer_alpha":
                alpha = self.layer_pixels.get(step[1], bytes([30, 20, 10, 255]))[3]
                shape = bytearray(bytes([alpha]) * (width * height))
            elif step[0] == "invert" and shape is not None:
                shape = bytearray(255 - value for value in shape)
            elif step[0] == "combine" and shape is not None:
                shape = _combine(step[1], current, shape)
        self._select(key, bytes(shape or b""))
        self._push(key, history.LABELS["selection.set"], before)

    def set_blend(self, document: Any, layer_id: str, mode: str) -> None:
        self._marked()
        self._maybe_fail("set_blend")
        self.calls.append("blend")
        node = self._layer(document.key, layer_id)
        # Krita's command undoes the blend alone; property writes around it stay (K22).
        blend = (layer_id, node["blend_mode"], mode)
        node["blend_mode"] = mode
        self._push(document.key, history.LABELS["layer.update"], None, blend)
        self._redraw(document.key)

    def set_properties(self, document: Any, layer_id: str, values: dict[str, Any]) -> None:
        self._marked()
        self.calls.append("properties")
        self._layer(document.key, layer_id).update(values)
        self._maybe_fail("set_properties")
        for hook in self.on_properties:
            hook(self._tree(document.key))

    def refresh(self, document: Any) -> None:
        self._maybe_fail("refresh")
        self.calls.append("refresh")
        self._redraw(document.key)

    def effects(self, document: Any, reach: bool) -> dict[str, Any]:
        self.calls.append(f"effects {reach}")
        default = {"styled": [], "clones": {}, "animated": False}
        found = copy.deepcopy(self.reach.get(document.key, default))
        return found if reach else {**found, "styled": [], "clones": {}}

    def add_fixture_node(self, document: Any, kind: str, layer_id: str) -> tuple[str, bool]:
        key = document.key
        layer = self._layer(key, layer_id)
        before = self._state(key)
        tree = self._tree(key)
        index = len(tree["nodes"]) + 700
        if kind == "filter_layer":
            parent, order, made = layer["parent_id"], layer["order"] + 1, "filterlayer"
            for node in tree["nodes"]:
                if node["parent_id"] == parent and node["order"] >= order:
                    node["order"] += 1
        elif kind == "clone_layer":
            parent, made = tree["root_id"], "clonelayer"
            order = sum(1 for node in tree["nodes"] if node["parent_id"] == parent)
        else:
            parent, made = layer_id, kind.replace("_", "")
            order = sum(1 for node in tree["nodes"] if node["parent_id"] == parent)
        node = fake_node(key, index, "probe node", parent, order, type=made)
        tree["nodes"].append(node)
        if made == "clonelayer":
            facts = self.reach.setdefault(key, {"styled": [], "clones": {}, "animated": False})
            facts["clones"][node["id"]] = layer_id
        self._push(key, "Add Layer", before)
        return str(node["id"]), True

    def _layer(self, key: int, layer_id: str) -> dict[str, Any]:
        node = next((n for n in self._tree(key)["nodes"] if n["id"] == layer_id), None)
        if node is None:
            raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.")
        found: dict[str, Any] = node
        return found

    def _select(self, key: int, canvas: bytes | None) -> None:
        # Krita keeps the global selection in a selection mask under the root.
        tree = self._tree(key)
        global_masks = [
            node
            for node in tree["nodes"]
            if node["type"] == "selectionmask" and node["parent_id"] == tree["root_id"]
        ]
        if canvas is None:
            self.live[key]["selection"] = None
            tree["nodes"] = [node for node in tree["nodes"] if node not in global_masks]
            return
        if not global_masks:
            order = sum(1 for node in tree["nodes"] if node["parent_id"] == tree["root_id"])
            mask = fake_node(key, 800, "Selection Mask", tree["root_id"], order)
            tree["nodes"].append({**mask, "type": "selectionmask"})
        width = self.live[key]["size_px"][0]
        rows = [canvas[top : top + width] for top in range(0, len(canvas), width)]
        used = [index for index, row in enumerate(rows) if any(row)]
        if not used:
            self.live[key]["selection"] = ({"x": 0, "y": 0, "width": 0, "height": 0}, b"")
            return
        left = min(next(i for i, v in enumerate(rows[r]) if v) for r in used)
        right = max(max(i for i, v in enumerate(rows[r]) if v) for r in used) + 1
        bounds = {"x": left, "y": used[0], "width": right - left, "height": used[-1] - used[0] + 1}
        data = b"".join(rows[r][left:right] for r in range(used[0], used[-1] + 1))
        self.live[key]["selection"] = (bounds, data)

    def _state(self, key: int) -> Any:
        tree = self._tree(key)
        ids = {node["id"] for node in tree["nodes"]}
        buffers = {node_id: bytes(data) for node_id, data in self.buffers.items() if node_id in ids}
        canvas = self.canvas.get(key)
        held = copy.deepcopy((tree, self.live[key].get("selection")))
        return (*held, buffers, None if canvas is None else bytes(canvas))

    def _restore(self, key: int, state: Any) -> None:
        tree, selection, buffers, canvas = state
        self.live[key]["tree"] = copy.deepcopy(tree)
        self.live[key]["selection"] = copy.deepcopy(selection)
        for node_id, data in buffers.items():
            self.buffers[node_id] = bytearray(data)
        if canvas is not None:
            self.canvas[key] = bytearray(canvas)

    def _push(self, key: int, label: str, before: Any, blend: Any = None) -> None:
        info = self.live[key]
        stack = info.setdefault("stack", [])
        del stack[info.get("index", 0) :]
        after = None if blend is not None else self._state(key)
        stack.append({"label": label, "before": before, "after": after, "blend": blend})
        if len(stack) > self.limit:
            del stack[0]
        info["index"] = len(stack)

    def undo(self, document: Any) -> None:
        self._marked()
        self.calls.append("undo")
        info = self.live.get(self.front_key or -1)
        if self.undo_works and info is not None and info.get("index", 0) > 0:
            info["index"] -= 1
            self._step(self.front_key or -1, info["stack"][info["index"]], "before")

    def redo(self, document: Any) -> None:
        self._marked()
        self.calls.append("redo")
        info = self.live.get(self.front_key or -1)
        if info is not None and info.get("index", 0) < len(info.get("stack", [])):
            self._step(self.front_key or -1, info["stack"][info["index"]], "after")
            info["index"] += 1

    def _step(self, key: int, entry: dict[str, Any], side: str) -> None:
        if entry["blend"] is not None:
            node_id, old, new = entry["blend"]
            self._layer(key, node_id)["blend_mode"] = old if side == "before" else new
        else:
            self._restore(key, entry[side])
        self._redraw(key)

    def undo_labels(self, document: Any) -> tuple[str | None, str | None]:
        # The actions name the steps of the document in front.
        info = self.live.get(self.front_key or -1, {})
        stack, index = info.get("stack", []), info.get("index", 0)
        undo = stack[index - 1]["label"] if index > 0 else None
        redo = stack[index]["label"] if index < len(stack) else None
        return undo, redo

    def undo_limit(self) -> int:
        return self.limit

    def label_timing(self, document: Any, trials: int) -> list[str | None]:
        root = self._tree(document.key)["root_id"]
        reads = []
        for trial in range(trials):
            self.create_layer(document, root, None, "paintlayer", f"timing {trial}")
            reads.append(self.undo_labels(document)[0])
        return reads

    def export(self, document: Any, target: str) -> bool:
        # Writes a zip with the document's mergedimage.png, and keeps what an open reads back.
        self._marked()
        self.calls.append("export")
        if not self.export_works:
            return False
        key = document.key
        width, height = self.live[key]["size_px"]
        tree = copy.deepcopy(self._tree(key))
        whole = _whole(width, height)
        kind = os.path.splitext(target)[1].lower()
        saved: dict[str, Any] = {
            "kind": kind,
            "size_px": [width, height],
            "space": self.live[key].get("space", self.space),
            "tree": tree,
            # An ORA layer holds its projection.
            "pixels": {
                node["id"]: self._node_bytes(key, node, whole, kind == ".ora")
                for node in tree["nodes"]
            },
            "composite": self._composite(key),
        }
        for hook in self.on_export:
            hook(saved)
        merged = bytearray(saved["composite"])
        if self.merged_change is not None:
            self.merged_change(merged)
        with zipfile.ZipFile(target, "x") as archive:
            archive.writestr("mimetype", "application/x-krita")
            archive.writestr("mergedimage.png", png(width, height, merged))
        self.saved[target] = saved
        return True

    def _reopen(self, path: str) -> Any:
        # The file as an open reads it: an ORA keeps no ids, masks or adjustment layers, and
        # brings every layer but a group back as a paint layer without alpha lock, its opacity
        # rounded as Krita's ORA writer and loader round it.
        saved = self.saved[path]
        width, height = saved["size_px"]
        front = self.front_key
        key = self._add(os.path.basename(path), width, height)
        self.front_key = front
        tree = copy.deepcopy(saved["tree"])
        root = f"root-{key}"
        nodes = []
        renamed = {tree["root_id"]: root}
        for index, node in enumerate(tree["nodes"]):
            if saved["kind"] == ".ora":
                if node["type"] not in ORA_TYPES or node["parent_id"] not in renamed:
                    continue
                renamed[node["id"]] = layer_id(key, index)
                kind = "grouplayer" if node["type"] == "grouplayer" else "paintlayer"
                node = {
                    **node,
                    "id": renamed[node["id"]],
                    "type": kind,
                    "alpha_locked": False,
                    "opacity": saving.ora_opacity(node["opacity"]),
                }
            else:
                renamed[node["id"]] = node["id"]
            nodes.append({**node, "parent_id": renamed[node["parent_id"]]})
        if saved["kind"] == ".ora":
            for parent in {node["parent_id"] for node in nodes}:
                siblings = sorted(
                    (node for node in nodes if node["parent_id"] == parent),
                    key=lambda node: node["order"],
                )
                for order, node in enumerate(siblings):
                    node["order"] = order
        for old, new in renamed.items():
            if old in saved["pixels"]:
                self.node_canvas[(key, new)] = saved["pixels"][old]
        active = nodes[-1]["id"] if nodes else None
        self.live[key].update(
            path=path,
            space=saved["space"],
            tree={"root_id": root, "active_id": active, "nodes": nodes},
        )
        self.canvas[key] = bytearray(saved["composite"])
        self.opened.append(path)
        return FakeDocument(key)

    def node_pixels(
        self, document: Any, node_id: str, rect: dict[str, int], projection: bool
    ) -> bytes:
        self.calls.append("node")
        node = self._layer(document.key, node_id)
        return self._node_bytes(document.key, node, rect, projection)

    def _node_bytes(
        self, key: int, node: dict[str, Any], rect: dict[str, int], projection: bool
    ) -> bytes:
        # A group has no pixels of its own; a mask reads one byte a pixel; a layer reads its
        # buffer, or its layer_pixels everywhere. The fake applies no mask, so a projection
        # reads as the layer.
        width = self.live[key]["size_px"][0]
        found = self.node_canvas.get((key, node["id"]))
        if found is not None:
            return crop(found, width, rect, 1 if node["type"].endswith("mask") else 4)
        area = rect["width"] * rect["height"]
        if node["type"] == "grouplayer":
            return b""
        if node["type"].endswith("mask"):
            if node["id"] in self.buffers:
                return crop(bytes(self.buffers[node["id"]]), width, rect, 1)
            return b"\xff" * area
        if node["id"] in self.buffers:
            return crop(bytes(self.buffers[node["id"]]), width, rect, 4)
        return self.layer_pixels.get(node["id"], UNREAD) * area

    def paintable(self, key: int, pixel: bytes | None = bytes(4)) -> None:
        # Gives every paint layer of a document its own pixels, and the composite a buffer; with
        # pixel None, each layer starts as layer_rects read it before it had any.
        width, height = self.live[key]["size_px"]
        for node in self._tree(key)["nodes"]:
            if node["type"] == "paintlayer" and node["id"] not in self.buffers:
                fill = self.layer_pixels.get(node["id"], UNREAD) if pixel is None else pixel
                self.buffers[node["id"]] = bytearray(fill * (width * height))
        found = self.canvas.get(key)
        if not isinstance(found, bytearray):
            self.canvas[key] = bytearray(found or bgra(width, height))

    def set_brush(self, document: Any, brush: dict[str, Any], preset: Any) -> dict[str, Any]:
        for key in BRUSH_ORDER:
            self.brush_order.append(key)
            if key in self.ignore_brush:
                continue
            if key == "preset":
                # Activating a preset resets the composite op (K3).
                self.brush_now["blend_mode"] = "normal"
            self.brush_now[key] = copy.deepcopy(self.adjust.get(key, brush[key]))
        found = copy.deepcopy(self.brush_now)
        found["preset_xml"] = self.preset_xml.get(found["preset"], "")
        return found

    def brush(self, document: Any) -> dict[str, Any]:
        self.brush_now.update(self.brush_drift)
        self.brush_drift = {}
        return copy.deepcopy(self.brush_now)

    def edit_preset(self, document: Any, xml: str) -> str:
        # Preset.fromXML: the one preset the view and the resources hold changes, and is dirty.
        self.calls.append("edit_preset")
        self._maybe_fail("edit_preset")
        self.preset_edits.append(xml)
        self._preset_now(xml, True)
        return self.preset_xml[self.brush_now["preset"]]

    def restore_preset(self, document: Any, xml: str, reload: bool) -> str:
        self.calls.append("restore_preset")
        self._maybe_fail("restore_preset")
        if not self.restore_keeps_edit:
            self._preset_now(xml, True)
            if reload and self.resources is not None:
                name = self.brush_now["preset"]
                self._preset_now(self.resources.stored[name], False)
        return self.preset_xml[self.brush_now["preset"]]

    def _preset_now(self, xml: str, dirty: bool) -> None:
        name = self.brush_now["preset"]
        self.preset_xml[name] = xml
        if self.resources is not None:
            self.resources.xmls[name] = xml
            self.resources.dirty[name] = dirty

    def paint_ability(self, document: Any, layer_id: str) -> str:
        self.calls.append("ability")
        return self.ability.get(layer_id, "PAINT")

    def cumulative_undo(self) -> bool:
        return self.cumulative

    def set_fill(self, document: Any, fill: dict[str, Any], preset: Any) -> dict[str, Any]:
        values = {**fill, "preset": preset, "flow": 1.0, "eraser": False}
        for key in FILL_ORDER:
            self.brush_order.append(key)
            if key in self.ignore_brush:
                continue
            if key == "preset":
                self.brush_now["blend_mode"] = "normal"
            self.brush_now[key] = copy.deepcopy(self.adjust.get(key, values[key]))
        found = copy.deepcopy(self.brush_now)
        found["preset_xml"] = self.preset_xml.get(found["preset"], "")
        return found

    def fill_path(self, document: Any, layer_id: str, shape: dict[str, Any]) -> None:
        # The shape's whole pixels in the fill's colour: a rect exactly, any other its box.
        self._marked()
        self.calls.append("fill")
        self._maybe_fail("fill_path")
        key = document.key
        node = self._layer(key, layer_id)
        self.paintable(key, None)
        before = self._state(key)
        self.shapes.append(copy.deepcopy(shape))
        boxes = [shapes.aligned(shapes.box(shape))] + [dict(rect) for rect in self.stray]
        size = self.live[key]["size_px"]
        if node["type"] == MASK:
            self._cover(layer_id, size, boxes)
        else:
            red, green, blue = (round(value * 255) for value in self.brush_now["color"][:3])
            pixel = bytes([blue, green, red, 255])
            composite = self.canvas[key]
            assert isinstance(composite, bytearray)
            for box in boxes:
                _fill(self.buffers[layer_id], size, box, pixel)
                _fill(composite, size, box, pixel)
            node["bounds_px"] = _span([node["bounds_px"], *boxes])
        for hook in self.on_paint:
            hook(key)
        self._push(key, history.LABELS["paint.fill"], before)
        self._maybe_fail("fill_path_after")

    def paint_path(self, document: Any, layer_id: str, path: dict[str, Any]) -> None:
        self._marked()
        self.calls.append("paint")
        self._maybe_fail("paint_path")
        key = document.key
        node = self._layer(key, layer_id)
        # The pixels exist before the snapshot, so an undo has them to put back.
        self.paintable(key, None)
        before = self._state(key)
        self.paths.append(copy.deepcopy(path))
        brush = self.brush_now
        radius = brush["size_px"] / 2
        points = [path["start"]] + [segment[-2:] for segment in path["segments"]]
        boxes = [_around(x, y, radius) for x, y in points] + [dict(rect) for rect in self.stray]
        if node["type"] == MASK:
            self._cover(layer_id, self.live[key]["size_px"], boxes)
            for hook in self.on_paint:
                hook(key)
            self._push(key, history.LABELS["paint.stroke"], before)
            self._maybe_fail("paint_path_after")
            return
        if brush["eraser"]:
            pixel = bytes(4)
        else:
            red, green, blue = (round(value * 255) for value in brush["color"][:3])
            pixel = bytes([blue, green, red, 255])
        size = self.live[key]["size_px"]
        composite = self.canvas[key]
        assert isinstance(composite, bytearray)
        for box in boxes:
            _fill(self.buffers[layer_id], size, box, pixel)
            # An eraser here leaves the composite alone, as it does over an empty layer.
            if not brush["eraser"]:
                _fill(composite, size, box, pixel)
        if not brush["eraser"]:
            node["bounds_px"] = _span([node["bounds_px"], *boxes])
        for hook in self.on_paint:
            hook(key)
        self._push(key, history.LABELS["paint.stroke"], before)
        self._maybe_fail("paint_path_after")

    def _cover(self, mask_id: str, size: list[int], boxes: list[dict[str, int]]) -> None:
        # White reveals and black hides on a mask, each by the opacity (measured on 5.3.4.1).
        target = round(self.brush_now["color"][0] * 255)
        opacity = self.brush_now["opacity"]
        cover = self.buffers[mask_id]
        for box in boxes:
            left, top = max(0, box["x"]), max(0, box["y"])
            right = min(size[0], box["x"] + box["width"])
            bottom = min(size[1], box["y"] + box["height"])
            for row in range(top, bottom):
                for column in range(left, right):
                    index = row * size[0] + column
                    cover[index] = round(cover[index] + (target - cover[index]) * opacity)

    def view_state(self, document: Any) -> dict[str, Any]:
        return copy.deepcopy(self.views.setdefault(document.key, dict(VIEW)))

    def set_view(self, document: Any, view: dict[str, Any]) -> dict[str, Any]:
        self.views.setdefault(document.key, dict(VIEW)).update(copy.deepcopy(view))
        return self.view_state(document)

    def brush_state(self, document: Any, preset_ids: list[str]) -> dict[str, Any]:
        # Each preset's values by file id, as the adapter resolves them.
        current = {key: value for key, value in self.brush_now.items()}
        presets = {one: dict(self.preset_state.get(one, PRESET_STATE)) for one in preset_ids}
        return copy.deepcopy({"current": current, "presets": presets})

    def set_brush_state(self, document: Any, state: dict[str, Any]) -> None:
        for preset_id, values in state["presets"].items():
            self.preset_state[preset_id] = dict(values)
        self.brush_now = copy.deepcopy(state["current"])

    def _maybe_fail(self, step: str) -> None:
        failure = self.fail.get(step)
        if failure is not None:
            raise failure

    def layers(self, document: Any) -> tuple[str, list[dict[str, Any]]]:
        return f"root-{document.key}", [{"id": f"layer-{document.key}", **self.layer}]

    def close(self, document: Any, settle_s: float = 0.0) -> bool:
        self._marked()
        self.closed.append(document.key)
        self.settled.append(settle_s)
        if self.close_works:
            del self.live[document.key]
        return True


def _whole(width: int, height: int) -> dict[str, int]:
    return {"x": 0, "y": 0, "width": width, "height": height}


# The node types Krita's ORA exporter writes as layers.
ORA_TYPES = {"paintlayer", "grouplayer", "filllayer", "clonelayer", "filelayer", "vectorlayer"}


def png(width: int, height: int, composite: bytes | bytearray) -> bytes:
    # An 8-bit RGBA PNG of a B, G, R, A composite, as Krita's mergedimage.png is.
    rows = []
    for row in range(height):
        line = bytearray(composite[row * width * 4 : (row + 1) * width * 4])
        line[0::4], line[2::4] = line[2::4], line[0::4]
        rows.append(b"\x00" + bytes(line))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", binascii.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def _combine(mode: str, current: bytes | None, shape: bytearray) -> bytearray:
    if mode == "replace" or current is None:
        return shape
    if mode == "add":
        return bytearray(max(a, b) for a, b in zip(current, shape, strict=True))
    if mode == "subtract":
        return bytearray(min(a, 255 - b) for a, b in zip(current, shape, strict=True))
    return bytearray(min(a, b) for a, b in zip(current, shape, strict=True))


def _around(x: float, y: float, radius: float) -> dict[str, int]:
    # A dab's box: every pixel the brush can touch around an on-curve point.
    left, top = math.floor(x - radius), math.floor(y - radius)
    right, bottom = math.ceil(x + radius), math.ceil(y + radius)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _fill(canvas: bytearray, size: list[int], box: dict[str, int], pixel: bytes) -> None:
    left, top = max(0, box["x"]), max(0, box["y"])
    right = min(size[0], box["x"] + box["width"])
    bottom = min(size[1], box["y"] + box["height"])
    for row in range(top, bottom):
        start = (row * size[0] + left) * 4
        canvas[start : start + (right - left) * 4] = pixel * max(0, right - left)


def _span(rects: list[dict[str, int]]) -> dict[str, int]:
    found = [rect for rect in rects if rect["width"] > 0 and rect["height"] > 0]
    left = min(rect["x"] for rect in found)
    top = min(rect["y"] for rect in found)
    right = max(rect["x"] + rect["width"] for rect in found)
    bottom = max(rect["y"] + rect["height"] for rect in found)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def crop(canvas: bytes, width: int, rect: dict[str, int], depth: int) -> bytes:
    rows = (
        canvas[((rect["y"] + row) * width + rect["x"]) * depth :][: rect["width"] * depth]
        for row in range(rect["height"])
    )
    return b"".join(rows)


def preset_xml(
    name: str,
    engine: str = "paintbrush",
    brush: str = '<Brush type="auto_brush" spacing="0.1"><MaskGenerator type="circle"/></Brush>',
    scatter: dict[str, str] | None = None,
) -> str:
    # A preset as Preset.toXML() writes it: the tip's own XML escaped inside a param.
    if scatter is None:
        scatter = {"PressureScatter": "false", "ScatterValue": "1", "Scattering/AxisX": "true"}
        scatter["Scattering/AxisY"] = "false"
    params = {"brush_definition": brush, **scatter}
    body = "".join(
        f'<param type="string" name="{key}">{_escape(value)}</param>'
        for key, value in params.items()
    )
    return f'<Preset paintopid="{engine}" name="{name}">{body}</Preset>'


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# A round tip with its scatter off, as Krita's own basic preset is.
PRESET_XML = preset_xml("Basic Round")
SCATTERED = {
    "PressureScatter": "true",
    "ScatterValue": "2",
    "Scattering/AxisX": "true",
    "Scattering/AxisY": "false",
}
# Brush presets as (file, name, XML); after the first three, those the stroke tests add: a round,
# a square and an image tip, a scattering one, one with its scatter keys missing, another engine.
PRESETS = [
    ("basic-round.kpp", "Basic Round", PRESET_XML),
    ("airbrush-soft.kpp", "Soft Airbrush", '<Preset name="Soft Airbrush" paintopid="airbrush"/>'),
    ("broken.kpp", "Broken", ""),
    ("hard-round.kpp", "Hard Round", preset_xml("Hard Round")),
    (
        "hard-square.kpp",
        "Hard Square",
        preset_xml(
            "Hard Square",
            brush='<Brush type="auto_brush" spacing="0.2"><MaskGenerator type="rect"/></Brush>',
        ),
    ),
    (
        "bristles.kpp",
        "Bristles",
        preset_xml("Bristles", brush='<Brush type="png_brush" spacing="0.5" filename="b.png"/>'),
    ),
    ("scatter.kpp", "Scatter", preset_xml("Scatter", scatter=SCATTERED)),
    ("no-scatter-keys.kpp", "No Scatter Keys", preset_xml("No Scatter Keys", scatter={})),
    ("smudge.kpp", "Smudge", preset_xml("Smudge", engine="colorsmudge")),
]
# The build-up stock preset every fill activates.
FILL_PRESET = (
    "c)_Pencil-3_Large_4B.kpp",
    "c) Pencil-3 Large 4B",
    preset_xml("c) Pencil-3 Large 4B", scatter={"PaintOpAction": "1"}),
)
# The window's brush as Krita starts, the order set_brush takes the fields in (K3), and a view.
BRUSH: dict[str, Any] = {
    "preset": "Basic Round",
    "size_px": 10.0,
    "opacity": 1.0,
    "flow": 1.0,
    "color": [0.0, 0.0, 0.0, 1.0],
    "eraser": False,
    "blend_mode": "normal",
    "alpha_lock": False,
    "rotation_deg": 0.0,
}
BRUSH_ORDER = (
    "preset",
    "size_px",
    "opacity",
    "flow",
    "blend_mode",
    "eraser",
    "alpha_lock",
    "rotation_deg",
    "color",
)
FILL_ORDER = ("preset", "opacity", "flow", "blend_mode", "eraser", "alpha_lock", "color")
VIEW: dict[str, Any] = {"zoom": 1.0, "rotation_deg": 0.0, "pan_px": [0, 0]}
PRESET_STATE: dict[str, Any] = {
    "size_px": 10.0,
    "opacity": 1.0,
    "flow": 1.0,
    "blend_mode": "normal",
    "eraser": False,
}


class FakeResources:
    # Krita's resources as resource.list sees them.
    def __init__(self) -> None:
        self.preset_list = [{"name": name, "file": file} for file, name, _ in PRESETS[:3]]
        self.xmls = {name: xml for _, name, xml in [*PRESETS, FILL_PRESET]}
        # Found but not listed, so the listings keep their three; None as if Krita lacked it.
        self.stock: dict[str, str] | None = {"name": FILL_PRESET[1], "file": FILL_PRESET[0]}
        self.profile_names = ["sRGB-elle-V2-srgbtrc.icc", "sRGB built-in"]
        self.palette_list = [{"name": "Default", "file": "default.kpl"}]
        self.asked: list[list[str]] = []
        # Each call a stroke makes, by method: the walks and serialisations it costs.
        self.calls: list[str] = []
        # Each preset's XML as Krita's storage holds it, its dirty flag by name (None as if no
        # resource chooser said), and kritarc's useDirtyPresets.
        self.stored = dict(self.xmls)
        self.dirty: dict[str, bool | None] = {}
        self.setting: str | None = None

    def add_stroke_presets(self) -> None:
        self.preset_list += [{"name": name, "file": file} for file, name, _ in PRESETS[3:]]

    def presets(self) -> list[dict[str, str]]:
        self.calls.append("presets")
        return list(self.preset_list)

    def preset_xmls(self, names: list[str]) -> dict[str, str]:
        self.calls.append("preset_xmls")
        self.asked.append(list(names))
        return {name: self.xmls.get(name, "") for name in names}

    def preset(self, preset_id: str) -> dict[str, Any] | None:
        self.calls.append("preset")
        for entry in [*self.preset_list, *([self.stock] if self.stock else [])]:
            if entry["file"] == preset_id:
                name = entry["name"]
                return {"name": name, "xml": self.xmls.get(name, ""), "resource": name}
        return None

    def preset_xml(self, resource: Any) -> str:
        self.calls.append("preset_xml")
        return self.xmls.get(resource, "")

    def preset_dirty(self, preset_id: str) -> bool | None:
        self.calls.append("preset_dirty")
        for entry in [*self.preset_list, *([self.stock] if self.stock else [])]:
            if entry["file"] == preset_id:
                return self.dirty.get(entry["name"], False)
        return None

    def dirty_presets_setting(self) -> str | None:
        return self.setting

    def profiles(self, model: str, depth: str) -> list[str]:
        return list(self.profile_names) if (model, depth) == ("RGBA", "U8") else []

    def palettes(self) -> list[dict[str, str]]:
        return list(self.palette_list)


class MainThread:
    # Stands in for Krita's main thread: it drains the jobs whenever they are woken.
    def __init__(self) -> None:
        self.woken = threading.Event()
        self.stopping = False
        self.bridge: Bridge | None = None
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def wake(self) -> None:
        self.woken.set()

    def is_current(self) -> bool:
        return threading.current_thread() is self.thread

    def _loop(self) -> None:
        while not self.stopping:
            if self.woken.wait(0.05) and self.bridge is not None:
                self.woken.clear()
                self.bridge.drain()
