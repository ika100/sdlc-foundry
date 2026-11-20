"""The agents a covered command starts, the definition that wins for each, its shell grant and model (spec 207).

Backs AC-207.3 (each agent that runs shell commands resolves to a definition that grants Bash) and AC-207.5 (a model the
managed or user settings exclude fails without a model call). It never imports `preflight` at load time."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

import core
import preflight_trust
import shapecmd

ALIASES = ("opus", "sonnet", "haiku")
BUILD_ROLES = ("coder", "tester", "reviewer", "security", "quality")
FALLBACK = {"coder": "svc:coder", "tester": "svc:tester", "reviewer": "svc:reviewer",
            "security": "shared:security", "quality": "shared:quality"}


@dataclass
class Agent:
    role: str                   # "coder"
    type: str                   # "svc:coder"
    path: Path | None           # the winning definition
    layer: str                  # "project" | "user" | "plugin-dir" | "installed" | "platform"
    bash: bool                  # grants the shell tool
    model: str | None           # its model; None = inherits the coordinator's


def roles(folder: Path, command: str) -> list[tuple[str, str]]:
    """`[(role, type)]` the command starts in the folder, in table order; `[]` for a gitops or cluster folder."""
    try:
        route = shapecmd.route(folder)
    except core.PlatformError:
        return list(FALLBACK.items())
    if route.get("unsupported"):
        return []
    types = route.get("agents", {})
    wanted = list(BUILD_ROLES) + (["deployment"] if command != "/component:build" else [])
    return [(r, types[r]) for r in wanted if r in types]


def _front_matter(path: Path) -> dict | None:
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines or lines[0].strip() != "---":
        return {}
    for end, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            try:
                data = yaml.safe_load("\n".join(lines[1:end]))
            except yaml.YAMLError:
                return {}
            return data if isinstance(data, dict) else {}
    return {}


def _named(agents_dir: Path, role: str, type_: str) -> Path | None:
    if not agents_dir.is_dir():
        return None
    for f in sorted(agents_dir.glob("*.md")):
        meta = _front_matter(f)
        if meta and meta.get("name") in (role, type_):
            return f
    return None


def _items(value: object) -> list[str]:
    if isinstance(value, str):
        return [i.strip() for i in value.strip().strip("[]").split(",") if i.strip()]
    if isinstance(value, list):
        return [str(i).strip() for i in value]
    return []


def _is_bash(item: str) -> bool:
    return item == "Bash" or item.startswith("Bash(")


def _grants_bash(meta: dict) -> bool:
    if "tools" in meta and meta["tools"] is not None:
        if not any(_is_bash(i) for i in _items(meta["tools"])):
            return False
    return not any(_is_bash(i) for i in _items(meta.get("disallowedTools")))


def _installed(folder: Path, plugin: str, role: str) -> Path | None:
    found = [(key, p / "agents" / f"{role}.md") for key, paths in preflight_trust.installed_plugins().items()
             if key.split("@")[0] == plugin for p in paths]
    found = [(k, f) for k, f in found if f.is_file()]
    if not found:
        return None
    enabled = preflight_trust.committed_settings(folder).get("enabledPlugins")
    if isinstance(enabled, dict):
        for key, f in found:
            if enabled.get(key) is True:
                return f
    return found[0][1]


def resolve(folder: Path, role: str, type_: str, plugin_dirs: list[str]) -> Agent:
    """The definition that wins for the agent: project, user, `--plugin-dir`, installed, then this platform's own."""
    plugin = type_.split(":")[0]
    path = _named(folder / ".claude" / "agents", role, type_)
    layer = "project"
    if path is None:
        path, layer = _named(preflight_trust.plugins_dir().parent / "agents", role, type_), "user"
    if path is None:
        layer = "plugin-dir"
        base = preflight_trust.plugin_dir_names(plugin_dirs).get(plugin)
        path = base / "agents" / f"{role}.md" if base and (base / "agents" / f"{role}.md").is_file() else None
    if path is None:
        path, layer = _installed(folder, plugin, role), "installed"
    if path is None:
        layer = "platform"
        candidate = core.PLATFORM_ROOT / "plugins" / plugin / "agents" / f"{role}.md"
        path = candidate if candidate.is_file() else None
    meta = (_front_matter(path) if path else None) or {}
    model = meta.get("model")
    model = model.strip() if isinstance(model, str) and model.strip() not in ("", "inherit") else None
    if override := os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL"):
        model = override
    return Agent(role=role, type=type_, path=path, layer=layer, bash=_grants_bash(meta), model=model)


def check_definitions(agents: list[Agent]) -> str | None:
    """AC-207.3: the detail for the first agent whose winning definition does not grant Bash."""
    for a in agents:
        if not a.bash:
            return (f"{a.role} resolves to {a.path} ({a.layer} definition), which does not grant Bash: "
                    "add Bash to its tools, or remove the override")
    return None


def models(agents_by_folder: dict[Path, list[Agent]], coordinator: str | None) -> dict[str, list[str]]:
    """`{model: [roles]}`, the coordinator first; an agent without a model joins the coordinator's model."""
    out: dict[str, list[str]] = {}
    if coordinator:
        out[coordinator] = ["coordinator"]
    for agents in agents_by_folder.values():
        for a in agents:
            model = a.model or coordinator
            if model is None:
                continue
            roles_ = out.setdefault(model, [])
            if a.role not in roles_:
                roles_.append(a.role)
    return out


def _matches(model: str, entry: str) -> bool:
    if model == entry:
        return True
    for alias, full in ((model, entry), (entry, model)):
        if alias in ALIASES and alias in full.split("-") and full != alias:
            return True
    return False


def _list(settings: object, key: str) -> list[str] | None:
    value = settings.get(key) if isinstance(settings, dict) else None
    return [str(v) for v in value] if isinstance(value, list) else None


def check_models(models: dict[str, list[str]], repo: Path) -> str | None:
    """AC-207.5: the detail for the first model the managed or user settings exclude; no model call."""
    import json

    import preflight  # inside the function: no import cycle at load time

    for layer, path in preflight.layers(repo):
        if layer not in ("managed", "user"):
            continue
        try:
            settings = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        available, denied = _list(settings, "availableModels"), _list(settings, "deniedModels")
        for model, users in models.items():
            who = f"{model} (used by {', '.join(users)})"
            if available is not None and not any(_matches(model, e) for e in available):
                return (f"{who} is not in availableModels of {layer} settings ({path}): "
                        f"add {model} to availableModels, or set a model the settings allow")
            if denied is not None and any(_matches(model, e) for e in denied):
                return (f"{who} is in deniedModels of {layer} settings ({path}): "
                        f"remove {model} from deniedModels, or set a model the settings allow")
    return None
