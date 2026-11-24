"""The briefing of a unit session: the sections of the build instructions and the unit-mode reference that one unit needs (spec 211).

Cut at print time by heading key from one mapping (`MAPPING`); no slice is stored. Pure text work: no git, no run state.
`problems` is the guard `cplat platform rules check` runs: a mapped heading that is gone, a section that belongs to no unit,
a reference a briefing cannot resolve, a briefing without its general part. The contract is
docs/specs/211-unit-sessions-start-with-their/design.md, section 1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import core
from core import PlatformError

PLUGIN_ROOT = core.PLATFORM_ROOT / "plugins" / "component"
BUILD_FILE = "commands/build.md"
UNIT_FILE = "references/unit-mode.md"
KNOWN_UNITS = ("plan", "red-tests", "batch:<id>,<id>…", "task:<id>", "verification", "land")
GENERAL = ("cplat", "Rules")
MAPPING = {
    "plan": (),
    "red-tests": ("Phase 0", "Phase 1"),
    "batch": ("Phase 0", "Phase 2", "2.1", "2.2", "2.3", "2.4", "2.4a"),
    "task": ("Phase 0", "Phase 2", "2.1", "2.3", "2.4", "2.4a"),
    "verification": ("Phase 0", "2.5", "2.6", "Phase 3", "Phase 4", "Phase 5", "Phase 6"),
    "land:build": ("Phase 0", "Phase 7"),
    "land:ship": (),
}

_VAR = "${CLAUDE_PLUGIN_ROOT}"
_HEAD = re.compile(r"^(#{2,3}) +(.*)$")
_PHASE_REF = re.compile(r"\bPhase (\d+)\b")
_NUMBER_REF = re.compile(r"(?<![\w.])(\d+\.\d+a?)(?![\w.])")
_PERMISSIONS = "**Permissions:**"
_GENERAL_OPENER = "A rule marked **Hard rule:**"
_UNIT_RULES = "Rules for every unit"
_FALLBACK = "Full build instructions, for a step this briefing lacks:"
_BUILD_REL = "plugins/component/commands/build.md"
_PROBLEM_UNITS = (("plan", "ship"), ("plan", "build"), ("red-tests", "build"), ("batch:a,b", "build"), ("batch:a,b", "ship"),
                  ("task:a", "build"), ("task:a", "ship"), ("verification", "build"), ("verification", "ship"),
                  ("land", "build"), ("land", "ship"))


class UnknownUnit(PlatformError):
    def __init__(self, unit: str):
        super().__init__(f"unknown unit '{unit}'; known units: {', '.join(KNOWN_UNITS)}")


class BriefingUnavailable(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Section:
    key: str
    level: int
    line: int
    text: str


@dataclass(frozen=True)
class Problem:
    kind: str
    file: str
    line: int
    text: str
    message: str


def kind(unit: str, command: str) -> str:
    if unit in ("plan", "red-tests", "verification"):
        return unit
    if unit == "land":
        return "land:build" if command == "build" else "land:ship"
    name, _, rest = unit.partition(":")
    ids = rest.split(",")
    if name == "batch" and all(ids):
        return "batch"
    if name == "task" and rest and len(ids) == 1 and ids[0]:
        return "task"
    raise UnknownUnit(unit)


def heading_key(heading_line: str) -> str:
    text = _HEAD.match(heading_line).group(2)
    m = re.match(r"(Phase \d+)\b", text) or re.match(r"(\d+\.\d+a?)\b", text)
    return m.group(1) if m else text.strip()


def sections(text: str) -> list[Section]:
    out: list[Section] = []
    key, level, start, buf = None, 0, 0, []

    def close() -> None:
        if key is not None:
            out.append(Section(key, level, start, "\n".join(buf).rstrip()))
    for n, line in enumerate(text.splitlines(), 1):
        m = _HEAD.match(line)
        if m:
            close()
            key, level, start, buf = heading_key(line), len(m.group(1)), n, [line]
        elif key is not None:
            buf.append(line)
    close()
    return out


def _read(root: Path, rel: str) -> str:
    path = root / rel
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BriefingUnavailable(f"cannot read {path}: {exc}") from exc


def _paragraph(text: str, opener: str) -> str | None:
    return next((p.strip("\n") for p in text.split("\n\n") if p.startswith(opener)), None)


def _row(unit_text: str, mapping_key: str) -> str | None:
    base = mapping_key.split(":")[0]
    for line in unit_text.splitlines():
        if line.startswith(f"| `{base}`") or line.startswith(f"| `{base}:"):
            return line
    return None


def _wanted(mapping_key: str) -> set[str]:
    return {*GENERAL, *MAPPING[mapping_key]}


def build(unit: str, command: str, root: Path | None = None) -> str:
    mapping_key = kind(unit, command)
    root = Path(root) if root is not None else PLUGIN_ROOT
    build_text, unit_text = _read(root, BUILD_FILE), _read(root, UNIT_FILE)
    build_path, unit_path = root / BUILD_FILE, root / UNIT_FILE
    permissions = _paragraph(unit_text, _PERMISSIONS)
    if permissions is None:
        raise BriefingUnavailable(f'no "{_PERMISSIONS}" paragraph in {unit_path}')
    row = _row(unit_text, mapping_key)
    if row is None:
        raise BriefingUnavailable(f"no row for {mapping_key.split(':')[0]} in {unit_path}")
    rules = next((s for s in sections(unit_text) if s.key == _UNIT_RULES), None)
    if rules is None:
        raise BriefingUnavailable(f'no "## {_UNIT_RULES}" in {unit_path}')
    general = _paragraph(build_text, _GENERAL_OPENER)
    if general is None:
        raise BriefingUnavailable(f"no general rule paragraph in {build_path}")
    by_key = {s.key: s for s in sections(build_text)}
    keys = headings(unit, command, root, _by_key=by_key)
    blocks = [f"briefing for unit {unit} ({command}), cut from {unit_path} and {build_path}", permissions,
              f"| Unit | What you do |\n|---|---|\n{row}", rules.text, general, *(by_key[k].text for k in keys),
              f"{_FALLBACK} {build_path}"]
    return "\n\n".join(blocks).replace(_VAR, str(root))


def headings(unit: str, command: str, root: Path | None = None, _by_key: dict | None = None) -> list[str]:
    wanted = _wanted(kind(unit, command))
    root = Path(root) if root is not None else PLUGIN_ROOT
    if _by_key is None:
        _by_key = {s.key: s for s in sections(_read(root, BUILD_FILE))}
    for key in sorted(wanted):
        if key not in _by_key:
            raise BriefingUnavailable(f'heading "{key}" missing from {root / BUILD_FILE}')
    return [k for k in _by_key if k in wanted]


def _unit_problems(unit: str, command: str, root: Path, general: str, rules_text: str, bullets: list[str]) -> list[Problem]:
    try:
        text = build(unit, command, root)
    except BriefingUnavailable as exc:
        kind_ = "briefing-heading" if exc.reason.startswith("heading ") else "briefing-general"
        return [Problem(kind_, _BUILD_REL, 0, "", f"unit {unit}: {exc.reason}")]
    out: list[Problem] = []
    lines = text.splitlines()
    held = {heading_key(ln) for ln in lines if _HEAD.match(ln)}
    body = "\n".join(lines[1:-1])
    seen: set[str] = set()
    for ref in [f"Phase {n}" for n in _PHASE_REF.findall(body)] + _NUMBER_REF.findall(body):
        if ref not in held and ref not in seen:
            seen.add(ref)
            out.append(Problem("briefing-ref", _BUILD_REL, 0, ref, f'unit {unit}: refers to "{ref}" but holds no such section'))
    missing = []
    if general not in text:
        missing.append("the general rule paragraph")
    if rules_text not in text:
        missing.append("the ## Rules section")
    missing += [f'the bullet "{b[2:62]}"' for b in bullets if b not in lines]
    out += [Problem("briefing-general", _BUILD_REL, 0, "", f"unit {unit}: lacks {m}") for m in missing]
    return out


def problems(root: Path | None = None) -> list[Problem]:
    root = Path(root) if root is not None else PLUGIN_ROOT
    try:
        build_text, unit_text = _read(root, BUILD_FILE), _read(root, UNIT_FILE)
    except BriefingUnavailable as exc:
        return [Problem("briefing-general", _BUILD_REL, 0, "", exc.reason)]
    secs = sections(build_text)
    present = {s.key for s in secs}
    mapped = {k for v in MAPPING.values() for k in v} | set(GENERAL)
    out = [Problem("briefing-heading", _BUILD_REL, 0, k, f'mapped heading "{k}" is missing from {_BUILD_REL} (renamed or removed)')
           for k in sorted(mapped - present)]
    for s in secs:
        if s.key not in mapped:
            heading = build_text.splitlines()[s.line - 1].lstrip("#").strip()
            out.append(Problem("briefing-orphan", _BUILD_REL, s.line, heading, f'section "{heading}" belongs to no unit'))
    general = _paragraph(build_text, _GENERAL_OPENER)
    rules = next((s for s in secs if s.key == "Rules"), None)
    unit_rules = next((s for s in sections(unit_text) if s.key == _UNIT_RULES), None)
    bullets = [ln for ln in (unit_rules.text.splitlines() if unit_rules else []) if ln.startswith("- ")]
    sub = lambda t: t.replace(_VAR, str(root))  # noqa: E731
    for unit, command in _PROBLEM_UNITS:
        out += _unit_problems(unit, command, root, sub(general or "\0"), sub(rules.text if rules else "\0"),
                              [sub(b) for b in bullets])
    return out
