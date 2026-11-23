"""#931, #880, #887: pr wait waits for the run of a transient failure, names the run to rerun, and leaves the runner's
cleanup out of the log excerpt."""
import failsum
import pr as prmod
import ship
from test_tags_and_wait import Gh, fake  # noqa: F401  (fake is a fixture)

URL = "https://github.com/acme/other/pull/5"
CACHE_404 = "ERROR: failed to solve: failed to load cache key: invalid response status 404"


def job(name, bucket, run="42", job_id="7"):
    return {"name": name, "state": bucket.upper(), "bucket": bucket,
            "link": f"https://github.com/acme/shop-api/actions/runs/{run}/job/{job_id}"}


class RunningGh(Gh):
    """`gh run view --log-failed` is empty until the run completes (#399); the finished job's own log is there before."""

    def __init__(self, status, job_log):
        super().__init__()
        self.status, self.job_log = status, job_log

    def __call__(self, args, *, cwd, check=True):
        if args[:2] == ["run", "view"] and "status" in args and "--json" in args and "status,conclusion" not in args:
            seq = self.status
            return seq.pop(0) if len(seq) > 1 else seq[0]
        if args[0] == "api" and "/actions/jobs/" in args[1]:
            self.calls.append(args)
            return self.job_log
        return super().__call__(args, cwd=cwd, check=check)


def running_gh(monkeypatch, fake, status, job_log):  # noqa: F811
    g = RunningGh(status, job_log)
    g.said, g.merges = fake.said, fake.merges
    monkeypatch.setattr(ship, "gh", g)
    return g


def test_a_transient_failure_waits_for_its_run_then_is_rerun_931(fake, tmp_path, monkeypatch):  # noqa: F811
    """#931: a cache 404 while sibling jobs still queue is not RED; once the run completes, its failed jobs rerun once."""
    g = running_gh(monkeypatch, fake, ["in_progress", "in_progress", "completed"], f"e2e backups\t\t{CACHE_404}\n")
    g.logs["42"] = ["", "", CACHE_404]
    g.checks = [[job("e2e backups", "fail"), job("e2e core", "pending", job_id="8")]] * 3 + \
               [[job("e2e backups", "pending"), job("e2e core", "pass", job_id="8")]] + \
               [[job("e2e backups", "pass"), job("e2e core", "pass", job_id="8")]]
    ok, _ = prmod.wait(tmp_path, URL, True, 3600, 10, 300)
    assert ok and g.merges == [URL]
    assert [c for c in g.calls if c[:2] == ["run", "rerun"]] == [["run", "rerun", "42", "-R", "acme/shop-api", "--failed"]]
    assert sum("rerun once the run completes" in s for s in g.said) == 1


def test_a_real_failure_while_the_run_is_in_progress_is_red_at_once_931(fake, tmp_path, monkeypatch):  # noqa: F811
    """#931: only a transient failure waits; an assertion failure in a finished job ends the wait as before."""
    g = running_gh(monkeypatch, fake, ["in_progress"], "test\t\t--- FAIL: TestPriceAlert (0.00s)\n")
    g.logs["42"] = [""]
    g.checks = [[job("test", "fail"), job("e2e core", "pending", job_id="8")]]
    ok, lines = prmod.wait(tmp_path, URL, False, 600, 10, 300)
    assert not ok and lines[0].startswith("RED") and not any(c[:2] == ["run", "rerun"] for c in g.calls)


def test_red_names_the_run_and_its_rerun_command_880(fake, tmp_path):  # noqa: F811
    """#880: each red check's run id and the `gh run rerun` command for exactly that run."""
    fake.checks = [[job("test", "fail"), job("lint", "fail", run="43", job_id="9"), job("docs", "fail", job_id="10")]]
    fake.logs["42"], fake.logs["43"] = ["--- FAIL: TestPriceAlert"], ["E501 line too long"]
    ok, lines = prmod.wait(tmp_path, URL, False, 600, 10, 300)
    assert not ok and lines[0].startswith("RED: 3 of 3")
    assert "run 42 (test, docs): gh run rerun 42 -R acme/shop-api --failed" in lines
    assert "run 43 (lint): gh run rerun 43 -R acme/shop-api --failed" in lines


def test_the_excerpt_leaves_out_the_runners_cleanup_887():
    """#887: post-job steps (checkout's git config cleanup) are not the tail; the failing step's last lines are."""
    ts = "2026-11-21T10:00:00.0000000Z "
    failed = [f"e2e\tRun tests/e2e/run.sh\t{ts}== check backups", f"e2e\tRun tests/e2e/run.sh\t{ts}restore timed out",
              f"e2e\tRun tests/e2e/run.sh\t{ts}##[error]Process completed with exit code 1."]
    cleanup = [f"e2e\tPost Run actions/checkout@v6\t{ts}Post job cleanup.",
               *(f"e2e\tPost Run actions/checkout@v6\t{ts}[command]/usr/bin/git config --local --unset-all includeif.gitdir:{i}"
                 for i in range(40)),
               f"e2e\tComplete job\t{ts}Cleaning up orphan processes"]
    raw_job = [f"e2e\t\t{ts}restore timed out", f"e2e\t\t{ts}##[error]Process completed with exit code 1.",
               f"e2e\t\t{ts}Post job cleanup.", *(f"e2e\t\t{ts}[command]/usr/bin/git config --unset includeif.{i}" for i in range(40))]
    for text in ("\n".join(failed + cleanup), "\n".join(raw_job)):
        c = failsum.ci_check(failsum.CiCheck("e2e", "link", None, text), failsum.Context(root=None), [])
        assert c.tail[-1] == "Process completed with exit code 1." and "restore timed out" in c.tail
        assert not any("includeif" in t or "orphan" in t for t in c.tail) and c.exit == "1"
