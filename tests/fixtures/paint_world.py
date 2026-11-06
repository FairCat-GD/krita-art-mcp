import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, harness, history, painting
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call
from bridge_core.registry import Handle, Registry
from fake_krita import FakePort, FakeResources, fake_node, layer_id

# The plugin painting tests' world: a document with a protected base, an editable paint layer,
# a protected layer far right and a group, over the fake Krita.

A: dict[str, Any] = {"pid": 101, "started_at": "Sun Oct 25 10:00:00 2026"}
WIDTH, HEIGHT = 200, 120
CREATE = {
    "name": "sketch",
    "size_px": [WIDTH, HEIGHT],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
BASE, PAINT, FAR, GROUP = (layer_id(1, index) for index in range(4))
BASE_PIXEL = bytes([9, 8, 7, 255])
# Orange at full opacity, as the fake paints it: B, G, R, A.
ORANGE = bytes([0, 128, 255, 255])
LABEL = history.LABELS["paint.stroke"]
# The fill tests' shape: a rect on the paint layer.
RECT: dict[str, Any] = {"kind": "rect", "rect": {"x": 40, "y": 50, "width": 20, "height": 10}}


def box(x: int, y: int, width: int, height: int) -> dict[str, int]:
    return {"x": x, "y": y, "width": width, "height": height}


class World:
    def __init__(self, tmp: Path) -> None:
        self.data = tmp / "data"
        (self.data / "harness").mkdir(parents=True)
        (tmp / "art").mkdir()
        roots = {"v": 1, "roots": [os.path.realpath(tmp / "art")]}
        (self.data / "config.json").write_text(json.dumps(roots))
        self.port = FakePort()
        self.resources = FakeResources()
        self.resources.add_stroke_presets()
        self.port.resources = self.resources
        self.registry = Registry(self.port, lambda client: True)
        self.ops = {
            **documents.handlers(self.registry, self.port, self.data),
            **harness.handlers(self.registry, self.port, self.data, self.resources),
            **painting.handlers(self.registry, self.port, self.resources, self.data),
        }
        self.ids = itertools.count(1)
        # Each layer read, as (layer id, rect).
        self.layer_reads: list[tuple[str, dict[str, int]]] = []
        reads = self.port.layer_rects

        def logged(document: Any, layer: str, rects: list[dict[str, int]]) -> list[bytes]:
            self.layer_reads += [(layer, dict(rect)) for rect in rects]
            return reads(document, layer, rects)

        self.port.layer_rects = logged  # type: ignore[assignment]

    def run(self, op: str, args: dict[str, Any], request_id: str = "") -> dict[str, Any]:
        number = next(self.ids)
        call = Call(f"op-{number:032x}", request_id or f"req-{number}", A)
        return self.ops[op](args, call)

    def refused(self, op: str, args: dict[str, Any], request_id: str = "") -> dict[str, Any]:
        with pytest.raises(BridgeError) as raised:
            self.run(op, args, request_id)
        body: dict[str, Any] = raised.value.body
        return body

    def document(self) -> tuple[str, Handle]:
        # A protected base under the whole canvas, an empty editable paint layer, a protected
        # layer far to the right, and an empty group.
        document_id = self.run("document.create", CREATE)["document_id"]
        handle = self.registry.find(document_id)
        tree = self.port._tree(1)
        root = tree["root_id"]
        tree["nodes"] = [
            fake_node(1, 0, "base", root, 0, bounds_px=box(0, 0, WIDTH, HEIGHT)),
            fake_node(1, 1, "paint", root, 1),
            fake_node(1, 2, "far", root, 2, bounds_px=box(180, 0, 20, 10)),
            fake_node(1, 3, "group", root, 3, type="grouplayer"),
        ]
        tree["active_id"] = PAINT
        handle.protected = {BASE, FAR}
        self.port.paintable(1)
        self.port.buffers[BASE] = bytearray(BASE_PIXEL * (WIDTH * HEIGHT))
        return document_id, handle

    def args(self, document_id: str, **changes: Any) -> dict[str, Any]:
        brush = {
            "preset_id": "basic-round.kpp",
            "preset_sha256": None,
            "size_px": 10,
            "opacity": 1,
            "flow": 1,
            "color": [1, 0.5, 0, 1],
            "mask": None,
            "eraser": False,
            "blend_mode": "normal",
            "alpha_lock": False,
            "rotation_deg": 0,
            **changes.pop("brush", {}),
        }
        found = {
            "document_id": document_id,
            "layer_id": PAINT,
            "verify": "region",
            "accepted_points": 2,
            "brush": brush,
            "path": {"start": [40, 60], "segments": [[50, 60]]},
            "dynamics": None,
        }
        found.update(changes)
        return found

    def stroke(self, document_id: str, request_id: str = "", **changes: Any) -> dict[str, Any]:
        return self.run("paint.stroke", self.args(document_id, **changes), request_id)

    def stroke_refused(self, document_id: str, **changes: Any) -> dict[str, Any]:
        return self.refused("paint.stroke", self.args(document_id, **changes))

    def pixels(self, layer: str, rect: dict[str, int]) -> bytes:
        handle = self.registry.sync()[0]
        [found] = FakePort.layer_rects(self.port, handle.document, layer, [rect])
        return found

    def history(self, document_id: str, action: str, steps: int = 1) -> dict[str, Any]:
        args = {"document_id": document_id, "action": action, "steps": steps}
        return self.run("history.step", args)

    def history_refused(self, document_id: str, action: str) -> dict[str, Any]:
        args = {"document_id": document_id, "action": action, "steps": 1}
        return self.refused("history.step", args)

    def allow(self, document_id: str, rect: dict[str, int], preserve: bool = False) -> None:
        handle = self.registry.find(document_id)
        request_id = f"req-protect-{next(self.ids)}"
        data = b"\xff" * (rect["width"] * rect["height"])
        folder = self.data / "transfer"
        folder.mkdir(exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()
        key = hashlib.sha256(request_id.encode()).hexdigest()[:16]
        path = folder / f"mask-{key}-{digest}.a8"
        path.write_bytes(data)
        spec = {
            "path": str(path),
            "size_px": [rect["width"], rect["height"]],
            "format": "A8",
            "sha256": digest,
        }
        args = {
            "document_id": document_id,
            "protected_layer_ids": sorted(handle.protected),
            "allowed_change_mask": {
                "origin_px": [rect["x"], rect["y"]],
                "mask": spec,
                "source_path": None,
            },
            "preserve_composite_alpha": preserve,
            "preserve_canvas": False,
        }
        self.run("protection.set", args, request_id)

    def harness_document(self) -> tuple[str, Handle]:
        source = self.data / "harness" / "fixture.ora"
        source.write_bytes(b"ora")
        args = {
            "source_path": str(source),
            "source_sha256": hashlib.sha256(b"ora").hexdigest(),
            "mode": "working_copy",
            "working_dir": str(self.data / "harness" / "work"),
            "editable_layer_ids": None,
            "editable_layer_names": None,
        }
        (self.data / "harness" / "work").mkdir()
        document_id = str(self.run("document.open", args)["document_id"])
        handle = self.registry.find(document_id)
        handle.protected = set()
        self.port.live[1]["size_px"] = [WIDTH, HEIGHT]
        tree = self.port._tree(1)
        tree["nodes"] = [fake_node(1, 1, "paint", tree["root_id"], 0)]
        self.port.paintable(1)
        return document_id, handle


def fill_args(document_id: str, **changes: Any) -> dict[str, Any]:
    style = {
        "color": [1, 0.5, 0, 1],
        "mask": None,
        "opacity": 1,
        "blend_mode": "normal",
        "alpha_lock": False,
        **changes.pop("fill", {}),
    }
    found = {
        "document_id": document_id,
        "layer_id": PAINT,
        "verify": "region",
        "shape": copy.deepcopy(RECT),
        "fill": style,
    }
    found.update(changes)
    return found
