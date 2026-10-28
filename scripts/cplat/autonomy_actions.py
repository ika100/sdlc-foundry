# SPDX-FileCopyrightText: 2026 Eike Hensler
#
# SPDX-License-Identifier: Apache-2.0
"""`cplat system autonomy undo|approve`: the two person actions on what an engine did (spec 124, AC-124.16, AC-124.17).

`undo` takes back an engine's merge (a revert pull request), promotion or rollback (a pin pull request through `promote`) or
dismissal (the issue is reopened). `approve` approves an engine fix PR and merges it once every check passed. Both write an audit
event. Refusals exit 1 with the reason on stderr; `--dry-run` changes nothing.
"""
from __future__ import annotations

import json as jsonlib
import re
import sys
from pathlib import Path

import audit
import gitops
import model
import runlist
import runs
from core import PlatformError, run

TARGET = re.compile(r"^([\w.-]+/[\w.-]+)#(\d+)$")
_REVERT = ("mutation($id: ID!, $title: String!, $body: String!) { revertPullRequest(input: {pullRequestId: $id, title: $title, "
           "body: $body}) { revertPullRequest { number url } } }")


def gh(args: list[str]) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *[str(a) for a in args]]).stdout


def pr_wait(number: int, repo: str) -> int:
    """`cplat pr wait <n> -R <repo> --merge`: merge when every check passed (tests replace this)."""
    import pr
    import ship
    ok, lines = pr.wait(Path.cwd(), pr.url_of(str(number), repo), True, 3600, 20, ship.QUEUE_TIMEOUT, repo)
    print("\n".join(lines), file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def _login() -> str:
    return gh(["api", "user", "-q", ".login"]).strip() or "unknown"


def _refuse(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _emit(plan: list[str], as_json: bool, extra: str = "") -> None:
    if as_json:
        print(jsonlib.dumps({"will_do": plan}, indent=2))
    else:
        print("\n".join(["Would:", *[f"- {p}" for p in plan]]))


def _record(event: dict) -> None:
    reason = runs.record_audit(event)
    if reason:
        print(f"note: {reason}", file=sys.stderr)


def _app(repo_dir: Path) -> tuple[Path, dict]:
    app_dir = gitops.find_app(Path(repo_dir))
    return app_dir, model.load_dir(app_dir).to_dict()


def _previous_args(ev: dict) -> list[str]:
    """The promote flags that pin the event's environment back to the version before the event."""
    prev = str((ev.get("object") or {}).get("previous") or "")
    if ev.get("environment") == "staging":
        return ["--sha", prev.removeprefix("sha-")]
    return ["--version", prev]


def _undo_plan(ev: dict, event_id: str) -> list[str]:
    obj, kind = ev.get("object") or {}, ev.get("kind")
    if kind == "merge":
        return [f"revert {obj.get('repo')}#{obj.get('number')} with a revert pull request ('Undo of {event_id}')"]
    if kind in ("promotion", "rollback"):
        return [f"pin {ev.get('component')} in {ev.get('environment')} back to {obj.get('previous')} with a pull request"]
    return [f"reopen {obj.get('repo')}#{obj.get('number')} with the comment 'Reopened: undo of {event_id}'"]


def _revert(ev: dict, event_id: str, login: str) -> str:
    obj = ev.get("object") or {}
    target = ["pr", "view", obj.get("number"), "-R", obj.get("repo"), "--json", "id,number,state,title,url"]
    doc = jsonlib.loads(gh(target))
    out = gh(["api", "graphql", "-f", f"query={_REVERT}", "-f", f"id={doc['id']}", "-f", f"title=Revert \"{doc['title']}\"",
              "-f", f"body=Undo of {event_id} by {login} (spec 124)."])
    reverted = ((jsonlib.loads(out).get("data") or {}).get("revertPullRequest") or {}).get("revertPullRequest") or {}
    return str(reverted.get("url") or "")


def undo(repo_dir: Path, event_id: str, *, dry_run: bool = False, json: bool = False) -> int:
    """Undo the engine event `event_id` (spec 124, AC-124.16)."""
    events = audit.read(30)
    ev = next((e for e in events if e.get("event_id") == event_id), None)
    if ev is None:
        return _refuse(f"{event_id}: no such audit event in the last 30 days")
    app_dir, doc = _app(repo_dir)
    state = audit.undo_state(ev, doc, events, runs.utcnow())
    if not state["allowed"]:
        return _refuse(f"{event_id} cannot be undone: {state['reason']}")
    plan = _undo_plan(ev, event_id)
    if dry_run:
        _emit(plan, json)
        return 0
    login = _login()
    obj, kind, url = ev.get("object") or {}, ev["kind"], None
    if kind == "merge":
        url = _revert(ev, event_id, login)
        print(f"Revert pull request: {url}")
    elif kind in ("promotion", "rollback"):
        import promote
        argv = [str(ev.get("component")), "--to", str(ev.get("environment")), *_previous_args(ev), "--pr", "--repo-dir", str(repo_dir)]
        rc = promote.main(argv)
        if rc != 0:
            return rc
    else:
        gh(["issue", "reopen", obj.get("number"), "-R", obj.get("repo"), "--comment", f"Reopened: undo of {event_id} by {login}."])
        print(f"Reopened {obj.get('repo')}#{obj.get('number')}")
    _record(audit.person_event("undo", actor=login, system=app_dir.name, environment=ev.get("environment"),
                               object={**obj, "type": obj.get("type") or "pr"}, policy=ev.get("policy") or {},
                               detail={"undone_kind": kind, "pr": url}, undoes=event_id))
    return 0


def _fix_run(number: int, repo: str) -> dict | None:
    for row in runlist.collect(30).get("runs") or []:
        pr = row.get("pr") or {}
        if row.get("kind") == "fix" and row.get("engine") and pr.get("number") == number and (
                row.get("repo") == repo or f"/{repo}/pull/" in str(pr.get("url") or "")):
            return row
    return None


def _approve_review(number: int, repo: str, login: str) -> None:
    try:
        gh(["pr", "review", number, "-R", repo, "--approve", "--body", f"Approved by {login} in the review decision (spec 124)."])
    except PlatformError as e:
        if "own pull request" not in str(e).lower():
            raise
        gh(["pr", "comment", number, "-R", repo, "--body", f"approved by {login} (author is the system owner)"])


def approve(repo_dir: Path, target: str, *, dry_run: bool = False, json: bool = False) -> int:
    """Approve an engine's fix PR and merge it once every check passed (spec 124, AC-124.17)."""
    m = TARGET.match(target)
    if not m:
        return _refuse(f"{target}: expected <owner/repo>#<number>")
    repo, number = m.group(1), int(m.group(2))
    row = _fix_run(number, repo)
    if row is None:
        return _refuse(f"{repo}#{number} is not the pull request of an engine fix run in the last 30 days")
    state = jsonlib.loads(gh(["pr", "view", number, "-R", repo, "--json", "id,number,state,title,url"])).get("state")
    if state != "OPEN":
        return _refuse(f"{repo}#{number} is not open ({str(state).lower()})")
    plan = [f"approve {repo}#{number}", f"merge {repo}#{number} once every check passed (cplat pr wait {number} -R {repo} --merge)"]
    if dry_run:
        _emit(plan, json)
        return 0
    login = _login()
    _approve_review(number, repo, login)
    if pr_wait(number, repo) != 0:
        return _refuse(f"{repo}#{number} is approved but did not merge")
    app_dir, _ = _app(repo_dir)
    pr = row.get("pr") or {}
    _record(audit.person_event("approve", actor=login, system=app_dir.name, environment=row.get("environment"),
                               object={"type": "pr", "repo": repo, "number": number, "url": pr.get("url")},
                               policy=(row.get("fix") or {}).get("policy") or {}, detail={"run_id": row.get("run_id")}))
    return 0
