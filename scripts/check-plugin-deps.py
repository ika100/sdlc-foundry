#!/usr/bin/env python3
"""Plugin dependency check (spec 174, AC-174.3): every `dependencies` entry of a plugin.json or a marketplace entry is a bare
name or `name@sdlc-foundry` of a live (not tombstone-only) plugin of this marketplace, no plugin depends on itself and the
graph has no cycle. Standard library only. Run: `python3 scripts/check-plugin-deps.py [--root DIR]`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "cplat"))
import plugin_set  # noqa: E402


def _label(entry: object) -> str:
    return entry if isinstance(entry, str) else json.dumps(entry)


def _cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    colour: dict[str, int] = {}
    found: list[list[str]] = []
    stack: list[str] = []

    def visit(node: str) -> None:
        colour[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            if colour.get(nxt, 0) == 0:
                visit(nxt)
            elif colour[nxt] == 1:
                cyc = stack[stack.index(nxt):]
                start = cyc.index(min(cyc))
                cyc = cyc[start:] + cyc[:start]
                if cyc not in found:
                    found.append(cyc)
        stack.pop()
        colour[node] = 2

    for node in sorted(graph):
        if colour.get(node, 0) == 0:
            visit(node)
    return found


def _declarations(root: Path) -> tuple[list[tuple[str, str, object]], str | None]:
    """(plugin, file, dependencies) for every declaration; an error line when a file cannot be read."""
    found: list[tuple[str, str, object]] = []
    try:
        entries = plugin_set.catalog(root)
        for name, entry in entries.items():
            if "dependencies" in entry:
                found.append((name, plugin_set.MARKETPLACE_FILE, entry["dependencies"]))
            data = plugin_set.manifest(root, name)
            if "dependencies" in data:
                rel = (plugin_set.plugin_dir(root, entry) / ".claude-plugin" / "plugin.json").relative_to(root).as_posix()
                found.append((name, rel, data["dependencies"]))
    except ValueError as exc:
        return [], f"ERROR: {exc}"
    return found, None


def problems(root: Path) -> list[str]:
    decls, error = _declarations(root)
    if error:
        return [error]
    entries = plugin_set.catalog(root)
    tomb = {n: plugin_set.is_tombstone_only(plugin_set.plugin_dir(root, e)) for n, e in entries.items()}
    out: list[str] = []
    graph: dict[str, list[str]] = {}
    for name, rel, deps in decls:
        head = f"ERROR: {name} ({rel}): "
        if not isinstance(deps, list):
            out.append(head + "dependencies is not a list")
            continue
        for item in deps:
            dep = plugin_set.dependency_name(item)
            if dep is None:
                out.append(head + f'dependency "{_label(item)}" is not a plugin name or <name>@{plugin_set.MARKETPLACE} '
                           "(version ranges are not supported)")
            elif dep not in entries:
                out.append(head + f'dependency "{_label(item)}" names no plugin of this marketplace')
            elif tomb[dep]:
                out.append(head + f'dependency "{_label(item)}" holds only tombstones')
            elif dep == name:
                out.append(head + f'dependency "{_label(item)}" is the plugin itself')
            else:
                graph.setdefault(name, [])
                if dep not in graph[name]:
                    graph[name].append(dep)
    for cyc in _cycles(graph):
        out.append("ERROR: dependency cycle: " + " -> ".join([*cyc, cyc[0]]))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    root = parser.parse_args(argv).root
    found = problems(root)
    for line in found:
        print(line)
    if found:
        print(f"FAILED: {len(found)} problem(s) in plugin dependencies")
        return 1
    decls, _ = _declarations(root)
    count = len({name for name, _, _ in decls})
    print(f"OK: {count} plugin(s) declare dependencies on live plugins of this marketplace, no cycle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
