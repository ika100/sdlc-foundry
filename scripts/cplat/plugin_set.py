"""The plugin set of the marketplace: its catalog, the tombstone-only test and the dependency names (spec 174).

Standard library only, so the repository checks can import it without an environment.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MARKETPLACE = "sdlc-foundry"
STARTER = "starter"
EXTRAS = ("agents", "skills", "hooks", "bin")
MARKETPLACE_FILE = ".claude-plugin/marketplace.json"
_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


def _load(root: Path, rel: str) -> object:
    try:
        return json.loads((root / rel).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{rel}: {exc.strerror or exc}") from exc
    except ValueError as exc:
        raise ValueError(f"{rel}: invalid JSON ({exc})") from exc


def catalog(root: Path) -> dict[str, dict]:
    """Marketplace entries by name, in file order."""
    data = _load(root, MARKETPLACE_FILE)
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list):
        raise ValueError(f"{MARKETPLACE_FILE}: no plugins list")
    out: dict[str, dict] = {}
    for item in plugins:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("source"), str):
            raise ValueError(f"{MARKETPLACE_FILE}: a plugin entry lacks name or source")
        out[item["name"]] = item
    return out


def plugin_dir(root: Path, entry: dict) -> Path:
    return root / entry["source"]


def manifest(root: Path, name: str) -> dict:
    """The plugin.json of the named plugin."""
    entry = catalog(root).get(name)
    if entry is None:
        raise ValueError(f"{MARKETPLACE_FILE}: no plugin {name}")
    rel = (plugin_dir(root, entry) / ".claude-plugin" / "plugin.json").relative_to(root).as_posix()
    data = _load(root, rel)
    if not isinstance(data, dict):
        raise ValueError(f"{rel}: not a JSON object")
    return data


def _front_matter(text: str) -> list[str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return lines[1:i]
    return []


def is_tombstone_only(plugin_dir: Path) -> bool:
    """True when every command is a `moved-to:` tombstone and the plugin holds nothing else."""
    if any((plugin_dir / extra).exists() for extra in EXTRAS):
        return False
    commands = sorted((plugin_dir / "commands").glob("*.md"))
    if not commands:
        return False
    for path in commands:
        front = _front_matter(path.read_text(encoding="utf-8"))
        if not any(line.startswith("moved-to:") for line in front):
            return False
    return True


def dependency_name(entry: object) -> str | None:
    """`x` or `x@sdlc-foundry` gives `x`; anything else gives None."""
    if not isinstance(entry, str):
        return None
    name, _, market = entry.partition("@")
    if "@" in entry and market != MARKETPLACE:
        return None
    return name if _NAME.fullmatch(name) else None


def starter(root: Path) -> tuple[str, ...]:
    """The dependency names of the starter bundle, in order."""
    deps = manifest(root, STARTER).get("dependencies", [])
    names = [dependency_name(d) for d in deps] if isinstance(deps, list) else [None]
    if any(n is None for n in names):
        raise ValueError(f"plugins/{STARTER}/.claude-plugin/plugin.json: unreadable dependencies")
    return tuple(n for n in names if n is not None)
