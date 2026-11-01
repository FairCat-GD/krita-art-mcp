import io
import re

import pytest

from krita_art_mcp.probe.report import Report


def test_a_stage_is_measured_once_with_its_time() -> None:
    out = io.StringIO()
    report = Report(out)
    with report.timed("paint"):
        pass
    assert report.measured_count == 1
    assert re.fullmatch(r"MEASURED the paint stage: \d+\.\d s\n", out.getvalue())


def test_a_stage_that_raises_is_still_measured() -> None:
    out = io.StringIO()
    report = Report(out)
    with pytest.raises(RuntimeError), report.timed("save"):
        raise RuntimeError("the stage failed")
    assert out.getvalue().startswith("MEASURED the save stage: ")
