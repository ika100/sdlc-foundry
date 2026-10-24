"""`cplat deps`: fixable dependency findings of a red security gate are patched by the run (spec 095, ADR-034).

  cplat deps findings [--json] [--dir D]    the findings that turn the security gate red, one line per package
  cplat deps patch [--dir D]                bump every fixable package, re-run the gates, commit or revert (exit 0, 3 escalate, 4 not ours)
  cplat deps report [--body-file F] [--update-pr] [--dir D]    the PR-body section of the run's patched bumps

The recipes `deps-findings` and `deps-bump` of the repo's devbox.json are the contract with each shape; cplat never calls
uv, pnpm, go, mvn or trivy itself. Round state lives in `<git dir>/cplat-deps.json`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import core
import deps_parse
import gates
import runs
from core import PlatformError
from deps_parse import DEP_FILES, TOOLS, Finding

MAX_ROUNDS = 2
GATE_TIMEOUT = 3600
STATE_FILE = "cplat-deps.json"
REPORT_FILE = "cplat-deps-report.json"
SECTION = "## Dependency patches"
HINT = "/shared:update-service adds the deps recipes"


# ---------------- seams (tests replace these) ----------------

def devbox(repo: Path, args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return core.run(["devbox", *args], cwd=repo, check=False, timeout=timeout)


def git(repo: Path, args: list[str], check: bool = True) -> str:
    return core.run(["git", *args], cwd=repo, check=check).stdout.strip()


def shape_of(repo: Path) -> str:
    import shapecmd
    return shapecmd.route(repo)["shape"]


# ---------------- helpers ----------------

class Escalate(Exception):
    def __init__(self, reason: str, cause: str, tail: str = ""):
        super().__init__(reason)
        self.reason, self.cause, self.tail = reason, cause, tail


def _path(repo: Path, rev_parse_flag: str) -> Path:
    out = git(repo, ["rev-parse", rev_parse_flag])
    return Path(out) if os.path.isabs(out) else (repo / out).resolve()


def _output(p: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(x for x in (p.stdout, p.stderr) if x)


def _lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def _last_line(text: str) -> str:
    lines = _lines(text)
    return lines[-1].strip() if lines else "no output"


def _tail(text: str) -> str:
    return "\n".join(f"  {ln}" for ln in _lines(text)[-40:])


def _ids(f: Finding) -> str:
    return ", ".join(f.advisories)


def _arrow(f: Finding) -> str:
    return f"{f.package} {f.installed} -> {f.fixed}"


def _fixable(f: Finding) -> bool:
    return f.fixed is not None and f.kind == "dependency"


def _failing_tests(text: str) -> list[str]:
    found: list[str] = []
    for pat in (r"^FAILED (\S+)", r"^\s*FAIL\s+(\S+ > .+?)\s*$", r"^\s*×\s*(.+?)\s*$", r"^\s*--- FAIL: (\S+)",
                r"^\[ERROR\]\s{3}(\S+)"):
        found += re.findall(pat, text, flags=re.M)
    return list(dict.fromkeys(found))


# ---------------- findings ----------------

def findings(repo: Path) -> list[Finding]:
    shape = shape_of(repo)
    if shape not in TOOLS:
        raise PlatformError(f"{shape} repos have no dependency findings (spec 095)")
    if "deps-findings" not in gates.recipes(repo):
        raise PlatformError("deps-findings failed: devbox.json has no deps-findings recipe", hint=HINT)
    out = _path(repo, "--git-dir") / REPORT_FILE
    out.unlink(missing_ok=True)
    p = devbox(repo, ["run", "deps-findings", str(out)], GATE_TIMEOUT)
    if p.returncode != 0:
        raise PlatformError(f"deps-findings failed: {_last_line(p.stderr or p.stdout or '')}", hint=HINT)
    try:
        text = out.read_text()
    except OSError:
        raise PlatformError("deps-findings failed: the recipe wrote no report", hint=HINT) from None
    return deps_parse.group(deps_parse.parse(TOOLS[shape], text, deps_parse.declared(shape, repo)))


def _finding_line(f: Finding) -> str:
    line = f"{f.package} {f.installed} -> {f.fixed or 'no fix released'} {_ids(f)} {f.severity}"
    return line + (" transitive" if f.transitive else "") + (" major bump" if f.major else "") + (" toolchain" if f.kind == "toolchain" else "")


def _cmd_findings(ns: argparse.Namespace) -> int:
    fs = findings(Path(ns.dir))
    if ns.json:
        print(json.dumps([asdict(f) for f in fs], indent=2))
    elif fs:
        print("\n".join(_finding_line(f) for f in fs))
    else:
        print("no dependency finding turns the security gate red")
    return 0


# ---------------- round state and run record ----------------

def _run_key(repo: Path) -> tuple[str, str | None]:
    """(round-state key, run id for the run record or None)."""
    ptr = runs._read_pointer(runs._pointer(repo))
    rid = (ptr or {}).get("run_id") or runs.attach_point(repo)
    if rid:
        return rid, rid
    return f"branch:{git(repo, ['symbolic-ref', '--short', 'HEAD'], check=False) or 'detached'}", None


def _state_path(repo: Path) -> Path:
    return _path(repo, "--git-dir") / STATE_FILE


def _load_state(repo: Path, key: str | None = None) -> dict:
    try:
        st = json.loads(_state_path(repo).read_text())
    except (OSError, ValueError):
        st = {}
    if key is not None and st.get("run") != key:
        st = {}
    return {"run": key or st.get("run"), "rounds": st.get("rounds", 0), "bumps": st.get("bumps", [])}


def _save_state(repo: Path, st: dict) -> None:
    path = _state_path(repo)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st, indent=2))
    os.replace(tmp, path)


def _record(run_id: str | None, bump: dict) -> None:
    runs.event(run_id, "patches", bump["package"], {
        "package": bump["package"], "from": bump["from"], "to": bump["to"], "advisory": ", ".join(bump["advisories"]),
        "severity": bump["severity"], "major": bump["major"], "outcome": bump["outcome"], "round": bump["round"]})


# ---------------- snapshot and revert ----------------

def _read_files(repo: Path, files: tuple[str, ...]) -> dict[str, bytes | None]:
    out: dict[str, bytes | None] = {}
    for f in files:
        try:
            out[f] = (repo / f).read_bytes()
        except OSError:
            out[f] = None
    return out


def _revert(repo: Path, pre: str, snap: dict[str, bytes | None]) -> None:
    files = list(snap)
    git(repo, ["reset", "-q", "--soft", pre])
    for f, data in snap.items():
        if data is None:
            (repo / f).unlink(missing_ok=True)
        else:
            (repo / f).write_bytes(data)
    git(repo, ["reset", "-q", "--", *files])
    if _read_files(repo, tuple(files)) != snap or git(repo, ["diff", pre, "--", *files]):
        raise PlatformError("revert left the dependency files different from before the round (platform bug)")


# ---------------- patch ----------------

def _escalate(reason: str, cause: str, tail: str = "") -> int:
    print(f"ESCALATE: {reason}\nCAUSE: {cause}")
    if tail:
        print(tail)
    return 3


def _open_list(fs: list[Finding]) -> str:
    return "; ".join(f"{_arrow(f)} ({_ids(f)})" for f in fs)


def _bump_dict(f: Finding, rnd: int) -> dict:
    return {"package": f.package, "from": f.installed, "to": f.fixed, "advisories": list(f.advisories), "severity": f.severity,
            "major": f.major, "transitive": f.transitive, "round": rnd, "outcome": "attempted", "commit": None}


def _gates(repo: Path) -> tuple[str, str] | None:
    """Run the steps of the repo's `ci` recipe; (step, log) of the first red one, or None when all are green."""
    scripts = gates.recipes(repo)
    if "ci" not in scripts:
        raise PlatformError("devbox.json has no ci recipe", hint="/shared:update-service adds it")
    for step in gates.chain(scripts["ci"]):
        if step == gates.CI_EXTRA and step not in scripts:
            continue
        p = devbox(repo, ["run", step], GATE_TIMEOUT)
        if p.returncode != 0:
            return step, _output(p)
    return None


