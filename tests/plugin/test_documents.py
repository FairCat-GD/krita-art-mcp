import os
import re
from pathlib import Path
from typing import Any

import pytest
from bridge_core import documents, processes, registry
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call, Handler
from bridge_core.registry import Handle, Registry
from fake_krita import FakePort

A: dict[str, Any] = {"pid": 101, "started_at": "Sat Oct 24 10:00:00 2026"}
B: dict[str, Any] = {"pid": 202, "started_at": "Sat Oct 24 10:05:00 2026"}


class World:
    def __init__(self, data: Path) -> None:
        self.data = data
        self.port = FakePort()
        self.alive: dict[int, bool] = {}
        self.asked: list[int] = []
        self.registry = Registry(self.port, self._holder_alive)
        self.ops = documents.handlers(self.registry, self.port, data)

    def _holder_alive(self, client: dict[str, Any]) -> bool:
        self.asked.append(client["pid"])
        return self.alive.get(client["pid"], True)

    def run(self, op: str, args: dict[str, Any], client: dict[str, Any] = A) -> dict[str, Any]:
        return self.ops[op](args, Call("op-x", "req-x", client))

    def create(self, client: dict[str, Any] = A, **changes: Any) -> dict[str, Any]:
        args = {
            "name": "sketch",
            "size_px": [64, 32],
            "color_model": "RGBA",
            "depth": "U8",
            "profile_id": documents.SRGB_PROFILE,
            "background": "transparent",
            **changes,
        }
        return self.run("document.create", args, client)

    def close(self, document_id: str, policy: str = "refuse", client: dict[str, Any] = A) -> Any:
        return self.run(
            "document.close", {"document_id": document_id, "dirty_policy": policy}, client
        )

    def listed(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = self.run("document.list", {})["documents"]
        return entries


def _code(world: World, call: Any, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(BridgeError) as raised:
        call(*args, **kwargs)
    return str(raised.value.body["code"])


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_a_created_document_is_new_clean_and_listed(world: World) -> None:
    created = world.create()
    assert re.fullmatch(r"doc-[0-9a-f]{12}", created["document_id"])
    assert created == {
        "document_id": created["document_id"],
        "canvas_px": [64, 32],
        "root_layer_id": "root-1",
        "initial_layer_id": "layer-1",
        "profile_id": documents.SRGB_PROFILE,
        "mode": "new",
    }
    assert world.listed() == [
        {
            "document_id": created["document_id"],
            "name": "sketch",
            "path": None,
            "size_px": [64, 32],
            "color_model": "RGBA",
            "depth": "U8",
            "profile_id": documents.SRGB_PROFILE,
            "dirty": False,
            "mode": "new",
        }
    ]


def test_ids_are_never_reused(world: World) -> None:
    ids = {world.create()["document_id"] for _ in range(20)}
    assert len(ids) == 20


def test_documents_opened_by_hand_are_read_only_with_a_stable_id(world: World) -> None:
    world.port.open_by_hand("owner-art")
    first = world.listed()
    assert [(entry["mode"], entry["path"]) for entry in first] == [
        ("read_only", "/owner/owner-art.kra")
    ]
    assert world.listed() == first


def test_a_document_the_owner_opened_is_never_closed(world: World) -> None:
    world.port.open_by_hand("owner-art")
    owner_id = world.listed()[0]["document_id"]
    for policy in ("refuse", "discard"):
        assert _code(world, world.close, owner_id, policy) == "DOCUMENT_READ_ONLY"
    assert world.port.closed == []


def test_a_document_closed_by_hand_is_not_found(world: World) -> None:
    created = world.create()
    world.port.live.clear()
    assert _code(world, world.close, created["document_id"]) == "DOCUMENT_NOT_FOUND"
    assert world.listed() == []


def test_close_ends_the_document_and_its_id(world: World) -> None:
    created = world.create()
    assert world.close(created["document_id"]) == {
        "document_id": created["document_id"],
        "closed": True,
        "baseline_untouched": None,
        "baseline_id": None,
    }
    assert world.port.closed == [1]
    assert world.listed() == []
    assert _code(world, world.close, created["document_id"]) == "DOCUMENT_NOT_FOUND"


def test_a_close_krita_did_not_carry_out_is_an_error(world: World) -> None:
    created = world.create()
    world.port.close_works = False
    assert _code(world, world.close, created["document_id"]) == "INTERNAL_ERROR"
    assert [entry["document_id"] for entry in world.listed()] == [created["document_id"]]


def test_the_lease_refuses_another_live_server_process(world: World) -> None:
    created = world.create(client=A)
    assert _code(world, world.close, created["document_id"], "discard", B) == "DOCUMENT_IN_USE"
    assert world.port.closed == []
    # Reads stay open to everyone.
    assert [entry["document_id"] for entry in world.run("document.list", {}, B)["documents"]] == [
        created["document_id"]
    ]


def test_the_lease_passes_on_once_its_holder_has_exited(world: World) -> None:
    created = world.create(client=A)
    world.alive[A["pid"]] = False
    world.close(created["document_id"], "discard", B)
    assert world.port.closed == [1]


def test_the_holder_is_never_asked_about_its_own_calls(world: World) -> None:
    created = world.create(client=A)
    world.close(created["document_id"], client=dict(A))
    assert world.asked == []


def test_a_restarted_server_with_the_same_pid_is_another_process(world: World) -> None:
    created = world.create(client=A)
    restarted = {"pid": A["pid"], "started_at": "Sat Oct 24 11:00:00 2026"}
    world.alive[A["pid"]] = False
    world.close(created["document_id"], client=restarted)
    assert world.asked == [A["pid"]]


def _guarded(world: World, **options: Any) -> Handler:
    # A mutation as every handler makes one: refusals first, then dirty, then Krita.
    def paint(handle: Handle, args: dict[str, Any], call: Call) -> dict[str, Any]:
        if args.get("refuse"):
            raise BridgeError("LOCKED_TARGET", "Protected.")
        if args.get("active_only"):
            return {"painted": None}
        handle.before_change()
        if args.get("raise_after"):
            raise RuntimeError("libkis failed after the change")
        return {"painted": handle.document_id}

    return world.registry.guarded(paint, **options)


def test_a_successful_mutation_dirties_and_close_then_refuses(world: World) -> None:
    created = world.create()
    paint = _guarded(world)
    paint({"document_id": created["document_id"]}, Call("op", "req", A))
    assert world.listed()[0]["dirty"] is True
    assert _code(world, world.close, created["document_id"], "refuse") == "DOCUMENT_DIRTY"
    world.close(created["document_id"], "discard")
    assert world.port.closed == [1]


def test_a_change_is_announced_once_on_its_own_document(world: World) -> None:
    first = world.create()
    world.create()
    _guarded(world)({"document_id": first["document_id"]}, Call("op", "req", A))
    assert [key for key, _ in world.port.announced] == [1]


def test_a_refused_call_a_call_that_changes_nothing_and_a_close_announce_nothing(
    world: World,
) -> None:
    created = world.create()
    handle = world.registry.add(world.port.create("fixture", 8, 8), registry.READ_ONLY, A)
    paint = _guarded(world)
    call = Call("op", "req", A)
    with pytest.raises(BridgeError):
        paint({"document_id": handle.document_id}, call)
    with pytest.raises(BridgeError):
        paint({"document_id": created["document_id"], "refuse": True}, call)
    paint({"document_id": created["document_id"], "active_only": True}, call)
    world.close(created["document_id"])
    assert world.port.announced == []


def test_a_refusal_before_the_mutation_or_a_call_that_changes_nothing_leaves_it_clean(
    world: World,
) -> None:
    created = world.create()
    paint = _guarded(world)
    call = Call("op", "req", A)
    with pytest.raises(BridgeError):
        paint({"document_id": created["document_id"], "refuse": True}, call)
    paint({"document_id": created["document_id"], "active_only": True}, call)
    assert world.listed()[0]["dirty"] is False


def test_a_mutation_that_raises_after_its_change_leaves_it_dirty(world: World) -> None:
    created = world.create()
    with pytest.raises(RuntimeError):
        _guarded(world)(
            {"document_id": created["document_id"], "raise_after": True}, Call("op", "req", A)
        )
    assert world.listed()[0]["dirty"] is True
    assert _code(world, world.close, created["document_id"], "refuse") == "DOCUMENT_DIRTY"


def test_an_unsafe_document_refuses_mutations_but_still_closes(world: World) -> None:
    created = world.create()
    world.registry.find(created["document_id"]).unsafe = True
    paint = _guarded(world)
    with pytest.raises(BridgeError) as raised:
        paint({"document_id": created["document_id"]}, Call("op", "req", A))
    assert raised.value.body["code"] == "DOCUMENT_UNSAFE"
    world.close(created["document_id"])
    assert world.port.closed == [1]


def test_a_read_only_open_refuses_writes_but_closes(world: World) -> None:
    handle = world.registry.add(world.port.create("fixture", 8, 8), registry.READ_ONLY, A)
    paint = _guarded(world)
    with pytest.raises(BridgeError) as raised:
        paint({"document_id": handle.document_id}, Call("op", "req", A))
    assert raised.value.body["code"] == "DOCUMENT_READ_ONLY"
    world.close(handle.document_id)
    assert world.listed() == []


@pytest.mark.parametrize("code", ["KRITA_MODAL_DIALOG", "MULTIPLE_WINDOWS"])
def test_a_dialog_or_a_second_window_refuses_at_job_start(world: World, code: str) -> None:
    created = world.create()
    world.port.refuse = BridgeError(code, "refused", True)
    assert _code(world, world.create) == code
    assert _code(world, world.close, created["document_id"]) == code
    assert len(world.port.live) == 1
    assert len(world.listed()) == 1


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"depth": "U16"}, "UNSUPPORTED_CAPABILITY"),
        ({"profile_id": "sRGB-elle-V2-g10.icc"}, "UNSUPPORTED_CAPABILITY"),
        ({"color_model": "GRAYA"}, "UNSUPPORTED_CAPABILITY"),
        ({"size_px": [0, 8]}, "INVALID_ARGUMENT"),
        ({"size_px": [True, 8]}, "INVALID_ARGUMENT"),
        ({"name": ""}, "INVALID_ARGUMENT"),
        ({"project_id": "p"}, "INVALID_ARGUMENT"),
    ],
)
def test_create_refuses_what_phase_1_cannot_make(
    world: World, changes: dict[str, Any], code: str
) -> None:
    assert _code(world, world.create, **changes) == code
    assert world.port.live == {}


