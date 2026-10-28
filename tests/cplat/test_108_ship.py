"""Spec 108 acceptance tests: ship fix rounds (AC-108.8), spec 102's failure of record (AC-108.9), the CI case of AC-108.10 and
AC-108.7 for the run store. Contract: design.md (CI fix rounds, Spec 102, summaries off)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import core
import ship
from failsum_support import has
from test_budget import TOKEN, budget, here, snapshot_file, start_ship  # noqa: F401  (fixtures and helpers)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import check, git, gh, repo, to_land  # noqa: F401  (fixtures)
from test_ship_checks import gh as checks_gh  # noqa: F401  (fixture: `devbox run ci` red/green)

OFF = "summaries: off (.platform-settings.yml failure_summary: off)"


def ci_log(n: int) -> str:
    """`gh run view 42 --log-failed` for a run whose `test` job failed; `n` changes the timestamps (noise between two rounds)."""
    rows = []

    def r(job, step, text):
        rows.append(f"{job}\t{step}\t2026-10-28T10:1{n}:0{n}.123456{n}Z {text}")
    r("test", "Run tests", "##[group]Run devbox run test")
    for i in range(70):
        r("test", "Run tests", f"NOISE-PASSING-{i:03d}")
    r("test", "Run tests", "/home/runner/work/shop-api/shop-api/src/shop/router.py:58: AssertionError: expected 204, got 200")
    r("test", "Run tests", "FAILED tests/test_shop.py::test_delete - AssertionError: expected 204, got 200")
    r("test", "Run tests", "1 failed, 4 passed in 0.30s")
    r("test", "Run tests", "##[endgroup]")
    r("test", "Run tests", "##[error]Process completed with exit code 1.")
    r("docker", "Build", "OTHERJOB-LINE")
    return "\n".join(rows) + "\n"


@pytest.fixture()
def ci(gh, monkeypatch, tmp_path):  # noqa: F811
    """The scripted gh, with a GitHub Actions log for the failed `test` check; the log cache is in tmp_path."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    state = SimpleNamespace(rounds=0, views=[], cache=tmp_path / "cache" / "sdlc-foundry" / "logs")

    def wrapper(args, *, cwd, check=True):
        if args[:2] == ["run", "view"] and "--log-failed" in args:
            state.rounds += 1
            state.views.append(args)
            return ci_log(state.rounds)
        return gh(args, cwd=cwd, check=check)
    monkeypatch.setattr(ship, "gh", wrapper)
    state.gh = gh
    return state


def saved(ci, suffix):
    return sorted(ci.cache.rglob(f"*-{suffix}.log"))


# ---------------- AC-108.8 ----------------

def test_a_red_check_is_saved_locally_and_the_brief_holds_its_summary_and_log_path_ac_108_8(repo, ci):  # AC-108.8
    to_land(repo, ci.gh)
    ci.gh.checks = [[check("test", "fail"), check("quality", "pass")]]
    ok, lines = ship.land(repo, timeout=600, interval=10)
    assert not ok
    text = "\n".join(lines)
    (log,) = saved(ci, "ci-test")
    assert lines[0].startswith("RED: 1 of 2 check(s) failed on ") and lines[0].endswith(": test")
    assert f"== check: test | format: pytest | command: test / Run tests | exit: 1 | log: {log} | entries: 1" in text
    assert has(text, r"^- tests/test_shop\.py::test_delete at src/shop/router\.py:58 \| AssertionError \| expected <n>, got <n>")
    assert "NOISE-PASSING" not in text and "OTHERJOB-LINE" not in text, "not the raw CI log"
    raw = log.read_text()
    assert "NOISE-PASSING-000" in raw and "AssertionError" in raw and "OTHERJOB-LINE" not in raw, "the failed check's own lines"
    assert len(ci.views) == 1 and ci.views[0][:3] == ["run", "view", "42"] and "--log-failed" in ci.views[0]


