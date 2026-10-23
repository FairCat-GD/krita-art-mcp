import re
from pathlib import Path

import bridge_core
import pytest
from bridge_core import capabilities, errors
from bridge_core.source_hash import source_hash

# The capability names of PDD Part 4, krita_server_info.
CAPABILITIES = {
    "stroke.native_brush",
    "stroke.per_point_input",
    "stroke.smoothing",
    "undo.grouping",
    "stroke.deterministic",
    "operation.cancel_running",
    "selection.enforced",
    "color_spaces",
    "filters",
    "animation",
}


def test_plugin_version_is_major_minor_fix() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", bridge_core.PLUGIN_VERSION)


def test_the_capability_matrix_has_every_entry_in_its_shape() -> None:
    matrix = capabilities.matrix()
    assert set(matrix) == CAPABILITIES
    for name, entry in matrix.items():
        assert set(entry) == {"supported", "since", "notes"}, name
        assert isinstance(entry["supported"], bool)
        assert entry["notes"]
        # A supported entry names the release that built it; an unsupported one names none.
        if entry["supported"]:
            assert re.fullmatch(r"\d+\.\d+\.\d+", entry["since"])
        else:
            assert entry["since"] is None


def test_nothing_is_supported_before_it_is_built() -> None:
    assert [name for name, entry in capabilities.matrix().items() if entry["supported"]] == []


def test_the_source_hash_covers_python_sources_only(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "a.py").write_text("A = 1\n")
    (tmp_path / "b.py").write_text("B = 2\n")
    first = source_hash(tmp_path)
    (tmp_path / "core" / "__pycache__").mkdir()
    (tmp_path / "core" / "__pycache__" / "a.py").write_text("stale\n")
    (tmp_path / "notes.txt").write_text("not code\n")
    assert source_hash(tmp_path) == first
    (tmp_path / "b.py").write_text("B = 3\n")
    assert source_hash(tmp_path) != first


def test_error_bodies_use_known_codes_only() -> None:
    assert len(errors.CODES) == len(set(errors.CODES)) == 30
    assert errors.error("BUSY", "Wait.", True) == {
        "code": "BUSY",
        "message": "Wait.",
        "retryable": True,
        "details": {},
    }
    with pytest.raises(ValueError):
        errors.error("STALE_REVISION", "Phase 3.")
