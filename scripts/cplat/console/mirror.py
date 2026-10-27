"""Snapshots of each system repo's `main` and of its draft spec pull requests (spec 122, design.md Decisions).

The console never reads a working tree. `Mirror` downloads `main` through `gh api repos/<o>/<r>/tarball/<sha>` into
`${XDG_CACHE_HOME:-~/.cache}/sdlc-foundry/console/<system>/<owner>__<repo>/<sha>/`, adds the `docs/specs/<id>/` folders of
open draft spec pull requests (with `.cplat-draft-pr.json`), polls the `main` sha every 15 s and watches the run records.
A change calls `on_change(names)` with the sources to read again. Traffic goes only through `gh`."""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import threading
from collections.abc import Callable
from pathlib import Path

POLL_EVERY = 15.0
MARKER = re.compile(r"<!--\s*cplat:spec\s+(\S+)\s*-->")
SAFE = re.compile(r"^[\w.-]+$")


def gh(args: list[str], *, cwd: Path | None = None, binary: bool = False) -> bytes | str:
    """Run `gh`; raises OSError / RuntimeError when it is missing or fails. Tests replace this function."""
    done = subprocess.run(["gh", *args], capture_output=True, cwd=cwd, timeout=120, stdin=subprocess.DEVNULL)  # noqa: S603, S607
    if done.returncode:
        raise RuntimeError(done.stderr.decode(errors="replace").strip()[-300:] or f"gh exited {done.returncode}")
    return done.stdout if binary else done.stdout.decode()


def cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "sdlc-foundry" / "console"


def _extract(data: bytes, dest: Path, only: str | None = None) -> None:
    """Unpack a GitHub tarball into `dest`, dropping the top folder; with `only`, just that folder (`docs/specs/<id>`)."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts[1:]
            if not parts or ".." in parts or not (member.isfile() or member.isdir()):
                continue
            rel = Path(*parts)
            if only and not (rel == Path(only) or Path(only) in rel.parents):
                continue
            target = dest / rel
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            source = tar.extractfile(member)
            if source is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
            if member.mode & 0o111:
                target.chmod(target.stat().st_mode | 0o111)


class Mirror:
    """Snapshots of `repos` (`owner/name`) under the cache of one system; `gitops` is the gitops repo's own name."""

    def __init__(self, system: str, gitops: str | None, repos: Callable[[], list[str]], on_change: Callable[[list[str]], None],
                 runs_dir: Callable[[], Path] | None = None):
        self.system, self.gitops, self.repos, self.on_change = system, gitops, repos, on_change
        self.runs_dir = runs_dir
        self.shas: dict[str, str] = {}
        self.paths: dict[str, Path] = {}
        self.runs_mtime = 0.0
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def all_repos(self) -> list[str]:
        names = list(self.repos())
        if self.gitops and self.gitops not in names:
            names.insert(0, self.gitops)
        return names

    def snapshot(self, repo: str | None) -> Path | None:
        """The directory of the newest snapshot of `repo` (None = the gitops repo), or None before the first download."""
        return self.paths.get(repo or self.gitops or "")

    def folder(self, repo: str, sha: str) -> Path:
        return cache_root() / self.system / repo.replace("/", "__") / sha

    def fetch(self, repo: str, sha: str) -> Path:
        """Download `main` at `sha` plus the spec folders of draft spec pull requests."""
        dest = self.folder(repo, sha)
        if not dest.is_dir():
            tmp = dest.with_name(dest.name + ".part")
            shutil.rmtree(tmp, ignore_errors=True)
            _extract(gh(["api", f"repos/{repo}/tarball/{sha}"], binary=True), tmp)       # type: ignore[arg-type]
            self._add_drafts(repo, tmp)
            tmp.rename(dest)
        return dest

    def _add_drafts(self, repo: str, into: Path) -> None:
        try:
            listing = json.loads(gh(["pr", "list", "--repo", repo, "--state", "open", "--draft", "--json",
                                     "number,url,headRefName,body"]))
        except (OSError, RuntimeError, ValueError):
            return
        for pr in listing if isinstance(listing, list) else []:
            found = MARKER.search(pr.get("body") or "")
            ref = pr.get("headRefName") or ""
            if not found or not SAFE.match(found.group(1)) or not ref:
                continue
            spec_id = found.group(1)
            try:
                data = gh(["api", f"repos/{repo}/tarball/{ref}"], binary=True)
                _extract(data, into, only=f"docs/specs/{spec_id}")                       # type: ignore[arg-type]
            except (OSError, RuntimeError, tarfile.TarError):
                continue
            folder = into / "docs" / "specs" / spec_id
            if folder.is_dir():
                (folder / ".cplat-draft-pr.json").write_text(json.dumps({"number": pr.get("number"), "url": pr.get("url")}))

    def poll(self) -> list[str]:
        """One round: new `main` shas and changed run records. Returns the sources it asked to be read again."""
        stale: list[str] = []
        for repo in self.all_repos():
            try:
                sha = str(gh(["api", f"repos/{repo}/commits/main", "-q", ".sha"])).strip()
                if sha and sha != self.shas.get(repo):
                    path = self.fetch(repo, sha)
                    self.shas[repo], self.paths[repo] = sha, path
                    if repo == self.gitops:
                        stale += ["model", "status", "needs"]
                    stale.append(f"specs:{repo}")
            except (OSError, RuntimeError, tarfile.TarError):
                continue
        mtime = self._runs_mtime()
        if mtime != self.runs_mtime:
            self.runs_mtime = mtime
            stale += ["runs", "needs"]
        names = sorted(set(stale))
        if names:
            self.on_change(names)
        return names

    def _runs_mtime(self) -> float:
        if self.runs_dir is None:
            return 0.0
        active = self.runs_dir() / "active"
        try:
            return max([active.stat().st_mtime, *(p.stat().st_mtime for p in active.iterdir())])
        except OSError:
            return 0.0

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            self.poll()
            self.stop_event.wait(POLL_EVERY)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name="mirror", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
