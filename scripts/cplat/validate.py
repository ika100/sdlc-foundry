"""`cplat validate plan|run|final`: change-aware validation in the inner loop (spec 103, ADR-044).

Public API:

  plan(root, base, full=, risk=) -> dict        the plan: every check of the repo is run / reused / skipped with a rule and a reason
  execute(root, plan) -> int                    run it quietly (one line per check), write evidence, record the `validation` section
  record_final(run_id, check, result)           a final-gate result: a failed check the loop skipped or reused is a miss
  record_final_gate(root)                       after a red `devbox run ci`: attribute the failure to checks (used by ship.run_ci)

  cplat validate plan [--base REF] [--full] [--risk low|medium|high] [--json]
  cplat validate run  [--base REF] [--full] [--risk ...]            exit 0 green, 1 red
  cplat validate final --check NAME passed|failed                   exit 0

Rules, the first match decides (deterministic, no model): full, mandatory:<category>, docs-only, mapped, no rule. An
agent's risk level can only add checks. Evidence of passed checks lives in `<git common dir>/cplat-evidence/<check>.json`
(`{inputs, result, run_id, at}`), never pushed; equal inputs and `passed` make a check `reused`. The final gate
(`devbox run ci`) is not planned here and always runs whole. Recording never raises into a caller.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import core
import quiet
import runs
import settings
import spec as specmod
from core import PlatformError

ORDER = ("lint", "typecheck", "test", "acceptance", "security", "image", "ci-extra")
RISKS = ("low", "medium", "high")
TAIL = 40
CONFIG_FILES = ("pyproject.toml", "uv.lock", "package.json", "pnpm-lock.yaml", "package-lock.json", "pom.xml", "go.mod",
                "go.sum", "devbox.json", "devbox.lock", ".platform-settings.yml")
MANDATORY = {   # category -> globs (spec 103 rule 2); shapes.yml adds per-shape categories
    "dockerfile": ["Dockerfile*", "**/Dockerfile*"],
    "manifest": ["pyproject.toml", "package.json", "pom.xml", "go.mod", "**/pyproject.toml", "**/package.json", "**/pom.xml",
                 "**/go.mod"],
    "lockfile": ["uv.lock", "pnpm-lock.yaml", "package-lock.json", "go.sum", "**/uv.lock", "**/pnpm-lock.yaml",
                 "**/package-lock.json", "**/go.sum"],
    "ci-workflow": [".github/workflows/**"],
    "secrets": [".secrets.baseline.json", "**/auth*", "**/security*", "**/*secret*"],
    "spec": ["docs/specs/**"],
}
TEST_NAME = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.(py|go)|[^/]*\.(test|spec)\.[jt]sx?|[^/]*Test\.java)$")


# ---------------- small helpers ----------------

def _glob_re(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def matches(path: str, globs: list[str]) -> bool:
    return any(_glob_re(g).match(path) for g in globs)


def _git(root: Path, *args: str) -> tuple[int, str]:
    p = core.run(["git", *args], cwd=root, check=False)
    return p.returncode, p.stdout


def toplevel() -> Path:
    p = core.run(["git", "rev-parse", "--show-toplevel"], cwd=Path.cwd(), check=False)
    if p.returncode != 0 or not p.stdout.strip():
        raise PlatformError("not inside a git repository", hint="run `cplat validate` in the repo to validate")
    return Path(p.stdout.strip())


def default_base(root: Path) -> str:
    for ref in ("origin/main", "main"):
        if _git(root, "rev-parse", "--verify", "-q", ref + "^{commit}")[0] == 0:
            return ref
    return "main"


def changed_files(root: Path, base: str) -> list[str] | None:
    """Files changed against `base` (merge base to HEAD, working tree, untracked); None when the diff cannot be read."""
    out: set[str] = set()
    for args in (("diff", "--name-only", f"{base}...HEAD"), ("diff", "--name-only", "HEAD"),
                 ("ls-files", "-o", "--exclude-standard")):
        code, text = _git(root, *args)
        if code != 0:
            return None
        out |= {ln for ln in text.splitlines() if ln}
    return sorted(out)


def all_files(root: Path) -> list[str]:
    code, text = _git(root, "ls-files", "-co", "--exclude-standard")
    return sorted(f for f in text.splitlines() if f and not specmod._ignored(Path(f))) if code == 0 else []


def shape_entry(root: Path) -> dict:
    shape = specmod.repo_shape(root)
    entry = next((s for s in core.registry.load() if s["id"] == shape), None) if shape else None
    return entry or {}


def is_doc(path: str) -> bool:
    return path.endswith(".md") or path == "LICENSE" or (path.startswith("docs/") and not path.startswith("docs/specs/"))


def _read_text(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(errors="ignore")
    except OSError:
        return ""


# ---------------- the checks of the repo ----------------

def discover(root: Path) -> list[dict]:
    """The checks of `devbox run ci` by name, each with the devbox script that runs it."""
    try:
        scripts = json.loads((root / "devbox.json").read_text()).get("shell", {}).get("scripts", {}) or {}
    except (OSError, ValueError):
        scripts = {}
    test = "test-fast" if "test-fast" in scripts else ("test" if "test" in scripts else None)
    found = {"lint": "lint" if "lint" in scripts else None, "typecheck": "typecheck" if "typecheck" in scripts else None,
             "test": test, "acceptance": test, "security": "security" if "security" in scripts else None,
             "image": "image-build" if "image-build" in scripts and (root / "Dockerfile").is_file() else None,
             "ci-extra": "ci-extra" if "ci-extra" in scripts else None}
    return [{"name": n, "script": found[n]} for n in ORDER if found[n]]


def _entry(check: dict, decision: str, rule: str, reason: str, targets: list[str] | None = None) -> dict:
    return {"name": check["name"], "script": check["script"], "decision": decision, "rule": rule, "reason": reason,
            "targets": targets, "from_run": None}


def _all(checks: list[dict], rule: str, reason: str) -> list[dict]:
    return [_entry(c, "run", rule, reason) for c in checks]


# ---------------- the rules ----------------

def forced_full(full: bool) -> str | None:
    if full:
        return "--full given"
    if os.environ.get("CPLAT_VALIDATION") == "full":
        return "CPLAT_VALIDATION=full"
    return None


def settings_full(root: Path) -> str | None:
    f = root / settings.PROJECT_FILE
    if not f.is_file():
        return None
    try:
        import yaml
        data = yaml.safe_load(f.read_text())
    except Exception as e:  # noqa: BLE001
        raise PlatformError(f"{f} cannot be read: {e}") from None
    value = data.get("validation") if isinstance(data, dict) else None
    if value in (None, "selective"):
        return None
    if value != "full":
        raise PlatformError(f"{f}: validation must be 'full' or 'selective', not '{value}'")
    return f"validation: full in {settings.PROJECT_FILE}"


def mandatory_categories(root: Path, files: list[str], shape: dict) -> dict[str, list[str]]:
    cats = dict(MANDATORY)
    cats.update({k: list(v) for k, v in ((shape.get("validation") or {}).get("mandatory") or {}).items()})
    hit: dict[str, list[str]] = {}
    for f in files:
        for cat, globs in cats.items():
            if matches(f, globs):
                hit.setdefault(cat, []).append(f)
        if (TEST_NAME.search(f) or matches(f, specmod.test_globs(shape.get("id")))) and specmod.AC_ANY.search(_read_text(root, f)):
            hit.setdefault("acceptance-test", []).append(f)
    return hit


def _is_test(path: str, shape: dict) -> bool:
    return bool(TEST_NAME.search(path)) or matches(path, specmod.test_globs(shape.get("id")))


def _task_matches(path: str, task_files: list) -> bool:
    for p in task_files:
        p = str(p)
        if p == path or (p.endswith("/") and path.startswith(p)) or matches(path, [p]):
            return True
    return False


def _unit_tests(path: str, selector: str, files: list[str]) -> list[str]:
    stem = Path(path).stem
    if selector == "pytest":
        pat = f"test_{stem}*.py"
    else:
        pat = f"{stem}.test.*"
    return [f for f in files if fnmatch.fnmatch(Path(f).name, pat) and f != path]


def mapped(root: Path, files: list[str], shape: dict, tracked: list[str]) -> tuple[list[str], list[str], bool] | str:
    """(test targets, acceptance targets, any source changed) or the reason nothing maps."""
    selector = (shape.get("validation") or {}).get("selector")
    if not selector:
        return f"shape {shape.get('id') or 'unknown'} has no test selector"
    specs = specmod.all_specs(root)
    globs = specmod.test_globs(shape.get("id"))
    traces = {s.id: specmod.trace(root, s, globs) for s in specs if s.plan}
    unit: set[str] = set()
    acceptance: set[str] = set()
    sources = False
    for f in files:
        if _is_test(f, shape):
            unit.add(f)
            continue
        sources = True
        tasks = [(s, t) for s in specs if s.plan for t in (s.plan[0].get("tasks") or [])
                 if isinstance(t, dict) and _task_matches(f, t.get("files") or [])]
        if not tasks:
            return f"{f} is in no task of any plan"
        tests = _unit_tests(f, selector, tracked)
        if not tests:
            return f"{f} has no unit tests to select"
        unit.update(tests)
        for s, t in tasks:
            for ac in t.get("covers") or []:
                acceptance.update(traces.get(s.id, {}).get(str(ac), []))
    if sources and not acceptance:
        return "the criteria of the changed files have no traced tests"
    return sorted(unit), sorted(acceptance), sources


def decide(root: Path, checks: list[dict], files: list[str] | None, full: bool, shape: dict, base: str) -> list[dict]:
    why = forced_full(full) or settings_full(root)
    if why:
        return _all(checks, "full", why)
    if files is None:
        return _all(checks, "no rule", f"the diff against {base} cannot be read")
    if not files:
        return _all(checks, "no rule", f"no changed files against {base}")
    cats = mandatory_categories(root, files, shape)
    if cats:
        cat = sorted(cats)[0]
        reason = f"{cat} changed ({cats[cat][0]})"
        return [_entry(c, "run", f"mandatory:{cat}", reason if c["name"] in ("test", "acceptance", "security")
                       else "always runs") for c in checks]
    if all(is_doc(f) for f in files):
        out = []
        for c in checks:
            if c["name"] in ("test", "acceptance", "image"):
                out.append(_entry(c, "skipped", "docs-only", "only documentation changed"))
            else:
                out.append(_entry(c, "run", "docs-only", "always runs" if c["name"] != "ci-extra" else "no rule for this check"))
        return out
    m = mapped(root, files, shape, all_files(root))
    if isinstance(m, str):
        return _all(checks, "no rule", m)
    tests, acc, sources = m
    out = []
    for c in checks:
        n = c["name"]
        if n == "test":
            out.append(_entry(c, "run", "mapped", f"unit tests of the changed components ({len(tests)} file(s))", tests))
        elif n == "acceptance" and sources:
            out.append(_entry(c, "run", "mapped", f"tests naming the criteria of the changed components ({len(acc)} file(s))", acc))
        elif n == "acceptance":
            out.append(_entry(c, "skipped", "mapped", "only tests changed; they run as unit tests"))
        else:
            out.append(_entry(c, "run", "mapped", "always runs" if n in ("lint", "typecheck", "security")
                              else "no rule for this check"))
    return out


def apply_risk(entries: list[dict], risk: str | None) -> dict:
    """Risk can only add checks: `high` widens the selection to the whole checks. Returns the plan's risk section."""
    mandatory = any(e["rule"].startswith("mandatory:") for e in entries)
    added: list[str] = []
    if risk == "high":
        for e in entries:
            if e["decision"] == "skipped":
                e["decision"], e["reason"] = "run", e["reason"] + " (risk high)"
                added.append(f"{e['name']}: run")
            elif e["targets"] is not None:
                e["targets"], e["reason"] = None, e["reason"] + " (risk high: whole suite)"
                added.append(f"{e['name']}: whole suite")
        note = "high risk: skipped checks run and selections widen to the whole suite" if added else "high risk: already everything runs"
    elif risk == "low":
        note = ("low risk ignored: this change category always runs the full tests and security" if mandatory
                else "low risk: removes no check")
    elif risk == "medium":
        note = "medium risk: no change to the plan"
    else:
        note = ""
    return {"level": risk, "added": added, "note": note}


