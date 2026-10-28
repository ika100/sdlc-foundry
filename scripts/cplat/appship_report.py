"""`cplat system ship` rendering (spec 097): the repo state table and the final report. Pure functions of the state."""
from __future__ import annotations

PASSED = ("passed", "done-before")


def is_entry(repo: dict) -> bool:
    return repo.get("shape") == "gitops-app" or repo.get("gate") == "entry"


def ordered(st: dict) -> list[tuple[str, dict]]:
    """The entry first, then the plan order (the order of `repos`)."""
    items = list((st.get("repos") or {}).items())
    return [i for i in items if is_entry(i[1])] + [i for i in items if not is_entry(i[1])]


def shown_state(st: dict, repo: dict) -> str:
    state = repo.get("state", "ready")
    if state == "escalated":
        return f"escalated: {repo.get('reason') or 'unknown'}"
    if state == "ready":
        repos = st.get("repos") or {}
        if any((repos.get(d) or {}).get("state") not in PASSED for d in repo.get("depends_on") or []):
            return "blocked"
    return state


def state_table(st: dict) -> list[str]:
    rows = ["| Repo | State |", "|---|---|"]
    for rid, repo in ordered(st):
        rows.append(f"| {rid}{' (entry)' if is_entry(repo) else ''} | {shown_state(st, repo)} |")
    return rows


def _smoke(rid: str, repo: dict) -> str:
    if repo.get("smoke_row"):
        return repo["smoke_row"]
    if repo.get("gate") == "library":
        return "not run: not deployable (library)"
    if repo.get("gate") == "internal":
        return f"not run: {rid} has no dev URL (not exposed in dev)"
    return "not run: no smoke result recorded"


def final_report(st: dict, title: str, product_steps: list[str] | None = None) -> list[str]:
    out = [f"## Shipped: {st['spec']} — {title}", "",
           "| Repo | Repo spec | PR | CI rounds | dev | Argo | Smoke (dev) |", "|---|---|---|---|---|---|---|"]
    steps: list[str] = []
    promote: list[str] = []
    for rid, repo in ordered(st):
        if repo.get("state") == "done-before":
            out.append(f"| {rid} | - | - | - | - | - | done before this run |")
            continue
        rounds = int(repo.get("fix_rounds") or 0) + 1
        steps += [s for s in repo.get("human_steps") or [] if s not in steps]
        if is_entry(repo):
            out.append(f"| {rid} (entry) | - | {repo.get('pr') or '-'} | {rounds} | - | - | - |")
            continue
        dev = f"{rid}:{repo['deployed']}" if repo.get("deployed") else "-"
        out.append(f"| {rid} | {repo.get('spec') or '-'} | {repo.get('pr') or '-'} | {rounds} | {dev} | "
                   f"{repo.get('argo') or '-'} | {_smoke(rid, repo)} |")
        if repo.get("gate") in ("exposed", "internal"):
            promote.append(f"/instance:promote {rid} --to staging")
    steps += [s for s in product_steps or [] if s not in steps]
    if steps:
        out += ["", "Human steps (the run cannot do these):", *(f"- [ ] {s}" for s in steps)]
    out += ["", "Next (staging is not promoted by this run):", *(promote or ["(no deployable service)"]),
            "", "This run promotes nothing beyond dev."]
    return out
