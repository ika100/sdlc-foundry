"""Spec 156 acceptance tests: a system ship benchmark.

Seams: the joint system ship world of spec 144 (`test_144_joint_pr.JointWorld`) for `--until repos`; plain transcript calls
(`transcripts.Call`) for the numbers of a run; the run store of `test_runs` for the stored report.
"""
import datetime
import json

import pytest

import appship_state
import core
import runs_bench
import runs_bench_system as rbs
import runs_usage
import transcripts
from test_144_joint_pr import WEB_SHA, JointWorld
from test_appship_097 import SPEC

T0 = datetime.datetime(2026, 11, 8, 10, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture()
def j(tmp_path, monkeypatch, capsys):
    return JointWorld(tmp_path, monkeypatch, capsys)


def call(minute, agent=None, tokens=100, role="main", second=0):
    return transcripts.Call(key=f"{minute}-{second}-{agent}", at=T0 + datetime.timedelta(minutes=minute, seconds=second),
                            model="claude-sonnet-5-5", failed=False, input=tokens, output=0, cache_read=0, cache_write=0,
                            agent=agent, role=role, cwd=None)


def session(sid, calls):
    return transcripts.Session(session_id=sid, calls=calls, found=True)


# ---------------- AC-156.3: --until repos stops before land, without a cluster ----------------

def test_until_repos_needs_no_kube_context_ac_156_3(j, monkeypatch):  # AC-156.3
    def no_cluster(*a, **kw):
        raise core.PlatformError("no kube context for the product's cluster")
    monkeypatch.setattr(appship_state, "resolve_context", no_cluster)
    r = j.app("start", SPEC, "--until", "repos")
    assert r.rc == 0, r.out
    st = j.state()
    assert st["until"] == "repos" and st["context"] is None


def test_until_repos_ends_done_after_the_repos_and_lands_nothing_ac_156_3(j):  # AC-156.3
    assert j.app("start", SPEC, "--context", "kind-shop", "--until", "repos").rc == 0
    j.entry()
    j.deliver("shop-api")
    j.deliver("shop-web", WEB_SHA)
    assert j.app("next", "--json").json["action"] == "complete"     # not `land`
    r = j.app("complete")
    assert r.rc == 0, r.out
    assert "stopped after the repos (--until repos); nothing landed" in r.out
    assert j.state()["phase"] == "done"
    assert j.dev_merges() == []                                      # the one dev PR stays open
    assert not [c for c in j.made("pr", "create") if any(str(x).startswith("docs/done-") for x in c)]


def test_a_resumed_run_keeps_until_ac_156_3(j):  # AC-156.3
    assert j.app("start", SPEC, "--context", "kind-shop", "--until", "repos").rc == 0
    assert j.app("start", SPEC, "--context", "kind-shop").rc == 0
    assert j.state()["until"] == "repos"


def test_an_unknown_until_is_refused_ac_156_3(j):  # AC-156.3
    with pytest.raises(SystemExit):
        j.app("start", SPEC, "--context", "kind-shop", "--until", "dev")
    with pytest.raises(core.PlatformError, match="unknown stop point"):
        appship_state.start(j.gitops, SPEC, context="kind-shop", until="dev")


def test_without_until_the_run_still_lands_ac_156_3(j):  # AC-156.3
    j.to_land()
    assert j.app("next", "--json").json["action"] == "land"


# ---------------- AC-156.4: the numbers of a run ----------------

def test_repo_numbers_count_wall_agent_tokens_sessions_and_parallel_subagents_ac_156_4(tmp_path):  # AC-156.4
    clone = tmp_path / "bench-files-api"
    (clone / "docs" / "specs" / "003-labels").mkdir(parents=True)
    (clone / "docs" / "specs" / "003-labels" / "spec.md").write_text(
        "---\nspec_id: 003-labels\nparent: acme/bench-files-gitops:950-labels\n---\n\n## Acceptance criteria\n\n"
        "- **AC-003.1** one\n- **AC-003.2** two\n- **AC-003.3** three\n")
    s1 = session("a", [call(0), call(1), call(2, agent="c1", role="coder"), call(5, agent="c1", role="coder"),
                       call(3, agent="c2", role="coder"), call(4, agent="c2", role="coder"), call(20)])
    s2 = session("b", [call(21), call(22)])
    old = session("c", [call(-90)])                                   # before the run: not counted
    n = rbs.repo_numbers("bench-files-api", [s1, s2, old], clone, "acme/bench-files-gitops:950-labels", T0, T0 + datetime.timedelta(hours=1))
    assert n["wall_s"] == 22 * 60
    assert n["agent_s"] == 5 * 60 + 2 * 60          # gaps under two minutes only: 0-5 and 20-22
    assert n["tokens"] == 900 and n["sessions"] == 2
    assert n["criteria"] == 3 and n["parallel_subagents"] == 2
    assert isinstance(n["cost_usd"], float)


def test_overlap_is_the_components_wall_clock_over_the_runs_ac_156_4():  # AC-156.4
    per = [{"repo": "g", "gitops": True, "wall_s": 3000, "tokens": 10, "cost_usd": 1.0},
           {"repo": "a", "gitops": False, "wall_s": 1200, "tokens": 20, "cost_usd": 2.0},
           {"repo": "b", "gitops": False, "wall_s": 1200, "tokens": 30, "cost_usd": None},
           {"repo": "c", "gitops": False, "wall_s": 600, "tokens": 40, "cost_usd": 0.5}]
    w = rbs.run_numbers(per, 2000)
    assert w == {"wall_s": 2000, "tokens": 100, "cost_usd": 3.5, "overlap": 1.5}


def test_the_report_names_every_repo_and_the_spread_ac_156_4():  # AC-156.4
    rows = [{"repo": "bench-files-api", "wall_s": 600, "agent_s": 300, "tokens": 5, "sessions": 2, "criteria": 4, "parallel_subagents": 2}]
    lines = rbs.report([{"outcome": "done", "check": None, "wall_s": 1800, "tokens": 9, "cost_usd": 1.2, "overlap": 1.4, "repos": rows},
                        {"outcome": "done", "check": None, "wall_s": 2400, "tokens": 11, "cost_usd": 1.3, "overlap": 1.1, "repos": rows}])
    text = "\n".join(lines)
    assert "run 1: done, 30.0 min" in text and "overlap 1.4" in text
    assert "bench-files-api" in text and "4 criteria" in text and "2 subagent(s) at once" in text
    assert "wall clock (s): median 2100, spread 1800 to 2400 over 2 done run(s)" in text


# ---------------- AC-156.5: median and spread decide, never one run ----------------

def test_a_difference_inside_the_spread_is_no_gain_ac_156_5():  # AC-156.5
    a = rbs.spread([3000, 3300, 3600])
    b = rbs.spread([2900, 3100, 3500])
    assert "within the spread" in rbs.compare(a, b)


def test_a_difference_beyond_the_spread_is_reported_ac_156_5():  # AC-156.5
    a = rbs.spread([3000, 3100, 3200])
    b = rbs.spread([2000, 2100, 2200])
    assert rbs.compare(a, b) == "-1000: beyond the spread (200)"


def test_one_run_per_side_is_never_a_result_ac_156_5():  # AC-156.5
    assert "not a result" in rbs.compare(rbs.spread([3000]), rbs.spread([1000]))
    assert "no comparison" in rbs.compare(None, rbs.spread([1000]))


def test_the_stored_report_groups_by_plugins_tree_and_compares_the_last_two_ac_156_5():  # AC-156.5
    def rec(commit, wall, tokens, ended):
        return {"schema": 1, "run_id": f"r-{commit}-{wall}", "kind": "benchmark", "outcome": "done", "ended_at": ended,
                "benchmark": {"workflow": "system-ship", "task_version": 1, "plugins": {"commit": commit, "dirty": False},
                              "system": {"wall_s": wall, "tokens": tokens}}}
    records = [rec("aaaaaaa1", 3000, 100, "2026-11-08T10:00:00Z"), rec("aaaaaaa1", 3600, 120, "2026-11-08T11:00:00Z"),
               rec("bbbbbbb2", 1800, 80, "2026-11-08T12:00:00Z"), rec("bbbbbbb2", 2000, 90, "2026-11-08T13:00:00Z")]
    groups = {}
    for r in records:
        label = f"local {r['benchmark']['plugins']['commit'][:7]}"
        g = groups.setdefault(label, {"wall_s": [], "tokens": [], "ended": []})
        g["wall_s"].append(r["benchmark"]["system"]["wall_s"])
        g["tokens"].append(r["benchmark"]["system"]["tokens"])
        g["ended"].append(r["ended_at"])
    shaped = {k: {"wall_s": rbs.spread(v["wall_s"]), "tokens": rbs.spread(v["tokens"]), "last": max(v["ended"])} for k, v in groups.items()}
    lines = rbs.stored_report(shaped)
    assert lines[0].startswith("local aaaaaaa: wall clock median 55.0 min")
    assert lines[-1].startswith("local bbbbbbb against local aaaaaaa: wall clock (s) -1400: beyond the spread (600)")


# ---------------- AC-156.1: one record per run, usage from every sample folder ----------------

def test_usage_registrations_of_several_project_dirs_are_all_kept_ac_156_1(tmp_path, monkeypatch):  # AC-156.1
    monkeypatch.setattr(runs_usage, "_ledger_path", lambda: tmp_path / "ledger.json")
    for d in ("a", "b", "c", "d"):
        runs_usage.register("r1", mode="own", project_dir=str(tmp_path / d))
    runs_usage.register("r1", mode="own", project_dir=str(tmp_path / "a"))   # the same folder again replaces it
    assert sorted(e["project_dir"] for e in runs_usage._load()) == sorted(str(tmp_path / d) for d in "abcd")


def test_the_benchmark_command_dispatches_system_ship_ac_156_1(monkeypatch):  # AC-156.1
    seen = []
    monkeypatch.setattr(rbs, "main", lambda argv: seen.append(argv) or 0)
    assert runs_bench.main(["system-ship", "--repeat", "3"]) == 0
    assert seen == [["--repeat", "3"]]


def test_the_task_pins_a_gitops_repo_and_three_components_with_their_revisions_ac_156_1_ac_156_2():  # AC-156.1, AC-156.2
    task = json.loads((runs_bench.BENCH_DIR / "tasks.json").read_text())["workflows"]["system-ship"]
    assert task["prompt"].endswith("--until repos")
    sys_ = task["system"]
    assert len(sys_["components"]) == 3
    for r in [sys_["gitops"], *sys_["components"]]:
        assert len(r["rev"]) == 40
    for f in (task["spec_file"], task["plan_file"]):
        assert (runs_bench.BENCH_DIR / f).is_file()


def test_the_pinned_plan_has_independent_repos_and_an_ordering_ac_156_2():  # AC-156.2
    import yaml
    task = json.loads((runs_bench.BENCH_DIR / "tasks.json").read_text())["workflows"]["system-ship"]
    text = (runs_bench.BENCH_DIR / task["plan_file"]).read_text()
    meta = yaml.safe_load(text.split("---")[1])
    deps = {r["id"]: set(r.get("depends_on") or []) for r in meta["repos"]}
    comps = [c["repo"].split("/", 1)[1] for c in task["system"]["components"]]
    assert any(deps[c] for c in comps)                                             # some repo waits for another
    independent = [(a, b) for a in comps for b in comps if a < b and a not in deps[b] and b not in deps[a]]
    assert independent                                                             # and two can run at once


def test_the_sample_differs_from_the_journey_system_ac_156_6():  # AC-156.6
    task = json.loads((runs_bench.BENCH_DIR / "tasks.json").read_text())["workflows"]["system-ship"]
    names = [task["system"]["gitops"]["repo"], *[c["repo"] for c in task["system"]["components"]]]
    assert not any("taskboard" in n or "task" in n.split("/", 1)[1] for n in names)
    readme = (runs_bench.BENCH_DIR / "README.md").read_text()
    assert "system-ship" in readme and "a journey only confirms" in readme


def test_the_eval_gate_does_not_require_the_system_benchmark_ac_156_7():  # AC-156.7
    import evalgate
    assert "system-ship" not in json.dumps(getattr(evalgate, "REQUIRED", None) or getattr(evalgate, "WORKFLOWS", None) or [])


# ---------------- found by the first benchmark run ----------------

def test_the_entry_pr_needs_no_body_file_ac_156_1(j):  # AC-156.1 (a headless session may not write the file)
    import subprocess
    from test_appship_097 import GITOPS, git
    j.started()
    assert j.app("repo", "start", GITOPS).rc == 0
    wt = j.common / "cplat-app-ship" / f"{SPEC}-entry"
    (wt / "x.yaml").write_text("x: 1\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "feat(compose): x")
    r = j.app("entry", "pr", GITOPS, "--title", "feat(compose): x")
    assert r.rc == 0, r.out
    create = j.made("pr", "create")[-1]
    body = create[create.index("--body") + 1]
    assert "## Operations of the plan" in body and "- feat(compose): x" in body
    assert subprocess.run(["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True).stdout == ""


def test_a_run_starts_without_the_last_runs_worktrees_and_state_ac_156_1(tmp_path):  # AC-156.1
    import subprocess

    def g(*a, cwd):
        subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
    repo = tmp_path / "bench-files-gitops"
    repo.mkdir()
    g("init", "-q", "-b", "main", cwd=repo)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x", cwd=repo)
    (repo / ".git" / "cplat-app-ship").mkdir()
    g("worktree", "add", "-q", "-b", "compose/001", str(repo / ".git" / "cplat-app-ship" / "001-entry"), cwd=repo)
    (repo / ".git" / "cplat-app-ship.json").write_text("{}")
    (repo / ".git" / "cplat-units.json").write_text("{}")
    rbs.clear_runs(repo)
    assert not list((repo / ".git").glob("cplat-*"))
    g("branch", "-D", "compose/001", cwd=repo)                      # no longer held by a worktree


def test_no_refused_rule_ends_in_the_prefix_syntax_ac_156_1():  # AC-156.1 (Claude Code matched `* main:*` literally)
    import preflight
    rules = preflight.refused_rules("main")
    assert not [r for r in rules if r.endswith(":*)") and "*" in r[:-3]]
    assert "Bash(git push * main)" in rules


def test_a_headless_system_ship_may_work_in_its_component_clones_ac_156_1(j):  # AC-156.1 (found by the benchmark)
    import headless
    dirs = headless.system_clones(j.gitops, [SPEC])
    assert dirs == [str(j.clone("shop-api").absolute()), str(j.clone("shop-web").absolute())]
    cmd = headless.claude_cmd("/system:ship 012", "sonnet", add_dirs=dirs)
    assert cmd[cmd.index("--add-dir") + 1] == dirs[0] and cmd.count("--add-dir") == 2


def test_the_benchmarks_git_calls_retry_a_dropped_network_ac_156_1(monkeypatch):  # AC-156.1 (a run died in `ls-remote`)
    import core
    seen = []

    def fake(cmd, **kw):
        seen.append(kw)
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, "ok", "")
    monkeypatch.setattr(core, "run", fake)
    assert runs_bench.run(["git", "ls-remote", "x"]) == (0, "ok", "")
    assert seen and seen[0]["check"] is False
