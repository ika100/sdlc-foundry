"""Spec 087: every run is recorded in a private run store (record API, buffer, flush, CLI, ship/pr/headless/doctor)."""
import datetime as dt
import json
import subprocess
import sys

import pytest

import cplat
import core
import doctor
import feedback
import headless
import pr as prmod
import runs
import runs_store
import ship
from test_headless import fake_claude, repo as hl_repo, set_state  # noqa: F401  (fixture)
from test_ship import check, git, repo, to_land  # noqa: F401  (fixtures)
from test_ship import gh  # noqa: F401  (fixture)
from test_spec import SPEC, make
from test_tags_and_wait import Gh as TaggedGh
from test_tags_and_wait import fake  # noqa: F401  (fixture)

ROOT = core.PLATFORM_ROOT
SECRET = "GH_TOKEN=ghp_abc123abc123abc123abc123abc123"
BEARER = "Authorization: Bearer abcdefghijklmnop1234567890"


# ---------------- fakes ----------------

class Clock:
    """Fake wall and monotonic time for `runs.utcnow` / `runs.monotonic` (no real sleeping)."""

    def __init__(self):
        self.now = dt.datetime(2026, 10, 24, 8, 0, 0, tzinfo=dt.timezone.utc)
        self.mono = 0.0

    def utcnow(self):
        return self.now

    def monotonic(self):
        return self.mono

    def set(self, iso: str):
        self.now = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))

    def tick(self, seconds: float):
        self.now += dt.timedelta(seconds=seconds)


class MemStore:
    """An in-memory `runs_store.Store`; files are keyed by path, like the real repo."""

    def __init__(self, slug="acme/runs"):
        self.slug = slug
        self.vis = "private"
        self.exists = True
        self.reachable = True
        self.reject = False                 # a rejected write: visibility works, put fails
        self.fail_after_write = False       # an interrupted flush: the files land, then the call fails
        self.created = False
        self.files: dict[str, str] = {}
        self.puts: list[dict] = []
        self.cost = 0.0                     # fake seconds that each call takes
        self.clock = None

    def _spend(self):
        if self.clock:
            self.clock.mono += self.cost

    def visibility(self, deadline=None):
        self._spend()
        if not self.reachable:
            raise runs_store.StoreUnreachable("offline")
        if not self.exists:
            raise runs_store.StoreMissing("not found")
        return self.vis

    def create_private(self):
        self.created, self.exists, self.vis = True, True, "private"

    def put(self, files, message, deadline=None):
        self._spend()
        if not self.reachable or self.reject:
            raise runs_store.StoreUnreachable("write rejected")
        self.puts.append(dict(files))
        self.files.update(files)
        if self.fail_after_write:
            raise runs_store.StoreUnreachable("interrupted")

    def read(self, days, deadline=None):
        wanted = {d.isoformat() for d in days}
        out = []
        for path, text in sorted(self.files.items()):
            _, y, m, d, _name = path.split("/", 4)
            if f"{y}-{m}-{d}" in wanted:
                out.append((path, text))
        return out


@pytest.fixture()
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(runs, "utcnow", c.utcnow)
    monkeypatch.setattr(runs, "monotonic", c.monotonic)
    return c


@pytest.fixture()
def mem(clock):
    s = MemStore()
    s.clock = clock
    return s


def attach(monkeypatch, s):
    monkeypatch.setenv("CPLAT_RUNS_REPO", s.slug)
    monkeypatch.setattr(runs, "open_store", lambda slug: s)


@pytest.fixture()
def store(mem, monkeypatch):
    attach(monkeypatch, mem)
    return mem


def stored(s):
    """Records in the store (follow-up lines excluded), oldest first."""
    out = [json.loads(text) for path, text in sorted(s.files.items()) if ".filed." not in path]
    return sorted(out, key=lambda r: r["ended_at"])


def followups(s):
    return [json.loads(text) for path, text in sorted(s.files.items()) if ".filed." in path]


def buffered_lines():
    f = runs.state_dir() / "buffer.jsonl"
    return [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()] if f.is_file() else []


def warnings(capsys):
    err = capsys.readouterr().err
    return [ln for ln in err.splitlines() if ln.startswith("WARNING")]


def one_run(kind="ship", outcome="done", **kw):
    rid = runs.start(kind, repo=kw.pop("repo", "acme/shop-api"), spec=kw.pop("spec", None))
    assert rid
    runs.finish(rid, outcome, **kw)
    return rid


# ---------------- AC-087.1 ship records ----------------

def test_a_done_ship_run_appends_exactly_one_record(repo, gh, store, clock):
    """AC-087.1: a ship run that ends in phase done appends one `ship` record with every phase it entered, in order."""
    to_land(repo, gh, merge=False)
    clock.tick(60)
    gh.checks = [[check("test", "pass")]]
    ok, _ = ship.land(repo, timeout=60, interval=10)
    assert ok and ship.load_state(repo)["phase"] == "done"
    ship.finish(repo)                                    # archiving a recorded run adds nothing
    recs = stored(store)
    assert len(recs) == 1
    r = recs[0]
    assert (r["schema"], r["kind"], r["spec"], r["outcome"], r["escalation"]) == (1, "ship", "007-price-alerts", "done", None)
    assert r["repo"] == "acme/shop-api" and r["mode"] == "interactive" and r["resumes"] is None
    names = [p["name"] for p in r["phases"]]
    assert names[:2] == ["build", "land"]
    assert all(p["started_at"] and p["ended_at"] for p in r["phases"])
    assert r["started_at"] and r["ended_at"]


