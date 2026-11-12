#!/usr/bin/env python3
"""Lint the templates a branch changes (spec 184, AC-184.5), with the lint each template's CI smoke job runs.

  uv run scripts/template-lint.py --changed [--base REF]    render and lint each template the branch changes (devbox run ci)
  python3 scripts/template-lint.py <template> <rendered dir> lint one rendered project (the CI smoke jobs)

A violation is printed as `<template>: <file>:<line>: <rule>: <message>` (`<line>` is `-` for a whole-file format finding),
so a failing run names file, line and rule, not only a count. Standard library only.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

PNPM = "pnpm@11.22.0"


class Violation(NamedTuple):
    file: str
    line: str
    rule: str
    message: str


# ---------------- parsers: output lines of one command -> violations ----------------

RUFF = re.compile(r"^(\S+?):(\d+):(\d+): ([A-Z]{1,5}\d{1,4}) (.*)$")
CHECKSTYLE = re.compile(r"^\[(?:WARN|WARNING|ERROR)\] (\S.*?):\[(\d+)(?:,\d+)?\] \((\w+)\) (\w+): (.*)$")
SPOTLESS = re.compile(r"^\[ERROR\]\s+(\S+\.java)\s*$")
GOLANGCI = re.compile(r"^(\S+?):(\d+):(\d+): (.*) \(([\w-]+)\)$")
ESLINT_PROBLEM = re.compile(r"^\s+(\d+):(\d+)\s+(?:error|warning)\s+(.*?)\s{2,}(\S+)\s*$")


def parse_ruff(lines: list[str]) -> list[Violation]:
    out = []
    for ln in lines:
        m = RUFF.match(ln)
        if m:
            out.append(Violation(m[1], m[2], m[4], m[5].replace("[*] ", "", 1)))
    return out


def parse_ruff_format(lines: list[str]) -> list[Violation]:
    out = []
    for ln in lines:
        m = re.match(r"^Would reformat: (.+)$", ln)
        if m:
            out.append(Violation(m[1].strip(), "-", "ruff-format", "would be reformatted (run ruff format)"))
    return out


def parse_maven(lines: list[str]) -> list[Violation]:
    """Checkstyle `[WARN] file:[l,c] (group) Rule: msg` and Spotless's list of files."""
    out: list[Violation] = []
    for ln in lines:
        m = CHECKSTYLE.match(ln)
        if m:
            out.append(Violation(m[1], m[2], m[4], m[5]))
            continue
        m = SPOTLESS.match(ln)
        if m:
            v = Violation(m[1], "-", "spotless", "needs formatting (run spotless:apply)")
            if v not in out:
                out.append(v)
    return out


def parse_golangci(lines: list[str]) -> list[Violation]:
    out = []
    for ln in lines:
        m = GOLANGCI.match(ln)
        if m:
            out.append(Violation(m[1], m[2], m[5], m[4]))
    return out


def parse_eslint(lines: list[str]) -> list[Violation]:
    out, current = [], ""
    for ln in lines:
        m = ESLINT_PROBLEM.match(ln)
        if m and current:
            out.append(Violation(current, m[1], m[4], m[3]))
        elif ln.strip() and not ln[0].isspace():
            current = ln.strip()
    return out


# ---------------- the lint table ----------------

class Step(NamedTuple):
    argv: list[str]
    parse: Callable[[list[str]], list[Violation]]
    stop_on_fail: bool = False


def no_lines(_: list[str]) -> list[Violation]:
    return []


def steps(template: str, rendered: Path) -> list[Step] | None:
    if template in ("service-python", "library-python"):
        return [Step(["uv", "run", "ruff", "check", "--output-format=concise", "."], parse_ruff),
                Step(["uv", "run", "ruff", "format", "--check", "."], parse_ruff_format)]
    if template == "service-java":
        return [Step(["mvn", "-B", "--no-transfer-progress", "spotless:check", "checkstyle:check"], parse_maven)]
    if template == "service-go":
        return [Step(["golangci-lint", "run", "./..."], parse_golangci)]
    if template == "web-nextjs":
        found = [] if (rendered / "node_modules").exists() else [Step(["npx", "-y", PNPM, "install"], no_lines, True)]
        return found + [Step(["npx", "-y", PNPM, "lint"], parse_eslint)]
    if template in ("gitops-app", "cluster-gitops"):
        return None
    raise SystemExit(f"template lint: unknown template {template}")