# ---------------- evidence and reuse ----------------

def evidence_dir(root: Path) -> Path:
    code, text = _git(root, "rev-parse", "--git-common-dir")
    common = Path(text.strip()) if code == 0 and text.strip() else Path(".git")
    return (common if common.is_absolute() else root / common) / "cplat-evidence"


class Digests:
    """sha256 of file contents, read once per plan."""

    def __init__(self, root: Path):
        self.root, self._cache = root, {}

    def of(self, rel: str) -> str:
        if rel not in self._cache:
            try:
                self._cache[rel] = hashlib.sha256((self.root / rel).read_bytes()).hexdigest()
            except OSError:
                self._cache[rel] = "absent"
        return self._cache[rel]


def command(entry: dict) -> list[str]:
    return ["devbox", "run", entry["script"], *(["--", *entry["targets"]] if entry["targets"] is not None else [])]


def inputs_hash(root: Path, entry: dict, files: list[str], tracked: list[str], digests: Digests) -> str:
    """sha256 over the command, the files the check reads and the configuration / tool versions."""
    read = set(tracked) if entry["targets"] is None else {*entry["targets"], *files}
    read |= {f for f in CONFIG_FILES if (root / f).is_file()}
    body = {"check": entry["name"], "command": command(entry), "files": {f: digests.of(f) for f in sorted(read)}}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def read_evidence(root: Path, name: str) -> dict | None:
    try:
        rec = json.loads((evidence_dir(root) / f"{name}.json").read_text())
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def write_evidence(root: Path, name: str, inputs: str, result: str, run_id: str | None) -> None:
    try:
        d = evidence_dir(root)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.json").write_text(json.dumps({"inputs": inputs, "result": result, "run_id": run_id,
                                                    "at": runs._iso(runs.utcnow())}) + "\n")
    except Exception:  # noqa: BLE001  (evidence is an optimisation)
        pass


