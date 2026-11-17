"""Spec 193 (AC-193.4): the person's answer to a stopped unit, written where the work goes on (design.md `answer`).

  answer(repo, slug, key, text, question=None) -> list[str]   the output lines of `cplat dispatch answer <item> --answer TEXT`

The unit of `key` must have ended `escalated`. The question is question `question` (1-based) of the unit's ship state (the live one
or the newest archive in the worktree's git dir), else the unit's reason. A spec item gets the answer as an assumption the person
decided in `## Assumptions` of its spec in the worktree: when the criteria hash equals that on `origin/main` the amendment is
approved in the Changelog, committed and (once every question has an answer) the item goes on; else the spec goes back to draft with
its pull request. An issue item gets the answer as a comment and loses `needs-decision`. `git` and `gh` are the seams of
`dispatch_units` and `spec_pr` (tests replace them).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import dispatch_state as ds
import dispatch_units as du
import spec as specmod
import spec_pr
from core import PlatformError

MARK = "<!-- cplat-dispatch-answer -->"
SPEC_FILE = "docs/specs/{id}/spec.md"


def _stop_state(worktree: Path) -> dict | None:
    """The ship state of the stopped run: the live one, else the newest archive (the glob `ship.revive_escalated` uses)."""
    gd = ds.unit_git_dir(worktree)
    files = [gd / "cplat-ship.json", *reversed(sorted(gd.glob("cplat-ship-*-[0-9]*.json")))]
    for f in files:
        try:
            doc = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            return doc
    return None


def _questions(unit: dict, state: dict | None) -> list[str]:
    qs = [str(q.get("text") or "") if isinstance(q, dict) else str(q) for q in (state or {}).get("questions") or []]
    return [q for q in qs if q] or [str(unit.get("reason") or "the stop")]


def _add_assumption(body: str, bullet: str) -> str:
    m = re.search(r"^## +Assumptions\s*$", body, re.M)
    if not m:
        head = re.search(r"^## +Changelog\s*$", body, re.M)
        block = f"## Assumptions\n\n{bullet}\n\n"
        return body[:head.start()] + block + body[head.start():] if head else body.rstrip("\n") + f"\n\n{block}".rstrip("\n") + "\n"
    nxt = specmod.SECTION.search(body, m.end())
    end = nxt.start() if nxt else len(body)
    kept = body[m.end():end].rstrip("\n")
    return body[:m.end()] + kept + f"\n{bullet}\n" + ("\n" + body[end:] if nxt else "")


def _hash_of(text: str) -> str | None:
    m = specmod.FRONT.match(text)
    return specmod.Spec(Path("."), {}, m.group(2)).ac_hash() if m else None


def _remove_label(repo: Path, numbers: list[int]) -> None:
    for n in numbers:
        du.gh(["issue", "edit", str(n), "--remove-label", du.NEEDS_DECISION], cwd=repo)


def _answer_issue(repo: Path, slug: str, key: str, unit: dict, text: str) -> list[str]:
    n = int(str(unit["item"]).lstrip("#"))
    body = f'{MARK}\nAnswer of the person to the stop of {unit["unit"]}: "{text}"'
    if du.gh(["issue", "comment", str(n), "--body", body], cwd=repo) is None:
        raise PlatformError(f"the comment on #{n} could not be written")
    _remove_label(repo, [n])
    ds.resume_item(slug, key)
    return [f"answered: #{n}"]


def _answer_spec(repo: Path, slug: str, key: str, worktree: Path, unit: dict, state: dict | None, text: str, k: int | None) -> list[str]:
    spec_id = str(unit["spec"])
    rel = SPEC_FILE.format(id=spec_id)
    path = worktree / rel
    qs = _questions(unit, state)
    has_questions = bool((state or {}).get("questions"))
    done = {str(a) for a in unit.get("answers") or {}}
    if has_questions:
        if k is None:
            k = next((i for i in range(1, len(qs) + 1) if str(i) not in done), 1)
        if not 1 <= k <= len(qs):
            raise ds.ItemRefused(f"{unit['item']} has {len(qs)} question(s), not question {k}")
        akey, asked = str(k), qs[k - 1]
    else:
        akey, asked = "reason", qs[0]
    if not path.is_file():
        raise PlatformError(f"{rel} is not in {worktree}")
    before = du.git(["show", f"HEAD:{rel}"], cwd=worktree, check=False)
    main = du.git(["show", f"origin/main:{rel}"], cwd=worktree, check=False) or before
    unit_name = str(unit["unit"])
    bullet = f'- Decided by the user ({ds.today()}, stop of {unit_name}): {asked} Answer: "{text}"'
    meta, body = specmod.load(path)
    specmod.save(path, meta, _add_assumption(body, bullet))
    answers = {**(unit.get("answers") or {}), akey: text}
    du.update_unit(worktree, lambda u: u.update(answers=answers))
    spec = specmod.read(path.parent)
    unchanged = spec.ac_hash() == _hash_of(main)
    if unchanged:
        specmod.save(path, spec.meta, specmod.add_changelog(spec.body, f'answer to the stop of {unit_name} approved by the user: "{text}"'))
        msg = f"docs(spec): answer to the stop of {spec_id}"
    else:
        specmod.set_status(spec, "draft", "the answer changes criteria")
        spec = specmod.read(path.parent)
        specmod.save(path, spec.meta, specmod.add_changelog(spec.body, f'answer of the user changes criteria: "{text}"; back to approval'))
        msg = f"docs(spec): the answer to the stop of {spec_id} changes criteria"
    spec = specmod.read(path.parent)
    n = spec.number
    if not unchanged:
        spec_pr._git_ok(worktree, "add", "--", f"docs/specs/{spec_id}")
        spec_pr._git_ok(worktree, "commit", "-s", "-m", msg, "--", f"docs/specs/{spec_id}")
        pr = spec_pr.publish(worktree, spec)
        ds.resume_item(slug, key)
        return [f"back to approval: spec {n} (PR #{pr['pr']})"]
    spec_pr._git_ok(worktree, "add", "--", f"docs/specs/{spec_id}")
    spec_pr._git_ok(worktree, "commit", "-s", "-m", msg, "--", f"docs/specs/{spec_id}")
    sha = du.git(["rev-parse", "HEAD"], cwd=worktree)
    out: list[str] = []
    if len(answers) >= (len(qs) if has_questions else 1):
        ds.resume_item(slug, key)
        _remove_label(repo, du._open_issues(repo, du._issues_of(unit)))
        phase = (state or {}).get("phase") or "the start"
        out.append(f"answered: spec {n}; it goes on from {phase}")
    else:
        out.append(f"answered {len(answers)} of {len(qs)}: spec {n} waits for the other answers")
    out.append(f"Undo: git -C {worktree} revert --no-edit {sha}")
    return out


def answer(repo: Path, slug: str, key: str, text: str, question: int | None = None) -> list[str]:
    repo = Path(repo)
    worktree = ds.worktree_path(slug, key)
    unit = ds.read_unit(worktree) if worktree.is_dir() else None
    ref = f"spec {key.split('-', 1)[1]}" if key.startswith("spec-") else f"#{key.split('-', 1)[1]}"
    if not unit or unit.get("status") != "escalated":
        raise ds.ItemRefused(f"{ref} has no stop to answer")
    if unit.get("kind") == "fix":
        return _answer_issue(repo, slug, key, unit, text)
    return _answer_spec(repo, slug, key, worktree, unit, _stop_state(worktree), text, question)
