"""Prompt rules (spec 168): scan the plugin prompts for rule sentences and load the register that classifies them.

Pure building blocks, no CLI and no printing; `rulescheck` (the check) and `house_rules` (the retire gate) use them.
The contract is docs/specs/168-agent-rules-state-their-reason-and-can/design.md, *Register files* and *Prompt scanning*.

Entry problems are data: every `Entry` and `HardRule` carries `problems`, a list of `(kind, message)` pairs, `kind` being
`bad-entry` or `bad-retired`, for the check to report with the file and line of the entry. An unreadable YAML file raises
`RegisterError(file, line, message)`; so does a missing register (line 0).
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from evalgate import PROMPT

REGISTER = "docs/rules/register.yml"
RULES_DIR = "docs/rules"
ENTRIES = "docs/rules/plugins"
MARKER = "**Hard rule:**"
STATEMENT = ("A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated "
             "purpose does not apply, depart from it and name each departure and its reason in one line of your report.")
RULE_WORDS = ("never", "always", "must", "do not", "don't", "don’t", "only", "unless", "except")
REASON_WORDS = ("so that", "because", "since", "otherwise")
CONDITIONS = ("only when", "only if", "unless", "except")
CLASSES = ("hard", "practice", "experience", "not a rule", "retired")
ENTRY_KEYS = ("id", "text", "class", "source", "hard", "enforced_by", "retired", "reason", "benchmark_runs")
HARD_KEYS = ("enforced_by", "intentional_prose_rule", "source")
MIN_REASON_WORDS = 3

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’_-]*")
_RULE = re.compile(r"\b(?:" + "|".join(w.replace(" ", r"\s+") for w in RULE_WORDS) + r")\b", re.I)
_REASON = re.compile(r"\b(?:" + "|".join(w.replace(" ", r"\s+") for w in REASON_WORDS) + r")\b", re.I)
_CONDITION = re.compile(r"\b(?:only\s+when|only\s+if|unless|except)\b", re.I)
_CODE = re.compile(r"(`+)(.+?)\1", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^\s*#{1,6}(?:\s|$)")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_QUOTE = re.compile(r"^\s*>+")
_END = re.compile(r"[.!?][)\"'*`]*\s+(?=[^a-z\s])")
_REFS = re.compile(r"\]\([^)]*\)|#\d+|\bspec\s+\d+|\bADR-\d+", re.I)
_SOURCE = re.compile(r"#\d+|spec \d+|ADR-\d+")
_ID = re.compile(r"R\d+")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_STATEMENT = re.compile(r"\s+".join(re.escape(w) for w in STATEMENT.split()))
_JOBS_END = re.compile(r"^\S")
_JOB = re.compile(r"^  ([A-Za-z0-9_][A-Za-z0-9_-]*):\s*(?:#.*)?$")
_JOB_NAME = re.compile(r"^    name:\s*(.+?)\s*$")


@dataclass(frozen=True)
class Sentence:
    file: str        # repo-relative prompt path
    line: int        # 1-based
    text: str        # raw, whitespace collapsed
    scope: str       # raw scope (item, row, heading, or the sentence)
    rule: bool


class RegisterError(Exception):
    """An unreadable register file: the file, the 1-based line (0 when unknown) and the message."""

    def __init__(self, file: str, line: int, message: str):
        super().__init__(f"{file}:{line}: {message}")
        self.file, self.line, self.message = file, line, message


@dataclass
class Entry:
    file: str                       # the entries file (repo-relative)
    line: int                       # 1-based line of the entry
    id: str = ""
    text: str = ""
    cls: str = ""
    source: str | None = None
    hard: str | None = None
    enforced_by: str | None = None
    retired: str | None = None      # ISO date
    reason: str | None = None
    benchmark_runs: list[str] | None = None
    problems: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class HardRule:
    key: str
    line: int
    enforced_by: str | None = None
    intentional_prose_rule: str | None = None
    source: str | None = None
    problems: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Register:
    hard: dict[str, HardRule]
    hard_line: int                              # line of the `hard:` key (0 when absent)
    baseline_commit: str
    baseline_bytes: int | None
    baseline_line: int
    entries: dict[str, list[Entry]]             # prompt path -> entries of its register file
    bad_files: list[tuple[str, int, str]]       # entries files mirroring no prompt path: (file, line, message)
    problems: list[tuple[int, str]] = field(default_factory=list)   # (line, message) of register.yml itself


# ---------------------------------------------------------------- prompt scanning

def _collapse(text: str) -> str:
    return " ".join(text.split())


def _blank(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def _frontmatter_end(lines: list[str]) -> int:
    """The number of lines the YAML frontmatter takes (0 without one)."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return i + 1
    return 0


