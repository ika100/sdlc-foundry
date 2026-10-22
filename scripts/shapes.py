#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Read and validate the shape registry (shapes.yml, ADR-015).

Usage:
  shapes.py validate          schema + referential checks on shapes.yml
  shapes.py check             validate + templates/plugins exist + PRD §4 table matches
  shapes.py get <id> <field>  print one field (plugin, template, deployable, library, status)
  shapes.py ids               print shape ids, one per line

Run with: uv run scripts/shapes.py <cmd>   (PEP 723 inline deps)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ["id", "plugin", "template", "deployable", "library", "detection", "status"]
STATUSES = {"stable", "planned", "deprecated"}
PRD = ROOT / "docs" / "requirements" / "platform-vision.md"


def load() -> list[dict]:
    return yaml.safe_load((ROOT / "shapes.yml").read_text())["shapes"]


def validate(shapes: list[dict]) -> list[str]:
    errs: list[str] = []
    seen: set[str] = set()
    for s in shapes:
        sid = s.get("id", "<missing id>")
        for f in REQUIRED:
            if f not in s:
                errs.append(f"{sid}: missing field '{f}'")
        if sid in seen:
            errs.append(f"{sid}: duplicate id")
        seen.add(sid)
        if s.get("status") not in STATUSES:
            errs.append(f"{sid}: status must be one of {sorted(STATUSES)}")
        det = s.get("detection", {})
        if det.get("copier_src") != f"templates/{s.get('template')}":
            errs.append(f"{sid}: detection.copier_src must be templates/{s.get('template')}")
        if not det.get("sniff"):
            errs.append(f"{sid}: detection.sniff must list at least one marker")
        rt = s.get("runtime")
        if s.get("deployable") and s.get("status") != "planned":
            if not rt:
                errs.append(f"{sid}: deployable shapes need a runtime block (port, probes, user, volumes, env, resources)")
            else:
                for k in ("port", "probes", "user", "resources", "metrics"):
                    if k not in rt:
                        errs.append(f"{sid}: runtime.{k} missing")
                if rt.get("probes", {}).keys() != {"liveness", "readiness"}:
                    errs.append(f"{sid}: runtime.probes needs liveness and readiness")
                if not str(rt.get("metrics", "/")).startswith("/"):
                    errs.append(f"{sid}: runtime.metrics must be a path starting with /")
                if not isinstance(rt.get("user"), int) or rt.get("user", 0) < 1:
                    errs.append(f"{sid}: runtime.user must be a numeric non-root UID")
        globs = s.get("test_globs")
        if s.get("status") != "planned" and (not isinstance(globs, list) or not globs or not all(isinstance(g, str) and g for g in globs)):
            errs.append(f"{sid}: test_globs must list where tests live (ADR-026: `cplat spec trace` searches them for AC ids)")
        checks = s.get("ci_checks")
        if s.get("status") != "planned" and (not isinstance(checks, list) or not checks):
            errs.append(f"{sid}: ci_checks must list the CI job names new repos require on main (spec 054)")
        if s.get("library") and s.get("deployable"):
            errs.append(f"{sid}: a library cannot be deployable")
    return errs


def check_files(shapes: list[dict]) -> list[str]:
    errs: list[str] = []
    for s in shapes:
        tdir = ROOT / "templates" / s["template"]
        pdir = ROOT / "plugins" / s["plugin"]
        if s["status"] != "planned":
            if not (tdir / "copier.yml").is_file():
                errs.append(f"{s['id']}: templates/{s['template']}/copier.yml missing (status {s['status']})")
            if not pdir.is_dir():
                errs.append(f"{s['id']}: plugins/{s['plugin']}/ missing (status {s['status']})")
    return errs


CORE_RECIPES = ["lint", "lint-fix", "quality", "test", "test-fast", "security", "ci"]
DEPLOY_RECIPES = ["image-build", "image-scan"]
CONTRACT_AGENTS = ["coder", "tester"]
DEPLOY_AGENTS = ["deployment", "observability", "release"]


