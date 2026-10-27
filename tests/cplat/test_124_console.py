"""Spec 124 acceptance tests: the console supervises autonomy (AC-124.13, AC-124.15, AC-124.17, AC-124.18, AC-124.19, AC-124.21, AC-124.22
and the console half of AC-124.6, AC-124.7, AC-124.16).

Contract: design.md "Console" (source, actions, preview form, tab markup, badge, review decision, signal facts, run panel). The console
runs over file-backed JSON sources (console_support); the `autonomy` source is the document of `cplat system autonomy show --json`
(autonomy_support.show_json). Nothing reaches the network, GitHub or claude."""
import json
import re
from pathlib import Path

import pytest

from autonomy_support import (PROD_URL, SHA, console_data, declared_system, done_action, engine_run_row, engines, env_show, review_need,  # noqa: F401
                              show_json, signal_triage_need, undo_info)
from console_support import disabled, needs_json, parse, q, runs_json
from test_124_command import world  # noqa: F401  (world is a fixture)
from test_124_store import FACTS
from test_console_actions import ready  # noqa: F401  (ready is a fixture)

GITOPS = "acme/shop-gitops"
EID = "20261026T091733Z-ai-ops-3f9c2a71"


@pytest.fixture()
def cons(console, tmp_path):
    def make(**over):
        return console(console_data(tmp_path, **over))
    return make


def tab(c, name="autonomy"):
    return c.page(f"/system?tab={name}")


def env_section(root, env):
    [s] = q(root, "section", data_env=env)
    return s


# ---------------- html fragments ----------------

def test_the_engine_badge_fragment_ac_124_18():  # AC-124.18
    """AC-124.18: the engine badge fragment."""
    from console import html
    assert html.engine_badge("ai-ops") == '<span class="badge" data-engine="ai-ops">ai-ops</span>'
    assert html.engine_badge(None) == ""
    assert "<script" not in html.engine_badge("<script>x</script>")


def test_the_guardrail_list_fragment_has_one_entry_per_effective_guardrail_ac_124_19():  # AC-124.19
    """AC-124.19: the guardrail list fragment has one entry per effective guardrail."""
    from console import html
    policy = env_show()
    root = parse(html.guardrails(policy))
    [dl] = q(root, "dl", data_guardrails=True)
    keys = [dd.attrs["data-key"] for dd in q(dl, "dd")]
    assert keys[:2] == ["autoMerge.routes", "autoMerge.maxCriticality"]
    for k in ("riskGate.maxFiles", "riskGate.maxLines", "riskGate.regressionTest", "riskGate.secondReview", "budget.runsPerDay",
              "budget.mergesPerDay", "window.days", "window.from", "window.to", "window.timezone", "undoWindow"):
        assert k in keys, k
    assert keys.index("riskGate.maxFiles") < keys.index("budget.runsPerDay") < keys.index("window.from") < keys.index("undoWindow")
    assert next(dd for dd in q(dl, "dd") if dd.attrs["data-key"] == "riskGate.maxLines").text() == "200"
    assert len(q(dl, "dt")) == len(q(dl, "dd"))


def test_the_level_sentences_stay_in_sync_with_the_platforms_ac_124_19():  # AC-124.19
    """AC-124.19: the level sentences stay in sync with the platforms."""
    import autonomy
    from console import html
    for lv in autonomy.LEVELS:
        assert html.level_sentence(lv) == autonomy.allows(lv)
        assert html.level_name(lv)


# ---------------- AC-124.19: the System tabs ----------------

def test_system_has_two_tabs_and_marks_the_current_one_ac_124_19(cons):  # AC-124.19
    """AC-124.19: system has two tabs and marks the current one."""
    c = cons()
    for path, current in (("/system", "overview"), ("/system?tab=overview", "overview"), ("/system?tab=autonomy", "autonomy")):
        root, _ = c.page(path)
        [nav] = q(root, "nav", aria_label="System sections")
        tabs = q(nav, "a", data_tab=True)
        assert [t.attrs["data-tab"] for t in tabs] == ["overview", "autonomy"], path
        assert [t.attrs["data-tab"] for t in tabs if t.attrs.get("aria-current") == "page"] == [current], path


def test_an_unknown_tab_is_404_ac_124_19(cons):  # AC-124.19
    """AC-124.19: an unknown tab is 404."""
    assert cons().get("/system?tab=nonsense")[0] == 404


