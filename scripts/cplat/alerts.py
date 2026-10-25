"""`cplat alerts poll`: firing alerts become issues (spec 092, ADR 036). Run every 15 minutes by the gitops-app's alerts workflow.

For each `applications/<app>`: read the alert sources (`alertsources`), reconcile them with the issues on GitHub
(`alertissues`), count consecutive failures of the poll itself in a state file, and report. The poll never raises out of
`main`. Exit 1 on source errors, GitHub errors or a rerouted issue; otherwise 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import alertissues
import alertsources
import autoissue
from alertissues import META_SERVICE, POLL_FAILING_NAME
from alertsources import Alert, SourceError
from autoissue import TrackerError

STATE_ARTIFACT = "alert-poll-state"
STATE_VERSION = 1
FAILING_AFTER = 3
DEFAULT_STATE = ".alert-poll/state.json"


def _stamp() -> str:
    return autoissue.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state(gitops_repo: str, state_file: Path) -> dict:
    """The state file if it exists; else the newest unexpired artifact `alert-poll-state`. Nothing found gives {}.
    A gh failure raises TrackerError."""
    state_file = Path(state_file)
    if state_file.exists():
        return _read(state_file)
    code, out, err = autoissue.gh(["api", f"repos/{gitops_repo}/actions/artifacts?name={STATE_ARTIFACT}&per_page=20"])
    if code != 0:
        raise TrackerError(f"cannot list the {STATE_ARTIFACT} artifacts: {autoissue.scrub((err or out).strip())[:200]}")
    try:
        items = json.loads(out).get("artifacts") or []
    except (ValueError, AttributeError) as e:
        raise TrackerError(f"unreadable artifact list: {e}") from e
    live = [a for a in items if isinstance(a, dict) and a.get("name") == STATE_ARTIFACT and not a.get("expired")]
    if not live:
        return {}
    newest = max(live, key=lambda a: str(a.get("created_at") or ""))
    run_id = str((newest.get("workflow_run") or {}).get("id") or "")
    if not run_id:
        return {}
    state_file.parent.mkdir(parents=True, exist_ok=True)
    code, out, err = autoissue.gh(["run", "download", run_id, "-R", gitops_repo, "-n", STATE_ARTIFACT, "-D", str(state_file.parent)],
                                  timeout=60.0)
    if code != 0:
        raise TrackerError(f"cannot download the {STATE_ARTIFACT} artifact: {autoissue.scrub((err or out).strip())[:200]}")
    return _read(state_file) if state_file.exists() else {}


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise TrackerError(f"unreadable poll state {path}: {e}") from e
    return data if isinstance(data, dict) else {}


def _failing_alert(app: str, failures: int, reason: str, gitops_repo: str) -> Alert:
    return Alert(app=app, name=POLL_FAILING_NAME, severity="critical", environment="*", service=META_SERVICE, repo=gitops_repo,
                 started_at=autoissue.now(), summary=f"The alert poll failed {failures} times in a row. Last reason: {reason}",
                 source="rule", query="", series=[])


def poll(repo_dir: Path, *, gitops_repo: str, state_file: Path, dry_run: bool, app: str | None = None,
         write_state: bool = True) -> tuple[int, list[str]]:
    repo_dir = Path(repo_dir)
    lines: list[str] = []
    red = False
    apps_dir = repo_dir / "applications"
    dirs = sorted(d for d in apps_dir.glob("*") if (d / "services.yaml").exists()) if apps_dir.is_dir() else []
    if app:
        dirs = [d for d in dirs if d.name == app]
    state: dict | None = None
    state_loaded = False
    state_tried = False
    new_apps: dict[str, dict] = {}

    for app_dir in dirs:
        name = app_dir.name
        src_errors: list[SourceError] = []
        alerts: list[Alert] = []
        cfg = None
        try:
            cfg = alertsources.load_app(app_dir)
        except SourceError as e:
            src_errors.append(e)
        if cfg is not None and cfg.skip:
            lines.append(f"alert poll {name}: skipped: {cfg.skip}")
            continue
        if cfg is not None:
            alerts, errs = alertsources.collect(cfg, now=autoissue.now())
            src_errors += errs
        if not state_tried:
            state_tried = True
            try:
                state = load_state(gitops_repo, Path(state_file))
                state_loaded = True
            except TrackerError as e:
                lines.append(f"ERROR: {gitops_repo}: {autoissue.scrub(str(e))}")
                red = True
        prev = (((state or {}).get("apps") or {}).get(name) or {}) if state_loaded else {}
        previous = int(prev.get("failures") or 0) if isinstance(prev, dict) else 0
        rule_n = sum(1 for a in alerts if a.source == "rule")
        am_n = len(alerts) - rule_n
        envs = sorted({a.environment for a in alerts})
        failures, reason = 0, ""
        poll_failing = False
        if src_errors:
            failures = previous + 1
            reason = autoissue.scrub(str(src_errors[0]))
            if failures >= FAILING_AFTER:
                alerts = [*alerts, _failing_alert(name, failures, reason, gitops_repo)]
                poll_failing = True
        services = cfg.services if cfg is not None else []
        repos = sorted({s["repo"] for s in services if s.get("repo")} | {gitops_repo})
        where = f" in {', '.join(envs)}" if envs else ""
        lines.append(f"alert poll {name}: {rule_n + am_n} firing{where} ({rule_n} from rules, {am_n} from Alertmanager)")
        if cfg is not None:
            lines += [f"note: {n}" for n in cfg.notes]
        result = alertissues.reconcile(alerts, app=name, gitops_repo=gitops_repo, repos=repos,
                                       tr=alertissues.tracker(gitops_repo), now=autoissue.now(), dry_run=dry_run,
                                       resolve=not src_errors and state_loaded)
        lines += result.lines
        lines += [f"ERROR: {e.endpoint}: {autoissue.scrub(e.reason)}" for e in src_errors]
        lines += [f"ERROR: {autoissue.scrub(e)}" for e in result.errors]
        if src_errors:
            lines.append("no issue was resolved or closed in this run")
        if poll_failing:
            lines.append(f"alert poll is failing for {failures} polls in a row")
        if src_errors or result.errors or result.rerouted:
            red = True
        new_apps[name] = {"failures": failures, "last_reason": reason, "at": _stamp()}

    if new_apps and state_loaded and not dry_run and write_state:
        merged = {"version": STATE_VERSION, "apps": {**((state or {}).get("apps") or {}), **new_apps}}
        sf = Path(state_file)
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")
    return (1 if red else 0), lines


def _gitops_repo(repo_dir: Path, given: str | None) -> str:
    if given:
        return given
    env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if env:
        return env
    answers = Path(repo_dir) / ".copier-answers.yml"
    if answers.exists():
        import yaml
        data = yaml.safe_load(answers.read_text()) or {}
        if data.get("github_org") and data.get("project_name"):
            return f"{data['github_org']}/{data['project_name']}"
    return ""


def _summary(lines: list[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("## Alert poll\n\n" + "".join(f"- {ln}\n" for ln in lines) + "\n")
    except OSError:
        pass


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="cplat alerts", description="firing alerts become issues (spec 092)")
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("poll", help="evaluate the alert sources and reconcile the issues")
    q.add_argument("--repo-dir", default=".")
    q.add_argument("--app")
    q.add_argument("--gitops-repo")
    q.add_argument("--state-file", default=DEFAULT_STATE)
    q.add_argument("--dry-run", action="store_true")
    ns = p.parse_args(argv)
    repo_dir = Path(ns.repo_dir)
    try:
        repo = _gitops_repo(repo_dir, ns.gitops_repo)
        if not repo:
            lines, code = ["ERROR: the gitops repo is unknown: pass --gitops-repo OWNER/NAME"], 1
        else:
            code, lines = poll(repo_dir, gitops_repo=repo, state_file=Path(ns.state_file), dry_run=ns.dry_run, app=ns.app)
    except Exception as e:  # noqa: BLE001  (the poll never raises out of main)
        code, lines = 1, [f"ERROR: unexpected failure: {type(e).__name__}: {autoissue.scrub(str(e))}"]
    for ln in lines:
        print(ln)
    _summary(lines)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
