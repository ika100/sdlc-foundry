"""Spec 206: the refused (deny) rules of an unattended run, a matcher with Claude Code's deny semantics, and the check
of the rules against a sample of commands the run needs and a sample it must refuse.

Stdlib only: `preflight` imports `refused_rules` from here.
"""
from __future__ import annotations

import re


def refused_rules(default_branch: str) -> list[str]:
    d = default_branch
    return [
        "Bash(git push --force*)", "Bash(git push -f*)", "Bash(git push * --force*)", "Bash(git push * -f*)",
        "Bash(git push * +*)", f"Bash(git push * {d})", f"Bash(git push * {d}:*{d}*)", f"Bash(git push * {d}:refs*)", f"Bash(git push * *:{d})",
        f"Bash(git push * *:refs/heads/{d})",
        "Bash(gh pr merge*)",
        "Bash(gh api */pulls/*/merge*)", "Bash(gh api */merges*)", "Bash(gh api *mutation*merge*)",   # spec 206: no read of .mergeable
        "Bash(cplat pr wait *--merge*)",
        "Bash(git rm -f*)", "Bash(git rm --force*)", "Bash(git rm -rf*)", "Bash(git rm -fr*)",
        "Bash(git rm * -f*)", "Bash(git rm * --force*)", "Bash(git rm * -rf*)", "Bash(git rm * -fr*)",
    ]


def must_allow(default: str, branch: str) -> list[str]:
    D, B = default, branch
    return [f"git push -u origin {B}", f"git push origin {B}", "git push origin feature/x-fix", f"git push origin feature/{D}-page",
            f"git push --follow-tags origin {B}", "git push origin v1.2.0", f"git fetch origin {D} && git push origin {B}",
            f"gh pr create --base {D} --head {B} --title t --body-file .pr-body.md", "cplat pr wait 7",
            "cplat pr wait 7 -R acme/shop-api", "gh api repos/acme/x/pulls/7 --jq .mergeable",
            """gh api graphql -f query='{repository(owner:"acme",name:"x"){pullRequest(number:7){mergeStateStatus}}}'""",
            "git switch -c feature/x-force-field", "git rm tests/test_x.py", "git rm -r --cached build"]


def must_refuse(default: str, branch: str) -> list[str]:
    D, B = default, branch
    return [f"git push origin {D}", f"git push -u origin {D}", f"git push origin HEAD:{D}", f"git push origin {D}:{D}",
            f"git push origin {B}:refs/heads/{D}", f"GIT_TRACE=1 git push origin {D}", f"git status && git push origin {D}",
            f"git push --force origin {B}", f"git push -f origin {B}", f"git push origin {B} --force-with-lease",
            f"git push origin +{B}", "gh pr merge 7 --squash", "gh api repos/acme/x/pulls/7/merge -X PUT",
            """gh api graphql -f query='mutation{mergePullRequest(input:{pullRequestId:"x"}){clientMutationId}}'""",
            "cplat pr wait 7 --merge", "git rm -f x", "git rm -rf src"]


# ---------------- the matcher ----------------

WRAPPERS = ("timeout", "time", "nice", "nohup", "stdbuf")
VALUE_OPTIONS = {"timeout": ("-s", "-k"), "nice": ("-n",), "stdbuf": ("-i", "-o", "-e")}
_ASSIGN = re.compile(r"""[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|[^\s"']+)*""")
_DURATION = re.compile(r"\d+(\.\d+)?[smhd]?")
_WORD = re.compile(r"\S+")


def _glob(pat: str, text: str) -> bool:
    if pat.endswith(":*"):
        p = pat[:-2]
        return text == p or text.startswith(p + " ")
    if re.fullmatch(".*".join(re.escape(part) for part in pat.split("*")), text, re.DOTALL):
        return True
    return pat.endswith(" *") and text == pat[:-2]


def _parts(command: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    quote = ""
    i = 0
    while i < len(command):
        c = command[i]
        if quote:
            quote = "" if c == quote else quote
            cur.append(c)
        elif c in "\"'":
            quote = c
            cur.append(c)
        elif command.startswith(("&&", "||"), i):
            parts.append("".join(cur))
            cur = []
            i += 1
        elif c in ";|\n":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _strip_once(text: str) -> str | None:
    """`text` without its first assignment or wrapper (with options), or None when it starts with neither."""
    m = _ASSIGN.match(text)
    if m:
        return text[m.end():].lstrip()
    first = _WORD.match(text)
    if not first or first.group() not in WRAPPERS:
        return None
    wrapper = first.group()
    pos = first.end()
    while True:
        w = _WORD.search(text, pos)
        if not w or not w.group().startswith("-"):
            break
        pos = w.end()
        if w.group() in VALUE_OPTIONS.get(wrapper, ()):
            v = _WORD.search(text, pos)
            if v:
                pos = v.end()
    if wrapper == "timeout":
        w = _WORD.search(text, pos)
        if w and _DURATION.fullmatch(w.group()):
            pos = w.end()
    return text[pos:].lstrip()


def _candidates(command: str) -> list[str]:
    out: list[str] = []
    for base in [command.strip(), *_parts(command)]:
        cur: str | None = base
        while cur:
            out.append(cur)
            cur = _strip_once(cur)
    return out


def refuses(rule: str, command: str) -> bool:
    if rule in ("Bash", "Bash(*)"):
        return True
    if not (rule.startswith("Bash(") and rule.endswith(")")):
        return False
    pat = rule[5:-1]
    return any(_glob(pat, c) for c in _candidates(command))


# ---------------- the check ----------------

def correction(rule: str, rules: list[str], default: str, branches: list[str]) -> str | None:
    if not (rule.startswith("Bash(") and rule.endswith(")")):
        return None
    pat = rule[5:-1]
    for i, ch in enumerate(pat):
        if ch != "*":
            continue
        nxt = pat[i + 1] if i + 1 < len(pat) else None
        last = nxt is None
        edits: list[str] = []
        if nxt is not None and nxt != " ":
            edits.append(pat[:i + 1] + " " + pat[i + 1:])
        if nxt is not None and nxt not in " /":
            edits.append(pat[:i + 1] + "/" + pat[i + 1:])
        if last:
            edits.append(pat[:i])
            if i > 0 and pat[i - 1] != " ":
                edits.append(pat[:i] + " *")
        for cand in edits:
            fixed = f"Bash({cand})"
            if problem([fixed if r == rule else r for r in rules], default, branches) is None:
                return fixed
    return None


def problem(rules: list[str], default: str, branches: list[str]) -> str | None:
    if re.search(r"[*(),\s]", default):
        return f'default branch "{default}" cannot be guarded by a rule'
    for b in branches:
        for command in must_allow(default, b):
            for rule in rules:
                if refuses(rule, command):
                    fix = correction(rule, rules, default, branches) or "remove the rule"
                    return f'{rule} refuses "{command}", which the run needs; use: {fix}'
    for b in branches:
        for command in must_refuse(default, b):
            if not any(refuses(r, command) for r in rules):
                add = next((r for r in refused_rules(default) if refuses(r, command)), f"Bash({command})")
                return f'no rule refuses "{command}"; add: {add}'
    return None