def _template_file(tdir: Path, name: str) -> Path | None:
    for cand in (tdir / name, tdir / f"{name}.jinja"):
        if cand.is_file():
            return cand
    return None


def check_contract(shapes: list[dict]) -> list[str]:
    """PRD §4.1 contract: every non-planned shape ships the template, plugin and detection artifacts."""
    errs: list[str] = []
    detect = (ROOT / "scripts" / "detect-shape.sh").read_text()
    fixtures = (ROOT / "scripts" / "test-detect-shape.sh").read_text()
    for s in shapes:
        if s["status"] == "planned":
            continue
        sid, tdir, pdir = s["id"], ROOT / "templates" / s["template"], ROOT / "plugins" / s["plugin"]
        # 1. template: devbox recipes, CLAUDE.md, plugin enablement
        devbox = _template_file(tdir, "devbox.json")
        if devbox is None:
            errs.append(f"{sid}: template has no devbox.json")
        else:
            text = devbox.read_text()
            need = CORE_RECIPES + (DEPLOY_RECIPES if s["deployable"] else [])
            for r in need:
                if f'"{r}"' not in text:
                    errs.append(f"{sid}: devbox.json missing canonical recipe '{r}'")
        claude = _template_file(tdir, "CLAUDE.md")
        if claude is None:
            errs.append(f"{sid}: template has no CLAUDE.md")
        elif "### Spec first" not in claude.read_text():
            errs.append(f"{sid}: CLAUDE.md has no '### Spec first' section (ADR-024)")
        elif ("/app:spec" if sid == "gitops-app" else "/svc:spec") not in claude.read_text():
            errs.append(f"{sid}: CLAUDE.md 'Spec first' does not name {'/app:spec' if sid == 'gitops-app' else '/svc:spec'} (ADR-026)")
        if not (tdir / "docs" / "plan").is_dir():
            errs.append(f"{sid}: template has no docs/plan/ (ADR-024)")
        # ADR-026: specs live in docs/specs/ (project-owned) and are checked by the warn-only `specs` workflow
        for need in ("docs/specs/README.md", "scripts/spec-check.sh", ".github/workflows/specs.yml"):
            if not (tdir / need).is_file():
                errs.append(f"{sid}: template has no {need} (ADR-026)")
        if devbox is not None and '"spec-check"' not in devbox.read_text():
            errs.append(f"{sid}: devbox.json has no spec-check recipe (ADR-026)")
        if "docs/specs/**" not in (tdir / "copier.yml").read_text():
            errs.append(f"{sid}: copier.yml must list docs/specs/** in _skip_if_exists (project-owned, ADR-026)")
        ci = tdir / ".github" / "workflows" / "ci.yml"
        if s.get("deployable") and sid != "gitops-app" and ci.is_file() and not re.search(
                r"^  pin-dev:\n(?:    .*\n)*?    needs: docker-publish$", ci.read_text(), re.M):
            errs.append(f"{sid}: ci.yml needs a `pin-dev` job after docker-publish (dev follows main, spec 062)")
        skip = (yaml.safe_load((tdir / "copier.yml").read_text()) or {}).get("_skip_if_exists") or []
        if "README.md" not in skip:
            errs.append(f"{sid}: copier.yml must list README.md in _skip_if_exists (project-owned after creation, spec 060)")
        for form in ("bug_report.yml", "feature_request.yml", "config.yml"):
            if not (tdir / ".github" / "ISSUE_TEMPLATE" / form).is_file():
                errs.append(f"{sid}: template has no .github/ISSUE_TEMPLATE/{form} (ADR-025)")
        if sid != "gitops-app" and not (tdir / "docs" / "backlog.md").is_file():
            errs.append(f"{sid}: template has no docs/backlog.md (ADR-024)")
        settings = _template_file(tdir / ".claude", "settings.json")
        if settings is None:
            errs.append(f"{sid}: template has no .claude/settings.json")
        else:
            st = settings.read_text()
            # spec 044: subagent worktrees must branch from the feature branch, not the default branch
            if not __import__("re").search(r'"worktree"\s*:\s*\{\s*"baseRef"\s*:\s*"head"', st):
                errs.append(f'{sid}: .claude/settings.json must set worktree.baseRef: "head" (spec 044)')
            for plugin in (s["plugin"], "shared"):
                if f'"{plugin}@sdlc-foundry": true' not in st:
                    errs.append(f"{sid}: .claude/settings.json does not enable '{plugin}'")
        # 2. plugin: agents
        if s["plugin"] != "gitops":
            agents = CONTRACT_AGENTS + (DEPLOY_AGENTS if s["deployable"] else [])
            for a in agents:
                if s["plugin"] == "svc":
                    break  # svc owns the python shapes and is checked by its own manifest
                if not (pdir / "agents" / f"{a}.md").is_file():
                    errs.append(f"{sid}: plugins/{s['plugin']}/agents/{a}.md missing")
        # 2a000. Dockerfile USER must be numeric, otherwise `runAsNonRoot: true` pods fail with CreateContainerConfigError
        df = _template_file(tdir, "Dockerfile")
        if df is not None:
            for line in df.read_text().splitlines():
                if line.startswith("USER ") and not __import__("re").match(r"USER \d+(:\d+)?\s*$", line):
                    errs.append(f"{sid}: Dockerfile '{line}' must use a numeric UID (e.g. USER 65532:65532)")
        # 2a000. Dockerfile USER must be numeric, otherwise `runAsNonRoot: true` pods fail with CreateContainerConfigError
        df = _template_file(tdir, "Dockerfile")
        if df is not None:
            for line in df.read_text().splitlines():
                if line.startswith("USER ") and not __import__("re").match(r"USER \d+(:\d+)?\s*$", line):
                    errs.append(f"{sid}: Dockerfile '{line}' must use a numeric UID (e.g. USER 65532:65532)")
        # 2a00. k8s label values cannot contain '@' or '/': owner_team ("@org") must go through owner_label
        for kf in (tdir / "k8s").rglob("*") if (tdir / "k8s").is_dir() else []:
            if kf.is_file() and 'team: "{{ owner_team }}"' in kf.read_text():
                errs.append(f"{sid}: {kf.relative_to(tdir)} uses owner_team as a label value; use owner_label")
        # 2a0. the GitOps repo owns every manifest (ADR-017): service templates ship an image, never Kubernetes YAML
        if s["id"] != "gitops-app" and (tdir / "k8s").exists():
            errs.append(f"{sid}: templates/{s['template']}/k8s must not exist; manifests are generated in the gitops-app repo (ADR-017)")
        # 2a. CI must run on pushes to main, otherwise merged code is never built/pushed (found by the e2e test)
        ci = _template_file(tdir / ".github" / "workflows", "ci.yml")
        if ci is None:
            errs.append(f"{sid}: template has no .github/workflows/ci.yml")
        else:
            on_push = ci.read_text().split("pull_request", 1)[0]
            if not __import__("re").search(r"(^|\s|\[|,)main(\s|,|\]|$)", on_push.split("push:", 1)[-1]):
                errs.append(f"{sid}: ci.yml does not trigger on push to main")
        # 2a1. required checks (spec 054) must be real job names, or no pull request could ever merge
        if ci is not None:
            for name in s.get("ci_checks") or []:
                if f"name: {name}\n" not in ci.read_text():
                    errs.append(f"{sid}: ci_checks entry '{name}' is not a job name in ci.yml")
        # 2b. pinned toolchains must agree (a mismatch broke bootstrap: devbox's pnpm cannot switch to a newer pinned one)
        if s["id"] == "web-nextjs":
            import re as _re
            pm = _re.search(r'"packageManager":\s*"pnpm@([0-9.]+)"', (tdir / "package.json.jinja").read_text())
            dv = _re.search(r'"pnpm@([0-9.]+)"', devbox.read_text()) if devbox else None
            if not pm or not dv or pm.group(1) != dv.group(1):
                errs.append(f"{sid}: package.json packageManager pnpm@{pm and pm.group(1)} must equal the devbox.json pin pnpm@{dv and dv.group(1)}")
        # 3. detection registration
        if f"templates/{s['template']}" not in detect:
            errs.append(f"{sid}: scripts/detect-shape.sh has no copier_src case for templates/{s['template']}")
        if "for s in" not in fixtures:  # fixtures iterate over every id in shapes.yml
            errs.append(f"{sid}: detection fixtures do not iterate the registry")
    return errs


