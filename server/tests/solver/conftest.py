from __future__ import annotations

from pathlib import Path

import pytest

from tools.solver_test_profiles import marker_for_test_file


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        marker_name = marker_for_test_file(Path(str(item.path)).name)
        if marker_name is not None:
            item.add_marker(getattr(pytest.mark, marker_name))
