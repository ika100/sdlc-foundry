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
        "what": "An open issue that no spec tracks yet. Nothing is planned or built for it.",
        "agents": ["shared:triage"],
        "commands": ["/component:spec", "/system:spec"],
        "decision": None,
    },
    "Spec": {
        "what": "The spec is a draft: the problem, the criteria and the scope are written down and wait for your approval.",
        "agents": ["shared:architect", "shared:tester"],
        "commands": ["/component:spec", "/system:spec", "/component:approve"],
        "decision": "Approve the spec, or ask for changes. Nothing is planned or built before you approve.",
    },
    "Plan": {
        "what": "The approved spec is split into tasks and repo slices, with the order they are built in.",
        "agents": ["shared:architect", "shared:planner"],
        "commands": ["/component:plan", "/component:ship"],
        "decision": None,
    },
    "Build": {
        "what": "The tests are written first, then the coders implement the tasks and the quality, security and review gates run.",
        "agents": ["svc:tester", "svc:coder", "shared:quality", "shared:security", "svc:reviewer"],
        "commands": ["/component:build", "/component:ship"],
        "decision": "Answer an escalation when the run stops, for example a failing gate or an exhausted budget.",
    },
    "Land": {
        "what": "The change is in a pull request that is checked and merged, and the release is built.",
        "agents": ["shared:reviewer", "shared:release"],
        "commands": ["/component:ship"],
        "decision": None,
    },
    "Dev": {
        "what": "The release is deployed to the dev instance and its smoke checks run.",
        "agents": ["shared:deployer"],
        "commands": ["/component:ship", "/component:deploy"],
        "decision": None,
    },
    "Staging": {
        "what": "The release runs in staging, where the acceptance criteria are verified against the live instance.",
        "agents": ["shared:deployer", "shared:tester"],
        "commands": ["/component:ship", "/component:promote"],
        "decision": None,
    },
    "Prod": {
        "what": "The release is verified in staging and waits to be promoted to production.",
        "agents": ["shared:deployer"],
        "commands": ["/component:promote"],
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
