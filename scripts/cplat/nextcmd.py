"""`cplat next` and `cplat next answer` (spec 192): the screen of where the person is in the delivery process and the
questions that go with it.

  cplat next [--json] [--ascii] [--repo-dir DIR] [--later ITEM]... [--judgement FILE]
             [--page N] [--choose approve] [--watch S --after SEQ]
             [--show assumptions | --show details:<QID> | --show log:<KEY> | --show raise-budget:<N>]
  cplat next answer --shown-at ISO --option ID [--item REF]...

`cplat next` reads the repo's sources (nothing is written), prints the screen (text) or the JSON document (`--json`,
schema 1: bar, screen, waiting, running, drafts, questions, page, unavailable, `how`; spec 193 adds `build` and
`judge_items`) and exits 0 even when a source fails. `CPLAT_HEADLESS=1` (an unattended run) leaves out the questions. ASCII mode comes from `--ascii` or from a
locale that is not UTF-8. `cplat next answer` records the person's answer as one run-store follow-up per `--item`
(`spec:<repo>:<spec id>` or `issue:<repo>:<number>`) and prints `recorded: <n> item(s), <m> min`.

Spec 193: `--watch S --after SEQ` first waits (read-only, polling the dispatcher state and the mtime of its `needs.json`
every 2 s) until a dispatcher event with `seq` > SEQ exists, `needs.json` changed, the build loop is gone or S seconds
passed, then prints as without it. `--judgement` also reads `items` (per `issue-<n>` / `spec-<NNN>` key: `you_get`,
`what_happened`, `why_ask`); `judge_items` lists the queue entries, running items and stops that still lack one, and
`judgement_wanted` is true while `drafts` or `judge_items` is not empty and no `--judgement` was given.

`cplat next` returns within 60 s whatever a source does (20 s per source, `nextstate`; spec 203): before it reads, fd 0
points at /dev/null and `GIT_TERMINAL_PROMPT=0`, `GH_PROMPT_DISABLED=1` and (when unset) `GIT_SSH_COMMAND=ssh -o
BatchMode=yes` keep every program it calls from asking; when a source was abandoned it ends with `hard_exit(0)`.

Public API: `main(argv) -> int`, `hard_exit(code)`, `HOW` (the procedure the session follows), `ascii_mode(environ)`,
`judge_items(state, judgement) -> list[dict]`, `sleep`/`clock` (the replaceable time seams of `--watch`).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

import dispatch_state
import nextbuildscreen
import nextquestions
import nextscreen
import nextstate
import runs

SCHEMA = 1
MAX_MINUTES = 10
WATCH_POLL = 2
TEXT_LIMIT = 600
sleep = time.sleep
clock = time.monotonic
HOW = ("Print `screen` verbatim. Then ask `questions` with AskUserQuestion: each question's `header` and `question`, its "
       "`options` in order with `label` and `description`, the first marked \"(Recommended)\". After the person chose: "
       "run the option's `record`; with `then`, run that call and follow its `how`; otherwise run its `steps` in order "
       "(a slash command: follow that command; a `cplat` call: run it), print its `undo` lines verbatim, and run "
       "`cplat next --json` again with the same `--later` arguments. Nothing in `steps` runs before the person chose. "
       "Without questions, stop. "
       "An option with `input`: before running it, ask its `input.prompt` and wait for the typed value; put it in place of "
       "`<name>` in its `steps`, `then` and `undo`. An answer the person types for a question with `other`: when it changes "
       "an acceptance criterion, change that criterion in `other.spec` as asked first; then run `other.steps` with "
       "`<answer>` replaced by the typed text, and go on as after an option. Print the output of a `cplat dispatch` step whole.")


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
    p.add_argument("--watch", type=int, default=0)
    p.add_argument("--after", type=int, default=0)
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


def hard_exit(code: int) -> None:
    """End the process at once (flushed output): an abandoned source's thread may still hold it. The test seam."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def _no_input() -> None:
    """No program `cplat next` calls may wait for input, a password or a confirmation (spec 203)."""
    fd = os.open(os.devnull, os.O_RDONLY)
    try:
        os.dup2(fd, 0)
    finally:
        os.close(fd)
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    os.environ["GH_PROMPT_DISABLED"] = "1"
    os.environ.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _watch(repo_dir: str, seconds: int, after: int) -> None:
    """Wait (read-only) for a dispatcher event after `after`, a change of `needs.json`, the end of the build loop or `seconds`."""
    slug = dispatch_state.slug_of(repo_dir)
    needs = dispatch_state.needs_path(slug)
    first, started = _mtime(needs), clock()
    while True:
        events = dispatch_state.load(slug).get("events") or []
        if any(int(e.get("seq") or 0) > after for e in events) or _mtime(needs) != first:
            return
        if not dispatch_state.loop_alive(slug) or clock() - started >= seconds:
            return
        sleep(min(WATCH_POLL, max(0.0, seconds - (clock() - started))))


def _clip(text: object) -> str:
    return " ".join(str(text or "").split())[:TEXT_LIMIT]


def judge_items(state: dict, judgement: dict | None) -> list[dict]:
    """The queue entries and running items without a `you_get`, and the dispatcher stops without a `what_happened` (a decision
    also without `why_ask`), each `{key, ref, title, text, wants}` (design.md)."""
    build, given = state.get("build") or {}, nextbuildscreen.given_of(judgement)
    found: dict[str, dict] = {}

    def want(key: str | None, ref: str, title: str, text: str, field: str) -> None:
        if key and not str((given.get(key) or {}).get(field) or "").strip():
            entry = found.setdefault(key, {"key": key, "ref": ref, "title": title, "text": _clip(text), "wants": []})
            entry["wants"].append(field)

    for q in build.get("queue") or []:
        want(q["key"], q["ref"], q.get("title") or "", q.get("title") or "", "you_get")
    for r in build.get("running") or []:
        want(r["key"], r["ref"], r.get("what") or "", r.get("what") or "", "you_get")
    for item in state.get("items") or []:
        stop = item.get("stop") or {}
        if stop.get("kind") not in ("decision", "failure") or not stop.get("key"):
            continue
        open_q = next((q["text"] for i, q in enumerate(stop.get("questions") or [], 1) if i not in (stop.get("answered") or [])), "")
        text = " ".join(t for t in (stop.get("reason") or item.get("reason"), open_q) if t)
        args = (stop["key"], stop["ref"], item.get("what") or "", text)
        want(*args, "what_happened")
        if stop["kind"] == "decision":
            want(*args, "why_ask")
    return list(found.values())


def _next(argv: list[str]) -> int:
    ns = _next_parser().parse_args(argv)
    _no_input()
    if ns.watch > 0:
        try:
            _watch(ns.repo_dir, ns.watch, ns.after)
        except Exception:  # noqa: BLE001 - a state that cannot be read ends the wait, the screen says the rest
            pass
    state = nextstate.collect(ns.repo_dir)
    code = _print(ns, state)
    if state.get("abandoned"):
        hard_exit(code)
    return code


def _print(ns: argparse.Namespace, state: dict) -> int:
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
    judge = judge_items(state, judgement)
    doc = {"schema": SCHEMA, "repo": state["repo"], "shape": state["shape"], "attended": attended, "shown_at": shown_at,
           "bar": rendered["bar"], "screen": rendered["screen"], "waiting": rendered["waiting"], "running": rendered["running"],
           "drafts": drafts, "judgement_wanted": bool(drafts or judge) and not ns.judgement, "questions": questions, "page": page,
           "unavailable": state["unavailable"], "build": state.get("build"), "judge_items": judge, "how": HOW}
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
