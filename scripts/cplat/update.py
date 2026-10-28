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
import time
from pathlib import Path

import yaml

import core
import gates
import gitops
import migrate5
import settingsmerge
import shapecmd
from core import PLATFORM_ROOT, PlatformError, Report, run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat platform update", description=__doc__)
    p.add_argument("--ref", default=None, help="platform ref being applied (informational; the running checkout is the source)")
    p.add_argument("--data", action="append", default=[], metavar="KEY=VALUE", help="change a template answer (repeatable)")
    p.add_argument("--repo", default=".", help="repo to update (default: current directory)")
    p.add_argument("--migrate", action="store_true", help="4.x → 5.0 (system.yaml, plugins; v1 `k8s/` removal included)")
    p.add_argument("--skip-tasks", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--verify", action="store_true", help="after the update is merged and synced: operators, moved dev pins, every environment's smoke tests (spec 121)")
    p.add_argument("--context", action="append", metavar="[ENV=]CTX", help="with --verify: kube context (of one environment, or of all); repeatable")
    p.add_argument("--component-dir", action="append", metavar="C=DIR", help="with --verify: a checkout of a component for the smoke tests; repeatable")
    p.add_argument("--app", help="with --verify: the application (when the repo has several)")
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
    if shapecmd.resolve(repo) == "platform":
        raise PlatformError("the platform repo is not updated from a template",
                            hint="the platform is released through its own procedure: CONTRIBUTING.md, Releases")
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
    unmigrated = _major(stamp.get("platform")) < 5 or (shape == "gitops-app" and bool(_old_files(repo)))
    if unmigrated and not ns.migrate:
        raise PlatformError(f"this repo is on platform {stamp.get('platform') or 'none'}: 5.0 changes its files and plugins",
                            hint="run cplat platform update --migrate (or /platform:update --migrate)")
    return {"unmigrated": unmigrated,"repo": repo, "shape": shape, "template": entry["template"], "data": ns.data, "old": stamp.get("platform"),
            "new": core.platform_version(), "ref": ns.ref or stamp.get("ref") or "main", "skip_tasks": ns.skip_tasks, "migrate": ns.migrate,
            "dry_run": ns.dry_run, "json": ns.json}


def _major(version: str | None) -> int:
    try:
        return int(str(version).split(".")[0])
    except ValueError:
        return -1


def _old_files(repo: Path) -> list[str]:
    """The 4.x inputs (applications/*/app.yaml, services.yaml) a gitops-app repo still has, as repo-relative paths."""
    base = repo / "applications"
    return sorted(p.relative_to(repo).as_posix() for f in ("app.yaml", "services.yaml") for p in base.glob(f"*/{f}"))


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


# repo-owned once they exist, but the skeleton needs them: added when missing, never replaced (CLAUDE.md imports the notes, #239)
SEEDS = {".secrets.baseline.json", ".claude/project-notes.md"}


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


def _archive(tag: str, path: str, root: Path) -> bytes:
    """`git archive <tag> <path>` in the platform checkout. The marketplace clone cplat runs from is shallow and has no
    tags, so a missing tag is fetched from origin first; without it every difference would count as a customisation."""
    cmd = ["git", "archive", tag, path]
    got = subprocess.run(cmd, cwd=root, capture_output=True)
    if got.returncode != 0:
        subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", f"refs/tags/{tag}:refs/tags/{tag}"], cwd=root,
                       capture_output=True, check=True)
        got = subprocess.run(cmd, cwd=root, capture_output=True, check=True)
    return got.stdout


def render_baseline(template: str, old: str | None, answers: str, dest: Path, root: Path = PLATFORM_ROOT) -> Path | None:
    """The template as rendered at platform `old` with the repo's pre-update answers, or None when it cannot be (spec 086)."""
    if not old:
        return None
    try:
        src = dest / "src"
        src.mkdir(parents=True, exist_ok=True)
        archive = _archive(f"v{old}", "templates", root)
        subprocess.run(["tar", "-x", "-C", str(src)], input=archive, capture_output=True, check=True)
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