def check_front_matter() -> list[str]:
    """Every agent/command must have strictly valid YAML front matter with a description (a bare `: ` in an unquoted
    description is invalid YAML; Claude Code tolerates it, other tools do not) and the description must stay short:
    descriptions are loaded into every session."""
    errs: list[str] = []
    for f in sorted(list((ROOT / "plugins").glob("*/agents/*.md")) + list((ROOT / "plugins").glob("*/commands/*.md"))):
        m = re.match(r"---\n(.*?)\n---", f.read_text(), re.S)
        rel = f.relative_to(ROOT)
        if not m:
            errs.append(f"{rel}: no front matter")
            continue
        try:
            meta = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            errs.append(f"{rel}: front matter is not valid YAML (quote the description)")
            continue
        d = (meta or {}).get("description")
        if not d:
            errs.append(f"{rel}: missing description")
        elif len(d) > 260:
            errs.append(f"{rel}: description is {len(d)} chars (max 260; it is loaded into every session)")
    return errs


def check_adr_index() -> list[str]:
    """Every docs/adr/NNN-*.md must be listed in docs/adr/README.md (the index people actually read)."""
    index = ROOT / "docs" / "adr" / "README.md"
    if not index.is_file():
        return ["docs/adr/README.md is missing"]
    text = index.read_text()
    return [f"docs/adr/{f.name} is not listed in docs/adr/README.md" for f in sorted((ROOT / "docs" / "adr").glob("[0-9]*.md")) if f"]({f.name})" not in text]


