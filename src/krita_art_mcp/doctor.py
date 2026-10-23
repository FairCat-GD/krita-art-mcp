import sys
from typing import TextIO

from krita_art_mcp import paths, plugin_files, setup_checks
from krita_art_mcp.bridge_client import BridgeClient, Done, Failed
from krita_art_mcp.errors import PROTOCOL
from krita_art_mcp.setup_checks import Setup, Step

STEPS = 5


def run(
    setup: Setup | None = None, client: BridgeClient | None = None, out: TextIO = sys.stdout
) -> int:
    setup = setup or Setup()
    client = client or BridgeClient()
    status = _report(_steps(setup, client), out)
    # A session checks this before it restarts Krita itself (decision 21), usually because the
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
        steps.append(Step("the bridge is reachable", False, health.error["message"], fix))
        return steps
    info = health.result
    session = str(info.get("session_id"))[:12]
    steps.append(
        Step("the bridge is reachable", True, f"Krita {info.get('krita_version')}, {session}")
    )
    repo_hash = plugin_files.source_hash(setup.plugin_source / paths.PLUGIN_NAME)
    running_hash = str(info.get("plugin_hash"))
    current = info.get("protocol") == PROTOCOL and running_hash == repo_hash
    detail = f"protocol {info.get('protocol')}, running {running_hash[:12]}, repo {repo_hash[:12]}"
    steps.append(Step("the protocol and plugin hash match", current, detail, setup_checks.INSTALL))
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
