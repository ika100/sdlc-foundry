"""Spec 086: merge a repo's `.claude/settings.json` into the template's.

The template's file wins, except for the repo's own permission entries (allow, ask, deny), which are kept. Entries
the platform removed since the repo's previous platform version (the baseline) are dropped, not kept.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

LISTS = ("allow", "ask", "deny")
REL = ".claude/settings.json"
DROPPED_PLUGINS = ("app@sdlc-foundry", "gitops@sdlc-foundry")   # the 4.x plugins 5.0 replaced by the noun plugins
LEGACY_SUFFIX = "@ika100-claude"   # every plugin of the marketplace before the v3.0.0 rename (doctor.LEGACY_MARKETPLACE)


def _json(v) -> str:
    return json.dumps(v, separators=(",", ":"))


def _same_as_baseline(value, baseline: dict | None, key: str, sub: str | None) -> bool:
    """True when the baseline has the same value for the key (a baseline value containing `{{` counts as equal)."""
    if baseline is None:
        return False
    src = (baseline.get("permissions") or {}) if sub else baseline
    if key not in src:
        return False
    return "{{" in _json(src[key]) or src[key] == value


def merge_settings(project: dict, template: dict, baseline: dict | None) -> tuple[dict, dict]:
    """-> (merged, {"kept": [{"list", "entry"}], "removed_by_platform": [{"list", "entry"}], "replaced": [{"key", "was"}]})"""
    merged = copy.deepcopy(template)
    kept: list[dict] = []
    removed: list[dict] = []
    replaced: list[dict] = []
    pperm = project.get("permissions") if isinstance(project.get("permissions"), dict) else {}
    tperm = template.get("permissions") if isinstance(template.get("permissions"), dict) else {}
    bperm = (baseline or {}).get("permissions") if isinstance((baseline or {}).get("permissions"), dict) else {}

    for name in LISTS:
        mine = pperm.get(name)
        if not isinstance(mine, list):
            continue
        theirs = tperm.get(name) if isinstance(tperm.get(name), list) else []
        base = bperm.get(name) if isinstance(bperm.get(name), list) else []
        for entry in mine:
            if entry in theirs:
                continue
            if baseline is not None and entry in base:
                removed.append({"list": name, "entry": entry})
            else:
                kept.append({"list": name, "entry": entry})
                merged.setdefault("permissions", {}).setdefault(name, []).append(entry)

    for key, value in project.items():
        if key not in ("permissions", "enabledPlugins") and value != template.get(key) and not _same_as_baseline(value, baseline, key, None):
            replaced.append({"key": key, "was": _json(value)})
    for key, value in pperm.items():
        if key not in LISTS and value != tperm.get(key) and not _same_as_baseline(value, baseline, key, "permissions"):
            replaced.append({"key": f"permissions.{key}", "was": _json(value)})
    plugins = _merge_plugins(project, template, merged)
    return merged, {"kept": kept, "removed_by_platform": removed, "replaced": replaced, "plugins": plugins}


def _merge_plugins(project: dict, template: dict, merged: dict) -> dict:
    """enabledPlugins = the template's map + the repo's own entries - the dropped 4.x and old-marketplace plugins; -> {added, removed}."""
    mine = project.get("enabledPlugins") if isinstance(project.get("enabledPlugins"), dict) else {}
    theirs = template.get("enabledPlugins") if isinstance(template.get("enabledPlugins"), dict) else {}
    if not theirs and not mine:
        return {"added": [], "removed": []}
    result = dict(theirs)
    for name, value in mine.items():
        if name not in result and name not in DROPPED_PLUGINS and not name.endswith(LEGACY_SUFFIX):
            result[name] = value
    merged["enabledPlugins"] = result
    return {"added": sorted(set(result) - set(mine)), "removed": sorted(set(mine) - set(result))}


def _write_plugins(text: str, plugins: dict) -> str:
    """Replace the enabledPlugins block of `text`, keeping the rest of the file as it is."""
    m = re.search(r'"enabledPlugins"\s*:\s*\{', text)
    if not m:
        raise ValueError("enabledPlugins")
    open_at = m.end() - 1
    end = _close(text, open_at)
    line_start = text.rfind("\n", 0, m.start()) + 1
    key_indent = re.match(r"[ \t]*", text[line_start:]).group(0)  # type: ignore[union-attr]
    inner = ",\n".join(f"{key_indent}  {json.dumps(k)}: {json.dumps(v)}" for k, v in plugins.items())
    return text[:open_at] + "{\n" + inner + f"\n{key_indent}" + text[end:]


def _close(text: str, start: int) -> int:
    """Index of the bracket closing the one at `start`, skipping JSON strings."""
    depth, i, in_str = 0, start, False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced JSON")


def _insert(text: str, merged: dict) -> str:
    """Add the kept entries to the template's text before each list's closing bracket; falls back to a plain dump."""
    out = text
    try:
        start = re.search(r'"permissions"\s*:\s*\{', out)
        if not start:
            raise ValueError("permissions")
        for name in LISTS:
            current = json.loads(out).get("permissions", {}).get(name)
            new = merged.get("permissions", {}).get(name)
            if new is None or new == current:
                continue
            if current is None:
                raise ValueError(name)
            perm_start = re.search(r'"permissions"\s*:\s*\{', out)
            assert perm_start is not None
            m = re.compile(rf'"{name}"\s*:\s*\[').search(out, perm_start.end())
            if not m:
                raise ValueError(name)
            open_at = m.end() - 1
            end = _close(out, open_at)
            body = out[open_at + 1:end]
            line_start = out.rfind("\n", 0, m.start()) + 1
            key_indent = re.match(r"[ \t]*", out[line_start:]).group(0)  # type: ignore[union-attr]
            indent = (re.findall(r"\n([ \t]+)\S", body) or [key_indent + "  "])[-1]
            extra = [json.dumps(v) for v in new[len(current):]]
            head = body.rstrip()
            sep = "," if head.strip() else ""
            insert = sep + "".join(f"\n{indent}{e}" + ("," if i < len(extra) - 1 else "") for i, e in enumerate(extra))
            tail = body[len(head):] if head.strip() else f"\n{key_indent}"
            out = out[:open_at + 1] + head + insert + tail + out[end:]
        if json.loads(out) == merged:
            return out
    except ValueError:
        pass
    return json.dumps(merged, indent=2) + "\n"


def merge_settings_file(repo: Path, before: str | None, baseline: dict | None) -> tuple[dict, str | None]:
    """Reads the rendered file, writes the merge (only when something is kept), returns (report, note)."""
    empty: dict = {"kept": [], "removed_by_platform": [], "replaced": [], "plugins": {"added": [], "removed": []}}
    path = repo / REL
    if before is None or not path.is_file():
        return empty, None
    try:
        project = json.loads(before)
        if not isinstance(project, dict):
            raise ValueError("not an object")
    except ValueError:
        return empty, (f"{REL} was not valid JSON: replaced by the template's file; "
                       f"re-add your permission entries from git show HEAD~1:{REL}")
    text = path.read_text()
    merged, report = merge_settings(project, json.loads(text), baseline)
    out = _insert(text, merged) if report["kept"] else text
    if merged.get("enabledPlugins") != json.loads(text).get("enabledPlugins"):
        try:
            out = _write_plugins(out, merged["enabledPlugins"])
        except ValueError:
            out = json.dumps({**json.loads(out), "enabledPlugins": merged["enabledPlugins"]}, indent=2) + "\n"
    if out != text:
        path.write_text(out)
    return report, None
