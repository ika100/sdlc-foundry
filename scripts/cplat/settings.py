"""Settings files (spec 100, ADR-036): a project file and a user file with the same schema, both optional.

  <repo>/.platform-settings.yml                          committed, project-owned
  ${XDG_CONFIG_HOME:-~/.config}/sdlc-foundry/settings.yml   personal

`budget` (spec 102) is a map of per-ship limits `{minutes, invocations, reruns, cost}`, each a number or `off`; project over user.

`coordinator_model` is a model name (every workflow) or a map `{default: ..., <workflow>: ...}`. Precedence: the
`--model` flag, project (workflow, then general), user (workflow, then general), then `sonnet`.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from core import PlatformError

MODELS = ("sonnet", "opus", "haiku")
DEFAULT_MODEL = "sonnet"
PROJECT_FILE = ".platform-settings.yml"


def user_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "sdlc-foundry" / "settings.yml"


def workflow_of(prompt: str) -> str | None:
    m = re.match(r"^/(?:[a-z0-9-]+:)?([a-z0-9-]+)", prompt.strip())
    return m.group(1) if m else None


def _check(value: object, where: str) -> str:
    if value not in MODELS:
        raise PlatformError(f"unknown coordinator model '{value}' in {where}: use sonnet, opus or haiku")
    return value  # type: ignore[return-value]


def _read(path: Path) -> tuple[str | None, dict[str, str]]:
    """(general model, per-workflow models) of one file, every value validated."""
    if not path.is_file():
        return None, {}
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise PlatformError(f"{path} cannot be read: {e}") from None
    value = data.get("coordinator_model") if isinstance(data, dict) else None
    if value is None:
        return None, {}
    if isinstance(value, str):
        return _check(value, f"{path} (coordinator_model)"), {}
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise PlatformError(f"{path}: coordinator_model must be a model name or a map of model names")
    mapped = {k: _check(v, f"{path} (coordinator_model.{k})") for k, v in value.items()}
    return mapped.pop("default", None), mapped


def coordinator_model(repo: Path, prompt: str, flag: str | None) -> tuple[str, str]:
    """(model, source) for a headless run; raises PlatformError for an unknown name anywhere."""
    if flag is not None:
        _check(flag, "--model")
    files = [("project", *_read(repo / PROJECT_FILE)), ("user", *_read(user_file()))]
    if flag is not None:
        return flag, "flag"
    workflow = workflow_of(prompt)
    for source, general, by_workflow in files:
        hit = by_workflow.get(workflow) if workflow else None
        if hit or general:
            return (hit or general), source  # type: ignore[return-value]
    return DEFAULT_MODEL, "default"


def kube_context(repo: Path) -> tuple[str | None, str | None]:
    """(context, source) for commands that talk to the product's cluster when no --context is given: CPLAT_KUBE_CONTEXT,
    then `kube_context:` in the project file, then the user file; (None, None) when none is set. Never guessed."""
    env = os.environ.get("CPLAT_KUBE_CONTEXT", "").strip()
    if env:
        return env, "CPLAT_KUBE_CONTEXT"
    for source, path in (("project", repo / PROJECT_FILE), ("user", user_file())):
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as e:
            raise PlatformError(f"{path} cannot be read: {e}") from None
        value = data.get("kube_context") if isinstance(data, dict) else None
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise PlatformError(f"{path}: kube_context must be the name of a kube context")
        return value.strip(), source
    return None, None


BUDGET_KEYS = ("minutes", "invocations", "reruns", "cost")


def budget_defaults(repo: Path) -> dict:
    """Per-ship budget limits from the settings files (spec 102): project over user; a value is a number or None (off)."""
    out: dict = {}
    for path in (user_file(), repo / PROJECT_FILE):          # the project file is read last: it wins
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as e:
            raise PlatformError(f"{path} cannot be read: {e}") from None
        block = data.get("budget") if isinstance(data, dict) else None
        if block is None:
            continue
        if not isinstance(block, dict):
            raise PlatformError(f"{path}: budget must be a map of {', '.join(BUDGET_KEYS)}")
        for key, value in block.items():
            if key not in BUDGET_KEYS:
                raise PlatformError(f"{path}: unknown budget limit '{key}'", hint="use " + ", ".join(BUDGET_KEYS))
            if value in ("off", None):
                out[key] = None
            elif isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                out[key] = value
            else:
                raise PlatformError(f"{path}: budget.{key} must be a number or off, got '{value}'")
    return out


def mcp_config(repo: Path) -> Path | None:
    """`headless: {mcp_config: <file>}` of the project file (spec 111): an extra MCP config for unattended sessions,
    relative to the repo; it must exist."""
    path = repo / PROJECT_FILE
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise PlatformError(f"{path} cannot be read: {e}") from None
    block = data.get("headless") if isinstance(data, dict) else None
    if block is None or (isinstance(block, dict) and block.get("mcp_config") is None):
        return None
    value = block.get("mcp_config") if isinstance(block, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise PlatformError(f"{path}: headless.mcp_config must be a path to an MCP config file")
    target = repo / value.strip()
    if not target.is_file():
        raise PlatformError(f"headless.mcp_config in {path} names {value}, which does not exist",
                            hint="create the file or remove headless.mcp_config")
    return target
