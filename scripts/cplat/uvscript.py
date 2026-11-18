"""Command lines that run a target repo's inline script through the platform's uv-script.sh helper."""
from __future__ import annotations

from pathlib import Path

from core import PLATFORM_ROOT

HELPER: Path = PLATFORM_ROOT / "scripts" / "uv-script.sh"


def script_cmd(script: str, *args: str, quiet: bool = False) -> list[str]:
    """The platform's helper (absolute path, so repos that have not updated yet work) runs the script."""
    return ["bash", str(HELPER), *(["--quiet"] if quiet else []), script, *args]
