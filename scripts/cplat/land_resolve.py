"""Resolvers for the two id-keyed files that conflict on every parallel land (spec 184).

The ADR index (`docs/adr/README.md`) and a prompt's rule register (`docs/rules/**.yml`) are merged as the union of both sides;
the number the branch added and `origin/<base>` also uses is renumbered, with its references in the files the branch changed.
Everything the union cannot decide stays a person's decision (`Refused`). Text and git plumbing only: no `gh`, no push, no
commit; the caller (`land_merge.regenerate`) stages `Outcome.written` and commits.

  land_resolve.handles(path)                      is `path` one of the two kinds
  land_resolve.resolve(repo, path, ctx, run)      write the resolved file (and the renames) into the working tree
"""
from __future__ import annotations

import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ADR_INDEX = "docs/adr/README.md"
ADR_DIR = "docs/adr/"
RULES_DIR = "docs/rules/"
ROW = re.compile(r"^\| \[(\d{3,4})\]\((\d{3,4}-[^)]+\.md)\) \|")
ADR_NAME = re.compile(r"^(\d{3,4})-(.+)\.md$")
ENTRY = re.compile(r"^\s*- id: (R\d+)\s*$")
ITEM = re.compile(r"^(\s*)- ")
PLACEHOLDER = "<!-- cplat: adr rows (spec 184) -->\n"


class Refused(Exception):
    """The conflict stays a person's decision; `str(e)` is the reason."""


@dataclass
class Context:
    base: str                         # merge base of the branch head and origin/<base>
    ours: str                         # the branch head before the merge
    theirs: str                       # "origin/<base>"
    changed: list[str]                # git diff --name-only <base> <ours>: the files the branch changed
    next_adr: Callable[[], int]       # adr.next_number(repo); called after each rename


@dataclass
class Outcome:
    lines: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)


def handles(path: str) -> bool:
    return path == ADR_INDEX or (path.startswith(RULES_DIR) and path.endswith(".yml"))


def resolve(repo: Path, path: str, ctx: Context, run) -> Outcome:
    if path == ADR_INDEX:
        return _adr_index(repo, path, ctx, run)
    return _rules(repo, path, ctx, run)


# ---------------- shared helpers ----------------

def _git(repo: Path, run, *args: str):
    return run(["git", *args], cwd=repo, check=False)


def _stages(repo: Path, path: str, run) -> tuple[str, str, str]:
    """(base, ours, theirs) of a conflicted path; a missing stage is empty."""
    out = []
    for n in (1, 2, 3):
        res = _git(repo, run, "show", f":{n}:{path}")
        out.append(res.stdout if res.returncode == 0 else "")
    return out[0], out[1], out[2]


def _merge_text(repo: Path, run, base: str, ours: str, theirs: str) -> str | None:
    """`git merge-file -p` of three texts; None on a conflict."""
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for name, text in (("ours", ours), ("base", base), ("theirs", theirs)):
            f = Path(tmp) / name
            f.write_text(text)
            files.append(str(f))
        res = _git(repo, run, "merge-file", "-p", *files)
    return res.stdout if res.returncode == 0 else None


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _rewrite(repo: Path, rel: str, sub: Callable[[str], tuple[str, int]]) -> tuple[int, bool]:
    """Apply `sub` to a working-tree file; (replacements, whether it was written). Missing or non-text files are skipped."""
    p = repo / rel
    if not p.is_file():
        return 0, False
    try:
        text = p.read_text()
    except UnicodeDecodeError:
        return 0, False
    new, k = sub(text)
    if new == text:
        return 0, False
    p.write_text(new)
    return k, True


def _note(out: Outcome, path: str) -> None:
    if path not in out.written:
        out.written.append(path)


# ---------------- ADR index ----------------

def _split_rows(text: str) -> tuple[str, dict[str, str]]:
    """(text with each run of rows replaced by one placeholder line, rows by linked file)."""
    masked: list[str] = []
    rows: dict[str, str] = {}
    in_run = False
    for ln in _lines(text):
        m = ROW.match(ln)
        if m:
            rows[m.group(2)] = ln if ln.endswith("\n") else ln + "\n"
            if not in_run:
                masked.append(PLACEHOLDER)
            in_run = True
        else:
            masked.append(ln)
            in_run = False
    return "".join(masked), rows


