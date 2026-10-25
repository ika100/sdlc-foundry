"""`update-service`: re-apply the platform template to an existing repo on a review branch."""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

import core
import gates
import settingsmerge
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


SEEDS = {".secrets.baseline.json"}   # repo-owned once they exist, but the skeleton needs them: added when missing, never replaced


def drop_new_project_owned_files(repo: Path, patterns: list[str]) -> list[str]:
    """copier creates files that do not exist yet even inside `_skip_if_exists` paths. For an update that is wrong: a repo that
    evolved its own app code or tests must not receive new starter files (and tests that assert the starter UI). Remove them."""
    dropped = []
    for line in run(["git", "status", "--porcelain", "-uall"], cwd=repo).stdout.splitlines():
        if not line.startswith("??"):
            continue
        path = line[3:]
        if path not in SEEDS and any(fnmatch.fnmatch(path, pattern) for pattern in patterns):
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


def merge_devbox(project: dict, template: dict, baseline: dict | None = None) -> tuple[dict, list[str], list[tuple[str, str]]]:
    """Spec 060: the template's devbox.json wins; recipes, packages and env vars only the project has are kept.
    Returns (merged, kept labels, replaced (label, project's old value)). With a baseline (the template at the repo's
    previous platform version, spec 086), an entry equal to the baseline's is a template change, not a replaced one."""
    import copy
    merged = copy.deepcopy(template)
    kept: list[str] = []
    replaced: list[tuple[str, str]] = []
    base = baseline or {}

    mine = (project.get("shell") or {}).get("scripts") or {}
    theirs = (template.get("shell") or {}).get("scripts") or {}
    bscripts = (base.get("shell") or {}).get("scripts") or {}
    for name, cmd in mine.items():
        if name not in theirs:
            merged.setdefault("shell", {}).setdefault("scripts", {})[name] = cmd
            kept.append(f"scripts {name}")
        elif _cmd(cmd) != _cmd(theirs[name]) and not (name in bscripts and _cmd(bscripts[name]) == _cmd(cmd)):
            replaced.append((f"scripts {name}", _cmd(cmd)))

    pkgs, tpkgs, bpkgs = project.get("packages"), template.get("packages"), base.get("packages")
    if isinstance(pkgs, list) and isinstance(tpkgs, list):
        tnames = {p.split("@", 1)[0]: p for p in tpkgs}
        bnames = {p.split("@", 1)[0]: p for p in bpkgs} if isinstance(bpkgs, list) else {}
        for p in pkgs:
            name = p.split("@", 1)[0]
            if name not in tnames:
                merged["packages"].append(p)
                kept.append(f"packages {p}")
            elif p != tnames[name] and bnames.get(name) != p:
                replaced.append((f"packages {name}", p))
    elif isinstance(pkgs, dict) and isinstance(tpkgs, dict):
        bd = bpkgs if isinstance(bpkgs, dict) else {}
        for name, ver in pkgs.items():
            if name not in tpkgs:
                merged["packages"][name] = ver
                kept.append(f"packages {name}")
            elif ver != tpkgs[name] and not (name in bd and bd[name] == ver):
                replaced.append((f"packages {name}", str(ver)))

    tenv = template.get("env") or {}
    benv = base.get("env") or {}
    for name, val in (project.get("env") or {}).items():
        if name not in tenv:
            merged.setdefault("env", {})[name] = val
            kept.append(f"env {name}")
        elif val != tenv[name] and not (name in benv and benv[name] == val):
            replaced.append((f"env {name}", str(val)))
    return merged, kept, replaced


def render_baseline(template: str, old: str | None, answers: str, dest: Path) -> Path | None:
    """The template as rendered at platform `old` with the repo's pre-update answers, or None when it cannot be (spec 086)."""
    if not old:
        return None
    try:
        src = dest / "src"
        src.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(["git", "archive", f"v{old}", f"templates/{template}"], cwd=PLATFORM_ROOT, capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(src)], input=archive.stdout, capture_output=True, check=True)
        data = dest / "answers.yml"
        data.write_text(answers)
        out = dest / "out"
        out.mkdir()
        subprocess.run([*core.find_copier(), "copy", str(src / "templates" / template), str(out), "--data-file", str(data),
                        "--overwrite", "--defaults", "--trust", "--skip-tasks"], capture_output=True, check=True)
        return out
    except Exception:   # the baseline is advisory: the update never fails because of it
        return None


