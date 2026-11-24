"""Spec 222: the UX step is measured on website plans (#1059) and its selection rule is tuned (#1060).

Seams: `runs_bench.run` (git / gh) and `headless.main` are replaced as in the spec 099 tests (the `world` fixture); the
eval gate reads a real git repo under tmp_path with records passed in (`records=`); `cplat spec ux` runs through
`spec.main` on repos named by their `.copier-answers.yml`, as in spec 219's tests."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import core
import evalgate
import runs
import runs_bench
import spec
import spec_ux
from core import PlatformError
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_runs_usage_bench import World, benchmark_records, world  # noqa: F401  (fixtures)
from usage_support import projects  # noqa: F401

ROOT = core.PLATFORM_ROOT
BENCH = ROOT / "scripts" / "cplat" / "benchmark"
CASES = Path(__file__).parent / "fixtures" / "ux_cases.json"
WEB = "ika100-demo/bench-files-web"


def tasks() -> dict:
    return json.loads((BENCH / "tasks.json").read_text())


def web_pin() -> str:
    return next(c["rev"] for c in tasks()["workflows"]["system-ship"]["system"]["components"] if c["repo"] == WEB)


def repo(tmp_path, template: str, name: str = "repo") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / ".copier-answers.yml").write_text(f"_src_path: gh:ika100/sdlc-foundry/templates/{template}\n")
    return root


def put_spec(root: Path, spec_file: str, spec_id: str) -> Path:
    d = root / "docs" / "specs" / spec_id
    d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BENCH / spec_file, d / "spec.md")
    return d


def decide(root: Path, spec_id: str, capsys) -> dict:
    assert spec.main(["--repo", str(root), "ux", spec_id, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def ux_md(d: Path, hash_: str | None = None) -> None:
    s = spec.read(d)
    first = s.active_acs()[0]
    (d / "ux.md").write_text(f"---\nspec_id: {s.id}\nspec_hash: {hash_ or s.ac_hash()}\n---\n\n# UX\n\n## Flows\n\n1. Header → status ({first}).\n\n"
                             "## Screens\n\n- Status page.\n\n## States\n\n- Ready, not ready, checking.\n\n"
                             "## Accessibility\n\n- The button is reachable by keyboard.\n")


def planned_clone(tmp_path, *, ux=True, stale=False, named=True) -> Path:
    """A bench-files-web clone after `/component:plan 902`: spec, ux.md and design.md on the plan branch."""
    clone = repo(tmp_path, "web-nextjs", "bench-files-web")
    (clone / ".git").mkdir()
    task = tasks()["workflows"]["ux-plan"]
    d = put_spec(clone, task["spec_file"], task["spec_id"])
    if ux:
        ux_md(d, "0" * 16 if stale else None)
    (d / "design.md").write_text("# Design\n\nThe screens follow ux.md.\n" if named else "# Design\n\nA client component.\n")
    return clone


# ---------------- AC-222.1: the workflow and its spec ----------------

def test_the_ux_plan_workflow_plans_spec_902_on_the_web_component_ac_222_1(tmp_path, capsys):  # AC-222.1
    t = tasks()
    task = t["workflows"]["ux-plan"]
    assert runs_bench.steps(task) == [("plan", "/component:plan 902")] and task["spec_file"] == "spec-902.md"
    assert runs_bench.sample_of(t, task) == (WEB, web_pin())
    assert runs_bench.sample_of(t, t["workflows"]["build"]) == (t["sample"]["repo"], t["sample"]["rev"])
    meta, _ = spec.load(BENCH / "spec-902.md")
    assert meta["shape"] == "web-nextjs" and meta["spec_id"] == task["spec_id"] and meta["status"] == "approved"
    root = repo(tmp_path, "web-nextjs")
    put_spec(root, task["spec_file"], task["spec_id"])
    assert decide(root, task["spec_id"], capsys)["ux"] == "needed"


def test_a_sample_component_that_is_not_in_system_ship_is_refused_ac_222_1():  # AC-222.1
    with pytest.raises(PlatformError, match="not a system-ship component"):
        runs_bench.sample_of(tasks(), {"sample_component": "ika100-demo/elsewhere"})


# ---------------- AC-222.2: the trusted system-ship clone ----------------

def test_the_clone_is_the_system_ship_one_from_dir_env_or_state_dir_ac_222_2(tmp_path, monkeypatch):  # AC-222.2
    task = tasks()["workflows"]["ux-plan"]
    monkeypatch.setenv("CPLAT_RUNS_DIR", str(tmp_path / "state"))
    assert runs_bench.clone_of("ux-plan", task, str(tmp_path / "bench")) == tmp_path / "bench" / "bench-files-web"
    assert runs_bench.clone_of("ux-plan", task, None) == runs.state_dir() / "benchmark" / "system-ship" / "bench-files-web"
    assert runs_bench.clone_of("build", tasks()["workflows"]["build"], str(tmp_path / "bench")) == runs.state_dir() / "benchmark" / "build"


def test_a_missing_clone_is_refused_with_its_folder_ac_222_2(world, store, tmp_path, monkeypatch):  # AC-222.2
    monkeypatch.setattr(World, "rev", lambda self: web_pin())
    with pytest.raises(PlatformError, match=r"bench-files-web, which does not exist"):
        runs.main(["benchmark", "ux-plan", "--dir", str(tmp_path / "nowhere")])
    assert benchmark_records(store) == [] and world.headless_calls == []


def test_an_untrusted_clone_is_refused_ac_222_2(world, store, tmp_path, monkeypatch):  # AC-222.2
    monkeypatch.setattr(World, "rev", lambda self: web_pin())
    monkeypatch.setattr(runs_bench, "trusted", lambda clone: False)
    (tmp_path / "bench" / "bench-files-web" / ".git").mkdir(parents=True)
    with pytest.raises(PlatformError, match="is not trusted"):
        runs.main(["benchmark", "ux-plan", "--dir", str(tmp_path / "bench")])
    assert world.headless_calls == []


# ---------------- AC-222.3: the result check ----------------

def ok_run(cmd, cwd=None):
    return 0, "", ""


def test_a_plan_with_a_current_named_ux_md_is_done_ac_222_3(tmp_path, monkeypatch):  # AC-222.3
    monkeypatch.setattr(runs_bench, "run", ok_run)
    task = tasks()["workflows"]["ux-plan"]
    assert runs_bench.result("ux-plan", WEB, {}, planned_clone(tmp_path), task) is None


@pytest.mark.parametrize("kw, why", [({"ux": False}, "wrote no ux.md"), ({"stale": True}, "cplat spec ux answers needed"),
                                     ({"named": False}, "neither design.md nor plan.md names ux.md")])
def test_a_plan_without_a_usable_ux_md_fails_naming_it_ac_222_3(tmp_path, monkeypatch, kw, why):  # AC-222.3
    monkeypatch.setattr(runs_bench, "run", ok_run)
    task = tasks()["workflows"]["ux-plan"]
    assert why in runs_bench.result("ux-plan", WEB, {}, planned_clone(tmp_path, **kw), task)


def test_an_invalid_ux_md_fails_with_the_check_error_ac_222_3(tmp_path, monkeypatch):  # AC-222.3
    monkeypatch.setattr(runs_bench, "run", ok_run)
    task = tasks()["workflows"]["ux-plan"]
    clone = planned_clone(tmp_path)
    ux = clone / "docs" / "specs" / task["spec_id"] / "ux.md"
    ux.write_text(ux.read_text().replace("## States", "## Notes"))
    assert "cplat spec check: ux.md: missing section '## States'" in runs_bench.result("ux-plan", WEB, {}, clone, task)


def test_no_plan_branch_fails_ac_222_3(tmp_path, monkeypatch):  # AC-222.3
    monkeypatch.setattr(runs_bench, "run", lambda cmd, cwd=None: (1, "", "error: pathspec did not match"))
    task = tasks()["workflows"]["ux-plan"]
    assert runs_bench.result("ux-plan", WEB, {}, planned_clone(tmp_path), task).startswith("no plan branch feature/902-")


# ---------------- AC-222.4: the record and the reset ----------------

def test_a_ux_plan_run_writes_a_benchmark_record_and_resets_the_sample_ac_222_4(world, store, tmp_path, monkeypatch, capsys):  # AC-222.4
    import headless
    monkeypatch.setattr(World, "rev", lambda self: web_pin())
    bench = tmp_path / "bench"
    clone_ready = {}
    fake = headless.main

    def plan(argv):
        rc = fake(argv)
        clone = Path(argv[argv.index("--repo") + 1])
        task = tasks()["workflows"]["ux-plan"]
        (clone / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/web-nextjs\n")
        d = clone / "docs" / "specs" / task["spec_id"]
        ux_md(d)
        (d / "design.md").write_text("Screens: see ux.md.\n")
        clone_ready["yes"] = True
        return rc
    monkeypatch.setattr(headless, "main", plan)
    (bench / "bench-files-web" / ".git").mkdir(parents=True)
    assert runs.main(["benchmark", "ux-plan", "--dir", str(bench)]) == 0
    (r,) = benchmark_records(store)
    b = r["benchmark"]
    assert r["outcome"] == "done" and b["workflow"] == "ux-plan" and b["sample_repo"] == WEB and b["sample_rev"] == web_pin()
    assert b["reset"] == "done" and r["usage"]["totals"]["calls"] == 2 and clone_ready
    assert world.pushed() and all(c[-1] == f"{web_pin()}:refs/heads/main" for c in world.pushed())
    assert [a[-1] for a in world.headless_calls] == ["/component:plan 902"]


# ---------------- AC-222.5: the Python benchmarks never run the step ----------------

def test_the_build_benchmark_spec_gets_no_ux_step_ac_222_5(tmp_path, capsys):  # AC-222.5
    task = tasks()["workflows"]["build"]
    root = repo(tmp_path, "service-python")
    put_spec(root, task["spec_file"], task["spec_id"])
    assert decide(root, task["spec_id"], capsys)["ux"] == "none"


# ---------------- AC-222.6, AC-222.7: the eval gate ----------------

def git(r, *args):
    return subprocess.run(["git", *args], cwd=r, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def platform(tmp_path):
    r = tmp_path / "platform"
    for f, text in (("plugins/svc/agents/coder.md", "coder\n"), ("plugins/web/agents/ux-designer.md", "ux\n"),
                    ("plugins/web/README.md", "web\n"), ("scripts/cplat/spec_ux.py", "x = 1\n"), ("scripts/x.py", "x = 1\n")):
        (r / f).parent.mkdir(parents=True, exist_ok=True)
        (r / f).write_text(text)
    git(r, "init", "-q", "-b", "main")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    git(r, "tag", "v1.0.0")
    return r


def change(r, path, text):
    (r / path).write_text(text)
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", f"change {path}")
    return git(r, "rev-parse", "HEAD")


def bench(workflow, commit):
    return {"kind": "benchmark", "outcome": "done", "platform_version": "1.0.1", "run_id": f"r-{workflow}",
            "ended_at": "2026-11-24T10:00:00Z", "usage": {"totals": {"input_tokens": 1}},
            "benchmark": {"workflow": workflow, "plugins": {"commit": commit, "dirty": False}}}


def asked(fails: list[str]) -> list[str]:
    return [f.split(":")[0] for f in fails]


@pytest.mark.parametrize("path", ["plugins/svc/agents/coder.md", "scripts/x.py", "plugins/web/README.md"])
def test_without_a_ux_change_the_gate_selects_the_defaults_ac_222_6(platform, path):  # AC-222.6
    change(platform, path, "changed\n")
    changed, fails = evalgate.check(platform, records=lambda d: [])
    assert asked(fails) == (["quick-task", "build"] if path.endswith("coder.md") else [])
    assert evalgate.selected(["plugins/svc/agents/coder.md"], [], None) == evalgate.WORKFLOWS == ("quick-task", "build")


def test_a_web_prompt_also_asks_for_ux_plan_ac_222_7(platform):  # AC-222.7
    c = change(platform, "plugins/web/agents/ux-designer.md", "ux v2\n")
    assert asked(evalgate.check(platform, records=lambda d: [])[1]) == ["quick-task", "build", "ux-plan"]
    assert evalgate.check(platform, records=lambda d: [bench("quick-task", c), bench("build", c), bench("ux-plan", c)])[1] == []


def test_the_ux_rule_alone_asks_only_for_ux_plan_ac_222_7(platform):  # AC-222.7
    c = change(platform, "scripts/cplat/spec_ux.py", "x = 2\n")
    changed, fails = evalgate.check(platform, records=lambda d: [])
    assert changed == ["scripts/cplat/spec_ux.py"] and asked(fails) == ["ux-plan"]
    assert "cplat platform runs benchmark ux-plan --plugins plugins --reset-first" in fails[0]
    assert evalgate.check(platform, records=lambda d: [bench("ux-plan", c)])[1] == []


def test_named_workflows_win_and_rebaseline_keeps_its_two_ac_222_7(platform, monkeypatch):  # AC-222.7
    import rules_rebaseline
    change(platform, "plugins/web/agents/ux-designer.md", "ux v2\n")
    assert asked(evalgate.check(platform, workflows=("ux-plan",), records=lambda d: [])[1]) == ["ux-plan"]
    seen = []
    monkeypatch.setattr(evalgate, "check", lambda repo, base, workflows: seen.append(workflows) or ([], []))
    assert evalgate.main(["--repo", str(platform), "--workflow", "ux-plan"]) == 0 and evalgate.main(["--repo", str(platform)]) == 0
    assert seen == [("ux-plan",), None]
    assert rules_rebaseline.WORKFLOWS == ("quick-task", "build")


# ---------------- AC-222.8, AC-222.9: the words ----------------

@pytest.mark.parametrize("text", [
    "the title input keeps its value", "the row leaves edit mode", "the label reads Done", "the heading says Status",
    "the header has a Status link", "the footer names the version", "keyboard focus is on the button", "the empty state reads None",
    "a loading state appears", "a screen reader announces Saved", "its accessible name is Title", "the colours follow the theme",
    "an error appears", "the user types a title", "a person presses Enter", "the visitor enters a name", "they select a date",
    "the user submits", "a person opens the board", "the user saves"])
def test_widened_words_count_as_visible_ac_222_8(text):  # AC-222.8
    assert spec_ux.visible_word(text)


@pytest.mark.parametrize("text, keep", [
    ("the container image runs as non-root", None), ("the Docker image tag is the version", None), ("the base image scan passes", None),
    ("the JSON fields are id and title", None), ("the response fields stay the same", None), ("a missing field answers 422", None),
    ("the page size is 50", None), ("`GET /api/tasks?page=2` answers", None), ("the `page` parameter is optional", None),
    ("the server logs show one entry", None), ("the metrics show an error", None), ("the response header is no-store", None),
    ("the site keeps serving its pages", None),
    ("the container image runs and the page shows the list", "page")])
def test_vetoed_phrases_do_not_count_but_another_word_does_ac_222_9(text, keep):  # AC-222.9
    assert spec_ux.visible_word(text) == keep


# ---------------- AC-222.10: the labelled cases ----------------

def cases() -> list[dict]:
    return json.loads(CASES.read_text())["cases"]


def test_the_cases_name_their_source_and_cover_both_labels_ac_222_10():  # AC-222.10
    c = cases()
    assert all(x["source"] and x["ux"] in ("needed", "none") for x in c)
    real = [x for x in c if x["criterion"]]
    assert len(real) >= 20 and {x["ux"] for x in real} == {"needed", "none"}


@pytest.mark.parametrize("case", cases(), ids=lambda x: f"{x['source']}:{x['criterion'] or x['text'][:30]}")
def test_every_labelled_case_gets_its_label_ac_222_10(case):  # AC-222.10
    assert ("needed" if spec_ux.visible_word(case["text"]) else "none") == case["ux"]


def test_the_field_keeps_its_answer_whatever_the_criteria_ac_222_10(tmp_path, capsys):  # AC-222.10
    task = tasks()["workflows"]["ux-plan"]
    root = repo(tmp_path, "web-nextjs")
    d = put_spec(root, task["spec_file"], task["spec_id"])
    (d / "spec.md").write_text((d / "spec.md").read_text().replace("shape: web-nextjs\n", "shape: web-nextjs\nux: none\n"))
    assert decide(root, task["spec_id"], capsys)["ux"] == "none"


# ---------------- AC-222.11: the docs ----------------

def test_the_docs_name_the_workflow_and_the_rule_ac_222_11():  # AC-222.11
    readme = (BENCH / "README.md").read_text()
    section = readme.split("## ux-plan", 1)[1].split("\n## ", 1)[0]
    for word in ("bench-files-web", "--dir", "plugins/web/", "spec_ux.py", "ux.md"):
        assert word in section
    ref = (ROOT / "plugins/svc/skills/spec-format/references/spec.md").read_text()
    assert "spec 222" in ref
    assert os.path.exists(ROOT / "docs/specs/222-the-ux-step-is-measured-on-website-plans/spec.md")
