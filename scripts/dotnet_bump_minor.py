#!/usr/bin/env python3
"""Bump the NuGet pins of a rendered service-dotnet project within their major (spec 218, scripts/bump_template_pins.py).

Run in the rendered project after `dotnet restore`: asks `dotnet list package --outdated --highest-minor` for the newest
minor/patch of every package and writes it into Directory.Packages.props. Standard library only.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


def latest(report: dict) -> dict[str, str]:
    """package id -> the newest version within its major, from the JSON report."""
    out: dict[str, str] = {}
    for project in report.get("projects") or []:
        for fw in project.get("frameworks") or []:
            for pkg in fw.get("topLevelPackages") or []:
                if pkg.get("latestVersion") and pkg.get("id"):
                    out[pkg["id"]] = pkg["latestVersion"]
    return out


def apply(props: str, versions: dict[str, str]) -> str:
    """Directory.Packages.props with each <PackageVersion Include="id" Version="..."> set to its new version."""
    def sub(m: re.Match) -> str:
        new = versions.get(m[2])
        return f'{m[1]}{new}{m[4]}' if new else m[0]
    return re.sub(r'(<PackageVersion Include="([^"]+)" Version=")([^"]+)(")', sub, props)


def main() -> int:
    res = subprocess.run(["dotnet", "list", "package", "--outdated", "--highest-minor", "--format", "json"],
                         capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr or res.stdout, file=sys.stderr)
        return 1
    props = Path("Directory.Packages.props")
    props.write_text(apply(props.read_text(), latest(json.loads(res.stdout))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
