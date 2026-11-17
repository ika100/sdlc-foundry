"""`cplat next` questions of the build, the stops and the raise (spec 193): options, `input`, `other`, actions and undo, as pure
functions of the state. Standard library only; nothing here does any I/O.

Public API (every function takes the `_Ctx` of `nextquestions.build` first; it is passed in, so this module needs no cycle):
- `actions(item) -> list[dict]`: the actions of a build item (`kind: build`) or a dispatcher stop (an item with `stop`), as
  `{what, target, undo}`; `[]` for any other item. `setup_actions(repo) -> list[dict]`: those of the set-up.
- `build(ctx, item, b) -> dict`: the `build` question of the run queue item (or `build-setup` while `b["setup"]` is set).
- `watch(ctx, b) -> dict`: the `watch` question of the progress screen.
- `stop(ctx, item, log=False) -> dict`: the question of a dispatcher stop (`Decide`, `Stopped` or `Budget`); `log=True` leaves
  out "Show the log".
- `raise_budget(ctx, b, value) -> dict`: the `raise-budget` question of `--show raise-budget:<value>`.
- `quote(text) -> str`: `text` as one double-quoted shell word (backslash, quote, dollar and backtick escaped).

An option with `input` is `{"name": ..., "prompt": ...}`; the typed value replaces `<name>` in its `steps`, `then` and `undo`.
A question with `other` is `{"steps": [...], "spec": path|None}`: a typed answer replaces `<answer>` in `other.steps`.
"""
from __future__ import annotations

import re

import nextbuildscreen as bs
import nextquestions as nq

_PROMPT = {"tokens": "How many tokens may be used today? (a whole number)"}
_SETUP_PROMPT = "How many tokens may be used per day? (a whole number)"
_MERGES = "each merge (a revert pull request takes it back)"


def quote(text: object) -> str:
    return '"' + re.sub(r'([\\"$`])', r"\\\1", " ".join(str(text).split())) + '"'


def _tokens_input(prompt: str = _PROMPT["tokens"]) -> dict:
    return {"name": "tokens", "prompt": prompt}


def _undo(*lines: str) -> list[str]:
    return [f"Undo: {ln}" for ln in lines]


# ---------------- actions ----------------

def _label(repo: str, number: int) -> dict:
    return {"what": "label removed", "target": f"{repo}#{number} needs-decision",
            "undo": f"gh issue edit {number} -R {repo} --add-label needs-decision"}


def setup_actions(repo: str) -> list[dict]:
    return [{"what": "pull request with .platform/dispatch.yml", "target": f"{repo} main", "undo": None}]


def _build_actions(repo: str) -> list[dict]:
    return [{"what": "the run queue starts: claims, pull requests, merges on green CI", "target": f"{repo} main",
             "undo": "cplat dispatch pause --drain"}]


def _label_actions(item: dict) -> list[dict]:
    if "--remove-label needs-decision" not in (item.get("command") or ""):
        return []
    number = nq._issue_ref(item)
    return [_label(nq._where(item), number)] if number else []


def actions(item: dict) -> list[dict]:
    stop = item.get("stop")
    if item.get("kind") == "build":
        return _build_actions(nq._where(item) or str((item.get("object") or {}).get("repo") or ""))
    if not stop or stop.get("kind") == "budget":
        return []
    repo, number = nq._where(item), (item.get("object") or {}).get("issue")
    if stop.get("kind") != "decision":
        return _label_actions(item)
    key = str(stop.get("key") or "")
    labels = [_label(repo, number)] if number else []
    if key.startswith("issue-"):
        return [{"what": "comment", "target": f"{repo}#{key[6:]}", "undo": None}, *(labels or [_label(repo, int(key[6:]))])]
    spec_id = (item.get("object") or {}).get("spec") or ""
    return [{"what": "answer commit", "target": f"docs/specs/{spec_id}/ on {stop.get('branch')}",
             "undo": "printed by the command"}, *labels]


