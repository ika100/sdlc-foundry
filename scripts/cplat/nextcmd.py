"""`cplat next` and `cplat next answer` (spec 192): the screen of where the person is in the delivery process and the
questions that go with it.

  cplat next [--json] [--ascii] [--repo-dir DIR] [--later ITEM]... [--judgement FILE]
             [--page N] [--show assumptions | --show details:<QID>] [--choose approve]
  cplat next answer --shown-at ISO --option ID [--item REF]...

`cplat next` reads the repo's sources (nothing is written), prints the screen (text) or the JSON document (`--json`,
schema 1: bar, screen, waiting, running, drafts, questions, page, unavailable, `how`) and exits 0 even when a source
fails. `CPLAT_HEADLESS=1` (an unattended run) leaves out the questions. ASCII mode comes from `--ascii` or from a
locale that is not UTF-8. `cplat next answer` records the person's answer as one run-store follow-up per `--item`
(`spec:<repo>:<spec id>` or `issue:<repo>:<number>`) and prints `recorded: <n> item(s), <m> min`.

Public API: `main(argv) -> int`, `HOW` (the procedure the session follows), `ascii_mode(environ)`.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import nextquestions
import nextscreen
import nextstate
import runs

SCHEMA = 1
MAX_MINUTES = 10
HOW = ("Print `screen` verbatim. Then ask `questions` with AskUserQuestion: each question's `header` and `question`, its "
       "`options` in order with `label` and `description`, the first marked \"(Recommended)\". After the person chose: "
       "run the option's `record`; with `then`, run that call and follow its `how`; otherwise run its `steps` in order "
       "(a slash command: follow that command; a `cplat` call: run it), print its `undo` lines verbatim, and run "
       "`cplat next --json` again with the same `--later` arguments. Nothing in `steps` runs before the person chose. "
       "Without questions, stop.")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # noqa: D102 - usage errors exit 2 with the message on stderr
        self.print_usage(sys.stderr)
        print(f"cplat next: {message}", file=sys.stderr)
        raise SystemExit(2)


def _next_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="cplat next", description="Where you are in the delivery process and what waits for you.")
    p.add_argument("--json", action="store_true")
    p.add_argument("--ascii", action="store_true")
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--later", action="append", default=[])
    p.add_argument("--judgement")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--show")
    p.add_argument("--choose", choices=["approve"])
    return p


def _answer_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="cplat next answer", description="Record the person's answer to a question of `cplat next`.")
    p.add_argument("--shown-at", required=True)
    p.add_argument("--option", required=True)
    p.add_argument("--item", action="append", default=[])
    return p


def ascii_mode(environ=None) -> bool:
    """True when the first set of LC_ALL, LC_CTYPE, LANG does not name UTF-8 (or none is set)."""
    environ = os.environ if environ is None else environ
    for name in ("LC_ALL", "LC_CTYPE", "LANG"):
        value = environ.get(name)
        if value:
            return not any(tag in value.lower() for tag in ("utf-8", "utf8"))
    return True


def _stamp(when: datetime.datetime) -> str:
    return when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _judgement(path: str | None) -> tuple[dict | None, bool]:
    """(parsed file, unreadable?): an unreadable or malformed file is ignored, with a line on the screen."""
    if not path:
        return None, False
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None, True
    return (doc, False) if isinstance(doc, dict) else (None, True)


def _drafts(shown: list[dict]) -> list[dict]:
    out = []
    for item in shown:
        draft = item.get("draft")
        if item.get("kind") in ("answer", "approve") and draft:
            out.append({"id": item["id"], "spec": draft["spec"], "title": draft["title"], "problem": draft["problem"],
                        "assumptions": draft["assumptions"], "pr": draft.get("pr")})
    return out


def _repeated(ns: argparse.Namespace) -> list[str]:
    """The arguments of this call that every `then` call repeats (`--later` is added per item by the questions)."""
    args = ["--ascii"] if ns.ascii else []
    if ns.judgement:
        args += ["--judgement", ns.judgement]
    if ns.repo_dir != ".":
        args += ["--repo-dir", ns.repo_dir]
    return args


def _next(argv: list[str]) -> int:
    ns = _next_parser().parse_args(argv)
    state = nextstate.collect(ns.repo_dir)
    shown_at = _stamp(runs.utcnow())
    attended = os.environ.get("CPLAT_HEADLESS") != "1"
    judgement, unreadable = _judgement(ns.judgement)
    rendered = nextscreen.render(state, ascii=ns.ascii or ascii_mode(), later=ns.later, judgement=judgement, show=ns.show,
                                 choose=ns.choose, actions=nextquestions.action_map(state, ns.later), judgement_error=unreadable)
    if not ns.json:
        print(rendered["screen"])
        return 0
    questions, page = nextquestions.build(state, shown_at=shown_at, later=ns.later, args=_repeated(ns), page=ns.page, show=ns.show,
                                          choose=ns.choose, attended=attended)
    _group, shown, _also, _later = nextstate.groups(state, ns.later)
    drafts = _drafts(shown)
    doc = {"schema": SCHEMA, "repo": state["repo"], "shape": state["shape"], "attended": attended, "shown_at": shown_at,
           "bar": rendered["bar"], "screen": rendered["screen"], "waiting": rendered["waiting"], "running": rendered["running"],
           "drafts": drafts, "judgement_wanted": bool(drafts) and not ns.judgement, "questions": questions, "page": page,
           "unavailable": state["unavailable"], "how": HOW}
    print(json.dumps(doc, indent=2))
    return 0


def _ref(text: str) -> tuple[str, str, str]:
    kind, _, rest = text.partition(":")
    repo, _, ident = rest.rpartition(":")
    if kind not in ("spec", "issue") or not repo or not ident or (kind == "issue" and not ident.isdigit()):
        raise ValueError(text)
    return kind, repo, ident


def _answer(argv: list[str]) -> int:
    ns = _answer_parser().parse_args(argv)
    try:
        shown = datetime.datetime.strptime(ns.shown_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        refs = [_ref(r) for r in ns.item]
    except ValueError as e:
        print(f"cplat next answer: bad value: {e}", file=sys.stderr)
        return 2
    now = runs.utcnow()
    minutes = min(MAX_MINUTES, max(0.0, (now - shown).total_seconds() / 60)) if refs else 0.0
    warning = runs.person_answer(shown_at=ns.shown_at, answered_at=_stamp(now), option=ns.option, refs=refs, minutes_total=minutes)
    print(f"recorded: {len(refs)} item(s), {minutes:.1f} min")
    if warning:
        print(warning)
    return 0


def main(argv: list[str]) -> int:
    try:
        return _answer(argv[1:]) if argv[:1] == ["answer"] else _next(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (1 if e.code else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