def test_the_record_carries_every_field_of_the_contract(store, clock):
    """AC-087.1: the record is one JSON line with the schema-1 fields in contract order."""
    rid = one_run("ship", spec="007-price-alerts")
    (path, text), = store.files.items()
    assert path == f"runs/2026/10/24/{rid}.json" and text.endswith("\n") and text.count("\n") == 1
    r = json.loads(text)
    assert list(r)[:17] == ["schema", "run_id", "kind", "repo", "spec", "platform_version", "mode", "started_at", "ended_at",
                            "phases", "ci_rounds", "reruns", "escalation", "filed", "outcome", "resumes", "parent"]
    assert r["platform_version"] == core.platform_version() and r["ci_rounds"] == 0 and r["reruns"] == [] and r["filed"] == []


# ---------------- AC-087.3 take-over ----------------

def other_spec(repo):
    d = repo / "docs" / "specs" / "008-other-thing"
    d.mkdir(parents=True)
    text = SPEC.format(status="approved", questions="None.").replace("007-price-alerts", "008-other-thing").replace("AC-007", "AC-008")
    (d / "spec.md").write_text(text.replace("tracks: [42]\n", ""))


def test_taking_over_ends_the_other_run_as_abandoned(repo, store):
    """AC-087.3: a ship of another spec that takes over an unfinished run gives it one `abandoned` record."""
    ship.start(repo, "7", True)
    other_spec(repo)
    with pytest.raises(core.PlatformError) as e:
        ship.start(repo, "8", True)
    assert "--take-over" in (e.value.hint or "")
    assert stored(store) == []
    ship.start(repo, "8", True, take_over=True)
    recs = stored(store)
    assert [(r["spec"], r["outcome"]) for r in recs] == [("007-price-alerts", "abandoned")]
    assert ship.load_state(repo)["spec"] == "008-other-thing"


def test_finishing_an_unfinished_run_records_it_abandoned(repo, store):
    """AC-087.3: `cplat ship finish` of an unfinished, unrecorded run records it abandoned."""
    ship.start(repo, "7", True)
    ship.finish(repo)
    assert [r["outcome"] for r in stored(store)] == ["abandoned"]


# ---------------- AC-087.4 CI rounds and reruns ----------------

class RerunGh(TaggedGh):
    def __call__(self, args, *, cwd, check=True):
        if args[:2] == ["run", "cancel"]:
            self.calls.append(args)
            return ""
        if args[:2] == ["run", "view"] and "-q" in args:
            self.calls.append(args)
            return "completed"
        return super().__call__(args, cwd=cwd, check=check)


@pytest.fixture()
def rgh(gh, monkeypatch):
    g = RerunGh()
    g.merges = gh.merges
    monkeypatch.setattr(ship, "gh", g)
    return g


def queued(name):
    return {"name": name, "state": "QUEUED", "bucket": "pending", "link": f"https://github.com/acme/shop-api/actions/runs/42/job/{name}"}


def test_ci_rounds_and_reruns_are_counted_in_the_record(repo, rgh, store):
    """AC-087.4: two red conclusions then green is 3 CI rounds; a stuck run and a transient failure are named in `reruns`."""
    to_land(repo, rgh, merge=False)
    rgh.checks = [[check("test", "fail")]]
    rgh.logs["42"] = ["--- FAIL: TestPriceAlert", "expected 3, got 4"]
    assert not ship.land(repo, timeout=600, interval=10, queue_timeout=20)[0]
    rgh.checks = [[queued("e2e")]] * 6 + [[check("e2e", "fail")]]
    assert not ship.land(repo, timeout=600, interval=10, queue_timeout=20)[0]
    maven = "[ERROR] Failed to read artifact descriptor for org.apache.maven.shared:maven-shared-utils:jar:3.4.2"
    rgh.logs["42"] = [maven]
    rgh.checks = [[check("java", "fail")], [check("java", "fail")], [check("java", "pending")], [check("java", "pass")]]
    assert ship.land(repo, timeout=600, interval=10, queue_timeout=20)[0]
    (r,) = stored(store)
    assert r["outcome"] == "done" and r["ci_rounds"] == 3
    assert r["reruns"] == [{"check": "e2e", "reason": "stuck"}, {"check": "java", "reason": "transient"}]


# ---------------- AC-087.5 build and pr wait ----------------

URL = "https://github.com/acme/other/pull/5"


def test_pr_wait_outside_a_ship_run_records_done_on_green(repo, fake, store):
    """AC-087.5: green is a `pr-wait` record with outcome done."""
    fake.checks = [[check("quality", "pending")], [check("quality", "pass")]]
    ok, _ = prmod.wait(repo, URL, False, 600, 10, 300)
    assert ok
    (r,) = stored(store)
    assert (r["kind"], r["outcome"], r["ci_rounds"]) == ("pr-wait", "done", 1)


def test_pr_wait_records_an_already_merged_pr_as_done(repo, fake, store):
    """AC-087.5: merged is done."""
    fake.state = "MERGED"
    assert prmod.wait(repo, URL, False, 600, 10, 300)[0]
    assert [(r["kind"], r["outcome"]) for r in stored(store)] == [("pr-wait", "done")]


def test_pr_wait_records_red_as_failed_and_keeps_its_exit_code(repo, fake, store, capsys):
    """AC-087.5 AC-087.7: red is failed; `pr wait` still exits 1 and prints what it printed before."""
    fake.checks = [[check("test", "fail")]]
    code = prmod.main(["wait", "5", "-R", "acme/other", "--repo", str(repo)])
    assert code == 1 and capsys.readouterr().out.startswith("RED")
    assert [(r["kind"], r["outcome"]) for r in stored(store)] == [("pr-wait", "failed")]