def run(argv: list[str], cwd: Path) -> tuple[int, list[str]]:
    """Run a command, printing its output as it comes; returns the exit code and the output lines."""
    proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    lines = []
    assert proc.stdout is not None
    for ln in proc.stdout:
        print(ln, end="", flush=True)
        lines.append(ln.rstrip("\n"))
    return proc.wait(), lines


def lint(template: str, rendered: Path) -> int:
    rendered = rendered.resolve()
    table = steps(template, rendered)
    if table is None:
        print(f"template lint: {template}: rendered (its smoke job runs no lint)")
        return 0
    for tool in dict.fromkeys(s.argv[0] for s in table):
        if not shutil.which(tool):
            print(f"template lint: {template} needs {tool}, which is not on PATH")
            return 1
    found: list[Violation] = []
    unparsed: list[str] = []
    for step in table:
        code, lines = run([shutil.which(step.argv[0]) or step.argv[0], *step.argv[1:]], rendered)
        if code == 0:
            continue
        parsed = step.parse(lines)
        found += [v for v in parsed if v not in found]
        if not parsed:
            unparsed.append(f"template lint: {template} failed: {shlex.join(step.argv)} exited {code}")
        if step.stop_on_fail:
            break
    for v in found:
        print(f"{template}: {v.file}:{v.line}: {v.rule}: {v.message}")
    for line in unparsed:
        print(line)
    if found:
        print(f"template lint: {template} failed: {len(found)} violation(s)")
    if found or unparsed:
        return 1
    print(f"template lint: {template} passed")
    return 0


# ---------------- --changed ----------------

def git(root: Path, *args: str, check: bool = True) -> str:
    res = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise SystemExit(f"template lint: git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout if res.returncode == 0 else ""


def changed_templates(root: Path, base: str | None) -> list[str]:
    if base is None:
        ok = subprocess.run(["git", "rev-parse", "--verify", "-q", "origin/main"], cwd=root, capture_output=True).returncode == 0
        base = "origin/main" if ok else "main"
    point = git(root, "merge-base", base, "HEAD", check=False).strip() or base
    names = git(root, "diff", "--name-only", point).splitlines()
    names += git(root, "ls-files", "--others", "--exclude-standard", "--", "templates").splitlines()
    found = {m[1] for n in names if (m := re.match(r"^templates/([^/]+)/", n))}
    return sorted(found)


def render_data(template: str) -> list[str]:
    """The `--data` of the template's CI smoke job, with `lint-` / `lint_` names."""
    data = {"project_name": f"lint-{template}"}
    if template in ("service-python", "library-python"):
        data["module_name"] = "lint_" + template.replace("-", "_")
        data["description"] = "Smoke test"
    elif template == "web-nextjs":
        data["description"] = "Smoke test"
    elif template == "gitops-app":
        data.update(app_name="lint", description="Smoke test")
    elif template == "cluster-gitops":
        data["description"] = "Smoke test"
    return [x for k, v in data.items() for x in ("--data", f"{k}={v}")]


def copier_command() -> list[str] | None:
    if shutil.which("copier"):
        return ["copier"]
    if shutil.which("uv"):
        return ["uv", "tool", "run", "--from", "copier", "copier"]
    return None


def changed(base: str | None) -> int:
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    templates = changed_templates(root, base)
    if not templates:
        print("template lint: no template changed")
        return 0
    copier = copier_command()
    if copier is None:
        print("template lint: needs copier, which is not on PATH")
        return 1
    failed = False
    with tempfile.TemporaryDirectory(prefix="template-lint-") as tmp:
        for t in templates:
            dest = Path(tmp) / t
            print(f"template lint: rendering {t}")
            code, _ = run([*copier, "copy", f"./templates/{t}", str(dest), "--defaults", "--trust", "--skip-tasks", *render_data(t)], root)
            if code != 0:
                print(f"template lint: {t} failed: render exited {code}")
                failed = True
                continue
            failed = lint(t, dest) != 0 or failed
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--changed":
        rest = argv[1:]
        if rest and rest[0] == "--base" and len(rest) == 2:
            return changed(rest[1])
        if not rest:
            return changed(None)
    elif len(argv) == 2 and not argv[0].startswith("-"):
        return lint(argv[0], Path(argv[1]))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    sys.exit(main(sys.argv[1:]))