def _cmd_patch(ns: argparse.Namespace) -> int:
    repo = Path(ns.dir).resolve()
    shape = "unknown"
    try:
        shape = shape_of(repo)
    except PlatformError:
        pass
    if shape not in TOOLS:
        print(f"NOT A DEPENDENCY FINDING: {shape} repos never bump dependencies (spec 095)")
        return 4
    dep_files = DEP_FILES[shape]
    for line in git(repo, ["status", "--porcelain", "--", *dep_files]).splitlines():
        raise PlatformError(f"{line.split(None, 1)[-1].strip()} has uncommitted changes",
                            hint="commit them first; cplat deps commits only its own bumps")
    fs = findings(repo)
    if not fs:
        print("NOT A DEPENDENCY FINDING: the security gate is red for another reason (secrets, bandit, or a scanner error)")
        return 4
    key, run_id = _run_key(repo)
    st = _load_state(repo, key)
    done_this_call: list[dict] = []
    try:
        while True:
            _check_fixable(st, fs, run_id)
            if st["rounds"] >= MAX_ROUNDS:
                raise Escalate(f"patch rounds exhausted ({MAX_ROUNDS} of {MAX_ROUNDS}): still open: {_open_list(fs)}", "decision")
            st["rounds"] += 1
            rnd = st["rounds"]
            _save_state(repo, st)
            pre = git(repo, ["rev-parse", "HEAD"])
            snap = _read_files(repo, dep_files)
            round_bumps: list[dict] = []
            try:
                _apply_round(repo, fs, rnd, dep_files, round_bumps)
                red = _gates(repo)
                new: list[Finding] | None = None
                if red and red[0] == "security":
                    try:
                        new = findings(repo)
                    except PlatformError:
                        new = None
            except BaseException as e:
                _revert(repo, pre, snap)
                if isinstance(e, _FailedRound):
                    for b in round_bumps:
                        b["outcome"] = "reverted"
                        _record(run_id, b)
                    st["bumps"] += round_bumps
                    _save_state(repo, st)
                raise
            if red is None or (new and all(_fixable(f) for f in new)):
                st["bumps"] += round_bumps
                for b in round_bumps:
                    b["outcome"] = "patched"
                    _record(run_id, b)
                done_this_call += round_bumps
                _save_state(repo, st)
                if red is None:
                    for b in done_this_call:
                        print(f"PATCHED: {b['package']} {b['from']} -> {b['to']} ({', '.join(b['advisories'])}, {b['severity']})"
                              + (" major bump" if b["major"] else ""))
                    print(f"GREEN: every gate passed after patch round {rnd} of {MAX_ROUNDS}")
                    return 0
                fs = new or []
                continue
            _revert(repo, pre, snap)
            for b in round_bumps:
                b["outcome"] = "reverted"
                _record(run_id, b)
            st["bumps"] += round_bumps
            _save_state(repo, st)
            step, log = red
            names = _failing_tests(log)[:5]
            why = ", ".join(names) if names else _last_line(log)
            listed = ", ".join(f"{b['package']} {b['from']} -> {b['to']}" for b in round_bumps)
            raise Escalate(f"bump reverted: {listed} turned {step} red: {why}", "code", _tail(log))
    except Escalate as e:
        return _escalate(e.reason, e.cause, e.tail)


