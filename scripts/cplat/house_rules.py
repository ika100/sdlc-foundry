"""`cplat platform pr-check`: the platform repo's house rules, checked (and fixed where they can be) before a PR opens (spec 150).

  cplat platform pr-check --title T [--body-file F] [--label L …] [--base REF] [--fix] [--json]

The rules are CI's own (`scripts/check-pr-title.py`, `scripts/check-spec-required.py`, the `dco` job, the `validate` and
`quality` version loop, `scripts/check-links.py`, the fragment names of `scripts/release-check.py`); this module calls the
same functions, so a check that passes here passes there. `--fix` shortens the title to 72 characters and prints it.
Exit 0 all rules pass, 1 a rule fails (one `ERROR:` line each, with the fix).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import platrelease_changelog as fragments
import pr_rules
from core import PlatformError

KINDS_WITH_ENTRY = ("feat", "fix", "perf")   # a change users can notice; docs/chore/ci/test/refactor need no fragment
SIGNED = re.compile(r"^Signed-off-by: .+ <.+>$", re.M)
RULES = ("pr-title", "spec-required", "fragment", "validate", "dco", "links")
PR_OPEN_RULES = ("fragment", "validate")   # `cplat pr open` checks title and spec itself and commits with a sign-off


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False).stdout


def changed(repo: Path, base: str) -> list[str]:
    return [f for f in _git(repo, "diff", "--name-only", f"{base}...HEAD").splitlines() if f]


def added(repo: Path, base: str) -> list[str]:
    return [f for f in _git(repo, "diff", "--name-only", "--diff-filter=A", f"{base}...HEAD").splitlines() if f]


def unsigned(repo: Path, base: str) -> list[str]:
    """Commits of base..HEAD without a DCO sign-off (the `dco` job), as `<sha7> <subject>`."""
    out = _git(repo, "log", "--format=%h%x00%s%x00%B%x1e", f"{base}..HEAD")
    rows = []
    for rec in filter(str.strip, out.split("\x1e")):
        sha, subject, body = (rec.strip("\n").split("\x00") + ["", ""])[:3]
        if not SIGNED.search(body):
            rows.append(f"{sha} {subject}")
    return rows


def check(repo: Path, *, title: str, body: str, labels: list[str], base: str, fix: bool,
          rules: tuple[str, ...] = RULES) -> tuple[str, list[str]]:
    """(the title to use, the problems of the named rules). Each problem is one line that says what to do."""
    problems: list[str] = []
    if fix:
        try:
            title = pr_rules.fit(title)
        except ValueError:
            pass
    err = pr_rules.title_error(title) if "pr-title" in rules else None
    if err:
        problems.append("pr-title: " + err.splitlines()[0] + f" ({title!r}); use `<type>(<scope>): <subject>`, "
                        "type one of feat fix docs style refactor perf test chore ci build revert")
    files = changed(repo, base)
    err = pr_rules.spec_error(body, labels, files) if "spec-required" in rules else None
    if err:
        problems.append("spec-required: " + err)
    kind = (pr_rules._SPLIT.match(title) or [None, ""])[1]
    new_fragments = [f for f in added(repo, base) if f.startswith(fragments.FRAGMENTS + "/") and not f.endswith("README.md")]
    for f in new_fragments if "fragment" in rules else []:
        try:
            fragments.parse_fragment(Path(f).name, (repo / f).read_text())
        except (fragments.FragmentError, OSError) as e:
            problems.append(f"changelog fragment: {e}")
    code = [f for f in files if f.startswith(pr_rules.CODE)]
    if "fragment" in rules and kind in KINDS_WITH_ENTRY and code and not new_fragments and "docs/CHANGELOG.md" not in files:
        problems.append(f"changelog fragment: a `{kind}` PR that changes {len(code)} platform file(s) adds none; write "
                        f"{fragments.FRAGMENTS}/<id>-<slug>.<added|changed|fixed>.md (<id>: the issue, or the spec number)")
    for line in fragments.plugin_mismatches(repo) if "validate" in rules else []:
        problems.append(f"validate: plugin version mismatch {line}; bump both plugin.json and .claude-plugin/marketplace.json")
    for manifest in [repo / ".claude-plugin/marketplace.json", *sorted((repo / "plugins").glob("*/.claude-plugin/plugin.json")),
                     *sorted((repo / "plugins").glob("*/hooks/hooks.json"))] if "validate" in rules else []:
        try:
            json.loads(manifest.read_text())
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as e:
            problems.append(f"validate: {manifest.relative_to(repo)} is not valid JSON ({e})")
    for row in unsigned(repo, base) if "dco" in rules else []:
        problems.append(f"dco: commit {row} has no Signed-off-by; amend it with `git commit --amend -s` (or rebase with --signoff)")
    if "links" in rules and any(f.endswith(".md") for f in files) and (repo / "scripts" / "check-links.py").is_file():
        links = subprocess.run([sys.executable, "scripts/check-links.py"], cwd=repo, text=True, capture_output=True, check=False)
        if links.returncode != 0:
            detail = [ln for ln in (links.stdout + links.stderr).splitlines() if ln.strip()][:5]
            problems.append("links: " + " | ".join(detail))
    return title, problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat platform pr-check", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file", help="the PR body (for the spec rule's closing references)")
    ap.add_argument("--label", action="append", default=[])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--fix", action="store_true", help="shorten the title to 72 characters (printed as `TITLE: …`)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo", default=".")
    ns = ap.parse_args(argv)
    repo = Path(ns.repo).resolve()
    if not (repo / ".claude-plugin" / "marketplace.json").is_file():
        raise PlatformError("pr-check runs in the platform repo (no .claude-plugin/marketplace.json here)",
                            hint="a component or gitops repo opens its PRs with `cplat pr open`, which applies its own rules")
    body = Path(ns.body_file).read_text() if ns.body_file else ""
    title, problems = check(repo, title=ns.title, body=body, labels=ns.label, base=ns.base, fix=ns.fix)
    if ns.json:
        print(json.dumps({"title": title, "ok": not problems, "problems": problems}, indent=2))
    else:
        if ns.fix or title != ns.title:
            print(f"TITLE: {title}")
        for p in problems:
            print(f"ERROR: {p}")
        if not problems:
            print("OK: the house rules pass (pr-title, spec-required, changelog fragment, validate, dco, links)")
    return 1 if problems else 0
