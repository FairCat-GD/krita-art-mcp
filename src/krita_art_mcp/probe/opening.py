import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from mcp import Client

from krita_art_mcp import baselines, paths, roots
from krita_art_mcp.bridge_client import BridgeClient, Done, Failed
from krita_art_mcp.probe import fixtures
from krita_art_mcp.probe.common import close, harness_call, open_args
from krita_art_mcp.probe.report import Report, code, differs, sheet_cell, tool
from krita_art_mcp.tools.saving import file_sha256

COPY_NAME = re.compile(r"^\d{8}T\d{6}\.\d{3}Z-probe\.(ora|kra|png)$")
# Never writable, so an escape that slipped through could still write nothing there.
UNWRITABLE = Path("/var/empty")
COMPARED = (
    "type",
    "parent",
    "order",
    "visible",
    "blend_mode",
    "locked",
    "alpha_locked",
    "inherit_alpha",
)


@dataclass
class Opened:
    data: dict[str, Any]
    baseline: np.ndarray | None


async def run(report: Report, a: Client, b: Client, client: BridgeClient, harness: Path) -> None:
    harness = Path(os.path.realpath(harness))
    folder = harness / "fixtures"
    folder.mkdir(exist_ok=True)
    ora, kra, png = folder / "probe.ora", folder / "probe.kra", folder / "probe.png"
    stack = fixtures.probe_stack()
    composite = fixtures.write_ora(ora, stack)
    fixtures.write_png(png, composite)
    info = (await tool(a, "krita_server_info", {})).get("data") or {}
    allowed = info.get("allowed_roots")
    report.check(
        "krita_server_info lists the allowed roots",
        isinstance(allowed, list) and all(isinstance(root, str) for root in allowed),
        f"{len(allowed)} root(s)" if isinstance(allowed, list) else str(allowed),
    )
    if not await _make_kra(report, a, client, ora, kra):
        return
    hashes = {path: file_sha256(path) for path in (ora, kra, png)}
    ora_tree = fixtures.expected_tree(stack)
    png_tree = [{**ora_tree[0], "name": None, "bounds_px": fixtures.bounds(composite)}]
    opened: dict[tuple[str, str], Opened] = {}
    for label, source, tree in (
        ("ORA", ora, ora_tree),
        ("KRA", kra, ora_tree),
        ("PNG", png, png_tree),
    ):
        for mode in ("read_only", "working_copy"):
            work = harness / "work" / label.lower() if mode == "working_copy" else None
            found = await _round_trip(report, a, label, source, mode, work, tree, harness)
            if found is not None:
                opened[(label, mode)] = found
    _baselines(report, opened, composite)
    _layer_ids(report, opened)
    await _editable(report, a, ora, kra, harness, opened)
    await _refusals(report, a, b, client, png, harness, allowed or [])
    report.check(
        "every fixture is unchanged by the opens",
        all(file_sha256(path) == digest for path, digest in hashes.items()),
    )
    _kritarc(report, harness)


async def _make_kra(report: Report, a: Client, client: BridgeClient, ora: Path, kra: Path) -> bool:
    # The fixture comes from Krita's own exporter, so it holds what a real KRA holds.
    opened = await tool(a, "krita_document_open", open_args(ora, "read_only"))
    if opened.get("status") != "completed":
        report.check("harness.export_kra writes the KRA fixture", False, str(opened.get("error")))
        return False
    document_id = opened["document_id"]
    try:
        made = _harness_export(client, document_id, kra)
        outside = _harness_export(client, document_id, UNWRITABLE / "probe.kra")
        again = _harness_export(client, document_id, kra)
    finally:
        await close(a, document_id)
    written = (
        isinstance(made, Done) and kra.exists() and made.result.get("sha256") == file_sha256(kra)
    )
    report.check(
        "harness.export_kra writes the KRA fixture with Krita's own exporter",
        written,
        "" if written else str(made),
    )
    codes = tuple(_failed_code(outcome) for outcome in (outside, again))
    report.check(
        "harness.export_kra refuses a target outside its folder, and one that exists",
        codes == ("PATH_NOT_ALLOWED", "FILE_EXISTS"),
        ", ".join(str(found) for found in codes),
    )
    return written