def test_a_failed_check_that_is_not_an_actions_run_still_gets_a_header_ac_108_8(repo, ci):  # AC-108.8
    to_land(repo, ci.gh)
    external = {"name": "external", "state": "FAILURE", "bucket": "fail", "link": "https://ci.example.com/build/9"}
    ci.gh.checks = [[check("test", "fail"), external]]
    ok, lines = ship.land(repo, timeout=600, interval=10)
    text = "\n".join(lines)
    assert not ok and lines[0].startswith("RED: 2 of 2 check(s) failed on ")
    assert text.count("== check: ") == 2
    assert "== check: external | " in text and "log: none (not a GitHub Actions run: https://ci.example.com/build/9)" in text
    assert len(saved(ci, "ci-external")) == 0 and len(saved(ci, "ci-test")) == 1


def test_red_ci_logs_and_summaries_never_reach_the_run_store_ac_108_7(repo, ci, store):  # AC-108.7
    to_land(repo, ci.gh)
    ci.gh.checks = [[check("test", "fail"), check("quality", "pass")]]
    ship.land(repo, timeout=600, interval=10)
    assert len(saved(ci, "ci-test")) == 1, "the summary and the log exist locally"
    blob = json.dumps(stored(store))
    assert "NOISE-PASSING" not in blob and "== check:" not in blob and "test_delete" not in blob


# ---------------- AC-108.9 ----------------

def test_budget_normalise_is_the_failsum_rule_ac_108_9():  # AC-108.9
    import budget as budget_module
    import failsum
    assert budget_module.normalise is failsum.normalise
    assert failsum.normalise("2026-10-25T10:01:00Z fail at /tmp/pytest-1/a.py:41 id deadbeef11c0") == \
        budget_module.normalise("2026-10-26T11:02:00Z fail at /tmp/pytest-9/b.py:77 id cafebabe22d0")


def test_a_given_normalized_text_is_the_failure_that_counts_for_no_progress_ac_108_9(here, gh, budget):  # AC-108.9
    start_ship(here)
    norm = "test|AssertionError|expected <n>, got <n>"
    assert budget.attempt(here, "ci", "raw text one: alpha 1", 2, ["test"], normalized=norm) is None
    why = budget.attempt(here, "ci", "raw text two: entirely different beta 2", 2, ["test"], normalized=norm)
    assert why and why.startswith("no progress: ci") and "expected <n>, got <n>" in why
    other = budget.attempt(here, "ci", "same raw", 2, ["test"], normalized="test|ValueError|something else")
    assert other is None, "a different normalized message is not the same failure"


def test_the_snapshot_excerpt_is_the_whole_summary_when_given_ac_108_9(here, gh, budget):  # AC-108.9
    start_ship(here)
    summary = "\n".join(f"SUMROW-{i:04d}" for i in range(60)) + f"\nGH_TOKEN={TOKEN}"
    budget.snapshot(here, "ci", "short raw tail", [], summary=summary)
    data = json.loads(snapshot_file(here).read_text())
    assert "SUMROW-0000" in data["excerpt"] and "SUMROW-0059" in data["excerpt"] and "short raw tail" not in data["excerpt"]
    assert TOKEN not in json.dumps(data) and "<redacted>" in data["excerpt"]


def test_a_land_that_stops_for_no_progress_snapshots_the_summary_ac_108_9(here, ci, budget):  # AC-108.9
    to_land(here, ci.gh)
    ci.gh.checks = [[check("test", "fail"), check("quality", "pass")]]
    ok1, lines1 = ship.land(here, timeout=600, interval=10)
    ok2, lines2 = ship.land(here, timeout=600, interval=10)
    assert not ok1 and not ok2
    stop = [ln for ln in lines2 if "no progress: ci" in ln]
    assert stop and "expected <n>, got <n>" in stop[0], "the reason carries the summary's normalized message"
    assert not any("no progress" in ln for ln in lines1)
    data = json.loads(snapshot_file(here).read_text())
    assert data["stage"] == "ci"
    assert data["excerpt"].startswith("RED: 1 of 2 check(s) failed on ") and "== check: test | format: pytest | " in data["excerpt"]
    assert "NOISE-PASSING" not in data["excerpt"]
    assert ship.load_state(here)["escalated"].startswith("no progress: ci")


