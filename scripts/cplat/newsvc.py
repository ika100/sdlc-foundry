"""`new-service`: create a repo of any registered shape from its Copier template (and, optionally, on GitHub)."""
from __future__ import annotations

import argparse
import re
import shlex
from pathlib import Path

import yaml

import core
import model
from core import PLATFORM_ROOT, PlatformError, Report, run

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
PYTHON_SHAPES = {"service-python", "library-python"}
# 4.x flags that 5.0 replaced: flag -> what to use now
REPLACED = {
    "web": "`--type website --lang typescript`",
    "library": "`--type library --lang python`",
    "gitops": "`cplat system new <manifest>` (/system:new)",
}
# the pair a lone --type or --lang completes to
TYPE_DEFAULT_LANG = {"service": "python", "website": "typescript", "library": "python"}
LANG_DEFAULT_TYPE = {"python": "service", "java": "service", "go": "service", "typescript": "website"}


def valid_pairs() -> list[tuple[str, str]]:
    """The (type, lang) pairs `component new` accepts: the registry's, never service/unknown."""
    order = [("service", "python"), ("service", "java"), ("service", "go"), ("website", "typescript"), ("library", "python")]
    pairs = [p for p in model.TYPE_LANGS if p != ("service", "unknown")]
    return sorted(pairs, key=lambda p: order.index(p) if p in order else len(order))


def pairs_text() -> str:
    return ", ".join(f"{t}/{lang}" for t, lang in valid_pairs())


