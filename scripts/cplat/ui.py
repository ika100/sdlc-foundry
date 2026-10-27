"""cplat ui: the local console (spec 122).

  cplat ui [--repo-dir DIR] [--port N] [--no-open] [--no-notify]
  cplat ui notify …                    the notifier (notify.py): `--loop` or `--once`

Finds `applications/<system>/system.yaml` in the gitops-app clone, serves the console on 127.0.0.1 (a free port unless
`--port`), prints the URL and opens it. SIGINT, SIGTERM or `POST /api/shutdown` stop it; running actions are listed and a
confirmation comes first (AC-122.46)."""
from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

import core
import gitops
import model

CPLAT = Path(__file__).resolve().with_name("cplat.py")


def find_system(repo: Path) -> str | None:
    """The system name of the gitops-app clone, or None when it has no `applications/<system>/system.yaml`."""
    try:
        return gitops.find_app(repo).name
    except (core.PlatformError, model.NotMigrated):
        return None


def gitops_name(repo: Path) -> str | None:
    """`owner/name` of the clone's GitHub repo (a read through `gh`), or None when it cannot be told."""
    from console import mirror
    if not shutil.which("gh"):
        return None
    try:
        name = str(mirror.gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=repo)).strip()
    except (OSError, RuntimeError):
        return None
    return name if "/" in name else None


def confirm_stop(httpd: Any, ask: Any = input) -> None:
    """Stop the server; with running actions, list them and ask first (only on a terminal)."""
    from console import actions, server
    running = actions.running()
    if not running:
        server.stop_later(httpd)
        return
    print(f"{len(running)} action(s) are running:", file=sys.stderr)
    for a in running:
        print(f"  {a.get('id')}  {a.get('command')}", file=sys.stderr, flush=True)
    if not sys.stdin.isatty():
        print("no terminal to ask on: stopping the console, the actions keep running", file=sys.stderr, flush=True)
        server.stop_later(httpd)
        return
    try:
        answer = ask(f"stop {len(running)} actions? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() in ("y", "yes"):
        actions.stop_all()
        server.stop_later(httpd)
    else:
        print("keeping the console running", file=sys.stderr, flush=True)


def start_notifier(repo: Path) -> subprocess.Popen | None:
    try:
        return subprocess.Popen([sys.executable, str(CPLAT), "ui", "notify", "--loop"], cwd=repo,  # noqa: S603
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    except OSError as e:
        print(f"notifier not started: {e}", file=sys.stderr)
        return None


def main(argv: list[str]) -> int:
    if argv and argv[0] == "notify":
        import notify   # task 20; imported only when asked for
        return notify.main(argv[1:])
    ap = argparse.ArgumentParser(prog="cplat ui", description=__doc__.splitlines()[0])
    ap.add_argument("--repo-dir", default=".", help="the gitops-app clone (default: the current directory)")
    ap.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: a free one)")
    ap.add_argument("--no-open", action="store_true", help="do not open the browser")
    ap.add_argument("--no-notify", action="store_true", help="do not start the notifier")
    ns = ap.parse_args(argv)
    repo = Path(ns.repo_dir).resolve()
    system = find_system(repo)
    if system is None:
        print(f"ERROR: no applications/<system>/system.yaml in {repo}", file=sys.stderr)
        print("  fix: run it inside a gitops-app clone, or pass --repo-dir <clone>", file=sys.stderr)
        return 1

    import runs
    from console import mirror as mirror_mod, server, sources
    holder: dict[str, Any] = {}

    def snapshot(name: str | None) -> Path:
        mirrored = holder["mirror"].snapshot(name) if "mirror" in holder else None
        return mirrored or repo

    name = gitops_name(repo)
    found = sources.default_sources(repo, snapshot)
    found[f"specs:{name}" if name else "specs:gitops"] = sources.spec_source(name, snapshot)
    refresher = sources.Refresher(found, snapshot)
    mirror = None
    if name:
        mirror = mirror_mod.Mirror(system, name, lambda: sources.system_repos(found["model"].data),
                                   lambda names: threading.Thread(target=refresher.refresh, args=(names,), daemon=True).start(),
                                   runs.state_dir)
        holder["mirror"] = mirror
    try:
        httpd = server.make_server(repo, found, port=ns.port, mirror=mirror)
    except OSError as e:
        print(f"ERROR: cannot listen on 127.0.0.1:{ns.port}: {e}", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"console: {url}", flush=True)

    refresher.start()
    if mirror:
        mirror.start()
    notifier = None if ns.no_notify else start_notifier(repo)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: threading.Thread(target=confirm_stop, args=(httpd,), daemon=True).start())
    if not ns.no_open:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        httpd.serve_forever()
    finally:
        refresher.stop()
        if mirror:
            mirror.stop()
        if notifier and notifier.poll() is None:
            notifier.terminate()
        httpd.server_close()
    return 0
