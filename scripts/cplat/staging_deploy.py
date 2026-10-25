"""`cplat ship deploy` promotes a build to staging after its green dev smoke (spec 093, ADR-041).

`promote` asks `staging.decide`, dispatches the gitops-app's `pin-staging` workflow, waits for its self-merging PR and for Argo
CD to run the build (at most `STAGING_WINDOW_S` from the green dev smoke), runs the staging smoke and records the outcome.
`resume` continues after an escalation. Both return `(ok, lines)`; `ship` imports this module and this module imports `ship`
lazily, so there is no import cycle. Staging is never rolled back: a red staging smoke escalates with cause `code`.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import autoissue
import core
import runs
import smoke
import staging
from core import PlatformError

STAGING_WINDOW_S = 900


def sleep(seconds: float) -> None:   # tests replace this (default: ship's)
    import ship
    ship.sleep(seconds)


def now() -> float:                   # tests replace this (default: ship's)
    import ship
    return ship.now()


def _utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _section(repo: Path, st: dict) -> dict:
    return st.setdefault("staging", {})


def _set(repo: Path, st: dict, **kw) -> None:
    import ship
    _section(repo, st).update(kw)
    ship.save_state(repo, st)


def _record(repo: Path, st: dict, *, result: str | None = None, smoke_section: dict | None = None) -> None:
    """The run record's `promotion` and `smoke.staging` sections. Never raises."""
    try:
        import ship
        s = _section(repo, st)
        rid = ship._ensure_run(repo, st)

        def change(rec: dict) -> None:
            if result:
                rec["promotion"] = {"staging": {"result": result, "reason": s.get("reason"), "app": s.get("app"), "tag": s.get("tag"),
                                                "previous": s.get("previous"), "pr": s.get("pr")}}
            if smoke_section is not None:
                rec.setdefault("smoke", {})["staging"] = smoke_section
        runs.mutate(rid, change)
    except Exception:  # noqa: BLE001  (a recording never changes the deploy)
        pass


def skip(repo: Path, st: dict, reason: str, lines: list[str], *, result: str = "skipped") -> list[str]:
    """Record `not promoted: <reason>` (state, run record, report line)."""
    row = f"Promotion (staging): not promoted: {reason}"
    _section(repo, st).update(state="skipped", reason=reason, row=row)
    _record(repo, st, result=result)
    return [*lines, row]


def _escalate(repo: Path, st: dict, reason: str, cause: str, lines: list[str], tail: str | None = None) -> tuple[bool, list[str]]:
    import ship
    ship.save_state(repo, st)
    ship.escalate(repo, reason, cause, report=lines)
    lines.append(tail or f"ship {st['spec']}: escalated ({reason}). Resume with /svc:ship {st['spec']}")
    return False, lines


def _pr(repo: Path, app: str, branch: str) -> dict | None:
    import ship
    try:
        prs = json.loads(ship.gh(["pr", "list", "-R", app, "--state", "all", "--head", branch, "--json", "number,state,url"],
                                 cwd=repo, check=False) or "[]")
    except ValueError:
        return None
    return prs[0] if prs else None


def _find_run(repo: Path, app: str, svc: str, tag: str) -> str | None:
    import ship
    try:
        rs = json.loads(ship.gh(["run", "list", "-R", app, "--workflow", "pin-staging", "--limit", "30",
                                 "--json", "databaseId,displayTitle"], cwd=repo, check=False) or "[]")
    except ValueError:
        return None
    hit = [r for r in rs if r.get("displayTitle") == staging.run_name(svc, tag)]
    return str(hit[0]["databaseId"]) if hit else None


def _run_view(repo: Path, app: str, rid: str) -> dict:
    import ship
    try:
        return json.loads(ship.gh(["run", "view", rid, "-R", app, "--json", "status,conclusion,url"], cwd=repo, check=False) or "{}")
    except ValueError:
        return {}


