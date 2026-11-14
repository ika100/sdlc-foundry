"""Spec 192 test world: a repo whose sources (`gh`, run list, dispatcher files, notifications) are faked, and a runner for
`cplat next`. New modules are imported lazily so that the rest of the suite still collects without them."""
import datetime
import importlib
import json
import subprocess
from pathlib import Path

NOW = datetime.datetime(2026, 11, 14, 10, 0, 0, tzinfo=datetime.timezone.utc)
WRITE_VERBS = {"edit", "comment", "close", "merge", "create", "reopen", "review", "delete"}


def iso(when: datetime.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def spec_text(spec_id, title, *, tracks=(), criteria=3, assumptions=("Use the existing store",), questions=(), created="2026-11-10"):
    acs = "\n".join(f"- **AC-{spec_id.split('-')[0]}.{i}** Given x, when y, then z{i}." for i in range(1, criteria + 1))
    assume = "\n".join(f"- **A{i}** {a} (other option: b)" for i, a in enumerate(assumptions, 1)) or "- none"
    qs = "\n".join(f"- {q}" for q in questions) or "- none"
    return (f"---\nspec_id: {spec_id}\ntitle: {title}\nstatus: draft\nshape: platform\ntracks: {list(tracks)}\n---\n\n"
            f"# {spec_id}\n\n## Problem\n\nProblem text of {title}.\n\n## Acceptance criteria\n\n{acs}\n\n"
            f"## Assumptions\n\n{assume}\n\n## Open questions\n\n{qs}\n\n## Changelog\n\n- {created} created\n")


class World:
    def __init__(self, tmp_path, monkeypatch, shape="platform"):
        self.mp, self.tmp, self.shape = monkeypatch, tmp_path, shape
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        self.slug = "o/n"
        self.gh_calls: list[list[str]] = []
        self.specs: dict[str, str] = {}
        self.prs: list[dict] = []
        self.issues: list[dict] = []
        self.gh_fail: str | None = None
        self.run_rows: list[dict] = []
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_STATE_HOME", str(xdg / "state"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg / "config"))
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        for name in ("LC_ALL", "LC_CTYPE"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        self._git("init", "-q")
        self._git("remote", "add", "origin", f"https://github.com/{self.slug}.git")
        if shape == "platform":
            (self.repo / ".platform-settings.yml").write_text("shape: platform\n")
        else:
            (self.repo / ".copier-answers.yml").write_text(f"_src_path: https://github.com/ika100/sdlc-foundry/templates/{shape}\n")
        self._git("add", "-A")
        self._git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        import needs
        import notify
        import runlist
        import runs
        monkeypatch.setattr(needs, "gh", self._gh)
        monkeypatch.setattr(runs, "utcnow", lambda: NOW)
        monkeypatch.setattr(notify, "now", lambda: NOW)
        monkeypatch.setattr(runlist, "collect", lambda *a, **k: {"schema": 1, "runs": self.run_rows, "store": {}})

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def _gh(self, args):
        self.gh_calls.append(list(args))
        if self.gh_fail:
            raise RuntimeError(self.gh_fail)
        a = list(args)
        if a[0] == "api":
            path = a[1]
            if path.endswith("/contents/docs/specs"):
                return json.dumps([{"name": s, "type": "dir"} for s in self.specs])
            for sid, text in self.specs.items():
                if f"/{sid}/spec.md" in path:
                    return text
            return ""
        if a[:2] == ["pr", "list"]:
            return json.dumps(self.prs)
        if a[:2] == ["issue", "list"]:
            return json.dumps(self.issues)
        return "null"

    def writes(self) -> list[list[str]]:
        return [c for c in self.gh_calls if (len(c) > 1 and c[0] in ("pr", "issue", "release", "label") and c[1] in WRITE_VERBS)
                or ("-X" in c and c[c.index("-X") + 1] != "GET") or "--method" in c]

    def add_draft(self, spec_id, title, *, issue=None, pr=None, created="2026-11-10", criteria=3, **kw):
        self.specs[spec_id] = spec_text(spec_id, title, tracks=[issue] if issue else [], criteria=criteria, created=created, **kw)
        if pr:
            self.prs.append({"number": pr, "body": f"<!-- cplat:spec {spec_id} -->", "createdAt": f"{created}T08:00:00Z",
                             "url": f"https://github.com/{self.slug}/pull/{pr}", "headRefName": f"feature/{spec_id}"})

    def add_issue(self, number, title, created="2026-11-12T08:00:00Z"):
        self.issues.append({"number": number, "title": title, "createdAt": created, "url": f"https://github.com/{self.slug}/issues/{number}",
                            "labels": [{"name": "triage"}], "body": ""})

    def dispatch_item(self, item: dict):
        import dispatch_state
        path = dispatch_state.needs_path(self.slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = json.loads(path.read_text()) if path.exists() else {"items": []}
        doc["items"].append(item)
        path.write_text(json.dumps(doc))

    def stuck(self, number=500, since="2026-11-13T08:00:00Z"):
        self.dispatch_item({"id": f"stuck:{self.slug}:{number}", "kind": "stuck", "stage": "Build", "since": since,
                            "reason": f"the run for #{number} stopped", "command": f"cplat dispatch resume {number}",
                            "object": {"type": "issue", "repo": self.slug, "issue": number, "spec": None, "run_id": None, "component": None,
                                       "version": None, "pr": None, "url": None},
                            "cwd_repo": self.slug, "consequence": None, "way_back": None})

    def budget(self, since="2026-11-14T06:00:00Z"):
        self.dispatch_item({"id": f"budget:{self.slug}:2026-11-14", "kind": "budget", "stage": "Build", "since": since,
                            "reason": "the daily budget is reached", "command": "wait",
                            "object": {"type": "repo", "repo": self.slug, "spec": None, "run_id": None, "issue": None, "component": None,
                                       "version": None, "pr": None, "url": None},
                            "cwd_repo": self.slug, "consequence": None, "way_back": None})

    def notified(self, item_id, minutes_ago, channel="desktop"):
        import dispatch_state
        import notify
        path = notify.state_path(f"dispatch-{dispatch_state.slug_dir(self.slug)}")
        path.parent.mkdir(parents=True, exist_ok=True)
        at = (NOW - datetime.timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
        state = json.loads(path.read_text()) if path.exists() else {"events": {}}
        state["events"][item_id] = {"first_seen": at, "sent": {channel: {"at": at, "ref": "x"}}, "resolved_at": None}
        path.write_text(json.dumps(state))

    def running(self, spec_id="189-x", phase="build"):
        self.run_rows.append({"run_id": f"r-{spec_id}", "kind": "ship", "level": "component", "spec": spec_id, "repo": self.slug,
                              "parent": None, "children": [], "phase": phase, "stopped_in": None, "stage": "Build", "stopped": False,
                              "active": True, "started_at": iso(NOW - datetime.timedelta(minutes=20)), "ended_at": None, "outcome": None,
                              "escalation": None, "failure": None, "budget": None, "activity": None, "pr": None})

    def done_run(self, spec_id, minutes, kind="ship"):
        self.run_rows.append({"run_id": f"d-{spec_id}", "kind": kind, "level": "component", "spec": spec_id, "repo": self.slug,
                              "phase": "done", "active": False, "outcome": "done", "escalation": None, "children": [],
                              "started_at": iso(NOW - datetime.timedelta(hours=5)), "ended_at": iso(NOW - datetime.timedelta(hours=4)),
                              "budget": {"used": {"minutes": minutes}}})

    def notify_yaml(self, text):
        path = Path(self.tmp / "xdg" / "config" / "sdlc-foundry" / "notify.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def local_spec(self, spec_id, title, criteria):
        d = self.repo / "docs" / "specs" / spec_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.md").write_text(spec_text(spec_id, title, criteria=criteria).replace("status: draft", "status: done"))

    def snapshot(self) -> list[str]:
        """Every file under the repo (outside .git), the state dirs and the git refs: what a read-only command must not change."""
        out = []
        for base in (self.repo, self.tmp / "xdg", self.tmp / "home"):
            if base.exists():
                out += [f"{p}:{p.stat().st_size}" for p in sorted(base.rglob("*")) if p.is_file() and ".git/" not in str(p)]
        out.append(subprocess.run(["git", "-C", str(self.repo), "for-each-ref"], capture_output=True, text=True).stdout)
        out.append(subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True, text=True).stdout)
        return out

    def next(self, capsys, *args, repo=None):
        nextcmd = importlib.import_module("nextcmd")
        capsys.readouterr()
        rc = nextcmd.main(["--repo-dir", str(repo or self.repo), *args])
        return rc, capsys.readouterr().out

    def doc(self, capsys, *args, repo=None) -> dict:
        rc, out = self.next(capsys, "--json", *args, repo=repo)
        assert rc == 0
        return json.loads(out)

    def screen(self, capsys, *args, repo=None) -> str:
        rc, out = self.next(capsys, *args, repo=repo)
        assert rc == 0
        return out


def question(doc, qid):
    return next(q for q in doc["questions"] if q["id"] == qid)


def option(q, oid):
    return next(o for o in q["options"] if o["id"] == oid)