def is_tombstone(text: str) -> bool:
    lines = text.splitlines()
    end = _frontmatter_end(lines)
    return any(re.match(r"moved-to\s*:", ln) for ln in lines[1:end - 1]) if end else False


def _visible(text: str) -> list[str]:
    """The lines of `text` with frontmatter, fenced code, comments and the statement blanked (line numbers kept)."""
    lines = text.splitlines()
    out = list(lines)
    for i in range(_frontmatter_end(lines)):
        out[i] = ""
    fence = ""
    for i in range(_frontmatter_end(lines), len(lines)):
        m = _FENCE.match(lines[i])
        if fence:
            if m and m.group(1) == fence:
                fence = ""
            out[i] = ""
        elif m:
            fence = m.group(1)
            out[i] = ""
    joined = _STATEMENT.sub(lambda m: _blank(m.group(0)), _COMMENT.sub(lambda m: _blank(m.group(0)), "\n".join(out)))
    return joined.split("\n")


def _mask(text: str) -> str:
    """`text` with every inline code span replaced by `x` of the same length: one word, never a rule or reason word."""
    return _CODE.sub(lambda m: "x" * len(m.group(0)), text)


def _spans(masked: str) -> list[tuple[int, int]]:
    """The (start, end) of every sentence of `masked`, whitespace around them left out."""
    spans, start = [], 0
    for m in _END.finditer(masked):
        end = m.start() + len(m.group(0).rstrip())
        spans.append((start, end))
        start = m.end()
    spans.append((start, len(masked)))
    return [(a, b) for a, b in spans if masked[a:b].strip()]


def _blocks(lines: list[str]) -> list[tuple[str, list[tuple[int, str]]]]:
    """(kind, [(line number, text)]) per block; kind is `item`, `row`, `heading` or `paragraph`."""
    blocks: list[tuple[str, list[tuple[int, str]]]] = []
    cur: list[tuple[int, str]] = []
    kind = ""

    def flush() -> None:
        nonlocal cur, kind
        if cur:
            blocks.append((kind, cur))
        cur, kind = [], ""

    for n, raw in enumerate(lines, 1):
        line = _QUOTE.sub("", raw, count=1) if _QUOTE.match(raw) else raw
        if not line.strip():
            flush()
        elif _HEADING.match(line):
            flush()
            blocks.append(("heading", [(n, line.strip().lstrip("#").strip())]))
        elif line.lstrip().startswith("|"):
            flush()
            blocks.append(("row", [(n, line.strip())]))
        elif _ITEM.match(line):
            flush()
            cur, kind = [(n, _ITEM.sub("", line, count=1).strip())], "item"
        else:
            if not cur:
                kind = "paragraph"
            cur.append((n, line.strip()))
    flush()
    return blocks


