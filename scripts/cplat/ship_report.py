"""Spec 200: the report of a finished ship run, built from the ship state, the spec and the deps state.

Both paths (the in-session ship and the hand-off) read the same files, so `data` gives the same answer for both.
`ship status` prints `lines(data)` and `--json` carries `data` as `report`.
"""
from __future__ import annotations

from pathlib import Path

import ship
import spec as specmod
from core import PlatformError

PROMOTION_PREFIX = "Promotion (staging): "


def _patches(repo: Path) -> list[dict]:
    try:
        import deps
        bumps = deps._load_state(repo).get("bumps") or []
    except Exception:  # noqa: BLE001  (a report never fails on the deps state)
        return []
    return [{"package": b.get("package"), "from": b.get("from"), "to": b.get("to"),
             "advisories": list(b.get("advisories") or []), "major": bool(b.get("major"))}
            for b in bumps if isinstance(b, dict) and b.get("outcome") == "patched"]


def data(repo: Path, st: dict) -> dict:
    try:
        sp = specmod.find(repo, st["spec"])
        criteria, verification = len(sp.active_acs()), specmod.verification_result(sp)
    except PlatformError:
        criteria, verification = 0, None
    staging = st.get("staging") or {}
    promotion = staging.get("row")
    if isinstance(promotion, str):
        promotion = promotion.removeprefix(PROMOTION_PREFIX)
    return {
        "plan_tasks": len(ship.plan_meta(repo, st).get("tasks") or []),
        "criteria_total": criteria,
        "verification": verification,
        "pr": st.get("pr"),
        "merged": bool(st.get("merge", True)),
        "ci_rounds": int(st.get("fix_rounds") or 0) + 1,
        "merge_sha": st.get("merge_sha"),
        "deployed": st.get("deployed"),
        "deploy_lines": list(st.get("deploy_lines") or []),
        "smoke_dev": (st.get("smoke") or {}).get("row"),
        "promotion_staging": promotion,
        "smoke_staging": (staging.get("smoke") or {}).get("row"),
        "dependency_patches": _patches(repo),
        "human_steps": [str(s) for s in ship.plan_meta(repo, st).get("human_steps") or []],
    }


def lines(d: dict) -> list[str]:
    total = d["criteria_total"]
    build = (f"{total}/{total} criteria met (verification.md: pass)" if d["verification"] == "pass"
             else f"verification.md: {d['verification'] or 'missing'}")
    if d["merged"]:
        pr = f"{d['pr']}, merged after {d['ci_rounds']} CI round(s)"
    else:
        pr = f"{d['pr']}, green, not merged (--no-merge)"
    out = ["report:", f"  plan: {d['plan_tasks']} tasks", f"  build: {build}", f"  pr: {pr}",
           f"  merge: {d['merge_sha'] or '-'}"]
    out += [f"  deploy: {ln}" for ln in d["deploy_lines"]] or ["  deploy: -"]
    out += [f"  smoke (dev): {d['smoke_dev'] or '-'}",
            f"  promotion (staging): {d['promotion_staging'] or '-'}",
            f"  smoke (staging): {d['smoke_staging'] or '-'}"]
    patches = [f"{p['package']} {p['from']} → {p['to']} ({', '.join(p['advisories'])})"
               + (", major bump" if p["major"] else "") for p in d["dependency_patches"]]
    out += [f"  dependency patches: {p}" for p in patches] or ["  dependency patches: none"]
    out += [f"  human steps: - [ ] {s}" for s in d["human_steps"]] or ["  human steps: none"]
    return out