# ---------------- build start and set-up ----------------

def _queue_refs(item: dict, b: dict) -> list[str]:
    repo = str((item.get("object") or {}).get("repo") or "")
    refs = []
    for q in b.get("queue") or []:
        key = str(q.get("key") or "")
        if key.startswith("issue-"):
            refs.append(f"issue:{repo}:{key[6:]}")
        elif key:
            refs.append(f"spec:{repo}:{q.get('spec') or key[5:]}")
    return refs


def build(ctx, item: dict, b: dict) -> dict:
    refs = _queue_refs(item, b)
    later = nq._option(ctx, "later", "Not now", "Puts it off for now; it stays in the list of what waits.",
                       then=ctx.call(more_later=[item["id"]]), refs=refs)
    setup = b.get("setup")
    if setup is not None:
        acts, n = setup_actions(nq._where(item)), setup.get("tokens_per_day")
        if n:
            opt = nq._option(ctx, "set-up", "Set up and build", "", steps=[f"cplat dispatch setup --tokens-per-day {int(n)}"],
                             acts=acts, refs=refs)
        else:
            opt = nq._option(ctx, "set-up", "Set up and build", "", steps=["cplat dispatch setup --tokens-per-day <tokens>"],
                             acts=acts, refs=refs, input=_tokens_input(_SETUP_PROMPT))
        return nq._question("build-setup", "Set up", "Building needs a run policy. Set it up and build?",
                            [opt, nq._details(ctx, "build-setup", refs), later])
    acts = _build_actions(nq._where(item))
    opts = [nq._option(ctx, f"slots-{n}", label, "", steps=[f"cplat dispatch build --slots {n}"], acts=acts,
                       extra_cannot=[_MERGES], refs=refs)
            for n, label in ((2, "Two at a time"), (1, "One at a time"))]
    count = len(b.get("queue") or [])
    return nq._question("build", "Build", f"{nq._n(count, 'item is', 'items are')} ready to build. How many at once?",
                        [*opts, nq._details(ctx, "build", refs), later])


# ---------------- progress ----------------

def watch(ctx, b: dict) -> dict:
    keep = nq._option(ctx, "keep-watching", "Keep watching", "Waits for the next change and shows the screen again.",
                      then=ctx.call("--watch", "540", "--after", str(b.get("last_seq") or 0)))
    leave = nq._option(ctx, "leave-running", "Leave it running", "Does nothing; the build goes on without this session.")
    drain = nq._option(ctx, "stop-after", "Stop after the running items", "", steps=["cplat dispatch pause --drain"],
                       undo=_undo("cplat dispatch resume"))
    return nq._question("watch", "Building", "The build is running. What now?", [keep, leave, drain])


# ---------------- stops ----------------

def _refs(item: dict) -> list[str]:
    ref = nq._ref(item)
    if ref:
        return [ref]
    key = str((item.get("stop") or {}).get("key") or "")
    repo = str((item.get("object") or {}).get("repo") or "")
    return [f"issue:{repo}:{key[6:]}"] if key.startswith("issue-") else []


def _next_question(stop: dict) -> tuple[int, dict] | None:
    answered = set(stop.get("answered") or [])
    return next(((n, q) for n, q in enumerate(stop.get("questions") or [], 1) if n not in answered), None)


def _answer_step(key: str, n: int, answer: str) -> str:
    return f"cplat dispatch answer {key} --question {n} --answer {quote(answer)}"


def _park(ctx, item: dict, stop: dict, refs: list[str], *, drain: bool = False) -> dict:
    if drain:
        return nq._option(ctx, "park", "Park it", "", steps=["cplat dispatch pause --drain"], undo=_undo("cplat dispatch resume"),
                          refs=refs)
    key, reason = stop["key"], " ".join(str(stop.get("reason") or item.get("reason") or "it needs you").split())[:60]
    return nq._option(ctx, "park", "Park it", "", steps=[f"cplat dispatch skip {key} --reason {quote('parked: ' + reason)}"],
                      undo=_undo(f"cplat dispatch resume {key}"), refs=refs)