def sentences(rel: str, text: str) -> list[Sentence]:
    found: list[Sentence] = []
    for kind, block in _blocks(_visible(text)):
        starts, pos = [], 0
        for _, t in block:
            starts.append(pos)
            pos += len(t) + 1
        raw = "\n".join(t for _, t in block)
        masked = _mask(raw)
        scope = _collapse(raw)
        for a, b in _spans(masked):
            while raw[a].isspace():
                a += 1
            line = block[max(i for i, s in enumerate(starts) if s <= a)][0]
            sentence = _collapse(raw[a:b])
            found.append(Sentence(rel, line, sentence, scope if kind != "paragraph" else sentence,
                                  bool(_RULE.search(masked[a:b]))))
    return found


def _count_words(masked_clause: str) -> int:
    return len(_WORD.findall(_REFS.sub(" ", masked_clause)))


def _clauses(scope: str) -> list[tuple[int, str]]:
    """(word count, raw text) of the text after each reason word up to the end of its sentence."""
    masked = _mask(scope)
    spans = _spans(masked)
    clauses = []
    for m in _REASON.finditer(masked):
        end = next((b for a, b in spans if a <= m.start() < b), len(masked))
        clauses.append((_count_words(masked[m.end():end]), _collapse(scope[m.end():end])))
    return clauses


def reason_words(scope: str) -> int | None:
    """The words of the longest reason clause of `scope`; None when it has no reason word at all."""
    clauses = _clauses(scope)
    return max(n for n, _ in clauses) if clauses else None


def reason_clause(scope: str) -> str | None:
    """The longest clause of `scope` with at least 3 words after the references are removed, raw text, else None."""
    good = [c for c in _clauses(scope) if c[0] >= MIN_REASON_WORDS]
    return max(good, key=lambda c: c[0])[1] if good else None


def condition(sentence: str) -> str | None:
    m = _CONDITION.search(_mask(sentence))
    return _collapse(sentence[m.start():m.end()]) if m else None


def prompt_files(root: Path) -> list[str]:
    base = Path(root)
    return sorted(p.relative_to(base).as_posix() for p in (base / "plugins").rglob("*.md")
                  if PROMPT.match(p.relative_to(base).as_posix()))


def prompt_bytes(root: Path) -> int:
    return sum((Path(root) / rel).stat().st_size for rel in prompt_files(root))


def entries_path(prompt_rel: str) -> str:
    return f"{RULES_DIR}/{prompt_rel.removesuffix('.md')}.yml"


def prompt_path(entries_rel: str) -> str | None:
    """The prompt a register file belongs to, None when the path mirrors no prompt path pattern."""
    head = RULES_DIR + "/"
    if not (entries_rel.startswith(head) and entries_rel.endswith(".yml")):
        return None
    rel = entries_rel[len(head):-len(".yml")] + ".md"
    return rel if PROMPT.match(rel) else None


# ---------------------------------------------------------------- register

