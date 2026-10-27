"""The palette of the console (spec 122, design.md "Console HTTP"): go to, describe a change, add to the model, ask.

  fragment(ctx, q) -> HTML      GET /palette?q=...: go-to results, "Describe a change", "Add to the model" and "Ask"
  ask(ctx, question) -> dict    POST /api/ask: {"answer", "suggestions": [{"command", "repo", "diff"}]}

`ask` runs `claude -p` in the gitops clone with read-only tools only. Commands that Claude proposes come back as
suggestions; nothing runs until the user confirms one (it then goes through /api/actions or /api/preview)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

from console.html import action_button, command_block, esc

ASK_TIMEOUT = 300
GO_LIMIT = 6
READ_ONLY_TOOLS = (
    "Read", "Grep", "Glob",
    "Bash(cplat model show:*)", "Bash(cplat spec list:*)", "Bash(cplat needs:*)",
    "Bash(cplat system status:*)", "Bash(cplat runs:*)",
)
DISALLOWED_TOOLS = ("Edit", "Write", "NotebookEdit")   # the clone's own allowlist adds to --allowedTools; these stay denied
PROMPT = (
    "You answer a question about this system from its gitops clone. You may only read files and run the read-only "
    "`cplat` commands you were given; change nothing. If a change would help, end your answer with one fenced block "
    "per proposed command, using the language tag `command` and one slash command or cplat command inside, for example:\n"
    "```command\n/component:set shop-api --replicas 2\n```\n"
    "The user decides whether it runs.\n\nQuestion: ")
_BLOCK = re.compile(r"```command[ \t]*\n(.*?)```", re.S)
_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "fix", "add", "make", "use", "new", "not", "are", "when"}


# ---------------- data ----------------

def _model(ctx: Any) -> dict:
    data = ctx.data("model")
    return data if isinstance(data, dict) else {}


def _components(ctx: Any) -> list[dict]:
    rows = _model(ctx).get("components")
    return [c for c in rows if isinstance(c, dict) and c.get("name")] if isinstance(rows, list) else []


def _gitops_repo(ctx: Any) -> str:
    system = _model(ctx).get("system")
    if isinstance(system, dict) and system.get("owner") and system.get("name"):
        return f"{system['owner']}/{system['name']}-gitops"
    return ""


def _specs(ctx: Any) -> list[dict]:
    rows: list[dict] = []
    for name in sorted(getattr(ctx, "sources", {}) or {}):
        if name.startswith("specs:") and isinstance(ctx.data(name), list):
            rows += [dict(r, _repo=name[len("specs:"):]) for r in ctx.data(name) if isinstance(r, dict)]
    return rows


def _runs(ctx: Any) -> list[dict]:
    data = ctx.data("runs")
    rows = data.get("runs") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _issues(ctx: Any) -> list[dict]:
    """Issues the needs list knows about (triage items and `issues`): `{"number", "title", "repo", "state"}`."""
    data = ctx.data("needs")
    items = data.get("items") if isinstance(data, dict) else None
    found: dict[Any, dict] = {}
    for it in items if isinstance(items, list) else []:
        obj = it.get("object") if isinstance(it, dict) else None
        if isinstance(obj, dict) and obj.get("issue"):
            found.setdefault(obj["issue"], {"number": obj["issue"], "title": it.get("reason") or "", "repo": obj.get("repo") or "",
                                            "state": "OPEN"})
    listed = data.get("issues") if isinstance(data, dict) else None     # open untracked issues and recently closed ones
    for issue in listed if isinstance(listed, list) else []:
        if isinstance(issue, dict) and issue.get("number") is not None:
            found[issue["number"]] = {"number": issue["number"], "title": issue.get("title") or "", "repo": issue.get("repo") or "",
                                      "state": str(issue.get("state") or "OPEN").upper()}
    return list(found.values())


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower())) - _STOP


# ---------------- go to ----------------

def _hit(label: str, href: str, kind: str, detail: str = "") -> str:
    more = f' <span class="muted">{esc(detail)}</span>' if detail else ""
    return f'<li data-goto="{esc(kind)}"><a href="{esc(href)}" data-open="{esc(href)}">{esc(label)}</a>{more}</li>'


def _go_to(ctx: Any, q: str) -> str:
    needle = q.strip().lower()
    if not needle:
        return ""
    hits: list[str] = []
    for s in _specs(ctx):
        if needle in f"{s.get('id', '')} {s.get('title', '')}".lower():
            hits.append(_hit(f"{s.get('id')} {s.get('title') or ''}".strip(), f"/panel/spec/{quote(str(s.get('_repo')) + ':' + str(s.get('id')), safe='')}",
                             "spec", str(s.get("_repo"))))
    for r in _runs(ctx):
        if needle in f"{r.get('run_id', '')} {r.get('spec', '')}".lower():
            hits.append(_hit(f"Run {r.get('run_id')}", f"/panel/run/{quote(str(r.get('run_id')), safe='')}", "run", str(r.get("spec") or "")))
    for i in _issues(ctx):
        if needle in f"{i['number']} {i['title']}".lower():
            hits.append(_hit(f"#{i['number']} {i['title']}", f"/panel/issue/{quote(str(i['number']), safe='')}", "issue", i["repo"]))
    for c in _components(ctx):
        if needle in str(c["name"]).lower():
            hits.append(_hit(str(c["name"]), "/system", "component", str(c.get("type") or "")))
            for env in c.get("environments") or []:
                ident = quote(f"{c['name']}:{env}", safe="")
                hits.append(_hit(f"{c['name']} in {env}", f"/panel/instance/{ident}", "instance"))
    body = "".join(hits[:GO_LIMIT * 3]) or '<li class="muted">Nothing matches.</li>'
    return f'<section data-palette="goto"><h3>Go to</h3><ul class="plain">{body}</ul></section>'


# ---------------- describe ----------------

def _matching_issues(ctx: Any, sentence: str) -> str:
    words = _words(sentence)
    if not words:
        return ""
    rows = [i for i in _issues(ctx) if i["state"] == "OPEN" and words & _words(i["title"])]
    if not rows:
        return ""
    items = "".join(f'<li data-issue="{esc(i["number"])}"><a href="/panel/issue/{esc(i["number"])}" data-open="/panel/issue/{esc(i["number"])}">'
                    f'#{esc(i["number"])}</a> {esc(i["title"])}</li>' for i in rows)
    return f'<p>Open issues that look related. You can link one in the sentence:</p><ul class="plain" data-matching-issues>{items}</ul>'


def _describe_button(label: str, repo: str, level: str) -> str:
    return action_button("describe", label, None, None, attrs={
        "data_object": json.dumps({"repo": repo}), "data_args": json.dumps({"level": level}),
        "data_confirm": f"Start Claude Code in {repo}?"})


def _describe(ctx: Any, q: str) -> str:
    gitops = _gitops_repo(ctx)
    sentence = q.strip()
    buttons = []
    if gitops:
        buttons.append(f'<li>{_describe_button("System", gitops, "system")} <span class="muted">the whole system, in {esc(gitops)}</span></li>')
    repos = sorted({str(c.get("repo")) for c in _components(ctx) if c.get("repo") and not c.get("external")})
    for repo in repos:
        buttons.append(f'<li>{_describe_button("Component", repo, "component")} <span class="muted">{esc(repo)}</span></li>')
    if gitops:
        buttons.append(f'<li>{_describe_button("Let Claude decide", gitops, "decide")} <span class="muted">Claude picks the level</span></li>')
    if not buttons:
        buttons.append('<li class="muted">The model is not available, so there is no repository to start in.</li>')
    return (f'<section data-palette="describe"><h3>Describe a change</h3>'
            f'<form data-describe onsubmit="return false"><label>What should change? '
            f'<input type="text" class="wide" name="text" value="{esc(sentence)}" placeholder="add a wishlist to the shop"></label>'
            f'{_matching_issues(ctx, sentence)}<ul class="plain">{"".join(buttons)}</ul></form></section>')


# ---------------- add to the model ----------------

def _add(ctx: Any) -> str:
    try:
        from console import system_page
        forms = system_page.model_forms(ctx)
    except (ImportError, AttributeError):
        forms = '<p><a href="/system#add">Open the forms on the System page.</a></p>'
    heading = "" if "<h2>Add to the model</h2>" in forms else "<h3>Add to the model</h3>"
    return f'<section data-palette="add">{heading}{forms}</section>'


# ---------------- ask ----------------

def _ask_form(q: str) -> str:
    return (f'<section data-palette="ask"><h3>Ask</h3><form data-form="ask" data-post="/api/ask" onsubmit="return false">'
            f'<label>Question <input type="text" name="question" value="{esc(q.strip())}" placeholder="why is shop-api slow?"></label> '
            f'<button type="submit" class="btn">Ask</button> '
            f'<span class="muted">Claude only reads; it proposes commands and you confirm them.</span>'
            f'<pre data-result></pre></form></section>')


def fragment(ctx: Any, q: str) -> str:
    """The palette body for the text `q`."""
    return _go_to(ctx, q) + _describe(ctx, q) + _add(ctx) + _ask_form(q)


def _claude() -> str | None:
    path = os.environ.get("CPLAT_CLAUDE")
    if path and Path(path).is_file():
        return path
    return shutil.which("claude")


def _target_repo(ctx: Any, command: str) -> str:
    for c in _components(ctx):
        if re.search(rf"(?<![\w-]){re.escape(str(c['name']))}(?![\w-])", command) and c.get("repo"):
            return str(c["repo"])
    return _gitops_repo(ctx)


def _diff(ctx: Any, command: str) -> str:
    """The `system.yaml` diff of a suggestion that changes the model (through the preview); "" for any other command."""
    from console import preview
    try:
        return preview.diff_of_command(ctx.snapshot(), command)
    except Exception:  # noqa: BLE001 - a suggestion without a diff is still useful; the preview must never break the answer
        return ""


def suggestions_of(ctx: Any, answer: str) -> list[dict]:
    """One suggestion per fenced `command` block; the diff is filled when the preview shows one."""
    out = []
    for block in _BLOCK.findall(answer):
        command = block.strip()
        if command:
            out.append({"command": command, "repo": _target_repo(ctx, command), "diff": _diff(ctx, command)})
    return out


def ask(ctx: Any, question: str) -> dict:
    """Ask Claude (read-only) about the system. Nothing it proposes is started."""
    claude = _claude()
    if not claude:
        return {"answer": "Claude Code is not installed, so I cannot answer. Run /platform:doctor for the fix.", "suggestions": []}
    cwd = ctx.repo_dir if Path(ctx.repo_dir).is_dir() else Path.cwd()
    argv = [claude, "-p", PROMPT + question, "--permission-mode", "plan", "--allowedTools", ",".join(READ_ONLY_TOOLS),
            "--disallowedTools", ",".join(DISALLOWED_TOOLS)]
    try:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=ASK_TIMEOUT, env=os.environ.copy())
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"answer": f"Claude could not answer: {e}", "suggestions": []}
    if done.returncode != 0 and not done.stdout.strip():
        return {"answer": f"Claude failed: {(done.stderr or '').strip()[-400:]}", "suggestions": []}
    answer = done.stdout.strip()
    return {"answer": answer, "suggestions": suggestions_of(ctx, answer)}
