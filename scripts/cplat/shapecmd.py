"""`shape`: detect the repo's shape and print the agent routing the /component:* orchestrators use (agent routing)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import core
import settings
from core import PLATFORM_ROOT, PlatformError, run

ROLES_BY_SHAPE_PLUGIN = ("coder", "tester", "deployment", "observability", "release")


def resolve(repo: Path) -> str | None:
    """The repo's shape: a committed declaration (spec 123), else detect-shape.sh; None when neither resolves."""
    declared = settings.declared_shape(repo)
    if declared:
        answers = repo / ".copier-answers.yml"
        if answers.is_file():
            m = re.search(r"^_src_path:[ \t]*(.*)$", answers.read_text(), re.M)
            src = re.sub(r"/*$", "", m.group(1).replace('"', "").replace("'", "")) if m else ""
            for t in core.registry.load():
                if src == f"templates/{t['id']}" or src.endswith(f"/templates/{t['id']}"):
                    raise settings.ShapeDeclarationError(
                        f"conflicting shape sources: .platform-settings.yml declares '{declared}' and .copier-answers.yml "
                        f"names templates/{t['id']}; remove one of them",
                        hint="a component repo keeps .copier-answers.yml and drops `shape:`; the platform repo has no .copier-answers.yml")
        return declared
    det = run(["bash", str(PLATFORM_ROOT / "scripts" / "detect-shape.sh"), str(repo)], check=False)
    return det.stdout.strip() or None


def route(repo: Path) -> dict:
    shape = resolve(repo)
    if not shape:
        raise PlatformError("cannot determine the repo's shape", hint="ask the user which shape this is, or add a .copier-answers.yml (docs/ADOPTING.md)")
    entry = core.registry.get(shape)
    plugin = entry["plugin"]
    declared = core.registry.is_declared(entry)
    agents = {role: f"{plugin}:{role}" for role in ROLES_BY_SHAPE_PLUGIN}
    if declared:
        agents.pop("release")  # released through its own procedure (ADR-056)
    if not entry["deployable"]:
        agents.pop("deployment"), agents.pop("observability")  # nothing to deploy
    agents.update({"product-manager": "svc:product-manager", "architect": "svc:architect", "reviewer": "svc:reviewer",
                   "quality": "shared:quality", "security": "shared:security"})
    if shape == "service-python":
        agents["migrations"] = "svc:migrations"
    out = {"shape": shape, "plugin": plugin, "deployable": entry["deployable"], "library": entry["library"], "agents": agents}
    if shape == "gitops-app":
        out["unsupported"] = "/component:* commands do not apply to a gitops-app repo; use /system:spec, /component:add or /instance:promote"
    if shape == "cluster-gitops":
        out["unsupported"] = ("/component:* commands do not apply to a cluster repo; use /cluster:add, /cluster:remove, "
                              "/platform:update or /platform:doctor")
    return out


def main(argv: list[str]) -> int:
    if argv[:1] == ["check"]:  # the platform's shape contract (spec 086)
        scripts = str(PLATFORM_ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import shapes
        return shapes.main(["check"])
    ap = argparse.ArgumentParser(prog="cplat shape", description=__doc__)
    ap.add_argument("--repo", default=".")
    ns = ap.parse_args(argv)
    print(json.dumps(route(Path(ns.repo).resolve()), indent=2))
    return 0
