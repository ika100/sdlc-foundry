"""Spec 122 acceptance tests: notifications (AC-122.22 .. AC-122.27, and the notification part of AC-122.2).

Contract: design.md "notify.yaml" and "Delivery". Assumed seams (listed in the tester's report), all module-level and replaced here:
`notify_config.load(path=None)` -> object with `.events[event][channel]`, `.digest`, `.quiet_hours`; `notify_config.secret(name, account=None)`;
`notify.collect(repo_dir)` -> {"needs": <needs doc>, "runs": <runs doc>, "issues": [gh issue dicts], "shipped": [..]};
`notify.now()`, `notify.gh(args) -> str`, `notify.http_post(url, payload)`, `notify.send_mail(cfg, subject, body)`,
`notify.desktop_send(title, text) -> ref`, `notify.desktop_withdraw(ref)`. Nothing leaves the machine."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest
import yaml

import core
from console_support import need
from system_fixtures import rich5, write_system

WEBHOOK = "https://hooks.slack.test/services/T/B/X"
EVENTS = ["approve", "answer", "escalation", "promote", "alert", "smoke", "run-done", "retro"]
CHANNELS = ["github", "slack", "email", "desktop"]


def write_cfg(tmp_path, monkeypatch, doc):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    p = tmp_path / "config" / "sdlc-foundry" / "notify.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc if isinstance(doc, str) else yaml.safe_dump(doc))
    return p


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for k in ("CPLAT_SLACK_WEBHOOK_SHOP_DEV", "CPLAT_SMTP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


# ---------------- AC-122.22: notify.yaml, preset, secrets ----------------

def test_without_a_file_the_recommended_preset_applies_ac_122_22(tmp_path):  # AC-122.22
    import notify_config
    cfg = notify_config.load(tmp_path / "nowhere.yaml")
    for e in ("approve", "answer", "escalation", "alert", "smoke"):
        assert cfg.events[e]["github"] == "instant", e
    for e in ("promote", "run-done", "retro"):
        assert cfg.events[e]["github"] == "off", e
    for e in ("approve", "answer", "escalation", "promote", "alert", "smoke"):
        assert cfg.events[e]["desktop"] == "instant", e
    assert all(cfg.events[e]["slack"] == "off" and cfg.events[e]["email"] == "off" for e in EVENTS)
    assert set(cfg.events) == set(EVENTS) and all(set(cfg.events[e]) == set(CHANNELS) for e in EVENTS)


def test_the_file_overrides_single_cells_of_the_preset_ac_122_22(tmp_path, monkeypatch):  # AC-122.22
    import notify_config
    p = write_cfg(tmp_path, monkeypatch, {"preset": "recommended", "events": {"approve": {"slack": "digest", "email": "digest"}},
                                          "slack": {"channels": ["#shop-dev"]}, "digest": {"at": "08:30", "days": ["mon", "tue"]},
                                          "quiet_hours": "22:00-07:00"})
    cfg = notify_config.load(p)
    assert cfg.events["approve"]["slack"] == "digest" and cfg.events["approve"]["github"] == "instant"
    assert cfg.digest["at"] == "08:30" and cfg.digest["days"] == ["mon", "tue"] and cfg.quiet_hours == "22:00-07:00"


@pytest.mark.parametrize("doc, key", [
    ({"events": {"bogus": {"github": "off"}}}, "bogus"),
    ({"events": {"approve": {"pager": "instant"}}}, "pager"),
    ({"events": {"approve": {"github": "sometimes"}}}, "sometimes"),
    ({"events": {"approve": {"github": "digest"}}}, "digest"),
    ({"events": {"approve": {"desktop": "digest"}}}, "digest"),
    ({"events": {"approve": {"console": "off"}}}, "console"),
    ({"surprise": 1}, "surprise"),
])
def test_an_unknown_key_or_value_is_an_error_naming_it_ac_122_22(tmp_path, monkeypatch, doc, key):  # AC-122.22
    import notify_config
    p = write_cfg(tmp_path, monkeypatch, doc)
    with pytest.raises(core.PlatformError, match=key):
        notify_config.load(p)


@pytest.mark.parametrize("doc, key", [
    ({"slack": {"webhook": WEBHOOK}}, "webhook"),
    ({"slack": {"channels": ["#a"], "url": WEBHOOK}}, "url"),
    ({"email": {"to": "me@example.com", "password": "hunter2"}}, "password"),
    ({"email": {"to": "me@example.com", "token": "x"}}, "token"),
])
def test_secrets_are_refused_anywhere_in_the_file_ac_122_22(tmp_path, monkeypatch, doc, key):  # AC-122.22
    import notify_config
    p = write_cfg(tmp_path, monkeypatch, doc)
    with pytest.raises(core.PlatformError, match=key):
        notify_config.load(p)


def test_a_secret_comes_from_the_environment_first_ac_122_22(monkeypatch):  # AC-122.22
    import notify_config
    monkeypatch.setenv("CPLAT_SLACK_WEBHOOK_SHOP_DEV", WEBHOOK)
    assert notify_config.secret("CPLAT_SLACK_WEBHOOK_SHOP_DEV", account="slack-webhook:#shop-dev") == WEBHOOK


@pytest.mark.parametrize("platform, tool", [("darwin", "security"), ("linux", "secret-tool")])
def test_a_secret_falls_back_to_the_os_keychain_ac_122_22(monkeypatch, platform, tool):  # AC-122.22
    import notify_config
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "from-keychain\n", ""

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(notify_config.subprocess, "run", lambda argv, *a, **k: calls.append(list(argv)) or Done())
    monkeypatch.setattr(notify_config.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert notify_config.secret("CPLAT_SLACK_WEBHOOK_SHOP_DEV", account="slack-webhook:#shop-dev") == "from-keychain"
    [argv] = calls
    assert Path(argv[0]).name == tool and "sdlc-foundry" in argv and "slack-webhook:#shop-dev" in argv


def test_a_missing_secret_is_none_ac_122_22(monkeypatch):  # AC-122.22
    import notify_config

    class Gone:
        returncode, stdout, stderr = 1, "", "not found"

    monkeypatch.setattr(notify_config.subprocess, "run", lambda *a, **k: Gone())
    assert notify_config.secret("CPLAT_SLACK_WEBHOOK_SHOP_DEV", account="slack-webhook:#shop-dev") is None


# ---------------- AC-122.27 and the doctor part of AC-122.41 ----------------

def used(tmp_path, monkeypatch):
    write_cfg(tmp_path, monkeypatch, {"events": {"escalation": {"slack": "instant", "email": "digest"}},
                                      "slack": {"channels": ["#shop-dev"]},
                                      "email": {"to": "me@example.com", "from": "cplat@example.com", "host": "smtp.example.com",
                                                "port": 587, "user": "me", "starttls": True}})


def test_doctor_names_the_channel_and_the_missing_setting_ac_122_27(tmp_path, monkeypatch):  # AC-122.27
    import notify_config
    used(tmp_path, monkeypatch)
    rows = notify_config.doctor_checks()
    text = json.dumps(rows)
    assert all(r["status"] == "warn" for r in rows) and all({"status", "name", "detail", "fix"} <= set(r) for r in rows)
    assert "slack" in text and "CPLAT_SLACK_WEBHOOK_SHOP_DEV" in text
    assert "email" in text and "CPLAT_SMTP_PASSWORD" in text


def test_doctor_is_quiet_when_the_settings_are_there_ac_122_27(tmp_path, monkeypatch):  # AC-122.27
    import notify_config
    used(tmp_path, monkeypatch)
    monkeypatch.setenv("CPLAT_SLACK_WEBHOOK_SHOP_DEV", WEBHOOK)
    monkeypatch.setenv("CPLAT_SMTP_PASSWORD", "pw")
    assert notify_config.doctor_checks() == []


def test_doctor_has_nothing_to_say_about_the_preset_ac_122_27(tmp_path):  # AC-122.27
    import notify_config
    assert notify_config.doctor_checks() == []


def test_a_channel_set_to_off_is_not_checked_ac_122_27(tmp_path, monkeypatch):  # AC-122.27
    import notify_config
    write_cfg(tmp_path, monkeypatch, {"events": {"escalation": {"slack": "off", "email": "off"}}, "slack": {"channels": ["#shop-dev"]}})
    assert notify_config.doctor_checks() == []


def test_run_checks_includes_the_notification_checks_ac_122_27(tmp_path, monkeypatch):  # AC-122.27
    import doctor
    import gates
    import notify_config
    for name in [n for n in dir(doctor) if n.startswith("check_") and n != "check"]:
        monkeypatch.setattr(doctor, name, (lambda *a, **k: {"status": "ok", "name": "x", "detail": "", "fix": None}) if name == "check_run_store"
                            else (lambda *a, **k: []))
    monkeypatch.setattr(gates, "check_gates", lambda *a, **k: [])
    row = {"status": "warn", "name": "notify:slack", "detail": "no webhook", "fix": "export CPLAT_SLACK_WEBHOOK_SHOP_DEV"}
    monkeypatch.setattr(notify_config, "doctor_checks", lambda: [row])
    assert row in doctor.run_checks(tmp_path)


def test_doctor_warns_when_claude_is_not_on_the_path_ac_122_41(monkeypatch):  # AC-122.41
    import doctor
    real = doctor.shutil.which
    monkeypatch.setattr(doctor.shutil, "which", lambda name, *a, **k: None if name == "claude" else real(name, *a, **k))
    [row] = [r for r in doctor.check_tools() if r["name"] == "claude"]
    assert row["status"] == "warn" and "Claude Code" in row["fix"]


# ---------------- delivery (AC-122.23 .. AC-122.26, AC-122.2) ----------------

class World:
    def __init__(self, tmp_path, monkeypatch, cfg_doc, when):
        import notify
        self.notify = notify
        self.repo = tmp_path / "gitops"
        write_system(self.repo, rich5())
        write_cfg(tmp_path, monkeypatch, cfg_doc)
        monkeypatch.setenv("CPLAT_SLACK_WEBHOOK_SHOP_DEV", WEBHOOK)
        monkeypatch.setenv("CPLAT_SMTP_PASSWORD", "pw")
        self.when = when
        self.needs, self.issues, self.shipped, self.runs = [], [], [], []
        self.posts, self.gh_calls, self.desktop, self.withdrawn, self.mails = [], [], [], [], []
        monkeypatch.setattr(notify, "now", lambda: self.when)
        monkeypatch.setattr(notify, "collect", self.collect)
        monkeypatch.setattr(notify, "gh", self.gh)
        monkeypatch.setattr(notify, "http_post", lambda url, payload: self.posts.append((url, payload)))
        monkeypatch.setattr(notify, "send_mail", lambda cfg, subject, body: self.mails.append((subject, body)))
        monkeypatch.setattr(notify, "desktop_send", lambda title, text: self.desktop.append((title, text)) or f"d{len(self.desktop)}")
        monkeypatch.setattr(notify, "desktop_withdraw", lambda ref: self.withdrawn.append(ref))

    def collect(self, repo_dir):
        return {"needs": {"schema": 1, "system": "shop", "items": list(self.needs), "unavailable": []},
                "runs": {"schema": 1, "runs": list(self.runs)}, "issues": list(self.issues), "shipped": list(self.shipped)}

    def gh(self, args):
        self.gh_calls.append(list(args))
        if args[:2] == ["issue", "create"]:
            return "https://github.com/acme/shop-gitops/issues/88"
        return ""

    def once(self):
        self.notify.run_once(self.repo)

    def calls(self, *words):
        return [c for c in self.gh_calls if all(w in c for w in words)]

    def state(self, tmp_path):
        return json.loads((tmp_path / "state" / "sdlc-foundry" / "notify" / "shop.json").read_text())


INSTANT = {"events": {"escalation": {"github": "instant", "slack": "instant", "email": "off", "desktop": "instant"},
                      "approve": {"github": "instant", "slack": "instant", "desktop": "instant", "email": "off"},
                      "alert": {"github": "off", "slack": "instant", "desktop": "off", "email": "off"}},
           "slack": {"channels": ["#shop-dev"]}}
TUE_NOON = dt.datetime(2026, 10, 27, 12, 0)


def esc():
    return need("escalation", spec="011-cart", object={"type": "run", "run_id": "r1", "spec": "011-cart"}, reason="3 CI fix rounds")


def test_each_instant_channel_gets_one_notification_per_event_ac_122_23(tmp_path, monkeypatch):  # AC-122.23
    w = World(tmp_path, monkeypatch, INSTANT, TUE_NOON)
    w.needs = [esc()]
    w.once()
    assert len(w.posts) == 1 and w.posts[0][0] == WEBHOOK and "3 CI fix rounds" in json.dumps(w.posts[0][1])
    [create] = w.calls("issue", "create")
    assert "notify" in " ".join(create) and "Signature:" in " ".join(create)
    assert len(w.desktop) == 1 and not w.mails
    w.once()
    w.once()
    assert len(w.posts) == 1 and len(w.calls("issue", "create")) == 1 and len(w.desktop) == 1


def test_a_github_notification_for_approve_is_the_review_request_not_an_issue_ac_122_23(tmp_path, monkeypatch):  # AC-122.23
    w = World(tmp_path, monkeypatch, INSTANT, TUE_NOON)
    w.needs = [need("approve", spec="013-search", reason="draft without open questions")]
    w.once()
    assert not w.calls("issue", "create") and len(w.posts) == 1 and len(w.desktop) == 1


def test_for_other_events_github_assigns_the_user_to_the_existing_issue_ac_122_23(tmp_path, monkeypatch):  # AC-122.23
    doc = {"events": {"alert": {"github": "instant", "slack": "off", "desktop": "off", "email": "off"}}}
    w = World(tmp_path, monkeypatch, doc, TUE_NOON)
    w.issues = [{"repo": "acme/shop-api", "number": 9, "title": "5xx", "labels": [{"name": "alert"}, {"name": "env:staging"}],
                 "createdAt": "2026-10-27T10:00:00Z"}]
    w.once()
    [edit] = w.calls("issue", "edit")
    assert "--add-assignee" in edit and "9" in edit


def test_resolving_an_event_clears_it_everywhere_but_slack_ac_122_24(tmp_path, monkeypatch):  # AC-122.24
    w = World(tmp_path, monkeypatch, INSTANT, TUE_NOON)
    w.needs = [esc()]
    w.once()
    w.needs = []
    w.once()
    assert w.calls("issue", "close") and any("88" in a for c in w.calls("issue", "close") for a in c)
    assert w.withdrawn == ["d1"]
    assert len(w.posts) == 1
    ev = w.state(tmp_path)["events"]
    [(key, rec)] = ev.items()
    assert key.startswith("escalation:") and rec["resolved_at"]


def test_the_next_digest_lists_a_resolved_event_as_done_ac_122_24(tmp_path, monkeypatch):  # AC-122.24
    doc = {"events": {"escalation": {"slack": "instant", "github": "off", "desktop": "off", "email": "off"}},
           "slack": {"channels": ["#shop-dev"]}, "digest": {"at": "09:00", "days": ["mon", "tue", "wed", "thu", "fri"]}}
    doc["events"]["promote"] = {"slack": "digest", "github": "off", "desktop": "off", "email": "off"}
    w = World(tmp_path, monkeypatch, doc, TUE_NOON)
    w.needs = [esc()]
    w.once()
    w.needs = []
    w.shipped = [{"what": "012-checkout shipped in 1.4.0"}]
    w.when = dt.datetime(2026, 10, 28, 9, 0)
    w.once()
    digest = [p for u, p in w.posts][-1]
    text = json.dumps(digest)
    assert "done" in text.lower() and "011-cart" in text


def test_a_digest_lists_open_items_and_what_shipped_ac_122_25(tmp_path, monkeypatch):  # AC-122.25
    doc = {"events": {"approve": {"slack": "digest", "github": "off", "desktop": "off", "email": "off"}},
           "slack": {"channels": ["#shop-dev"]}, "digest": {"at": "09:00", "days": ["tue"]}}
    w = World(tmp_path, monkeypatch, doc, dt.datetime(2026, 10, 27, 9, 0))
    w.needs = [need("approve", spec="013-search", reason="draft without open questions")]
    w.shipped = [{"what": "012-checkout shipped in 1.4.0"}]
    w.once()
    [(url, payload)] = w.posts
    text = json.dumps(payload)
    assert url == WEBHOOK and "013-search" in text and "012-checkout" in text


def test_the_digest_is_sent_once_and_only_at_its_time_ac_122_25(tmp_path, monkeypatch):  # AC-122.25
    doc = {"events": {"approve": {"slack": "digest", "github": "off", "desktop": "off", "email": "off"}},
           "slack": {"channels": ["#shop-dev"]}, "digest": {"at": "09:00", "days": ["mon", "tue", "wed", "thu", "fri"]}}
    w = World(tmp_path, monkeypatch, doc, dt.datetime(2026, 10, 27, 8, 0))
    w.needs = [need("approve", spec="013-search", reason="draft")]
    w.once()
    assert w.posts == []                        # before 09:00
    w.when = dt.datetime(2026, 10, 27, 9, 5)
    w.once()
    w.once()
    assert len(w.posts) == 1                    # once
    w.when = dt.datetime(2026, 10, 31, 9, 5)    # a Saturday
    w.once()
    assert len(w.posts) == 1


def test_an_empty_digest_is_not_sent_ac_122_25(tmp_path, monkeypatch):  # AC-122.25
    doc = {"events": {"approve": {"slack": "digest", "github": "off", "desktop": "off", "email": "off"}},
           "slack": {"channels": ["#shop-dev"]}, "digest": {"at": "09:00", "days": ["tue"]}}
    w = World(tmp_path, monkeypatch, doc, dt.datetime(2026, 10, 27, 9, 0))
    w.once()
    assert w.posts == [] and w.mails == []


def test_quiet_hours_hold_instant_notifications_ac_122_26(tmp_path, monkeypatch):  # AC-122.26
    doc = dict(INSTANT, quiet_hours="22:00-07:00")
    w = World(tmp_path, monkeypatch, doc, dt.datetime(2026, 10, 27, 23, 30))
    w.needs = [esc()]
    w.once()
    assert not w.posts and not w.desktop and not w.calls("issue", "create")
    w.when = dt.datetime(2026, 10, 28, 7, 30)
    w.once()
    assert not w.posts                          # a held event is not sent late as an instant: it waits for the next digest


def test_an_alert_on_a_prod_instance_breaks_quiet_hours_ac_122_26(tmp_path, monkeypatch):  # AC-122.26
    doc = dict(INSTANT, quiet_hours="22:00-07:00")
    w = World(tmp_path, monkeypatch, doc, dt.datetime(2026, 10, 27, 23, 30))
    w.issues = [{"repo": "acme/shop-api", "number": 9, "title": "5xx", "labels": [{"name": "alert"}, {"name": "env:prod"}],
                 "createdAt": "2026-10-27T23:00:00Z"},
                {"repo": "acme/shop-api", "number": 10, "title": "slow", "labels": [{"name": "alert"}, {"name": "env:staging"}],
                 "createdAt": "2026-10-27T23:00:00Z"}]
    w.once()
    assert len(w.posts) == 1 and "5xx" in json.dumps(w.posts[0][1]) and "slow" not in json.dumps(w.posts[0][1])


def test_held_events_wait_for_the_next_digest_and_stay_in_the_inbox_ac_122_26(tmp_path, monkeypatch):  # AC-122.26
    doc = dict(INSTANT, quiet_hours="22:00-07:00", digest={"at": "09:00", "days": ["mon", "tue", "wed", "thu", "fri"]})
    doc["events"]["escalation"]["slack"] = "instant"
    w = World(tmp_path, monkeypatch, doc, dt.datetime(2026, 10, 27, 23, 30))
    w.needs = [esc()]
    w.once()
    w.when = dt.datetime(2026, 10, 28, 9, 0)
    w.once()
    texts = [json.dumps(p) for _, p in w.posts]
    assert any("011-cart" in t for t in texts)
    assert w.needs                              # the Inbox still has it: the notifier never touches the needs list


def test_notifications_only_reach_the_configured_endpoints_ac_122_2(tmp_path, monkeypatch):  # AC-122.2
    import notify
    w = World(tmp_path, monkeypatch, INSTANT, TUE_NOON)
    w.needs = [esc()]
    w.once()
    assert {u for u, _ in w.posts} == {WEBHOOK}
    assert all(c[0] in {"issue", "api", "pr", "repo"} for c in w.gh_calls)


def test_the_cli_routes_ui_notify_once_ac_122_23(tmp_path, monkeypatch, capsys):  # AC-122.23
    import cplat
    w = World(tmp_path, monkeypatch, INSTANT, TUE_NOON)
    w.needs = [esc()]
    assert cplat.main(["ui", "notify", "--once", "--repo-dir", str(w.repo)]) == 0
    assert len(w.posts) == 1
