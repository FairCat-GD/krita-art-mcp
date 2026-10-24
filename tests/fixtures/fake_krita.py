import copy
import os
import threading
from typing import Any

from bridge_core import documents, history
from bridge_core.bridge import Bridge
from bridge_core.errors import BridgeError

# Krita as the registry sees it, for the plugin-core tests on 3.10 and the server's tool tests.
SPACE = ("RGBA", "U8", documents.SRGB_PROFILE)


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
        # The document whose view is active; a new or opened document comes to the front.
        self.front_key: int | None = None
        # The order of the K46 steps and reads.
        self.calls: list[str] = []
        # One BGRA pixel per layer id; a layer reads as that pixel everywhere.
        self.layer_pixels: dict[str, bytes] = {}
        self.overlay = True
        # A document's composite, by key, in place of bgra(); and hooks run at each read.
        self.canvas: dict[int, bytes] = {}
        self.on_read: list[Any] = []

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
        self.created += 1
        for hook in self.on_create:
            hook()
        return FakeDocument(self._add(name, width, height))

    def open(self, path: str) -> Any:
        for hook in self.on_open:
            hook()
        self._maybe_fail("open")
        spec = self.files.get(path, {})
        width, height = spec.get("size_px", [8, 4])
        key = self._add(os.path.basename(path), width, height)
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
        }

    def tree(self, document: Any) -> dict[str, Any]:
        self._maybe_fail("tree")
        return copy.deepcopy(self._tree(document.key))

    def _tree(self, key: int) -> dict[str, Any]:
        info = self.live[key]
        if "tree" not in info:
            node = fake_node(key, 0, "Layer 1", f"root-{key}", 0)
            info["tree"] = {"root_id": f"root-{key}", "active_id": node["id"], "nodes": [node]}
        tree: dict[str, Any] = info["tree"]
        return tree

    def activate(self, document: Any, node_id: str) -> None:
        # setActiveNode acts on the document in front only.
        self.calls.append("activate")
        if self.front_key == document.key:
            self._tree(document.key)["active_id"] = node_id

    def composite(self, document: Any) -> bytes:
        self._maybe_fail("composite")
        width, height = self.live[document.key]["size_px"]
        return bgra(width, height)

    def selection_bounds(self, document: Any) -> dict[str, int] | None:
        found = self.live[document.key].get("selection")
        return None if found is None else dict(found[0])

    def composite_rects(self, document: Any, rects: list[dict[str, int]]) -> list[bytes]:
        self._maybe_fail("composite")
        for hook in self.on_read:
            hook()
        self.calls.append("read")
        width, height = self.live[document.key]["size_px"]
        canvas = self.canvas.get(document.key) or bgra(width, height)
        return [crop(canvas, width, rect, 4) for rect in rects]

    def layer_rects(self, document: Any, layer_id: str, rects: list[dict[str, int]]) -> list[bytes]:
        self.calls.append("read")
        if layer_id not in {node["id"] for node in self.tree(document)["nodes"]}:
            raise BridgeError("LAYER_NOT_FOUND", "No layer has that id.")
        pixel = self.layer_pixels.get(layer_id, bytes([30, 20, 10, 255]))
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

    def set_selection(self, document: Any, recipe: list[tuple[Any, ...]]) -> None:
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
        return copy.deepcopy((self._tree(key), self.live[key].get("selection")))

    def _restore(self, key: int, state: Any) -> None:
        tree, selection = copy.deepcopy(state)
        self.live[key]["tree"] = tree
        self.live[key]["selection"] = selection

    def _push(self, key: int, label: str, before: Any) -> None:
        info = self.live[key]
        stack = info.setdefault("stack", [])
        del stack[info.get("index", 0) :]
        stack.append({"label": label, "before": before, "after": self._state(key)})
        if len(stack) > self.limit:
            del stack[0]
        info["index"] = len(stack)

    def undo(self, document: Any) -> None:
        self.calls.append("undo")
        info = self.live.get(self.front_key or -1)
        if self.undo_works and info is not None and info.get("index", 0) > 0:
            info["index"] -= 1
            self._restore(self.front_key or -1, info["stack"][info["index"]]["before"])

    def redo(self, document: Any) -> None:
        self.calls.append("redo")
        info = self.live.get(self.front_key or -1)
        if info is not None and info.get("index", 0) < len(info.get("stack", [])):
            self._restore(self.front_key or -1, info["stack"][info["index"]]["after"])
            info["index"] += 1

    def undo_labels(self, document: Any) -> tuple[str | None, str | None]:
        # The actions name the steps of the document in front.
        info = self.live.get(self.front_key or -1, {})
        stack, index = info.get("stack", []), info.get("index", 0)
        undo = stack[index - 1]["label"] if index > 0 else None
        redo = stack[index]["label"] if index < len(stack) else None
        return undo, redo

    def undo_actions(self, document: Any) -> dict[str, Any]:
        undo, redo = self.undo_labels(document)
        return {
            "undo": {"text": f"Undo {undo or ''}", "enabled": undo is not None},
            "redo": {"text": f"Redo {redo or ''}", "enabled": redo is not None},
        }

    def undo_limit(self) -> int:
        return self.limit

    def label_timing(self, document: Any, trials: int) -> list[list[str | None]]:
        root = self._tree(document.key)["root_id"]
        reads = []
        for trial in range(trials):
            self.create_layer(document, root, None, "paintlayer", f"timing {trial}")
            reads.append([None, self.undo_labels(document)[0]])
        return reads

    def export_kra(self, document: Any, target: str) -> bool:
        if self.export_works:
            with open(target, "wb") as stream:
                stream.write(b"a KRA, as far as the tests care")
        return self.export_works

    def _maybe_fail(self, step: str) -> None:
        failure = self.fail.get(step)
        if failure is not None:
            raise failure

    def layers(self, document: Any) -> tuple[str, list[dict[str, Any]]]:
        return f"root-{document.key}", [{"id": f"layer-{document.key}", **self.layer}]

    def close(self, document: Any, settle_s: float = 0.0) -> bool:
        self.closed.append(document.key)
        self.settled.append(settle_s)
        if self.close_works:
            del self.live[document.key]
        return True