def test_the_overview_is_unchanged_ac_124_19(cons):  # AC-124.19
    """AC-124.19: the overview is unchanged."""
    root, _ = cons().page("/system")
    assert {f.attrs["data-form"] for f in q(root, None, data_form=True)} == {"component", "api", "resource", "environment", "system"}


# ---------------- AC-124.19: the Autonomy tab ----------------

def test_each_environment_has_a_section_with_level_and_flags_ac_124_19(cons):  # AC-124.19
    """AC-124.19: each environment has a section with level and flags."""
    root, _ = tab(cons())
    assert [s.attrs["data-env"] for s in q(root, "section", data_env=True)] == ["dev", "staging", "prod"]
    prod = env_section(root, "prod")
    assert prod.attrs["data-level"] == "act" and prod.attrs["data-supervised"] == "true" and prod.attrs["data-confirmed"] == "true"


def test_the_level_is_a_choice_of_the_five_levels_in_a_form_that_previews_ac_124_19(cons):  # AC-124.19
    """AC-124.19: the level is a choice of the five levels in a form that previews."""
    root, _ = tab(cons())
    dev = env_section(root, "dev")
    [form] = q(dev, "form", data_form="autonomy")
    assert form.attrs["data-post"] == "/api/preview" and "data-wrap" in form.attrs
    radios = q(form, "input", type="radio", name="level")
    assert [r.attrs["value"] for r in radios] == ["observe", "advise", "propose", "act", "improve"]
    assert [r.attrs["value"] for r in radios if "checked" in r.attrs] == ["act"]
    assert not [r for r in radios if disabled(r)]


def test_levels_above_the_environments_cap_are_disabled_with_the_reason_ac_124_19(cons):  # AC-124.19
    """AC-124.19: levels above the environments cap are disabled with the reason."""
    root, _ = tab(cons())
    prod = env_section(root, "prod")
    radios = {r.attrs["value"]: r for r in q(prod, "input", type="radio", name="level")}
    assert disabled(radios["improve"]) and radios["improve"].attrs.get("aria-disabled") == "true"
    assert not any(disabled(radios[lv]) for lv in ("observe", "advise", "propose", "act"))
    assert any("act is the highest level allowed in prod" in s.text() for s in q(prod, "span", data_disabled_reason=True))


def test_the_effective_guardrails_are_listed_with_their_keys_ac_124_19(cons):  # AC-124.19
    """AC-124.19: the effective guardrails are listed with their keys."""
    root, _ = tab(cons())
    [dl] = q(env_section(root, "dev"), "dl", data_guardrails=True)
    assert next(dd for dd in q(dl, "dd") if dd.attrs["data-key"] == "riskGate.maxLines").text() == "200"


def test_a_change_shows_its_diff_command_and_the_open_pr_button_ac_124_19(cons):  # AC-124.19
    """AC-124.19: a change shows its diff command and the open pr button."""
    root, text = tab(cons())
    dev = env_section(root, "dev")
    assert q(dev, "pre", data_diff=True) and q(dev, "code", data_command=True)
    [btn] = q(dev, "button", data_action="model")
    assert "Open PR" in btn.text()
    assert "/api/preview" in text


def test_pause_all_autonomy_explains_what_pausing_means_ac_124_19(cons):  # AC-124.19
    """AC-124.19: pause all autonomy explains what pausing means."""
    root, _ = tab(cons())
    [btn] = q(root, "button", data_action="pause")
    assert "Pause all autonomy" in btn.text() and btn.attrs.get("data-confirm")
    assert json.loads(btn.attrs["data-object"]) == {"repo": GITOPS}
    means = q(root, "p", data_pause_means=True)[0].text().lower()
    for needle in ("observe", "60 seconds", "next step", "pull request", "resume", "system.yaml"):
        assert needle in means, needle
    assert not q(root, None, data_paused="true") and not q(root, "button", data_action="resume")