def move_ci_gates(project: dict, template: dict, baseline: dict | None) -> tuple[list[str], list[str]]:
    """-> (moved, dropped): gates of the project's old `ci` the new template `ci` does not run (and the baseline `ci`
    did not run). `moved` when the project has no `ci-extra`, else `dropped`."""
    def scripts(d: dict | None) -> dict:
        return {k: _cmd(v) for k, v in ((d or {}).get("shell") or {}).get("scripts", {}).items()}
    mine, theirs, base = scripts(project), scripts(template), scripts(baseline)
    merged = {**mine, **theirs}
    known = {gates._real(g, theirs) for g in gates.chain(theirs.get("ci", ""))}
    if baseline is not None:
        known |= {gates._real(g, base) for g in gates.chain(base.get("ci", ""))}
    missing: list[str] = []
    for g in gates.chain(mine.get("ci", "")):
        if g != gates.CI_EXTRA and g not in missing and gates._real(g, merged) not in known:
            missing.append(g)
    return (missing, []) if gates.CI_EXTRA not in mine else ([], missing)


def _ci_is_template_change(project: dict, template: dict, baseline: dict | None, taken: list[str]) -> bool:
    """True when the project's `ci`, minus the gates moved or dropped, is the old template's `ci` (spec 086)."""
    suffix = " && " + gates.CI_EXTRA_STEP

    def ci(d: dict | None) -> str:
        cmd = _cmd((((d or {}).get("shell") or {}).get("scripts") or {}).get("ci", ""))
        return cmd[:-len(suffix)] if cmd.endswith(suffix) else cmd   # a `ci` from this platform version ends with the step
    mine = ci(project)
    steps = [g for g in gates.chain(mine) if g not in taken]
    if mine != " && ".join(f"devbox run {g}" for g in gates.chain(mine)):
        return False
    if baseline is not None:
        return steps == gates.chain(ci(baseline))
    return steps == [g for g in gates.chain(ci(template)) if g != gates.CI_EXTRA]


def _readme_changed(template: str, old: str | None) -> bool:
    """True when the template's README changed since the repo's platform version, or that version is unknown."""
    path = f"templates/{template}/README.md.jinja"
    if not old:
        return True
    rc = run(["git", "diff", "--quiet", f"v{old}", "--", path], cwd=PLATFORM_ROOT, check=False).returncode
    return rc != 0


def refresh_devbox_lock(repo: Path, changed: list[str]) -> str | None:   # tests replace this
    """devbox.lock must match the merged devbox.json, or the next `devbox install` rewrites it and every run starts with a dirty
    tree. Returns a next step when the lock could not be refreshed here."""
    if "devbox.json" not in changed or not (repo / "devbox.lock").is_file():
        return None
    step = "run `devbox install` and commit devbox.lock in this branch, or the next devbox run rewrites it"
    if shutil.which("devbox") is None:
        return "devbox is not installed here: " + step
    proc = run(["devbox", "install"], cwd=repo, check=False, timeout=1800)
    if proc.returncode != 0:
        return f"`devbox install` failed (exit {proc.returncode}), so devbox.lock may not match devbox.json: " + step
    return None


def ensure_playwright(repo: Path, template: str) -> tuple[bool, str | None]:
    """Spec 091: every web-nextjs repo has the Playwright scaffold, so a project-owned package.json that opted out gets
    `@playwright/test` and the `e2e` script. Returns (added, next step when the lockfile could not be refreshed)."""
    path = repo / "package.json"
    if not path.is_file():
        return False, None
    try:
        pkg = json.loads(path.read_text())
    except ValueError:
        return False, None
    if not isinstance(pkg, dict) or any("@playwright/test" in (pkg.get(k) or {}) for k in ("dependencies", "devDependencies")):
        return False, None
    src = PLATFORM_ROOT / "templates" / template / "package.json.jinja"
    m = re.search(r'"@playwright/test"\s*:\s*"([^"]+)"', src.read_text()) if src.is_file() else None
    pkg.setdefault("devDependencies", {})["@playwright/test"] = m.group(1) if m else "latest"
    if isinstance(pkg.get("scripts"), dict):
        pkg["scripts"].setdefault("e2e", "playwright test")
    path.write_text(json.dumps(pkg, indent=2) + "\n")
    step = "refresh the lockfile: devbox run -- pnpm install, then commit pnpm-lock.yaml"
    try:
        proc = run(["devbox", "run", "--", "pnpm", "install", "--lockfile-only"], cwd=repo, check=False, timeout=600)
    except (PlatformError, OSError):
        return True, step
    return True, (step if proc.returncode != 0 else None)