def _load(rel: str, text: str) -> tuple[object, yaml.Node | None]:
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise RegisterError(rel, mark.line + 1 if mark else 0, f"unreadable YAML: {getattr(exc, 'problem', None) or exc}") from exc
    return data, node


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _entry(rel: str, item: object, line: int, seen: set[str]) -> Entry:
    entry = Entry(rel, line)
    bad = entry.problems
    if not isinstance(item, dict):
        bad.append(("bad-entry", "an entry is a mapping with id, text and class"))
        return entry
    for key in item:
        if key not in ENTRY_KEYS:
            bad.append(("bad-entry", f"unknown key `{key}`"))
    entry.id = str(item.get("id") or "")
    if not _ID.fullmatch(entry.id):
        bad.append(("bad-entry", "`id` is required and has the form R<n>"))
    elif entry.id in seen:
        bad.append(("bad-entry", f"duplicate id {entry.id}"))
    seen.add(entry.id)
    entry.text = _text(item.get("text")) or ""
    if not entry.text:
        bad.append(("bad-entry", "`text` is required"))
    entry.cls = str(item.get("class") or "")
    if entry.cls not in CLASSES:
        bad.append(("bad-entry", f"`class` is one of {', '.join(CLASSES)}"))
    source = item.get("source")
    if source is not None:
        if isinstance(source, str) and all(_SOURCE.fullmatch(s) for s in source.split(", ")):
            entry.source = source
        else:
            bad.append(("bad-entry", "`source` is refs (#<n>, spec <nnn>, ADR-<nnn>) separated by `, `"))
    for key, only in (("hard", "hard"), ("retired", "retired"), ("reason", "retired"), ("benchmark_runs", "retired")):
        if key in item and entry.cls in CLASSES and entry.cls != only:
            bad.append(("bad-entry", f"`{key}` belongs to class {only} only"))
    if "enforced_by" in item and entry.cls in ("hard", "not a rule"):
        bad.append(("bad-entry", f"`enforced_by` is not allowed on class {entry.cls}"))
    if entry.cls == "hard":
        entry.hard = _text(item.get("hard"))
        if not entry.hard:
            bad.append(("bad-entry", "a hard rule names its `hard` key of register.yml"))
    if "enforced_by" in item:
        entry.enforced_by = _text(item.get("enforced_by"))
        if not entry.enforced_by and entry.cls not in ("hard", "not a rule"):
            bad.append(("bad-entry", "`enforced_by` is a cplat command or ci:<job>"))
    if entry.cls == "retired":
        _retired(entry, item)
    elif isinstance(item.get("benchmark_runs"), list):
        entry.benchmark_runs = [str(x) for x in item["benchmark_runs"]]
    return entry


def _retired(entry: Entry, item: dict) -> None:
    date = item.get("retired")
    if isinstance(date, (datetime.date, datetime.datetime)):
        date = date.isoformat()[:10]
    if isinstance(date, str) and _DATE.fullmatch(date):
        entry.retired = date
    else:
        entry.problems.append(("bad-retired", "`retired` is the ISO date the rule was retired"))
    reason = item.get("reason")
    if isinstance(reason, str) and len(_WORD.findall(reason)) >= MIN_REASON_WORDS:
        entry.reason = reason
    else:
        entry.problems.append(("bad-retired", "`reason` says in at least 3 words why the rule no longer holds"))
    runs = item.get("benchmark_runs")
    if runs is not None:
        if isinstance(runs, list) and all(isinstance(r, str) and r for r in runs):
            entry.benchmark_runs = list(runs)
        else:
            entry.problems.append(("bad-entry", "`benchmark_runs` is a list of run ids"))


def load_entries(rel: str, text: str) -> list[Entry]:
    """The entries of one register file (`rel` is its repo-relative path); RegisterError on unreadable YAML."""
    data, node = _load(rel, text)
    if data is None:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("rules"), (list, type(None))):
        raise RegisterError(rel, 1, "a register file is `rules:` followed by a list of entries")
    nodes = []
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            if key.value == "rules" and isinstance(value, yaml.SequenceNode):
                nodes = [n.start_mark.line + 1 for n in value.value]
    seen: set[str] = set()
    items = data.get("rules") or []
    return [_entry(rel, item, nodes[i] if i < len(nodes) else 1, seen) for i, item in enumerate(items)]


def _hard_table(table: object, node: yaml.Node | None) -> dict[str, HardRule]:
    rules: dict[str, HardRule] = {}
    lines = {}
    if isinstance(node, yaml.MappingNode):
        lines = {k.value: k.start_mark.line + 1 for k, _ in node.value}
    if not isinstance(table, dict):
        return rules
    for key, fields in table.items():
        rule = HardRule(str(key), lines.get(key, 1))
        if not isinstance(fields, dict):
            rule.problems.append(("bad-entry", "a hard rule is a mapping with enforced_by or intentional_prose_rule"))
        else:
            for k, v in fields.items():
                if k not in HARD_KEYS:
                    rule.problems.append(("bad-entry", f"unknown key `{k}`"))
                elif k in ("enforced_by", "intentional_prose_rule", "source"):
                    setattr(rule, k, v if isinstance(v, str) else None)
        rules[str(key)] = rule
    return rules


