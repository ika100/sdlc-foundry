#!/usr/bin/env python3
"""Check that the user-facing docs name only things that exist (spec 161, CI guard, `quality`, `ci-local`).

  check-docs.py [PATH...]     default: the user-facing pages (README, docs/*.md guides, hand-written site pages, plugin READMEs)

For every page it checks: each `/<plugin>:<command>` exists and is not a tombstone, each `--flag` written after a command in
code is in the command's usage line, each `/plugin install <name>@sdlc-foundry` names a plugin that is more than tombstones,
the plugins a page installs in code include the starter set (read from plugins/starter; installing `starter` counts as all of it), each `devbox run <recipe>` is defined, and each YAML block with
`system` and `components` is a valid system manifest. Tombstones may appear in a `## … 4.x …` section or next to the
command that replaced them. Reader pages may not name a spec or criterion outside a closing
"Background" section. A page with `<!-- historical -->` is skipped. Run with pyyaml (`uv run --with-requirements
requirements-test.txt python scripts/check-docs.py`).
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "cplat"))

import plugin_set  # noqa: E402

# what a newcomer installs in an empty folder, read from the starter plugin (spec 174); generated repos enable the rest in .claude/settings.json
STARTER = tuple(
    plugin_set.dependency_name(d)
    for d in json.loads((ROOT / "plugins" / plugin_set.STARTER / ".claude-plugin" / "plugin.json").read_text())["dependencies"])
SITE = ROOT / "site" / "src" / "content" / "docs"
# synced from docs/ at build time (site/.gitignore): checked at their source
SITE_GENERATED = ("guides/", "reference/", "community/", "vision/design-history", "vision/end-to-end-scenario")
DOCS_SKIPPED = {"CHANGELOG.md", "backlog.md"}
# recipes a repo defines itself (repo-owned companions, ADR-031)
OWN_RECIPES = {"ci-extra"}
# reader pages: no spec numbers or criterion ids in the body (AC-161.10; every guide since spec 173)
PLAIN = ["README.md", "docs", "site/src/content/docs/get-started", "site/src/content/docs/concepts",
         "site/src/content/docs/scenarios"]
# measurement records name the spec each number came from
RECORDS = {"docs/PERFORMANCE.md", "docs/BASELINES.md"}

COMMAND = re.compile(r"(?<![\w/.:<-])/([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)")
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
INSTALL = re.compile(r"/plugin install ([a-z0-9-]+)@sdlc-foundry")
RECIPE = re.compile(r"devbox run ([a-z][a-z0-9-]*)")
JARGON = re.compile(r"\bspecs? \d{2,3}\b|\bAC-\d+\.\d+", re.I)
FENCE = re.compile(r"^\s*(```|~~~)\s*([\w-]*)")
CODE_SPAN = re.compile(r"`([^`\n]+)`")


def commands() -> dict[str, tuple[bool, set[str]]]:
    """`/plugin:command` -> (is a tombstone, the flags its command file names; `[flags]` in the usage allows any)."""
    out = {}
    for f in sorted(ROOT.glob("plugins/*/commands/*.md")):
        text = f.read_text()
        head = text.split("---", 2)[1] if text.startswith("---") else ""
        desc = (yaml.safe_load(head) or {}).get("description", "")
        flags = {"*"} if "[flags]" in desc else set(FLAG.findall(text))
        out[f"/{f.parent.parent.name}:{f.stem}"] = (desc.startswith("Moved in"), flags)
    return out


def live_plugins(cmds: dict[str, tuple[bool, set[str]]]) -> set[str]:
    """Plugins that hold more than tombstones (`plugin_set.is_tombstone_only`)."""
    return {p.name for p in sorted((ROOT / "plugins").iterdir())
            if (p / ".claude-plugin" / "plugin.json").is_file() and not plugin_set.is_tombstone_only(p)}


def recipes() -> set[str]:
    out = set()
    for f in [ROOT / "devbox.json", *ROOT.glob("templates/*/devbox.json*")]:
        text = f.read_text()
        block = text.split('"scripts"', 1)[1] if '"scripts"' in text else ""
        out |= set(re.findall(r'^\s*"([a-z][a-z0-9-]*)"\s*:', block, re.M))
    return out | OWN_RECIPES


def pages(paths: list[str], plugins: set[str]) -> list[Path]:
    if paths:
        found = [ROOT / p for p in paths]
        return [f for p in found for f in ([p] if p.is_file() else sorted(p.rglob("*.md*")))]
    out = [ROOT / "README.md"]
    out += [f for f in sorted((ROOT / "docs").glob("*.md")) if f.name not in DOCS_SKIPPED]
    out += [f for f in sorted(SITE.rglob("*.md*")) if not f.relative_to(SITE).as_posix().startswith(SITE_GENERATED)]
    out += [f for f in sorted(ROOT.glob("plugins/*/README.md")) if f.parent.name in plugins]  # tombstone plugins list their moves
    return out


def is_plain(f: Path) -> bool:
    rel = f.relative_to(ROOT).as_posix()
    return rel not in RECORDS and any(rel == p or rel.startswith(p + "/") for p in PLAIN)


def check_manifest(block: str) -> str | None:
    import newapp
    from core import PlatformError
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("system"), str) or not isinstance(data.get("components"), list):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "manifest.yml"
        path.write_text(block)
        try:
            newapp.load_manifest(path)
        except PlatformError as e:
            return f"invalid system manifest: {e}"
    return None


def check_page(f: Path, cmds, plugins, known_recipes) -> list[str]:
    text = f.read_text()
    if "<!-- historical -->" in text:
        return []
    rel, problems, installed = f.relative_to(ROOT).as_posix(), [], set()
    plain, background, history = is_plain(f), False, False
    fence, block, block_start = None, [], 0

    def flags_after(snippet: str, at: int, name: str, n: int) -> None:
        rest = snippet[at:]
        nxt = COMMAND.search(rest)
        rest = rest[: nxt.start()] if nxt else rest
        quote = snippet[at - len(name) - 1: at - len(name)]
        if quote in ("'", '"'):  # `cplat headless "/component:ship 012" --quiet`: the flags after the quote are not the command's
            rest = rest.split(quote, 1)[0]
        if "*" in cmds[name][1]:
            return
        for flag in FLAG.findall(rest):
            if flag not in cmds[name][1]:
                problems.append(f"{rel}:{n}: {name} has no {flag} (usage: {' '.join(sorted(cmds[name][1])) or 'no flags'})")

    def scan(snippet: str, n: int, code: bool, fenced: bool = False) -> None:
        # a tombstone in a 4.x migration section, or on a line that also names a live command, is an old-to-new mapping
        mapping = history or any(c in cmds and not cmds[c][0] for c in (m.group(0) for m in COMMAND.finditer(line)))
        for m in COMMAND.finditer(snippet):
            name = m.group(0)
            if name not in cmds:
                problems.append(f"{rel}:{n}: {name} is not a command")
            elif cmds[name][0] and not mapping:
                problems.append(f"{rel}:{n}: {name} is a tombstone (moved in 5.0)")
            elif code:
                flags_after(snippet, m.end(), name, n)
        for m in INSTALL.finditer(snippet):
            if m.group(1) not in plugins:
                problems.append(f"{rel}:{n}: plugin {m.group(1)} does not exist or holds only tombstones")
            if fenced:
                installed.add(m.group(1))
        for m in RECIPE.finditer(snippet):
            if m.group(1) not in known_recipes:
                problems.append(f"{rel}:{n}: devbox run {m.group(1)} is not a recipe of this repo or a template")

    for n, line in enumerate(text.splitlines(), 1):
        fm = FENCE.match(line)
        if fence is None and fm:
            fence, block, block_start = fm.group(2), [], n
            continue
        if fence is not None:
            if fm and not fm.group(2):
                if fence in ("yaml", "yml") and (err := check_manifest("\n".join(block))):
                    problems.append(f"{rel}:{block_start}: {err}")
                fence = None
            else:
                block.append(line)
                if fence != "mermaid":
                    scan(line, n, code=True, fenced=True)
            continue
        if line.startswith("#"):
            background = line.lstrip("#").strip().lower().startswith("background")
            if line.startswith("## "):
                history = bool(re.search(r"\b4\.(x|7)\b", line))
        spans = CODE_SPAN.findall(line)
        for span in spans:
            scan(span, n, code=True)
        scan(CODE_SPAN.sub("", line), n, code=False)
        if plain and not background and not history and (m := JARGON.search(CODE_SPAN.sub("", line))):
            problems.append(f"{rel}:{n}: '{m.group(0)}' on a reader page: move it to a closing Background section")
    if plugin_set.STARTER in installed:  # the starter plugin depends on the whole starter set
        installed = installed | set(STARTER)
    missing = [p for p in STARTER if p not in installed]
    if installed and missing:
        problems.append(f"{rel}: installs {', '.join(sorted(installed))} but not the starter plugin(s) {', '.join(missing)}")
    return problems


def main(argv: list[str]) -> int:
    cmds = commands()
    plugins, known = live_plugins(cmds), recipes()
    problems = [p for f in pages(argv, plugins) for p in check_page(f, cmds, plugins, known)]
    for p in problems:
        print(p)
    print(f"{'FAIL' if problems else 'OK'}: {len(problems)} problem(s) in the user-facing docs")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
