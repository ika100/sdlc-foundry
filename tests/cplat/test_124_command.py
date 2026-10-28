"""Spec 124 acceptance tests: `cplat system autonomy show|set|pause|resume` behind `/system:autonomy`
(AC-124.5, AC-124.6, AC-124.7, AC-124.8, AC-124.13, AC-124.21).

Contract: design.md "`cplat system autonomy …`". The world is a gitops-app checkout with the real renderer and three environments that
have engines; engines are the fake of autonomy_support (`engine._http`), the pull request goes through a recording `gitops.open_pr`,
`gh` through the replaceable `autonomycmd.gh(args) -> str`, the run store through `runs.open_store` (see autonomy_support's header)."""
import json
import shutil
import subprocess
import sys

import pytest
import yaml

import cplat
import gitops
import runs
from autonomy_support import (APP, DEV_URL, PROD_URL, STG_URL, AutoStore, ago, audit_event, declared_system, engines, iso,  # noqa: F401
                              now, run_record, store)
from system_fixtures import RENDER5, files, git, init_git, render, write_system


class CmdGh:
    """Replaces `autonomycmd.gh`."""

    def __init__(self):
        self.calls = []
        self.open_pr_for: dict[str, list[dict]] = {}

    def __call__(self, args):
        args = [str(a) for a in args]
        self.calls.append(args)
        if args[:2] == ["api", "user"]:
            return "eike\n"
        if args[:2] == ["pr", "list"]:
            head = args[args.index("--head") + 1]
            return json.dumps(self.open_pr_for.get(head, []))
        return ""


class World:
    pass


@pytest.fixture()
def world(tmp_path, monkeypatch, engines):
    w = World()
    w.repo, w.engines, w.prs, w.gh = tmp_path / "shop-gitops", engines, [], CmdGh()
    w.repo.mkdir()
    write_system(w.repo, "# the shop system (keep this comment)\n" + yaml.safe_dump(declared_system(), sort_keys=False))
    (w.repo / "scripts").mkdir()
    shutil.copy(RENDER5, w.repo / "scripts" / "render.py")
    (w.repo / ".copier-answers.yml").write_text("github_org: acme\napp_name: shop\nproject_name: shop-gitops\n")
    w.render_error = render(w.repo).stderr          # fails until render.py knows the autonomy keys; the tests then fail on the missing behaviour
    init_git(w.repo)

    def open_pr(repo, branch, title, body):
        status = git(repo, "status", "--porcelain")
        changed = sorted(ln[3:].strip() for ln in status.splitlines())
        w.prs.append({"branch": branch, "title": title, "body": body, "changed": changed, "system_yaml": (repo / APP / "system.yaml").read_text()})
        return f"https://github.com/acme/shop-gitops/pull/{len(w.prs) + 10}"
    monkeypatch.setattr(gitops, "open_pr", open_pr)
    try:
        import autonomycmd
        monkeypatch.setattr(autonomycmd, "gh", w.gh)
    except ImportError:
        pass
    return w


def cmd(w, *argv, capsys=None):
    rc = cplat.main(["system", "autonomy", *argv, "--repo-dir", str(w.repo)])
    if capsys is None:
        return rc
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def sysdoc(w):
    return yaml.safe_load((w.repo / APP / "system.yaml").read_text())


def recorded(kind=None):
    """The audit events `cplat` recorded (the local buffer, because no store is configured)."""
    buf = runs.state_dir() / "audit-buffer.jsonl"
    evs = [json.loads(ln) for ln in buf.read_text().splitlines() if ln.strip()] if buf.is_file() else []
    return [e for e in evs if kind is None or e["kind"] == kind]


# ---------------- AC-124.6: set ----------------