def test_attempt_with_an_error_file_uses_the_sidecar_summary_ac_108_9(here, gh, budget):  # AC-108.9
    import failsum
    start_ship(here)
    log = here / "run.log"
    norm = "test|AssertionError|expected <n>, got <n>"
    text = "FAILED (exit 1): devbox run test (log: x)\n== check: test | format: pytest | entries: 1\nSIDECAR-SUMMARY-MARK"
    failsum.sidecar(log).write_text(json.dumps({"text": text, "normalized": norm}))
    codes = []
    for raw in ("first raw content 1", "something else entirely 2"):
        log.write_text(raw)
        codes.append(budget.main(["attempt", "tests", "--failing", "2", "--error-file", str(log)]))
    assert codes == [0, 3]
    assert ship.load_state(here)["escalated"].startswith("no progress: tests")
    assert "SIDECAR-SUMMARY-MARK" in json.loads(snapshot_file(here).read_text())["excerpt"]


def test_attempt_with_an_error_file_without_a_sidecar_behaves_as_before_ac_108_9(here, gh, budget):  # AC-108.9
    start_ship(here)
    log = here / "run.log"
    codes = []
    for n in (4, 3, 2, 1):
        log.write_text(f"FAIL TestPriceAlert at /tmp/x{n}/a_test.go:{40 + n}")
        codes.append(budget.main(["attempt", "tests", "--failing", str(n), "--error-file", str(log)]))
    assert codes == [0, 0, 0, 0]


# ---------------- AC-108.10 (CI) and the pre-push `devbox run ci` ----------------

def test_with_summaries_off_the_red_lines_are_todays_plus_the_off_line_ac_108_10(repo, ci):  # AC-108.10
    to_land(repo, ci.gh)
    (repo / ".platform-settings.yml").write_text("failure_summary: off\n")
    monkey_gh = ci.gh
    monkey_gh.checks = [[check("test", "fail"), check("quality", "pass")]]
    ok, lines = ship.land(repo, timeout=600, interval=10)
    assert not ok
    assert lines[0].startswith("RED: 1 of 2 check(s) failed on ") and lines[1] == OFF
    assert "--- test (run 42) ---" in lines and any("NOISE-PASSING-069" in ln for ln in lines)
    assert not any(ln.startswith("== check:") for ln in lines)
    assert saved(ci, "ci-test") == [], "logs are not saved when summaries are off"


def test_the_pre_push_ci_failure_message_holds_the_summary_and_the_log_path_ac_108_8(repo, checks_gh, tmp_path, monkeypatch):  # AC-108.8
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    (repo / "devbox.json").write_text('{"shell": {"scripts": {"ci": "devbox run quality"}}}')
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", "feature/007-price-alerts")
    (repo / "body.md").write_text("b")
    checks_gh.ci_rc = 1
    with pytest.raises(core.PlatformError) as e:
        ship.open_pr(repo, "feat(alerts): price alerts", repo / "body.md")
    msg = str(e.value)
    (log,) = sorted(cache.rglob("*-ship-ci.log"))
    assert msg.startswith("`devbox run ci` is red; nothing was pushed:\n")
    assert f"== check: ci | format: unknown | command: devbox run ci | exit: 1 | log: {log}" in msg
    assert "Potential secret" in msg and "Potential secret" in log.read_text()
    assert Path(str(log) + ".summary.json").is_file()
    assert checks_gh.pushes == []


def test_the_pre_push_ci_failure_with_summaries_off_says_so_ac_108_10(repo, checks_gh, tmp_path, monkeypatch):  # AC-108.10
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    (repo / "devbox.json").write_text('{"shell": {"scripts": {"ci": "devbox run quality"}}}')
    (repo / ".platform-settings.yml").write_text("failure_summary: off\n")
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", "feature/007-price-alerts")
    (repo / "body.md").write_text("b")
    checks_gh.ci_rc = 1
    with pytest.raises(core.PlatformError) as e:
        ship.open_pr(repo, "feat(alerts): price alerts", repo / "body.md")
    msg = str(e.value)
    assert msg.startswith("`devbox run ci` is red; nothing was pushed:\n" + OFF + "\n")
    assert "Potential secret" in msg and "== check:" not in msg
    assert not list(cache.rglob("*.summary.json"))