def test_a_paused_system_shows_the_banner_and_resume_ac_124_19(cons):  # AC-124.19
    """AC-124.19: a paused system shows the banner and resume."""
    envs = [env_show(n, d, effective="observe", cap=c) for n, d, c in (("dev", "act", "improve"), ("staging", "propose", "improve"), ("prod", "act", "act"))]
    root, _ = tab(cons(autonomy=show_json(envs=envs, paused=True)))
    assert q(root, "section", data_paused="true")
    [btn] = q(root, "button", data_action="resume")
    assert "Resume" in btn.text() and json.loads(btn.attrs["data-object"]) == {"repo": GITOPS}
    assert not q(root, "button", data_action="pause")
    assert env_section(root, "dev").attrs["data-level"] == "observe"


def test_the_engine_status_shows_state_and_heartbeat_ac_124_19(cons):  # AC-124.19
    """AC-124.19: the engine status shows state and heartbeat."""
    root, _ = tab(cons())
    prod = env_section(root, "prod")
    [st] = q(prod, "span", data_engine_state=True)
    assert st.attrs["data-engine-state"] == "ok"
    [hb] = q(prod, "time", data_heartbeat=True)
    assert hb.attrs["data-heartbeat"] == "2026-10-26T09:19:00Z"


# ---------------- AC-124.13 / AC-124.21: not supervised, not confirmed ----------------

def test_an_unreachable_engine_is_shown_as_not_supervised_with_the_unavailable_part_ac_124_13(cons):  # AC-124.13
    """AC-124.13: an unreachable engine is shown as not supervised with the unavailable part."""
    envs = [env_show("dev", "act", cap="improve"), env_show("staging", "propose", cap="improve"),
            env_show("prod", "act", engine={"url": PROD_URL, "state": "unreachable", "name": "ai-ops", "version": None,
                                            "heartbeat_at": "2026-10-26T08:00:00Z"}, supervised=False)]
    root, _ = tab(cons(autonomy=show_json(envs=envs)))
    prod = env_section(root, "prod")
    assert prod.attrs["data-supervised"] == "false" and env_section(root, "dev").attrs["data-supervised"] == "true"
    assert q(prod, "span", data_engine_state="unreachable")
    [part] = q(prod, "section", data_source="engine:prod")
    assert "not supervised" in part.text().lower()
    assert "unavailable" in part.attrs.get("class", "")
    assert q(prod, "time", data_heartbeat="2026-10-26T08:00:00Z")


def test_an_environment_without_an_engine_is_not_supervised_ac_124_13(cons):  # AC-124.13
    """AC-124.13: an environment without an engine is not supervised."""
    envs = [env_show("dev", "act", cap="improve", engine={"url": None, "state": "none", "name": None, "version": None, "heartbeat_at": None}, supervised=False)]
    root, _ = tab(cons(autonomy=show_json(envs=envs)))
    dev = env_section(root, "dev")
    assert dev.attrs["data-supervised"] == "false" and q(dev, "span", data_engine_state="none")


def test_a_signal_that_is_not_confirmed_is_marked_until_the_engine_confirms_ac_124_21(cons):  # AC-124.21
    """AC-124.21: a signal that is not confirmed is marked until the engine confirms."""
    pending = [{"signal": "sig-0123456789ab", "kind": "pause", "at": "2026-10-26T09:20:00Z", "pr": None}]
    envs = [env_show("dev", "act", cap="improve"), env_show("prod", "act", confirmed=False, pending=pending)]
    root, _ = tab(cons(autonomy=show_json(envs=envs)))
    prod = env_section(root, "prod")
    assert prod.attrs["data-confirmed"] == "false"
    assert "not confirmed" in q(prod, "span", data_unconfirmed=True)[0].text()
    dev = env_section(root, "dev")
    assert dev.attrs["data-confirmed"] == "true" and not q(dev, "span", data_unconfirmed=True)


def test_a_failing_autonomy_source_is_the_standard_unavailable_part_ac_124_13(cons):  # AC-124.13
    """AC-124.13: a failing autonomy source is the standard unavailable part."""
    c = cons()
    c.fail("autonomy")
    root, text = tab(c)
    [part] = q(root, "section", data_source="autonomy")
    assert "is not available" in part.text() and q(part, "button", data_action="retry-source")
    assert not q(root, "button", data_action="pause"), "nothing is offered that cannot be done"


# ---------------- AC-124.22: component caps ----------------

