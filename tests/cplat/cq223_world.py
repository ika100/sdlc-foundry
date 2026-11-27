"""Spec 223 test world: a fake `gh` executable first on PATH (so every way of calling it is seen), driven by a JSON state file.

The fake answers the calls of the contract: `gh repo view --json nameWithOwner`, `gh api repos/<slug>/pulls/<n>`,
`gh api repos/<slug>/git/ref/tags/v<X.Y.Z>`, and the fleet reads (`gh api user`, `gh repo list`, `contents/<path>[?ref=<sha>]`,
`commits?path=.platform-version`). A call it does not know fails with a message that no retry rule matches (so no test waits).
State keys: `down` (every call fails as when logged out), `slug`, `prs` ({"812": {"merged_at": ..., "merge_commit_sha": ...}}),
`tags` (["v5.23.0"]), `login`, `login_fails`, `fleet` ({slug: {"answers": bool, "history": ["5.30.1", "5.30.0"]}}, newest first)."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SLUG = "ika100/sdlc-foundry"

SCRIPT = r'''#!{python}
import hashlib, json, os, re, sys

args = sys.argv[1:]
sp = os.environ["FAKE_GH_STATE"]
st = json.load(open(sp))
with open(sp + ".calls", "a") as f:
    f.write(json.dumps(args) + "\n")


def fail(msg, rc=1):
    sys.stderr.write(msg + "\n")
    sys.exit(rc)


def not_found():
    fail("gh: Not Found (HTTP 404)")


if st.get("down"):
    fail("To get started with GitHub CLI, please run:  gh auth login", 4)

query = None
for i, a in enumerate(args):
    if a in ("-q", "--jq") and i + 1 < len(args):
        query = args[i + 1]


def emit(data):
    if query is None:
        print(json.dumps(data))
        return
    if query.startswith(".[]."):
        for item in data:
            print(item[query[4:]])
    else:
        print(data[query[1:]])


def sha(slug, i):
    return hashlib.sha1(f"{{slug}}:{{i}}".encode()).hexdigest()


def path_arg():
    flags = {{"-q", "--jq", "-H", "--header", "-f", "-F", "--field", "-X", "--method", "--input"}}
    skip = False
    for a in args[1:]:
        if skip:
            skip = False
        elif a in flags:
            skip = True
        elif not a.startswith("-"):
            return a
    return ""


if args[:2] == ["repo", "view"]:
    emit({{"nameWithOwner": st.get("slug", "ika100/sdlc-foundry")}})
elif args[:2] == ["repo", "list"]:
    owner = args[2]
    emit([{{"nameWithOwner": s, "isArchived": False, "isFork": False, "defaultBranchRef": {{"name": "main"}}}}
          for s in st.get("fleet", {{}}) if s.startswith(owner + "/")])
elif args[:1] == ["api"]:
    path = path_arg()
    if path == "user":
        if st.get("login_fails"):
            fail("gh: Bad credentials (HTTP 401)", 1)
        emit({{"login": st.get("login", "o")}})
    elif m := re.match(r"repos/[^/]+/[^/]+/pulls/(\d+)$", path):
        pr = st.get("prs", {{}}).get(m.group(1))
        if pr is None:
            not_found()
        emit(pr)
    elif m := re.match(r"repos/[^/]+/[^/]+/git/ref/tags/(v[\d.]+)$", path):
        if m.group(1) not in st.get("tags", []):
            not_found()
        emit({{"ref": "refs/tags/" + m.group(1)}})
    elif m := re.match(r"repos/([^/]+/[^/]+)/commits\?path=\.platform-version", path):
        repo = st.get("fleet", {{}}).get(m.group(1))
        if repo is None or not repo.get("history"):
            not_found()
        emit([{{"sha": sha(m.group(1), i)}} for i in range(len(repo["history"]))])
    elif m := re.match(r"repos/([^/]+/[^/]+)/contents/([^?]+)", path):
        slug, name = m.group(1), m.group(2)
        repo = st.get("fleet", {{}}).get(slug)
        if repo is None:
            not_found()
        if name == ".platform-version" and repo.get("history"):
            wanted = re.search(r"ref=([0-9a-f]{{40}})", " ".join(args))
            idx = 0
            if wanted:
                idx = next((i for i in range(len(repo["history"])) if sha(slug, i) == wanted.group(1)), None)
                if idx is None:
                    not_found()
            print("platform: " + repo["history"][idx])
        elif name == ".copier-answers.yml" and repo.get("answers"):
            print("_src_path: https://github.com/ika100/sdlc-foundry/templates/service-python")
        else:
            not_found()
    else:
        fail("gh: unscripted api call " + path)
else:
    fail("gh: unscripted call " + " ".join(args))
'''


class FakeGh:
    def __init__(self, tmp_path: Path, monkeypatch):
        self.dir = tmp_path / "fakebin"
        self.dir.mkdir()
        self.state_path = tmp_path / "gh-state.json"
        self.state: dict = {"slug": SLUG, "prs": {}, "tags": [], "login": "o", "fleet": {}}
        self.save()
        script = self.dir / "gh"
        script.write_text(SCRIPT.format(python=sys.executable))
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        monkeypatch.setenv("FAKE_GH_STATE", str(self.state_path))
        monkeypatch.setenv("PATH", f"{self.dir}{os.pathsep}{os.environ['PATH']}")

    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.state))

    def set(self, **kw) -> "FakeGh":
        self.state.update(kw)
        self.save()
        return self

    def merged(self, *numbers: int) -> "FakeGh":
        for n in numbers:
            self.state["prs"][str(n)] = {"merged_at": "2026-11-20T10:00:00Z", "merge_commit_sha": "a" * 40}
        return self.set()

    def calls(self) -> list[list[str]]:
        f = Path(str(self.state_path) + ".calls")
        return [json.loads(ln) for ln in f.read_text().splitlines()] if f.is_file() else []


@pytest.fixture()
def fake_gh(tmp_path, monkeypatch):
    return FakeGh(tmp_path, monkeypatch)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                           "-c", "tag.gpgsign=false", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
