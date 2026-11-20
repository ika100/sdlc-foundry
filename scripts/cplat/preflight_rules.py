"""Whether the permission rules let a coder subagent run its commands in its worktree (spec 207, failure category subagent-tools).

Read-only. `preflight` is imported inside the functions: it imports this module, so a module-level import would be a cycle.
"""
from __future__ import annotations

import re
from pathlib import Path

import denyrules
import preflight_trust
from core import run
from preflight_agents import Agent
from units import feature_head

RESET = "cplat component build reset 0123abc"
ADD = "git add src/x.py"
COMMIT = 'git commit -s -m "<subject>"'
RUN_PATH = "--disallowedTools"
_SCRIPT = re.compile(r"devbox run ([A-Za-z0-9][\w:.-]*)")
_PATTERNS = {RESET: "Bash(cplat component build reset *)", ADD: "Bash(git add *)", COMMIT: "Bash(git commit -s *)"}


def _show(folder: Path, head: str, path: str) -> str:
    p = run(["git", "show", f"{head}:{path}"], cwd=folder, check=False)
    return p.stdout if p.returncode == 0 else ""


def coder_commands(folder: Path, specs: list[str]) -> list[str]:
    """The reset, the git commands and the devbox scripts the plan names (`devbox run test` when none), in order."""
    scripts: list[str] = []
    for spec in specs:
        text = _show(folder, feature_head(folder, spec), f"docs/specs/{spec}/plan.md")
        for name in _SCRIPT.findall(text):
            if name not in scripts:
                scripts.append(name)
    return [RESET, ADD, COMMIT, *(f"devbox run {s}" for s in (scripts or ["test"]))]


def _allow_rules(folder: Path, run_allow: list[str]) -> list[str]:
    import preflight
    rules: list[str] = []
    for name, path in preflight.layers(folder):
        if name in ("managed", "user") or (name == "local" and preflight_trust.trusted(folder)):
            rules += preflight._rules(path, "allow")
    perms = preflight_trust.committed_settings(folder).get("permissions")
    committed = perms.get("allow") if isinstance(perms, dict) else None
    if isinstance(committed, list):
        rules += [r for r in committed if isinstance(r, str)]
    return rules + list(run_allow)


def _refusals(folder: Path, run_deny: list[str]) -> list[tuple[str, str, str, str]]:
    """`(layer, path, kind, rule)` for every deny and ask rule, the run's own deny rules last."""
    import preflight
    out = [(name, str(path), kind, rule) for name, path in preflight.layers(folder) for kind in ("deny", "ask")
           for rule in preflight._rules(path, kind)]
    return out + [("run", RUN_PATH, "deny", rule) for rule in run_deny]


def _agent_rule(rule: str, agents: list[Agent]) -> Agent | None:
    m = re.fullmatch(r"(?:Agent|Task)(?:\((.*)\))?", rule)
    if not m:
        return None
    if m.group(1) is None:
        return agents[0] if agents else None
    return next((a for a in agents if m.group(1) in (a.role, a.type)), None)


def check(folder: Path, specs: list[str], agents: list[Agent], run_allow: list[str], run_deny: list[str]) -> str | None:
    import preflight
    refusals = _refusals(folder, run_deny)
    denies = [r for r in refusals if r[2] == "deny"]
    for layer, path, _, rule in denies:
        if rule in ("Bash", "Bash(*)"):
            return f'deny rule "{rule}" in {layer} settings ({path}) denies the shell tool to every agent: remove "{rule}"'
    for layer, path, _, rule in denies:
        if (agent := _agent_rule(rule, agents)) is not None:
            return f'deny rule "{rule}" in {layer} settings ({path}) denies the {agent.role} agent this run starts: remove "{rule}"'
    commands = coder_commands(folder, specs)
    for agent in agents:
        for command in commands:
            for layer, path, kind, rule in refusals:
                if denyrules.refuses(rule, command):
                    return (f'{agent.role} runs "{command}", which {kind} rule "{rule}" in {layer} settings ({path}) matches: '
                            f'remove or narrow "{rule}"')
    allow = _allow_rules(folder, run_allow)
    who = agents[0].role if agents else "coder"
    for command in commands:
        if not any(preflight.matches(rule, command) for rule in allow):
            pattern = _PATTERNS.get(command, f"Bash({command})")
            return (f'{who} runs "{command}", which no allow rule permits: add "{pattern}" to permissions.allow '
                    f"in {folder}/.claude/settings.json")
    return None