def test_a_capped_component_shows_its_cap_next_to_the_level_ac_124_22(cons):  # AC-124.22
    """AC-124.22: a capped component shows its cap next to the level."""
    envs = [env_show("dev", "act", cap="improve"),
            env_show("prod", "act", caps=[{"component": "shop-api", "max": "propose", "effective": "propose"}])]
    root, _ = tab(cons(autonomy=show_json(envs=envs)))
    [cap] = q(env_section(root, "prod"), "span", data_cap="shop-api")
    assert "max propose" in cap.text()
    assert not q(env_section(root, "dev"), "span", data_cap=True)


# ---------------- AC-124.16 / AC-124.15: done on its own ----------------

def test_the_actions_of_the_last_24_hours_are_a_table_with_undo_ac_124_16(cons):  # AC-124.16
    """AC-124.16: the actions of the last 24 hours are a table with undo."""
    actions = [done_action(EID, "merge"), done_action("20261026T081000Z-ai-ops-aaaaaaaa", "dismissal", allowed=False,
                                                      reason="the undo window of 24h has passed")]
    root, _ = tab(cons(autonomy=show_json(actions=actions)))
    [box] = [d for d in q(root, "div") if "scroll-x" in d.attrs.get("class", "") and q(d, "tr", data_event=True)]
    rows = q(box, "tr", data_event=True)
    assert [r.attrs["data-event"] for r in rows] == [EID, "20261026T081000Z-ai-ops-aaaaaaaa"]
    assert [r.attrs["data-event-kind"] for r in rows] == ["merge", "dismissal"]
    first = rows[0]
    assert "ai-ops" in first.text() and "act" in first.text() and SHA[:7] in first.text()
    [undo] = q(first, "button", data_action="undo")
    assert json.loads(undo.attrs["data-object"]) == {"repo": GITOPS, "event": EID} and not disabled(undo)
    [off] = q(rows[1], "button", data_action="undo")
    assert disabled(off)
    assert "the undo window of 24h has passed" in q(rows[1], "span", data_disabled_reason=True)[0].text()


def test_a_rollback_row_shows_the_pinned_and_the_previous_version_ac_124_15(cons):  # AC-124.15
    """AC-124.15: a rollback row shows the pinned and the previous version."""
    prev, new = "sha-" + "a" * 40, "sha-" + "b" * 40
    row = done_action("20261026T090000Z-ai-ops-bbbbbbbb", "rollback", obj={"type": "instance", "version": prev, "previous": new, "number": None, "url": None},
                      detail={"smoke": {"outcome": "failed"}})
    root, _ = tab(cons(autonomy=show_json(actions=[row])))
    r = q(root, "tr", data_event="20261026T090000Z-ai-ops-bbbbbbbb")[0]
    assert prev[:11] in r.text() and new[:11] in r.text()


# ---------------- AC-124.19 / AC-124.6: the preview of a change ----------------

def preview(repo, **fields):
    from console import preview as pv
    return pv.preview(repo, "autonomy", fields)


def test_the_autonomy_form_previews_the_exact_command_and_sends_no_signal_ac_124_6(world, engines):  # AC-124.6
    """AC-124.6: the autonomy form previews the exact command and sends no signal."""
    from system_fixtures import files
    before = files(world.repo)
    res = preview(world.repo, env="dev", level="propose", maxLines="100")
    assert res["command"].startswith("/system:autonomy set dev propose") and "--max-lines 100" in res["command"]
    assert "--pr" not in res["command"]
    assert res["valid"] is True and all({"key", "rule", "ok"} <= set(c) for c in res["checks"]) and not [c for c in res["checks"] if not c["ok"]]
    assert re.search(r"^[-+]\s+level: (act|propose)", res["diff"], re.M)
    assert files(world.repo) == before and engines.posts == [], "the preview runs on a scratch copy and sends no signal"


def test_the_preview_turns_every_field_into_its_flag_ac_124_6(world):  # AC-124.6
    """AC-124.6: the preview turns every field into its flag."""
    res = preview(world.repo, env="staging", level="act", routes="none", maxCriticality="medium", maxFiles="3", maxLines="80",
                  regressionTest="false", secondReview="false", runsPerDay="4", mergesPerDay="1", days="mon,tue", **{"from": "08:00"},
                  to="18:00", timezone="Europe/Berlin", undoWindow="48h", engine="https://e.example.com", **{"perRun.cost": "5"})
    cmd = res["command"]
    for flag in ("--routes none", "--max-criticality medium", "--max-files 3", "--max-lines 80", "--regression-test false", "--second-review false",
                 "--runs-per-day 4", "--merges-per-day 1", "--days mon,tue", "--from 08:00", "--to 18:00", "--timezone Europe/Berlin",
                 "--undo-window 48h", "--engine https://e.example.com", "--per-run cost=5"):
        assert flag in cmd, flag
    assert res["valid"] is True


