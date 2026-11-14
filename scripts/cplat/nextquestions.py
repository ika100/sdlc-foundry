"""`cplat next` questions (spec 192): the choices the session asks after it printed the screen, as pure functions of the state.

Public API:
- `build(state, *, shown_at, later, args, page, show=None, choose=None, attended=True) -> (questions, page)`: the
  questions of the shown group (design.md, Questions per group) cut to one page of at most four, and `{n, of, text}` of
  the page. `later` is the ids put off; `args` the call's other arguments to repeat (`--ascii`, `--judgement FILE`,
  `--repo-dir DIR`); `show="assumptions"` keeps the approve question, `show="details:<QID>"` that one question, both
  without their "Show" option; `choose="approve"` asks which spec to approve, two specs a page. `attended=False` (an
  unattended run) has no questions and no `record` argv.
- `actions(item) -> list[dict]`: what choosing the item's option does outside the machine, as `{what, target, undo}`.
- `action_map(state, later=()) -> dict`: item id and question id -> actions, the `actions` argument of
  `nextscreen.render`.

An option is `{id, label, recommended, description, steps, then, actions, cannot_undo, undo, record}`: `steps` (commands
to run) or `then` (argv of the next `cplat next` call) or neither (the option does nothing). The first option is the
recommended one. Question ids: `approve`, `triage`, `approve-one`, `unavailable`, the item id of a stopped run, a
release, a promotion or a review, and `<item id>#<n>` for the n-th open question of a draft. Nothing here does any I/O.
"""
from __future__ import annotations

import re

import nextscreen
import nextstate

PER_PAGE = 4
CHOOSE_PER_PAGE = 2
_REVERT = "(a revert pull request takes it back)"