def _check_fixable(st: dict, fs: list[Finding], run_id: str | None) -> None:
    """Step 4: nothing is bumped while any gate-red finding cannot be fixed."""
    nofix = [f for f in fs if f.fixed is None]
    tool = [f for f in fs if f.kind == "toolchain" and f.fixed is not None]
    if not nofix and not tool:
        return
    for f in nofix:
        _record(run_id, {"package": f.package, "from": f.installed, "to": None, "advisories": f.advisories, "severity": f.severity,
                         "major": False, "outcome": "no-fix", "round": st["rounds"]})
    parts = []
    if nofix:
        parts.append("no fix released: " + "; ".join(f"{f.package} {f.installed} ({_ids(f)})" for f in nofix))
    parts += [f"toolchain finding: {f.package} {f.installed} -> {f.fixed} ({_ids(f)}): bump go in devbox.json" for f in tool]
    raise Escalate("; ".join(parts), "decision")


def _apply_round(repo: Path, fs: list[Finding], rnd: int, dep_files: tuple[str, ...], round_bumps: list[dict]) -> None:
    for f in sorted(fs, key=lambda x: x.package):
        before = _read_files(repo, dep_files)
        bump = _bump_dict(f, rnd)
        round_bumps.append(bump)
        p = devbox(repo, ["run", "deps-bump", f.package, str(f.fixed)], GATE_TIMEOUT)
        head = f"bump failed: {_arrow(f)} ({_ids(f)}): "
        if p.returncode != 0:
            bump["outcome"] = "reverted"
            raise _FailedRound(round_bumps, head + _last_line(_output(p)), _tail(_output(p)))
        after = _read_files(repo, dep_files)
        changed = [x for x in dep_files if after[x] != before[x]]
        if not changed:
            raise _FailedRound(round_bumps, head + "the recipe changed no file", "")
        git(repo, ["add", "-A", "--", *changed])
        git(repo, ["commit", "-q", "-s", "-m", f"fix(deps): bump {f.package} {f.installed} -> {f.fixed} ({_ids(f)})", "--", *changed])
        bump["commit"] = git(repo, ["rev-parse", "HEAD"])