def test_raising_a_level_opens_one_pr_that_changes_only_that_environments_autonomy_ac_124_6(world, capsys):  # AC-124.6
    """AC-124.6: raising a level opens one pr that changes only that environments autonomy."""
    before = sysdoc(world)
    rc, out, err = cmd(world, "set", "staging", "act", "--pr", capsys=capsys)
    assert rc == 0, err
    [pr] = world.prs
    assert pr["branch"] == "system/autonomy-staging" and pr["title"] == "chore(system): autonomy staging propose → act"
    assert pr["changed"] == [f"{APP}/autonomy.json", f"{APP}/system.yaml"]
    after = sysdoc(world)
    assert after["environments"]["staging"]["autonomy"]["level"] == "act"
    after["environments"]["staging"]["autonomy"]["level"] = "propose"
    assert after == before, "nothing but staging's autonomy changed"
    assert "# the shop system (keep this comment)" in (world.repo / APP / "system.yaml").read_text()
    assert world.engines.posts == [], "a higher level takes effect only after the merge: no signal"
    assert "pull/" in out


def test_the_description_lists_old_and_new_level_guardrails_and_what_the_level_allows_ac_124_6(world):  # AC-124.6
    """AC-124.6: the description lists old and new level guardrails and what the level allows."""
    import autonomy
    assert cmd(world, "set", "staging", "act", "--max-lines", "300", "--pr") == 0
    body = world.prs[0]["body"]
    assert "propose" in body and "act" in body
    assert autonomy.allows("act") in body
    for g in ("riskGate.maxLines", "riskGate.maxFiles", "autoMerge.maxCriticality", "budget.runsPerDay", "window", "undoWindow"):
        assert g in body, g
    assert "200" in body and "300" in body, "old and new value of the changed guardrail"
    assert "Takes effect after the merge." in body


def test_lowering_a_level_signals_the_engine_at_once_and_the_pr_records_it_ac_124_6(world):  # AC-124.6
    """AC-124.6: lowering a level signals the engine at once and the pr records it."""
    assert cmd(world, "set", "dev", "propose", "--pr") == 0
    [post] = world.engines.posts
    assert post["url"] == DEV_URL and post["body"]["kind"] == "lower" and post["body"]["environment"] == "dev"
    assert post["body"]["policy"]["effective"] == "propose" and post["body"]["actor"] == "eike"
    [pr] = world.prs
    assert f"In effect now by signal {post['body']['id']} (confirmed)" in pr["body"]
    assert "the rest after the merge" in pr["body"]
    assert post["body"]["pr"] in (None, "") or post["body"]["pr"].startswith("https://")


def test_a_tighter_guardrail_alone_is_signalled_with_the_tighter_value_ac_124_6(world):  # AC-124.6
    """AC-124.6: a tighter guardrail alone is signalled with the tighter value."""
    assert cmd(world, "set", "dev", "act", "--max-lines", "100", "--pr") == 0
    [post] = world.engines.posts
    pol = post["body"]["policy"]
    assert pol["riskGate"]["maxLines"] == 100 and pol["effective"] == "act"


def test_a_looser_guardrail_alone_sends_no_signal_ac_124_6(world):  # AC-124.6
    """AC-124.6: a looser guardrail alone sends no signal."""
    assert cmd(world, "set", "dev", "act", "--max-lines", "400", "--pr") == 0
    assert world.engines.posts == [] and len(world.prs) == 1
    assert "Takes effect after the merge." in world.prs[0]["body"]


def test_a_lower_level_with_a_looser_guardrail_signals_only_the_tighter_part_ac_124_6(world):  # AC-124.6
    """AC-124.6: a lower level with a looser guardrail signals only the tighter part."""
    assert cmd(world, "set", "dev", "propose", "--max-files", "9", "--pr") == 0
    [post] = world.engines.posts
    pol = post["body"]["policy"]
    assert pol["effective"] == "propose" and pol["riskGate"]["maxFiles"] == 5, "the looser value is not signalled"
    assert sysdoc(world)["environments"]["dev"]["autonomy"]["riskGate"]["maxFiles"] == 9, "git gets the new value"


def test_no_signal_is_sent_for_an_environment_without_an_engine_ac_124_6(world):  # AC-124.6
    """AC-124.6: no signal is sent for an environment without an engine."""
    d = sysdoc(world)
    del d["environments"]["dev"]["autonomy"]["engine"]
    (world.repo / APP / "system.yaml").write_text(yaml.safe_dump(d, sort_keys=False))
    git(world.repo, "commit", "-qam", "no engine")
    assert render(world.repo).returncode == 0
    git(world.repo, "add", "-A")
    git(world.repo, "commit", "-qm", "render", "--allow-empty")
    assert cmd(world, "set", "dev", "observe", "--pr") == 0
    assert world.engines.posts == [] and len(world.prs) == 1