def merge_devbox_file(repo: Path, before: str | None, baseline: dict | None = None
                      ) -> tuple[list[str], list[tuple[str, str]], str | None, list[str], list[str]]:
    """Merge the project's devbox.json (before the update) into the rendered one. Rewrites only when something is kept or moved.
    Returns (kept, replaced, note, moved to ci-extra, dropped gates)."""
    path = repo / "devbox.json"
    if before is None or not path.is_file():
        return [], [], None, [], []
    try:
        project = json.loads(before)
    except ValueError:
        return [], [], "devbox.json was not valid JSON: replaced by the template's file — re-add your recipes from `git show HEAD~1:devbox.json`", [], []
    text = path.read_text()
    template = json.loads(text)
    merged, kept, replaced = merge_devbox(project, template, baseline)
    moved, dropped = move_ci_gates(project, template, baseline)
    if moved:
        merged.setdefault("shell", {}).setdefault("scripts", {})[gates.CI_EXTRA] = " && ".join(f"devbox run {g}" for g in moved)
    if kept or moved:
        path.write_text(_insert_kept(text, template, merged))
    if _ci_is_template_change(project, template, baseline, moved + dropped):
        replaced = [(k, v) for k, v in replaced if k != "scripts ci"]
    return kept, replaced, None, moved, dropped


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


def _load_json(path: Path) -> dict | None:
    try:
        v = json.loads(path.read_text())
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def _current_ci_extra(devbox_before: str | None) -> str:
    try:
        return _cmd(((json.loads(devbox_before or "{}").get("shell") or {}).get("scripts") or {}).get(gates.CI_EXTRA, ""))
    except ValueError:
        return ""


def _ci_extra_line(current: str, names: list[str]) -> str:
    return '"ci-extra": "' + " && ".join(([current] if current else []) + [f"devbox run {g}" for g in names]) + '"'


WHERE_RECIPE = "re-add it under a new recipe name; gates belong in the ci-extra recipe"
WHERE_FILES = {
    ".github/workflows/ci.yml": "gates belong in the ci-extra recipe, extra jobs in a workflow file of your own in .github/workflows/",
    settingsmerge.REL: "only your own permission entries (allow, ask, deny) are kept; other settings are the platform's",
    "CLAUDE.md": "project guidance belongs in .claude/project-notes.md (CLAUDE.md loads it; updates never change it)",
}
NOT_CUSTOMISATION = ("devbox.json", settingsmerge.REL, ".copier-answers.yml", ".platform-version")


def _where_file(path: str) -> str:
    return WHERE_FILES.get(path) or f"it has no repo-owned companion: keep yours with git checkout HEAD~1 -- {path} and propose the change with /shared:report-issue"


def _lost(repo: Path, modified: list[str], replaced: list[tuple[str, str]], dropped_gates: list[str], settings: dict,
          base_root: Path | None, current_extra: str, notes: list[str | None] = ()) -> list[dict]:
    """Everything the repo had added that the update overwrote (spec 086): empty exactly when nothing was lost."""
    lost: list[dict] = [{"kind": "recipe", "file": "devbox.json", "entry": k, "was": v, "where": WHERE_RECIPE} for k, v in replaced]
    lost += [{"kind": "gate", "file": "devbox.json", "entry": g, "was": None,
              "where": "add it to ci-extra: " + _ci_extra_line(current_extra, [g])} for g in dropped_gates]
    lost += [{"kind": "setting", "file": settingsmerge.REL, "entry": e["key"], "was": e["was"], "where": WHERE_FILES[settingsmerge.REL]}
             for e in settings["replaced"]]
    for note, path in zip(notes, ("devbox.json", settingsmerge.REL)):
        if note:   # invalid JSON: the template's file replaced the repo's, and its entries are gone
            m = re.search(r"re-add.*", note)
            lost.append({"kind": "file", "file": path, "entry": None, "was": None, "where": m.group(0) if m else note})
    for path in modified:
        if path in NOT_CUSTOMISATION:
            continue
        if base_root is not None:
            mine = run(["git", "show", f"HEAD:{path}"], cwd=repo, check=False)
            theirs = base_root / path
            try:
                if mine.returncode == 0 and theirs.is_file() and theirs.read_text() == mine.stdout:
                    continue   # the repo never touched it: a template change
            except (OSError, UnicodeDecodeError):
                pass
        lost.append({"kind": "file", "file": path, "entry": None, "was": None, "where": _where_file(path)})
    return lost


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
    settings_file = repo / settingsmerge.REL
    settings_before = settings_file.read_text() if settings_file.is_file() else None
    ci_file = repo / ".github" / "workflows" / "ci.yml"
    had_pin_dev = (ci_file.is_file() and "\n  pin-dev:" in ci_file.read_text()) or (repo / ".github/workflows/pin-dev.yml").is_file()

    cmd = [*core.find_copier(), "copy", str(PLATFORM_ROOT / "templates" / req["template"]), ".", "--data-file", ".copier-answers.yml",
           "--overwrite", "--defaults", "--trust", "--skip-tasks"]
    for kv in req["data"]:
        cmd += ["--data", kv]
    run(cmd, cwd=repo)
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

    tmp = tempfile.TemporaryDirectory()
    try:
        return _finish(req, r, before, devbox_before, settings_before, had_pin_dev, cur, branch, Path(tmp.name))
    finally:
        tmp.cleanup()


