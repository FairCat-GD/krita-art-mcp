import re

import bridge_core


def test_plugin_version_is_major_minor_fix() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", bridge_core.PLUGIN_VERSION)
