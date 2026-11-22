"""#848: after a timeout or network error the run store is skipped for a few minutes, not waited on per record."""
import pytest

import runs
import runs_store
from test_runs import MemStore, attach, clock, one_run, stored, warnings  # noqa: F401  (fixture)


class DownStore(MemStore):
    """A MemStore that fails every call with `down` (a gh error line) and counts the calls it gets."""

    def __init__(self):
        super().__init__()
        self.down: str | None = "timeout"
        self.calls = 0

    def visibility(self, deadline=None):
        self.calls += 1
        if self.down:
            raise runs_store.StoreUnreachable(self.down)
        return super().visibility(deadline)

    def put(self, files, message, deadline=None):
        self.calls += 1
        if self.down:
            raise runs_store.StoreUnreachable(self.down)
        super().put(files, message, deadline)


@pytest.fixture()
def down(clock, monkeypatch):
    s = DownStore()
    attach(monkeypatch, s)
    return s


def test_a_second_record_after_a_timeout_makes_no_network_call(down, capsys):
    one_run()
    (w,) = warnings(capsys)
    assert down.calls == 1 and "unreachable: timeout; skipping the store until 08:03 UTC" in w
    one_run()
    one_run()
    assert down.calls == 1 and warnings(capsys) == [] and runs.buffered_count() == 3


def test_a_network_error_skips_the_store_too(down, capsys):
    down.down = "check your internet connection or https://githubstatus.com"
    one_run()
    one_run()
    assert down.calls == 1 and len(warnings(capsys)) == 1


def test_a_later_command_skips_the_store_and_warns_once(down, capsys, monkeypatch):
    one_run()
    capsys.readouterr()
    monkeypatch.setattr(runs, "_announced", set())            # a new process: only the marker on disk is left
    one_run()
    one_run()
    (w,) = warnings(capsys)
    assert down.calls == 1 and "run store acme/runs skipped until 08:03 UTC after: timeout" in w and "2 record(s) buffered" in w
    assert runs.record_audit({"event_id": "e1", "at": "2026-10-24T08:01:00Z", "kind": "x", "actor": "me"}) is not None and down.calls == 1


def test_the_marker_expires_and_the_next_record_flushes_the_buffer(down, clock, capsys):
    first = one_run()
    down.down = None
    clock.tick(runs.SKIP_SECONDS + 1)
    second = one_run()
    assert {r["run_id"] for r in stored(down)} == {first, second} and runs.buffered_count() == 0
    assert not (runs.state_dir() / "store-skip.json").exists()


def test_flush_ignores_the_marker_and_success_clears_it(down, capsys):
    one_run()
    down.down = None
    assert runs.main(["flush"]) == 0
    assert len(stored(down)) == 1 and runs.buffered_count() == 0 and not (runs.state_dir() / "store-skip.json").exists()
    one_run()                                                  # the store is tried again at once
    assert len(stored(down)) == 2


def test_a_rejected_write_does_not_skip_the_store(down, capsys):
    down.down = "HTTP 403: Resource not accessible by integration"
    one_run()
    one_run()
    assert down.calls == 2 and not (runs.state_dir() / "store-skip.json").exists()
