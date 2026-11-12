"""Spec 178 (AC-178.5): every fake program a `cplat` test writes takes `TEST_FAKE_DELAY`.

The stress gate slows every spawned fake process by `TEST_FAKE_DELAY`; only a fake whose text starts with `waiting.fake_prelude()` (or
passes through `waiting.with_prelude()`) takes the delay. This test finds the places that make a file executable (`chmod` with an
executable mode) and fails naming `file:line` when the function around it never builds the program text through one of the two, or holds
the marker `fake-delay`. Nothing here waits or spawns a process.
"""
import ast
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARKERS = {"fake_prelude", "with_prelude"}

# "file::function" -> why that executable cannot take the delay
ALLOWED = {
    "test_sync_template_copies.py::test_rewrite_keeps_executable_bit_of_existing_copy": "a script copy whose mode is under test, never run as a fake program",
    "test_e2e_probes_323.py::test_the_lint_rejects_a_literal_double_dollar_323": "a shell file the lint reads as text, never run as a program",
    "test_e2e_probes_323.py::test_the_lint_rejects_a_double_dollar_in_a_quoted_heredoc_323": "a shell file the lint reads as text, never run as a program",
}


def _is_executable_chmod(call: ast.Call) -> bool:
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "chmod" and call.args):
        return False
    arg = call.args[-1]
    if isinstance(arg, ast.Constant):
        return arg.value in (0o755, 0o775, 0o777, 0o700)
    text = ast.unparse(arg)
    return "S_IEXEC" in text or "S_IXUSR" in text


def _takes_prelude(scope: ast.AST) -> bool:
    for node in ast.walk(scope):
        if isinstance(node, ast.Name) and node.id in MARKERS:
            return True
        if isinstance(node, ast.Attribute) and node.attr in MARKERS:
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "fake-delay" in node.value:
            return True
    return False


def _writes_shebang(call: ast.Call) -> bool:
    """A `write_text`/`write_bytes`/`write` whose text holds a string starting with `#!` (a script run as `sh <file>` needs no chmod)."""
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr in ("write_text", "write_bytes", "write") and call.args):
        return False
    return any(isinstance(n, ast.Constant) and isinstance(n.value, (str, bytes)) and n.value[:2] in ("#!", b"#!")
               for n in ast.walk(call.args[0]))


def missing(root: Path) -> list[str]:
    """`file:line: ...` for every executable chmod or `#!` write in a function that never gives its program the prelude."""
    out = []
    for path in sorted(root.glob("*.py")):
        if path.name in ("waiting.py", Path(__file__).name):
            continue
        tree = ast.parse(path.read_text())
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            chmod = _is_executable_chmod(node)
            if not (chmod or _writes_shebang(node)):
                continue
            scope: ast.AST = node
            while scope in parents and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scope = parents[scope]
            name = getattr(scope, "name", "<module>")
            if f"{path.name}::{name}" in ALLOWED or _takes_prelude(scope):
                continue
            if not chmod and any(isinstance(n, ast.Call) and _is_executable_chmod(n) for n in ast.walk(scope)):
                continue  # the function's chmod is reported instead, once
            out.append(f"{path.name}:{node.lineno}: {name} makes a program executable without fake_prelude() "
                       "(write its text through waiting.with_prelude(...) so TEST_FAKE_DELAY slows it)")
    return out


def test_every_fake_program_a_test_writes_takes_the_fake_delay_ac_178_5():  # AC-178.5
    found = missing(HERE)
    assert not found, "\n".join(found)


def test_the_check_names_file_and_line_of_a_fake_without_the_prelude(tmp_path):  # AC-178.5
    (tmp_path / "test_a.py").write_text(textwrap.dedent("""
        import stat
        from waiting import with_prelude

        def good(p):
            p.write_text(with_prelude("#!/bin/sh\\n"))
            p.chmod(p.stat().st_mode | stat.S_IEXEC)

        def bad(p):
            p.write_text("#!/bin/sh\\n")
            p.chmod(0o755)

        def mode_only(p):
            p.chmod(0o600)
    """))
    found = missing(tmp_path)
    assert len(found) == 1 and found[0].startswith("test_a.py:11: bad "), found


def test_the_check_flags_a_shebang_write_without_chmod(tmp_path):  # AC-178.5
    (tmp_path / "test_b.py").write_text(textwrap.dedent("""
        from waiting import with_prelude

        def good(p):
            p.write_text(with_prelude("#!/bin/sh\\n"))

        def bad(p):
            p.write_text("#!/bin/sh\\nexit 0\\n")

        def bad_fstring(p, d):
            p.write_text(f"#!/bin/sh\\necho {d}\\n")

        def not_a_script(p):
            p.write_text("plain text")
    """))
    found = missing(tmp_path)
    assert [f.split(": ")[0] for f in found] == ["test_b.py:8", "test_b.py:11"], found


def test_the_allowlist_names_only_functions_that_exist():  # AC-178.5
    for key in ALLOWED:
        name, _, function = key.partition("::")
        tree = ast.parse((HERE / name).read_text())
        assert any(isinstance(n, ast.FunctionDef) and n.name == function for n in ast.walk(tree)), key