def _adr_files(repo: Path, run, ref: str) -> set[str]:
    res = _git(repo, run, "ls-tree", "--name-only", ref, ADR_DIR)
    return {ln.removeprefix(ADR_DIR) for ln in res.stdout.splitlines() if ADR_NAME.match(ln.removeprefix(ADR_DIR))}


def _adr_index(repo: Path, path: str, ctx: Context, run) -> Outcome:
    (b_text, o_text, t_text) = _stages(repo, path, run)
    (b_masked, b_rows), (o_masked, o_rows), (t_masked, t_rows) = (_split_rows(t) for t in (b_text, o_text, t_text))
    merged = _merge_text(repo, run, b_masked, o_masked, t_masked)
    if merged is None or PLACEHOLDER not in merged:
        raise Refused(f"{path} outside its table")
    rows: dict[str, str] = {}
    for name in {*b_rows, *o_rows, *t_rows}:
        b, o, t = b_rows.get(name), o_rows.get(name), t_rows.get(name)
        if o == t or t == b:
            pick = o
        elif o == b:
            pick = t
        else:
            raise Refused(f"{path}: the row of {name} changed on both sides")
        if pick is not None:
            rows[name] = pick

    out = Outcome()
    added = _adr_files(repo, run, ctx.ours) - _adr_files(repo, run, ctx.base)
    theirs_by_number = {ADR_NAME.match(f).group(1): f for f in _adr_files(repo, run, ctx.theirs)}  # type: ignore[union-attr]
    clashes = sorted((f for f in added if theirs_by_number.get(ADR_NAME.match(f).group(1), f) != f),  # type: ignore[union-attr]
                     key=lambda f: (int(ADR_NAME.match(f).group(1)), f))  # type: ignore[union-attr]
    moved: dict[str, str] = {}                      # repo-relative old path -> new path of renamed ADR files
    for name in clashes:
        old, slug = ADR_NAME.match(name).groups()   # type: ignore[union-attr]
        n = f"{ctx.next_adr():03d}"
        new = f"{n}-{slug}.md"
        res = _git(repo, run, "mv", f"{ADR_DIR}{name}", f"{ADR_DIR}{new}")
        if res.returncode != 0:
            raise Refused(f"{path}: renumbering {name} failed: {(res.stderr or res.stdout).strip()}")
        out.renamed.append((f"{ADR_DIR}{name}", f"{ADR_DIR}{new}"))
        moved[f"{ADR_DIR}{name}"] = f"{ADR_DIR}{new}"
        _note(out, f"{ADR_DIR}{new}")
        _rewrite(repo, f"{ADR_DIR}{new}", lambda s, o=old, n=n: (re.subn(rf"^# ADR-{o}(?!\d)", f"# ADR-{n}", s, count=1, flags=re.M)))
        row_text = rows.pop(name, None)
        if row_text is not None:
            rows[new] = row_text.replace(f"[{old}]({name})", f"[{n}]({new})", 1)
        own = {f"{ADR_DIR}{name}", f"{ADR_DIR}{new}", path}
        total = 0
        for rel in ctx.changed:
            rel = moved.get(rel, rel)
            if rel in own:
                continue
            k, wrote = _rewrite(repo, rel, lambda s, o=old, n=n, nm=name, nw=new: _sub_adr(s, o, n, nm, nw))
            total += k
            if wrote:
                _note(out, rel)
        out.lines.append(f"renumbered ADR-{old} to ADR-{n} ({total} references)")

    ordered = sorted(rows.items(), key=lambda kv: (int(ROW.match(kv[1]).group(1)), kv[0]))  # type: ignore[union-attr]
    block = "".join(v for _, v in ordered)
    first = merged.index(PLACEHOLDER)
    text = merged[:first] + block + merged[first + len(PLACEHOLDER):].replace(PLACEHOLDER, "")
    (repo / path).write_text(text if text.endswith("\n") else text + "\n")
    _note(out, path)
    return out