@pytest.mark.parametrize("state, checks", [("OPEN", [[check("test", "pending")]]), ("CLOSED", [[check("test", "pass")]])])
def test_pr_wait_records_a_timeout_or_error_as_failed_and_reraises(repo, fake, store, state, checks):
    """AC-087.5: a timeout (or any platform error) is failed, and the error still reaches the caller."""
    fake.state, fake.checks = state, checks
    with pytest.raises(core.PlatformError):
        prmod.wait(repo, URL, False, 30, 10, 300)
    assert [(r["kind"], r["outcome"]) for r in stored(store)] == [("pr-wait", "failed")]


def test_pr_wait_inside_a_ship_run_counts_toward_the_ship_record(repo, rgh, store):
    """AC-087.5: inside a ship run `pr wait` writes no record of its own; its CI round and rerun count for the ship run."""
    to_land(repo, rgh, merge=False)
    maven = "[ERROR] Failed to read artifact descriptor for org.apache.maven.shared:maven-shared-utils:jar:3.4.2"
    rgh.logs["42"] = [maven]
    rgh.checks = [[check("java", "fail")], [check("java", "fail")], [check("java", "pending")], [check("java", "pass")]]
    assert prmod.wait(repo, URL, False, 600, 10, 300)[0]
    assert stored(store) == []
    rgh.checks = [[check("test", "pass")]]
    assert ship.land(repo, timeout=60, interval=10)[0]
    (r,) = stored(store)
    assert r["kind"] == "ship" and r["ci_rounds"] == 2
    assert r["reruns"] == [{"check": "java", "reason": "transient"}]


def test_build_outside_a_ship_run_records_a_build_run(repo, store, capsys):
    """AC-087.5: `cplat runs begin/phase/end` around /svc:build writes one `build` record."""
    d = ["--dir", str(repo)]
    assert runs.main(["begin", "build", "--spec", "007-price-alerts", *d]) == 0
    assert "run " in capsys.readouterr().out
    assert runs.main(["phase", "build:tests", *d]) == 0 and runs.main(["phase", "build:implement", *d]) == 0
    assert stored(store) == []                                                    # nothing before the run ends
    assert runs.main(["end", "--outcome", "done", *d]) == 0
    (r,) = stored(store)
    assert (r["kind"], r["spec"], r["outcome"]) == ("build", "007-price-alerts", "done")
    assert [p["name"] for p in r["phases"]] == ["build:tests", "build:implement"]


def test_a_build_that_needs_the_user_is_recorded_escalated(repo, store):
    """AC-087.5 AC-087.16: `runs end --outcome escalated --reason` carries the reason; the cause defaults to unknown."""
    d = ["--dir", str(repo)]
    runs.main(["begin", "build", "--spec", "007-price-alerts", *d])
    runs.main(["end", "--outcome", "escalated", "--reason", "needs a decision on rate limits", *d])
    (r,) = stored(store)
    assert r["outcome"] == "escalated" and r["escalation"] == {"reason": "needs a decision on rate limits", "cause": "unknown"}


def test_build_inside_a_ship_run_attaches_to_it(repo, gh, store, capsys):
    """AC-087.5: inside a ship run, build's phases count toward the ship record and no separate record is written."""
    d = ["--dir", str(repo)]
    ship.start(repo, "7", True)
    runs.main(["begin", "build", "--spec", "007-price-alerts", *d])
    assert "attached to ship" in capsys.readouterr().out
    runs.main(["phase", "build:tests", *d])
    runs.main(["end", "--outcome", "done", *d])
    assert stored(store) == []
    ship.set_phase(repo, "done")
    (r,) = stored(store)
    assert r["kind"] == "ship" and "build:tests" in [p["name"] for p in r["phases"]]


# ---------------- AC-087.6 headless ----------------

def drop_tracks(repo):
    f = repo / "docs" / "specs" / "007-price-alerts" / "spec.md"
    f.write_text(f.read_text().replace("tracks: [42]\n", ""))


def test_a_headless_invocation_records_itself_and_the_ship_runs_it_drove(hl_repo, tmp_path, monkeypatch):
    """AC-087.6: one `headless` record (command, sessions, stop reason, ships); the ship record is marked headless."""
    drop_tracks(hl_repo)
    cp = ROOT / "scripts" / "cplat" / "cplat.py"
    fake_claude(tmp_path, monkeypatch, f'"{sys.executable}" "{cp}" ship --repo . start 7 >/dev/null && '
                                       f'"{sys.executable}" "{cp}" ship --repo . phase done >/dev/null')
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo)]) == 0
    recs = buffered_lines()
    (h,) = [r for r in recs if r["kind"] == "headless"]
    (s,) = [r for r in recs if r["kind"] == "ship"]
    assert h["mode"] == "headless" and h["command"] == "/svc:ship 7" and h["sessions"] == 1
    assert h["stop_reason"] == "done" and h["outcome"] == "done" and h["ships"] == [s["run_id"]]
    assert s["mode"] == "headless" and s["parent"] == h["run_id"] and s["outcome"] == "done"


def test_a_headless_dry_run_records_nothing(hl_repo, capsys):
    """AC-087.6: only real invocations are recorded."""
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo), "--dry-run"]) == 0
    assert buffered_lines() == []


