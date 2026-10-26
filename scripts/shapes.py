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

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
# Must equal scripts/cplat/gates.py CI_EXTRA_STEP (a test asserts it): the decoded last step of every template's `ci` recipe (spec 086).
CI_EXTRA_STEP = "if grep -qs '\"ci-extra\"[[:space:]]*:' devbox.json; then devbox run ci-extra; fi"
REQUIRED = ["id", "plugin", "template", "deployable", "library", "detection", "status"]
STATUSES = {"stable", "planned", "deprecated"}
PRD = ROOT / "docs" / "requirements" / "platform-vision.md"


DECLARED_IN = ".platform-settings.yml"


def load_all() -> list[dict]:
    """Every registry entry in file order, including declared shapes (ADR-056)."""
    return yaml.safe_load((ROOT / "shapes.yml").read_text())["shapes"]


def is_declared(entry: dict) -> bool:
    return (entry.get("detection") or {}).get("declared") is not None


def load() -> list[dict]:
    """The template shapes: what every creating, adopting and rolling-out caller sees."""
    return [e for e in load_all() if not is_declared(e)]


def get(sid: str) -> dict | None:
    return next((e for e in load_all() if e.get("id") == sid), None)


def declared_ids() -> list[str]:
    return [e["id"] for e in load_all() if is_declared(e)]


def _declared_errors(sid: str, s: dict) -> list[str]:
    errs: list[str] = []
    det = s.get("detection") or {}
    if det.get("declared") != DECLARED_IN:
        errs.append(f"{sid}: detection.declared must be {DECLARED_IN} (ADR-056)")
    if "copier_src" in det or "sniff" in det:
        errs.append(f"{sid}: a declared shape has no copier_src or sniff rule (ADR-056)")
    if s.get("template") is not None:
        errs.append(f"{sid}: a declared shape has no template (template: null, ADR-056)")
    if s.get("deployable") or s.get("library"):
        errs.append(f"{sid}: a declared shape is neither deployable nor a library (ADR-056)")
    for k in ("runtime", "smoke_tag", "smoke_globs", "default_stack"):
        if k in s:
            errs.append(f"{sid}: a declared shape has no {k} (ADR-056)")
    return errs


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
        if is_declared(s):
            errs += _declared_errors(sid, s)
            continue
        if s.get("template") is None:
            errs.append(f"{sid}: template missing: only a shape declared in {DECLARED_IN} has none (ADR-056)")
        det = s.get("detection") or {}
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
        tag, sglobs = s.get("smoke_tag"), s.get("smoke_globs")
        if s.get("deployable") and s.get("status") != "planned":
            try:
                if not isinstance(tag, str) or not tag:
                    raise ValueError("missing")
                re.compile(tag)
            except (ValueError, re.error) as e:
                errs.append(f"{sid}: smoke_tag must be a regex that marks smoke tests (spec 091): {e}")
        elif tag is not None or sglobs is not None:
            errs.append(f"{sid}: only deployable shapes have smoke_tag / smoke_globs (spec 091)")
        if sglobs is not None and (not isinstance(sglobs, list) or not sglobs or not all(isinstance(g, str) and g for g in sglobs)):
            errs.append(f"{sid}: smoke_globs must be a non-empty list of globs")
        checks = s.get("ci_checks")
        if s.get("status") != "planned" and (not isinstance(checks, list) or not checks):
            errs.append(f"{sid}: ci_checks must list the CI job names new repos require on main (spec 054)")
        errs += _validation_errors(sid, s)
        if s.get("library") and s.get("deployable"):
            errs.append(f"{sid}: a library cannot be deployable")
    return errs


def _validation_errors(sid: str, s: dict) -> list[str]:
    """Spec 103: `validation.selector` (pytest | vitest | null) and `validation.mandatory` (category -> globs)."""
    v = s.get("validation")
    if v is None:
        return []
    if not isinstance(v, dict):
        return [f"{sid}: validation must be a map with selector and mandatory (spec 103)"]
    errs: list[str] = []
    if v.get("selector") not in ("pytest", "vitest", None):
        errs.append(f"{sid}: validation.selector must be pytest, vitest or null (spec 103)")
    m = v.get("mandatory", {})
    if not isinstance(m, dict) or not all(isinstance(k, str) and k and isinstance(g, list) and g
                                          and all(isinstance(x, str) and x for x in g) for k, g in m.items()):
        errs.append(f"{sid}: validation.mandatory must map a category to a non-empty list of globs (spec 103)")
    return errs


def check_files(shapes: list[dict]) -> list[str]:
    errs: list[str] = []
    for s in shapes:
        pdir = ROOT / "plugins" / s["plugin"]
        if is_declared(s):
            if s["status"] != "planned" and not pdir.is_dir():
                errs.append(f"{s['id']}: plugins/{s['plugin']}/ missing (status {s['status']})")
            continue
        tdir = ROOT / "templates" / s["template"]
        if s["status"] != "planned":
            if not (tdir / "copier.yml").is_file():
                errs.append(f"{s['id']}: templates/{s['template']}/copier.yml missing (status {s['status']})")
            if not pdir.is_dir():
                errs.append(f"{s['id']}: plugins/{s['plugin']}/ missing (status {s['status']})")
    return errs


