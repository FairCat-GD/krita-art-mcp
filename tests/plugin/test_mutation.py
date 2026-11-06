import itertools
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, mutation, verification
from bridge_core.errors import BridgeError
from bridge_core.history import LABELS
from bridge_core.jobs import Call
from bridge_core.registry import Registry
from fake_krita import FakePort

A: dict[str, Any] = {"pid": 101, "started_at": "Wed Nov  4 10:00:00 2026"}
CREATE = {
    "name": "sketch",
    "size_px": [8, 4],
    "color_model": "RGBA",
    "depth": "U8",
    "profile_id": documents.SRGB_PROFILE,
    "background": "transparent",
}
ADD = LABELS["layer.create"]


class World:
    # The frame alone, on a created document, with layers as its node steps.
    def __init__(self, tmp: Path) -> None:
        (tmp / "data" / "harness").mkdir(parents=True)
        self.port = FakePort()
        self.registry = Registry(self.port, lambda client: True)
        ops = documents.handlers(self.registry, self.port, tmp / "data")
        created = ops["document.create"](CREATE, Call("op-0", "req-0", A))
        self.handle = self.registry.find(created["document_id"])
        self.document = self.handle.document
        self.root = self.port._tree(self.document.key)["root_id"]
        self.numbers = itertools.count(1)

    def frame(self, labels: tuple[str, ...]) -> mutation.Mutation:
        number = next(self.numbers)
        call = Call(f"op-{number}", f"req-{number}", A)
        return mutation.Mutation(self.port, self.handle, call, "layer.create", labels)

    def add(self, name: str) -> None:
        self.port.create_layer(self.document, self.root, None, "paintlayer", name)

    def added(self, steps: mutation.Steps, name: str) -> None:
        self.add(name)
        steps.push(steps.of(self.port.tree(self.document)))

    def ids(self) -> list[str]:
        return [node["id"] for node in self.port.tree(self.document)["nodes"]]

    def back(self, ids: list[str]) -> Any:
        return lambda: self.ids() == ids


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def _refuses(applied: mutation.Applied) -> None:
    raise BridgeError("LOCKED_TARGET", "Refused after the change.")


def test_two_steps_are_undone_newest_first_and_confirmed(world: World) -> None:
    ids = world.ids()

    def change(steps: mutation.Steps) -> None:
        world.added(steps, "first")
        world.added(steps, "second")

    with pytest.raises(BridgeError) as raised:
        world.frame((ADD, ADD)).run(change, _refuses, world.back(ids))
    details = raised.value.body["details"]
    assert raised.value.body["code"] == "LOCKED_TARGET"
    assert (details["rolled_back"], details["rollback_verified"]) == (True, True)
    assert world.ids() == ids and world.handle.ledger.steps == []
    assert world.port.undo_labels(world.document) == (None, ADD)


def test_a_raise_between_two_steps_undoes_both_and_leaves_history_open_after(
    world: World,
) -> None:
    ids = world.ids()

    def change(steps: mutation.Steps) -> None:
        world.added(steps, "first")
        # Krita holds the second step, and the raise comes before the ledger does.
        world.add("second")
        raise RuntimeError("libkis failed")

    with pytest.raises(BridgeError) as raised:
        world.frame((ADD, ADD)).run(change, back=world.back(ids))
    details = raised.value.body["details"]
    assert (details["rolled_back"], details["rollback_verified"]) == (True, True)
    ledger = world.handle.ledger
    assert world.ids() == ids and ledger.floor == ledger.applied == 0
    # The seal comes after the pushed step is off, so the next op's step can be undone.
    world.frame((ADD,)).run(lambda steps: world.added(steps, "next"))
    assert ledger.undo_available() == 1


