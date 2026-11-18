"""Spec 205: an edit to a frozen acceptance test that changes no assertion (comments, Python docstrings, static imports).

`judge(old, new, name)` returns `"no assertion changed: <kinds>"` or None (refused: the caller keeps today's reason).
"""
import ast
import io
import re
import tokenize
from collections import Counter

KINDS = ("comments", "docstrings", "imports")
_TS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
_DIRECTIVES = ("noqa", "type:", "pragma", "pylint:", "ruff:", "flake8:", "mypy:", "fmt:", "isort:", "nosec", "nolint",
               "go:", "+build", "eslint", "@ts-", "prettier-ignore", "istanbul", "c8", "v8 ignore", "@vitest-environment",
               "@jest-environment", "biome-ignore", "NOSONAR", "CHECKSTYLE", "/ <reference")


def _squash(text: str) -> str:
    return " ".join(text.split())


def _is_directive(text: str) -> bool:
    return text.lstrip().startswith(_DIRECTIVES)


def _verdict(old_parts: dict[str, Counter], new_parts: dict[str, Counter]) -> str | None:
    kinds = [k for k in KINDS if old_parts.get(k, Counter()) != new_parts.get(k, Counter())]
    return "no assertion changed: " + ", ".join(kinds) if kinds else None


# ---------------- Python ----------------

class _Strip(ast.NodeTransformer):
    """Drops docstrings and imports at every level, collecting them."""

    def __init__(self) -> None:
        self.docs: Counter = Counter()

    def generic_visit(self, node):
        super().generic_visit(node)
        for field in node._fields:
            stmts = getattr(node, field, None)
            if not (isinstance(stmts, list) and stmts and all(isinstance(s, ast.stmt) for s in stmts)):
                continue
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and field == "body":
                first = stmts[0]
                if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    self.docs[_squash(first.value.value)] += 1
                    stmts = stmts[1:]
            kept = [s for s in stmts if not isinstance(s, (ast.Import, ast.ImportFrom))]
            if not kept and not isinstance(node, ast.Module):
                kept = [ast.Pass()]
            setattr(node, field, kept)
        return node


class _Norm(ast.NodeTransformer):
    def visit_Constant(self, node):
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(_squash(node.value)), node)
        return node


def _py_parts(src: str) -> tuple[dict[str, Counter], str]:
    tree = ast.parse(src)
    imports = Counter(ast.dump(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))
    comments: Counter = Counter()
    directives: Counter = Counter()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            continue
        text = tok.string[1:]
        if _is_directive(text) or (tok.start[0] <= 2 and (text.startswith("!") or "-*-" in text)):
            directives[_squash(text)] += 1
        else:
            comments[_squash(text)] += 1
    strip = _Strip()
    stripped = strip.visit(tree)
    code = ast.dump(_Norm().visit(stripped))
    return {"comments": comments, "docstrings": strip.docs, "imports": imports, "directives": directives}, code


# ---------------- TS/JS, Go, Java ----------------

_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^")
_TS_IMPORTS = [
    re.compile(r"^[ \t]*import\s+(?:type\s+)?[^'\";()=]*?\s*from\s*(['\"])[^'\"\n]*\1[ \t]*;?", re.M),
    re.compile(r"^[ \t]*import\s*(['\"])[^'\"\n]*\1[ \t]*;?", re.M),
]
_GO_BLOCK = re.compile(r"^[ \t]*import[ \t]*\(([^)]*)\)", re.M)
_GO_ONE = re.compile(r"^[ \t]*import[ \t]+((?:[\w.]+[ \t]+)?\"[^\"\n]*\")", re.M)
_JAVA_IMPORT = re.compile(r"^[ \t]*import[ \t]+(?:static[ \t]+)?[\w.*]+[ \t]*;", re.M)


