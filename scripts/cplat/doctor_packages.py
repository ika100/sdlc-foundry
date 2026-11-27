"""Spec 104 (AC-104.12): /platform:doctor reports a missing PACKAGES_READ_TOKEN when the repo reads private packages."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

NAME = "secret PACKAGES_READ_TOKEN"
_WHEEL_URL = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/releases/download/")


def _npm_scope(repo: Path, owner: str) -> bool:
    npmrc = repo / ".npmrc"
    if not npmrc.is_file():
        return False
    want = re.compile(rf"^@{re.escape(owner)}:registry\s*=\s*https://npm\.pkg\.github\.com/?\s*$", re.IGNORECASE)
    for line in npmrc.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith(("#", ";")) and want.match(s):
            return True
    return False


def _private_wheel_repos(repo: Path) -> list[str]:
    import ship
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file():
        return []
    seen: list[str] = []
    for m in _WHEEL_URL.finditer(pyproject.read_text()):
        slug = f"{m.group(1)}/{m.group(2)}"
        if slug not in seen:
            seen.append(slug)
    # a repo this login cannot read is private to it: anything but a plain `false` counts as private
    return [s for s in seen if ship.gh(["api", f"repos/{s}", "--jq", ".private"], cwd=repo, check=False).strip() != "false"]


def private_package_sources(repo: Path, owner: str) -> list[str]:
    """What needs the token, in order; [] = none."""
    out = []
    if _npm_scope(repo, owner):
        out.append(f"@{owner.lower()} packages from npm.pkg.github.com")
    out += [f"wheels of {s} (private release assets)" for s in _private_wheel_repos(repo)]
    return out


def check_packages_token(repo: Path) -> list[dict]:
    import ship
    from doctor import FAIL, OK, WARN, check
    if not shutil.which("gh"):
        return []
    slug = ship.service_slug(repo)
    owner = slug.split("/")[0]
    sources = private_package_sources(repo, owner)
    if not sources:
        return []
    joined = ", ".join(sources)
    wheels = _private_wheel_repos(repo)
    what = []
    if _npm_scope(repo, owner):
        what.append("packages (classic token, read:packages)")
    if wheels:
        what.append(f"{', '.join(wheels)} (fine-grained: Contents read)")
    fix = f"create a token that can read {' and '.join(what)}, then: gh secret set PACKAGES_READ_TOKEN -R {slug}"
    names = ship.secret_names(repo)
    if names is None:
        return [check(WARN, NAME, "could not be read with this gh login", fix)]
    if "PACKAGES_READ_TOKEN" in names:
        return [check(OK, NAME, f"set: CI and the image build can read {joined}")]
    return [check(FAIL, NAME, f"not set: CI and the image build cannot install {joined}", fix)]
