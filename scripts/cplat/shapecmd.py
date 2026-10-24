"""`shape`: detect the repo's shape and print the agent routing the /svc:* orchestrators use (agent routing)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import core
from core import PLATFORM_ROOT, PlatformError, run

ROLES_BY_SHAPE_PLUGIN = ("coder", "tester", "deployment", "observability", "release")


def route(repo: Path) -> dict:
    det = run(["bash", str(PLATFORM_ROOT / "scripts" / "detect-shape.sh"), str(repo)], check=False)
    shape = det.stdout.strip()
    if not shape:
        raise PlatformError("cannot determine the repo's shape", hint="ask the user which shape this is, or add a .copier-answers.yml (docs/ADOPTING.md)")
    entry = next(s for s in core.registry.load() if s["id"] == shape)
    plugin = entry["plugin"]
    agents = {role: f"{plugin}:{role}" for role in ROLES_BY_SHAPE_PLUGIN}
    if not entry["deployable"]:
        agents.pop("deployment"), agents.pop("observability")  # nothing to deploy
    agents.update({"product-manager": "svc:product-manager", "architect": "svc:architect", "reviewer": "svc:reviewer",
                   "quality": "shared:quality", "security": "shared:security"})
    if shape == "service-python":
        agents["migrations"] = "svc:migrations"
    out = {"shape": shape, "plugin": plugin, "deployable": entry["deployable"], "library": entry["library"], "agents": agents}
    if shape == "gitops-app":
        out["unsupported"] = "/svc:* commands do not apply to a gitops-app repo; use /gitops:compose, /gitops:promote or /app:spec"
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
