"""`smoke`: run a repo's smoke tests against a deployed environment (spec 091, ADR-040).

Every deployable template ships `devbox run smoke`, which prints the same result lines whatever the runner (`PASS|FAIL|SKIP  <id>`
and `smoke: <p> passed, <f> failed, <s> skipped`). This module reads only those lines, so it has no per-shape code. Ship deploy
(spec 091) and the staging promotion (spec 093) use `run_smoke`, `file_issue` and `SmokeResult.section`.

  cplat smoke run [--env dev] [--base-url URL] [--spec SPEC] [--timeout 600] [--no-retry] [--json]

Exit codes: 0 passed or passed on retry, 1 red or timed out, 3 not run. It files no issue and touches no ship state.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import autoissue
import core
import feedback
import spec as specmod
from core import PlatformError, run

OUTCOMES = ("passed", "passed-on-retry", "red", "timed-out", "not-run")
LIMIT_S, RETRY_DELAY_S, TAIL_LINES = 600, 30, 60
ENV_ATTEMPTS = 3                    # spec 105: an environment failure is tried up to 3 times in total
GATEWAY = {502, 503, 504}
RECIPE_FAILED = "(smoke recipe)"
TIMED_OUT = "(timed out)"
DEFAULT_LOCAL_PORT = 8088
RESULT = re.compile(r"^(PASS|FAIL|SKIP)  (\S.*?)\s*$")
SUMMARY = re.compile(r"^smoke: (\d+) passed, (\d+) failed, (\d+) skipped\s*$")
WORDS = {"PASS": "passed", "FAIL": "failed", "SKIP": "skipped"}
KINDS = {v: k for k, v in WORDS.items()}


def gh(args: list[str], *, cwd: Path | None = None, check: bool = True) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *args], cwd=cwd, check=check).stdout


def sleep(seconds: float) -> None:   # tests replace this
    time.sleep(seconds)


def monotonic() -> float:            # tests replace this
    return time.monotonic()


@dataclass
class Attempt:
    exit_code: int | None            # None: timed out
    tests: list[tuple[str, str]]     # ("PASS" | "FAIL" | "SKIP", id) in run order
    passed: int
    failed: int
    skipped: int
    output: str
    duration_s: float


@dataclass
class SmokeResult:
    env: str
    outcome: str
    base_url: str | None
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    tests: list[dict] = field(default_factory=list)
    failing: list[str] = field(default_factory=list)
    flaky: list[str] = field(default_factory=list)
    retried: bool = False
    duration_s: float = 0.0
    reason: str | None = None
    tail: str = ""
    criteria: dict[str, str] = field(default_factory=dict)
    digest: str | None = None            # spec 105: the image digest the cluster ran when the smoke started
    failure_class: str | None = None     # spec 105: "environment" | "application" for a red run
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return self.outcome in {"passed", "passed-on-retry"}

    def row(self, issue: str | None = None) -> str:
        """The `Smoke (dev)` value of the final report. `issue` is a URL, or `not filed: <reason>`."""
        if self.outcome == "passed":
            return f"{self.passed}/{self.passed + self.failed + self.skipped} passed"
        if self.outcome == "passed-on-retry":
            return "passed on retry"
        if self.outcome == "not-run":
            return f"not run: {self.reason}"
        return f"red ({len(self.failing)} failing" + (f", issue {issue}" if issue else "") + ")"

    def unchecked(self) -> list[str]:
        return [ac for ac, v in self.criteria.items() if v == "unchecked"]

    def lines(self) -> list[str]:
        if self.outcome == "not-run":
            return [f"smoke not run: {self.reason}", f"unchecked (smoke) criteria: {', '.join(self.criteria) or 'none'}"]
        out = [f"smoke ({self.env}) against {self.base_url}:"]
        out += [f"{KINDS[t['result']]}  {t['id']}" for t in self.tests]
        if self.outcome == "timed-out":
            out.append(self.reason or f"timed out after {LIMIT_S}s")
        else:
            out.append(f"smoke: {self.passed} passed, {self.failed} failed, {self.skipped} skipped")
        if self.retried:
            out.append(f"retried after {RETRY_DELAY_S}s: " + (f"{len(self.failing)} failing again" if not self.ok else "passed"))
        out += [f"criterion {ac} (smoke): {v}" for ac, v in self.criteria.items()]
        if not self.ok:
            if self.failure_class:
                out.append(f"failure class: {self.failure_class}")
            out.append("failing: " + ", ".join(self.failing))
            out.append(f"--- smoke output (last {TAIL_LINES} lines, secrets redacted) ---")
            out += self.tail.splitlines()
        return out

    def section(self, filed: dict | None = None) -> dict:
        return {"env": self.env, "outcome": self.outcome, "base_url": self.base_url, "passed": self.passed,
                "failed": self.failed, "skipped": self.skipped, "total": self.passed + self.failed + self.skipped,
                "duration_s": round(self.duration_s, 1), "retried": self.retried, "flaky": list(self.flaky),
                "reason": self.reason, "criteria": dict(self.criteria), "failing": list(self.failing), "filed": filed,
                "digest": self.digest, "class": self.failure_class, "attempts": self.attempts}


# ---------------- the recipe ----------------

def has_recipe(repo: Path) -> bool:
    try:
        data = json.loads((repo / "devbox.json").read_text())
    except (OSError, ValueError):
        return False
    scripts = (data.get("shell") or {}).get("scripts") if isinstance(data, dict) else None
    return isinstance(scripts, dict) and "smoke" in scripts


def parse(output: str, exit_code: int | None) -> tuple[list[tuple[str, str]], int, int, int]:
    """Only the contract lines count. A recipe that failed without a FAIL line is one failure."""
    tests: list[tuple[str, str]] = []
    counts: tuple[int, int, int] | None = None
    for ln in output.splitlines():
        if m := RESULT.match(ln):
            tests.append((m.group(1), m.group(2)))
        elif m := SUMMARY.match(ln):
            counts = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if exit_code not in (0, None) and not any(k == "FAIL" for k, _ in tests):
        tests.append(("FAIL", RECIPE_FAILED))
        counts = None
    p, f, s = counts or tuple(sum(1 for k, _ in tests if k == w) for w in ("PASS", "FAIL", "SKIP"))
    return tests, p, f, s


def run_recipe(repo: Path, base_url: str, timeout: float) -> Attempt:
    """`devbox run smoke` against `base_url` in its own process group; at `timeout` the whole group is killed."""
    t0 = monotonic()
    env = {**os.environ, "SMOKE_BASE_URL": base_url}
    try:
        proc = subprocess.Popen(["devbox", "run", "smoke"], cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", start_new_session=True)
    except OSError as e:
        out = f"cannot run `devbox run smoke`: {e}"
        return Attempt(127, [("FAIL", RECIPE_FAILED)], 0, 1, 0, out, monotonic() - t0)
    timed_out = False
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            out = ""
    out = out or ""
    if timed_out:
        return Attempt(None, [], 0, 0, 0, out, monotonic() - t0)
    tests, p, f, s = parse(out, proc.returncode)
    return Attempt(proc.returncode, tests, p, f, s, out, monotonic() - t0)


def reachable(url: str, timeout: float = 10.0) -> str | None:
    """None when `url` answers with any HTTP status; else the error text."""
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout).close()
    except urllib.error.HTTPError:
        return None
    except urllib.error.URLError as e:
        return str(e.reason)
    except Exception as e:  # noqa: BLE001  (timeouts, TLS, resets: all mean unreachable)
        return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
    return None


def status(url: str, timeout: float = 10.0) -> int | str:
    """The HTTP status `url` answers with, or the error text when it does not answer (tests replace this)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return int(e.code)
    except urllib.error.URLError as e:
        return str(e.reason)
    except Exception as e:  # noqa: BLE001  (timeouts, TLS, resets: all mean unreachable)
        return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