def test_a_lowering_whose_engine_is_down_still_opens_the_pr_and_says_not_confirmed_ac_124_6(world):  # AC-124.6
    """AC-124.6: a lowering whose engine is down still opens the pr and says not confirmed."""
    world.engines.down.add(DEV_URL)
    assert cmd(world, "set", "dev", "propose", "--pr") == 0
    assert "not confirmed" in world.prs[0]["body"]


def test_set_without_pr_changes_the_files_but_sends_nothing_and_opens_nothing_ac_124_6(world):  # AC-124.6
    """AC-124.6: set without pr changes the files but sends nothing and opens nothing."""
    assert cmd(world, "set", "dev", "propose") == 0
    assert world.engines.posts == [] and world.prs == []
    assert sysdoc(world)["environments"]["dev"]["autonomy"]["level"] == "propose"


def test_set_records_an_audit_event_with_who_old_and_new_ac_124_6(world):  # AC-124.6
    """AC-124.6: set records an audit event with who old and new."""
    assert cmd(world, "set", "dev", "propose", "--pr") == 0
    [ev] = recorded("set")
    assert ev["actor"] == {"type": "person", "name": "eike", "id": "eike"} or ev["actor"]["name"] == "eike"
    assert ev["environment"] == "dev" and ev["store_ref"] is None
    assert ev["detail"]["old"] and ev["detail"]["new"] and ev["detail"]["pr"].startswith("https://")
    assert ev["detail"]["signal"].startswith("sig-")


def test_every_flag_lands_in_system_yaml_with_quoted_times_ac_124_6(world):  # AC-124.6
    """AC-124.6: every flag lands in system yaml with quoted times."""
    assert cmd(world, "set", "staging", "propose", "--routes", "none", "--max-criticality", "medium", "--max-files", "3",
               "--max-lines", "80", "--regression-test", "false", "--second-review", "false", "--runs-per-day", "4",
               "--merges-per-day", "1", "--per-run", "cost=5", "--per-run", "minutes=30", "--days", "mon,tue", "--from", "08:00",
               "--to", "18:00", "--timezone", "Europe/Berlin", "--undo-window", "48h", "--engine", "https://e.example.com") == 0
    a = sysdoc(world)["environments"]["staging"]["autonomy"]
    assert a["autoMerge"] == {"routes": [], "maxCriticality": "medium"}
    assert a["riskGate"] == {"maxFiles": 3, "maxLines": 80, "regressionTest": False, "secondReview": False}
    assert a["budget"]["runsPerDay"] == 4 and a["budget"]["mergesPerDay"] == 1 and a["budget"]["perRun"]["cost"] == 5 and a["budget"]["perRun"]["minutes"] == 30
    assert a["window"] == {"days": ["mon", "tue"], "from": "08:00", "to": "18:00", "timezone": "Europe/Berlin"}
    assert a["undoWindow"] == "48h" and a["engine"] == "https://e.example.com"
    assert '"08:00"' in (world.repo / APP / "system.yaml").read_text() or "'08:00'" in (world.repo / APP / "system.yaml").read_text()


def test_an_invalid_value_exits_1_with_the_renderers_message_and_changes_nothing_ac_124_6(world, capsys):  # AC-124.6
    """AC-124.6: an invalid value exits 1 with the renderers message and changes nothing."""
    before = files(world.repo)
    rc, _, err = cmd(world, "set", "prod", "improve", "--pr", capsys=capsys)
    assert rc == 1 and "act is the highest level allowed in prod" in err
    rc, _, err = cmd(world, "set", "dev", "act", "--undo-window", "1 day", "--pr", capsys=capsys)
    assert rc == 1 and "undoWindow" in err
    assert files(world.repo) == before and world.prs == [] and world.engines.posts == []


def test_a_change_that_changes_nothing_exits_1_ac_124_6(world, capsys):  # AC-124.6
    """AC-124.6: a change that changes nothing exits 1."""
    rc, _, err = cmd(world, "set", "dev", "act", capsys=capsys)
    assert rc == 1 and "nothing to change" in err


