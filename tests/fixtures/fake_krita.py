import os
import threading
from typing import Any

from bridge_core import documents
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
        self.created = 0
        self.on_create: list[Any] = []
        # What a file opens as, by path: size_px, space, names (top-level layers), selection,
        # active_mask. Anything else opens as an 8 x 4 document with one layer.
        self.files: dict[str, dict[str, Any]] = {}
        self.opened: list[str] = []
        self.on_open: list[Any] = []
        self.fail: dict[str, BaseException] = {}
        self.prepared: list[int] = []
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
            active_mask=spec.get("active_mask", False),
        )
        self.opened.append(path)
        return FakeDocument(key)

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
        }

    def tree(self, document: Any) -> dict[str, Any]:
        self._maybe_fail("tree")
        info = self.live[document.key]
        if "tree" in info:
            tree: dict[str, Any] = info["tree"]
            return tree
        key = document.key
        node = fake_node(key, 0, "Layer 1", f"root-{key}", 0)
        return {"root_id": f"root-{key}", "active_id": node["id"], "nodes": [node]}

    def prepare_read(self, document: Any) -> None:
        self.live[document.key]["active_mask"] = False
        self.prepared.append(document.key)
        self.calls.append("prepare")

    def composite(self, document: Any) -> bytes:
        self._maybe_fail("composite")
        width, height = self.live[document.key]["size_px"]
        return bgra(width, height)

    def selection(self, document: Any) -> tuple[dict[str, int], bytes] | None:
        found: tuple[dict[str, int], bytes] | None = self.live[document.key].get("selection")
        return found

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

    def mask_active(self, document: Any) -> bool:
        return bool(self.live[document.key].get("active_mask"))

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
        self.live[document.key]["active_mask"] = True
        return self.overlay

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

    def close(self, document: Any) -> bool:
        self.closed.append(document.key)
        if self.close_works:
            del self.live[document.key]
        return True


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
