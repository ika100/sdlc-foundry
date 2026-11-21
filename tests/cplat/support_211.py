"""Spec 211: shared helpers of the acceptance tests (not a test module).

`briefing` is imported on first use (a `Lazy` module), so a missing module fails the test that needs it, not the collection.
The text helpers cut the real instructions on their own (by `##` / `###` heading), so a test compares the briefing with the
source and not with the code under test."""
import re
import shutil
from pathlib import Path

import core
from rules_support import Lazy

briefing = Lazy("briefing")

PLUGIN = core.PLATFORM_ROOT / "plugins" / "component"
BUILD_MD = PLUGIN / "commands" / "build.md"
UNIT_MD = PLUGIN / "references" / "unit-mode.md"
SPEC_DIR = core.PLATFORM_ROOT / "docs" / "specs" / "211-unit-sessions-start-with-their"

# A2 of the spec, written out: the build-instruction heading keys a unit's briefing holds besides `cplat` and `Rules`.
MAPPING = {
    "plan": (),
    "red-tests": ("Phase 0", "Phase 1"),
    "batch": ("Phase 0", "Phase 2", "2.1", "2.2", "2.3", "2.4", "2.4a"),
    "task": ("Phase 0", "Phase 2", "2.1", "2.3", "2.4", "2.4a"),
    "verification": ("Phase 0", "2.5", "2.6", "Phase 3", "Phase 4", "Phase 5", "Phase 6"),
    "land:build": ("Phase 0", "Phase 7"),
    "land:ship": (),
}
# (unit name, command, MAPPING key)
UNITS = [
    ("plan", "ship", "plan"), ("plan", "build", "plan"),
    ("red-tests", "build", "red-tests"),
    ("batch:t1,t2", "build", "batch"), ("batch:t1,t2", "ship", "batch"),
    ("task:t1", "build", "task"), ("task:t1", "ship", "task"),
    ("verification", "build", "verification"), ("verification", "ship", "verification"),
    ("land", "build", "land:build"), ("land", "ship", "land:ship"),
]
KNOWN = "plan, red-tests, batch:<id>,<id>…, task:<id>, verification, land"
FALLBACK_LINE = "Full build instructions, for a step this briefing lacks:"

HEAD = re.compile(r"^(#{2,3}) +(.*)$")


def key_of(line: str) -> str:
    """The heading key of design.md section 1, computed here from the heading line."""
    text = HEAD.match(line).group(2)
    m = re.match(r"(Phase \d+)\b", text) or re.match(r"(\d+\.\d+a?)\b", text)
    return m.group(1) if m else text.strip()


def cut(text: str) -> dict[str, str]:
    """key -> the section's own text (heading line to the line before the next ## / ### heading, trailing blank lines dropped)."""
    out, key, buf = {}, None, []
    for line in text.splitlines():
        if HEAD.match(line):
            if key is not None:
                out[key] = "\n".join(buf).rstrip()
            key, buf = key_of(line), [line]
        elif key is not None:
            buf.append(line)
    if key is not None:
        out[key] = "\n".join(buf).rstrip()
    return out


def build_sections() -> dict[str, str]:
    return cut(BUILD_MD.read_text())


def expected_keys(mapping_key: str) -> list[str]:
    """`cplat`, the mapped keys and `Rules`, in the order of build.md."""
    order = list(build_sections())
    return sorted({"cplat", "Rules", *MAPPING[mapping_key]}, key=order.index)


def unit_rules_bullets() -> list[str]:
    lines = UNIT_MD.read_text().split("## Rules for every unit", 1)[1].splitlines()
    out = []
    for line in lines:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            out.append(line)
    return out


def copy_plugin(tmp_path: Path, name: str = "plugin") -> Path:
    """A copy of the two instruction files under `<tmp>/<name>/{commands,references}`; the root to pass to `briefing`."""
    root = tmp_path / name
    for src in (BUILD_MD, UNIT_MD):
        dst = root / src.relative_to(PLUGIN)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    return root


def edit(root: Path, rel: str, old: str, new: str) -> None:
    p = root / rel
    text = p.read_text()
    assert old in text, f"fixture: {old!r} not in {rel}"
    p.write_text(text.replace(old, new, 1))


def kinds(problems) -> list[str]:
    return [p.kind for p in problems]


def of(problems, kind) -> list:
    return [p for p in problems if p.kind == kind]


# ---------------- `cplat platform rules check` on a small tree ----------------

def tree(tmp_path: Path) -> Path:
    """The good tree of the rule-check tests plus the real instruction files under plugins/component (other failures of the
    check, such as unregistered rule sentences, are expected; the tests look at the `briefing-*` ones)."""
    from rules_support import good_repo
    root = good_repo(tmp_path / "tree")
    for src in (BUILD_MD, UNIT_MD):
        dst = root / "plugins" / "component" / src.relative_to(PLUGIN)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    return root


def run_cli(root: Path, *extra: str) -> tuple[int, str, str]:
    import contextlib
    import io

    import cplat
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cplat.main(["platform", "rules", "check", "--repo", str(root), *extra])
    return rc, out.getvalue(), err.getvalue()


def check_real_repo() -> list:
    """The `briefing-*` failures of `rulescheck.check` on this repository."""
    import rulescheck
    res = rulescheck.check(core.PLATFORM_ROOT)
    return [f for f in res.failures if str(getattr(f, "kind", "")).startswith("briefing")]