def _lex(text: str, lang: str) -> tuple[str, list[str]] | None:
    """(code with comments blanked, comment texts after the marker); None when a literal or comment is unterminated."""
    code: list[str] = []
    comments: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            comments.append(text[i + 2:j])
            i = j
            code.append(" ")
        elif c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            if j < 0:
                return None
            comments.append(text[i + 2:j])
            code.append(" " + "\n" * text.count("\n", i, j))
            i = j + 2
        elif lang == "java" and text.startswith('"""', i):
            j = i + 3
            while True:
                j = text.find('"""', j)
                if j < 0:
                    return None
                if text[j - 1] != "\\":
                    break
                j += 1
            code.append(text[i:j + 3])
            i = j + 3
        elif c in "\"'" or (c == "`" and lang != "java"):
            j = i + 1
            escapes = not (c == "`" and lang == "go")
            while j < n and text[j] != c:
                if text[j] == "\\" and escapes:
                    j += 1
                elif text[j] == "\n" and c != "`":
                    return None
                j += 1
            if j >= n:
                return None
            code.append(text[i:j + 1])
            i = j + 1
        elif c == "/" and lang == "js" and _regex_allowed("".join(code)):
            j, in_class = i + 1, False
            while j < n and (text[j] != "/" or in_class):
                if text[j] == "\n":
                    return None
                if text[j] == "\\":
                    j += 1
                elif text[j] == "[":
                    in_class = True
                elif text[j] == "]":
                    in_class = False
                j += 1
            if j >= n:
                return None
            code.append(text[i:j + 1])
            i = j + 1
        else:
            code.append(c)
            i += 1
    return "".join(code), comments


def _regex_allowed(code: str) -> bool:
    tail = code.rstrip()
    return not tail or tail[-1] in _REGEX_PREV or re.search(r"(?:^|[^\w$])return$", tail) is not None


def _take_imports(code: str, lang: str) -> tuple[str, Counter]:
    found: list[str] = []

    def grab(rx: re.Pattern, text: str, fn=None) -> str:
        def sub(m: re.Match) -> str:
            found.extend(fn(m) if fn else [_squash(m.group(0)).rstrip(";").strip()])
            return "\n"
        return rx.sub(sub, text)

    if lang == "js":
        for rx in _TS_IMPORTS:
            code = grab(rx, code)
    elif lang == "go":
        code = grab(_GO_BLOCK, code, lambda m: [_squash(ln) for ln in m.group(1).split("\n") if ln.strip()])
        code = grab(_GO_ONE, code, lambda m: [_squash(m.group(1))])
    else:
        code = grab(_JAVA_IMPORT, code)
    return code, Counter(found)


def _c_parts(text: str, lang: str) -> tuple[dict[str, Counter], str] | None:
    lexed = _lex(text, lang)
    if lexed is None:
        return None
    code, comments = lexed
    code, imports = _take_imports(code, lang)
    plain = Counter(_squash(c) for c in comments if not _is_directive(c))
    directives = Counter(_squash(c) for c in comments if _is_directive(c))
    return {"comments": plain, "imports": imports, "directives": directives}, re.sub(r"\s+", "", code)


# ---------------- entry point ----------------

def judge(old: str, new: str, name: str) -> str | None:
    import spec
    lower = name.lower()
    if lower.endswith(".py"):
        parse = _py_parts
    elif lower.endswith(_TS):
        parse = lambda t: _c_parts(t, "js")  # noqa: E731
    elif lower.endswith(".go"):
        parse = lambda t: _c_parts(t, "go")  # noqa: E731
    elif lower.endswith(".java"):
        parse = lambda t: _c_parts(t, "java")  # noqa: E731
    else:
        return None
    if set(spec.AC_ANY.findall(old)) != set(spec.AC_ANY.findall(new)):
        return None
    try:
        a, b = parse(old), parse(new)
    except (SyntaxError, tokenize.TokenError, ValueError):
        return None
    if a is None or b is None:
        return None
    (pa, ca), (pb, cb) = a, b
    if pa["directives"] != pb["directives"] or ca != cb:
        return None
    return _verdict(pa, pb)
