"""`triage_batch`: the one GitHub read of `cplat issue triage batch` and the saved batch (spec 176).

One `gh api graphql` request returns the open issues with their comments, recently closed issues, merged pull requests and the
repo's labels; `build` turns the answer into the batch (facts from `triage_facts`, text redacted and fenced) and `save` keeps it
where `overview`, `confirm`, `act` and `publish-specs` read it.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import dispatch_state
import feedback
import spec as specs
import triage
import triage_facts as facts
from core import PlatformError

MAX_AGE = 7200
READ_LIMIT = 100
PRIORITY = ("p0", "p1", "p2")

QUERY = """query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    labels(first: 100) { nodes { name } }
    open: issues(states: OPEN, first: 100, orderBy: {field: CREATED_AT, direction: ASC}) {
      totalCount
      nodes { number title body url createdAt updatedAt authorAssociation author { login }
              labels(first: 30) { nodes { name } }
              comments(last: 100) { nodes { author { login } authorAssociation body createdAt } } }
    }
    closed: issues(states: CLOSED, first: 100, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number title body closedAt }
    }
    merged: pullRequests(states: MERGED, first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number title body url closingIssuesReferences(first: 20) { nodes { number } } }
    }
  }
}"""


def login(user: dict | str | None) -> str:
    """The login of a gh/GraphQL author object; a deleted user reads as `ghost`."""
    if isinstance(user, str):
        return user
    return (user or {}).get("login") or "ghost"


def normalise(node: dict) -> dict:
    """An issue as `triage_facts` takes it: flat author, labels as `[{"name"}]`, flat comments."""
    labels = node.get("labels") or []
    labels = labels.get("nodes", []) if isinstance(labels, dict) else labels
    comments = node.get("comments") or []
    comments = comments.get("nodes", []) if isinstance(comments, dict) else comments
    return {**node, "author": login(node.get("author")), "labels": [{"name": x["name"] if isinstance(x, dict) else x} for x in labels],
            "comments": [{**c, "author": login(c.get("author"))} for c in comments]}


def read(slug: str) -> dict:
    """The whole batch input from one GraphQL call: `open`, `open_total`, `closed`, `merged`, `labels`."""
    owner, _, name = slug.partition("/")
    try:
        raw = json.loads(triage.gh(["api", "graphql", "-F", f"owner={owner}", "-F", f"name={name}", "-f", f"query={QUERY}"]) or "{}")
    except (PlatformError, ValueError) as e:
        raise PlatformError("reading the issues failed", hint=str(e)) from e
    if raw.get("errors") or not (raw.get("data") or {}).get("repository"):
        first = (raw.get("errors") or [{}])[0].get("message") or "GitHub returned no repository"
        raise PlatformError("reading the issues failed", hint=first)
    repo = raw["data"]["repository"]
    open_ = repo["open"]
    nodes = [normalise(n) for n in open_["nodes"]]
    return {"open": nodes, "open_total": open_.get("totalCount", len(nodes)), "closed": repo["closed"]["nodes"],
            "merged": repo["merged"]["nodes"], "labels": [x["name"] for x in repo["labels"]["nodes"]]}


def _entry(issue: dict, now: datetime, ctx: dict) -> dict:
    reply = facts.reply(issue, now)
    fresh = {id(c) for c in facts.new_since(issue, reply)} if reply else set()
    status = facts.status(issue, ctx["specs"], ctx["open_numbers"], ctx["merged"])
    names = sorted(lb["name"] for lb in issue["labels"])
    return {
        "number": issue["number"], "title": feedback.redact(issue.get("title") or ""), "author": issue["author"],
        "role": facts.role(issue.get("authorAssociation")), "created": issue.get("createdAt", ""), "url": issue.get("url") or "",
        "labels": names, "priority_labels": [x for x in names if x in PRIORITY],
        "body": triage.fenced(issue.get("body") or "", triage.BODY_LIMIT),
        "comments": [{"author": c["author"], "role": facts.role(c.get("authorAssociation")), "created": c.get("createdAt", ""),
                      "new": id(c) in fresh, "text": triage.fenced(c.get("body") or "", triage.COMMENT_LIMIT)}
                     for c in issue["comments"]],
        "duplicates": facts.duplicates(issue, ctx["open"], ctx["closed"], now), "engine": facts.engine(issue), "reply": reply,
        "status": status, "handled": facts.handled(status),
    }


def build(raw: dict, *, new: bool, root: Path, now: datetime, slug: str = "") -> dict:
    """The batch: the queue (plus answered `needs-info` issues), what was skipped, facts per issue, the missing labels."""
    issues = raw["open"]
    ctx = {"open": issues, "closed": raw["closed"], "merged": raw["merged"], "open_numbers": {i["number"] for i in issues},
           "specs": specs.all_specs(root)}
    queued = {i["number"]: i for i in triage.queue(issues, new=new)}
    skipped = []
    for issue in sorted(issues, key=lambda i: i["number"]):
        if "needs-info" not in {lb["name"] for lb in issue["labels"]}:
            continue
        reply = facts.reply(issue, now)
        if reply and reply["state"] == "answered":
            queued[issue["number"]] = issue
        elif reply:
            skipped.append({"number": issue["number"], "reason": f"silent {reply['age']}"})
    more = raw["open_total"] - len(issues)
    if more > 0:
        skipped.append({"number": None, "reason": f"{more} more open issues not read (limit {READ_LIMIT})"})
    ordered = sorted(queued.values(), key=lambda i: (i.get("createdAt", ""), i["number"]))
    return {"repo": slug, "read_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "batch_file": "",
            "issues": [_entry(i, now, ctx) for i in ordered], "skipped": skipped,
            "missing_labels": sorted(set(triage.LABELS) - set(raw["labels"])), "specs_pr": None}


def path(slug: str) -> Path:
    return dispatch_state.state_root() / "triage" / dispatch_state.slug_dir(slug) / "batch.json"


def save(batch: dict) -> Path:
    """Write the batch to its file (atomically) and record the file in the batch."""
    target = path(batch["repo"])
    target.parent.mkdir(parents=True, exist_ok=True)
    batch["batch_file"] = str(target)
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(batch, f, indent=2)
    os.replace(tmp, target)
    return target


def load(slug: str, max_age: int = MAX_AGE, now: datetime | None = None) -> dict:
    """The saved batch of the repo; a missing or old one is refused."""
    target = path(slug)
    hint = "run cplat issue triage batch again"
    if not target.is_file():
        raise PlatformError("no triage batch saved", hint=hint)
    batch = json.loads(target.read_text())
    read_at = datetime.fromisoformat(batch["read_at"].replace("Z", "+00:00"))
    if ((now or datetime.now(timezone.utc)) - read_at).total_seconds() > max_age:
        raise PlatformError("the triage batch is older than 2 hours", hint=hint)
    return batch
