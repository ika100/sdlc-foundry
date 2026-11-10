"""cplat platform rules check [--only PATH ...] [--json] [--repo DIR]: every prompt rule classified, reasoned and marked (spec 168).

Every rule sentence of the plugin prompts has exactly one register entry (docs/rules/plugins/...) classed hard, practice,
experience or not a rule; hard, practice and experience sentences state a reason of at least 3 words; practices do not hide
behind a bare condition; hard rules are marked and enforced (or an intentional prose rule); every agent and command prompt
carries the statement once; retired entries are valid and gone from the prompt; the prompts stay within the baseline bytes.

`--only` limits the per-file checks to prompt files equal to or under PATH and their register files, and skips the two global
checks (hard-rule ceiling, bytes). Exit 0 pass, 1 a failure, 2 usage. The contract is
docs/specs/168-agent-rules-state-their-reason-and-can/design.md, `cplat platform rules check`.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import promptrules as pr
from promptrules import CLASSES, MARKER, REGISTER, STATEMENT

MAX_HARD = 20
_STATEMENT = re.compile(r"\s+".join(re.escape(w) for w in STATEMENT.split()))
_NEEDS_STATEMENT = re.compile(r"plugins/[^/]+/(agents|commands)/.+\.md")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’_-]*")
_ABOUT = "see docs/rules/README.md"


@dataclass(frozen=True)
class Failure:
    kind: str
    file: str
    line: int
    text: str
    message: str


@dataclass
class Result:
    failures: list[Failure] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    prompt_bytes: int = 0
    baseline_bytes: int = 0

    @property
    def ok(self) -> bool:
        return not self.failures


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _in_scope(rel: str, only: list[str] | None) -> bool:
    return only is None or any(rel == p or rel.startswith(p + "/") for p in only)


def _normalize(root: Path, only: list[str]) -> list[str]:
    out = []
    for item in only:
        p = Path(item)
        if p.is_absolute():
            try:
                p = p.relative_to(root)
            except ValueError:
                pass
        out.append(p.as_posix().removeprefix("./").rstrip("/"))
    return out


def _load_register(root: Path, fails: list[Failure]) -> pr.Register | None:
    """The register; one unreadable entries file is a failure, the others are still read (None: no register to check against)."""
    skipped: list[str] = []
    while True:
        try:
            if not skipped:
                return pr.load_register(root)
            with tempfile.TemporaryDirectory() as tmp:       # the register without the unreadable entries files
                dest = Path(tmp) / pr.RULES_DIR
                shutil.copytree(root / pr.RULES_DIR, dest)
                for rel in skipped:
                    (Path(tmp) / rel).unlink()
                return pr.load_register(Path(tmp))
        except pr.RegisterError as exc:
            if exc.file == REGISTER and exc.line == 0:
                fails.append(Failure("no-register", REGISTER, 0, "", "the register docs/rules/register.yml is missing"))
                return None
            fails.append(Failure("bad-entry", exc.file, exc.line, "", exc.message))
            if exc.file == REGISTER or exc.file in skipped:
                return None
            skipped.append(exc.file)


def _enforcement(value: str | None, root: Path) -> str | None:
    return pr.enforcement_error(value, root) if value else None


def _hard_table(reg: pr.Register, root: Path, fails: list[Failure]) -> None:
    for line, message in reg.problems:
        fails.append(Failure("bad-entry", REGISTER, line, "", message))
    for rule in reg.hard.values():
        for kind, message in rule.problems:
            fails.append(Failure(kind, REGISTER, rule.line, rule.key, message))
        if rule.problems and rule.enforced_by is None and rule.intentional_prose_rule is None:
            continue
        if rule.enforced_by is not None and rule.intentional_prose_rule is not None:
            fails.append(Failure("bad-entry", REGISTER, rule.line, rule.key,
                                 "a hard rule has `enforced_by` or `intentional_prose_rule`, not both"))
        elif rule.enforced_by is not None:
            error = pr.enforcement_error(rule.enforced_by, root)
            if error:
                fails.append(Failure("bad-enforcement", REGISTER, rule.line, rule.key, error))
        elif rule.intentional_prose_rule is None or len(_WORD.findall(rule.intentional_prose_rule)) < pr.MIN_REASON_WORDS:
            fails.append(Failure("no-enforcement", REGISTER, rule.line, rule.key,
                                 "a hard rule names an `enforced_by` cplat command or CI job, or an `intentional prose rule` "
                                 "of at least 3 words"))


def _entry_problems(entry: pr.Entry, fails: list[Failure]) -> None:
    for kind, message in entry.problems:
        fails.append(Failure(kind, entry.file, entry.line, entry.text, message))


def _check_prompt(rel: str, root: Path, reg: pr.Register, fails: list[Failure], counts: dict) -> int:
    """The per-file checks of one prompt and its entries; returns its number of rule sentences."""
    path = root / rel
    exists = path.is_file()
    text = path.read_text(encoding="utf-8") if exists else ""
    entries = reg.entries.get(rel, [])
    found = pr.sentences(rel, text) if exists else []
    entry_file = pr.entries_path(rel)
    for entry in entries:
        if entry.cls in CLASSES:
            counts["entries"][entry.cls] += 1
        _entry_problems(entry, fails)
    live = [(e, _collapse(e.text)) for e in entries if e.cls != "retired" and e.text.strip()]
    matched: set[int] = set()
    hard_lines: set[int] = set()
    rules = 0
    for s in found:
        hits = [e for e, t in live if t in s.text and s.rule]
        matched.update(id(e) for e in hits)
        if s.rule:
            rules += 1
        hard = [e for e in hits if e.cls == "hard"]
        if hard:
            hard_lines.add(id(s))
            if MARKER not in s.text:
                fails.append(Failure("no-marker", rel, s.line, s.text, f"a hard rule sentence carries `{MARKER}`"))
        elif MARKER in s.text:
            fails.append(Failure("stray-marker", rel, s.line, s.text, f"`{MARKER}` on a sentence no hard entry matches"))
        if not s.rule:
            continue
        if not hits:
            fails.append(Failure("no-entry", rel, s.line, s.text, "rule sentence has no register entry"))
            continue
        if len(hits) > 1:
            ids = ", ".join(e.id for e in hits)
            fails.append(Failure("ambiguous-entry", rel, s.line, s.text, f"rule sentence matched by more than one entry ({ids})"))
            continue
        entry = hits[0]
        if entry.cls in ("hard", "practice", "experience"):
            words = pr.reason_words(s.scope)
            if words is None:
                fails.append(Failure("no-reason", rel, s.line, s.text,
                                     "rule has no reason clause (so that, because, since, otherwise)"))
            elif words < pr.MIN_REASON_WORDS:
                fails.append(Failure("short-reason", rel, s.line, s.text, "the reason clause has fewer than 3 words"))
        if entry.cls in ("practice", "experience") and (cond := pr.condition(s.text)):
            fails.append(Failure("condition", rel, s.line, s.text,
                                 f"`{cond}` makes a practice a condition: state the purpose instead"))
    for entry in entries:
        if entry.cls == "retired":
            if entry.text.strip():
                want = _collapse(entry.text)
                for s in found:
                    if want in s.text:
                        fails.append(Failure("retired-present", rel, s.line, s.text,
                                             f"retired rule {entry.id} still occurs in the prompt"))
            error = _enforcement(entry.enforced_by, root)
            if error:
                fails.append(Failure("bad-retired", entry_file, entry.line, entry.text, error))
            continue
        if entry.text.strip() and id(entry) not in matched:
            fails.append(Failure("stale-entry", entry_file, entry.line, entry.text,
                                 f"entry {entry.id} matches no rule sentence of {rel}"
                                 + ("" if exists else " (the prompt is gone)")))
        if entry.cls == "hard" and entry.hard and entry.hard not in reg.hard:
            fails.append(Failure("unknown-hard", entry_file, entry.line, entry.text,
                                 f"`{entry.hard}` is no key of the `hard:` table of register.yml"))
        elif entry.cls in ("practice", "experience"):
            error = _enforcement(entry.enforced_by, root)
            if error:
                fails.append(Failure("bad-enforcement", entry_file, entry.line, entry.text, error))
    if exists and not pr.is_tombstone(text) and _NEEDS_STATEMENT.fullmatch(rel):
        hits = list(_STATEMENT.finditer(text))
        if not hits:
            fails.append(Failure("no-statement", rel, 1, "", "the prompt lacks the statement promptrules.STATEMENT"))
        elif len(hits) > 1:
            line = text.count("\n", 0, hits[1].start()) + 1
            fails.append(Failure("repeated-statement", rel, line, "", "the statement promptrules.STATEMENT stands more than once"))
    return rules


def check(root: Path, only: list[str] | None = None) -> Result:
    root = Path(root)
    only = _normalize(root, only) if only else None
    fails: list[Failure] = []
    counts: dict = {"rule_sentences": 0, "hard_rules": 0, "entries": dict.fromkeys(CLASSES, 0)}
    result = Result(fails, counts, pr.prompt_bytes(root) if (root / "plugins").is_dir() else 0, 0)
    reg = _load_register(root, fails)
    if reg is None:
        fails.sort(key=lambda f: (f.file, f.line, f.kind))
        return result
    result.baseline_bytes = reg.baseline_bytes or 0
    counts["hard_rules"] = len(reg.hard)
    _hard_table(reg, root, fails)
    for file, line, message in reg.bad_files:
        if only is None or any(file.startswith(f"{pr.RULES_DIR}/{p}") for p in only):
            fails.append(Failure("bad-entry", file, line, "", message))
    prompts = sorted({*pr.prompt_files(root), *reg.entries})
    for rel in prompts:
        if _in_scope(rel, only):
            counts["rule_sentences"] += _check_prompt(rel, root, reg, fails, counts)
    if only is None:
        if len(reg.hard) > MAX_HARD:
            fails.append(Failure("too-many-hard", REGISTER, reg.hard_line, "",
                                 f"{len(reg.hard)} distinct hard rules, at most {MAX_HARD} are allowed"))
        if reg.baseline_bytes is not None and result.prompt_bytes > reg.baseline_bytes:
            fails.append(Failure("bytes", REGISTER, reg.baseline_line, "",
                                 f"the prompts total {result.prompt_bytes} bytes, more than the baseline {reg.baseline_bytes}"))
    fails.sort(key=lambda f: (f.file, f.line, f.kind))
    return result


def render(result: Result) -> list[str]:
    if result.ok:
        return [f"OK: {result.counts['rule_sentences']} rule sentences classified, {result.counts['hard_rules']} hard rules; "
                f"prompts {result.prompt_bytes} bytes (baseline {result.baseline_bytes})"]
    lines = [f"FAIL {f.kind} {f.file}:{f.line}: {f.message}" + (f': "{f.text}"' if f.text else "") for f in result.failures]
    return [*lines, f"{len(result.failures)} failure(s); {_ABOUT}"]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat platform rules", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="verb", required=True)
    cp = sub.add_parser("check", help="check the prompt rules against the register")
    cp.add_argument("--only", action="append", metavar="PATH", help="only this prompt file or directory (repeatable)")
    cp.add_argument("--json", action="store_true")
    cp.add_argument("--repo", default=".")
    ns = ap.parse_args(argv)
    result = check(Path(ns.repo).resolve(), ns.only)
    if ns.json:
        print(json.dumps({"ok": result.ok, "failures": [asdict(f) for f in result.failures], "counts": result.counts,
                          "prompt_bytes": result.prompt_bytes, "baseline_bytes": result.baseline_bytes}, indent=2))
    else:
        for line in render(result):
            print(line)
    return 0 if result.ok else 1
