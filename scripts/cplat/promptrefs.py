"""Prompt targets (spec 180): every file, anchor, cplat command and slash command a plugin prompt points to.

Pure building blocks, no CLI and no printing; `rulescheck` reports `problems`. The contract is
docs/specs/180-*/design.md, *Prompt targets*. A target is a `Target(kind, line, raw, key)`; `problems` lists the ones
that do not resolve as `(kind, line, raw, message)` with kind `broken-link`, `broken-anchor`, `unknown-cplat` or
`unknown-slash`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"

_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|!\[[^\]]*\]\(([^)\s]+)\)")
_LINK_TEXT = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_CODE = re.compile(r"(`+)(.+?)\1")
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_PLUGIN_PATH = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")
_CPLAT = re.compile(r"\bcplat\s+([a-z][a-z0-9-]*)(?:\s+([a-z][a-z0-9-]*(?:\|[a-z][a-z0-9-]*)*))?")
_SLASH = re.compile(r"(?<![\w/.:-])/([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)")
_EXTERNAL = ("http://", "https://", "mailto:")


@dataclass(frozen=True)
class Target:
    kind: str      # "link" | "anchor" | "plugin-path" | "cplat" | "slash"
    line: int      # 1-based line in the prompt
    raw: str       # as written
    key: str       # normalized, see the contract


def slug(heading: str) -> str:
    text = heading.replace("`", "")
    text = _LINK_TEXT.sub(r"\1", text)
    text = text.replace("*", "")
    text = re.sub(r"(?<!\w)_+|_+(?!\w)", "", text)
    text = "".join(c for c in text.lower() if c.isalnum() or c in " -_")
    return text.strip().replace(" ", "-")


def _lines(text: str) -> list[tuple[int, str, bool]]:
    """(1-based line, text, inside a fence); the fence lines themselves count as inside."""
    out, fenced, mark = [], False, ""
    for n, line in enumerate(text.splitlines(), 1):
        m = _FENCE.match(line)
        if m and (not fenced or m.group(1) == mark):
            fenced, mark = (not fenced), m.group(1)
            out.append((n, line, True))
        else:
            out.append((n, line, fenced))
    return out


def heading_texts(text: str) -> list[str]:
    return [m.group(1) for _, line, fenced in _lines(text) if not fenced and (m := _HEADING.match(line))]


def anchors(text: str) -> set[str]:
    seen: dict[str, int] = {}
    out: set[str] = set()
    for heading in heading_texts(text):
        s = slug(heading)
        n = seen.get(s, 0)
        seen[s] = n + 1
        out.add(s if n == 0 else f"{s}-{n}")
    return out


def _plugin(rel: str) -> str:
    parts = rel.split("/")
    return parts[1] if len(parts) > 1 and parts[0] == "plugins" else ""


def _mask_code(line: str) -> str:
    return _CODE.sub(lambda m: " " * len(m.group(0)), line)


def _norm(path: str) -> str:
    return os.path.normpath(path).replace(os.sep, "/")


def _resolve(rel: str, target: str) -> str:
    if target.startswith(ROOT_VAR + "/"):
        return _norm(f"plugins/{_plugin(rel)}/{target[len(ROOT_VAR) + 1:]}")
    if target.startswith("/"):
        return _norm(target.lstrip("/"))
    return _norm(f"{os.path.dirname(rel)}/{target}")


def _link_targets(line: str) -> list[tuple[str, int, int]]:
    """(target, start, end) of every Markdown link target in a line with the code masked."""
    masked = _mask_code(line)
    return [(a or b, m.start(1 if a else 2), m.end(1 if a else 2)) for m in _LINK.finditer(masked) for a, b in [m.groups()]]


def _link_kinds(rel: str, n: int, target: str) -> list[Target]:
    if target.startswith(_EXTERNAL) or "<" in target or "{{" in target:
        return []
    path, _, frag = target.partition("#")
    path = path.split("?", 1)[0]
    out = []
    if path:
        out.append(Target("link", n, target, _resolve(rel, path)))
    if frag:
        out.append(Target("anchor", n, target, f"{_resolve(rel, path) if path else rel}#{frag}"))
    return out


def targets(root: Path, rel: str, text: str) -> list[Target]:
    out: list[Target] = []
    for n, line, fenced in _lines(text):
        spans: list[tuple[int, int]] = []
        if not fenced:
            for target, start, end in _link_targets(line):
                spans.append((start, end))
                out += _link_kinds(rel, n, target)
        for m in _PLUGIN_PATH.finditer(line):
            if any(a <= m.start() < b for a, b in spans):
                continue
            path = m.group(1).rstrip(".,;:")
            if not path or line[m.end():m.end() + 1] in ("<", "*"):
                continue
            out.append(Target("plugin-path", n, f"{ROOT_VAR}/{path}", _norm(f"plugins/{_plugin(rel)}/{path}")))
        code = [line] if fenced else [m.group(2) for m in _CODE.finditer(line)]
        for segment in code:
            for m in _CPLAT.finditer(segment):
                noun, verbs = m.group(1), m.group(2)
                if verbs is None:
                    out.append(Target("cplat", n, m.group(0), f"cplat {noun}"))
                else:
                    out += [Target("cplat", n, m.group(0), f"cplat {noun} {v}") for v in verbs.split("|")]
        for m in _SLASH.finditer(line):
            out.append(Target("slash", n, m.group(0), f"/{m.group(1)}:{m.group(2)}"))
    return out


def _cplat_problem(key: str) -> str | None:
    import cplat
    _, noun, *rest = key.split()
    verb = rest[0] if rest else None
    if noun in cplat.NOUNS:
        if verb is None or verb in cplat.NOUNS[noun]:
            return None
        return f"`{key}` is not offered (verbs of {noun}: {' '.join(cplat.NOUNS[noun])})"
    if noun == "runs":
        return None if verb is None else f"`{key}` is not offered (`cplat runs` takes no verb)"
    if noun in cplat.PLUMBING:
        return None
    return f"`cplat {noun}` is no cplat command"


def problems(root: Path, rel: str, text: str) -> list[tuple[str, int, str, str]]:
    root = Path(root)
    out: list[tuple[str, int, str, str]] = []
    own: dict[str, set[str]] = {}

    def heading_slugs(path: str) -> set[str] | None:
        if path not in own:
            f = root / path
            own[path] = anchors(text if path == rel else f.read_text(errors="replace")) if path == rel or f.is_file() else None
        return own[path]

    for t in targets(root, rel, text):
        if t.kind in ("link", "plugin-path"):
            if not (root / t.key).exists():
                out.append(("broken-link", t.line, t.raw, f"`{t.raw}` does not exist (resolved to {t.key})"))
        elif t.kind == "anchor":
            path, _, frag = t.key.partition("#")
            found = heading_slugs(path)
            if found is None or frag not in found:
                out.append(("broken-anchor", t.line, t.raw, f"no heading for `#{frag}` in {path}"))
        elif t.kind == "cplat":
            if (msg := _cplat_problem(t.key)):
                out.append(("unknown-cplat", t.line, t.raw, msg))
        elif t.kind == "slash":
            p, c = t.key[1:].split(":")
            if not (root / "plugins" / p / "commands" / f"{c}.md").is_file():
                out.append(("unknown-slash", t.line, t.raw,
                            f"`{t.key}` is defined by no plugin (no plugins/{p}/commands/{c}.md)"))
    return out
