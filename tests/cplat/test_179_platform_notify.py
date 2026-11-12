"""Spec 179 acceptance tests: escalations of runs in the platform repo go to the desktop, not to GitHub (AC-179.7, AC-179.8).

Seams: `runs.start` and `runlist.row` (the run's shape), `needs._escalations` (the item's `object.shape`), `notify.events_of`,
`notify_config.load` / `cells_for`, `notify.run_once` on the World of test_notify.py (nothing leaves the machine), and the
unchanged auto-filing of `cplat ship escalate` (spec 088). Contract: design.md section 6.
"""
import datetime as dt

import pytest

import needs
import runlist
import runs
import spec
from console_support import need
from test_autoissue import PLATFORM_REPO, SIG_LINE, TOKEN, Clock, FakeTracker, boom, clk, tr, ai  # noqa: F401  (fixtures)
from test_autoissue_ship import escalate, started
from test_notify import TUE_NOON, World, env, write_cfg  # noqa: F401  (env is an autouse fixture)
from test_runs import MemStore, attach, followups, stored  # noqa: F401  (helpers)
from test_runs import clock as run_clock, mem, store  # noqa: F401  (fixtures)
from test_ship import git, repo  # noqa: F401  (fixtures)

ESC_REASON = "3 CI fix rounds without progress"


def esc(shape="platform", run_id="r1"):
    obj = {"type": "run", "run_id": run_id, "spec": "011-cart"}
    if shape is not None:
        obj["shape"] = shape
    return need("escalation", spec="011-cart", object=obj, reason=ESC_REASON, id=f"escalation:{run_id}")


def issue_calls(w):
    return [c for c in w.gh_calls if c[:2] in (["issue", "create"], ["issue", "comment"])]


# ---------------- the run carries its shape, the escalation item and the event follow ----------------

def test_a_run_started_with_a_shape_stores_it_ac_179_7(tmp_path):  # AC-179.7
    rid = runs.start("build", repo="acme/shop", spec="011-cart", shape="platform")
    assert runs.active(rid)["shape"] == "platform"


def test_a_run_started_in_the_platform_repo_stores_the_shape_it_finds_ac_179_7(tmp_path, monkeypatch):  # AC-179.7
    import subprocess
    root = tmp_path / "platform"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".platform-settings.yml").write_text("shape: platform\n")
    monkeypatch.chdir(root)
    rid = runs.start("build", repo="ika100/sdlc-foundry", spec="011-cart")
    assert runs.active(rid)["shape"] == "platform"


def test_a_run_whose_shape_is_unknown_has_no_shape_key_ac_179_7(tmp_path, monkeypatch):  # AC-179.7
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(spec, "repo_shape", lambda root: (_ for _ in ()).throw(RuntimeError("no shape")))
    rid = runs.start("build", repo="acme/shop", spec="011-cart")
    assert rid and "shape" not in runs.active(rid)


def test_the_run_row_carries_the_records_shape_or_the_repos_ac_179_7(tmp_path, monkeypatch):  # AC-179.7
    rid = runs.start("build", repo="acme/shop", spec="011-cart", shape="platform")
    assert runlist.row(runs.active(rid), True)["shape"] == "platform"
    plain = runs.start("build", repo="acme/shop", spec="012-stock", shape="service-python")
    rec = runs.active(plain)
    rec.pop("shape")                                                  # a record written before spec 179
    root = tmp_path / "work"
    root.mkdir()
    monkeypatch.setattr(runlist, "_session", lambda run_id: ("s1", str(root)))
    monkeypatch.setattr(spec, "repo_shape", lambda r: "platform" if str(r) == str(root) else None)
    assert runlist.row(rec, True)["shape"] == "platform"
    monkeypatch.setattr(runlist, "_session", lambda run_id: (None, None))
    assert "shape" not in runlist.row(rec, True)                      # unknown: no key


def test_the_escalation_item_carries_the_shape_only_when_known_ac_179_7():  # AC-179.7
    base = {"run_id": "r1", "kind": "build", "level": "component", "spec": "011-cart", "repo": "acme/shop", "phase": "escalated",
            "stage": "Build", "started_at": "2026-11-01T10:00:00Z", "ended_at": "2026-11-01T11:00:00Z", "pr": {},
            "escalation": {"reason": ESC_REASON}, "active": False}
    (known,) = needs._escalations([{**base, "shape": "platform"}])
    assert known["object"]["shape"] == "platform"
    (unknown,) = needs._escalations([dict(base)])
    assert "shape" not in unknown["object"]


def test_an_escalation_event_carries_the_shape_ac_179_7():  # AC-179.7
    import notify
    doc = {"needs": {"items": [esc("platform", "r1"), esc(None, "r2")]}}
    evs = notify.events_of(doc)
    assert evs["escalation:r1"]["shape"] == "platform"
    assert "shape" in evs["escalation:r2"] and evs["escalation:r2"]["shape"] is None


# ---------------- the preset applies per event ----------------

def test_without_a_file_the_platform_escalation_is_desktop_only_ac_179_7(tmp_path):  # AC-179.7
    import notify_config
    cfg = notify_config.load(tmp_path / "nowhere.yaml")
    assert notify_config.PLATFORM_ESCALATION == {"github": "off", "desktop": "instant"}
    cells = notify_config.cells_for(cfg, "escalation", "platform")
    assert cells == {"github": "off", "slack": "off", "email": "off", "desktop": "instant"}
    assert cfg.events["escalation"]["github"] == "instant"            # the config itself is not changed


