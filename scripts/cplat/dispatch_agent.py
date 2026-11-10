"""Spec 167: the two agent calls of the dispatcher (design.md "Premise check", "Mode check").

  premise(repo, issue, main_sha) -> {verdict, evidence, why, tokens, cached}   holds | resolved, the evidence checked in code
  mode(repo, spec) -> {mode, why, tokens, cached}                                single | team

Both are one short, read-only `claude -p --output-format json` call (`ask`); every other decision of the dispatcher is plain code.
A failed call is `holds` (premise) or `single` (mode). `tokens` is what the call used (input + output + cache), None when the
answer reported no usage (the caller books `CEILING` then), 0 for a cached answer; the caller books it with
`dispatch_budget.book_agent`. The answers are cached in `state.json` under `checks[<key>]`: a premise by (`main_sha`, the issue's
`updatedAt`), a mode by the sha of the plan (of the spec text when there is none). A failed call is not cached.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import dispatch_state as st
import feedback
import settings
import spec as specmod
import triage
import units
from core import PlatformError, run

CEILING = 200_000        # tokens booked for a call whose answer reports no usage: the bound of `--max-turns 8`
TIMEOUT = 180            # seconds
MAX_TURNS = "8"
TOOLS = ["Read", "Grep", "Glob", "Bash(git log:*)", "Bash(git show:*)"]
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
BODY_LIMIT = 4000
SPEC_LIMIT = 8000
HINT_LIMIT = 15
TEAM_PARALLEL = 3
SHA = re.compile(r"[0-9a-fA-F]{7,40}")
PR_URL = re.compile(r"/pull/(\d+)")


# ---------------- the call ----------------

def ask(prompt: str, cwd: Path | str, tools: list[str] | None = None) -> tuple[str, int | None]:
    """One `claude -p` call: (the answer's `result` text, tokens used or None). PlatformError when it fails."""
    model, _ = settings.coordinator_model(Path(cwd), prompt, None)
    exe = os.environ.get("CPLAT_CLAUDE") or "claude"
    cmd = [exe, "-p", prompt, "--output-format", "json", "--max-turns", MAX_TURNS, "--model", model,
           "--allowedTools", *(tools if tools is not None else TOOLS)]
    p = run(cmd, cwd=cwd, check=False, timeout=TIMEOUT)
    if p.returncode != 0:
        raise PlatformError(f"claude exited {p.returncode}: {(p.stderr or '').strip()[-200:]}")
    try:
        doc = json.loads(p.stdout)
    except ValueError:
        raise PlatformError("claude answered no JSON") from None
    if not isinstance(doc, dict) or doc.get("is_error") or not isinstance(doc.get("result"), str):
        raise PlatformError("claude answered an error")
    usage = doc.get("usage")
    tokens = None
    if isinstance(usage, dict):
        tokens = sum(v for k in TOKEN_FIELDS if isinstance(v := usage.get(k), int) and not isinstance(v, bool))
    return doc["result"], tokens


def _answer(text: str) -> dict:
    """The first JSON object of the model's text (it may wrap it in a fence or a sentence)."""
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                doc, _ = dec.raw_decode(text[i:])
            except ValueError:
                continue
            if isinstance(doc, dict):
                return doc
    raise PlatformError("the answer holds no JSON object")


def _call(prompt: str, repo: Path) -> tuple[dict | None, int | None]:
    """(the answer as a dict or None when the call failed, tokens)."""
    try:
        text, tokens = ask(prompt, repo, TOOLS)
    except PlatformError:
        return None, None
    try:
        return _answer(text), tokens
    except PlatformError:
        return None, tokens


# ---------------- the cache ----------------

def _cached(slug: str, key: str, kind: str, **match: object) -> dict | None:
    hit = (st.load(slug).get("checks", {}).get(key) or {}).get(kind)
    return hit if isinstance(hit, dict) and all(hit.get(k) == v for k, v in match.items()) else None


def _store(slug: str, key: str, kind: str, entry: dict) -> None:
    def go(state: dict) -> None:
        state["checks"].setdefault(key, {})[kind] = {**entry, "at": st.stamp()}
    st.update(slug, go)


# ---------------- the premise check ----------------

def _git(repo: Path, *args: str) -> tuple[int, str]:
    p = run(["git", *args], cwd=repo, check=False)
    return p.returncode, p.stdout.strip()


def hints(repo: Path, issue: dict) -> list[str]:
    """Commits on `origin/main` since the issue was created that mention `#N` (`<sha> <subject>`)."""
    n = int(issue["number"])
    args = ["log", "origin/main", "-E", f"--grep=#{n}([^0-9]|$)", f"--max-count={HINT_LIMIT}", "--format=%h %s"]
    if issue.get("createdAt"):
        args.append(f"--since={issue['createdAt']}")
    code, out = _git(repo, *args)
    return out.splitlines() if code == 0 and out else []


def _prompt_premise(issue: dict, found: list[str]) -> str:
    n = issue["number"]
    text = f"{issue.get('title') or ''}\n\n{issue.get('body') or ''}"
    commits = "\n".join(found) if found else "(none)"
    return (
        f"Decide whether issue #{n} of this repository is already resolved on origin/main. Title: {issue.get('title')}\n"
        "Read-only: look at the code and the history of origin/main (git log, git show origin/main:<path>), change nothing.\n"
        f"Commits on origin/main since the issue was created that mention #{n}:\n{commits}\n\n"
        f"{triage.fenced(text, BODY_LIMIT)}\n\n"
        'Answer with one JSON object only: {"verdict": "holds" | "resolved", "evidence": "<full sha of a commit on '
        'origin/main, or the URL of a merged pull request>", "why": "<one sentence>"}. '
        'Answer "resolved" only when the problem the issue describes is gone from origin/main and you can name the commit '
        'or merged pull request that fixed it; in any doubt answer "holds" with an empty evidence.'
    )


def _validated(repo: Path, evidence: object) -> str | None:
    """The full sha of a commit on `origin/main`, or the URL of a merged pull request, else None."""
    if not isinstance(evidence, str):
        return None
    ev = evidence.strip()
    if m := PR_URL.search(ev):
        p = run(["gh", "pr", "view", m.group(1), "--json", "state,url"], cwd=repo, check=False)
        if p.returncode == 0:
            try:
                doc = json.loads(p.stdout)
            except ValueError:
                return None
            if isinstance(doc, dict) and str(doc.get("state")).upper() == "MERGED" and doc.get("url"):
                return str(doc["url"])
        return None
    if not SHA.fullmatch(ev):
        return None
    code, full = _git(repo, "rev-parse", "--verify", "-q", f"{ev}^{{commit}}")
    if code != 0 or not full:
        return None
    return full if _git(repo, "merge-base", "--is-ancestor", full, "origin/main")[0] == 0 else None


def premise(repo: Path, issue: dict, main_sha: str) -> dict:
    """The premise of an issue about to take a slot: `holds`, or `resolved` with evidence that is a commit on `origin/main`
    or a merged pull request (checked here; else the verdict counts as `holds`). A failed call is `holds`."""
    repo = Path(repo)
    slug, key = st.slug_of(repo), f"issue-{int(issue['number'])}"
    updated = issue.get("updatedAt")
    if hit := _cached(slug, key, "premise", main_sha=main_sha, issue_updated=updated):
        return {"verdict": hit["verdict"], "evidence": hit.get("evidence"), "why": hit.get("why"), "tokens": 0, "cached": True}
    answer, tokens = _call(_prompt_premise(issue, hints(repo, issue)), repo)
    if answer is None:
        return {"verdict": "holds", "evidence": None, "why": "the premise check failed", "tokens": tokens, "cached": False}
    verdict, why = str(answer.get("verdict") or "").lower(), feedback.redact(str(answer.get("why") or "")).strip()
    evidence = None
    if verdict == "resolved":
        evidence = _validated(repo, answer.get("evidence"))
        if evidence is None:
            verdict, why = "holds", f"no valid evidence ({why})" if why else "no valid evidence"
    else:
        verdict = "holds"
    out = {"verdict": verdict, "evidence": evidence, "why": why}
    _store(slug, key, "premise", {**out, "main_sha": main_sha, "issue_updated": updated})
    return {**out, "tokens": tokens, "cached": False}


# ---------------- the mode check ----------------

def _heads(repo: Path, spec_id: str) -> list[str]:
    code, out = _git(repo, "rev-parse", "--verify", "-q", f"refs/heads/feature/{spec_id}")
    return ([out] if code == 0 and out else []) + ["origin/main"]


def _resolve(repo: Path, spec: object) -> specmod.Spec | None:
    """The spec as a `spec.Spec`: given, or the committed one on `feature/<id>` or `origin/main`. A given spec without a plan
    gets the committed plan of those heads."""
    if isinstance(spec, specmod.Spec):
        if spec.plan is not None:
            return spec
        for head in _heads(repo, spec.id):
            if (c := units._committed(repo, spec.id, head)) is not None and c.plan is not None:
                return specmod.Spec(spec.dir, spec.meta, spec.body, c.plan)
        return spec
    spec_id = str(spec)
    for head in _heads(repo, spec_id):
        if (c := units._committed(repo, spec_id, head)) is not None:
            return c
    return None


def _batches(sp: specmod.Spec) -> bool:
    """True when the plan's units at `--parallel 3` hold a `batch:` unit."""
    tasks = units._plan_tasks(sp)
    by_id = {str(t["id"]): t for t in tasks}
    try:
        levels = specmod.topo_levels([{**t, "id": str(t["id"])} for t in tasks])
    except PlatformError:
        levels = [[str(t["id"]) for t in tasks]]
    pos = {str(t["id"]): i for i, t in enumerate(tasks)}
    for level in levels:
        found = units._task_units(by_id, sorted((i for i in level if i in by_id), key=lambda i: pos[i]), TEAM_PARALLEL)
        if any(u.startswith("batch:") for u in found):
            return True
    return False


def _plan_ok(sp: specmod.Spec) -> bool:
    if sp.plan is None:
        return False
    try:
        return not specmod.check_plan(sp, *sp.plan)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _prompt_mode(sp: specmod.Spec) -> str:
    text = f"# {sp.id}\n\n{sp.body}"
    return (
        f"Decide how spec {sp.id} of this repository should be built: `single` (one session builds it in order) or `team` "
        "(independent parts are built in parallel by several sessions). Choose `team` only when the spec holds at least "
        "two parts that touch different files and do not depend on each other. Read-only: you may read the code, change nothing.\n\n"
        f"{triage.fenced(text, SPEC_LIMIT)}\n\n"
        'Answer with one JSON object only: {"mode": "single" | "team", "why": "<one sentence>"}.'
    )


def mode(repo: Path, spec: object) -> dict:
    """`team` when the committed, valid plan has a `batch:` unit at `--parallel 3` (no call), else the agent decides from
    spec.md; a failed call is `single`. `spec` is a `spec.Spec` or a spec id (read from `feature/<id>` or `origin/main`)."""
    repo = Path(repo)
    sp = _resolve(repo, spec)
    if sp is None:
        return {"mode": "single", "why": "the spec cannot be read", "tokens": 0, "cached": False}
    if _plan_ok(sp):
        team = _batches(sp)
        return {"mode": "team" if team else "single", "tokens": 0, "cached": False,
                "why": "the plan has parallel tasks" if team else "the plan has no parallel tasks"}
    slug, key = st.slug_of(repo), f"spec-{sp.number}"
    sha = hashlib.sha256(f"{json.dumps(sp.meta, sort_keys=True, default=str)}\n{sp.body}".encode()).hexdigest()[:16]
    if hit := _cached(slug, key, "mode", plan_sha=sha):
        return {"mode": hit["mode"], "why": hit.get("why"), "tokens": 0, "cached": True}
    answer, tokens = _call(_prompt_mode(sp), repo)
    if answer is None:
        return {"mode": "single", "why": "the mode check failed", "tokens": tokens, "cached": False}
    chosen = "team" if str(answer.get("mode") or "").lower() == "team" else "single"
    why = feedback.redact(str(answer.get("why") or "")).strip()
    _store(slug, key, "mode", {"mode": chosen, "why": why, "plan_sha": sha})
    return {"mode": chosen, "why": why, "tokens": tokens, "cached": False}