RENDER_V4 = PLATFORM_ROOT / "scripts" / "cplat" / "assets" / "render_v4.py"   # the frozen 4.7 renderer (spec 114)
OLD_NAMES = ("app.yaml", "services.yaml")
NOT_RENDERED = (*OLD_NAMES, "system.yaml")


def _owner(repo: Path) -> str | None:
    org = gitops.answers(repo).get("github_org")
    if org:
        return str(org)
    url = run(["git", "remote", "get-url", "origin"], cwd=repo, check=False).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+)/", url)
    return m.group(1) if m else None


def _tree(root: Path) -> dict[str, bytes]:
    """Every generated file under applications/ and bootstrap/ (path -> bytes); the system's inputs are not generated."""
    out: dict[str, bytes] = {}
    for base in ("applications", "bootstrap"):
        for p in sorted((root / base).rglob("*")) if (root / base).is_dir() else []:
            if p.is_file() and p.name not in NOT_RENDERED:
                out[p.relative_to(root).as_posix()] = p.read_bytes()
    return out


_CLUSTER_FILE = re.compile(r"^applications/[^/]+/addons/[^/]+/[^/]+/cluster\.yaml$")
_DB_IMAGE = re.compile(rb"(imageName: ghcr\.io/cloudnative-pg/postgresql:)(\d+)\S*")


def _digested_refs(repo: Path) -> list[bytes]:
    """The engine image references of the repo's renderer table that carry a digest (spec 121), except the database ones."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("render_repo_pins", repo / "scripts" / "render.py")
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 - an unreadable renderer is reported by the render itself
        return []
    refs = [*mod.VALKEY_IMAGES.values(), *mod.NATS_IMAGES.values(), mod.SEAWEEDFS_IMAGE, mod.VELERO_AWS_PLUGIN_IMAGE, mod.COLLECTOR_IMAGE,
            mod.LGTM_IMAGE]
    return [r.encode() for r in refs if "@sha256:" in r]


def _normalised(tree: dict[str, bytes], pins: list[bytes] = ()) -> dict[str, bytes]:
    """The migration proof ignores the database image beyond its major (AC-115.6, AC-115.17) and the digest the versions
    table (spec 121) adds to the other engine images: exactly those references, mapped back to tag only."""
    out = {}
    for p, b in tree.items():
        b = _DB_IMAGE.sub(rb"\1\2", b) if _CLUSTER_FILE.match(p) else b
        for ref in pins:
            b = b.replace(ref, ref.split(b"@", 1)[0])
        out[p] = b
    return out


def convert_systems(repo: Path) -> list[dict]:
    """Convert every 4.x application directory; any problem stops the migration before anything changes."""
    owner = _owner(repo)
    found: list[dict] = []
    problems: list[str] = []
    for rel in _old_files(repo):
        d = Path(rel).parent
        if any(f["dir"] == d for f in found):
            continue
        texts = {n: (repo / d / n).read_text() if (repo / d / n).is_file() else "" for n in OLD_NAMES}
        try:
            docs = {n: yaml.safe_load(t) or {} for n, t in texts.items()}
        except yaml.YAMLError as e:
            raise PlatformError(f"cannot migrate {d} to 5.0: {str(e).splitlines()[0]}", hint="nothing was changed; fix the YAML and run again") from e
        conv = migrate5.convert(d.name, docs["app.yaml"], docs["services.yaml"], owner)
        problems += [f"{d}/{p}" if p.startswith(OLD_NAMES) else p for p in conv.problems]
        found.append({"dir": d, "text": migrate5.dump(conv.doc), "comments": any(migrate5.has_comments(t) for t in texts.values()),
                      "deleted": [f"{d.as_posix()}/{n}" for n in OLD_NAMES if (repo / d / n).is_file()]})
    if problems:
        names = ", ".join(f["dir"].as_posix() for f in found)
        raise PlatformError(f"cannot migrate {names} to 5.0: these values have no place in system.yaml:\n  " + "\n  ".join(problems),
                            hint="nothing was changed; remove or move them, commit, and run again")
    return found


def reference_render(repo: Path, tmp: Path) -> dict[str, bytes]:
    """What the frozen 4.7 renderer makes of HEAD (in a temporary copy)."""
    root = tmp / "v4"
    root.mkdir()
    archive = subprocess.run(["git", "archive", "HEAD"], cwd=repo, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(root)], input=archive, capture_output=True, check=True)
    (root / "scripts").mkdir(exist_ok=True)
    shutil.copyfile(RENDER_V4, root / "scripts" / "render.py")
    run(["uv", "run", "scripts/render.py"], cwd=root)
    return _tree(root)


def apply_systems(repo: Path, systems: list[dict], reference: dict[str, bytes]) -> None:
    """Write system.yaml, delete the old inputs, render with the repo's 5.0 renderer and compare with the 4.7 render."""
    for s in systems:
        (repo / s["dir"] / "system.yaml").write_text(s["text"])
        for rel in s["deleted"]:
            (repo / rel).unlink()
    gitops.render(repo)
    pins = _digested_refs(repo)
    reference = _normalised(reference)
    after = _normalised(_tree(repo), pins)
    diff =[f"{p} (changed)" for p in sorted(reference) if p in after and after[p] != reference[p]]
    diff += [f"{p} (missing)" for p in sorted(reference) if p not in after]
    diff += [f"{p} (extra)" for p in sorted(after) if p not in reference]
    if diff:
        names = ", ".join(s["dir"].as_posix() for s in systems)
        raise PlatformError(f"cannot migrate {names} to 5.0: the 5.0 render differs from 4.7:\n  " + "\n  ".join(diff),
                            hint="nothing was changed; report it with /issue:report")


