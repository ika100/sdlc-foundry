"""#1108: the dispatcher loop re-executes itself when its platform checkout moved and no unit runs."""
import dispatch
import dispatch_platform


def _commit(monkeypatch, sha):
    monkeypatch.setattr(dispatch_platform, "state", lambda repo, fetch=False: None if sha is None else dict(commit=sha))


def test_moved_checkout_with_no_unit_restarts(monkeypatch, tmp_path):
    _commit(monkeypatch, "b")
    assert dispatch._moved(tmp_path, "a", set()) is True


def test_a_running_unit_defers_the_restart(monkeypatch, tmp_path):
    _commit(monkeypatch, "b")
    assert dispatch._moved(tmp_path, "a", {123}) is False


def test_same_commit_or_no_platform_checkout_never_restarts(monkeypatch, tmp_path):
    _commit(monkeypatch, "a")
    assert dispatch._moved(tmp_path, "a", set()) is False
    _commit(monkeypatch, None)
    assert dispatch._moved(tmp_path, "a", set()) is False
    assert dispatch._moved(tmp_path, None, set()) is False


def test_loop_returns_true_after_a_cycle_when_the_checkout_moved(monkeypatch, tmp_path):
    commits = iter(["a", "b", "b"])
    monkeypatch.setattr(dispatch_platform, "state", lambda repo, fetch=False: dict(commit=next(commits)))
    monkeypatch.setattr(dispatch, "_live_pids", lambda repo, slug: set())
    monkeypatch.setattr(dispatch, "_steering", lambda slug: "")
    monkeypatch.setattr(dispatch.dispatch_policy, "load", lambda *a, **k: object())
    monkeypatch.setattr(dispatch, "_cycle", lambda *a, **k: None)
    assert dispatch._loop(tmp_path, "s", object(), dict(now=False)) is True