def plan(root: Path, base: str, *, full: bool = False, risk: str | None = None) -> dict:
    checks = discover(root)
    shape = shape_entry(root)
    files = changed_files(root, base)
    entries = decide(root, checks, files, full, shape, base)
    risk_section = apply_risk(entries, risk)
    tracked = all_files(root)
    digests = Digests(root)
    for e in entries:
        e["inputs"] = inputs_hash(root, e, files or [], tracked, digests)
        ev = read_evidence(root, e["name"])
        if e["decision"] == "run" and ev and ev.get("result") == "passed" and ev.get("inputs") == e["inputs"]:
            e["decision"], e["from_run"] = "reused", ev.get("run_id")
            e["reason"] += f"; inputs identical to the passed run {ev.get('run_id') or 'earlier'}"
    return {"base": base, "files": files or [], "checks": entries, "risk": risk_section}


def public(p: dict) -> dict:
    keep = ("name", "decision", "rule", "reason", "targets", "from_run")
    return {**p, "checks": [{k: c[k] for k in keep} for c in p["checks"]]}


# ---------------- run and record ----------------

def counts(checks: list[dict]) -> dict:
    return {d: sum(1 for c in checks if c["decision"] == d) for d in ("run", "reused", "skipped")}


def record_section(root: Path, p: dict) -> None:
    rid = runs.current(root)
    if not rid:
        return
    checks = [{k: c[k] for k in ("name", "decision", "rule", "reason")} | ({"from_run": c["from_run"]} if c["from_run"] else {})
              for c in p["checks"]]
    old = (runs.active(rid) or {}).get("validation")
    misses = list(old.get("misses") or []) if isinstance(old, dict) else []
    runs.set_section(rid, "validation", {"base": p["base"], "checks": checks, "counts": counts(checks), "misses": misses})