def _ignored(repo: Path) -> set[str]:
    return set(run(["git", "ls-files", "--others", "--ignored", "--exclude-standard"], cwd=repo, check=False).stdout.splitlines())


def rollback(repo: Path, cur: str, branch: str, created: bool, ignored: set[str]) -> None:
    """Back to the state before the migration: tracked files, untracked files and the ignored files the migration made."""
    run(["git", "reset", "--hard", "-q"], cwd=repo, check=False)
    run(["git", "clean", "-fdq"], cwd=repo, check=False)
    for rel in _ignored(repo) - ignored:
        (repo / rel).unlink(missing_ok=True)
    if created:
        run(["git", "checkout", "-q", cur], cwd=repo, check=False)
        run(["git", "branch", "-D", branch], cwd=repo, check=False)


# ---------------- versions: the change list of a gitops-app update (spec 121, AC-121.11, AC-121.20, AC-121.23) ----------------

def _targets(mod, app_dir: Path, system: str, r: str, typ: str, env: str):
    """The rendered file of an instance: (path, type)."""
    folder = app_dir / "addons" / env / r
    if typ == "database":
        base = f"{system}-{r}"
        try:
            active = next(c["name"] for c in mod.read_restore_state(app_dir, env, r)[0] if c["role"] == "active")
        except (mod.RenderError, StopIteration):
            return None
        return folder / ("cluster.yaml" if active == base else f"cluster-g{active[len(base) + 2:]}.yaml")
    return folder / {"cache": "statefulset.yaml", "broker": "server.yaml", "bucket": "seaweed.yaml"}[typ]


def _instances(mod, repo: Path) -> dict[tuple[str, str, str], dict]:
    """{(system, resource, env): {type, major, pin (rendered now, or None), table}} of every in-cluster resource instance."""
    out: dict[tuple[str, str, str], dict] = {}
    for sysfile in sorted((repo / "applications").glob("*/system.yaml")):
        app_dir = sysfile.parent
        try:
            doc = yaml.safe_load(sysfile.read_text()) or {}
            cfgs = mod.validate_resources(doc, app_dir)
        except Exception:  # noqa: BLE001 - an invalid system is reported by the render itself
            continue
        system = str(doc.get("system") or app_dir.name)
        for r, rc in cfgs.items():
            typ = rc["type"]
            for env, e in rc["envs"].items():
                if e.get("external"):
                    continue
                major = e.get("version")
                path = _targets(mod, app_dir, system, r, typ, env)
                held = mod.rendered_pin(path, typ) if path else None
                try:
                    table = mod.table_pin(typ, major if typ != "bucket" else None)["pin"]
                except KeyError:
                    table = None
                out[(system, r, env)] = {"type": typ, "major": major, "pin": held["pin"] if held else None, "table": table}
    return out