def promote(repo: Path, st: dict, apps: list[str], svc: str, dev: smoke.SmokeResult, context: str | None, interval: float,
            *, window: float = STAGING_WINDOW_S) -> tuple[bool, list[str]]:
    import ship
    begin = now()
    d = staging.decide(repo, st, apps, svc, dev)
    if d.action != "promote":
        return True, skip(repo, st, d.reason or "unknown", [])
    lines: list[str] = []
    if len(apps) > 1:
        lines.append(f"staging: promoting in {d.app} only, the first linked gitops-app that lists {svc}")
    tag, app = d.tag, d.app
    sp = ship._smoke_spec(repo, st)
    rid = ship._ensure_run(repo, st)
    _section(repo, st).update(state="dispatched", reason=None, app=app, tag=tag, previous=d.previous, pr=None, row=None)
    ship.save_state(repo, st)
    try:
        staging.gh(["api", f"repos/{app}/dispatches", "-f", "event_type=pin-staging",
                    "-f", f"client_payload[service]={d.service}", "-f", f"client_payload[tag]={tag}",
                    "-f", f"client_payload[spec]={sp.id if sp else st['spec']}", "-f", f"client_payload[smoke]={dev.row()}",
                    "-f", f"client_payload[record]={staging.record_url(rid) or ''}"], cwd=repo, check=True)
    except PlatformError as e:
        st.pop("staging", None)
        return _escalate(repo, st, f"could not start the staging promotion: {e}", "environment", lines)
    lines.append(f"staging: dispatched pin-staging {d.service} {tag} to {app}")
    return _after_dispatch(repo, st, svc, context, interval, window, begin, lines, d.service)


def _after_dispatch(repo: Path, st: dict, svc: str, context: str | None, interval: float, window: float, begin: float,
                    lines: list[str], name: str) -> tuple[bool, list[str]]:
    import ship
    s = _section(repo, st)
    app, tag, previous = s["app"], s["tag"], s.get("previous")
    branch = staging.pr_branch(name, tag)
    watch: ship.RunWatch | None = None
    last = "no pin PR yet"
    while True:
        pr = _pr(repo, app, branch)
        if pr:
            s["pr"] = pr["url"]
            last = f"pin PR {pr['state']}"
            if pr["state"] == "MERGED":
                break
            if pr["state"] == "CLOSED":
                return _pin_failed(repo, st, lines, f"staging pin failed for {name}: {pr['url']} was closed without merging; "
                                                    f"staging keeps {previous}")
        if watch is None and (rid := _find_run(repo, app, name, tag)):
            watch = ship.RunWatch(repo, app, rid, ship.QUEUE_TIMEOUT, st.get("run_id"))
        if watch is not None:
            outcome = watch.poll()
            last += f", pin run {outcome}"
            if outcome == "red":
                v = _run_view(repo, app, watch.rid)
                return _pin_failed(repo, st, lines, f"staging pin failed for {name}: gitops-app CI {v.get('conclusion') or 'failure'} "
                                                    f"({v.get('url') or watch.rid}); staging keeps {previous}",
                                   logs=ship.run_logs(repo, [(app, watch.rid)]))
            if outcome == "green" and not pr:
                row = f"Promotion (staging): staging already runs {tag}"
                _section(repo, st).update(state="skipped", reason=f"staging already runs {tag}", row=row)
                _record(repo, st, result="skipped")
                ship.save_state(repo, st)
                return True, [*lines, row]
        if now() - begin > window:
            return _pin_failed(repo, st, lines, f"staging did not run {tag} within 15 minutes of the green dev smoke ({last})")
        sleep(interval)
    _set(repo, st, state="merged", pr=s["pr"])
    _record(repo, st, result="promoted")
    lines.append(f"staging: pinned {name} to {tag} ({s['pr']}), was {previous}")
    return _argo_and_smoke(repo, st, name, context, interval, window, begin, lines)


def _pin_failed(repo: Path, st: dict, lines: list[str], reason: str, logs: list[str] | None = None) -> tuple[bool, list[str]]:
    _section(repo, st).update(state="pin-failed", reason=reason, row=f"Promotion (staging): {reason}")
    _record(repo, st, result="failed")
    return _escalate(repo, st, reason, "environment", [*lines, *(logs or [])])


def _argo_and_smoke(repo: Path, st: dict, name: str, context: str | None, interval: float, window: float, begin: float,
                    lines: list[str]) -> tuple[bool, list[str]]:
    import ship
    s = _section(repo, st)
    tag = s["tag"]
    if context:
        health = ship.argo_health(context, f"{name}-staging", max(window - (now() - begin), 0), interval,
                                  images={tag, f"sha-{tag.removeprefix('sha-')[:7]}"})
        lines.append(f"Argo CD {name}-staging: {health}")
        if health != "Synced/Healthy":
            return _pin_failed(repo, st, lines, f"{name}-staging is {health} on {tag}")
        return _smoke(repo, st, name, lines, None)
    return _smoke(repo, st, name, lines,
                  "no kube context, so Argo health was not checked (pass --context <kube-context>)")


