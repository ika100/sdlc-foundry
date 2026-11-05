"""`cplat system ship` rendering (spec 097): the repo state table and the final report. Pure functions of the state."""
from __future__ import annotations

PASSED = ("passed", "pinned", "done-before")


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


def decision_count(st: dict) -> int:
    """How many answers the run took for the user across its repo specs (spec 141, for the run record)."""
    return sum(len(r.get("decisions") or []) for r in (st.get("repos") or {}).values())


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
        if repo.get("gate") in ("exposed", "internal") and not str(repo.get("staging_row") or "").startswith("sha-"):
            promote.append(f"/instance:promote {rid} --to staging")
    staged = [(rid, repo) for rid, repo in ordered(st) if repo.get("staging_row")]
    if st.get("joint") and staged:             # spec 144 (AC-144.7): staging in one PR for the spec
        out += ["", "| Repo | Promotion (staging) | Smoke (staging) |", "|---|---|---|"]
        out += [f"| {rid} | {repo['staging_row']} | {(repo.get('staging_smoke') or {}).get('row') or '-'} |" for rid, repo in staged]
    steps += [s for s in product_steps or [] if s not in steps]
    taken = [(rid, repo.get("spec"), d) for rid, repo in ordered(st) for d in repo.get("decisions") or []]
    if taken:                                  # spec 141 (AC-141.3): what the run decided for the user, to correct later
        out += ["", "Decisions taken for you (suggested answers of the repo specs; change one with `/component:spec --amend`):",
                *(f"- {rid} ({sid}): {d}" for rid, sid, d in taken)]
    if steps:
        out += ["", "Human steps (the run cannot do these):", *(f"- [ ] {s}" for s in steps)]
    if st.get("staging_pr"):
        out += ["", "Next (staging promoted in " + st["staging_pr"] + "; the rest by hand):", *(promote or ["(nothing left)"]),
                "", "This run promotes nothing beyond staging."]
    else:
        out += ["", "Next (staging is not promoted by this run):", *(promote or ["(no deployable service)"]),
                "", "This run promotes nothing beyond dev."]
    return out