def test_a_change_that_takes_other_steps_than_it_names_is_rolled_back(world: World) -> None:
    ids = world.ids()
    with pytest.raises(BridgeError) as raised:
        world.frame((ADD, ADD)).run(lambda steps: world.added(steps, "only"), back=world.back(ids))
    body = raised.value.body
    assert body["code"] == "INTERNAL_ERROR"
    assert (body["details"]["named"], body["details"]["taken"]) == (2, 1)
    assert body["details"]["rollback_verified"] is True and world.ids() == ids


def test_a_rollback_with_no_step_to_move_keeps_the_view_and_reads_no_selection(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection_reads: list[Any] = []
    real = world.port.selection_bounds

    def counted(document: Any) -> Any:
        selection_reads.append(document)
        return real(document)

    monkeypatch.setattr(world.port, "selection_bounds", counted)
    world.port.calls.clear()
    with pytest.raises(BridgeError) as raised:
        world.frame(()).run(lambda steps: None, _refuses)
    assert raised.value.body["details"]["rollback_verified"] is True
    assert "forward" not in world.port.calls and selection_reads == []


def test_one_byte_pixels_are_counted_and_cropped_by_their_channels() -> None:
    rect = {"x": 10, "y": 20, "width": 3, "height": 2}
    old = bytes([0, 0, 0, 0, 0, 0])
    new = bytes([0, 0, 0, 0, 9, 0])
    assert verification.changes(old, new, rect, 1) == (
        1,
        {"x": 11, "y": 21, "width": 1, "height": 1},
    )
    inner = {"x": 11, "y": 20, "width": 2, "height": 2}
    assert verification.crop(bytes(range(6)), rect, inner, 1) == bytes([1, 2, 4, 5])


def test_a_step_krita_holds_above_the_ops_own_is_never_undone(world: World) -> None:
    ids = world.ids()

    def change(steps: mutation.Steps) -> None:
        world.added(steps, "own")
        # Krita then holds a step on top that the ledger never saw.
        world.add("stranger")

    world.port.calls.clear()
    with pytest.raises(BridgeError) as raised:
        world.frame((ADD,)).run(change, _refuses, world.back(ids))
    assert raised.value.body["code"] == "ROLLBACK_FAILED"
    assert "undo" not in world.port.calls and len(world.ids()) == len(ids) + 2


def test_a_rollback_that_fails_seals_history_on_the_unsafe_document(world: World) -> None:
    def change(steps: mutation.Steps) -> None:
        world.added(steps, "own")
        world.add("stranger")

    with pytest.raises(BridgeError) as raised:
        world.frame((ADD,)).run(change, _refuses, world.back(world.ids()))
    assert raised.value.body["details"]["history_sealed"] is True
    assert world.handle.unsafe and world.handle.ledger.undo_available() == 0


def test_a_rollback_says_whether_it_sealed_history(world: World) -> None:
    ids = world.ids()
    with pytest.raises(BridgeError) as pushed:
        world.frame((ADD,)).run(lambda steps: world.added(steps, "own"), _refuses, world.back(ids))
    assert pushed.value.body["details"]["history_sealed"] is False
    # A step named and never pushed may still be on Krita's stack, however still the state.
    with pytest.raises(BridgeError) as unnamed:
        world.frame((ADD,)).run(lambda steps: None, _refuses, world.back(ids))
    details = unnamed.value.body["details"]
    assert details["rollback_verified"] is True and details["history_sealed"] is True


def test_a_protected_mask_s_pixels_are_counted_one_byte_each(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    rect = {"x": 0, "y": 0, "width": 4, "height": 2}
    old, now = bytes(8), bytes([5, 0, 0, 5, 0, 0, 0, 0])
    monkeypatch.setattr(world.port, "layer_rects", lambda document, layer, rects: [now])
    reading: Any = type("Reading", (), {"rects": {"mask": rect}, "rect": rect})()
    frame = world.frame(())
    steps = mutation.Steps(world.port, world.handle, frame.op, "op-x", (), ((), None))
    # Two pixels of a one-byte mask, which four bytes a pixel would read as one.
    assert frame._counted(mutation.Applied(reading, steps), ("mask", old), True) == 2