@pytest.mark.parametrize("shape", ["service-python", "web-nextjs", "gitops-app", "library-python", None])
def test_any_other_shape_is_notified_as_today_ac_179_7(tmp_path, shape):  # AC-179.7
    import notify_config
    cfg = notify_config.load(tmp_path / "nowhere.yaml")
    assert notify_config.cells_for(cfg, "escalation", shape) == cfg.events["escalation"]
    assert cfg.events["escalation"]["github"] == "instant"


@pytest.mark.parametrize("event", ["approve", "answer", "alert", "promote", "review", "stuck"])
def test_the_platform_preset_changes_no_other_event_ac_179_7(tmp_path, event):  # AC-179.7
    import notify_config
    cfg = notify_config.load(tmp_path / "nowhere.yaml")
    assert notify_config.cells_for(cfg, event, "platform") == cfg.events[event]


def test_the_user_file_wins_cell_by_cell_ac_179_8(tmp_path, monkeypatch):  # AC-179.8
    import notify_config
    p = write_cfg(tmp_path, monkeypatch, {"events": {"escalation": {"github": "instant"}}})
    cfg = notify_config.load(p)
    assert "escalation.github" in cfg.explicit
    assert notify_config.cells_for(cfg, "escalation", "platform")["github"] == "instant"
    assert notify_config.cells_for(cfg, "escalation", "platform")["desktop"] == "instant"
    p = write_cfg(tmp_path, monkeypatch, {"events": {"escalation": {"desktop": "off", "slack": "instant"}}})
    cfg = notify_config.load(p)
    assert cfg.explicit >= {"escalation.desktop", "escalation.slack"} and "escalation.github" not in cfg.explicit
    cells = notify_config.cells_for(cfg, "escalation", "platform")
    assert cells["desktop"] == "off" and cells["slack"] == "instant" and cells["github"] == "off"   # only the unset cells change


def test_a_file_without_events_sets_nothing_explicit_ac_179_8(tmp_path, monkeypatch):  # AC-179.8
    import notify_config
    assert notify_config.load(tmp_path / "nowhere.yaml").explicit == set()
    p = write_cfg(tmp_path, monkeypatch, {"slack": {"channels": ["#shop-dev"]}})
    assert notify_config.load(p).explicit == set()


# ---------------- the notifier ----------------

def test_a_platform_escalation_reaches_the_desktop_and_no_issue_or_comment_is_made_ac_179_7(tmp_path, monkeypatch):  # AC-179.7
    w = World(tmp_path, monkeypatch, {}, TUE_NOON)
    w.needs = [esc("platform")]
    w.once()
    assert len(w.desktop) == 1 and ESC_REASON in w.desktop[0][1]
    assert issue_calls(w) == []
    assert not w.calls("pr", "comment")
    w.once()
    assert len(w.desktop) == 1 and issue_calls(w) == []               # and not again


@pytest.mark.parametrize("shape", ["service-python", "gitops-app", None])
def test_an_escalation_of_another_shape_is_notified_as_today_ac_179_7(tmp_path, monkeypatch, shape):  # AC-179.7
    w = World(tmp_path, monkeypatch, {}, TUE_NOON)
    w.needs = [esc(shape)]
    w.once()
    assert len(w.desktop) == 1 and len(w.calls("issue", "create")) == 1


def test_a_platform_escalation_with_the_users_github_setting_is_filed_ac_179_8(tmp_path, monkeypatch):  # AC-179.8
    w = World(tmp_path, monkeypatch, {"events": {"escalation": {"github": "instant"}}}, TUE_NOON)
    w.needs = [esc("platform")]
    w.once()
    assert len(w.calls("issue", "create")) == 1 and len(w.desktop) == 1


def test_a_users_desktop_off_holds_in_the_platform_repo_too_ac_179_8(tmp_path, monkeypatch):  # AC-179.8
    w = World(tmp_path, monkeypatch, {"events": {"escalation": {"desktop": "off"}}}, TUE_NOON)
    w.needs = [esc("platform")]
    w.once()
    assert w.desktop == [] and issue_calls(w) == []


# ---------------- auto-filing is not touched (ADR-033) ----------------

def test_a_platform_cause_escalation_in_the_platform_repo_is_still_auto_filed_ac_179_8(repo, tr, tmp_path, monkeypatch, capsys):  # AC-179.8
    """AC-179.8 (a guard: it holds before and after the change): `cplat ship escalate --cause platform` in a repo whose shape is
    `platform` files, then +1s, an auto-filed issue, whatever the notify file says about `escalation` on `github`."""
    write_cfg(tmp_path, monkeypatch, {"events": {"escalation": {"github": "off"}}})
    monkeypatch.setattr(spec, "repo_shape", lambda root: "platform")
    for _ in range(2):
        started(repo)
        assert escalate(repo, "copier render fails on the Dockerfile", "--cause", "platform") == 0
    out = capsys.readouterr().out
    ((_, target, title, body, labels),) = tr.created()
    assert target == PLATFORM_REPO and title == "[auto] copier render fails on the Dockerfile" and "auto-filed" in labels
    assert len(tr.commented()) == 1
    assert f"issue: https://github.com/{PLATFORM_REPO}/issues/1 +1" in out.splitlines()