def test_the_consequence_says_what_the_level_allows_and_when_it_takes_effect_ac_124_6(world):  # AC-124.6
    """AC-124.6: the consequence says what the level allows and when it takes effect."""
    import autonomy
    up = preview(world.repo, env="staging", level="act")
    assert up["consequence"] == [autonomy.allows("act"), "Takes effect after the merge."]
    assert up["way_back"] == ["/system:autonomy set staging propose"]
    down = preview(world.repo, env="dev", level="propose")
    assert down["consequence"][0] == autonomy.allows("propose") and down["consequence"][1].startswith("Takes effect at once by a signal: ")
    assert down["way_back"] == ["/system:autonomy set dev act"]


def test_an_invalid_level_in_prod_is_not_valid_and_names_the_rule_ac_124_19(world):  # AC-124.19
    """AC-124.19: an invalid level in prod is not valid and names the rule."""
    res = preview(world.repo, env="prod", level="improve")
    assert res["valid"] is False
    [bad] = [c for c in res["checks"] if not c["ok"]]
    assert "environments.prod.autonomy.level" in bad["key"] and "act" in bad["rule"]


def test_the_autonomy_form_is_served_by_the_preview_route_ac_124_19(cons):  # AC-124.19
    """AC-124.19: the autonomy form is served by the preview route."""
    c = cons()
    st, body = c.json("POST", "/api/preview", {"form": "autonomy", "fields": {"env": "prod", "level": "improve"}})
    assert st == 200 and body["valid"] is False and body["command"].startswith("/system:autonomy set prod improve")
    st, body = c.json("POST", "/api/preview", {"form": "autonomy", "fields": {"env": "dev", "level": "act"}}, token=False)
    assert st == 403


# ---------------- the source ----------------

def test_the_autonomy_source_reads_the_show_command_from_a_snapshot_ac_124_19(tmp_path):  # AC-124.19
    """AC-124.19: the autonomy source reads the show command from a snapshot."""
    from console import sources
    snap = tmp_path / "snap"
    srcs = sources.default_sources(tmp_path / "repo", lambda repo: snap)
    argv = list(srcs["autonomy"].argv() if callable(srcs["autonomy"].argv) else srcs["autonomy"].argv)
    assert all(w in argv for w in ("system", "autonomy", "show", "--json", "--repo-dir", str(snap)))
    assert srcs["autonomy"].timeout == 60


# ---------------- actions (AC-124.7, AC-124.16, AC-124.17) ----------------

def cf(kind, obj, **args):
    from console import actions
    return actions.command_for(kind, obj, {"level": "system", **args})


@pytest.mark.parametrize("kind, obj, args, command", [
    ("pause", {"repo": GITOPS}, {}, "/system:autonomy pause"),
    ("resume", {"repo": GITOPS}, {}, "/system:autonomy resume"),
    ("undo", {"repo": GITOPS, "event": EID}, {}, f"/system:autonomy undo {EID}"),
    ("review-approve", {"repo": GITOPS, "pr_repo": "acme/shop-api", "pr": 88}, {}, "/system:autonomy approve acme/shop-api#88"),
    ("model", {"repo": GITOPS}, {"command": "/system:autonomy set dev propose --max-lines 100"}, "/system:autonomy set dev propose --max-lines 100"),
])
def test_each_autonomy_action_runs_its_exact_command_through_headless_ac_124_7(ready, kind, obj, args, command):  # AC-124.7
    """AC-124.7: each autonomy action runs its exact command through headless."""
    argv, display, repo = cf(kind, obj, **args)
    assert command in display and any(command in a for a in argv), (display, argv)
    assert "headless" in argv and "--repo" in argv and repo == GITOPS
    assert str(ready.ws / "shop-gitops") in argv
    assert argv[argv.index("--max-runs") + 1] == "1"


