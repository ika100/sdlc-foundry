"""The system switcher (spec 122, AC-122.29): the gitops-app repos of the account and its organisations.

  list_systems() -> [{"repo", "clone", "action"}]   `action` is `open` (a local clone exists) or `clone` (clone it first)
  page(ctx, query) -> HTML of `/switch`

An opened system runs its own console: `cplat ui --repo-dir <clone>` starts a new server on its own port."""
from __future__ import annotations

import json
import shlex
import subprocess

from console import actions, layout
from console.html import command_block, esc, freshness

TOPIC = "gitops-app"


def gh(args: list[str]) -> str:
    """Run `gh` and return its output; raises OSError / RuntimeError on failure. Tests replace this function."""
    done = subprocess.run(["gh", *args], capture_output=True, timeout=60, stdin=subprocess.DEVNULL)  # noqa: S603, S607
    if done.returncode != 0:
        raise RuntimeError(done.stderr.decode(errors="replace").strip()[-300:] or f"gh exited {done.returncode}")
    return done.stdout.decode(errors="replace")


def _lines(args: list[str]) -> list[str]:
    return [x.strip() for x in str(gh(args)).splitlines() if x.strip()]


def list_systems() -> list[dict]:
    """The repos with the topic `gitops-app` of the user and of their organisations, with the local clone if any."""
    owners = _lines(["api", "user", "-q", ".login"]) + _lines(["api", "user/orgs", "-q", ".[].login"])
    repos: list[str] = []
    for owner in owners:
        for repo in _lines(["repo", "list", owner, "--topic", TOPIC, "--json", "nameWithOwner", "-q", ".[].nameWithOwner"]):
            if repo not in repos:
                repos.append(repo)
    out = []
    for repo in sorted(repos):
        clone = actions.clone_of(repo)
        have = clone.is_dir()
        out.append({"repo": repo, "clone": str(clone) if have else None, "action": "open" if have else "clone"})
    return out


def _row(entry: dict) -> str:
    repo = entry["repo"]
    if entry["action"] == "open":
        cmd = "cplat ui --repo-dir " + shlex.quote(entry["clone"])
        what = f'<span>Local clone <code>{esc(entry["clone"])}</code></span>'
        act = (f'<button type="button" class="btn primary" data-action="open-system" data-args="{{}}" data-object="{esc(json.dumps({"repo": repo}))}">Open</button>'
               f'{command_block(cmd)}')
    else:
        cmd = shlex.join(["gh", "repo", "clone", repo, str(actions.clone_of(repo))])
        what = "<span>No local clone yet</span>"
        obj = esc(json.dumps({"repo": repo}))
        act = f'<button type="button" class="btn" data-action="clone" data-object="{obj}" data-args="{{}}">Clone first</button>{command_block(cmd)}'
    return f'<li data-system="{esc(repo)}" data-switch="{entry["action"]}"><strong>{esc(repo)}</strong> {what} {act}</li>'


def page(ctx, query: dict[str, str]) -> str:
    """`/switch`: pick another system; a clone is offered first when there is none."""
    try:
        entries, error = list_systems(), None
    except (OSError, RuntimeError, ValueError) as e:
        entries, error = [], str(e)
    if error:
        body = f'<section data-source="gh"><p>The systems cannot be listed: {esc(error)}</p></section>'
    elif not entries:
        body = f'<p>No repository with the topic <code>{TOPIC}</code> found.</p>'
    else:
        body = f'<ul class="list" data-systems>{"".join(_row(e) for e in entries)}</ul>'
    stamp = freshness(ctx.state().get("read_at"))
    html = (f'<h1>Switch system</h1><p>Opening a system starts its own console on a new port; its address is shown here.</p>'
            f'{body}<p>{stamp}</p>')
    return layout.page("Switch system", "system", html, state=ctx.state())
