"""Hand-off from the console: "Open in Claude Code" and the deep links to evidence (spec 122, AC-122.36, AC-122.39)."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from typing import Any

LINK_KINDS = ("argocd", "grafana", "logs")


def _failure_summary(failure: dict[str, Any] | None) -> str:
    """One paragraph naming the failed check, test, criterion, error and diagnosis."""
    if not failure:
        return "The run stopped without a recorded failure."
    parts = []
    for label, key in (("check", "check"), ("test", "test"), ("criterion", "criterion"), ("error", "error"), ("diagnosis", "diagnosis")):
        if failure.get(key):
            parts.append(f"{label}: {failure[key]}")
    return "; ".join(parts) or "The run stopped without a recorded failure."


def claude_command(run: dict[str, Any], spec_path: str, failure: dict[str, Any] | None) -> list[str]:
    """The `claude` argv: resume the run's session, or start a new one that names the spec, the run record and the failure."""
    claude = shutil.which("claude") or "claude"
    summary = _failure_summary(failure)
    session = run.get("session_id")
    if session:
        return [claude, "--resume", str(session), f"The run {run.get('run_id')} stopped. {summary}"]
    prompt = (f"Continue the run {run.get('run_id')} for the spec {spec_path} (run record: {run.get('run_id')}). "
              f"It stopped with this failure. {summary}")
    return [claude, prompt]


def _osascript_argv(argv: list[str], cwd: str) -> list[str]:
    command = f"cd {shlex.quote(cwd)} && {shlex.join(argv)}"
    escaped = command.replace("\\", "\\\\").replace('"', '\\"')
    return ["osascript", "-e", f'tell application "Terminal" to do script "{escaped}"',
            "-e", 'tell application "Terminal" to activate']


def open_terminal(argv: list[str], cwd: str) -> bool:
    """Start `argv` in a new terminal window in `cwd`. False when no terminal is available (the console shows the command)."""
    try:
        if sys.platform == "darwin":
            if not shutil.which("osascript"):
                return False
            subprocess.Popen(_osascript_argv(argv, str(cwd)))  # noqa: S603
            return True
        terminal = os.environ.get("TERMINAL") or shutil.which("x-terminal-emulator")
        if not terminal or not shutil.which(terminal):
            return False
        subprocess.Popen([terminal, "-e", *argv], cwd=str(cwd))  # noqa: S603
        return True
    except OSError:
        return False


def links_for_work(run: dict[str, Any]) -> list[dict[str, str]]:
    """The pull request, the CI run and the run record of a run, as `{label, url}` entries (missing ones are left out)."""
    links: list[dict[str, str]] = []
    pr = run.get("pr") or {}
    if pr.get("url"):
        links.append({"label": f"PR #{pr.get('number')}" if pr.get("number") else "PR", "url": pr["url"]})
    if run.get("ci_url"):
        links.append({"label": "CI run", "url": run["ci_url"]})
    record = run.get("record_url") or run.get("store_url")
    if record:
        links.append({"label": "Run record", "url": record})
    return links


def links_for_instance(system: str, component: str, env: str, settings: dict[str, Any]
                       ) -> tuple[dict[str, str] | None, str]:
    """Argo CD, Grafana and logs links from `console.links.<env>` templates; `(None, reason)` when none is configured."""
    templates = (((settings or {}).get("console") or {}).get("links") or {}).get(env)
    if not isinstance(templates, dict):
        return None, f"No links are configured for {env}: set console.links.{env}.argocd, .grafana and .logs in settings.yml."
    links = {}
    for kind in LINK_KINDS:
        template = templates.get(kind)
        if isinstance(template, str) and template:
            links[kind] = template.format(system=system, component=component, env=env)
    if not links:
        return None, f"console.links.{env} has no argocd, grafana or logs template."
    return links, ""