@pytest.mark.parametrize("kind, obj, field", [
    ("undo", {"repo": GITOPS, "event": "../../etc/passwd"}, r"\bevent\b"),
    ("undo", {"repo": GITOPS, "event": "2026-10-26 merge"}, r"\bevent\b"),
    ("undo", {"repo": GITOPS}, r"\bevent\b"),
    ("review-approve", {"repo": GITOPS, "pr_repo": "not a repo", "pr": 88}, r"\bpr_repo\b"),
    ("review-approve", {"repo": GITOPS, "pr_repo": "acme/shop-api", "pr": "88; rm -rf /"}, r"\bpr\b"),
    ("review-approve", {"repo": GITOPS, "pr_repo": "acme/shop-api"}, r"\bpr\b"),
])
def test_a_bad_event_id_or_pull_request_is_a_400_naming_the_field_ac_124_16(cons, ready, kind, obj, field):  # AC-124.16
    """AC-124.16: a bad event id or pull request is a 400 naming the field."""
    st, body = cons().json("POST", "/api/actions", {"kind": kind, "object": obj, "args": {"level": "system"}})
    assert st == 400 and re.search(field, body["error"] + " " + str(body.get("detail"))), body


def test_the_model_action_takes_a_set_command_and_refuses_other_slash_commands_ac_124_6(cons, ready):  # AC-124.6
    """AC-124.6: the model action takes a set command and refuses other slash commands."""
    st, body = cons().json("POST", "/api/actions", {"kind": "model", "object": {"repo": GITOPS}, "args": {"command": "/system:autonomy pause; rm -rf ~"}})
    assert st == 400 and "/system:autonomy set" in json.dumps(body), "the allowed commands now include the set command"


def test_two_reviews_and_two_undos_do_not_lock_each_other_ac_124_17(cons, ready, monkeypatch):  # AC-124.17
    """AC-124.17: two reviews and two undos do not lock each other."""
    from test_console_actions import finish, stub_command
    stub_command(monkeypatch, ready)
    c = cons()
    first = {"kind": "review-approve", "object": {"repo": GITOPS, "pr_repo": "acme/shop-api", "pr": 88}, "args": {"level": "system"}}
    other = {"kind": "review-approve", "object": {"repo": GITOPS, "pr_repo": "acme/shop-api", "pr": 89}, "args": {"level": "system"}}
    assert c.json("POST", "/api/actions", first)[0] == 202
    assert c.json("POST", "/api/actions", first)[0] == 409, "the same review twice"
    assert c.json("POST", "/api/actions", other)[0] == 202
    u1 = {"kind": "undo", "object": {"repo": GITOPS, "event": EID}, "args": {"level": "system"}}
    u2 = {"kind": "undo", "object": {"repo": GITOPS, "event": "20261026T081000Z-ai-ops-aaaaaaaa"}, "args": {"level": "system"}}
    assert c.json("POST", "/api/actions", u1)[0] == 202
    assert c.json("POST", "/api/actions", u2)[0] == 202
    finish(ready)


# ---------------- AC-124.17: the review decision in the Inbox ----------------

def with_review(cons):
    c = cons()
    doc = needs_json()
    doc["items"] = doc["items"] + [review_need(), signal_triage_need()]
    c.set("needs", doc)
    return c


def test_the_inbox_lists_a_review_decision_in_land_with_the_engine_badge_ac_124_17(cons):  # AC-124.17
    """AC-124.17: the inbox lists a review decision in land with the engine badge."""
    c = with_review(cons)
    root, _ = c.page("/inbox")
    [row] = q(root, None, data_need="review:acme/shop-api#88")
    assert "review" in row.text() and "outside riskGate.maxLines" in row.text()
    assert q(row, None, data_stage="Land") and q(row, "span", data_engine="ai-ops")
    others = [r for r in q(root, None, data_need=True) if r is not row and r.attrs["data-need"] != "triage:acme/shop-api:57"]
    assert others and not any(q(r, "span", data_engine=True) for r in others), "only engine items carry the badge"