def _finish(req: dict, r: Report, before: str, devbox_before: str | None, settings_before: str | None, had_pin_dev: bool,
            cur: str, branch: str, tmp: Path) -> Report:
    repo: Path = req["repo"]
    answers = repo / ".copier-answers.yml"
    base_root: Path | None = None
    if run(["git", "status", "--porcelain"], cwd=repo).stdout.strip():   # a no-op update renders no baseline
        base_root = render_baseline(req["template"], req["old"], before, tmp)
    base_devbox = _load_json(base_root / "devbox.json") if base_root else None
    base_settings = _load_json(base_root / settingsmerge.REL) if base_root else None
    kept, replaced, devbox_note, moved, dropped_gates = merge_devbox_file(repo, devbox_before, base_devbox)
    settings, settings_note = settingsmerge.merge_settings_file(repo, settings_before, base_settings)

    if req["shape"] == "web-nextjs":
        added, lock_next = ensure_playwright(repo, req["template"])
        if added:
            r.did.append("added @playwright/test to package.json (spec 091: browser smoke tests)")
        if lock_next:
            r.next_steps.append(lock_next)

    new_keys = sorted(set(re.findall(r"^([a-z_]+):", answers.read_text(), re.M)) - set(re.findall(r"^([a-z_]+):", before, re.M)))
    changed = [ln[3:] for ln in run(["git", "status", "--porcelain"], cwd=repo).stdout.splitlines()]
    modified = [ln[3:] for ln in run(["git", "status", "--porcelain"], cwd=repo).stdout.splitlines() if ln[:2].strip() == "M"
                and not (ln[3:] == "devbox.json" and not replaced and not devbox_note)]   # merged, nothing lost (spec 060)
    if kept:
        r.did.append("kept in devbox.json: " + "; ".join(kept))
    if moved:
        r.did.append("moved to ci-extra: " + ", ".join(moved))
    if settings["kept"]:
        r.did.append("kept in .claude/settings.json: " + "; ".join(f"{k['list']} {k['entry']}" for k in settings["kept"]))
    if settings["removed_by_platform"]:
        r.did.append("removed by the platform from .claude/settings.json: " + "; ".join(f"{k['list']} {k['entry']}" for k in settings["removed_by_platform"]))
    if not changed:
        if cur in ("main", "master"):  # do not leave an empty review branch behind
            run(["git", "checkout", "-q", cur], cwd=repo)
            run(["git", "branch", "-D", branch], cwd=repo)
        r.did.append(f"already up to date with platform {req['new']} — nothing changed")
        return r
    current_extra = _current_ci_extra(devbox_before)
    lost = _lost(repo, modified, replaced, dropped_gates, settings, base_root, current_extra, [devbox_note, settings_note])
    lock_step = refresh_devbox_lock(repo, changed)
    if lock_step:
        r.next_steps.append(lock_step)
    elif "devbox.json" in changed and (repo / "devbox.lock").is_file():
        r.did.append("refreshed devbox.lock for the merged devbox.json")
    run(["git", "add", "-A"], cwd=repo)
    run(["git", *core.git_identity(repo), "commit", "-q", "-m", f"chore: update skeleton from platform {req['new']}"], cwd=repo)
    r.did.append(f"re-applied the template; {len(changed)} file(s) changed, committed on {branch if cur in ('main','master') else cur}")
    notes = core.changelog_between(req["old"], req["new"])
    r.data = {"changed": changed, "modified": modified, "new_answers": new_keys, "changelog": notes,
              "baseline": req["old"] if base_root else None,
              "devbox": {"kept": kept, "replaced": [{"entry": k, "was": v} for k, v in replaced],
                         "moved_to_ci_extra": moved, "dropped_gates": dropped_gates},
              "settings": settings, "lost": lost}
    if dropped_gates:
        r.next_steps.append(f"dropped from ci (ci-extra exists and was left unchanged): {', '.join(dropped_gates)}; add them with "
                            + _ci_extra_line(current_extra, dropped_gates))
    if settings_note:
        r.next_steps.append(settings_note)
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
    for e in lost:
        r.next_steps.append(f"replaced {e['file']}{' ' + e['entry'] if e['entry'] else ''}: the template's version wins; {e['where']}")
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
