import sys
from typing import TextIO

from krita_art_mcp import setup_checks
from krita_art_mcp.bridge_client import BridgeClient, Done, Failed
from krita_art_mcp.setup_checks import Setup, Step

STEPS = 6
REACHABLE = "the bridge is reachable"
# doctor reports; it does not wait out a busy Krita.
BUDGET_S = 5.0


def run(
    setup: Setup | None = None, client: BridgeClient | None = None, out: TextIO = sys.stdout
) -> int:
    setup = setup or Setup()
    client = client or BridgeClient(budget_s=BUDGET_S, any_plugin=True)
    status = _report(_steps(setup, client), out)
    # A session checks this before it restarts Krita itself, usually because the
    # plugin is stale, so it is reported whichever step failed.
    documents = client.call("bridge.unsaved_documents")
    if isinstance(documents, Done):
        open_count, unsaved = documents.result["open"], documents.result["unsaved"]
        print(f"Krita has {open_count} open document(s), {unsaved} unsaved.", file=out)
    elif not (isinstance(documents, Failed) and documents.error["code"] == "KRITA_NOT_RUNNING"):
        print("Could not read Krita's open documents.", file=out)
    return status


def _steps(setup: Setup, client: BridgeClient) -> list[Step]:
    steps: list[Step] = []
    for check in setup_checks.LOCAL_STEPS:
        steps.append(check(setup))
        if not steps[-1].passed:
            return steps
    health = client.health()
    if not isinstance(health, Done):
        fix = health.error["details"].get("fix") or setup_checks.bridge_missing().fix
        steps.append(Step(REACHABLE, False, health.error["message"], fix))
        return steps
    info = health.result
    session = str(info.get("session_id"))[:12]
    steps.append(Step(REACHABLE, True, f"Krita {info.get('krita_version')}, {session}"))
    steps.append(setup_checks.plugin_current(info, setup.plugin_source))
    if steps[-1].passed:
        steps.append(setup_checks.roots_allowed(setup))
    return steps


def _report(steps: list[Step], out: TextIO) -> int:
    for number, step in enumerate(steps, start=1):
        outcome = "PASS" if step.passed else "FAIL"
        print(f"{number}. {step.name}: {outcome} ({step.detail})", file=out)
        if not step.passed:
            print(f"   Fix: {step.fix}", file=out)
            print(f"doctor: stopped at step {number} of {STEPS}.", file=out)
            return 1
    print(f"doctor: all {STEPS} steps pass.", file=out)
    return 0