def test_the_review_detail_shows_why_regression_ci_second_review_summary_and_way_back_ac_124_17(cons):  # AC-124.17
    """AC-124.17: the review detail shows why regression ci second review summary and way back."""
    root, text = with_review(cons).panel("need", "review:acme/shop-api#88")
    [why] = q(root, "ul", data_why=True)
    [li] = q(why, "li", data_guardrail="riskGate.maxLines")
    assert "412 lines, at most 200" in li.text()
    [reg] = q(root, "dl", data_regression=True)
    assert "tests/test_cart.py::test_total_rounding" in reg.text() and "failed" in reg.text() and "passed" in reg.text()
    assert q(root, "section", data_second_review=True)
    assert "passed" in text and "Round the cart total once, at the end." in text
    assert "Undo or a revert pull request takes the change back" in text
    assert "/system:autonomy approve acme/shop-api#88" in text


def test_a_second_review_with_findings_lists_them_ac_124_17(cons):  # AC-124.17
    """AC-124.17: a second review with findings lists them."""
    item = review_need(why=[{"guardrail": "riskGate.secondReview", "text": "the second review found something"}])
    item["consequence"]["second_review"] = {"result": "findings", "findings": ["unchecked input in cart.py"]}
    item["consequence"]["ci"] = "failed"
    c = cons()
    doc = needs_json()
    doc["items"].append(item)
    c.set("needs", doc)
    root, text = c.panel("need", item["id"])
    [sec] = q(root, "section", data_second_review=True)
    assert "unchecked input in cart.py" in sec.text() and "findings" in sec.text()
    assert "failed" in text


def test_approving_a_review_approves_the_pull_request_through_its_own_action_ac_124_17(cons):  # AC-124.17
    """AC-124.17: approving a review approves the pull request through its own action."""
    root, _ = with_review(cons).panel("need", "review:acme/shop-api#88")
    [btn] = q(root, "button", data_action="review-approve")
    assert btn.attrs.get("aria-keyshortcuts") == "a" and "Approve" in btn.text()
    assert [k.text() for k in q(btn, "kbd")] == ["a"]
    assert json.loads(btn.attrs["data-object"]) == {"repo": GITOPS, "pr_repo": "acme/shop-api", "pr": 88}
    assert not disabled(btn)


def test_at_level_propose_the_decision_says_a_person_merges_every_fix_ac_124_17(cons):  # AC-124.17
    """AC-124.17: at level propose the decision says a person merges every fix."""
    item = review_need(why=[{"guardrail": "level", "text": "level propose: a person merges every fix"}], level="propose")
    c = cons()
    doc = needs_json()
    doc["items"].append(item)
    c.set("needs", doc)
    root, _ = c.panel("need", item["id"])
    assert "level propose: a person merges every fix" in q(root, "li", data_guardrail="level")[0].text()


# ---------------- AC-124.14: the why list names each guardrail ----------------

def test_every_guardrail_a_fix_is_outside_has_its_own_entry_ac_124_14(cons):  # AC-124.14
    """AC-124.14: every guardrail a fix is outside has its own entry."""
    why = [{"guardrail": "autoMerge.routes", "text": "route spec, allowed: fix"}, {"guardrail": "riskGate.maxFiles", "text": "9 files, at most 5"},
           {"guardrail": "window", "text": "Saturday 10:00, window mon-fri 09:00-17:00"}]
    item = review_need(why=why)
    c = cons()
    doc = needs_json()
    doc["items"].append(item)
    c.set("needs", doc)
    root, _ = c.panel("need", item["id"])
    assert [li.attrs["data-guardrail"] for li in q(q(root, "ul", data_why=True)[0], "li")] == ["autoMerge.routes", "riskGate.maxFiles", "window"]


# ---------------- AC-124.18: signal facts, badges, stages ----------------

def test_a_signal_issue_shows_its_facts_triage_and_policy_decision_ac_124_18(cons):  # AC-124.18
    """AC-124.18: a signal issue shows its facts triage and policy decision."""
    root, text = with_review(cons).panel("need", "triage:acme/shop-api:57")
    [sig] = q(root, "dl", data_signal=True)
    for needle in ("error-rate", "high", "3", "shop-api", "prod"):
        assert needle in sig.text(), needle
    assert q(sig, "a", href="https://grafana.example.com/d/abc") or q(root, "a", href="https://grafana.example.com/d/abc")
    [tri] = q(root, "dl", data_triage=True)
    assert "fix" in tri.text() and "0.82" in tri.text() and "src/shop_api/cart.py" in tri.text() and "src/shop_api/totals.py" in tri.text()
    assert "review: outside riskGate.maxLines" in q(root, "p", data_policy_decision=True)[0].text()
    assert q(root, "span", data_engine="ai-ops")


