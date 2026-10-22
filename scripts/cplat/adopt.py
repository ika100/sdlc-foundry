"""`adopt`: bring an existing repo that was not created from a template onto the platform (spec 071).

  cplat adopt --type service-python [--data module_name=app] [--dry-run]

Renders the shape's template with answers taken from the repo (name and org from `origin`, the description from the
README) into a scratch directory and copies over only what the repo lacks: CLAUDE.md, .claude/settings.json, devbox
recipes, spec and ADR scaffolding, CI files. Nothing that exists is overwritten: devbox.json gets the template's
missing recipes and packages added (yours win), .gitignore the missing lines, and every other file that differs is
listed so you can compare it with the template. Starter app code and tests are never added. Afterwards the repo has a
.copier-answers.yml and .platform-version, so `/shared:update-service` and every /svc:* command work. One commit on
chore/adopt-platform; nothing is pushed.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import tempfile
from pathlib import Path

import core
import update
from core import PLATFORM_ROOT, PlatformError, Report, run

BRANCH = "chore/adopt-platform"
NEVER = {".git", ".devbox", ".venv", "node_modules", ".copier-answers.yml"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat adopt", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--type", required=True, help="the shape this repo is (see shapes.yml)")
    p.add_argument("--data", action="append", default=[], metavar="KEY=VALUE", help="a template answer (repeatable)")
    p.add_argument("--repo", default=".")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def origin(repo: Path) -> tuple[str | None, str | None]:
    url = run(["git", "remote", "get-url", "origin"], cwd=repo, check=False).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", url)
    return (m.group(1), m.group(2)) if m else (None, None)


def readme_line(repo: Path) -> str | None:
    f = repo / "README.md"
    if not f.is_file():
        return None
    for ln in f.read_text().splitlines():
        s = ln.strip()
        if s and not s.startswith(("#", "[", "!", "<", "|", "```", ">")):
            return s.rstrip(".")[:120]
    return None


def answers_for(repo: Path, shape: str, data: list[str]) -> dict[str, str]:
    org, name = origin(repo)
    name = name or repo.name
    out = {"project_name": name}
    if org:
        out.update({"github_org": org, "docker_registry": f"ghcr.io/{org}", "owner_team": f"@{org}"})
    desc = readme_line(repo)
    if desc:
        out["description"] = desc
    if shape in ("service-python", "library-python"):
        out["module_name"] = re.sub(r"[^a-z0-9_]", "_", name.lower())
    if shape == "service-go" and org:
        out["module_name"] = f"github.com/{org}/{name}"
    for kv in data:
        if "=" not in kv:
            raise PlatformError(f"--data expects KEY=VALUE, got '{kv}'")
        k, v = kv.split("=", 1)
        out[k] = v
    return out


def resolve(argv: list[str]) -> dict:
    ns = build_parser().parse_args(argv)
    repo = Path(ns.repo).resolve()
    if not (repo / ".git").exists():
        raise PlatformError(f"{repo} is not a git repository")
    if (repo / ".copier-answers.yml").is_file():
        raise PlatformError("this repo already has a .copier-answers.yml", hint="use /shared:update-service to pull template changes")
    entry = next((s for s in core.registry.load() if s["id"] == ns.type), None)
    if entry is None:
        raise PlatformError(f"unknown shape '{ns.type}'", hint="one of: " + ", ".join(s["id"] for s in core.registry.load()))
    if not ns.dry_run and run(["git", "status", "--porcelain"], cwd=repo).stdout.strip():
        raise PlatformError("the working tree has uncommitted changes", hint="commit or stash first; adoption is one reviewable commit")
    return {"repo": repo, "shape": ns.type, "template": entry["template"], "answers": answers_for(repo, ns.type, ns.data),
            "dry_run": ns.dry_run, "json": ns.json}


def render(template: str, answers: dict[str, str], dest: Path) -> None:
    cmd = [*core.find_copier(), "copy", str(PLATFORM_ROOT / "templates" / template), str(dest), "--defaults", "--trust", "--skip-tasks"]
    for k, v in answers.items():
        cmd += ["--data", f"{k}={v}"]
    run(cmd)


def is_code(path: str, patterns: list[str]) -> bool:
    """Project-owned starter files (app code, tests, manifests of the language) — never added. Docs scaffolding is."""
    return not path.startswith("docs/") and any(fnmatch.fnmatch(path, p) for p in patterns)


def merge_gitignore(mine: str, theirs: str) -> tuple[str, list[str]]:
    have = {ln.strip() for ln in mine.splitlines()}
    add = [ln for ln in theirs.splitlines() if ln.strip() and not ln.startswith("#") and ln.strip() not in have]
    if not add:
        return mine, []
    return mine.rstrip("\n") + "\n\n# added by cplat adopt (platform template)\n" + "\n".join(add) + "\n", add


def merge_devbox(mine: str, theirs: str) -> tuple[str, list[str]]:
    """The repo's devbox.json wins; the template's missing recipes, packages and env vars are added."""
    merged, kept, _ = update.merge_devbox(json.loads(theirs), json.loads(mine))   # "project" = template: only missing ones added
    return json.dumps(merged, indent=2) + "\n", kept


def plan_files(repo: Path, rendered: Path, patterns: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"add": [], "merge": [], "differs": [], "skipped_code": []}
    for f in sorted(p for p in rendered.rglob("*") if p.is_file()):
        rel = f.relative_to(rendered).as_posix()
        if rel.split("/")[0] in NEVER:
            continue
        target = repo / rel
        if not target.exists():
            out["skipped_code" if is_code(rel, patterns) else "add"].append(rel)
        elif rel in ("devbox.json", ".gitignore"):
            out["merge"].append(rel)
        elif target.is_file() and target.read_bytes() != f.read_bytes():
            out["differs"].append(rel)
    return out


def execute(req: dict) -> Report:
    repo: Path = req["repo"]
    r = Report(title=f"Adopt {repo.name} as {req['shape']} (platform {core.platform_version()})")
    r.will_do += [f"render templates/{req['template']} with " + ", ".join(f"{k}={v}" for k, v in req["answers"].items()),
                  "ADD only files the repo does not have (CLAUDE.md, .claude/settings.json, CI, docs/specs …); no starter code",
                  "MERGE devbox.json (your recipes win; missing template recipes added) and .gitignore (missing lines added)",
                  "keep every other existing file; list the ones that differ from the template",
                  "write .copier-answers.yml and .platform-version; commit once on " + BRANCH + " (nothing is pushed)"]
    with tempfile.TemporaryDirectory(prefix="cplat-adopt-") as tmp:
        rendered = Path(tmp) / repo.name
        render(req["template"], req["answers"], rendered)
        files = plan_files(repo, rendered, update.project_owned_patterns(req["template"]))
        r.data = {"files": files}
        if req["dry_run"]:
            r.will_do.append(f"{len(files['add'])} file(s) to add, {len(files['merge'])} to merge, {len(files['differs'])} kept although they differ")
            return r
        cur = run(["git", "symbolic-ref", "--short", "HEAD"], cwd=repo, check=False).stdout.strip()
        if cur in ("main", "master"):
            run(["git", "checkout", "-q", "-b", BRANCH], cwd=repo)
            r.did.append(f"created branch {BRANCH}")
        for rel in files["add"]:
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(rendered / rel, repo / rel)
        if files["add"]:
            r.did.append(f"added {len(files['add'])} file(s): " + ", ".join(files["add"][:8]) + (" …" if len(files["add"]) > 8 else ""))
        for rel in files["merge"]:
            mine, theirs = (repo / rel).read_text(), (rendered / rel).read_text()
            text, added = merge_devbox(mine, theirs) if rel == "devbox.json" else merge_gitignore(mine, theirs)
            if added:
                (repo / rel).write_text(text)
                r.did.append(f"{rel}: added " + "; ".join(added[:10]) + (" …" if len(added) > 10 else ""))
        answers = (rendered / ".copier-answers.yml").read_text()
        answers = re.sub(r"^_src_path:.*$", f"_src_path: gh:ika100/sdlc-foundry/templates/{req['template']}", answers, flags=re.M)
        (repo / ".copier-answers.yml").write_text(answers)
        core.write_stamp(repo, req["shape"], "main")
    if files["differs"]:
        r.next_steps.append("kept yours, differ from the template (compare, adopt what you want; /shared:update-service will "
                            "overwrite skeleton files from now on): " + ", ".join(files["differs"]))
    if files["skipped_code"]:
        r.next_steps.append(f"not added (starter code/tests of the template): {len(files['skipped_code'])} file(s)")
    r.next_steps += ["make every `devbox run` recipe in devbox.json fit this repo (test, test-fast, quality, security): agents only "
                     "run recipes", "devbox install && devbox run quality && devbox run test-fast",
                     "start new work with /svc:spec; push the branch and open a PR"]
    import gates
    gaps = gates.ci_gaps(repo)
    if gaps:
        r.next_steps.append("your CI runs no " + ", ".join(f"`devbox run {g}`" for g in gaps) + " (spec 081): copy the job(s) "
                            f"from templates/{req['template']}/.github/workflows/ci.yml; `cplat doctor` keeps reporting it")
    r.data["ci_gaps"] = gaps
    run(["git", "add", "-A"], cwd=repo)
    run(["git", *core.git_identity(repo), "commit", "-q", "-m", f"chore: adopt the {req['shape']} platform template"], cwd=repo)
    r.did.append("committed: chore: adopt the platform template")
    r.undo.append(f"git checkout main && git branch -D {BRANCH}")
    return r


def main(argv: list[str]) -> int:
    req = resolve(argv)
    rep = execute(req)
    rep.emit(req["dry_run"], req["json"])
    return 0
