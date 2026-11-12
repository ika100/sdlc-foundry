"""Sentence pins: test literals that quote plugin prompt wording, and their `# interface:` markers (spec 180)."""
from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

import promptrules

MIN_PIN_WORDS = 4
_MARKER = re.compile(r"^#\s*interface:\s*(.*)$")
PIN_MESSAGE = ("a test pins prompt wording: check structure (the targets `cplat platform rules check` resolves, "
               "tests/cplat/structure.py) or mark the literal `# interface: <reason>`")
SHORT_MESSAGE = "the `# interface:` reason has fewer than 3 words"
STRAY_MESSAGE = "`# interface:` on a line with no literal that occurs in a prompt"


@dataclass
class PinScan:
    failures: list[tuple[str, str, int, str, str]] = field(default_factory=list)   # (kind, file, line, text, message)
    interface_pins: int = 0


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _docstrings(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            ids.update(id(v) for v in ast.walk(node) if isinstance(v, ast.Constant))
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _literals(tree: ast.AST) -> list[tuple[int, int, str]]:
    skip = _docstrings(tree)
    return [(n.lineno, n.end_lineno or n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip]


def _markers(source: str) -> list[tuple[int, str]]:
    found = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT and (m := _MARKER.match(tok.string)):
                found.append((tok.start[0], m.group(1).strip()))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return found


def scan(root: Path) -> PinScan:
    root = Path(root)
    texts = [_collapse((root / f).read_text(encoding="utf-8", errors="replace"))
             for f in promptrules.prompt_files(root)]
    corpus = "\x00".join(texts)
    vocab = set(corpus.replace("\x00", " ").split())
    result = PinScan()
    tests = root / "tests"
    for path in sorted(tests.rglob("*.py")) if tests.is_dir() else []:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
            continue
        rel = path.relative_to(root).as_posix()
        pins = []
        for lineno, end, value in _literals(tree):
            words = value.split()
            if len(words) >= MIN_PIN_WORDS and vocab.issuperset(words) and _collapse(value) in corpus:
                pins.append((lineno, end, value))
        markers = _markers(source)
        if not pins and not markers:
            continue
        covered: set[int] = set()
        found: list[tuple[str, int, str, str]] = []
        for line, reason in markers:
            hit = [i for i, (lo, hi, _) in enumerate(pins) if lo - 1 <= line <= hi]
            if len(promptrules._WORD.findall(reason)) < promptrules.MIN_REASON_WORDS:
                found.append(("short-interface", line, reason, SHORT_MESSAGE))
                covered.update(hit)
            elif hit:
                result.interface_pins += len({i for i in hit} - covered)
                covered.update(hit)
            else:
                found.append(("stray-interface", line, reason, STRAY_MESSAGE))
        for i, (lineno, _, value) in enumerate(pins):
            if i not in covered:
                found.append(("sentence-pin", lineno, value, PIN_MESSAGE))
        result.failures += [(k, rel, ln, t, m) for k, ln, t, m in sorted(found, key=lambda f: f[1])]
    return result