def shape_of_pair(type_: str | None, lang: str | None) -> str:
    """The shape id of a type/lang pair (a missing half is completed); PlatformError listing the valid pairs otherwise."""
    if not type_ and not lang:
        type_, lang = "service", "python"
    elif not lang:
        lang = TYPE_DEFAULT_LANG.get(type_ or "", "python")
    elif not type_:
        type_ = LANG_DEFAULT_TYPE.get(lang, "service")
    shape = model.shape_for(type_, lang) if (type_, lang) in valid_pairs() else None
    if shape is None:
        raise PlatformError(f"{type_}/{lang} is not a valid component type (valid: {pairs_text()})")
    return shape


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat new-service", description=__doc__)
    p.add_argument("words", nargs="*", help="<name> [description words...]")
    p.add_argument("--type", dest="type_", help="service, website or library (default service)")
    p.add_argument("--lang", help="python, java, go or typescript (default python)")
    p.add_argument("--shape", help=argparse.SUPPRESS)  # internal: a shape id (system new, tests)
    for flag in REPLACED:
        p.add_argument(f"--{flag}", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--python", help="Python version (Python shapes only)")
    p.add_argument("--org", help="GitHub org/user (default: your gh login)")
    p.add_argument("--ref", default="main", help="platform git ref recorded for the plugin marketplace (default main)")
    p.add_argument("--system", dest="app", metavar="OWNER/REPO", help="the system's gitops repo: write .platform-app.yml (deployable types)")
    p.add_argument("--app", dest="old_app", help=argparse.SUPPRESS)
    p.add_argument("--description", help="legacy alias; appended to the description words")
    p.add_argument("--dir", default=".", help="parent directory for the new repo (default: current directory)")
    p.add_argument("--no-github", action="store_true", help="local repo only; do not create a GitHub repo")
    p.add_argument("--public", action="store_true", help="create the GitHub repo as public (default: private); same as --visibility public")
    p.add_argument("--visibility", choices=["private", "public"], help="visibility of the GitHub repo (default: private)")
    p.add_argument("--data", action="append", default=[], metavar="KEY=VALUE", help="template option, e.g. needs_database=true (repeatable; see the template's copier.yml)")
    p.add_argument("--skip-tasks", action="store_true", help="skip the template's bootstrap tasks (tests/CI)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def template_options(template_dir: Path) -> list[str]:
    """Names of the template's questions (keys of copier.yml that are not `_settings`)."""
    try:
        cfg = yaml.safe_load((template_dir / "copier.yml").read_text()) or {}
    except (OSError, yaml.YAMLError):
        return []
    return sorted(k for k in cfg if not str(k).startswith("_"))


def resolve(argv: list[str]) -> dict:
    """Parse and validate the request; no side effects. Raises PlatformError with a hint on bad input."""
    ns = build_parser().parse_intermixed_args(argv)
    for flag, use in REPLACED.items():
        if getattr(ns, flag):
            raise PlatformError(f"`--{flag}` is {use} in 5.0")
    if ns.old_app:
        raise PlatformError("`--app` is `--system` in 5.0")
    shapes = {s["id"]: s for s in core.registry.load()}
    if ns.type_ in shapes:
        t, lang = model.type_lang(ns.type_)
        raise PlatformError(f"`--type {ns.type_}` is `--type {t} --lang {lang}` in 5.0")
    shape = ns.shape or shape_of_pair(ns.type_, ns.lang)
    if shape not in shapes:
        raise PlatformError(f"unknown shape '{shape}'", hint="valid shapes: " + ", ".join(sorted(shapes)))
    entry = shapes[shape]
    if entry["status"] == "planned":
        raise PlatformError(f"shape '{shape}' is registered but not available yet (status: planned)")
    template_dir = PLATFORM_ROOT / "templates" / entry["template"]
    if not template_dir.is_dir():
        raise PlatformError(f"templates/{entry['template']} does not exist in this platform checkout")

    if not ns.words:
        raise PlatformError("a project name is required", hint="usage: component new <name> <one-line description> [--type <type>] [--lang <lang>]")
    name, desc_words = ns.words[0], ns.words[1:]
    if ns.description:
        desc_words.append(ns.description)
    if not NAME_RE.match(name):
        raise PlatformError(f"invalid project name '{name}'", hint="kebab-case, 2-40 chars, must start with a letter: ^[a-z][a-z0-9-]{1,39}$")
    description = " ".join(desc_words).strip()
    if not description:
        raise PlatformError("a one-line description is required", hint="usage: component new <name> <one-line description> ...")

    python = entry["default_stack"].get("language") == "python" or shape in PYTHON_SHAPES
    org = ns.org
    if not org and not ns.no_github:
        org = core.gh_login()
    org = org or "ika100"

    target = Path(ns.dir).resolve() / name
    if target.exists() and any(p.name != ".claude" for p in target.iterdir()):
        raise PlatformError(f"{target} already exists and is not empty", hint="choose another name or remove the directory")

    visibility = "public" if ns.public else (ns.visibility or "private")
    if ns.public and ns.visibility == "private":
        raise PlatformError("--public conflicts with --visibility private")
    if visibility == "public" and ns.no_github:
        raise PlatformError("--public needs a GitHub repository", hint="drop --no-github")

    data = {"project_name": name, "description": description, "github_org": org, "platform_marketplace_ref": ns.ref}
    options = template_options(template_dir)
    for kv in ns.data:
        key, sep, value = kv.partition("=")
        if not key or not sep:
            raise PlatformError(f"--data expects KEY=VALUE, got '{kv}'")
        if options and key not in options:
            raise PlatformError(f"template {entry['template']} has no option '{key}'", hint="options: " + ", ".join(options))
        data[key] = value
    if python:
        data["module_name"] = name.replace("-", "_")
        data["python_version"] = ns.python or "3.12"
    return {
        "shape": shape, "entry": entry, "template": entry["template"], "name": name, "description": description,
        "org": org, "target": target, "data": data, "app": ns.app if entry["deployable"] else None,
        "ignored_app": bool(ns.app and not entry["deployable"]), "github": not ns.no_github and core.has_gh(),
        "want_github": not ns.no_github, "visibility": visibility, "set_keys": [kv.partition("=")[0] for kv in ns.data], "skip_tasks": ns.skip_tasks, "dry_run": ns.dry_run, "json": ns.json, "ref": ns.ref,
    }


def plan(req: dict) -> Report:
    r = Report(title=f"New {req['shape']} repo: {req['name']}")
    r.will_do.append(f"render templates/{req['template']} into {req['target']} (answers: " +
                     ", ".join(f"{k}={v}" for k, v in req["data"].items() if k in ("github_org", "module_name", "python_version", *req["set_keys"])) + ")")
    r.will_do.append("run the template's bootstrap tasks (git init, devbox install, lockfiles) and create the first commit")
    if req["app"]:
        r.will_do.append(f"write .platform-app.yml linking the repo to {req['app']}")
    r.will_do.append("stamp .platform-version and record the stable template source in .copier-answers.yml")
    if req["want_github"]:
        if req["github"]:
            r.will_do.append(f"[outward] create {req['visibility'].upper()} GitHub repo {req['org']}/{req['name']} and push")
            if req["entry"]["deployable"]:
                r.will_do.append("[outward] add topic deployable-service (so it can be added to a system)")
            if req["shape"] == "gitops-app":
                r.will_do.append("[outward] let pin PRs merge themselves: auto-merge on, Actions may open PRs (spec 062)")
            r.will_do.append("[outward] protect main: require the CI checks " + ", ".join(req["entry"].get("ci_checks") or []) + " (no review requirement)")
        else:
            r.will_do.append("gh is not available: skip GitHub steps and print the commands instead")
    if req["ignored_app"]:
        r.will_do.append(f"note: --system ignored, shape {req['shape']} is not deployable")
    return r


def _next_steps(req: dict) -> list[str]:
    n, shape = req["name"], req["shape"]
    desc = (req.get("description") or "<your first feature>").replace('"', "'")
    if shape == "gitops-app":
        return [f"cd {n} && devbox shell", "devbox run quality", "/component:add <component>  (after the components exist)",
                '/system:spec "<first feature of the system>"   # spec first: the system spec (answer, approve), then /system:plan <NNN> and /system:ship <NNN>',
                "devbox run cluster-up   # local k3d + ArgoCD (needs Docker)"]
    return [f"cd {n} && devbox shell", "devbox run quality && devbox run test",
            f'/component:spec "{desc}"   # spec first: docs/specs/<NNN>-<slug>/spec.md, it asks you its open questions; approve it',
            "/component:plan <NNN>   # the architect plans the approved spec (design.md, plan.md); review it",
            "/component:build <NNN> # failing acceptance tests first, then the code, verified against the spec; the bootstrap CI runs in parallel, do not wait for it"]


def protection_cmd(slug: str, checks: list[str]) -> list[str]:
    """Spec 054: main requires the shape's CI checks; no review requirement (solo founders cannot approve their own PRs)."""
    cmd = ["gh", "api", "-X", "PUT", f"repos/{slug}/branches/main/protection", "-F", "required_status_checks[strict]=false"]
    cmd += [f for c in checks for f in ("-f", f"required_status_checks[contexts][]={c}")]
    return cmd + ["-F", "enforce_admins=false", "-F", "required_pull_request_reviews=null", "-F", "restrictions=null"]


def pin_settings_cmds(slug: str) -> list[list[str]]:
    """Spec 062: the gitops-app's pin-dev workflow opens PRs with GITHUB_TOKEN and lets them merge themselves."""
    return [["gh", "api", "-X", "PATCH", f"repos/{slug}", "-F", "allow_auto_merge=true"],
            ["gh", "api", "-X", "PUT", f"repos/{slug}/actions/permissions/workflow",
             "-f", "default_workflow_permissions=read", "-F", "can_approve_pull_request_reviews=true"]]


def token_step(app: str, services: list[str]) -> str:
    """Spec 062: the one manual step — a token the services' CI uses to ask the gitops-app to pin dev."""
    sets = (f"gh secret set GITOPS_TOKEN -R {services[0]}" if len(services) == 1 else
            f"for r in {' '.join(s.split('/')[-1] for s in services)}; do gh secret set GITOPS_TOKEN -R {services[0].split('/')[0]}/$r; done")
    return (f"let dev follow main (spec 062): create a fine-grained token at https://github.com/settings/personal-access-tokens/new "
            f"with repository access {app} only and Contents: Read and write, then paste it into: {sets}")


def execute(req: dict) -> Report:
    r = plan(req)
    target: Path = req["target"]
    if target.exists():  # empty or .claude-only stub (checked in resolve)
        import shutil
        shutil.rmtree(target)

    cmd = [*core.find_copier(), "copy", str(PLATFORM_ROOT / "templates" / req["template"]), str(target), "--defaults", "--trust"]
    if req["skip_tasks"]:
        cmd.append("--skip-tasks")
    for k, v in req["data"].items():
        cmd += ["--data", f"{k}={v}"]
    run(cmd)
    r.did.append(f"rendered templates/{req['template']} → {target}")

    # copier records the (temporary) template path; point it at the stable source so shape detection and docs make sense
    answers = target / ".copier-answers.yml"
    text = answers.read_text()
    answers.write_text(re.sub(r"^_src_path:.*$", f"_src_path: gh:ika100/sdlc-foundry/templates/{req['template']}", text, flags=re.M))
    core.write_stamp(target, req["shape"], req["ref"])
    if req["app"]:
        (target / ".platform-app.yml").write_text(
            "# Application repos this service belongs to (read by /instance:promote)\n"
            f"gitops_apps:\n  - {req['app']}\n")
        r.did.append(f".platform-app.yml → {req['app']}")

    # one commit owned by the user (copier's task commit uses a generic identity)
    if not (target / ".git").exists():
        run(["git", "init", "-q"], cwd=target)
    run(["git", "add", "-A"], cwd=target)
    ident = core.git_identity(target)
    msg = (f"chore: bootstrap from {req['template']} template\n\nGenerated by /component:new.\n"
           f"Template: ika100/sdlc-foundry/templates/{req['template']} (platform {core.platform_version()})\nDescription: {req['description']}")
    has_head = run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=target, check=False).returncode == 0
    run(["git", *ident, "commit", "-q", *(["--amend", "--reset-author"] if has_head else []), "-m", msg], cwd=target)
    run(["git", "branch", "-M", "main"], cwd=target, check=False)
    r.did.append("created the bootstrap commit on branch main")

    cmds_if_manual = []
    slug = f"{req['org']}/{req['name']}"
    if req["want_github"] and req["github"]:
        run(["gh", "repo", "create", slug, f"--{req['visibility']}", "--description", req["description"], "--source=.", "--remote=origin", "--push"], cwd=target)
        r.did.append(f"created {req['visibility']} GitHub repo https://github.com/{slug} and pushed")
        if req["entry"]["deployable"]:
            run(["gh", "repo", "edit", slug, "--add-topic", "deployable-service"])
            r.did.append("added topic deployable-service")
        protect = protection_cmd(slug, req["entry"].get("ci_checks") or [])
        res = run(protect, check=False)
        if res.returncode == 0:
            r.did.append("protected main: " + ", ".join(req["entry"].get("ci_checks") or []) + " must pass before merging")
        else:
            reason = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
            r.did.append(f"WARNING: could not protect main ({reason[0]}); private repos on free plans cannot use branch protection. "
                         "Merges still wait for green CI: pin-dev and /component:ship merge only after every check passed (spec 065, ADR-028)")
            r.next_steps.append("protect main by hand when your plan allows it: " + " ".join(shlex.quote(c) for c in protect))
        if req["shape"] == "gitops-app":
            auto, actions = pin_settings_cmds(slug)
            if run(actions, check=False).returncode != 0:
                r.did.append("WARNING: could not let Actions open pull requests (needs admin rights on the repo); pin-dev cannot open pin PRs")
                r.next_steps.append("let pin-dev open PRs (spec 062): " + " ".join(shlex.quote(x) for x in actions))
            elif run(auto, check=False).returncode != 0:
                r.did.append("pin PRs merge after green CI; auto-merge is not available on this plan, pin-dev merges itself (spec 065)")
            else:
                r.did.append("allows pin PRs to merge themselves after CI (auto-merge on, Actions may open PRs)")
        r.undo.append(f"gh repo delete {slug} --yes   (needs the delete_repo scope: gh auth refresh -s delete_repo)")
    elif req["want_github"]:
        cmds_if_manual = [f"gh repo create {slug} --{req['visibility']} --source=. --remote=origin --push"]
        if req["entry"]["deployable"]:
            cmds_if_manual.append(f"gh repo edit {slug} --add-topic deployable-service")
        r.did.append("skipped GitHub (gh missing)")
        r.next_steps.append("install and log in to gh, then run: " + " && ".join(cmds_if_manual))
    r.undo.append(f"rm -rf {target}")
    if req["app"] and req["entry"]["deployable"] and req["shape"] != "gitops-app":
        r.next_steps.append(token_step(req["app"], [slug]))
    r.next_steps = _next_steps(req) + r.next_steps
    r.data = {"path": str(target), "shape": req["shape"], "repo": slug if req["github"] else None}
    return r


def main(argv: list[str]) -> int:
    req = resolve(argv)
    if req["dry_run"]:
        plan(req).emit(True, req["json"])
        return 0
    execute(req).emit(False, req["json"])
    return 0
