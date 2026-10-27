"""Stage vocabulary of the console (spec 122, AC-122.32, AC-122.10, AC-122.12).

One pure module names every item's stage and explains each stage, so no other module maps a status or a phase.
Standard library only, no I/O.
"""
from __future__ import annotations

STAGES = ("Issue", "Spec", "Plan", "Build", "Land", "Dev", "Staging", "Prod")
DECISION = frozenset({"Spec", "Build", "Prod"})

_PHASE_STAGE = {
    "plan": "Plan",
    "build": "Build",
    "pr": "Land",
    "land": "Land",
    "deploy": "Dev",
    "staging": "Staging",
}

_SPEC_STAGE = {"draft": "Spec", "approved": "Plan", "building": "Build"}

_EXPLAIN: dict[str, dict] = {
    "Issue": {
        "what": "An open issue that no spec tracks yet. Triage routes it to a fix, a spec or a reply.",
        "agents": ["svc:product-manager"],
        "commands": ["/issue:triage", "/component:fix", "/component:spec"],
        "decision": None,
    },
    "Spec": {
        "what": "The spec is a draft in a pull request: the problem, the acceptance criteria and the non-goals wait for your approval.",
        "agents": ["svc:product-manager"],
        "commands": ["/component:spec", "/system:spec", "/component:spec approve <NNN>"],
        "decision": "Answer the open questions, then approve the spec or ask for changes. Nothing is planned or built before you approve.",
    },
    "Plan": {
        "what": "The architect splits the approved spec into tasks (and repo slices for a system spec), with the files and order of each.",
        "agents": ["svc:architect"],
        "commands": ["/component:plan", "/system:plan"],
        "decision": None,
    },
    "Build": {
        "what": "Acceptance tests are written first and fail, coders make them pass, then the quality, security and review gates run against the spec.",
        "agents": ["svc:tester", "coder (svc, web, svc-java or svc-go, by shape)", "shared:quality", "shared:security", "svc:reviewer"],
        "commands": ["/component:build", "/component:ship"],
        "decision": "Answer an escalation when the run stops, for example a gate that stays red or an exhausted budget.",
    },
    "Land": {
        "what": "The pull request runs CI; it is merged only when every check is green, and red checks get up to three fix rounds.",
        "agents": ["coder (CI fix rounds)"],
        "commands": ["/component:ship"],
        "decision": None,
    },
    "Dev": {
        "what": "The merged build is pinned in the gitops repo, Argo CD rolls it out to dev and the smoke checks run.",
        "agents": [],
        "commands": ["/component:ship", "/instance:promote"],
        "decision": None,
    },
    "Staging": {
        "what": "The build runs in staging; the smoke checks verify it there, and the verified digest becomes a release candidate.",
        "agents": [],
        "commands": ["/instance:promote", "/component:release"],
        "decision": None,
    },
    "Prod": {
        "what": "A release verified in staging waits for you to promote it to production.",
        "agents": [],
        "commands": ["/instance:promote <component> --to prod"],
        "decision": "Promote the release to prod, or hold it back.",
    },
}


def earliest(stages) -> str | None:
    """Return the earliest of the given stage names in `STAGES` order, or None for none."""
    found = [s for s in stages if s is not None]
    for s in found:
        if s not in STAGES:
            raise ValueError(f"unknown stage: {s!r}")
    return min(found, key=STAGES.index) if found else None


def stage_of_run(phase: str, stopped_in: str | None) -> tuple[str, bool]:
    """Return `(stage, stopped)` for a run phase; `escalated` stays in the stage of `stopped_in`."""
    if phase == "escalated":
        if stopped_in not in _PHASE_STAGE:
            raise ValueError(f"unknown phase for an escalated run: {stopped_in!r}")
        return _PHASE_STAGE[stopped_in], True
    if phase not in _PHASE_STAGE:
        raise ValueError(f"unknown run phase: {phase!r}")
    return _PHASE_STAGE[phase], False


def stage_of_spec(status: str, run: dict | None) -> str | None:
    """Return the stage of a spec from its status and run (`{"phase", "stopped_in"}`), None for finished specs."""
    if status not in _SPEC_STAGE:
        return None
    if run and run.get("phase") and run["phase"] != "done":
        return stage_of_run(run["phase"], run.get("stopped_in"))[0]
    return _SPEC_STAGE[status]


def stage_of_issue(issue: dict) -> str | None:
    """Return "Issue" for an open issue without the `tracked` label, else None."""
    if str(issue.get("state", "")).upper() != "OPEN":
        return None
    names = {(label.get("name") if isinstance(label, dict) else label) for label in issue.get("labels") or []}
    return None if "tracked" in names else "Issue"


def stage_of_release(release: dict) -> str | None:
    """Return "Prod" for a release verified in staging and not yet running in prod, else None."""
    if release.get("verified") and not release.get("running_in_prod"):
        return "Prod"
    return None


def explain(stage: str) -> dict:
    """Return `{"what", "agents", "commands", "decision"}` for a stage; `decision` only for decision columns."""
    if stage not in _EXPLAIN:
        raise ValueError(f"unknown stage: {stage!r}")
    e = _EXPLAIN[stage]
    return {"what": e["what"], "agents": list(e["agents"]), "commands": list(e["commands"]),
            "decision": e["decision"] if stage in DECISION else None}