def _n(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _number(spec_id: str) -> str:
    return spec_id.split("-", 1)[0].lstrip("0") or "0"


# ---------------- actions ----------------

def _where(item: dict) -> str:
    return str((item.get("object") or {}).get("repo") or item.get("cwd_repo") or "")


def _issue_ref(item: dict) -> int | None:
    m = re.search(r"gh issue edit (\d+) --remove-label needs-decision", item.get("command") or "")
    return int(m.group(1)) if m else (item.get("object") or {}).get("issue")


def actions(item: dict) -> list[dict]:
    """What the item's choice does outside the machine (design.md, Actions); `undo` is None when nothing takes it back."""
    kind, obj, command = item.get("kind"), item.get("object") or {}, item.get("command") or ""
    repo = _where(item)
    if kind == "approve":
        sid = (item.get("draft") or {}).get("spec") or obj.get("spec") or ""
        pr = obj.get("pr")
        return [{"what": "approval commit", "target": f"docs/specs/{sid}/ on feature/{sid}",
                 "undo": f'cplat spec set-status {sid} draft --reason "undo approval"'},
                {"what": "merge", "target": f"PR #{pr} into main" if pr else f"feature/{sid} into main", "undo": None}]
    if kind == "answer":
        sid, pr = (item.get("draft") or {}).get("spec") or obj.get("spec") or "", obj.get("pr")
        level = (re.match(r"/(\w+):", command) or [None, "component"])[1]
        return [{"what": "spec commit and push", "target": f"PR #{pr}" if pr else f"feature/{sid}",
                 "undo": f"/{level}:spec --amend {_number(sid)} <your new answer>"}]
    if kind in ("escalation", "stuck"):
        if re.match(r"/\w+:ship\b", command):
            spec = obj.get("spec") or command.rsplit(" ", 1)[-1]
            return [{"what": "push and pull request", "target": f"{repo} feature/{spec}",
                     "undo": f"gh pr close --delete-branch feature/{spec} -R {repo}"},
                    {"what": "merge and deploy to dev", "target": f"{repo} main", "undo": None}]
        m = re.match(r"/component:fix #(\d+)", command)
        if m:
            return [{"what": "pull request", "target": f"{repo}, a fix for #{m.group(1)}",
                     "undo": f"gh pr close <its number> -R {repo}"}]
        number = _issue_ref(item) if "--remove-label needs-decision" in command else None
        if number:
            return [{"what": "label removed", "target": f"{repo}#{number} needs-decision",
                     "undo": f"gh issue edit {number} -R {repo} --add-label needs-decision"}]
        return []
    if kind == "triage":
        number = obj.get("issue")
        return [{"what": "labels and a comment", "target": f"{repo}#{number}",
                 "undo": f"/issue:triage {number} again routes it differently"}]
    if kind == "release":
        return [{"what": "release pull request and merge", "target": f"{repo} main", "undo": None},
                {"what": "tag", "target": "the next version", "undo": None},
                {"what": "GitHub release", "target": repo, "undo": None}]
    if kind == "promote":
        return [{"what": "promotion pull request and merge", "target": f"prod of {obj.get('component')}",
                 "undo": (item.get("way_back") or {}).get("command")}]
    if kind == "review":
        return [{"what": "approve and merge", "target": f"{repo} PR #{obj.get('pr')}", "undo": None}]
    return []


def _cannot_text(a: dict) -> str:
    what, target = a["what"], a["target"]
    return {"merge": f"the merge of {target} {_REVERT}",
            "tag": "the tag and the published release", "GitHub release": "the tag and the published release",
            "merge and deploy to dev": "the merge and the deploy to dev",
            "release pull request and merge": f"the merge of the release pull request {_REVERT}",
            "promotion pull request and merge": f"the promotion to {target}",
            "approve and merge": f"the approval and the merge of {target}"}.get(what, f"{what} ({target})")


def _cannot(acts: list[dict], extra: list[str] | None = None) -> list[str]:
    out: list[str] = []
    for text in [*(_cannot_text(a) for a in acts if not a.get("undo")), *(extra or [])]:
        if text not in out:
            out.append(text)
    return out


# ---------------- ids, calls and refs ----------------

def _qid(item: dict, n: int | None = None) -> str:
    return item["id"] if n is None else f"{item['id']}#{n}"


def _ref(item: dict) -> str | None:
    obj = item.get("object") or {}
    if obj.get("spec"):
        return f"spec:{obj.get('repo')}:{obj['spec']}"
    return f"issue:{obj.get('repo')}:{obj['issue']}" if obj.get("issue") else None


def action_map(state: dict, later=()) -> dict[str, list[dict]]:
    """Item id and question id -> actions, for the assumptions and details sub-screens of `nextscreen.render`."""
    later, out = set(later), {}
    for item in state["items"]:
        if item["id"] in later:
            continue
        acts = actions(item)
        out[item["id"]] = acts
        if item["kind"] == "answer":
            for n, _ in enumerate((item.get("draft") or {}).get("questions") or [], 1):
                out[_qid(item, n)] = acts
        elif item["kind"] in ("approve", "triage"):
            for qid in ((item["kind"], "approve-one") if item["kind"] == "approve" else ("triage",)):
                out[qid] = out.get(qid, []) + acts
    return out


class _Ctx:
    """What every option of one `build` call shares: the time shown, the arguments to repeat and what is put off."""

    def __init__(self, shown_at: str, later, args, attended: bool) -> None:
        self.shown_at, self.later, self.args, self.attended = shown_at, list(later), list(args), attended

    def call(self, *extra: str, more_later=()) -> list[str]:
        ids = [*self.later, *(i for i in more_later if i not in self.later)]
        return ["cplat", "next", "--json", *self.args, *(a for i in ids for a in ("--later", i)), *extra]

    def record(self, option: str, refs: list[str]) -> list[str]:
        if not self.attended:
            return []
        return ["cplat", "next", "answer", "--shown-at", self.shown_at, "--option", option,
                *(a for r in refs for a in ("--item", r))]


def _option(ctx: _Ctx, oid: str, label: str, what: str, *, steps=None, then=None, acts=None, extra_cannot=None,
            refs=None) -> dict:
    """One option; `what` says what happens when it does not run commands; `refs` are the items its record names."""
    acts = acts or []
    cannot = _cannot(acts, extra_cannot)
    parts = [f"Cannot be undone: {'; '.join(nextstate.plain(c) for c in cannot)}."] if cannot else []
    parts.append(f"Runs {', '.join(steps)}" if steps else nextstate.plain(what))
    return {"id": oid, "label": nextstate.plain(label), "recommended": False, "description": " ".join(parts),
            "steps": list(steps) if steps else None, "then": then, "actions": acts, "cannot_undo": cannot,
            "undo": [f"Undo: {a['undo']}" for a in acts if a.get("undo")],
            "record": ctx.record(oid, refs or [])}


def _question(qid: str, header: str, text: str, options: list[dict]) -> dict:
    options[0]["recommended"] = True
    return {"id": qid, "header": header[:12], "question": nextstate.plain(text), "options": options[:4]}


def _later(ctx: _Ctx, items: list[dict]) -> dict:
    return _option(ctx, "later", "Later", "Puts it off for now; it stays in the list of what waits.",
                   then=ctx.call(more_later=[i["id"] for i in items]), refs=[r for i in items if (r := _ref(i))])


def _details(ctx: _Ctx, qid: str, refs: list[str]) -> dict:
    return _option(ctx, "show-details", "Show details", "Shows what this does, step by step, and how to take it back.",
                   then=ctx.call("--show", f"details:{qid}"), refs=refs)


# ---------------- questions per group ----------------

def _stopped(ctx: _Ctx, item: dict) -> dict:
    qid, acts, kind = _qid(item), actions(item), item["kind"]
    if kind == "budget":
        return _question(qid, "Budget", "The daily budget is reached. What now?",
                         [_option(ctx, "wait", "Wait for tomorrow", "Does nothing now; the work goes on when the budget is back."),
                          _later(ctx, [item])])
    refs = [r] if (r := _ref(item)) else []
    opts = [_option(ctx, "try-again", "Try again", "", steps=[item["command"]], acts=acts)]
    if acts:
        opts.append(_details(ctx, qid, refs))
    opts.append(_later(ctx, [item]))
    return _question(qid, "Stopped", f"{item['what']} stopped: {item.get('reason') or 'it needs you'}. Try again?", opts)


def _answers(ctx: _Ctx, items: list[dict]) -> list[dict]:
    out, count = [], 0
    for item in items:
        d, acts = item["draft"], actions(item)
        refs = [r] if (r := _ref(item)) else []
        for n, q in enumerate(d.get("questions") or [], 1):
            count += 1
            qid, choices = _qid(item, n), list(q.get("options") or [])[:2]
            opts = []
            for i, answer in enumerate(choices):
                text = f"answers to open questions: {q['text']}: {answer}"
                opts.append(_option(ctx, f"answer-{i + 1}", answer, "",
                                    steps=[item["command"].replace("<answers>", text)], acts=acts, refs=refs))
            opts.append(_details(ctx, qid, refs))
            opts.append(_later(ctx, [item]))
            out.append(_question(qid, f"Question {count}", f"{q['text']} ({d['title']}, spec {_number(d['spec'])})", opts))
    return out


def _approve(ctx: _Ctx, items: list[dict], choose: bool = False) -> dict:
    refs = [r for i in items if (r := _ref(i))]
    acts = [a for i in items for a in actions(i)]
    if len(items) == 1:
        item = items[0]
        d = item["draft"]
        opts = [_option(ctx, "approve", "Approve", "", steps=[item["command"]], acts=acts, refs=refs),
                _option(ctx, "show-assumptions", "Show assumptions", "Shows the assumptions I made and what approving does.",
                        then=ctx.call("--show", "assumptions"), refs=refs),
                _later(ctx, items)]
        return _question("approve", "Approve", f"Approve the written spec {d['title']} (spec {_number(d['spec'])})?", opts)
    opts = [_option(ctx, "approve-all", f"Approve all {len(items)}", "", steps=[i["command"] for i in items], acts=acts, refs=refs),
            _option(ctx, "show-assumptions", "Show assumptions", "Shows the assumptions I made and what approving does.",
                    then=ctx.call("--show", "assumptions"), refs=refs),
            _option(ctx, "approve-only-one", "Approve only one", "Lets you pick one of the written specs.",
                    then=ctx.call("--choose", "approve"), refs=refs),
            _later(ctx, items)]
    return _question("approve", "Approve", f"Approve the {len(items)} written specs?", opts)


def _choose_approve(ctx: _Ctx, items: list[dict], page: int) -> tuple[list[dict], dict]:
    """The "Approve only one" question: two specs a page, oldest first."""
    pages = max(1, -(-len(items) // CHOOSE_PER_PAGE))
    n = min(max(1, page), pages)
    chunk = items[(n - 1) * CHOOSE_PER_PAGE:n * CHOOSE_PER_PAGE]
    opts = []
    for item in chunk:
        d = item["draft"]
        opts.append(_option(ctx, f"approve-{_number(d['spec'])}", f"{d['title']} (spec {_number(d['spec'])})", "",
                            steps=[item["command"]], acts=actions(item), refs=[r] if (r := _ref(item)) else []))
    opts.append(_details(ctx, "approve-one", [r for i in chunk if (r := _ref(i))]))
    if n < pages:
        opts.append(_option(ctx, "next-specs", "Next specs", "Shows the next written specs.",
                            then=ctx.call("--choose", "approve", "--page", str(n + 1))))
    else:
        opts.append(_later(ctx, items))
    return [_question("approve-one", "Which spec", "Which spec do you want to approve now?", opts)], _page(n, pages)


def _triage(ctx: _Ctx, items: list[dict]) -> dict:
    refs = [r for i in items if (r := _ref(i))]
    acts = [a for i in items for a in actions(i)]
    steps = [items[0]["command"]] if len(items) == 1 else ["/issue:triage"]
    text = f"Triage issue #{items[0]['object']['issue']} ({items[0]['what']})?" if len(items) == 1 \
        else f"Triage the {len(items)} new issues?"
    return _question("triage", "Triage", text, [
        _option(ctx, "triage", "Triage them", "", steps=steps, acts=acts, refs=refs),
        _details(ctx, "triage", refs), _later(ctx, items)])


def _release(ctx: _Ctx, item: dict) -> dict:
    qid, acts, kind = _qid(item), actions(item), item["kind"]
    extra = [w] if (w := (item.get("way_back") or {}).get("warning")) else []
    label, oid, header = {"release": ("Release now", "release-now", "Release"), "promote": ("Promote", "promote", "Promote"),
                          "review": ("Approve and merge", "approve-merge", "Review")}[kind]
    opts = [_option(ctx, oid, label, "", steps=[item["command"]], acts=acts, extra_cannot=extra),
            _details(ctx, qid, []), _later(ctx, [item])]
    text = {"release": f"{item.get('reason') or 'A release is ready'}. Release now?",
            "promote": f"{item['what']} is verified in staging. Promote it to prod?",
            "review": f"{item['what']} waits for your review. Approve and merge it?"}[kind]
    return _question(qid, header, text, opts)


def _unavailable(ctx: _Ctx, state: dict) -> dict:
    names = ", ".join(nextscreen._SOURCES.get(u["source"], (u["source"],))[0] for u in state["unavailable"])
    return _question("unavailable", "Source", f"Could not read {names}. Try again?", [
        _option(ctx, "try-again", "Try again", "Reads the sources again.", then=ctx.call()),
        _option(ctx, "not-now", "Not now", "Does nothing; the screen shows what is missing.")])


def _all(state: dict, ctx: _Ctx, group: str | None, shown: list[dict]) -> list[dict]:
    qs: list[dict] = []
    if group == "stopped":
        qs += [_stopped(ctx, i) for i in shown]
    elif group == "specs":
        qs += _answers(ctx, [i for i in shown if i["kind"] == "answer"])
        drafts = [i for i in shown if i["kind"] == "approve"]
        if drafts:
            qs.append(_approve(ctx, drafts))
    elif group == "issues":
        qs.append(_triage(ctx, shown))
    elif group == "release":
        qs += [_release(ctx, i) for i in shown]
    if state.get("unavailable"):
        qs.append(_unavailable(ctx, state))
    return qs


def _page(n: int, of: int) -> dict:
    return {"n": n, "of": of, "text": f"page {n} of {of}" if of > 1 else ""}


def build(state: dict, *, shown_at: str, later=(), args=(), page: int = 1, show: str | None = None,
          choose: str | None = None, attended: bool = True) -> tuple[list[dict], dict]:
    """The questions of one page and the page (see the module docstring)."""
    if not attended:
        return [], _page(1, 1)
    ctx = _Ctx(shown_at, later, args, attended)
    group, shown, _also, _count = nextstate.groups(state, later)
    if choose == "approve":
        waiting = [i for i in state["items"] if i["id"] not in set(ctx.later) and i["kind"] == "approve"]
        if waiting:
            return _choose_approve(ctx, waiting, page)
    questions = _all(state, ctx, group, shown)
    if show:
        wanted = "approve" if show == "assumptions" else show.split(":", 1)[-1]
        questions = [q for q in questions if q["id"] == wanted]
        for q in questions:
            q["options"] = [o for o in q["options"] if o["id"] not in ("show-assumptions", "show-details")]
        return questions, _page(1, 1)
    of = max(1, -(-len(questions) // PER_PAGE))
    n = min(max(1, page), of)
    return questions[(n - 1) * PER_PAGE:n * PER_PAGE], _page(n, of)