def _harness_export(client: BridgeClient, document_id: str, target: Path) -> Any:
    arguments = {"document_id": document_id, "target_path": str(target)}
    outcome = harness_call(client, "harness.export_kra", **arguments)
    if _failed_code(outcome) == "BUSY":
        # Krita's autosave can hold the document for a moment; the export wrote nothing.
        outcome = harness_call(client, "harness.export_kra", **arguments)
    return outcome


def _failed_code(outcome: Any) -> str | None:
    return outcome.error["code"] if isinstance(outcome, Failed) else None


async def _round_trip(
    report: Report,
    a: Client,
    label: str,
    source: Path,
    mode: str,
    work: Path | None,
    tree: list[dict[str, Any]],
    harness: Path,
) -> Opened | None:
    name = (
        f"{label} {mode}: opens protected, matches the fixture; a render reads its baseline, "
        "kept until close"
    )
    started = time.perf_counter()
    result = await tool(a, "krita_document_open", open_args(source, mode, work))
    seconds = time.perf_counter() - started
    if result.get("status") != "completed":
        report.check(name, False, f"{code(result)}: {(result.get('error') or {}).get('message')}")
        return None
    data, document_id = result["data"], result["document_id"]
    problems = []
    path = Path(data["path"])
    if work is not None:
        if path.parent != work or not COPY_NAME.match(path.name) or path.suffix != source.suffix:
            problems.append(f"the copy is {path.name} in {path.parent.name}")
    elif path != source or data["working_copy"]:
        problems.append("a read_only open did not open the source itself")
    problems += _tree_problems(data["layers"], tree)
    if not all(layer["protected"] for layer in data["layers"]):
        problems.append("a layer is unprotected")
    folder = harness / "server-a" / "baselines"
    if baselines.load(folder, data["baseline_id"]) is not None:
        problems.append("a baseline file at open, before any render asked for it")
    # Native size, so the as-opened cell is the baseline's own bytes.
    rendered = await tool(a, "krita_preview_render", _native_render(document_id, data))
    kept = baselines.load(folder, data["baseline_id"])
    baseline = None if kept is None else np.array(kept)
    if baseline is None:
        problems.append(f"no baseline file after a render: {code(rendered)}")
    else:
        problems += _as_opened_cell(rendered, baseline)
    inspected = await tool(a, "krita_document_inspect", {"document_id": document_id, "frame": 0})
    seen = inspected.get("data") or {}
    if seen.get("layers") != data["layers"] or seen.get("baseline_id") != data["baseline_id"]:
        problems.append("inspect disagrees with open")
    if (label, mode) == ("PNG", "read_only"):
        await _file_name(report, a, document_id, source)
    closed = (await close(a, document_id, "refuse")).get("data") or {}
    if closed != {"closed": True, "baseline_untouched": True}:
        problems.append(f"close answered {closed}")
    if baselines.load(folder, data["baseline_id"]) is not None:
        problems.append("the baseline outlived its document")
    detail = "; ".join(problems) or f"{len(data['layers'])} layers in {seconds * 1000:.0f} ms"
    report.check(name, not problems, detail)
    return Opened(data, baseline)


def _native_render(document_id: str, data: dict[str, Any]) -> dict[str, Any]:
    source = {
        "document_id": document_id,
        "frame": 0,
        "target": "composite",
        "baseline_id": data["baseline_id"],
    }
    return {
        "recipes": [{"id": "native", "target_size_px": data["canvas_px"]}],
        "filter": "nearest",
        "sources": [source],
        "overlays": [],
        "backgrounds": ["transparent"],
    }


def _as_opened_cell(rendered: dict[str, Any], baseline: np.ndarray) -> list[str]:
    sheet = ((rendered.get("data") or {}).get("sheets") or [None])[0]
    if sheet is None:
        return [f"the render failed: {code(rendered)}"]
    problem = differs(sheet_cell(sheet, 0), baseline)
    as_opened = sheet["columns"][0]["state"] == "as_opened"
    return [f"the as-opened cell: {problem}"] if problem or not as_opened else []


