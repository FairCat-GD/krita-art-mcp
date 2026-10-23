import logging
import threading
import time
from typing import Any

import pytest
from bridge_core.errors import BridgeError
from bridge_core.jobs import Call, Handler, Jobs

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

    def record(args: dict[str, Any], call: Call) -> dict[str, Any]:
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
        "op": "record",
        "result": {"ran": "b"},
    }


def test_a_reentered_drain_returns_at_once_and_the_next_job_waits_its_turn() -> None:
    events: list[str] = []
    jobs: Jobs

    def outer(args: dict[str, Any], call: Call) -> dict[str, Any]:
        events.append("outer starts")
        # A nested event loop inside waitForDone delivers the queued wake signal here.
        jobs.drain()
        events.append("outer ends")
        return {}

    def inner(args: dict[str, Any], call: Call) -> dict[str, Any]:
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

    def running(args: dict[str, Any], call: Call) -> dict[str, Any]:
        outcomes["while running"] = jobs.cancel("running")
        return {"finished": True}

    jobs, _, _ = _jobs({"running": running, "record": lambda args, call: {}})
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
            "op": "running",
            "result": {"finished": True},
        },
        False,
    )
    assert jobs.cancel("unknown") is None


def test_stop_cancels_queued_jobs_wakes_waiters_and_refuses_new_ones() -> None:
    jobs, _, _ = _jobs({"record": lambda args, call: {}})
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

    def record(args: dict[str, Any], call: Call) -> dict[str, Any]:
        ran.append("ran")
        return {}

    jobs, _, _ = _jobs({"record": record}, on_main_thread=False)
    _submit(jobs, "a")
    with pytest.raises(RuntimeError):
        jobs.drain()
    assert ran == []
    assert jobs.wait("a", 0) == {
        "status": "queued",
        "operation_id": "a",
        "request_id": "req-a",
        "op": "record",
    }


def test_a_raising_handler_becomes_internal_error_with_its_traceback_logged() -> None:
    def boom(args: dict[str, Any], call: Call) -> dict[str, Any]:
        raise ValueError("kaboom")

    def typed(args: dict[str, Any], call: Call) -> dict[str, Any]:
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

    def record(args: dict[str, Any], call: Call) -> dict[str, Any]:
        ran.append("ran")
        return {}

    jobs, _, _ = _jobs({"record": record})
    _submit(jobs, "a")
    _submit(jobs, "a")
    jobs.drain()
    assert ran == ["ran"]


def _counting() -> tuple[Jobs, list[dict[str, Any]]]:
    ran: list[dict[str, Any]] = []

    def record(args: dict[str, Any], call: Call) -> dict[str, Any]:
        ran.append(args)
        return {"ran": len(ran)}

    jobs, _, _ = _jobs({"record": record})
    return jobs, ran


def test_a_retried_request_id_returns_the_original_operation_without_running_again() -> None:
    jobs, ran = _counting()
    first = jobs.submit("op-1", "req-1", "record", {"x": 1}, CLIENT)
    jobs.drain()
    retry = jobs.submit("op-2", "req-1", "record", {"x": 1}, {"pid": 2, "started_at": "other"})
    jobs.drain()
    assert first is not None and retry is first
    assert len(ran) == 1
    assert retry.reply()["operation_id"] == "op-1"


def test_a_retry_while_queued_follows_the_same_operation() -> None:
    jobs, ran = _counting()
    jobs.submit("op-1", "req-1", "record", {"x": 1}, CLIENT)
    jobs.submit("op-2", "req-1", "record", {"x": 1}, CLIENT)
    jobs.drain()
    assert len(ran) == 1


def test_a_retrys_own_operation_id_finds_the_original_when_its_reply_was_lost() -> None:
    jobs, _ = _counting()
    jobs.submit("op-1", "req-1", "record", {"x": 1}, CLIENT)
    jobs.submit("op-2", "req-1", "record", {"x": 1}, CLIENT)
    jobs.drain()
    reply = jobs.wait("op-2", 0)
    assert reply is not None
    assert (reply["status"], reply["operation_id"]) == ("done", "op-1")


def test_a_request_id_with_other_arguments_conflicts() -> None:
    jobs, ran = _counting()
    jobs.submit("op-1", "req-1", "record", {"x": 1}, CLIENT)
    for op_id, op, args in (("op-2", "record", {"x": 2}), ("op-3", "other", {"x": 1})):
        conflict = jobs.submit(op_id, "req-1", op, args, CLIENT)
        assert conflict is not None
        assert conflict.reply()["error"]["code"] == "REQUEST_ID_CONFLICT"
        assert jobs.wait(op_id, 0) == conflict.reply()
    jobs.drain()
    assert ran == [{"x": 1}]