@pytest.mark.parametrize("script, extra, stop, outcome", [
    ("true", [], "escalated", "escalated"),
    ("git -c user.name=t -c user.email=t@t commit -q --allow-empty -m step", ["--max-runs", "2"], "out of runs", "failed"),
])
def test_a_headless_record_names_why_it_stopped(hl_repo, tmp_path, monkeypatch, script, extra, stop, outcome):
    """AC-087.6: the stop reason is one of done, escalated, out of runs, quiet window, error."""
    ship.start(hl_repo, "7", True)
    if stop == "escalated":
        set_state(hl_repo, phase="land", escalated="merge conflict in alerts.go")
    fake_claude(tmp_path, monkeypatch, script)
    headless.main(["/svc:ship 7", "--repo", str(hl_repo), *extra])
    (h,) = [r for r in buffered_lines() if r["kind"] == "headless"]
    assert (h["stop_reason"], h["outcome"], h["mode"]) == (stop, outcome, "headless")
    assert h["sessions"] >= 1


def test_a_headless_record_for_the_quiet_window(hl_repo, tmp_path, monkeypatch):
    """AC-087.6: --no-wait inside the quiet window starts no session; the record says `quiet window`."""
    fake_claude(tmp_path, monkeypatch, "true")
    monkeypatch.setattr(headless, "clock", lambda: dt.datetime(2026, 10, 22, 23, 45))
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo), "--quiet", "23:30-07:00", "--no-wait"]) == 3
    (h,) = buffered_lines()
    assert (h["stop_reason"], h["outcome"], h["sessions"]) == ("quiet window", "abandoned", 0)


def test_a_headless_record_for_a_crashing_session(hl_repo, monkeypatch):
    """AC-087.6: a missing claude binary is `error`; the error still reaches the caller."""
    monkeypatch.setenv("CPLAT_CLAUDE", "/nonexistent/claude")
    with pytest.raises(core.PlatformError):
        headless.main(["/svc:fix-bug x", "--repo", str(hl_repo)])
    (h,) = buffered_lines()
    assert (h["kind"], h["stop_reason"], h["outcome"]) == ("headless", "error", "failed")


def test_the_headless_command_is_redacted(hl_repo, tmp_path, monkeypatch):
    """AC-087.6 AC-087.10: a secret in the command appears as <redacted>."""
    fake_claude(tmp_path, monkeypatch, "true")
    headless.main([f"/svc:fix-bug {SECRET}", "--repo", str(hl_repo)])
    (h,) = buffered_lines()
    assert "ghp_abc123" not in json.dumps(h) and "<redacted>" in h["command"]


# ---------------- AC-087.7 recording never changes a run ----------------

def test_an_unreachable_store_costs_one_warning_and_buffers_the_record(store, capsys):
    """AC-087.7: offline: the record is buffered, one warning names the buffer count, stdout is untouched."""
    store.reachable = False
    one_run(spec="007-price-alerts")
    cap = capsys.readouterr()
    lines = [ln for ln in cap.err.splitlines() if ln.startswith("WARNING")]
    assert len(lines) == 1 and "run record buffered locally" in lines[0] and "1 record(s) buffered" in lines[0]
    assert cap.out == "" and runs.buffered_count() == 1 and store.files == {}


def test_a_rejected_write_is_buffered_too(store, capsys):
    """AC-087.7: no permission or a rejected write: same warning, the record stays in the buffer."""
    store.reject = True
    one_run()
    (w,) = warnings(capsys)
    assert "buffered locally" in w and runs.buffered_count() == 1


def test_no_store_configured_is_buffered_with_a_hint(clock, capsys):
    """AC-087.7: not configured: buffered, and the warning says how to configure."""
    one_run()
    (w,) = warnings(capsys)
    assert "buffered locally" in w and "CPLAT_RUNS_REPO" in w and "1 record(s) buffered" in w
    assert runs.buffered_count() == 1


def test_a_value_that_is_not_owner_name_counts_as_not_configured(clock, monkeypatch, capsys):
    """AC-087.7: CPLAT_RUNS_REPO=garbage is the same as unset."""
    monkeypatch.setenv("CPLAT_RUNS_REPO", "garbage")
    assert runs.configured_repo() is None
    one_run()
    assert len(warnings(capsys)) == 1


def test_recording_adds_at_most_twenty_seconds(store, clock, capsys):
    """AC-087.7: when the store is so slow that the 20 s budget is gone, the record is buffered, not waited for."""
    store.cost = 25.0
    one_run()
    (w,) = warnings(capsys)
    assert "20 s" in w and store.files == {} and runs.buffered_count() == 1


def test_a_store_within_the_budget_gets_the_record(store, clock, capsys):
    """AC-087.7: a slow but sufficient store (two calls of 5 s) still receives the record and nothing is warned."""
    store.cost = 5.0
    one_run()
    assert len(stored(store)) == 1 and warnings(capsys) == []


def test_a_bug_in_recording_never_fails_the_run(clock, monkeypatch, capsys):
    """AC-087.7: even an unexpected exception in the store layer is a warning, never an exception."""
    monkeypatch.setenv("CPLAT_RUNS_REPO", "acme/runs")

    def boom(slug):
        raise RuntimeError("bug")
    monkeypatch.setattr(runs, "open_store", boom)
    one_run()
    assert len(warnings(capsys)) == 1 and runs.buffered_count() == 1
    runs.phase("no-such-run", "x")                                                   # mutators on unknown ids are no-ops
    runs.ci_round(None)
    assert runs.finish("no-such-run", "done") is None


def test_a_ship_run_behaves_the_same_without_a_reachable_store(repo, gh, store, capsys, monkeypatch):
    """AC-087.7: land/merge results and stdout are unchanged when the store is down; only one stderr warning is added."""
    said: list[str] = []
    monkeypatch.setattr(ship, "say", said.append)   # ship's own progress lines are not the recording's output
    store.reachable = False
    to_land(repo, gh, merge=False)
    gh.checks = [[check("test", "pass")]]
    ok, lines = ship.land(repo, timeout=60, interval=10)
    assert ok and lines[0].startswith("GREEN")
    cap = capsys.readouterr()
    assert cap.out == "" and len([ln for ln in cap.err.splitlines() if ln.startswith("WARNING")]) == 1