@pytest.mark.parametrize(
    "broken",
    [
        {"space": ("RGBA", "U8", "sRGB-elle-V2-g10.icc")},
        {"layer": {"type": "paintlayer", "opacity": 255, "active": True, "alpha_at_origin": 255}},
        {"layer": {"type": "paintlayer", "opacity": 0, "active": True, "alpha_at_origin": 0}},
        {"layer": {"type": "paintlayer", "opacity": 255, "active": False, "alpha_at_origin": 0}},
    ],
)
def test_a_document_krita_made_wrong_is_closed_in_the_same_job(
    world: World, broken: dict[str, Any]
) -> None:
    for name, value in broken.items():
        setattr(world.port, name, value)
    assert _code(world, world.create) == "INTERNAL_ERROR"
    assert world.port.live == {}
    assert world.port.closed == [1]
    assert world.listed() == []


def test_list_takes_no_arguments(world: World) -> None:
    assert _code(world, world.run, "document.list", {"all": True}) == "INVALID_ARGUMENT"


def test_close_takes_refuse_or_discard_only(world: World) -> None:
    created = world.create()
    assert _code(world, world.close, created["document_id"], "keep") == "INVALID_ARGUMENT"


def _own_start_time() -> str:
    started = processes.ps("-p", str(os.getpid()), "-o", "lstart=")
    assert started
    return started


def test_a_live_holder_is_alive() -> None:
    assert processes.holder_alive({"pid": os.getpid(), "started_at": _own_start_time()})


def test_a_holder_whose_pid_now_belongs_to_a_later_process_is_gone() -> None:
    holder = {"pid": os.getpid(), "started_at": "Thu Jan  1 00:00:00 1970"}
    assert not processes.holder_alive(holder)


def test_a_holder_whose_pid_is_gone_is_gone() -> None:
    assert not processes.holder_alive({"pid": 2**22 + 12345, "started_at": "x"})


def test_a_holder_ps_cannot_answer_for_keeps_the_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(processes, "ps", lambda *args: None)
    assert processes.holder_alive({"pid": os.getpid(), "started_at": "x"})