def classify(base_url: str, attempt: Attempt) -> str:
    """Spec 105: `environment` when the base URL does not answer (or answers 502/503/504) and every test of the attempt
    failed; otherwise `application`."""
    if not attempt.tests or any(k != "FAIL" for k, _ in attempt.tests):
        return "application"
    try:
        answer = status(base_url)
    except Exception:  # noqa: BLE001  (a probe never changes the outcome)
        return "application"
    return "environment" if isinstance(answer, str) or answer in GATEWAY else "application"


# ---------------- results ----------------

def not_run(env: str, reason: str, smoke_acs: list[str]) -> SmokeResult:
    return SmokeResult(env=env, outcome="not-run", base_url=None, reason=reason, criteria={ac: "unchecked" for ac in smoke_acs})


def _failing(a: Attempt) -> list[str]:
    return sorted(i for k, i in a.tests if k == "FAIL")


def _tail(a: Attempt) -> str:
    lines = [ln for ln in a.output.splitlines() if ln.strip()][-TAIL_LINES:]
    return feedback.redact("\n".join(lines))


def _criteria(repo: Path, spec: specmod.Spec | None, tests: list[tuple[str, str]]) -> dict[str, str]:
    if spec is None or not spec.smoke_acs():
        return {}
    shape = spec.meta.get("shape") or specmod.repo_shape(repo)
    tag = specmod.smoke_tag(shape)
    files = specmod.smoke_trace(repo, spec, specmod.smoke_globs(shape), tag) if tag else {}
    out: dict[str, str] = {}
    for ac in spec.smoke_acs():
        mine = set(files.get(ac, []))
        got = {w: any(i.split("::", 1)[0] in mine for k, i in tests if k == w) for w in ("PASS", "FAIL")}
        out[ac] = "failed" if got["FAIL"] else "passed" if got["PASS"] else "unchecked"
    return out


