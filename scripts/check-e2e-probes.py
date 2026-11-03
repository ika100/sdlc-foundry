#!/usr/bin/env python3
"""Reject "$$" in strings the e2e scripts send as a pod command (#323; CI guard, `devbox run quality`).

  check-e2e-probes.py [FILE...]     default: tests/e2e/**/*.sh   (exit 0 OK, 1 findings)

Kubernetes turns "$$" into "$" in a pod's command and args before the shell runs, so an indirect expansion or a PID in a probe
script silently becomes something else. A literal "$$" reaches a pod only from a string the local shell does not expand: a
single-quoted string ('...' or $'...'), an escaped "\\$\\$" or "\\$$" in a double-quoted string, or the body of a quoted heredoc
(<<'EOF'). Those are findings. An unquoted or double-quoted "$$" is the local shell's PID and allowed, as are comments.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEREDOC = re.compile(r"<<(-?)\s*(?:'([^']+)'|\"([^\"]+)\"|\\(\w+)|(\w+))")
WORD_START = " \t;&|()"


def scan(text: str) -> list[tuple[int, str]]:
    """(line, kind) for every literal "$$" that a pod command could receive."""
    findings: list[tuple[int, str]] = []
    lines = text.split("\n")
    pending: list[tuple[str, bool, bool]] = []   # heredocs opened on the current line: (delimiter, quoted, strip tabs)
    stack: list[list] = [["code", 0]]             # contexts: [code, paren depth] | [single, line, text] | [double, line, text]
    i = 0
    while i < len(lines):
        line = lines[i]
        j = 0
        while j < len(line):
            c, top = line[j], stack[-1]
            if top[0] == "code":
                if c == "#" and (j == 0 or line[j - 1] in WORD_START):
                    break                                          # a comment: the rest of the line
                if c == "\\":
                    j += 2
                    continue
                if c == "'" or (c == "$" and line[j + 1:j + 2] == "'"):
                    stack.append(["single", i + 1, ""])
                    j += 1 if c == "'" else 2
                    continue
                if c == '"':
                    stack.append(["double", i + 1, ""])
                elif c == "(":
                    top[1] += 1
                elif c == ")":
                    if top[1] == 0 and len(stack) > 1:
                        stack.pop()                                # the end of a $( ) inside a double-quoted string
                    else:
                        top[1] = max(0, top[1] - 1)
                elif line.startswith("<<<", j):                    # a here-string, not a heredoc
                    j += 3
                    continue
                elif line.startswith("<<", j):
                    m = HEREDOC.match(line, j)
                    if m:
                        delim = next(g for g in m.groups()[1:] if g)
                        pending.append((delim, m.group(5) is None, m.group(1) == "-"))
                        j = m.end()
                        continue
                j += 1
            elif top[0] == "single":
                if c == "'":
                    stack.pop()
                    if "$$" in top[2]:
                        findings.append((top[1], "single-quoted string"))
                else:
                    top[2] += c
                j += 1
            else:  # double
                if c == "\\" and j + 1 < len(line):
                    top[2] += "\0" if line[j + 1] == "$" else ""  # \$ is a literal dollar
                    j += 2
                    continue
                if c == "$" and line[j + 1:j + 2] == "(":
                    stack.append(["code", 0])
                    top[2] += " "
                    j += 2
                    continue
                if c == '"':
                    stack.pop()
                    if re.search(r"\0\0|\0\$", top[2]):
                        findings.append((top[1], "double-quoted string with escaped dollars"))
                else:
                    top[2] += c
                j += 1
        if stack[-1][0] != "code":
            stack[-1][2] += "\n"
        i += 1
        for delim, quoted, strip in pending:                       # heredoc bodies follow the line that opened them
            start = i
            while i < len(lines) and (lines[i].lstrip("\t") if strip else lines[i]) != delim:
                i += 1
            hits = [k for k in range(start, i) if "$$" in lines[k]]
            if quoted and hits:
                findings.append((hits[0] + 1, "quoted heredoc"))
            i += 1
        pending = []
    if len(stack) > 1:
        findings.append((stack[-1][1] if stack[-1][0] != "code" else len(lines), "string that never ends (the check lost track)"))
    return findings


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv] or sorted((ROOT / "tests" / "e2e").rglob("*.sh"))
    bad = 0
    for f in files:
        for line, kind in scan(f.read_text(encoding="utf-8")):
            rel = f.resolve().relative_to(ROOT) if f.resolve().is_relative_to(ROOT) else f
            print(f'{rel}:{line}: "$$" in a {kind}: Kubernetes turns "$$" into "$" in a pod\'s command (#323)')
            bad += 1
    if bad:
        return 1
    print(f'OK: no "$$" in a string sent as a pod command ({len(files)} e2e scripts)')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