def stop(ctx, item: dict, log: bool = False) -> dict:
    st, qid = item["stop"], item["id"]
    refs = [] if st["kind"] == "budget" else _refs(item)
    if st["kind"] == "budget":
        opts = [nq._option(ctx, "wait", "Wait for tomorrow", "Does nothing now; the work goes on when the budget is back.", refs=refs),
                nq._option(ctx, "raise", "Raise today's budget", "Asks for the new budget and shows what it means.",
                           then=ctx.call("--show", "raise-budget:<tokens>"), input=_tokens_input(), refs=refs),
                _park(ctx, item, st, refs, drain=True)]
        return nq._question(qid, "Budget", "The daily budget is reached. What now?", opts)
    key, acts = st["key"], actions(item)
    if st["kind"] == "decision":
        return _decision(ctx, item, st, refs, acts)
    opts = [nq._option(ctx, "try-again", "Try again", "", steps=[f"cplat dispatch resume {key}"], acts=acts, refs=refs),
            _park(ctx, item, st, refs)]
    if not log:
        opts.append(nq._option(ctx, "show-log", "Show the log", "Shows where the log of the run is.",
                               then=ctx.call("--show", f"log:{key}"), refs=refs))
    if acts:
        opts.append(nq._details(ctx, qid, refs))
    return nq._question(qid, "Stopped", f"{item['what']} stopped: {item.get('reason') or 'it needs you'}. Try again?", opts)


def _decision(ctx, item: dict, st: dict, refs: list[str], acts: list[dict]) -> dict:
    qid, key = item["id"], st["key"]
    branch = f" (its work stays on branch {st['branch']})" if st.get("branch") else ""
    stop_it = nq._option(ctx, "stop-item", f"Stop this item{branch}", "", steps=[f"cplat dispatch skip {key} --reason {quote('stopped by you')}"],
                         undo=_undo(f"cplat dispatch resume {key}"), refs=refs)
    found = _next_question(st)
    if not found:
        opts = [nq._option(ctx, "let-go-on", "Let it go on", "", steps=[f"cplat dispatch resume {key}"], refs=refs),
                nq._details(ctx, qid, refs), stop_it]
        return nq._question(qid, "Decide", f"{item['what']} stopped for a decision. Let it go on?", opts)
    n, q = found
    opts = [nq._option(ctx, f"answer-{i}", answer, "", steps=[_answer_step(key, n, answer)], acts=acts, refs=refs)
            for i, answer in enumerate(list(q.get("options") or [])[:2], 1)]
    question = nq._question(qid, "Decide", f"{q['text']} ({item['what']})", [*opts, nq._details(ctx, qid, refs), stop_it])
    question["other"] = {"steps": [f'cplat dispatch answer {key} --question {n} --answer "<answer>"'],
                         "spec": st.get("spec_path")}
    return question


# ---------------- the raise ----------------

def raise_budget(ctx, b: dict, value: str) -> dict:
    keep = nq._option(ctx, "keep-budget", "Keep the budget", "Does nothing; the budget of today stays as it is.")
    if bs.valid_raise(b, value):
        n = int(value)
        up = nq._option(ctx, "raise-to", f"Raise to {n:,}", "", steps=[f"cplat dispatch budget --today {n}"],
                        undo=_undo("cplat dispatch budget --reset-today"))
        return nq._question("raise-budget", "Raise", f"Raise today's budget to {n:,} tokens?", [up, keep])
    again = nq._option(ctx, "try-another", "Try another number", "Asks for another number.",
                       then=ctx.call("--show", "raise-budget:<tokens>"), input=_tokens_input())
    return nq._question("raise-budget", "Raise", "That number is not above today's budget. Try another?", [again, keep])