def test_dry_run_json_lists_the_plan_the_signal_and_the_effect_and_changes_nothing_ac_124_6(world, capsys):  # AC-124.6
    """AC-124.6: dry run json lists the plan the signal and the effect and changes nothing."""
    before = files(world.repo)
    rc, out, err = cmd(world, "set", "dev", "propose", "--dry-run", "--json", capsys=capsys)
    assert rc == 0, err
    doc = json.loads(out)
    assert doc["will_do"] and doc["effect"] == "now" and doc["pr"] is None
    assert doc["signal"]["kind"] == "lower" and doc["signal"]["policy"]["effective"] == "propose"
    rc, out, _ = cmd(world, "set", "staging", "act", "--dry-run", "--json", capsys=capsys)
    assert json.loads(out)["effect"] == "after-merge" and json.loads(out)["signal"] is None
    rc, out, _ = cmd(world, "set", "dev", "propose", "--max-files", "9", "--dry-run", "--json", capsys=capsys)
    assert json.loads(out)["effect"] == "mixed"
    assert files(world.repo) == before and world.engines.posts == [] and world.prs == []


# ---------------- AC-124.5: promotion stays with the promote rule ----------------

def test_setting_act_in_prod_keeps_the_manual_promote_rule_ac_124_5(world, capsys):  # AC-124.5
    """AC-124.5: setting act in prod keeps the manual promote rule."""
    assert cmd(world, "set", "prod", "act", "--pr") == 0
    d = sysdoc(world)
    assert d["environments"]["prod"]["autonomy"]["level"] == "act"
    assert d["environments"]["prod"].get("promote", "manual") == "manual"
    assert d["environments"]["staging"].get("promote") == sysdoc(world)["environments"]["staging"].get("promote")
    out = subprocess.run([sys.executable, "scripts/render.py", "--check"], cwd=world.repo, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    aj = json.loads((world.repo / APP / "autonomy.json").read_text())
    assert aj["environments"]["prod"]["promotion"] == "manual"


# ---------------- AC-124.7: pause and resume ----------------

def test_pause_signals_every_environment_then_opens_the_pr_that_records_it_ac_124_7(world, capsys):  # AC-124.7
    """AC-124.7: pause signals every environment then opens the pr that records it."""
    rc, out, err = cmd(world, "pause", "--pr", capsys=capsys)
    assert rc == 0, err
    assert sorted(p["url"] for p in world.engines.posts) == sorted([DEV_URL, STG_URL, PROD_URL])
    assert {p["body"]["kind"] for p in world.engines.posts} == {"pause"}
    for env in ("dev", "staging", "prod"):
        assert f"{env}" in out
    assert out.count("confirmed") >= 3
    [pr] = world.prs
    assert pr["branch"] == "system/autonomy-pause" and pr["title"] == "chore(system): pause all autonomy"
    text = pr["system_yaml"]
    assert yaml.safe_load(text)["autonomy"] == {"paused": True}
    assert text.index("\nautonomy:") < text.index("\nenvironments:"), "paused sits at the top of system.yaml"
    assert pr["changed"] == [f"{APP}/autonomy.json", f"{APP}/system.yaml"]
    assert json.loads((world.repo / APP / "autonomy.json").read_text())["paused"] is True


def test_pause_is_audited_with_who_and_when_ac_124_7(world):  # AC-124.7
    """AC-124.7: pause is audited with who and when."""
    assert cmd(world, "pause", "--pr") == 0
    [ev] = recorded("pause")
    assert ev["actor"]["name"] == "eike" and ev["at"].endswith("Z")
    assert sorted(ev["detail"]["confirmed"]) == ["dev", "prod", "staging"] and ev["detail"]["unconfirmed"] == []
    assert ev["detail"]["pr"].startswith("https://github.com/") and ev["detail"]["signal"].startswith("sig-")


def test_pause_dry_run_sends_nothing_and_opens_nothing_ac_124_7(world, capsys):  # AC-124.7
    """AC-124.7: pause dry run sends nothing and opens nothing."""
    before = files(world.repo)
    rc, out, err = cmd(world, "pause", "--dry-run", "--json", capsys=capsys)
    assert rc == 0, err
    assert json.loads(out)["will_do"] and files(world.repo) == before and world.engines.posts == [] and world.prs == []


def test_resume_signals_and_opens_the_pr_that_removes_paused_ac_124_7(world):  # AC-124.7
    """AC-124.7: resume signals and opens the pr that removes paused."""
    d = sysdoc(world)
    d = {"autonomy": {"paused": True}, **d}
    (world.repo / APP / "system.yaml").write_text(yaml.safe_dump(d, sort_keys=False))
    assert render(world.repo).returncode == 0
    git(world.repo, "add", "-A")
    git(world.repo, "commit", "-qm", "paused")
    assert cmd(world, "resume", "--pr") == 0
    assert {p["body"]["kind"] for p in world.engines.posts} == {"resume"} and len(world.engines.posts) == 3
    [pr] = world.prs
    assert pr["branch"] == "system/autonomy-resume" and pr["title"] == "chore(system): resume autonomy"
    assert "autonomy" not in yaml.safe_load(pr["system_yaml"]), "the top-level autonomy is empty and goes"
    assert yaml.safe_load(pr["system_yaml"])["environments"]["dev"]["autonomy"]["level"] == "act", "the levels in system.yaml apply again"
    assert recorded("resume")


def test_resume_closes_the_open_pause_pr_instead_of_opening_one_ac_124_7(world):  # AC-124.7
    """AC-124.7: resume closes the open pause pr instead of opening one."""
    world.gh.open_pr_for["system/autonomy-pause"] = [{"number": 7, "url": "https://github.com/acme/shop-gitops/pull/7"}]
    assert cmd(world, "resume", "--pr") == 0
    assert world.prs == []
    close = [c for c in world.gh.calls if c[:2] == ["pr", "close"] and "7" in c]
    assert close and any("Resumed by eike at" in " ".join(c) and "before this merged." in " ".join(c) for c in close)
    assert len(world.engines.posts) == 3 and recorded("resume")


# ---------------- AC-124.21: an engine that cannot be reached ----------------

def test_an_unreachable_engine_is_named_and_the_pr_still_opens_ac_124_21(world, capsys):  # AC-124.21
    """AC-124.21: an unreachable engine is named and the pr still opens."""
    world.engines.down.add(PROD_URL)
    rc, out, err = cmd(world, "pause", "--pr", capsys=capsys)
    assert rc == 0, err
    assert "not confirmed within 60 s" in out
    line = next(ln for ln in out.splitlines() if "not confirmed within 60 s" in ln)
    assert "prod" in line and "dev" not in line and "staging" not in line
    assert len(world.prs) == 1
    [ev] = recorded("pause")
    assert ev["detail"]["unconfirmed"] == ["prod"] and sorted(ev["detail"]["confirmed"]) == ["dev", "staging"]


def test_show_marks_the_unconfirmed_environment_until_the_engine_confirms_ac_124_21(world, capsys):  # AC-124.21
    """AC-124.21: show marks the unconfirmed environment until the engine confirms."""
    world.engines.down.add(PROD_URL)
    assert cmd(world, "pause", "--pr") == 0
    capsys.readouterr()
    rc, out, _ = cmd(world, "show", "--json", capsys=capsys)
    prod = next(e for e in json.loads(out)["environments"] if e["name"] == "prod")
    assert prod["confirmed"] is False and [p["kind"] for p in prod["pending"]] == ["pause"]
    assert next(e for e in json.loads(out)["environments"] if e["name"] == "dev")["confirmed"] is True
    # the engine comes back and shows the requested state
    world.engines.down.discard(PROD_URL)
    world.engines.state[PROD_URL] = {"prod": {"paused": True, "effective": "observe"}}
    rc, out, _ = cmd(world, "show", "--json", capsys=capsys)
    prod = next(e for e in json.loads(out)["environments"] if e["name"] == "prod")
    assert prod["confirmed"] is True and prod["pending"] == []


def test_show_confirms_an_environment_when_a_signal_honoured_event_exists_ac_124_21(world, store, capsys):  # AC-124.21
    """AC-124.21: show confirms an environment when a signal honoured event exists."""
    world.engines.down.add(PROD_URL)
    assert cmd(world, "pause", "--pr") == 0
    sig = recorded("pause")[0]["detail"]["signal"] if recorded("pause") else None
    if sig is None:                                             # the store was configured: the event is in the store
        sig = json.loads(next(v for k, v in store.files.items() if k.startswith("audit/")))["detail"]["signal"]
    store.add_event(audit_event("signal-honoured", env="prod", at=iso(now()), obj={"type": "signal", "signal": sig}))
    capsys.readouterr()
    rc, out, _ = cmd(world, "show", "--json", capsys=capsys)
    prod = next(e for e in json.loads(out)["environments"] if e["name"] == "prod")
    assert prod["confirmed"] is True


# ---------------- AC-124.8 / AC-124.13: show ----------------

def show_doc(w, capsys, *extra):
    rc, out, err = cmd(w, "show", "--json", *extra, capsys=capsys)
    assert rc == 0, err
    return json.loads(out)


def test_show_json_has_the_documented_shape_per_environment_ac_124_8(world, store, capsys):  # AC-124.8
    """AC-124.8: show json has the documented shape per environment."""
    store.add_run(run_record(started=iso(now()), environment="dev", run_id="20261026T091500Z-aaaaaaaa", budget={
        "used": {"minutes": 1, "invocations": 1, "reruns": 0, "cost": 1.5}, "limits": {"minutes": 60, "invocations": 20, "reruns": 2, "cost": 3}}))
    store.add_event(audit_event("merge", env="dev", at=iso(now())))
    doc = show_doc(world, capsys)
    assert doc["schema"] == 1 and doc["system"] == "shop" and doc["paused"] is False and "read_at" in doc
    assert [e["name"] for e in doc["environments"]] == ["dev", "staging", "prod"]
    dev = doc["environments"][0]
    assert dev["declared"] == "act" and dev["effective"] == "act" and dev["cap"] == "improve" and dev["undoWindow"] == "24h"
    assert dev["guardrails"]["riskGate"]["maxLines"] == 200
    assert dev["budget_today"] == {"runs": 1, "merges": 1, "cost": 1.5, "runsPerDay": 5, "mergesPerDay": 2}
    assert dev["engine"]["url"] == DEV_URL and dev["engine"]["state"] == "ok" and dev["engine"]["name"] == "ai-ops"
    assert dev["engine"]["heartbeat_at"] and dev["supervised"] is True and dev["confirmed"] is True
    assert dev["pending"] == [] and dev["override"] is None and dev["caps"] == []
    assert doc["store"]["state"] == "ok" and doc["unavailable"] == []


def test_show_lists_the_actions_done_on_their_own_in_the_last_24_hours_with_undo_ac_124_8(world, store, capsys):  # AC-124.8
    """AC-124.8: show lists the actions done on their own in the last 24 hours with undo."""
    store.add_event(audit_event("merge", env="dev", at=ago(hours=2), eid="20261026T071733Z-ai-ops-aaaaaaaa"))
    store.add_event(audit_event("merge", env="dev", at=ago(hours=30), eid="20261025T031733Z-ai-ops-bbbbbbbb"))
    store.add_event(audit_event("pause", env="dev", at=ago(hours=1), name="eike", eid="20261026T081733Z-cplat-cccccccc"))
    doc = show_doc(world, capsys)
    assert [a["event_id"] for a in doc["actions"]] == ["20261026T071733Z-ai-ops-aaaaaaaa"]
    assert set(doc["actions"][0]["undo"]) == {"allowed", "reason", "command"}


def test_show_prints_a_block_per_environment_in_text_ac_124_8(world, capsys):  # AC-124.8
    """AC-124.8: show prints a block per environment in text."""
    rc, out, err = cmd(world, "show", capsys=capsys)
    assert rc == 0, err
    for env in ("dev", "staging", "prod"):
        assert env in out
    for needle in ("act", "propose", "paused", "riskGate", "maxLines", "budget", "ai-ops", DEV_URL, "heartbeat"):
        assert needle in out, needle


def test_show_names_a_paused_system_ac_124_8(world, capsys):  # AC-124.8
    """AC-124.8: show names a paused system."""
    d = sysdoc(world)
    (world.repo / APP / "system.yaml").write_text(yaml.safe_dump({"autonomy": {"paused": True}, **d}, sort_keys=False))
    doc = show_doc(world, capsys)
    assert doc["paused"] is True
    assert all(e["effective"] == "observe" for e in doc["environments"])
    assert doc["environments"][0]["declared"] == "act"


def test_show_lists_component_caps_next_to_the_environment_ac_124_22(world, capsys):  # AC-124.22
    """AC-124.22: show lists component caps next to the environment."""
    d = sysdoc(world)
    d["components"]["api"]["instances"] = {"dev": {"autonomy": {"max": "propose"}}}
    (world.repo / APP / "system.yaml").write_text(yaml.safe_dump(d, sort_keys=False))
    dev = show_doc(world, capsys)["environments"][0]
    assert dev["caps"] == [{"component": "api", "max": "propose", "effective": "propose"}]


def test_an_engine_that_is_down_is_unreachable_and_not_supervised_and_show_still_exits_0_ac_124_13(world, capsys):  # AC-124.13
    """AC-124.13: an engine that is down is unreachable and not supervised and show still exits 0."""
    world.engines.down.add(PROD_URL)
    rc, out, _ = cmd(world, "show", "--json", capsys=capsys)
    assert rc == 0
    doc = json.loads(out)
    prod = next(e for e in doc["environments"] if e["name"] == "prod")
    assert prod["engine"]["state"] == "unreachable" and prod["supervised"] is False
    assert next(e for e in doc["environments"] if e["name"] == "dev")["supervised"] is True


def test_a_heartbeat_older_than_5_minutes_is_unreachable_ac_124_13(world, capsys):  # AC-124.13
    """AC-124.13: a heartbeat older than 5 minutes is unreachable."""
    world.engines.heartbeat[STG_URL] = ago(minutes=6)
    staging = next(e for e in show_doc(world, capsys)["environments"] if e["name"] == "staging")
    assert staging["engine"]["state"] == "unreachable" and staging["supervised"] is False
    assert staging["engine"]["heartbeat_at"] == world.engines.heartbeat[STG_URL] or staging["engine"]["heartbeat_at"] is not None


def test_an_unreachable_engine_still_shows_when_it_was_last_heard_from_ac_124_13(world, capsys):  # AC-124.13
    """AC-124.13: an unreachable engine still shows when it was last heard from."""
    world.engines.heartbeat[PROD_URL] = ago(minutes=2)
    first = next(e for e in show_doc(world, capsys)["environments"] if e["name"] == "prod")
    assert first["engine"]["state"] == "ok"
    world.engines.down.add(PROD_URL)
    second = next(e for e in show_doc(world, capsys)["environments"] if e["name"] == "prod")
    assert second["engine"]["state"] == "unreachable" and second["engine"]["heartbeat_at"] == world.engines.heartbeat[PROD_URL]


def test_an_environment_without_an_engine_has_state_none_and_is_not_supervised_ac_124_13(world, capsys):  # AC-124.13
    """AC-124.13: an environment without an engine has state none and is not supervised."""
    d = sysdoc(world)
    del d["environments"]["staging"]["autonomy"]["engine"]
    (world.repo / APP / "system.yaml").write_text(yaml.safe_dump(d, sort_keys=False))
    staging = next(e for e in show_doc(world, capsys)["environments"] if e["name"] == "staging")
    assert staging["engine"]["state"] == "none" and staging["engine"]["url"] is None and staging["supervised"] is False


def test_show_exits_0_when_the_store_is_unreachable_and_says_so_ac_124_13(world, monkeypatch, capsys):  # AC-124.13
    """AC-124.13: show exits 0 when the store is unreachable and says so."""
    monkeypatch.setenv("CPLAT_RUNS_REPO", "acme/runs")

    def boom(slug):
        raise RuntimeError("store offline")
    monkeypatch.setattr(runs, "open_store", boom)
    doc = show_doc(world, capsys)
    assert doc["store"]["state"] in ("unreachable", "unset", "public")