# ---------------- AC-087.8 flush ----------------

def test_flush_writes_the_buffer_in_ended_at_order_and_empties_it(store, clock, monkeypatch, capsys):
    """AC-087.8: buffered records are appended in ended_at order and removed from the buffer by `cplat runs flush`."""
    store.reachable = False
    ids = {}
    for name, at in (("late", "09:00:00"), ("early", "07:00:00"), ("mid", "08:00:00")):
        clock.set("2026-10-24T08:00:00Z")
        rid = runs.start("ship", repo="acme/shop-api")
        clock.set(f"2026-10-24T{at}Z")
        runs.finish(rid, "done")
        ids[name] = rid
    assert runs.buffered_count() == 3
    store.reachable = True
    capsys.readouterr()
    assert runs.main(["flush"]) == 0
    assert capsys.readouterr().out.strip() == "flushed 3 record(s) and 0 follow-up(s) to acme/runs; 0 left in the buffer; 0 pending filing(s)"
    assert runs.buffered_count() == 0
    written = [p.rsplit("/", 1)[1] for batch in store.puts for p in batch]
    assert written == [f"{ids[n]}.json" for n in ("early", "mid", "late")]


def test_the_next_record_flushes_what_was_buffered(store, capsys):
    """AC-087.8: a reachable store at the next run's end also receives the earlier, buffered records."""
    store.reachable = False
    first = one_run()
    store.reachable = True
    second = one_run()
    assert {r["run_id"] for r in stored(store)} == {first, second} and runs.buffered_count() == 0


def test_an_interrupted_flush_is_repeated_without_duplicates(store, capsys):
    """AC-087.8: a flush that fails after the files landed is repeated; the store holds the run exactly once."""
    store.fail_after_write = True
    rid = one_run()
    assert runs.buffered_count() == 1
    first = dict(store.files)
    store.fail_after_write = False
    assert runs.main(["flush"]) == 0
    assert store.files == first and list(store.files) == [f"runs/2026/10/24/{rid}.json"]
    assert runs.buffered_count() == 0


def test_records_of_other_repos_and_machines_are_never_lost(store):
    """AC-087.8: a record that arrived from another machine in between stays; ours is added next to it."""
    other = {"schema": 1, "run_id": "20261024T070000Z-aaaaaaaa", "kind": "ship", "ended_at": "2026-10-24T07:05:00Z"}
    store.files["runs/2026/10/24/20261024T070000Z-aaaaaaaa.json"] = json.dumps(other) + "\n"
    rid = one_run()
    assert {r["run_id"] for r in stored(store)} == {other["run_id"], rid}


# ---------------- AC-087.9 public store ----------------

@pytest.mark.parametrize("visibility", ["public", "internal"])
def test_a_store_that_is_not_private_gets_nothing(store, capsys, visibility):
    """AC-087.9: a public store: nothing is written, the record is buffered, the warning says why."""
    store.vis = visibility
    one_run()
    (w,) = warnings(capsys)
    assert store.files == {} and store.puts == [] and runs.buffered_count() == 1
    assert "public" in w and "private" in w and "buffered locally" in w


def test_flush_refuses_a_public_store(store, capsys):
    """AC-087.9 AC-087.15: `cplat runs flush` against a public store fails with the fix and writes nothing."""
    store.reachable = False
    one_run()
    store.reachable, store.vis = True, "public"
    assert cplat.main(["runs", "flush"]) == 1
    err = capsys.readouterr().err
    assert "is public" in err and "visibility private" in err and store.files == {} and runs.buffered_count() == 1


# ---------------- AC-087.10 redaction ----------------

def test_secrets_in_reasons_commands_and_filed_evidence_are_redacted(store):
    """AC-087.10: tokens and bearer headers in an escalation reason, a field, a filed signature or a section are <redacted>."""
    rid = runs.start("headless", repo="acme/shop-api")
    reason = f"push failed with {SECRET} and {BEARER}"
    runs.filed(rid, f"boom {SECRET}", "https://github.com/acme/x/issues/1", "new")
    runs.set_section(rid, "agents", {"note": BEARER, "list": [SECRET]})
    runs.finish(rid, "escalated", escalation={"reason": reason, "cause": "environment"}, fields={"command": f"/svc:ship 7 {SECRET}"})
    (r,) = stored(store)
    text = json.dumps(r)
    assert "ghp_abc123" not in text and "abcdefghijklmnop" not in text
    assert r["escalation"]["reason"] == feedback.redact(reason) and "<redacted>" in r["escalation"]["reason"]
    assert r["command"] == feedback.redact(f"/svc:ship 7 {SECRET}")
    assert r["filed"][0]["url"] == "https://github.com/acme/x/issues/1"          # identifiers are kept as they are


def test_long_text_is_cut_to_500_characters(store):
    """AC-087.10: a string value never exceeds 500 characters, so no log output can end up in a record."""
    one_run("ship", outcome="escalated", escalation={"reason": "word " * 400, "cause": "code"})
    (r,) = stored(store)
    assert len(r["escalation"]["reason"]) <= 500


# ---------------- AC-087.11 doctor ----------------

def run_store_check():
    res = doctor.check_run_store()
    res = res if isinstance(res, list) else [res]
    (c,) = [x for x in res if x["name"] == "run store"]
    return c