def test_before_triage_the_triage_block_and_policy_decision_say_none_ac_124_18(cons):  # AC-124.18
    """AC-124.18: before triage the triage block and policy decision say none."""
    item = signal_triage_need()
    item["object"]["detail"]["signal"].update(triage=None, policy=None)
    c = cons()
    doc = needs_json()
    doc["items"].append(item)
    c.set("needs", doc)
    root, _ = c.panel("need", item["id"])
    assert "(none)" in q(root, "dl", data_triage=True)[0].text() and "(none)" in q(root, "p", data_policy_decision=True)[0].text()


def issue_row():
    return {"repo": "acme/shop-api", "number": 58, "title": "Signal: cart totals drift", "labels": ["triage", "signal", "engine:ai-ops"], "state": "open",
            "created_at": "2026-10-26T07:00:00Z", "closed_at": None, "url": "https://github.com/acme/shop-api/issues/58", "engine": "ai-ops", "signal": FACTS}


def board_data(cons):
    c = cons()
    doc = needs_json()
    doc["issues"] = [issue_row()]
    c.set("needs", doc)
    runs = runs_json()
    runs["runs"].append(engine_run_row())
    c.set("runs", runs)
    return c


def test_the_issue_panel_shows_the_signal_facts_ac_124_18(cons):  # AC-124.18
    """AC-124.18: the issue panel shows the signal facts."""
    root, _ = board_data(cons).panel("issue", "58")
    [sig] = q(root, "dl", data_signal=True)
    assert "error-rate" in sig.text() and "prod" in sig.text()


def test_an_engine_issue_sits_in_the_issue_column_with_a_badge_ac_124_18(cons):  # AC-124.18
    """AC-124.18: an engine issue sits in the issue column with a badge."""
    root, _ = board_data(cons).page("/board")
    card = next(c for c in q(root, None, data_card=True) if "cart totals drift" in c.text())
    assert q(card, "span", data_engine="ai-ops")
    col = next(n for n in q(root, None, data_column=True) if card in list(n.walk()))
    assert col.attrs["data-column"] == "Issue"


def test_an_engine_run_sits_in_a_stage_column_with_a_badge_and_other_cards_do_not_ac_124_18(cons):  # AC-124.18
    """AC-124.18: an engine run sits in a stage column with a badge and other cards do not."""
    root, _ = board_data(cons).page("/board")
    badged = [c for c in q(root, None, data_card=True) if q(c, "span", data_engine="ai-ops")]
    run_cards = [c for c in badged if "cart totals drift" not in c.text()]
    assert run_cards, "the engine's run has a card"
    col = next(n for n in q(root, None, data_column=True) if run_cards[0] in list(n.walk()))
    assert col.attrs["data-column"] == "Land"
    plain = [c for c in q(root, None, data_card=True) if c not in badged]
    assert plain and not any(q(c, "span", data_engine=True) for c in plain)


def test_the_list_view_badges_engine_rows_ac_124_18(cons):  # AC-124.18
    """AC-124.18: the list view badges engine rows."""
    root, _ = board_data(cons).page("/board?view=list")
    rows = [r for r in q(root, "tr") if q(r, "span", data_engine="ai-ops")]
    assert any("cart totals drift" in r.text() for r in rows) and len(rows) >= 2


def test_the_run_panel_of_an_engine_run_shows_actor_issue_policy_and_regression_ac_124_11(cons):  # AC-124.11
    """AC-124.11: the run panel of an engine run shows actor issue policy and regression."""
    root, text = board_data(cons).panel("run", engine_run_row()["run_id"])
    assert "by ai-ops" in text
    assert q(root, "a", href="https://github.com/acme/shop-api/issues/57")
    assert "act" in text and SHA[:7] in text
    assert "tests/test_cart.py::test_total_rounding" in text and "failed" in text and "passed" in text
    assert "riskGate.maxLines" in text, "the decision with its outside list"


def test_a_platform_run_panel_has_no_engine_actor_ac_124_11(cons):  # AC-124.11
    """AC-124.11: a platform run panel has no engine actor."""
    root, text = board_data(cons).panel("run", runs_json()["runs"][1]["run_id"])
    assert "by ai-ops" not in text and not q(root, "span", data_engine=True)