def _smoke(repo: Path, st: dict, name: str, lines: list[str], not_run: str | None) -> tuple[bool, list[str]]:
    """Step 5: the staging smoke against what staging runs, its record, issue and escalation."""
    import ship
    s = _section(repo, st)
    tag, app, previous, pr = s["tag"], s["app"], s.get("previous"), s.get("pr")
    sp = ship._smoke_spec(repo, st)
    acs = sp.smoke_acs() if sp else []
    if not_run:
        result = smoke.not_run("staging", not_run, acs)
    else:
        url, _why = smoke.dev_url(repo, [app], name, env="staging")
        result = (smoke.run_smoke(repo, url, env="staging", spec=sp, probe=smoke.liveness_probe(repo)) if url
                  else smoke.not_run("staging", f"no staging URL for {name}", acs))
    lines = [*lines, *result.lines()]
    promo = f"Promotion (staging): {tag} ({pr})"
    filed = None
    issue = None
    if not (result.ok or result.outcome == "not-run"):
        out = smoke.file_issue(result, service_slug=ship.service_slug(repo), spec_id=sp.id if sp else st["spec"], image=tag,
                               run_id=st.get("run_id"), shape=core.read_stamp(repo).get("shape", "none"))
        lines += out.lines
        issue = out.url
        if not issue:
            import re
            m = re.search(r"not filed: ([^;]*)", " ".join(out.lines))
            issue = f"not filed: {m.group(1).strip()}" if m else None
        filed = {"signature": out.signature, "url": out.url, "result": out.result}
    row = result.row(issue)
    s.update(state="smoked", reason=None, row=promo,
             smoke={"outcome": result.outcome, "row": row, "url": result.base_url,
                    "signature": autoissue.signature("smoke", ship.service_slug(repo), "staging", "\n".join(sorted(result.failing)))})
    _record(repo, st, result="promoted", smoke_section={**result.section(filed), "image": tag, "at": _utc()})
    ship.save_state(repo, st)
    if result.ok or result.outcome == "not-run":
        return True, [*lines, promo, f"Smoke (staging): {row}"]
    sid = sp.id if sp else st["spec"]
    reason = f"smoke red in staging: {len(result.failing)} failing ({sid})"
    lines.append(promo)
    ok, lines = _escalate(repo, st, reason, "code", lines,
                          f"ship {st['spec']}: escalated ({reason}); staging keeps running {tag} (no automatic rollback: revert "
                          f"{pr} to go back to {previous}). Resume with /svc:ship {st['spec']}")
    lines.append(f"Smoke (staging): {row}")
    return ok, lines


def resume(repo: Path, st: dict, apps: list[str], svc: str, context: str | None, interval: float,
           *, window: float = STAGING_WINDOW_S) -> tuple[bool, list[str]]:
    """Continue a staging promotion that escalated: a pin that failed, or a red staging smoke."""
    s = _section(repo, st)
    app, tag, previous = s.get("app"), s.get("tag"), s.get("previous")
    if s.get("state") == "pin-failed":
        pr = _pr(repo, app, staging.pr_branch(svc, tag))
        state = (pr or {}).get("state")
        if state == "MERGED":
            s["pr"] = pr["url"]
            _record(repo, st, result="promoted")
            return _argo_and_smoke(repo, st, svc, context, interval, window, now(),
                                   [f"resuming: staging pin {pr['url']} was merged"])
        if state == "OPEN":
            reason = f"{s.get('reason')}; fix the gitops-app CI and merge {pr['url']}, or close it"
            return _escalate(repo, st, reason, "environment", [])
        url = (pr or {}).get("url") or s.get("pr") or staging.pr_branch(svc, tag)
        row = f"Promotion (staging): {url} closed without merging; staging keeps {previous}"
        s.update(state="skipped", reason=f"{url} closed without merging", row=row)
        _record(repo, st, result="failed")
        return True, [row]
    return _smoke(repo, st, svc, ["resuming: staging smoke only, against what staging runs now"], None)
