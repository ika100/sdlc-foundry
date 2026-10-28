"""GitOps parsers (gitops-app): the template scripts' `ERROR:` lines, kustomize, kubeconform and Kyverno (spec 108, t3)."""
from __future__ import annotations

import re

from failsum.core import Context, Entry, FuncParser, Result, message

_ERR = re.compile(r"^ERROR: (?P<file>[^\s:]*[./][^\s:]*)(?::(?P<where>[^\s:]+))?: (?P<msg>.+)$")
_DRIFT = re.compile(r"rendered files are out of date")
_DRIFT_FILE = re.compile(r"^\s*(?:[-*]\s+)?(?P<file>[^\s:]+\.\w+)\s*$")


def gitops_scripts(lines: list[str], ctx: Context) -> Result | None:
    entries = []
    for i, ln in enumerate(lines):
        m = _ERR.match(ln)
        if m:
            f = ctx.own(m.group("file")) or m.group("file")
            where, msg = m.group("where"), m.group("msg")
            if where and not where.isdigit():
                msg = f"{where}: {msg}"
                where = None
            entries.append(Entry(i, False, f"{f}:{where}" if where else f, None, "error", message(msg)))
        elif _DRIFT.search(ln):
            for j in range(i + 1, len(lines)):
                d = _DRIFT_FILE.match(lines[j])
                if not d:
                    if lines[j].strip():
                        break
                    if j > i + 1:
                        break
                    continue
                f = ctx.own(d.group("file")) or d.group("file")
                entries.append(Entry(j, False, f, None, "render-drift", "rendered file is out of date"))
    return Result(tuple(entries)) if entries else None


_KUST_BUILD = re.compile(r"(?:^|\s)kustomize build (?P<dir>\S+)")
_KUST_ERR = re.compile(r"^Error: (?P<msg>.+)$")


def kustomize(lines: list[str], ctx: Context) -> Result | None:
    entries, current = [], None
    for i, ln in enumerate(lines):
        b = _KUST_BUILD.search(ln)
        if b:
            current = b.group("dir")
            continue
        m = _KUST_ERR.match(ln)
        if m and current:
            entries.append(Entry(i, False, ctx.own(current) or current, None, "error", message(m.group("msg"))))
            current = None
    return Result(tuple(entries)) if entries else None


_KC = re.compile(r"^(?P<file>\S+) - (?P<kind>\w+) (?P<name>\S+) (?:is invalid|failed validation): (?P<msg>.*)$")
_KC_TOTAL = re.compile(r"^Summary: .*Invalid: (?P<inv>\d+), Errors: (?P<err>\d+)")


def kubeconform(lines: list[str], ctx: Context) -> Result | None:
    entries, reported = [], None
    for i, ln in enumerate(lines):
        t = _KC_TOTAL.match(ln)
        if t:
            reported = int(t.group("inv")) + int(t.group("err"))
        m = _KC.match(ln)
        if m:
            f = ctx.own(m.group("file")) or m.group("file")
            entries.append(Entry(i, False, f, None, "invalid",
                                 message(f"{m.group('kind')} {m.group('name')}: {m.group('msg')}")))
    return Result(tuple(entries), reported) if entries else None


_KY_HEAD = re.compile(r"^POLICY VIOLATION in (?P<dir>.+?) \((?P<env>[^)]+)\):\s*$")
_KY_POLICY = re.compile(r"^\s+policy (?P<policy>\S+) -> resource (?P<res>\S+) failed:\s*$")
_KY_RULE = re.compile(r"^\s+(?P<rule>[\w.-]+): (?P<msg>.+)$")


def kyverno(lines: list[str], ctx: Context) -> Result | None:
    entries, scope, policy = [], None, None
    for i, ln in enumerate(lines):
        h = _KY_HEAD.match(ln)
        if h:
            scope, policy = f"{ctx.own(h.group('dir')) or h.group('dir')} ({h.group('env')})", None
            continue
        if scope is None:
            continue
        p = _KY_POLICY.match(ln)
        if p:
            policy = (p.group("policy"), p.group("res"))
            continue
        r = _KY_RULE.match(ln)
        if r and policy:
            entries.append(Entry(i, False, f"{scope} {policy[1]}", None, policy[0], message(f"{r.group('rule')}: {r.group('msg')}")))
    return Result(tuple(entries)) if entries else None


PARSERS: tuple = (FuncParser("gitops-scripts", gitops_scripts), FuncParser("kustomize", kustomize),
                  FuncParser("kubeconform", kubeconform), FuncParser("kyverno", kyverno))