def test_doctor_warns_when_no_store_is_configured(clock):
    """AC-087.11: not configured is a warning with the init hint."""
    c = run_store_check()
    assert c["status"] == doctor.WARN and "cplat runs init <owner/name>" in c["fix"]


def test_doctor_fails_for_a_public_store(store):
    """AC-087.11: a public store is the only failing case."""
    store.vis = "public"
    c = run_store_check()
    assert c["status"] == doctor.FAIL and "acme/runs" in c["detail"] and "public" in c["detail"]


def test_doctor_warns_for_an_unreachable_store_and_names_it(store):
    """AC-087.11: unreachable warns and names the repo."""
    store.reachable = False
    c = run_store_check()
    assert c["status"] == doctor.WARN and "acme/runs" in c["detail"]


def test_doctor_warns_about_buffered_records_and_pending_filings(store):
    """AC-087.11: buffered records or pending filings warn with both counts and `cplat runs flush`."""
    store.reachable = False
    rid = runs.start("ship", repo="acme/shop-api")
    runs.filed(rid, "sig", None, "pending", filer="nobody", payload={})
    runs.finish(rid, "done")
    store.reachable = True
    c = run_store_check()
    assert c["status"] == doctor.WARN and "1 buffered record(s), 1 pending filing(s)" in c["detail"] and "cplat runs flush" in c["fix"]


def test_doctor_is_ok_for_a_clean_private_store(store):
    """AC-087.11: otherwise ok, naming the repo."""
    c = run_store_check()
    assert c["status"] == doctor.OK and "acme/runs" in c["detail"]


@pytest.fixture()
def quiet_doctor(monkeypatch):
    for name in ("check_tools", "check_gh", "check_docker", "check_kube", "check_plugins", "check_platform_source"):
        monkeypatch.setattr(doctor, name, lambda: [])
    for name in ("check_repo", "check_gitops_token"):
        monkeypatch.setattr(doctor, name, lambda repo: [])
    import gates
    monkeypatch.setattr(gates, "check_gates", lambda repo: [])


def test_a_missing_store_never_fails_doctor(quiet_doctor, clock, tmp_path, capsys):
    """AC-087.11: with no store, doctor still exits 0, and the run store line is in its output."""
    assert doctor.main(["--repo", str(tmp_path)]) == 0
    assert "run store" in capsys.readouterr().out
    assert any(c["name"] == "run store" for c in doctor.run_checks(tmp_path))


def test_a_public_store_fails_doctor(quiet_doctor, store, tmp_path):
    """AC-087.11: fail makes the overall doctor exit non-zero."""
    store.vis = "public"
    assert doctor.main(["--repo", str(tmp_path)]) == 1


# ---------------- AC-087.15 CLI errors ----------------

@pytest.mark.parametrize("cmd", ["report", "flush"])
def test_report_and_flush_without_a_store_name_the_fix(clock, capsys, cmd):
    """AC-087.15: not configured: non-zero exit, the problem, `cplat runs init <owner/name>` and the setting."""
    assert cplat.main(["runs", cmd]) == 1
    err = capsys.readouterr().err
    assert "no run store configured" in err and "CPLAT_RUNS_REPO" in err and "cplat runs init <owner/name>" in err


@pytest.mark.parametrize("cmd", ["report", "flush"])
def test_report_and_flush_with_an_unreachable_store_name_the_repo(store, capsys, cmd):
    """AC-087.15: unreachable: non-zero exit, the repo that could not be reached and a command to check it."""
    store.reachable = False
    assert cplat.main(["runs", cmd]) == 1
    err = capsys.readouterr().err
    assert "acme/runs" in err and "unreachable" in err and "gh repo view acme/runs" in err


def test_cplat_knows_runs():
    """AC-087.15: the command is registered and documented."""
    assert cplat.COMMANDS["runs"] == "runs" and "cplat.py runs" in cplat.__doc__


# ---------------- AC-087.16 escalation ----------------

def test_an_escalation_is_recorded_with_its_cause(repo, store):
    """AC-087.16: `cplat ship escalate` gives one `escalated` record with reason and cause."""
    ship.start(repo, "7", True)
    assert ship.main(["--repo", str(repo), "escalate", "merge conflict in alerts.go", "--cause", "platform"]) == 0
    (r,) = stored(store)
    assert r["outcome"] == "escalated" and r["escalation"] == {"reason": "merge conflict in alerts.go", "cause": "platform"}


def test_a_missing_or_unknown_cause_is_stored_as_unknown(repo, store):
    """AC-087.16: no cause given: unknown; an unknown value is stored as unknown."""
    ship.start(repo, "7", True)
    ship.escalate(repo, "needs a decision")
    ship.start(repo, "7", True)
    runs.finish(runs.start("ship", repo="acme/x"), "escalated", escalation={"reason": "r", "cause": "weird"})
    causes = sorted(r["escalation"]["cause"] for r in stored(store))
    assert causes == ["unknown", "unknown"]


def test_the_cause_must_be_one_of_the_known_ones(repo, store, capsys):
    """AC-087.16 AC-088.3: the known causes are stored as given; any other is stored as `unknown` with a message (no argparse error)."""
    ship.start(repo, "7", True)
    assert ship.main(["--repo", str(repo), "escalate", "why", "--cause", "bogus"]) == 0
    out = capsys.readouterr().out
    assert ship.load_state(repo)["cause"] == "unknown" and ship.load_state(repo)["escalated"] == "why"
    assert "bogus" in out and all(c in out for c in ("platform", "code", "decision", "environment"))
    for cause in ("code", "decision", "environment", "unknown"):
        assert ship.main(["--repo", str(repo), "escalate", "why", "--cause", cause]) == 0
        assert ship.load_state(repo)["cause"] == cause


