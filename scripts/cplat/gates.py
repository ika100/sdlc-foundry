"""Gates that can fail (spec 081): static checks that a repo's CI gates are real, used by `cplat platform doctor` and `cplat adopt`.

A gate can pass while checking nothing: a secrets baseline without its filters, a scanner that changes with every
machine, a `ci` recipe that skips a job, or a CI workflow that never runs a gate. Each check here is a file read, so it
costs no CI time, and each problem comes with its one-line fix.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

OK, WARN, FAIL = "ok", "warn", "fail"
GATES = ("quality", "test", "security")
CI_EXTRA = "ci-extra"
# The step every template's `ci` recipe ends with (spec 086), decoded: runs the repo's own `ci-extra` recipe when it exists.
CI_EXTRA_STEP = "if grep -qs '\"ci-extra\"[[:space:]]*:' devbox.json; then devbox run ci-extra; fi"
GIBBERISH = "detect_secrets.filters.gibberish.should_exclude_secret"


def _check(status: str, name: str, detail: str, fix: str | None = None) -> dict:
    return {"status": status, "name": name, "detail": detail, "fix": fix}


def recipes(repo: Path) -> dict[str, str]:
    f = repo / "devbox.json"
    try:
        return json.loads(f.read_text()).get("shell", {}).get("scripts", {}) if f.is_file() else {}
    except ValueError:
        return {}


def packages(repo: Path) -> dict[str, str]:
    f = repo / "devbox.json"
    try:
        pkgs = json.loads(f.read_text()).get("packages", []) if f.is_file() else []
    except ValueError:
        return {}
    pkgs = pkgs if isinstance(pkgs, list) else list(pkgs)
    return dict(p.split("@", 1) if "@" in p else (p, "latest") for p in pkgs)


def workflow_gates(repo: Path) -> list[str]:
    """The `devbox run <gate>` steps of .github/workflows/ci.yml, in job order."""
    f = repo / ".github" / "workflows" / "ci.yml"
    if not f.is_file():
        return []
    try:
        jobs = (yaml.safe_load(f.read_text()) or {}).get("jobs") or {}
    except yaml.YAMLError:
        return []
    out: list[str] = []
    for job in jobs.values():
        for step in (job or {}).get("steps") or []:
            m = re.fullmatch(r"devbox run ([\w-]+)", str((step or {}).get("run", "")).strip())
            if m and m.group(1) not in out:
                out.append(m.group(1))
    return out


def chain(cmd: str) -> list[str]:
    """The `devbox run <name>` steps of a recipe, in order."""
    return re.findall(r"devbox run ([\w-]+)", cmd)


def _real(name: str, scripts: dict[str, str], seen: tuple = ()) -> str:
    """A recipe that is only `devbox run X` is the gate X (gitops-app: quality = validate). `ci-extra` stays itself."""
    if name == CI_EXTRA:
        return name
    m = re.fullmatch(r"devbox run ([\w-]+)", scripts.get(name, "").strip())
    return _real(m.group(1), scripts, (*seen, name)) if m and m.group(1) not in seen else name


def ci_gaps(repo: Path) -> list[str]:
    """Template gates (quality, test, security) that no job of the repo's CI runs through `devbox run`."""
    scripts = recipes(repo)
    have = {_real(g, scripts) for g in workflow_gates(repo)}
    return [g for g in GATES if g in scripts and _real(g, scripts) not in have]


def check_gates(repo: Path) -> list[dict]:
    if not (repo / "devbox.json").is_file():
        return []
    out: list[dict] = []
    scripts, pkgs = recipes(repo), packages(repo)
    base = repo / ".secrets.baseline.json"
    if base.is_file():
        try:
            paths = {f.get("path") for f in json.loads(base.read_text()).get("filters_used", [])}
        except ValueError:
            paths = set()
        if "detect_secrets.filters.allowlist.is_line_allowlisted" not in paths:
            out.append(_check(FAIL, "gate secrets baseline", "the baseline lists no standard filters, so the scan is not "
                              "what CI checks and `pragma: allowlist secret` does nothing", "devbox run secrets-baseline, audit, commit"))
        elif GIBBERISH in paths:
            out.append(_check(FAIL, "gate secrets baseline", "the baseline uses the gibberish filter, which only some "
                              "machines can apply", "devbox run secrets-baseline, audit, commit"))
        else:
            out.append(_check(OK, "gate secrets baseline", "standard filters, no gibberish filter"))
    for tool in ("detect-secrets", "trivy"):
        if tool in pkgs:
            v = pkgs[tool]
            out.append(_check(OK, f"gate {tool} pinned", v) if v != "latest" else
                       _check(FAIL, f"gate {tool} pinned", "@latest: local and CI can disagree",
                              f"pin it in devbox.json (the template's version: /platform:update)"))
    missing = [r for r in ("ci", "secrets-baseline") if r not in scripts]
    out.append(_check(WARN, "gate recipes", "missing: " + ", ".join(missing), "/platform:update adds them") if missing else
               _check(OK, "gate recipes", "ci, secrets-baseline"))
    wf = workflow_gates(repo)
    if "ci" in scripts and wf:
        chained = chain(scripts["ci"])
        real = [_real(g, scripts) for g in chained]
        want = [_real(g, scripts) for g in wf]
        name = "gate ci = CI workflow"
        if CI_EXTRA in scripts and CI_EXTRA not in want:
            out.append(_check(WARN, name, "CI does not run ci-extra: no job of .github/workflows/ci.yml runs devbox run ci-extra",
                              "/platform:update"))
        elif real == want:
            if CI_EXTRA in scripts:
                inner = " → ".join(chain(scripts[CI_EXTRA])) or scripts[CI_EXTRA]
            else:
                inner = "not defined"
            shown = [f"{g} ({inner})" if g == CI_EXTRA else g for g in chained]
            out.append(_check(OK, name, " → ".join(shown)))
        else:
            extra = [g for g, r in zip(chained, real) if r not in want and r != CI_EXTRA]
            if extra:
                cur = scripts.get(CI_EXTRA, "").strip()
                value = " && ".join([*([cur] if cur else []), *(f"devbox run {g}" for g in extra)])
                out.append(_check(WARN, name, f"`devbox run ci` runs {' → '.join(chained) or 'nothing'}, the "
                                  f"workflow runs {' → '.join(want)}",
                                  f'move {", ".join(extra)} into ci-extra: "ci-extra": "{value}" '
                                  "(updates replace the ci recipe; CI runs ci-extra)"))
            else:
                out.append(_check(WARN, name, f"`devbox run ci` runs {' → '.join(real) or 'nothing'}, the "
                                  f"workflow runs {' → '.join(want)}", "make the ci recipe chain the workflow's gates in its order"))
    gaps = ci_gaps(repo)
    if gaps:
        out.append(_check(WARN, "gate CI jobs", "no CI job runs " + ", ".join(f"`devbox run {g}`" for g in gaps),
                          "copy the template's job(s) " + ", ".join(gaps) + " from its .github/workflows/ci.yml"))
    return out