def _tree_problems(layers: list[dict[str, Any]], tree: list[dict[str, Any]]) -> list[str]:
    if len(layers) != len(tree):
        return [f"{len(layers)} layers, not {len(tree)}"]
    names = {layer["id"]: layer["name"] for layer in layers}
    problems = []
    for layer, want in zip(layers, tree, strict=True):
        got = {**layer, "parent": names.get(layer["parent_id"])}
        label = want["name"] or layer["name"]
        if want["name"] is not None and layer["name"] != want["name"]:
            problems.append(f"{layer['name']!r} where {want['name']!r} belongs")
        problems += [
            f"{label}: {key} {got[key]!r}, not {want[key]!r}"
            for key in COMPARED
            if got[key] != want[key]
        ]
        if abs(layer["opacity"] - want["opacity"]) > 1 / 255 + 1e-9:
            problems.append(f"{label}: opacity {layer['opacity']:.4f}, not {want['opacity']}")
        if want["bounds_px"] is not None and layer["bounds_px"] != want["bounds_px"]:
            problems.append(f"{label}: bounds {layer['bounds_px']}, not {want['bounds_px']}")
    return problems


def _baselines(
    report: Report, opened: dict[tuple[str, str], Opened], composite: np.ndarray
) -> None:
    def baseline(label: str) -> np.ndarray | None:
        found = opened.get((label, "read_only"))
        return None if found is None else found.baseline

    for name, found, expected in (
        ("the PNG's baseline is its pixels, byte for byte", baseline("PNG"), composite),
        (
            "the ORA's baseline is the fixture's composite, byte for byte",
            baseline("ORA"),
            composite,
        ),
        ("the KRA's baseline is the ORA's, byte for byte", baseline("KRA"), baseline("ORA")),
    ):
        problem = differs(found, expected)
        report.check(name, not problem, problem)


def _layer_ids(report: Report, opened: dict[tuple[str, str], Opened]) -> None:
    def ids(label: str, mode: str) -> list[str]:
        found = opened.get((label, mode))
        return [] if found is None else [layer["id"] for layer in found.data["layers"]]

    kra = ids("KRA", "read_only"), ids("KRA", "working_copy")
    report.check("a KRA keeps its layer ids across opens (K39)", bool(kra[0]) and kra[0] == kra[1])
    ora = ids("ORA", "read_only"), ids("ORA", "working_copy")
    report.check(
        "an ORA's layers get new ids at every open",
        bool(ora[0]) and len(ora[1]) == len(ora[0]) and not set(ora[0]) & set(ora[1]),
    )


async def _file_name(report: Report, a: Client, document_id: str, source: Path) -> None:
    listed = await tool(a, "krita_document_list", {})
    documents = (listed.get("data") or {}).get("documents", [])
    names = [entry["name"] for entry in documents if entry["document_id"] == document_id]
    report.check(
        "a file with no title lists under its file's name", names == [source.name], str(names)
    )


async def _editable(
    report: Report,
    a: Client,
    ora: Path,
    kra: Path,
    harness: Path,
    opened: dict[tuple[str, str], Opened],
) -> None:
    earlier = opened.get(("KRA", "read_only"))
    shape = None if earlier is None else _id_of(earlier.data["layers"], "probe shape")
    work = harness / "work" / "editable"
    unprotected = []
    for source, extra in (
        (kra, {"editable_layer_ids": [shape]}),
        (ora, {"editable_layer_names": ["probe locked"]}),
    ):
        result = await tool(
            a, "krita_document_open", open_args(source, "working_copy", work, **extra)
        )
        layers = (result.get("data") or {}).get("layers", [])
        unprotected.append(sorted(layer["name"] for layer in layers if not layer["protected"]))
        if result.get("document_id"):
            await close(a, result["document_id"])
    report.check(
        "editable_layer_ids (KRA) and editable_layer_names (ORA) unprotect exactly those layers",
        shape is not None and unprotected == [["probe shape"], ["probe locked"]],
        str(unprotected),
    )


def _id_of(layers: list[dict[str, Any]], name: str) -> str | None:
    return next((layer["id"] for layer in layers if layer["name"] == name), None)