class _FailedRound(Escalate):
    def __init__(self, bumps: list[dict], reason: str, tail: str):
        super().__init__(reason, "code", tail)
        self.bumps = bumps


# ---------------- report ----------------

def _section(bumps: list[dict]) -> str:
    rows = []
    for b in bumps:
        note = "major bump" if b.get("major") else ""
        rows.append(f"| {b['package']} | {b['from']} | {b['to']} | {', '.join(b['advisories'])} | {b['severity']} |"
                    + (f" {note} |" if note else " |"))
    return "\n".join([SECTION, "", "Bumped automatically because the security gate was red (spec 095).", "",
                      "| Package | From | To | Advisory | Severity | Note |", "|---|---|---|---|---|---|", *rows]) + "\n"


def _merge(body: str, section: str) -> str:
    m = re.search(rf"^{re.escape(SECTION)}[ \t]*$", body, flags=re.M)
    if m:
        nxt = re.search(r"^## ", body[m.end():], flags=re.M)
        end = m.end() + nxt.start() if nxt else len(body)
        return body[:m.start()] + section + ("\n" + body[end:] if end < len(body) else "")
    sep = "" if body.endswith("\n\n") or not body else ("\n" if body.endswith("\n") else "\n\n")
    return body + sep + section


def _cmd_report(ns: argparse.Namespace) -> int:
    repo = Path(ns.dir).resolve()
    bumps = [b for b in _load_state(repo)["bumps"] if b.get("outcome") == "patched"]
    if not bumps:
        return 0
    section = _section(bumps)
    if not ns.body_file:
        if ns.update_pr:
            raise PlatformError("--update-pr needs --body-file")
        print(section, end="")
        return 0
    body = Path(ns.body_file)
    body.write_text(_merge(body.read_text() if body.exists() else "", section))
    if ns.update_pr:
        try:
            pr = json.loads((_path(repo, "--git-common-dir") / "cplat-ship.json").read_text()).get("pr")
        except (OSError, ValueError):
            pr = None
        if pr:
            core.run(["gh", "pr", "edit", str(pr), "--body-file", str(body)], cwd=repo)
    return 0


# ---------------- cli ----------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat deps", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("findings")
    f.add_argument("--json", action="store_true")
    sub.add_parser("patch")
    r = sub.add_parser("report")
    r.add_argument("--body-file")
    r.add_argument("--update-pr", action="store_true")
    for p in sub.choices.values():
        p.add_argument("--dir", default=".")
    ns = ap.parse_args(argv)
    return {"findings": _cmd_findings, "patch": _cmd_patch, "report": _cmd_report}[ns.cmd](ns)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
