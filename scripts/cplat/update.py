"""`update-service`: re-apply the platform template to an existing repo on a review branch."""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import re
from pathlib import Path

import yaml

import core
from core import PLATFORM_ROOT, PlatformError, Report, run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat update-service", description=__doc__)
    p.add_argument("--ref", default=None, help="platform ref being applied (informational; the running checkout is the source)")
    p.add_argument("--data", action="append", default=[], metavar="KEY=VALUE", help="change a template answer (repeatable)")
    p.add_argument("--repo", default=".", help="repo to update (default: current directory)")
    p.add_argument("--migrate", action="store_true", help="v1 → v2: also delete the service's k8s/ directory (the gitops-app repo owns manifests now; import them first with `compose add <service> --from-k8s`)")
    p.add_argument("--skip-tasks", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def detect_shape(repo: Path) -> str:
    out = run(["bash", str(PLATFORM_ROOT / "scripts" / "detect-shape.sh"), str(repo)], check=False)
    if out.returncode != 0 or not out.stdout.strip():
        raise PlatformError("cannot determine the repo's shape", hint="a .copier-answers.yml with _src_path ending in templates/<shape> is required (see docs/ADOPTING.md, Step 5)")
    return out.stdout.strip()


def resolve(argv: list[str]) -> dict:
    ns = build_parser().parse_args(argv)
    repo = Path(ns.repo).resolve()
    if not (repo / ".git").exists():   # a file in a git worktree
        raise PlatformError(f"{repo} is not a git repository")
    if not (repo / ".copier-answers.yml").is_file():
        raise PlatformError("no .copier-answers.yml in the repo", hint="see docs/ADOPTING.md → 'Adopt the template for skeleton updates'")
    if run(["git", "status", "--porcelain"], cwd=repo).stdout.strip():
        raise PlatformError("the working tree has uncommitted changes", hint="commit or stash first; the update must be one reviewable commit")
    for kv in ns.data:
        if "=" not in kv:
            raise PlatformError(f"--data expects KEY=VALUE, got '{kv}'")
    shape = detect_shape(repo)
    entry = next(s for s in core.registry.load() if s["id"] == shape)
    stamp = core.read_stamp(repo)
    return {"repo": repo, "shape": shape, "template": entry["template"], "data": ns.data, "old": stamp.get("platform"),
            "new": core.platform_version(), "ref": ns.ref or stamp.get("ref") or "main", "skip_tasks": ns.skip_tasks, "migrate": ns.migrate,
            "dry_run": ns.dry_run, "json": ns.json}


def branch_name(repo: Path | None = None) -> str:
    """chore/platform-update-YYYYMMDD, with -2, -3, … when that branch already exists (a second update the same day)."""
    base = "chore/platform-update-" + datetime.date.today().strftime("%Y%m%d")
    if repo is None:
        return base
    taken = set(run(["git", "branch", "--list", "--format=%(refname:short)", base + "*"], cwd=repo).stdout.split())
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    return name


def project_owned_patterns(template: str) -> list[str]:
    """The template's `_skip_if_exists` globs: bootstrap-only paths (app code, tests, ADRs ...) that updates must never touch."""
    cfg = PLATFORM_ROOT / "templates" / template / "copier.yml"
    try:
        return [str(p) for p in (yaml.safe_load(cfg.read_text()) or {}).get("_skip_if_exists") or []]
    except (OSError, yaml.YAMLError):
        return []


def drop_new_project_owned_files(repo: Path, patterns: list[str]) -> list[str]:
    """copier creates files that do not exist yet even inside `_skip_if_exists` paths. For an update that is wrong: a repo that
    evolved its own app code or tests must not receive new starter files (and tests that assert the starter UI). Remove them."""
    dropped = []
    for line in run(["git", "status", "--porcelain", "-uall"], cwd=repo).stdout.splitlines():
        if not line.startswith("??"):
            continue
        path = line[3:]
        if any(fnmatch.fnmatch(path, pattern) for pattern in patterns):
            (repo / path).unlink()
            dropped.append(path)
    for directory in sorted({str(Path(d).parent) for d in dropped}, key=len, reverse=True):   # tidy empty directories
        try:
            (repo / directory).rmdir()
        except OSError:
            pass
    return dropped


def _cmd(v) -> str:
    return " && ".join(v) if isinstance(v, list) else str(v)


def merge_devbox(project: dict, template: dict) -> tuple[dict, list[str], list[tuple[str, str]]]:
    """Spec 060: the template's devbox.json wins; recipes, packages and env vars only the project has are kept.
    Returns (merged, kept labels, replaced (label, project's old value))."""
    import copy
    merged = copy.deepcopy(template)
    kept: list[str] = []
    replaced: list[tuple[str, str]] = []

    mine = (project.get("shell") or {}).get("scripts") or {}
    theirs = (template.get("shell") or {}).get("scripts") or {}
    for name, cmd in mine.items():
        if name not in theirs:
            merged.setdefault("shell", {}).setdefault("scripts", {})[name] = cmd
            kept.append(f"scripts {name}")
        elif _cmd(cmd) != _cmd(theirs[name]):
            replaced.append((f"scripts {name}", _cmd(cmd)))

    pkgs, tpkgs = project.get("packages"), template.get("packages")
    if isinstance(pkgs, list) and isinstance(tpkgs, list):
        tnames = {p.split("@", 1)[0]: p for p in tpkgs}
        for p in pkgs:
            name = p.split("@", 1)[0]
            if name not in tnames:
                merged["packages"].append(p)
                kept.append(f"packages {p}")
            elif p != tnames[name]:
                replaced.append((f"packages {name}", p))
    elif isinstance(pkgs, dict) and isinstance(tpkgs, dict):
        for name, ver in pkgs.items():
            if name not in tpkgs:
                merged["packages"][name] = ver
                kept.append(f"packages {name}")
            elif ver != tpkgs[name]:
                replaced.append((f"packages {name}", str(ver)))

    tenv = template.get("env") or {}
    for name, val in (project.get("env") or {}).items():
        if name not in tenv:
            merged.setdefault("env", {})[name] = val
            kept.append(f"env {name}")
        elif val != tenv[name]:
            replaced.append((f"env {name}", str(val)))
    return merged, kept, replaced


def _readme_changed(template: str, old: str | None) -> bool:
    """True when the template's README changed since the repo's platform version, or that version is unknown."""
    path = f"templates/{template}/README.md.jinja"
    if not old:
        return True
    rc = run(["git", "diff", "--quiet", f"v{old}", "--", path], cwd=PLATFORM_ROOT, check=False).returncode
    return rc != 0


def merge_devbox_file(repo: Path, before: str | None) -> tuple[list[str], list[tuple[str, str]], str | None]:
    """Merge the project's devbox.json (before the update) into the rendered one. Rewrites only when something is kept."""
    import json
    path = repo / "devbox.json"
    if before is None or not path.is_file():
        return [], [], None
    try:
        project = json.loads(before)
    except ValueError:
        return [], [], "devbox.json was not valid JSON: replaced by the template's file — re-add your recipes from `git show HEAD~1:devbox.json`"
    text = path.read_text()
    merged, kept, replaced = merge_devbox(project, json.loads(text))
    if kept:
        path.write_text(_insert_kept(text, json.loads(text), merged))
    return kept, replaced, None


def _close(text: str, start: int) -> int:
    """Index of the bracket closing the one at `start`, skipping JSON strings."""
    depth, i, in_str = 0, start, False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced JSON")


def _insert_kept(text: str, template: dict, merged: dict) -> str:
    """Add the kept entries to the rendered template text without reformatting it (templates align their recipes);
    falls back to a plain dump when the text cannot be edited safely."""
    import json
    out = text
    try:
        for section, path in (("scripts", ("shell", "scripts")), ("packages", ("packages",)), ("env", ("env",))):
            new, old = merged, template
            for k in path:
                new, old = (new or {}).get(k), (old or {}).get(k)
            if new == old:
                continue
            m = re.search(rf'"{section}"\s*:\s*([\[{{])', out)
            if not m or old is None:
                raise ValueError(section)
            end = _close(out, m.start(1))
            body = out[m.start(1) + 1:end]
            indent = (re.findall(r"\n([ \t]+)\S", body) or ["  "])[-1]
            if isinstance(new, list):
                extra = [json.dumps(v) for v in new[len(old):]]
            else:
                extra = [f"{json.dumps(k)}: {json.dumps(v)}" for k, v in new.items() if k not in old]
            head = body.rstrip()
            sep = "," if head.strip() else ""
            insert = sep + "".join(f"\n{indent}{e}" + ("," if i < len(extra) - 1 else "") for i, e in enumerate(extra))
            tail = body[len(head):]
            out = out[:m.start(1) + 1] + head + insert + tail + out[end:]
        if json.loads(out) == merged:
            return out
    except ValueError:
        pass
    return json.dumps(merged, indent=2) + "\n"


def pin_dev_steps(repo: Path, shape: str) -> list[str]:
    """Spec 062: what an existing repo needs once the update brings dev-follows-main."""
    import newsvc
    url = run(["git", "remote", "get-url", "origin"], cwd=repo, check=False).stdout.strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    slug = m.group(1) if m else f"<org>/{repo.name}"
    if shape == "gitops-app" and (repo / ".github/workflows/pin-dev.yml").is_file():
        return ["let pin PRs merge themselves (spec 062): " + " && ".join(" ".join(c) for c in newsvc.pin_settings_cmds(slug))]
    app_file = repo / ".platform-app.yml"
    ci_file = repo / ".github" / "workflows" / "ci.yml"
    if app_file.is_file() and ci_file.is_file() and "\n  pin-dev:" in ci_file.read_text():
        apps = re.findall(r"^\s*-\s*([^\s#]+)", app_file.read_text(), re.M)
        if m is None:
            slug = f"{apps[0].split('/')[0]}/{repo.name}" if apps else slug
        return [newsvc.token_step(app, [slug]) for app in apps]
    return []


def plan(req: dict) -> Report:
    was = req["old"] or "none — this repo has no .platform-version stamp yet"
    r = Report(title=f"Update {req['repo'].name} ({req['shape']}) from platform {was} → {req['new']}")
    cur = run(["git", "symbolic-ref", "--short", "HEAD"], cwd=req["repo"], check=False).stdout.strip()
    if cur in ("main", "master"):
        r.will_do.append(f"create review branch {branch_name(req['repo'])}")
    r.will_do.append(f"re-apply templates/{req['template']} with the repo's recorded answers" + (f" plus {', '.join(req['data'])}" if req["data"] else ""))
    r.will_do.append("OVERWRITE skeleton files (CI, Dockerfile, CLAUDE.md, …); project-owned files (README, app code, tests, ADRs) are never touched, and new starter files in those paths are not added")
    r.will_do.append("MERGE devbox.json: the template's recipes and packages, plus the ones only this repo has")
    if req["migrate"]:
        r.will_do.append("DELETE k8s/ (v1 → v2 migration: manifests are generated in the product's gitops-app repo; recoverable from git history)")
    r.will_do.append("restore the stable template source in .copier-answers.yml and stamp .platform-version")
    r.will_do.append("commit once (nothing is pushed)")
    return r


def execute(req: dict) -> Report:
    repo: Path = req["repo"]
    r = plan(req)
    cur = run(["git", "symbolic-ref", "--short", "HEAD"], cwd=repo).stdout.strip()
    branch = branch_name(repo)
    if cur in ("main", "master"):
        run(["git", "checkout", "-q", "-b", branch], cwd=repo)
        r.did.append(f"created branch {branch}")
    before = (repo / ".copier-answers.yml").read_text()
    devbox_before = (repo / "devbox.json").read_text() if (repo / "devbox.json").is_file() else None
    ci_file = repo / ".github" / "workflows" / "ci.yml"
    had_pin_dev = (ci_file.is_file() and "\n  pin-dev:" in ci_file.read_text()) or (repo / ".github/workflows/pin-dev.yml").is_file()

    cmd = [*core.find_copier(), "copy", str(PLATFORM_ROOT / "templates" / req["template"]), ".", "--data-file", ".copier-answers.yml",
           "--overwrite", "--defaults", "--trust", "--skip-tasks"]
    for kv in req["data"]:
        cmd += ["--data", kv]
    run(cmd, cwd=repo)
    kept, replaced, devbox_note = merge_devbox_file(repo, devbox_before)
    dropped = drop_new_project_owned_files(repo, project_owned_patterns(req["template"]))
    if dropped:
        r.did.append(f"left out {len(dropped)} new starter file(s) in project-owned paths (app code, tests, docs): {', '.join(dropped[:4])}{' ...' if len(dropped) > 4 else ''}")
    answers = repo / ".copier-answers.yml"
    answers.write_text(re.sub(r"^_src_path:.*$", f"_src_path: gh:ika100/sdlc-foundry/templates/{req['template']}", answers.read_text(), flags=re.M))
    core.write_stamp(repo, req["shape"], req["ref"])
    if req["migrate"] and (repo / "k8s").is_dir():
        import shutil
        shutil.rmtree(repo / "k8s")
        r.did.append("removed k8s/ (v1 manifests; import them with `compose add <service> --from-k8s` if you have not yet)")

    new_keys = sorted(set(re.findall(r"^([a-z_]+):", answers.read_text(), re.M)) - set(re.findall(r"^([a-z_]+):", before, re.M)))
    changed = [ln[3:] for ln in run(["git", "status", "--porcelain"], cwd=repo).stdout.splitlines()]
    modified = [ln[3:] for ln in run(["git", "status", "--porcelain"], cwd=repo).stdout.splitlines() if ln[:2].strip() == "M"
                and not (ln[3:] == "devbox.json" and not replaced and not devbox_note)]   # merged, nothing lost (spec 060)
    if kept:
        r.did.append("kept in devbox.json: " + "; ".join(kept))
    if not changed:
        if cur in ("main", "master"):  # do not leave an empty review branch behind
            run(["git", "checkout", "-q", cur], cwd=repo)
            run(["git", "branch", "-D", branch], cwd=repo)
        r.did.append(f"already up to date with platform {req['new']} — nothing changed")
        return r
    run(["git", "add", "-A"], cwd=repo)
    run(["git", *core.git_identity(repo), "commit", "-q", "-m", f"chore: update skeleton from platform {req['new']}"], cwd=repo)
    r.did.append(f"re-applied the template; {len(changed)} file(s) changed, committed on {branch if cur in ('main','master') else cur}")
    notes = core.changelog_between(req["old"], req["new"])
    r.data = {"changed": changed, "modified": modified, "new_answers": new_keys, "changelog": notes,
              "devbox": {"kept": kept, "replaced": [{"entry": k, "was": v} for k, v in replaced]}}
    if replaced:
        r.next_steps.append("replaced in devbox.json (the template's version wins): " +
                            "; ".join(f"{k} (was {v!r})" for k, v in replaced) + " — re-add yours under a new recipe name if you need it")
    if devbox_note:
        r.next_steps.append(devbox_note)
    if not had_pin_dev:
        r.next_steps += pin_dev_steps(repo, req["shape"])
    if (repo / "README.md").is_file() and _readme_changed(req["template"], req["old"]):
        r.next_steps.append(f"README.md kept (project-owned, spec 060); the template's current version: "
                            f"git -C {PLATFORM_ROOT} show HEAD:templates/{req['template']}/README.md.jinja")
    if modified:
        r.next_steps.append("review MODIFIED skeleton files for lost local customisations: " + ", ".join(modified[:12]) + " — keep yours with `git checkout HEAD~1 -- <file>`")
    if new_keys:
        r.next_steps.append("new template answers took their defaults: " + ", ".join(new_keys))
    if notes:
        r.next_steps.append("platform changes since your version are in docs/CHANGELOG.md of sdlc-foundry (see changelog in --json output)")
    r.next_steps.append("run the repo's checks: devbox run quality && devbox run test-fast, then push the branch and open a PR")
    r.undo.append(f"git checkout {cur} && git branch -D {branch}" if cur in ("main", "master") else "git reset --hard HEAD~1")
    return r


def main(argv: list[str]) -> int:
    req = resolve(argv)
    if req["dry_run"]:
        plan(req).emit(True, req["json"])
        return 0
    execute(req).emit(False, req["json"])
    return 0