def test_the_argument_hash_ignores_key_order() -> None:
    jobs, _ = _counting()
    jobs.submit("op-1", "req-1", "record", {"a": 1, "b": [1, 2]}, CLIENT)
    retry = jobs.submit("op-2", "req-1", "record", {"b": [1, 2], "a": 1}, CLIENT)
    assert retry is not None and retry.operation_id == "op-1"


def test_a_retryable_failure_releases_its_request_id_but_keeps_the_arguments_bound() -> None:
    attempts: list[str] = []

    def refused_once(args: dict[str, Any], call: Call) -> dict[str, Any]:
        attempts.append(call.operation_id)
        if len(attempts) == 1:
            raise BridgeError("KRITA_MODAL_DIALOG", "A dialog is open.", True)
        return {"ran": True}

    jobs, _, _ = _jobs({"record": refused_once})
    jobs.submit("op-1", "req-1", "record", {"x": 1}, CLIENT)
    jobs.drain()
    early = jobs.submit("op-0", "req-1", "record", {"x": 2}, CLIENT)
    assert early is not None and early.reply()["error"]["code"] == "REQUEST_ID_CONFLICT"
    retry = jobs.submit("op-2", "req-1", "record", {"x": 1}, CLIENT)
    jobs.drain()
    assert attempts == ["op-1", "op-2"]
    assert retry is not None and retry.reply()["status"] == "done"
    other = jobs.submit("op-3", "req-1", "record", {"x": 2}, CLIENT)
    assert other is not None and other.reply()["error"]["code"] == "REQUEST_ID_CONFLICT"


def test_a_non_retryable_failure_is_the_receipt_for_its_request_id() -> None:
    attempts: list[str] = []

    def refused(args: dict[str, Any], call: Call) -> dict[str, Any]:
        attempts.append(call.operation_id)
        raise BridgeError("DOCUMENT_NOT_FOUND", "Gone.")

    jobs, _, _ = _jobs({"record": refused})
    jobs.submit("op-1", "req-1", "record", {"x": 1}, CLIENT)
    jobs.drain()
    retry = jobs.submit("op-2", "req-1", "record", {"x": 1}, CLIENT)
    jobs.drain()
    assert attempts == ["op-1"]
    assert retry is not None and retry.reply()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_queued_jobs_failed_at_stop_never_ran_and_say_so() -> None:
    jobs, ran = _counting()
    queued = jobs.submit("op-1", "req-1", "record", {"x": 1}, CLIENT)
    jobs.stop()
    assert queued is not None
    assert queued.reply()["error"]["code"] == "CANCELLED"
    assert queued.reply()["error"]["retryable"] is True
    assert ran == []


def test_a_finished_operation_keeps_its_receipt_but_not_its_arguments() -> None:
    jobs, _ = _counting()
    operation = jobs.submit("op-1", "req-1", "record", {"points": list(range(1000))}, CLIENT)
    jobs.drain()
    assert operation is not None
    assert operation.args == {}
    assert operation.reply()["result"] == {"ran": 1}


def test_an_operation_id_reused_by_another_request_is_refused() -> None:
    jobs, ran = _counting()
    jobs.submit("op-1", "req-1", "record", {"x": 1}, CLIENT)
    reused = jobs.submit("op-1", "req-2", "record", {"x": 1}, CLIENT)
    jobs.drain()
    assert reused is not None
    assert reused.reply()["error"]["code"] == "INVALID_ARGUMENT"
    assert len(ran) == 1
    assert jobs.wait("op-1", 0) == {
        "status": "done",
        "operation_id": "op-1",
        "request_id": "req-1",
        "op": "record",
        "result": {"ran": 1},
    }


def test_a_handler_sees_the_calls_client() -> None:
    seen: list[dict[str, Any]] = []

    def record(args: dict[str, Any], call: Call) -> dict[str, Any]:
        seen.append({"client": call.client, "request_id": call.request_id})
        return {}

    jobs, _, _ = _jobs({"record": record})
    jobs.submit("op-1", "req-1", "record", {}, CLIENT)
    jobs.drain()
    assert seen == [{"client": CLIENT, "request_id": "req-1"}]
