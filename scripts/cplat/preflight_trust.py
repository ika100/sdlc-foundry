"""Whether a session start folder is trusted by Claude Code, and whether a run loses anything when it is not (spec 207).

Claude Code ignores a folder's committed `env`, `permissions.additionalDirectories` and enabled plugins until the trust dialog
was accepted there. This module only reads the trust record (Claude Code's config file) and never writes it."""
from __future__ import annotations

import json
import os
from pathlib import Path

import core


def config_file() -> Path:
    """Claude Code's config file, which holds the trust record."""
    if base := os.environ.get("CLAUDE_CONFIG_DIR"):
        return Path(base) / ".claude.json"
    return Path(os.environ.get("HOME") or Path.home()) / ".claude.json"


def plugins_dir() -> Path:
    if base := os.environ.get("CLAUDE_CONFIG_DIR"):
        return Path(base) / "plugins"
    return Path(os.environ.get("HOME") or Path.home()) / ".claude" / "plugins"


def trusted(folder: Path) -> bool:
    """True when the folder or one of its parents has its trust dialog recorded as accepted. Read-only."""
    try:
        projects = json.loads(config_file().read_text()).get("projects")
    except (OSError, ValueError, AttributeError):
        return False
    if not isinstance(projects, dict):
        return False
    here = folder.resolve()
    for p in (here, *here.parents):
        entry = projects.get(str(p))
        if isinstance(entry, dict) and entry.get("hasTrustDialogAccepted") is True:
            return True
    return False


def committed_settings(repo: Path) -> dict:
    """The repo's committed `.claude/settings.json` (the HEAD version, like `headless.repo_rules`); `{}` when missing or invalid."""
    try:
        done = core.run(["git", "-C", str(repo), "show", "HEAD:.claude/settings.json"], check=False)
        data = json.loads(done.stdout) if done.returncode == 0 else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def installed_plugins() -> dict[str, list[Path]]:
    """The plugins installed on this machine, `{name@marketplace: [install path]}`, for paths that exist."""
    try:
        data = json.loads((plugins_dir() / "installed_plugins.json").read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    plugins = data.get("plugins") if isinstance(data.get("plugins"), dict) else data
    found: dict[str, list[Path]] = {}
    for key, value in plugins.items():
        entries = value if isinstance(value, list) else [value]
        paths = [Path(e["installPath"]) for e in entries if isinstance(e, dict) and isinstance(e.get("installPath"), str)]
        if existing := [p for p in paths if p.exists()]:
            found[key] = existing
    return found


def plugin_dir_names(plugin_dirs: list[str]) -> dict[str, Path]:
    """`{plugin name: folder}` for the `--plugin-dir` folders, the name from each `.claude-plugin/plugin.json`."""
    names: dict[str, Path] = {}
    for d in plugin_dirs:
        try:
            name = json.loads((Path(d) / ".claude-plugin" / "plugin.json").read_text()).get("name")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(name, str) and name:
            names[name] = Path(d)
    return names


def check(folder: Path, plugin_dirs: list[str]) -> tuple[str | None, str | None]:
    """`(None, None)` for a trusted folder; `(detail, None)` when an untrusted one would lose something; else `(None, line)`."""
    if trusted(folder):
        return None, None
    tail = f"open claude in {folder} once and accept the trust dialog"
    settings = committed_settings(folder)
    env = settings.get("env")
    if isinstance(env, dict) and env:
        return (f"{folder} is not trusted and its committed settings set env ({', '.join(sorted(env))}), "
                f"which Claude Code ignores without trust: {tail}"), None
    perms = settings.get("permissions")
    if isinstance(perms, dict) and perms.get("additionalDirectories"):
        return (f"{folder} is not trusted and its committed settings set permissions.additionalDirectories, "
                f"which Claude Code ignores without trust: {tail}"), None
    enabled = settings.get("enabledPlugins")
    if isinstance(enabled, dict):
        installed, passed = installed_plugins(), plugin_dir_names(plugin_dirs)
        for key, on in enabled.items():
            if on is True and key not in installed and key.split("@")[0] not in passed:
                return (f"{folder} is not trusted and plugin {key}, which its committed settings enable, is neither installed "
                        f"on this machine nor passed with --plugin-dir: {tail}"), None
    return None, f"preflight: {folder} is not trusted; its permission rules are passed to the session"