def _sub_adr(text: str, old: str, new: str, name: str, new_name: str) -> tuple[str, int]:
    text, a = re.subn(rf"ADR-{old}(?!\d)", f"ADR-{new}", text)
    text, b = re.subn(rf"(?<!\d){re.escape(name)}", new_name, text)
    return text, a + b


# ---------------- rule register ----------------

def _parse_register(path: str, text: str) -> tuple[str, dict[str, str], list[str]]:
    """(header, entry text by id, ids in order); `Refused` for an item under `rules:` that is not `- id: R<n>`."""
    lines = _lines(text)
    starts = [i for i, ln in enumerate(lines) if ENTRY.match(ln)]
    header = "".join(lines[:starts[0]] if starts else lines)
    indent = re.match(r"\s*", lines[starts[0]]).group(0) if starts else None  # type: ignore[union-attr]
    entries: dict[str, str] = {}
    order: list[str] = []
    for k, s in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        body = lines[s:end]
        if body and not body[-1].endswith("\n"):
            body[-1] += "\n"
        ident = ENTRY.match(lines[s]).group(1)  # type: ignore[union-attr]
        entries[ident] = "".join(body)
        order.append(ident)
    for ln in lines:
        m = ITEM.match(ln)
        if m and indent is not None and m.group(1) == indent and not ENTRY.match(ln):
            raise Refused(f"{path} outside its id-keyed entries")
    return header, entries, order


def _rules(repo: Path, path: str, ctx: Context, run) -> Outcome:
    outside = f"{path} outside its id-keyed entries"
    b_text, o_text, t_text = _stages(repo, path, run)
    (b_head, b_ent, _), (o_head, o_ent, o_order), (t_head, t_ent, t_order) = (_parse_register(path, t) for t in (b_text, o_text, t_text))
    header = _merge_text(repo, run, b_head, o_head, t_head)
    if header is None:
        raise Refused(outside)

    result: dict[str, str | None] = {}
    clashes: list[str] = []
    for ident in {*b_ent, *o_ent, *t_ent}:
        b, o, t = b_ent.get(ident), o_ent.get(ident), t_ent.get(ident)
        if o == t or t == b:
            result[ident] = o
        elif o == b:
            result[ident] = t
        elif b is None:
            result[ident] = t
            clashes.append(ident)
        else:
            raise Refused(f"{path}: entry {ident} changed on both sides")
    number = max((int(i[1:]) for i in {*b_ent, *o_ent, *t_ent}), default=0)

    out = Outcome()
    final: dict[str, str] = {k: v for k, v in result.items() if v is not None}
    added = [i for i in o_order if i not in b_ent and i in final and i not in clashes]
    renumbered: list[tuple[str, str, str]] = []
    for old in sorted(clashes, key=lambda i: int(i[1:])):
        number += 1
        new = f"R{number}"
        text = re.sub(rf"^(\s*- id: ){old}(\s*)$", rf"\g<1>{new}\g<2>", o_ent[old], count=1, flags=re.M)
        final[new] = text
        added.append(new)
        renumbered.append((old, new, text))
    order = [i for i in t_order if i in final] + [i for i in added if i not in t_order]
    order += [i for i in final if i not in order]
    body = "".join(final[i] for i in order)
    if header and not header.endswith("\n") and body:
        header += "\n"
    (repo / path).write_text(header + body)
    _note(out, path)

    for old, new, _ in renumbered:
        found = 0
        for rel in ctx.changed:
            if rel.startswith(RULES_DIR):
                continue
            k, wrote = _rewrite(repo, rel, lambda s, o=old, n=new: re.subn(rf"\b{o}\b", n, s))
            if wrote:
                _note(out, rel)
                found += k
                out.lines.append(f"renumbered {old} to {new} in {rel} ({k} references)")
        if not found:
            out.lines.append(f"renumbered {old} to {new} in {path} (0 references)")
    return out