def prd_rows() -> dict[str, tuple[str, str]]:
    """Parse the §4 table: shape id -> (plugin, template)."""
    text = PRD.read_text()
    section = text.split("## 4. Shape registry", 1)[1].split("\n## 5.", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.fullmatch(r"[a-z]+(-[a-z]+)+", cells[0]):
            rows[cells[0]] = (cells[1].replace("`", "").split(" ")[0], cells[2])
    return rows


def check_prd(shapes: list[dict]) -> list[str]:
    errs: list[str] = []
    rows = prd_rows()
    by_id = {s["id"]: s for s in shapes}
    for sid in sorted(set(rows) | set(by_id)):
        if sid not in rows:
            errs.append(f"{sid}: in shapes.yml but not in PRD §4 table")
        elif sid not in by_id:
            errs.append(f"{sid}: in PRD §4 table but not in shapes.yml")
        elif rows[sid] != (by_id[sid]["plugin"], by_id[sid]["template"]):
            errs.append(f"{sid}: PRD says {rows[sid]}, shapes.yml says {(by_id[sid]['plugin'], by_id[sid]['template'])}")
    return errs


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, shapes = argv[0], load()
    if cmd == "ids":
        print("\n".join(s["id"] for s in shapes))
        return 0
    if cmd == "get":
        sid, field = argv[1], argv[2]
        s = next((x for x in shapes if x["id"] == sid), None)
        if s is None or field not in s:
            print(f"unknown shape/field: {sid} {field}", file=sys.stderr)
            return 1
        v = s[field]
        print(str(v).lower() if isinstance(v, bool) else v)
        return 0
    errs = validate(shapes)
    if cmd == "check":
        errs += check_files(shapes) + check_contract(shapes) + check_prd(shapes) + check_front_matter() + check_adr_index()
    elif cmd != "validate":
        print(__doc__)
        return 2
    for e in errs:
        print(f"ERROR: {e}", file=sys.stderr)
    if not errs:
        print(f"OK: {len(shapes)} shapes ({cmd})")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