CORE_RECIPES = ["lint", "lint-fix", "quality", "test", "test-fast", "security", "secrets-baseline", "ci"]   # ci, secrets-baseline: specs 073, 075
DEPLOY_RECIPES = ["image-build", "image-scan", "smoke"]   # smoke: spec 091
DEPS_RECIPES = ["deps-findings", "deps-bump"]   # spec 095: the recipes `cplat deps` calls
CONTRACT_AGENTS = ["coder", "tester"]
DEPLOY_AGENTS = ["deployment", "observability", "release"]


def _template_file(tdir: Path, name: str) -> Path | None:
    for cand in (tdir / name, tdir / f"{name}.jinja"):
        if cand.is_file():
            return cand
    return None


def _check_ci_extra(sid: str, tdir: Path, devbox: Path | None, claude: Path | None) -> list[str]:
    """Spec 086: the template hooks the repo-owned ci-extra recipe and ships the project notes file."""
    errs: list[str] = []
    if devbox is not None:
        text = devbox.read_text()
        if re.search(r'"ci-extra"\s*:', text):
            errs.append(f"{sid}: devbox.json defines ci-extra; it is the repo's own recipe (spec 086)")
        m = re.search(r'^\s*"ci":\s*"(.*)",?$', text, re.M)
        try:
            ci = json.loads(f'"{m.group(1)}"') if m else ""
        except ValueError:
            ci = ""
        if not ci.endswith(" && " + CI_EXTRA_STEP):
            errs.append(f"{sid}: the ci recipe must end with ` && {CI_EXTRA_STEP}` (spec 086)")
    wf = tdir / ".github" / "workflows" / "ci.yml"
    if wf.is_file():
        blocks = re.split(r"^  (?=[\w-]+:\s*$)", wf.read_text().split("\njobs:\n", 1)[-1], flags=re.M)
        ok = any(re.search(r"^    name: ci-extra\s*$", b, re.M) and re.search(r"^\s+(?:- )?run: devbox run ci-extra\s*$", b, re.M)
                 for b in blocks)
        if not ok:
            errs.append(f"{sid}: ci.yml has no ci-extra job running devbox run ci-extra (spec 086)")
    notes = tdir / ".claude" / "project-notes.md"
    if not notes.is_file() or notes.stat().st_size != 0:
        errs.append(f"{sid}: template has no .claude/project-notes.md, or it is not empty (spec 086)")
    skip = (yaml.safe_load((tdir / "copier.yml").read_text()) or {}).get("_skip_if_exists") or []
    if ".claude/project-notes.md" not in skip:
        errs.append(f"{sid}: copier.yml must list .claude/project-notes.md in _skip_if_exists (spec 086)")
    if claude is not None:
        ct = claude.read_text()
        if "## Where your additions go" not in ct or not re.search(r"^@\.claude/project-notes\.md$", ct, re.M):
            errs.append(f"{sid}: CLAUDE.md must import @.claude/project-notes.md and have a '## Where your additions go' section (spec 086)")
    return errs


def check_contract(shapes: list[dict]) -> list[str]:
    """PRD §4.1 contract: every non-planned shape ships the template, plugin and detection artifacts."""
    errs: list[str] = []
    detect = (ROOT / "scripts" / "detect-shape.sh").read_text()
    fixtures = (ROOT / "scripts" / "test-detect-shape.sh").read_text()
    for s in shapes:
        if s["status"] == "planned" or is_declared(s):
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
            # spec 095: every dependency-owning shape bumps through the platform recipes; gitops-app never does
            for r in DEPS_RECIPES:
                if sid == "gitops-app":
                    if f'"{r}"' in text:
                        errs.append(f"{sid}: devbox.json must not define '{r}': gitops-app repos never bump dependencies (spec 095)")
                elif f'"{r}"' not in text:
                    errs.append(f"{sid}: devbox.json missing deps recipe '{r}' (spec 095)")
            if sid != "gitops-app" and not (tdir / "scripts" / "deps.sh").is_file():
                errs.append(f"{sid}: template has no scripts/deps.sh (spec 095)")
            if s["deployable"] and sid != "gitops-app" and not (tdir / "scripts" / "smoke.sh").is_file():
                errs.append(f"{sid}: template has no scripts/smoke.sh (spec 091)")
        claude = _template_file(tdir, "CLAUDE.md")
        if claude is None:
            errs.append(f"{sid}: template has no CLAUDE.md")
        elif "### Spec first" not in claude.read_text():
            errs.append(f"{sid}: CLAUDE.md has no '### Spec first' section (ADR-024)")
        elif ("/system:spec" if sid == "gitops-app" else "/component:spec") not in claude.read_text():
            errs.append(f"{sid}: CLAUDE.md 'Spec first' does not name {'/system:spec' if sid == 'gitops-app' else '/component:spec'} (ADR-026)")
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
        errs += _check_ci_extra(sid, tdir, devbox, claude)
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
        if s["plugin"] != "system":
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
    by_id = {s["id"]: s for s in shapes if not is_declared(s)}
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
    cmd, shapes = argv[0], load_all()
    if cmd == "ids":
        print("\n".join(s["id"] for s in load()))
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
