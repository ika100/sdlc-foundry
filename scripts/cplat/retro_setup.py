"""The weekly retro schedule (spec 090, ADR-039): the workflow asset in the run store repo and what doctor checks."""
from __future__ import annotations

import json
from pathlib import Path

import autoissue
import runs_store

WORKFLOW_PATH = ".github/workflows/cplat-retro.yml"
ASSET = Path(__file__).parent / "assets" / "workflows" / "cplat-retro.yml"
CLAUDE_SECRETS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
GH_SECRET = "RETRO_GH_TOKEN"


def workflow_text(platform_repo: str) -> str:
    return ASSET.read_text(encoding="utf-8").replace("__PLATFORM_REPO__", platform_repo)


def install_schedule(store, slug: str) -> list[str]:
    """Add the workflow when it is missing and leave an existing one alone. Never raises."""
    lines: list[str] = []
    try:
        if store.read_file(WORKFLOW_PATH) is not None:
            lines.append(f"retro schedule: present ({WORKFLOW_PATH})")
        else:
            store.put({WORKFLOW_PATH: workflow_text(autoissue.default_repo())}, "retro: weekly schedule (spec 090)")
            lines.append(f"retro schedule: added {WORKFLOW_PATH} (Mondays 06:00 UTC)")
    except Exception as e:  # noqa: BLE001  (init must succeed without the workflow scope)
        lines.append(f"WARNING: retro schedule not added: {e or type(e).__name__}")
        lines.append(f"  fix: gh auth refresh -h github.com -s workflow, then cplat runs init {slug}")
    lines.append(f"retro: set the secrets CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) and {GH_SECRET} in {slug}, and a "
                 "self-hosted runner (repo variable CI_RUNNER); cplat doctor checks them")
    return lines


def secret_names(slug: str) -> set[str] | None:
    code, out, _ = runs_store.gh(["secret", "list", "-R", slug, "--json", "name"])
    if code != 0:
        return None
    try:
        return {str(x["name"]) for x in json.loads(out)}
    except (ValueError, KeyError, TypeError):
        return None


def missing(store, slug: str) -> list[str] | None:
    names = secret_names(slug)
    if names is None:
        return None
    out = []
    if store.read_file(WORKFLOW_PATH) is None:
        out.append(f"no retro schedule ({WORKFLOW_PATH})")
    if not names & set(CLAUDE_SECRETS):
        out.append("no Claude credential secret (CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY)")
    if GH_SECRET not in names:
        out.append(f"no {GH_SECRET} secret")
    return out