def _run_check(root: Path, entry: dict) -> tuple[int, str, Path]:
    log = quiet._log_path(root, f"validate-{entry['name']}")
    try:
        with log.open("wb") as fh:
            rc = subprocess.run(command(entry), cwd=root, stdout=fh, stderr=subprocess.STDOUT).returncode
    except FileNotFoundError:
        raise PlatformError("`devbox` is not installed or not on PATH", hint=core.install_hint("devbox")) from None
    return rc, log.read_text(errors="replace"), log


def execute(root: Path, p: dict) -> int:
    rid = runs.current(root)
    results: dict[str, str] = {}
    code = 0
    entries = {e["name"]: e for e in p["checks"]}
    for e in p["checks"]:
        n, label = e["name"], f"{e['name']} ({e['decision']}, {e['rule']})"
        if e["decision"] == "skipped":
            print(f"skipped: {label}: {e['reason']}")
            continue
        if e["decision"] == "reused":
            print(f"reused: {label}: {e['reason']}")
            continue
        twin = entries.get("test")
        if n == "acceptance" and e["targets"] is None and twin and twin["decision"] in ("run", "reused") \
                and twin["targets"] is None and twin["script"] == e["script"] and "test" in results:
            results[n] = results["test"]
            print(f"ok: {label}: covered by the full test run")
            write_evidence(root, n, e["inputs"], results[n], rid)
            continue
        rc, text, log = _run_check(root, e)
        lines = text.splitlines()
        results[n] = "passed" if rc == 0 else "failed"
        write_evidence(root, n, e["inputs"], results[n], rid)
        if rc == 0:
            print(f"ok: {label} ({len(lines)} lines, log: {log})")
        else:
            print(f"FAILED (exit {rc}): {label} (log: {log})")
            print("\n".join(lines[-TAIL:]))
            code = 1
            break
    record_section(root, p)
    return code


