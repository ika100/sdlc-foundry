"""Smoke test — confirms the package imports."""

from __future__ import annotations

from importlib.metadata import version

import {{ module_name }}


def test_package_has_version() -> None:
    assert {{ module_name }}.__version__ == version("{{ project_name }}")
