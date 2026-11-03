"""Changelog and plugin version lookups for acceptance tests that must survive later entries, releases and bumps (spec 132, #321).

A released entry is read from its section by the version heading (`section("5.4.0")`), an entry of any age by content (`entry`), and a
plugin version is compared with `at_least`, never with `==`. Tests replace `text`, `fragments` and `plugin_versions` to prove that."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = ROOT / "docs" / "CHANGELOG.md"
FRAGMENTS = ROOT / "docs" / "changelog.d"
HEADING = re.compile(r"^## \[(?P<name>[^\]]+)\][^\n]*$", re.M)


def text() -> str:
    return CHANGELOG.read_text()


def fragments() -> list[tuple[str, str]]:
    """(name, text) of the changelog fragments, by name; the README is not one."""
    if not FRAGMENTS.is_dir():
        return []
    return [(f.name, f.read_text()) for f in sorted(FRAGMENTS.glob("*.md")) if f.name != "README.md"]


def sections() -> list[tuple[str, str]]:
    """(name, section text from its heading to the next one) for every `## [..]` section, newest first."""
    t = text()
    heads = list(HEADING.finditer(t))
    return [(h["name"], t[h.start(): heads[i + 1].start() if i + 1 < len(heads) else len(t)]) for i, h in enumerate(heads)]


def section(version: str) -> str:
    """The released section `## [version] ...` (heading included)."""
    found = [s for name, s in sections() if name == version]
    assert found, f"docs/CHANGELOG.md has no ## [{version}] section"
    return found[0].rstrip() + "\n"


def paragraphs(block: str, pattern: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", block) if re.search(pattern, p)]


def entry(pattern: str) -> tuple[str, str]:
    """(where, first paragraph matching PATTERN): fragments first (`fragment docs/changelog.d/<name>`), then every changelog section
    (`[Unreleased]`, `[5.4.0]`, ...)."""
    for name, body in fragments():
        hits = paragraphs(body, pattern)
        if hits:
            return f"fragment docs/changelog.d/{name}", hits[0]
    for name, body in sections():
        hits = paragraphs(body, pattern)
        if hits:
            return f"[{name}]", hits[0]
    raise AssertionError(f"no changelog fragment or section has an entry matching {pattern!r}")


def plugin_versions(name: str) -> tuple[str, str]:
    """(plugin.json version, marketplace.json version) of plugin NAME."""
    manifest = json.loads((ROOT / f"plugins/{name}/.claude-plugin/plugin.json").read_text())["version"]
    market = next(p["version"] for p in json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"] if p["name"] == name)
    return manifest, market


def at_least(version: str, least: str) -> bool:
    return tuple(int(x) for x in version.split(".")) >= tuple(int(x) for x in least.split("."))


def assert_bumped(name: str, least: str) -> None:
    """Plugin NAME is at LEAST in plugin.json and marketplace.json, and both agree (later bumps keep this true)."""
    manifest, market = plugin_versions(name)
    assert manifest == market, f"{name}: plugin.json {manifest}, marketplace.json {market}"
    assert at_least(manifest, least), f"{name}: {manifest} < {least}"