def record_final(run_id: str | None, check: str, result: str) -> bool:
    """A failed final-gate `check` that the last loop plan skipped or reused is a miss for its rule. Never raises."""
    try:
        def change(rec: dict) -> None:
            v = rec.get("validation")
            if result != "failed" or not isinstance(v, dict):
                return
            hit = next((c for c in v.get("checks") or [] if c.get("name") == check), None)
            if hit and hit.get("decision") in ("skipped", "reused"):
                miss = {"check": check, "rule": hit.get("rule")}
                if miss not in v.setdefault("misses", []):
                    v["misses"].append(miss)
        return runs.mutate(run_id, change) == "ok"
    except Exception:  # noqa: BLE001
        return False


def record_final_gate(root: Path) -> None:
    """After a red `devbox run ci`: run the checks the loop skipped or reused one by one; the red ones are misses. Never raises."""
    try:
        rid = runs.current(root)
        v = (runs.active(rid) or {}).get("validation") if rid else None
        if not isinstance(v, dict):
            return
        scripts = {c["name"]: c for c in discover(root)}
        for c in v.get("checks") or []:
            if c.get("decision") in ("skipped", "reused") and c.get("name") in scripts:
                entry = _entry(scripts[c["name"]], "run", "final", "final gate")
                rc = subprocess.run(command(entry), cwd=root, capture_output=True).returncode
                record_final(rid, c["name"], "passed" if rc == 0 else "failed")
    except Exception:  # noqa: BLE001
        pass


# ---------------- cli ----------------

def render(p: dict) -> str:
    lines = [f"validation plan against {p['base']} ({len(p['files'])} changed file(s))"]
    for c in p["checks"]:
        extra = f" [{', '.join(c['targets'])}]" if c["targets"] else ""
        lines.append(f"  {c['name']}: {c['decision']} ({c['rule']}): {c['reason']}{extra}")
    if p["risk"]["note"]:
        lines.append(f"  risk: {p['risk']['note']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cplat validate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        s = sub.add_parser(name)
        s.add_argument("--base", metavar="REF")
        s.add_argument("--full", action="store_true", help="run every check")
        s.add_argument("--risk", choices=RISKS, help="the agent's risk level; it can only add checks")
    sub.choices["plan"].add_argument("--json", action="store_true")
    f = sub.add_parser("final")
    f.add_argument("--check", required=True)
    f.add_argument("result", choices=("passed", "failed"))
    return ap


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    if ns.cmd == "final":
        record_final(runs.current(Path.cwd()), ns.check, ns.result)
        return 0
    root = toplevel()
    p = plan(root, ns.base or default_base(root), full=ns.full, risk=ns.risk)
    if ns.cmd == "plan":
        print(json.dumps(public(p), indent=2) if ns.json else render(p))
        return 0
    return execute(root, p)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