def load_register(root: Path) -> Register:
    base = Path(root)
    path = base / REGISTER
    if not path.is_file():
        raise RegisterError(REGISTER, 0, "the register is missing")
    data, node = _load(REGISTER, path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RegisterError(REGISTER, 1, "the register is a mapping with schema, baseline and hard")
    problems: list[tuple[int, str]] = []
    top = {k.value: (k.start_mark.line + 1, v) for k, v in node.value} if isinstance(node, yaml.MappingNode) else {}
    if data.get("schema") != 1:
        problems.append((top.get("schema", (1,))[0], "`schema` is 1"))
    baseline = data.get("baseline") if isinstance(data.get("baseline"), dict) else {}
    size = baseline.get("prompt_bytes")
    if not isinstance(baseline.get("commit"), (str, int)) or isinstance(size, bool) or not isinstance(size, int):
        problems.append((top.get("baseline", (1,))[0], "`baseline` has `commit` and `prompt_bytes`"))
    hard_node = top["hard"][1] if "hard" in top else None
    if not isinstance(data.get("hard"), dict):
        problems.append((top.get("hard", (1,))[0], "`hard` is a mapping of the distinct hard rules"))
    entries: dict[str, list[Entry]] = {}
    bad_files: list[tuple[str, int, str]] = []
    for file in sorted((base / ENTRIES).rglob("*.yml")) if (base / ENTRIES).is_dir() else []:
        rel = file.relative_to(base).as_posix()
        prompt = prompt_path(rel)
        if prompt is None:
            bad_files.append((rel, 1, "this register file mirrors no prompt path (plugins/<p>/<kind>/<path>.md)"))
            continue
        entries[prompt] = load_entries(rel, file.read_text(encoding="utf-8"))
    return Register(_hard_table(data.get("hard"), hard_node), top.get("hard", (0,))[0], str(baseline.get("commit", "")),
                    size if isinstance(size, int) and not isinstance(size, bool) else None, top.get("baseline", (0,))[0],
                    entries, bad_files, problems)


# ---------------------------------------------------------------- enforcement

def workflow_jobs(root: Path) -> dict[str, str]:
    """Job id -> its `name:` (or the id) of every workflow; a line pattern, because the templates are Jinja."""
    base = Path(root)
    files = [*(base / ".github/workflows").glob("*.yml")]
    for pattern in ("templates/*/.github/workflows/*.yml", "templates/*/.github/workflows/*.yml.jinja"):
        files += base.glob(pattern)
    jobs: dict[str, str] = {}
    for file in sorted(files):
        in_jobs, job = False, ""
        for line in file.read_text(encoding="utf-8").splitlines():
            if _JOBS_END.match(line):
                in_jobs, job = line.startswith("jobs:"), ""
            elif in_jobs and (m := _JOB.match(line)):
                job = m.group(1)
                jobs.setdefault(job, job)
            elif in_jobs and job and (m := _JOB_NAME.match(line)):
                jobs[job] = m.group(1).strip("\"'")
    return jobs


def enforcement_error(value: str, root: Path) -> str | None:
    """Why `value` is no enforcement (a cplat command or a CI job), None when it is one."""
    value = value.strip()
    if value.startswith("ci:"):
        job = value[3:].strip()
        return None if job in workflow_jobs(root) else f"`{job}` is no job id of any workflow"
    words = value.split()
    if len(words) < 2 or words[0] != "cplat":
        return f"`{value}` is neither `cplat <command> …` nor `ci:<job>`"
    import cplat
    noun = words[1]
    if noun in cplat.PLUMBING:
        return None
    if noun in cplat.NOUNS:
        if len(words) > 2 and words[2] in cplat.NOUNS[noun]:
            return None
        return f"`cplat {noun}` has no verb `{words[2] if len(words) > 2 else ''}`"
    return f"`cplat {noun}` is no cplat command"
