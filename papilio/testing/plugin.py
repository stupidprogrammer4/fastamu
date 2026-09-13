"""Lightweight pytest markers."""

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-mark tests by their folder: tests/unit -> unit, tests/integration
    -> integration."""
    folders = {
        "/tests/integration/": pytest.mark.integration,
        "/tests/unit/": pytest.mark.unit,
        "/tests/api/": pytest.mark.api,
    }
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        for folder, mark in folders.items():
            if folder in path:
                item.add_marker(mark)