def _whole(width: int, height: int) -> dict[str, int]:
    return {"x": 0, "y": 0, "width": width, "height": height}


def _combine(mode: str, current: bytes | None, shape: bytearray) -> bytearray:
    if mode == "replace" or current is None:
        return shape
    if mode == "add":
        return bytearray(max(a, b) for a, b in zip(current, shape, strict=True))
    if mode == "subtract":
        return bytearray(min(a, 255 - b) for a, b in zip(current, shape, strict=True))
    return bytearray(min(a, b) for a, b in zip(current, shape, strict=True))


def crop(canvas: bytes, width: int, rect: dict[str, int], depth: int) -> bytes:
    rows = (
        canvas[((rect["y"] + row) * width + rect["x"]) * depth :][: rect["width"] * depth]
        for row in range(rect["height"])
    )
    return b"".join(rows)


PRESET_XML = (
    '<Preset paintopid="paintbrush" name="Basic Round">'
    '<param type="string" name="EraserMode">false</param></Preset>'
)


class FakeResources:
    # Krita's resources as resource.list sees them.
    def __init__(self) -> None:
        self.preset_list = [
            {"name": "Basic Round", "file": "basic-round.kpp"},
            {"name": "Soft Airbrush", "file": "airbrush-soft.kpp"},
            {"name": "Broken", "file": "broken.kpp"},
        ]
        self.xmls = {
            "Basic Round": PRESET_XML,
            "Soft Airbrush": '<Preset name="Soft Airbrush" paintopid="airbrush"/>',
            "Broken": "",
        }
        self.profile_names = ["sRGB-elle-V2-srgbtrc.icc", "sRGB built-in"]
        self.palette_list = [{"name": "Default", "file": "default.kpl"}]
        self.asked: list[list[str]] = []

    def presets(self) -> list[dict[str, str]]:
        return list(self.preset_list)

    def preset_xmls(self, names: list[str]) -> dict[str, str]:
        self.asked.append(list(names))
        return {name: self.xmls.get(name, "") for name in names}

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
