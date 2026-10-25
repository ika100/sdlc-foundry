"""`feedback`: turn a problem or idea into a GitHub issue on the platform repo, with diagnostics and without secrets.

Agents and commands tell the user to run `/shared:report-issue` when something fails in a way that looks like a platform
defect. This command drafts the issue (versions, shape, OS, tool availability, the error text) and shows it; with
`--submit` it files it through `gh`, or prints a prefilled browser link when `gh` is missing or not logged in.
Nothing is sent unless `--submit` is passed, and every piece of text goes through `redact()` first.
"""
from __future__ import annotations

import argparse
import os
import platform as pyplatform
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

import core
from core import PlatformError, run

REPO = os.environ.get("CPLAT_FEEDBACK_REPO", "ika100/sdlc-foundry")
MAX_DETAIL_LINES = 80
MAX_DETAIL_CHARS = 6000

_REDACTIONS = [
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), "<github-token>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<aws-key>"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer <redacted>"),
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:password|passwd|secret|token|api[_-]?key|authorization)[A-Z0-9_]*)(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)"), r"\1\2<redacted>"),
    (re.compile(r"\b(?![0-9a-f]{40}\b)(?![0-9a-f]{64}\b)(?!sha-[0-9a-f]{40}\b)[A-Za-z0-9_-]{40,}\b"), "<long-string>"),   # opaque keys; git/docker hashes, image tags (sha-<commit>, spec 091) and paths stay
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    (re.compile(r"/(?:Users|home)/[^/\s]+"), "~"),
]


def redact(text: str) -> str:
    """Remove tokens, passwords, e-mail addresses, home-directory names and long opaque strings."""
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def tail(text: str) -> str:
    lines = text.strip().splitlines()[-MAX_DETAIL_LINES:]
    out = "\n".join(lines)
    return out[-MAX_DETAIL_CHARS:]


def tool_versions() -> dict[str, str]:
    found = {}
    for tool in ("git", "gh", "devbox", "uv", "docker", "kubectl", "k3d"):
        found[tool] = "installed" if shutil.which(tool) else "missing"
    return found


def plugin_versions() -> dict[str, str]:
    try:
        import doctor
        return doctor.installed_plugins()
    except Exception:  # noqa: BLE001  (diagnostics must never fail the report)
        return {}


def diagnostics(repo: Path) -> list[str]:
    lines = [f"- platform: {core.platform_version()}", f"- OS: {pyplatform.system()} {pyplatform.release()} ({pyplatform.machine()})", f"- python: {pyplatform.python_version()}"]
    stamp = core.read_stamp(repo)
    if stamp:
        lines.append(f"- this repo: platform {stamp.get('platform', '?')}, shape {stamp.get('shape', '?')}, ref {stamp.get('ref', '?')}")
    plugins = plugin_versions()
    lines.append("- plugins: " + (", ".join(f"{n} {v}" for n, v in sorted(plugins.items())) or "none found"))
    lines.append("- tools: " + ", ".join(f"{k} {v}" for k, v in tool_versions().items()))
    return lines


def build_body(kind: str, what: str, command: str | None, details: str, repo: Path) -> str:
    parts = [f"**Type:** {kind}", ""]
    parts += ["## What happened" if kind == "bug" else "## The idea", redact(what.strip()) or "_(not provided)_", ""]
    if command:
        parts += ["## Command / step", f"`{redact(command)}`", ""]
    if details.strip():
        parts += ["## Output", "```", redact(tail(details)), "```", ""]
    parts += ["## Environment", *diagnostics(repo), "", "_Filed with `/shared:report-issue`; secrets, e-mail addresses and home-directory names were removed automatically._"]
    return "\n".join(parts)


def browser_url(title: str, body: str, labels: list[str]) -> str:
    return f"https://github.com/{REPO}/issues/new?title={quote(title)}&labels={quote(','.join(labels))}&body={quote(body[:5500])}"


def create_issue(title: str, body: str, labels: list[str]) -> str:
    """`gh issue create` (tests replace this). Retries without labels if the repo lacks them."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
        path = f.name
    try:
        base = ["gh", "issue", "create", "-R", REPO, "--title", title, "--body-file", path]
        label_args = [a for label in labels for a in ("--label", label)]
        proc = run([*base, *label_args], check=False)
        if proc.returncode != 0 and label_args:
            proc = run(base, check=False)
        if proc.returncode != 0:
            raise PlatformError("gh could not create the issue: " + " | ".join((proc.stderr or proc.stdout).strip().splitlines()[-3:]))
        return proc.stdout.strip().splitlines()[-1]
    finally:
        Path(path).unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat feedback", description=__doc__)
    p.add_argument("--kind", choices=["bug", "idea"], default="bug")
    p.add_argument("--title", required=True, help="one line, e.g. 'new-service fails on Python 3.14'")
    p.add_argument("--what", default="", help="what you did, what you expected, what happened")
    p.add_argument("--command", help="the slash command or script that was running")
    p.add_argument("--details-file", help="file with the error output ('-' = stdin)")
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--submit", action="store_true", help="actually file the issue (default: only show the draft)")
    return p


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    details = ""
    if ns.details_file:
        details = sys.stdin.read() if ns.details_file == "-" else Path(ns.details_file).read_text(errors="replace")
    title = redact(ns.title.strip())[:120]
    labels = ["feedback", "bug" if ns.kind == "bug" else "enhancement"]
    body = build_body(ns.kind, ns.what, ns.command, details, Path(ns.repo_dir).resolve())
    print(f"## Draft issue for {REPO}\n\n**{title}**   (labels: {', '.join(labels)})\n\n{body}\n")
    if not ns.submit:
        print("Nothing was sent. If this looks right, run the same command with --submit.")
        return 0
    if not core.has_gh():
        print("`gh` is missing or not logged in. Open this link to file the issue in your browser:\n" + browser_url(title, body, labels))
        return 0
    print("Filed: " + create_issue(title, body, labels))
    return 0