def test_the_gate_giving_up_records_an_escalation(repo, store):
    """AC-087.16: the stop gate giving up ends the run as escalated with cause unknown."""
    ship.start(repo, "7", True)
    for _ in range(3):
        ship.gate(repo, {}, 3, run_tests=False)
    ship.gate(repo, {}, 3, run_tests=False)
    (r,) = stored(store)
    assert r["outcome"] == "escalated" and r["escalation"]["cause"] == "unknown" and "gave up" in r["escalation"]["reason"]


def test_a_resumed_ship_is_a_new_run_linked_to_the_escalated_one(repo, store, clock):
    """AC-087.16: starting the same spec again after an escalation is a new run whose `resumes` names the escalated run."""
    ship.start(repo, "7", True)
    ship.escalate(repo, "merge conflict in alerts.go", cause="code")
    ship.start(repo, "7", True)
    clock.tick(60)
    ship.set_phase(repo, "done")
    first, second = stored(store)
    assert first["outcome"] == "escalated" and second["outcome"] == "done"
    assert first["run_id"] != second["run_id"] and second["resumes"] == first["run_id"] and first["resumes"] is None
    assert len(stored(store)) == 2                                                  # each escalation counted once


# ---------------- AC-087.19 buffer cap ----------------

def test_the_buffer_keeps_1000_records_and_drops_the_oldest(mem, clock, monkeypatch, capsys):
    """AC-087.19: beyond 1000 buffered records the oldest is dropped and the warning says how many; a later flush writes the rest."""
    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    lines = []
    for i in range(1000):
        at = (base + dt.timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(json.dumps({"schema": 1, "run_id": f"20260101T000000Z-{i:08x}", "kind": "ship", "repo": "acme/x", "spec": None,
                                 "outcome": "done", "started_at": at, "ended_at": at}))
    (runs.state_dir()).mkdir(parents=True, exist_ok=True)
    (runs.state_dir() / "buffer.jsonl").write_text("\n".join(lines) + "\n")
    assert runs.buffered_count() == 1000
    new = one_run()
    (w,) = warnings(capsys)
    assert "1 oldest dropped" in w and runs.buffered_count() == 1000
    ids = {r["run_id"] for r in buffered_lines()}
    assert new in ids and "20260101T000000Z-00000000" not in ids and "20260101T000000Z-00000001" in ids
    attach(monkeypatch, mem)
    assert runs.main(["flush"]) == 0
    assert len(mem.files) == 1000 and runs.buffered_count() == 0
    assert all(len(batch) <= 200 for batch in mem.puts)


# ---------------- AC-087.20 init ----------------

def test_init_creates_a_missing_repo_private_and_prints_the_setting(mem, monkeypatch, capsys):
    """AC-087.20: a missing repo is created private; the command prints the configuration line."""
    mem.exists = False
    monkeypatch.setattr(runs, "open_store", lambda slug: mem)
    assert runs.main(["init", "acme/runs"]) == 0
    out = capsys.readouterr().out
    assert mem.created and "created acme/runs (private)" in out
    assert "export CPLAT_RUNS_REPO=acme/runs   # add this to your shell profile" in out


def test_init_of_an_existing_private_repo_only_prints_the_setting(mem, monkeypatch, capsys):
    """AC-087.20: an existing private repo is left alone."""
    monkeypatch.setattr(runs, "open_store", lambda slug: mem)
    assert runs.main(["init", "acme/runs"]) == 0
    out = capsys.readouterr().out
    assert not mem.created and "created" not in out and "export CPLAT_RUNS_REPO=acme/runs" in out


def test_init_refuses_a_public_repo(mem, monkeypatch, capsys):
    """AC-087.20: an existing public repo: exit non-zero, nothing changed, 'must be private'."""
    mem.vis = "public"
    monkeypatch.setattr(runs, "open_store", lambda slug: mem)
    assert cplat.main(["runs", "init", "acme/runs"]) == 1
    cap = capsys.readouterr()
    assert "must be private" in cap.err and not mem.created and mem.vis == "public" and "export" not in cap.out


# ---------------- AC-087.21 in-place events ----------------

def test_events_change_in_place_and_reach_the_store_once_at_the_end(store):
    """AC-087.21: nothing is in the store while the run is in progress; the record holds each event once, in its last state."""
    rid = runs.start("ship", repo="acme/shop-api")
    runs.event(rid, "conflicts", "c1", {"outcome": "re-planned"})
    runs.event(rid, "conflicts", "c2", {"outcome": "open"})
    runs.event(rid, "conflicts", "c1", {"outcome": "resolved"})
    assert store.files == {} and store.puts == [] and runs.buffered_count() == 0
    assert runs.active(rid)["conflicts"] == [{"id": "c1", "outcome": "resolved"}, {"id": "c2", "outcome": "open"}]
    runs.add_to(rid, "notes", "a", unique=True)
    runs.add_to(rid, "notes", "a", unique=True)
    runs.set_section(rid, "outcome", "hacked")                                       # reserved names are ignored
    runs.finish(rid, "done")
    (r,) = stored(store)
    assert r["conflicts"] == [{"id": "c1", "outcome": "resolved"}, {"id": "c2", "outcome": "open"}]
    assert r["notes"] == ["a"] and r["outcome"] == "done"


def test_phases_nest_by_level_and_open_ones_end_with_the_run(store, clock):
    """AC-087.21: opening a phase closes its level and deeper ones; phases still open end with the run."""
    rid = runs.start("build", repo="acme/shop-api")
    for name in ("build", "build:qa", "build:verify", "build:verify", "build:image"):
        clock.tick(10)
        runs.phase(rid, name)
    clock.tick(10)
    runs.finish(rid, "done")
    (r,) = stored(store)
    by = {p["name"]: p for p in r["phases"]}
    assert [p["name"] for p in r["phases"]] == ["build", "build:qa", "build:verify", "build:image"]
    assert by["build:qa"]["ended_at"] == by["build:verify"]["started_at"]
    assert by["build"]["ended_at"] == r["ended_at"] == by["build:image"]["ended_at"]


# ---------------- AC-087.22 filed issues ----------------

def test_a_filed_issue_is_part_of_the_record(store):
    """AC-087.22: `filed` holds signature, url and result; the same signature is one entry."""
    rid = runs.start("ship", repo="acme/shop-api")
    runs.filed(rid, "sig-1", "https://github.com/ika100/sdlc-foundry/issues/9", "new")
    runs.filed(rid, "sig-1", "https://github.com/ika100/sdlc-foundry/issues/9", "+1")
    runs.filed(rid, "sig-2", "https://github.com/ika100/sdlc-foundry/issues/10", "suppressed")
    runs.finish(rid, "done")
    (r,) = stored(store)
    assert r["filed"] == [{"signature": "sig-1", "url": "https://github.com/ika100/sdlc-foundry/issues/9", "result": "+1"},
                          {"signature": "sig-2", "url": "https://github.com/ika100/sdlc-foundry/issues/10", "result": "suppressed"}]


class Filer:
    def __init__(self):
        self.calls: list[dict] = []
        self.ok = False

    def __call__(self, entry, timeout):
        self.calls.append(entry)
        if not self.ok:
            raise RuntimeError("github is down")
        return "https://github.com/ika100/sdlc-foundry/issues/12", "new"


@pytest.fixture()
def filer(monkeypatch):
    f = Filer()
    monkeypatch.setitem(runs.FILERS, "fake-filer", f)
    return f


def test_a_pending_filing_is_retried_once_per_flush_and_followed_up(store, filer):
    """AC-087.22: pending filings stay local, are retried once per flush, and a success appends one follow-up line."""
    rid = runs.start("ship", repo="acme/shop-api")
    runs.filed(rid, "sig-2", None, "pending", filer="fake-filer", payload={"title": "PAYLOAD-STAYS-LOCAL"})
    runs.filed(rid, "sig-2", None, "pending", filer="fake-filer", payload={"title": "PAYLOAD-STAYS-LOCAL"})   # upsert, not a second entry
    runs.finish(rid, "done")
    (r,) = stored(store)
    assert r["filed"] == [{"signature": "sig-2", "url": None, "result": "pending"}]
    assert "PAYLOAD-STAYS-LOCAL" not in json.dumps(store.files) and runs.pending_count() == 1
    before = len(filer.calls)
    runs.flush()
    assert len(filer.calls) == before + 1 and runs.pending_count() == 1                  # failed: kept, tried once
    assert filer.calls[-1]["run_id"] == rid and filer.calls[-1]["signature"] == "sig-2"
    filer.ok = True
    res = runs.flush()
    assert res.followups == 1 and runs.pending_count() == 0
    (f,) = followups(store)
    assert {k: f[k] for k in ("schema", "followup", "run_id", "signature", "url", "result")} == {
        "schema": 1, "followup": "filed", "run_id": rid, "signature": "sig-2",
        "url": "https://github.com/ika100/sdlc-foundry/issues/12", "result": "new"}
    n = len(filer.calls)
    runs.flush()
    assert len(filer.calls) == n                                                          # filed at most once per run and signature


def test_the_report_counts_a_retried_filing_with_its_final_result(store, filer, capsys):
    """AC-087.22 AC-087.17: the report merges the follow-up into the run's filing."""
    rid = runs.start("ship", repo="acme/shop-api")
    runs.filed(rid, "sig-2", None, "pending", filer="fake-filer", payload={})
    runs.finish(rid, "done")
    filer.ok = True
    runs.flush()
    assert runs.main(["report", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["filed"] == {"new": 1, "+1": 0, "suppressed": 0, "pending": 0}


# ---------------- AC-087.23 other kinds ----------------

@pytest.mark.parametrize("kind, spec, section", [
    ("fleet", None, {"updated": 3}),
    ("retro", None, {"window_days": 7}),
    ("product-ship", "097-product-x", {"note": "n"}),
])
def test_fleet_retro_and_product_ship_runs_are_recorded(store, kind, spec, section):
    """AC-087.23: these kinds have the common fields plus their own sections; product-ship lists the repo ships it drove."""
    rid = runs.start(kind, repo=None, spec=spec)
    runs.add_to(rid, "ships", "20261024T070000Z-aaaaaaaa")
    runs.finish(rid, "done", fields={**section, "outcome": "ignored"})
    (r,) = stored(store)
    assert (r["kind"], r["repo"], r["spec"], r["outcome"]) == (kind, None, spec, "done")
    assert all(r[k] == v for k, v in section.items()) and r["ships"] == ["20261024T070000Z-aaaaaaaa"]
    assert r["schema"] == 1 and r["started_at"] and r["ended_at"] and r["phases"] == []


def test_the_run_id_is_sortable_and_stable_across_retries(store, clock):
    """AC-087.8 AC-087.23: `<UTC start>-<8 hex>`, fixed at start, so a retried write uses the same id and path."""
    rid = runs.start("fleet", repo=None)
    import re
    assert re.fullmatch(r"20261024T080000Z-[0-9a-f]{8}", rid)
    assert runs.start("fleet", repo=None, run_id="20261024T080000Z-0000beef") == "20261024T080000Z-0000beef"