async def _refusals(
    report: Report,
    a: Client,
    b: Client,
    client: BridgeClient,
    png: Path,
    harness: Path,
    allowed: list[str],
) -> None:
    mismatch = harness / "work" / "mismatch"
    wrong = open_args(png, "working_copy", mismatch, source_sha256="0" * 64)
    refused = await tool(a, "krita_document_open", wrong)
    left = sorted(os.listdir(mismatch)) if mismatch.exists() else []
    report.check(
        "a wrong source_sha256 is SOURCE_HASH_MISMATCH, and leaves no copy",
        code(refused) == "SOURCE_HASH_MISMATCH" and left == [],
        f"{code(refused)}, {len(left)} file(s) left",
    )
    await _escapes(report, a, client, png, harness, allowed)
    await _retry(report, a, b, png, harness)


async def _escapes(
    report: Report, a: Client, client: BridgeClient, png: Path, harness: Path, allowed: list[str]
) -> None:
    # Dangling or unwritable targets, so nothing outside could be read or written if a check
    # broke; each is confirmed outside every root before it counts.
    link = harness / "escape.png"
    link.symlink_to(UNWRITABLE / "probe-escape.png")
    dotdot = harness / "fixtures" / ".." / ".." / "probe-outside.png"
    cases = {
        "..": open_args(png, "read_only", source_path=str(dotdot)),
        "a symlink": open_args(png, "read_only", source_path=str(link)),
        "a working_dir": open_args(png, "working_copy", UNWRITABLE / "probe-work"),
    }
    reals = [os.path.realpath(dotdot), os.path.realpath(link), str(UNWRITABLE / "probe-work")]
    rooted = [os.path.realpath(root) for root in allowed]
    if any(roots.inside(os.path.realpath(real), rooted) for real in reals):
        report.measured("paths outside every root", "skipped: an allowed root covers them")
        return
    answers = {name: await tool(a, "krita_document_open", args) for name, args in cases.items()}
    codes = {name: code(answer) for name, answer in answers.items()}
    # Refused before the send: the plugin's own refusal would carry an operation_id.
    report.check(
        "the server refuses paths outside every root: .., a symlink, a working_dir",
        set(codes.values()) == {"PATH_NOT_ALLOWED"}
        and all(answer.get("operation_id") is None for answer in answers.values()),
        str(codes),
    )
    op_args = {
        "source_path": str(link),
        "source_sha256": file_sha256(png),
        "mode": "read_only",
        "working_dir": None,
        "editable_layer_ids": None,
        "editable_layer_names": None,
    }
    direct = client.call("document.open", op_args, request_id=str(uuid.uuid4()))
    if isinstance(direct, Done):
        # Leased to this process, so only its own client can close it.
        close_args = {"document_id": direct.result["document_id"], "dirty_policy": "discard"}
        client.call("document.close", close_args, request_id=str(uuid.uuid4()))
    report.check(
        "the plugin refuses the same symlink when the server is bypassed",
        _failed_code(direct) == "PATH_NOT_ALLOWED",
        str(_failed_code(direct)),
    )


async def _retry(report: Report, a: Client, b: Client, png: Path, harness: Path) -> None:
    work = harness / "work" / "retry"
    arguments = open_args(png, "working_copy", work)
    first = await tool(a, "krita_document_open", arguments)
    again = await tool(a, "krita_document_open", arguments)
    through_b = await tool(b, "krita_document_open", arguments)
    copies = sorted(os.listdir(work)) if work.exists() else []
    report.check(
        "a retried open returns the original receipt, with one document and one copy",
        first.get("status") == "completed" and first == again == through_b and len(copies) == 1,
        f"{len(copies)} copies",
    )
    document_id = first.get("document_id")
    if not document_id:
        return
    later = await tool(a, "krita_document_inspect", {"document_id": document_id, "frame": 1})
    report.check(
        "the server refuses krita_document_inspect at frame 1 with UNSUPPORTED_CAPABILITY",
        code(later) == "UNSUPPORTED_CAPABILITY" and later.get("operation_id") is None,
        str(code(later)),
    )
    await close(a, document_id)


def _kritarc(report: Report, harness: Path) -> None:
    # Read only: the harness never writes kritarc (invariant 13).
    try:
        lines = paths.kritarc().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    section, named = "", 0
    for line in lines:
        text = line.strip()
        if text.startswith("[") and text.endswith("]"):
            section = text[1:-1]
        elif section == "RecentFiles" and str(harness) in text:
            named += 1
    report.check("kritarc's recent files name no harness file", named == 0, f"{named} entries")