_OPERATOR_REV = re.compile(r"^\s*targetRevision:\s*['\"]?([^\s'\"]+)", re.M)


def _operator_revisions(repo: Path) -> dict[str, str]:
    out = {}
    for p in sorted((repo / "operators" / "apps").glob("*.yaml")):
        m = _OPERATOR_REV.search(p.read_text())
        if m:
            out[p.stem] = m.group(1)
    return out


def _generated_snapshot(repo: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for top in ("applications", "operators"):
        for p in sorted((repo / top).rglob("*")) if (repo / top).is_dir() else []:
            if p.is_file():
                out[p.relative_to(repo).as_posix()] = p.read_bytes()
    return out


def render_and_compare(req: dict, repo: Path, written: set[str] | None = None) -> dict | None:
    """Re-render with the repo's new renderer (held pins follow from it) and list what moves, per environment; None when nothing does.
    `written` (optional) receives every path under applications/ and operators/ the render created or changed: generated output."""
    import upgrade
    mod = upgrade.load_renderer(repo)
    before = _instances(mod, repo)
    ops_before = _operator_revisions(repo)
    snap = _generated_snapshot(repo) if written is not None else {}
    gitops.render(repo)
    if written is not None:
        now = _generated_snapshot(repo)
        written |= {k for k, v in now.items() if snap.get(k) != v}
    after = _instances(mod, repo)
    ops_after = _operator_revisions(repo)
    order = {e: i for i, e in enumerate(core_envs())}
    rows: list[dict] = []
    moved_now = {k[:2] for k in after if k in before and before[k]["pin"] and after[k]["pin"] and before[k]["pin"] != after[k]["pin"]}
    for key in sorted(after, key=lambda k: (k[0], k[1], order.get(k[2], 9))):
        system, r, env = key
        a, b = after[key], before.get(key)
        if b is None or b["pin"] is None or a["pin"] is None:
            continue
        label = f"{r} {a['major']}" if a["type"] != "bucket" else r
        if a["pin"] != b["pin"]:
            rows.append({"env": env, "resource": r, "kind": "pin", "from": b["pin"], "to": a["pin"], "moves": True,
                         "text": f"{env:<8} {label}: {b['pin']} → {a['pin']} (moves now)"})
        elif env != "dev" and (system, r) in moved_now and a["table"] and a["table"] != a["pin"]:
            until = (f"/resource:upgrade {r} --to {a['major']} --env {env}" if a["type"] != "bucket"
                     else "dev is verified and /platform:update runs again")
            rows.append({"env": env, "resource": r, "kind": "pin", "from": a["pin"], "to": a["table"], "moves": False,
                         "text": f"{env:<8} {label}: keeps {a['pin']} until {until}"})
    envs = [e for e in core_envs() if any(k[2] == e for k in after)] or core_envs()
    for name in sorted(ops_after):
        if name in ops_before and ops_before[name] != ops_after[name]:
            rows.append({"env": "cluster", "resource": name, "kind": "operator", "from": ops_before[name], "to": ops_after[name], "moves": True,
                         "text": f"{'cluster':<8} operator {name} {ops_before[name]} → {ops_after[name]} "
                                 f"(operators/apps; shared by {', '.join(envs)}: moves with {envs[0]}'s step)"})
    if not rows:
        return None
    return {"from": req["old"] or "none", "to": req["new"], "rows": rows, "lines": [x["text"] for x in rows]}


def core_envs() -> list[str]:
    import model
    return list(model.ENVIRONMENTS)


def versions_block(versions: dict) -> str:
    return "\n".join([f"versions in this system (platform {versions['from']} → {versions['to']}):", *[f"  {ln}" for ln in versions["lines"]]])


# ---------------- --verify (spec 121, AC-121.20 .. AC-121.22) ----------------

OPERATOR_WAIT_S = 900.0
OPERATOR_POLL_S = 10.0


def _wait_operators(repo: Path, contexts: dict[str, str]) -> bool:
    """Wait for every operator row to read `ok` (installed = the table's version and its CRDs serve the table's versions)."""
    import doctor
    start = time.monotonic()
    while True:
        rows = [row for row in doctor.check_operators(repo, contexts) if row.get("operator")]
        pending = [row for row in rows if row["operator"]["state"] != "ok"]
        if not pending:
            for row in rows:
                print(f"  ok   {row['name']}: {row['detail']}")
            return True
        elapsed = time.monotonic() - start
        if elapsed >= OPERATOR_WAIT_S:
            for row in pending:
                print(f"  FAIL {row['name']}: {row['detail']} (not ok after {int(OPERATOR_WAIT_S // 60)} minutes)")
                if row.get("fix"):
                    print(f"       fix: {row['fix']}")
            return False
        time.sleep(OPERATOR_POLL_S)


def verify_update(ns: argparse.Namespace) -> int:
    """After the update is merged and synced: operators once per cluster, the moved dev pins, then every environment's smoke tests; on
    success the staging pin moves. (One cluster_server per gitops repo today, so all environments are one group; grouping by server would
    run AC-121.20's order, dev's cluster first, when a later release gives an environment its own cluster.)"""
    import model
    import status
    import upgradeverify as uv
    repo = Path(ns.repo).resolve()
    app_dir = gitops.find_app(repo, ns.app)
    m = model.load_dir(app_dir)
    contexts = status.parse_contexts(ns.context, list(model.ENVIRONMENTS))
    dirs = uv.parse_dirs(ns.component_dir)
    print("verify platform update: operators")
    if not _wait_operators(repo, contexts):
        print("NOT VERIFIED: an operator is not at the table's version; no environment is checked until it is")
        return 1
    moved = []
    for res in m.resources:
        ri = next((x for x in m.resource_instances if x.resource == res.name and x.environment == "dev"), None)
        if res.type not in ("database", "cache", "broker") or ri is None or ri.external:
            continue
        moved.append(res.name)
    results = []
    for name in moved:
        result = uv.verify(repo, ns.app, name, "dev", contexts, dirs)
        for line in result.lines:
            print(line)
        if not result.ok:
            return 1
        results.append(result)
    print("smoke tests of every component instance")
    comps = {c.name: c for c in m.components}
    for inst in m.instances:
        comp = comps.get(inst.component)
        if comp is None or comp.external:
            continue
        passed, text = uv.run_component_smoke(m, comp, inst.environment, dirs)
        print(f"  {'ok  ' if passed else 'FAIL'} smoke {comp.name} ({inst.environment}): {text}")
        if not passed:
            print("NOT VERIFIED: no later step is started")
            return 1
    import upgrade
    rc = 0
    for result in results:
        if result.auto_staging:
            sub = argparse.Namespace(repo_dir=str(repo), app=ns.app, context=ns.context, component_dir=ns.component_dir, pr=False, wait=False)
            try:
                rc = upgrade.main(uv.staging_argv(sub, result.resource, result.major)) or rc
            except PlatformError as e:
                print(f"the staging step was not started: {e}")
                rc = 1
        elif result.next:
            print(f"next: {result.next}")
    return rc


def _list(names: list[str]) -> str:
    return ", ".join(names) or "none"


def plan_migration(req: dict, r: Report) -> None:
    """--dry-run --migrate: the converted system.yaml, the files to delete and the plugin switch; nothing is written."""
    for s in convert_systems(req["repo"]) if req["shape"] == "gitops-app" else []:
        r.will_do.append(f"would write {s['dir'].as_posix()}/system.yaml:\n" + "\n".join("    " + ln if ln else ln for ln in s["text"].splitlines()))
        r.will_do.append("would delete " + ", ".join(s["deleted"]))
    mine = _load_json(req["repo"] / settingsmerge.REL) or {}
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out"
        cmd = [*core.find_copier(), "copy", str(PLATFORM_ROOT / "templates" / req["template"]), str(out), "--data-file",
               str(req["repo"] / ".copier-answers.yml"), "--overwrite", "--defaults", "--trust", "--skip-tasks"]
        for kv in req["data"]:
            cmd += ["--data", kv]
        run(cmd, cwd=Path(td))
        _, report = settingsmerge.merge_settings(mine, _load_json(out / settingsmerge.REL) or {}, None)
    p = report["plugins"]
    r.will_do.append(f"plugins: would add {_list(p['added'])}; would remove {_list(p['removed'])}")


def plan(req: dict) -> Report:
    was = req["old"] or "none — this repo has no .platform-version stamp yet"
    r = Report(title=f"Update {req['repo'].name} ({req['shape']}) from platform {was} → {req['new']}")
    cur = run(["git", "symbolic-ref", "--short", "HEAD"], cwd=req["repo"], check=False).stdout.strip()
    if cur in ("main", "master"):
        r.will_do.append(f"create review branch {branch_name(req['repo'])}")
    r.will_do.append(f"re-apply templates/{req['template']} with the repo's recorded answers" + (f" plus {', '.join(req['data'])}" if req["data"] else ""))
    r.will_do.append("OVERWRITE skeleton files (CI, Dockerfile, CLAUDE.md, …); project-owned files (README, app code, tests, ADRs) are never touched, and new starter files in those paths are not added")
    r.will_do.append("MERGE devbox.json: the template's recipes and packages, plus the ones only this repo has")
    if req["migrate"] and req["unmigrated"]:
        r.will_do.append("DELETE k8s/ (v1 → v2 migration: manifests are generated in the system's gitops-app repo; recoverable from git history)")
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
    return WHERE_FILES.get(path) or f"it has no repo-owned companion: keep yours with git checkout HEAD~1 -- {path} and propose the change with /issue:report"


def _lost(repo: Path, modified: list[str], replaced: list[tuple[str, str]], dropped_gates: list[str], settings: dict,
          base_root: Path | None, current_extra: str, notes: list[str | None] = (), generated: frozenset[str] | set[str] = frozenset()) -> list[dict]:
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
        if path in NOT_CUSTOMISATION or path in generated:   # generated: the update's own re-render wrote it (spec 121)
            continue
        if base_root is not None:
            mine = run(["git", "show", f"HEAD:{path}"], cwd=repo, check=False)
            theirs = base_root / path
            try:
                if mine.returncode == 0 and theirs.is_file() and theirs.read_text() == mine.stdout:
                    continue   # the repo never touched it: a template change
            except (OSError, UnicodeDecodeError):
                pass
        if path.startswith("applications/"):   # generated output: only the pinned engine images moved (AC-115.6, AC-115.17, spec 121)
            was = run(["git", "show", f"HEAD:{path}"], cwd=repo, check=False)
            try:
                pins = _digested_refs(repo)
                if was.returncode == 0 and _normalised({path: was.stdout.encode()}) == _normalised({path: (repo / path).read_bytes()}, pins):
                    continue
            except OSError:
                pass
        lost.append({"kind": "file", "file": path, "entry": None, "was": None, "where": _where_file(path)})
    return lost


def execute(req: dict) -> Report:
    repo: Path = req["repo"]
    r = plan(req)
    migrating = req["migrate"] and req["unmigrated"]
    systems: list[dict] = []
    reference: dict[str, bytes] = {}
    tmp = tempfile.TemporaryDirectory()
    if migrating and req["shape"] == "gitops-app":   # before anything changes: problems stop here, the 4.7 render is the reference
        systems = convert_systems(repo)
        if systems:
            reference = reference_render(repo, Path(tmp.name))
    cur = run(["git", "symbolic-ref", "--short", "HEAD"], cwd=repo).stdout.strip()
    branch = branch_name(repo)
    created = cur in ("main", "master")
    rendering = req["shape"] == "gitops-app" and not migrating
    ignored = _ignored(repo) if migrating or rendering else set()
    if created:
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
    mig: dict = {"ran": False, "already_migrated": True}
    generated: set[str] = set()
    try:
        run(cmd, cwd=repo)
        dropped = drop_new_project_owned_files(repo, project_owned_patterns(req["template"]))
        written = {f"{s['dir'].as_posix()}/system.yaml" for s in systems}   # the migration writes these next, not left out (#238)
        dropped = [d for d in dropped if d not in written]
        if dropped:
            r.did.append(f"left out {len(dropped)} new starter file(s) in project-owned paths (app code, tests, docs): {', '.join(dropped[:4])}{' ...' if len(dropped) > 4 else ''}")
        answers = repo / ".copier-answers.yml"
        answers.write_text(re.sub(r"^_src_path:.*$", f"_src_path: gh:ika100/sdlc-foundry/templates/{req['template']}", answers.read_text(), flags=re.M))
        core.write_stamp(repo, req["shape"], req["ref"])
        if migrating and (repo / "k8s").is_dir():
            shutil.rmtree(repo / "k8s")
            r.did.append("removed k8s/ (v1 manifests; import them with `cplat component add <component> --from-k8s` if you have not yet)")
        if migrating:
            mig = {"ran": True, "kind": "system" if req["shape"] == "gitops-app" else "component", "byte_identical": None, "compared": 0,
                   "system_yaml": None, "deleted": [], "plugins": {"added": [], "removed": []}, "comments_dropped": False}
            if systems:
                apply_systems(repo, systems, reference)
                mig.update(byte_identical=True, compared=len(reference), system_yaml=f"{systems[0]['dir'].as_posix()}/system.yaml",
                           deleted=sorted(p for s in systems for p in s["deleted"]), comments_dropped=any(s["comments"] for s in systems))
                for s in systems:
                    r.did.append(f"wrote {s['dir'].as_posix()}/system.yaml" + (" (the comments of app.yaml and services.yaml were not carried over)" if s["comments"] else ""))
                r.did.append("deleted " + ", ".join(mig["deleted"]))
                r.did.append(f"the 5.0 render is byte-identical to 4.7 ({mig['compared']} files compared)")
        elif req["migrate"]:
            r.did.append("already migrated to 5.0: nothing of the migration ran")
        if rendering:
            versions = render_and_compare(req, repo, generated)
            if versions:
                r.data["versions"] = versions
                r.did.append(f"re-rendered with the new renderer; {len(versions['lines'])} version change(s) listed below")
    except BaseException:
        if migrating or rendering:
            rollback(repo, cur, branch, created, ignored)
        tmp.cleanup()
        raise
    if req["migrate"]:
        r.data["migration"] = mig
    try:
        return _finish(req, r, before, devbox_before, settings_before, had_pin_dev, cur, branch, Path(tmp.name), generated)
    finally:
        tmp.cleanup()


def _finish(req: dict, r: Report, before: str, devbox_before: str | None, settings_before: str | None, had_pin_dev: bool,
            cur: str, branch: str, tmp: Path, generated: set[str] = frozenset()) -> Report:
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
    if r.data.get("migration", {}).get("ran"):
        r.data["migration"]["plugins"] = settings["plugins"]
        r.did.append(f"plugins added: {_list(settings['plugins']['added'])}; removed: {_list(settings['plugins']['removed'])}")
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
    lost = _lost(repo, modified, replaced, dropped_gates, settings, base_root, current_extra, [devbox_note, settings_note], generated)
    lock_step = refresh_devbox_lock(repo, changed)
    if lock_step:
        r.next_steps.append(lock_step)
    elif "devbox.json" in changed and (repo / "devbox.lock").is_file():
        r.did.append("refreshed devbox.lock for the merged devbox.json")
    run(["git", "add", "-A"], cwd=repo)
    run(["git", *core.git_identity(repo), "commit", "-q", "-m", f"chore: update skeleton from platform {req['new']}"], cwd=repo)
    r.did.append(f"re-applied the template; {len(changed)} file(s) changed, committed on {branch if cur in ('main','master') else cur}")
    notes = core.changelog_between(req["old"], req["new"])
    r.data |= {"changed": changed, "modified": modified, "new_answers": new_keys, "changelog": notes,
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
    ns = build_parser().parse_args(argv)
    if ns.verify:
        return verify_update(ns)
    req = resolve(argv)
    if req["dry_run"]:
        r = plan(req)
        if req["migrate"] and req["unmigrated"]:
            plan_migration(req, r)
        r.emit(True, req["json"])
        return 0
    report = execute(req)
    report.emit(False, req["json"])
    if report.data.get("versions") and not req["json"]:
        print("\n" + versions_block(report.data["versions"]))
    return 0
