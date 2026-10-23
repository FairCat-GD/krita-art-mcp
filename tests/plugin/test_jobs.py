import logging
import threading
import time
from typing import Any

import pytest
from bridge_core.errors import BridgeError
from bridge_core.jobs import Handler, Jobs

CLIENT = {"pid": 1, "started_at": "test"}


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _jobs(
    handlers: dict[str, Handler], on_main_thread: bool = True
) -> tuple[Jobs, list[str], _Records]:
    wakes: list[str] = []
    records = _Records()
    log = logging.getLogger("test_jobs")
    log.handlers = [records]
    log.propagate = False
    jobs = Jobs(handlers, lambda: wakes.append("wake"), lambda: on_main_thread, log)
    return jobs, wakes, records


def _submit(jobs: Jobs, operation_id: str, op: str = "record") -> None:
    assert jobs.submit(operation_id, f"req-{operation_id}", op, {"id": operation_id}, CLIENT)


def test_jobs_run_in_the_order_they_arrive() -> None:
    ran: list[str] = []

    def record(args: dict[str, Any]) -> dict[str, Any]:
        ran.append(args["id"])
        return {"ran": args["id"]}

    jobs, wakes, _ = _jobs({"record": record})
    for operation_id in ("a", "b", "c"):
        _submit(jobs, operation_id)
    jobs.drain()
    assert ran == ["a", "b", "c"]
    assert wakes == ["wake"] * 3
    assert jobs.wait("b", 0) == {
        "status": "done",
        "operation_id": "b",
        "request_id": "req-b",
        "result": {"ran": "b"},
    }


def test_a_reentered_drain_returns_at_once_and_the_next_job_waits_its_turn() -> None:
    events: list[str] = []
    jobs: Jobs

    def outer(args: dict[str, Any]) -> dict[str, Any]:
        events.append("outer starts")
        # A nested event loop inside waitForDone delivers the queued wake signal here.
        jobs.drain()
        events.append("outer ends")
        return {}

    def inner(args: dict[str, Any]) -> dict[str, Any]:
        events.append("inner runs")
        return {}

    jobs, _, _ = _jobs({"outer": outer, "inner": inner})
    _submit(jobs, "1", "outer")
    _submit(jobs, "2", "inner")
    jobs.drain()
    assert events == ["outer starts", "outer ends", "inner runs"]


def test_cancel_affects_queued_jobs_only() -> None:
    outcomes: dict[str, Any] = {}
    jobs: Jobs

    def running(args: dict[str, Any]) -> dict[str, Any]:
        outcomes["while running"] = jobs.cancel("running")
        return {"finished": True}

    jobs, _, _ = _jobs({"running": running, "record": lambda args: {}})
    _submit(jobs, "running", "running")
    _submit(jobs, "queued")
    reply, cancelled = jobs.cancel("queued") or ({}, None)
    assert cancelled is True
    assert reply["status"] == "error"
    assert reply["error"]["code"] == "CANCELLED"
    jobs.drain()
    assert outcomes["while running"][1] is False
    assert outcomes["while running"][0]["status"] == "running"
    assert jobs.cancel("running") == (
        {
            "status": "done",
            "operation_id": "running",
            "request_id": "req-running",
            "result": {"finished": True},
        },
        False,
    )
    assert jobs.cancel("unknown") is None


def test_stop_cancels_queued_jobs_wakes_waiters_and_refuses_new_ones() -> None:
    jobs, _, _ = _jobs({"record": lambda args: {}})
    _submit(jobs, "queued")
    replies: list[dict[str, Any] | None] = []
    waiter = threading.Thread(target=lambda: replies.append(jobs.wait("queued", 5)))
    waiter.start()
    time.sleep(0.05)
    started = time.monotonic()
    jobs.stop()
    waiter.join(5)
    assert time.monotonic() - started < 1
    assert replies[0] is not None and replies[0]["error"]["code"] == "CANCELLED"
    assert jobs.submit("late", "req-late", "record", {}, CLIENT) is None
    assert jobs.accepting is False


def test_drain_refuses_to_run_off_the_main_thread() -> None:
    ran: list[str] = []

    def record(args: dict[str, Any]) -> dict[str, Any]:
        ran.append("ran")
        return {}

    jobs, _, _ = _jobs({"record": record}, on_main_thread=False)
    _submit(jobs, "a")
    with pytest.raises(RuntimeError):
        jobs.drain()
    assert ran == []
    assert jobs.wait("a", 0) == {"status": "queued", "operation_id": "a", "request_id": "req-a"}


def test_a_raising_handler_becomes_internal_error_with_its_traceback_logged() -> None:
    def boom(args: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("kaboom")

    def typed(args: dict[str, Any]) -> dict[str, Any]:
        raise BridgeError("BUSY", "Try again.", True, {"why": "test"})

    jobs, _, records = _jobs({"boom": boom, "typed": typed})
    _submit(jobs, "a", "boom")
    _submit(jobs, "b", "typed")
    jobs.drain()
    reply = jobs.wait("a", 0)
    assert reply is not None and reply["error"]["code"] == "INTERNAL_ERROR"
    assert any("kaboom" in message for message in records.messages)
    typed_reply = jobs.wait("b", 0)
    assert typed_reply is not None
    assert typed_reply["error"] == {
        "code": "BUSY",
        "message": "Try again.",
        "retryable": True,
        "details": {"why": "test"},
    }


def test_an_unknown_op_fails_at_once_without_queueing() -> None:
    jobs, wakes, _ = _jobs({})
    _submit(jobs, "a", "paint_everything")
    assert wakes == []
    reply = jobs.wait("a", 0)
    assert reply is not None and reply["error"]["code"] == "INVALID_ARGUMENT"


def test_a_resent_operation_id_returns_the_same_operation() -> None:
    ran: list[str] = []

    def record(args: dict[str, Any]) -> dict[str, Any]:
        ran.append("ran")
        return {}

    jobs, _, _ = _jobs({"record": record})
    _submit(jobs, "a")
    _submit(jobs, "a")
    jobs.drain()
    assert ran == ["ran"]