def _result(repo: Path, spec: specmod.Spec | None, env: str, url: str, a: Attempt, outcome: str, **kw) -> SmokeResult:
    failing = [TIMED_OUT] if outcome == "timed-out" else _failing(a)
    return SmokeResult(
        env=env, outcome=outcome, base_url=url, passed=a.passed, failed=a.failed, skipped=a.skipped,
        tests=[{"id": i, "result": WORDS[k]} for k, i in a.tests], failing=[] if outcome.startswith("passed") else failing,
        tail="" if outcome.startswith("passed") else _tail(a), criteria=_criteria(repo, spec, a.tests), **kw)


def run_smoke(repo: Path, base_url: str, *, env: str = "dev", spec: specmod.Spec | None = None, timeout: float = LIMIT_S,
              retry_delay: float = RETRY_DELAY_S, retry: bool = True, probe: str | None = None) -> SmokeResult:
    """Run the repo's smoke recipe against `base_url`. A failing or missing runner is an outcome, never an exception."""
    acs = spec.smoke_acs() if spec else []
    base_url = base_url.rstrip("/")
    if not has_recipe(repo):
        return not_run(env, "the repo has no smoke recipe (update it with /shared:update-service)", acs)
    if probe and (err := reachable(base_url + probe)):
        return not_run(env, f"dev URL {base_url} is not reachable: {err}" if env == "dev" else f"{env} URL {base_url} is not reachable: {err}", acs)
    t0 = monotonic()
    first = run_recipe(repo, base_url, timeout)
    if first.exit_code is None:
        return _result(repo, spec, env, base_url, first, "timed-out", duration_s=monotonic() - t0, reason=f"timed out after {int(timeout)}s")
    if first.exit_code == 0 and not first.failed:
        return _result(repo, spec, env, base_url, first, "passed", duration_s=monotonic() - t0)
    cls = classify(base_url, first)
    if not retry:
        return _result(repo, spec, env, base_url, first, "red", duration_s=monotonic() - t0, failure_class=cls)
    attempts, last, flaky = 1, first, _failing(first)
    while attempts < (ENV_ATTEMPTS if cls == "environment" else 2):
        if attempts >= 2 and monotonic() - t0 + retry_delay > timeout:
            break                                  # no attempt starts past the limit (AC-091.8)
        sleep(retry_delay)
        last = run_recipe(repo, base_url, timeout)
        attempts += 1
        took = monotonic() - t0
        if last.exit_code is None:
            return _result(repo, spec, env, base_url, last, "timed-out", duration_s=took, retried=True, attempts=attempts,
                           reason=f"timed out after {int(timeout)}s")
        if last.exit_code == 0 and not last.failed:
            return _result(repo, spec, env, base_url, last, "passed-on-retry", duration_s=took, retried=True, flaky=flaky,
                           attempts=attempts)
        cls = classify(base_url, last)
    return _result(repo, spec, env, base_url, last, "red", duration_s=monotonic() - t0, retried=True, attempts=attempts,
                   failure_class=cls)


# ---------------- the dev URL ----------------

def _slug(repo: Path) -> str:
    url = run(["git", "remote", "get-url", "origin"], cwd=repo, check=False).stdout.strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    return m.group(1) if m else repo.name


