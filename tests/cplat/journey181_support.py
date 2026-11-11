"""Shared helpers of the spec 181 acceptance tests: synthetic transcripts, a fake `gh`, run records and the measure call.

Everything is synthetic: transcripts are written as jsonl under a temporary Claude config dir, run records are passed with
`--records FILE`, and `gh` is a script on PATH that answers `run list` from a file and everything else with `[]`.
"""
import datetime as dt
import json
import os
import stat

import pytest

import runs
from waiting import with_prelude

BASE = dt.datetime(2026, 11, 10, 8, 0, 0, tzinfo=dt.timezone.utc)
START, END = "2026-11-10T08:00:00Z", "2026-11-10T09:00:00Z"
SYSTEM_REPOS = ["ika100-demo/shop-gitops", "ika100-demo/shop-api", "ika100-demo/shop-web"]
COORD = "coordsess"
KINDS = ["ci", "deploy", "promotion", "restore", "cluster", "smoke", "unattributed", "no_transcript"]


def at(minute: float) -> str:
    return (BASE + dt.timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Transcript:
    """Builds one transcript file; times are minutes after 08:00."""

    def __init__(self):
        self.events, self.n = [], 0

    def _id(self):
        self.n += 1
        return f"toolu_{self.n}"

    def model(self, minute):
        self.events.append({"type": "assistant", "timestamp": at(minute),
                            "message": {"id": f"msg_{self._id()}", "content": [{"type": "text", "text": "ok"}], "usage": {}}})
        return self

    def call(self, start, end, name="Bash", **inp):
        i = self._id()
        self.events.append({"type": "assistant", "timestamp": at(start),
                            "message": {"id": f"msg_{i}", "content": [{"type": "tool_use", "id": i, "name": name, "input": inp}],
                                        "usage": {}}})
        self.events.append({"type": "user", "timestamp": at(end),
                            "message": {"content": [{"type": "tool_result", "tool_use_id": i, "content": "ok"}]}})
        return self

    def bash(self, start, end, command):
        return self.call(start, end, "Bash", command=command)

    def prompt(self, minute, text="go on"):
        self.events.append({"type": "user", "timestamp": at(minute), "message": {"content": text}})
        return self

    def write(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(e) + "\n" for e in self.events))
        return path


class World:
    """A temporary Claude config dir, a fake `gh` and a records file."""

    def __init__(self, tmp_path, monkeypatch):
        self.root = tmp_path
        self.projects = tmp_path / "claude" / "projects"
        self.coord_dir = self.projects / "-coord"
        self.records_file = tmp_path / "records.jsonl"
        self.gh_runs = tmp_path / "gh_runs.json"
        self.gh_runs.write_text("[]")
        self.records = []
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
        monkeypatch.delenv("CPLAT_RUNS_REPO", raising=False)
        bindir = tmp_path / "bin"
        bindir.mkdir()
        gh = bindir / "gh"
        gh.write_text(with_prelude(f'#!/bin/sh\nif [ "$1 $2" = "run list" ]; then cat "{self.gh_runs}"; else echo "[]"; fi\n'))
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")

    def coordinator(self, transcript, subagent=None):
        transcript.write(self.coord_dir / f"{COORD}.jsonl")
        if subagent is not None:
            subagent.write(self.coord_dir / COORD / "subagents" / "agent-a.jsonl")
        return str(self.coord_dir / COORD)

    def child(self, session_id, transcript, subagent=None):
        transcript.write(self.projects / "-child" / f"{session_id}.jsonl")
        if subagent is not None:
            subagent.write(self.projects / "-child" / session_id / "subagents" / "agent-c.jsonl")

    def actions_runs(self, *spans):
        self.gh_runs.write_text(json.dumps([{"createdAt": at(a), "startedAt": at(a), "updatedAt": at(b), "conclusion": "success"}
                                            for a, b in spans]))

    def add_records(self, *records):
        self.records += list(records)

    def measure(self, capsys, session, *extra, start=START, end=END, repos=SYSTEM_REPOS):
        """Run the verb with --json and --records; returns (exit code, parsed JSON or None, stderr)."""
        self.records_file.write_text("".join(json.dumps(r) + "\n" for r in self.records))
        capsys.readouterr()
        code = runs.main(["journey", "measure", session, start, end, *repos, "--records", str(self.records_file), "--json", *extra])
        out = capsys.readouterr()
        return code, json.loads(out.out), out.err

    def measure_text(self, capsys, session, *extra, start=START, end=END, repos=SYSTEM_REPOS):
        self.records_file.write_text("".join(json.dumps(r) + "\n" for r in self.records))
        capsys.readouterr()
        code = runs.main(["journey", "measure", session, start, end, *repos, "--records", str(self.records_file), *extra])
        out = capsys.readouterr()
        return code, out.out, out.err


@pytest.fixture()
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def run_record(run_id, kind, start, end, *, repo="ika100-demo/shop-api", sessions=(), phases=(), **extra):
    return {"schema": 1, "run_id": run_id, "kind": kind, "repo": repo, "spec": None, "platform_version": "5.17.0",
            "mode": "headless", "started_at": at(start), "ended_at": at(end),
            "phases": [{"name": n, "started_at": at(a), "ended_at": at(b)} for n, a, b in phases], "ci_rounds": 1, "reruns": [],
            "escalation": None, "filed": [], "outcome": "done", "resumes": None,
            "usage": {"sessions": list(sessions)}, **extra}


def split_of(d):
    """The split object out of a JSON section: asserts that every key is there and the parts add up."""
    assert set(d["waiting"]) == set(KINDS)
    assert set(d["agents"]) == {"coordinator", "children"}
    assert abs(d["person_min"] + d["agents_min"] + d["waiting_min"] - d["wall_min"]) <= 0.1
    return d


def system_ship(world, child_session="child1", *, child_span=(5, 55), phases=()):
    """A system ship run that lists the coordinator and one child record with a repo session."""
    world.add_records(
        run_record("ps1", "product-ship", 0, 60, repo="ika100-demo/shop-gitops", sessions=[COORD], ships=["r1"]),
        run_record("r1", "ship", *child_span, repo="ika100-demo/shop-api", sessions=[child_session], parent="ps1", phases=phases))