def _read(slug: str, path: str, repo: Path) -> dict | None:
    try:
        text = gh(["api", f"repos/{slug}/contents/{path}", "-H", "Accept: application/vnd.github.raw"], cwd=repo, check=False)
        data = yaml.safe_load(text) if text and text.strip() else None
    except (PlatformError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _app_dirs(slug: str, repo: Path) -> list[str] | None:
    try:
        data = json.loads(gh(["api", f"repos/{slug}/contents/applications"], cwd=repo, check=False) or "null")
    except (PlatformError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return [e["name"] for e in data if isinstance(e, dict) and e.get("type") == "dir" and e.get("name")]


def dev_url(repo: Path, apps: list[str], service: str, *, env: str = "dev") -> tuple[str | None, str | None]:
    """(url, None) or (None, reason): the URL the linked gitops-app publishes for the service (same values as the HTTPRoute)."""
    me = _slug(repo)
    unread: list[str] = []
    for slug in apps:
        dirs = _app_dirs(slug, repo)
        if dirs is None:
            unread.append(slug)
            continue
        for a in dirs:
            services = _read(slug, f"applications/{a}/services.yaml", repo)
            entries = [e for e in (services or {}).get("services") or [] if isinstance(e, dict)]
            entry = next((e for e in entries if e.get("repo") == me), None) or next((e for e in entries if e.get("name") == service), None)
            if entry is None:
                continue
            hidden = f"{service} has no {env} URL (not exposed in {env})"
            expose = entry.get("expose")
            if not expose or env not in (entry.get("environments") or ["dev"]):
                return None, hidden
            app = _read(slug, f"applications/{a}/app.yaml", repo) or {}
            template = (app.get("hosts") or {}).get(env)
            if not template:
                return None, hidden
            name = entry.get("name") or service
            host = str(template).format(service=(expose.get("host") if isinstance(expose, dict) else None) or name, app=a, env=env)
            urls = app.get("urls") or {}
            if urls.get(env):
                return str(urls[env]).format(host=host, service=name, app=a, env=env), None
            if host.endswith(".localhost"):
                port = os.environ.get("LOCAL_HTTP_PORT", "")
                return f"http://{host}:{port if port.isdigit() else DEFAULT_LOCAL_PORT}", None
            return f"https://{host}", None
    if unread and len(unread) == len(apps):
        return None, f"{service} has no {env} URL (could not read the gitops-app {', '.join(unread)})"
    return None, f"{service} has no {env} URL (not in the linked gitops-app)"


def liveness_probe(repo: Path) -> str | None:
    """The shape's liveness path from shapes.yml, for the reachability check."""
    try:
        import shapecmd
        shape = shapecmd.route(repo)["shape"]
        entry = next(s for s in core.registry.load() if s["id"] == shape)
        return ((entry.get("runtime") or {}).get("probes") or {}).get("liveness")
    except (PlatformError, StopIteration, KeyError):
        return None


# ---------------- the issue (spec 088's convention) ----------------

def issue_draft(result: SmokeResult, *, service_slug: str, spec_id: str | None, image: str | None, run_id: str | None,
                shape: str) -> autoissue.Draft:
    failing = sorted(result.failing)
    details = (f"- spec: {spec_id or 'none'}\n- image: {image or 'unknown'}\n- environment: {result.env}\n"
               f"- base URL: {result.base_url}\n- failure class: {result.failure_class or 'unknown'}\n- failing tests:\n" + "\n".join(f"  - {i}" for i in failing))
    return autoissue.Draft(
        kind="smoke", signature=autoissue.signature("smoke", service_slug, result.env, "\n".join(failing)),
        reason=f"Smoke red in {result.env}: " + ", ".join(failing), command="cplat ship deploy", phase="deploy",
        evidence="\n".join(result.tail.splitlines()[-TAIL_LINES:]), run_id=run_id, shape=shape, repo=service_slug, names={},
        sections=[("Smoke", details)])


def file_issue(result: SmokeResult, **draft_kw) -> autoissue.Outcome:
    """File or +1 the smoke issue in the service repo. Never raises."""
    sig = ""
    try:
        draft = issue_draft(result, **draft_kw)
        sig = draft.signature
        return autoissue.file(draft, run_id=draft_kw.get("run_id"))
    except Exception as e:  # noqa: BLE001  (a filing never changes the run)
        return autoissue.Outcome("pending", sig, None, None, [f"issue: not filed: {type(e).__name__}: {e}"])


# ---------------- CLI ----------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat smoke")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="run the repo's smoke tests against an environment")
    p.add_argument("--repo", default=".")
    p.add_argument("--env", default="dev")
    p.add_argument("--base-url")
    p.add_argument("--spec")
    p.add_argument("--timeout", type=float, default=LIMIT_S)
    p.add_argument("--no-retry", action="store_true")
    p.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    repo = Path(ns.repo).resolve()
    sp = specmod.find(repo, ns.spec) if ns.spec else None
    acs = sp.smoke_acs() if sp else []
    url, why = ns.base_url, None
    if not url:
        if ns.env != "dev":
            raise PlatformError(f"--env {ns.env} needs --base-url", hint="only dev resolves its URL from the gitops-app")
        import ship
        apps = ship.gitops_apps(repo)
        url, why = dev_url(repo, apps, ship.service_name(repo), env=ns.env) if apps else (None, "the repo is not linked to a gitops-app")
    if url:
        res = run_smoke(repo, url, env=ns.env, spec=sp, timeout=ns.timeout, retry=not ns.no_retry, probe=liveness_probe(repo))
    else:
        res = not_run(ns.env, why or "no URL", acs)
    if ns.json:
        print(json.dumps({"smoke": res.section(), "tests": res.tests}, indent=2))
    else:
        print("\n".join(res.lines()))
    return {"passed": 0, "passed-on-retry": 0, "red": 1, "timed-out": 1}.get(res.outcome, 3)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
