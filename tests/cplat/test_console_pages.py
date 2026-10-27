"""Spec 122 acceptance tests: the three places, their side panels and the shared page shell
(AC-122.6, .9 .. .15, .7, .8, .16, .17, .31, .32, .33, .34, .35, .37, .38, .39, .40, .47, .48, .49, .12).

Contract: design.md "Console HTTP" and "Markup contract". The pages are rendered from the fixture JSON of console_support."""
import datetime as dt
import re
import urllib.parse

import pytest

from console_support import (STAGES, doctor_json, disabled, need, needs_json, parse, q, row_of, run_row, runs_json, spec_row, specs_json,
                             status_json)

KINDS_OLDEST_FIRST = ["triage", "escalation", "answer", "approve", "promote"]


def need_id(kind):
    return next(i["id"] for i in needs_json()["items"] if i["kind"] == kind)


def quote(s):
    return urllib.parse.quote(s, safe="")


def stage_attrs(root):
    return q(root, None, data_stage=True)


def column(root, stage):
    [col] = [c for c in q(root, None, data_column=True) if c.attrs["data-column"] == stage]
    return col


def columns_holding(root, needle):
    return [c.attrs["data-column"] for c in q(root, None, data_column=True) if needle in c.text()]


def action(panel_root, kind):
    found = q(panel_root, "button", data_action=kind)
    assert len(found) == 1, (kind, [b.attrs.get("data-action") for b in q(panel_root, "button", data_action=True)])
    return found[0]


# ---------------- AC-122.31: three places, one palette, one menu ----------------

@pytest.mark.parametrize("path, place", [("/inbox", "inbox"), ("/board", "board"), ("/board?view=list", "board"), ("/system", "system")])
def test_the_sidebar_offers_exactly_three_places_ac_122_31(console, path, place):  # AC-122.31
    root, _ = console().page(path)
    [nav] = q(root, "nav", aria_label="Places")
    links = q(nav, "a", data_place=True)
    assert [a.attrs["data-place"] for a in links] == ["inbox", "board", "system"]
    assert len(q(nav, "a")) == 3
    current = [a for a in links if a.attrs.get("aria-current")]
    assert [a.attrs["data-place"] for a in current] == [place]


def test_the_palette_button_and_the_user_menu_are_on_every_page_ac_122_31(console):  # AC-122.31
    c = console()
    for path in ("/inbox", "/board", "/system"):
        root, _ = c.page(path)
        [btn] = q(root, "button", data_action="palette")
        assert btn.attrs["aria-keyshortcuts"] == "Meta+K Control+K"
        [menu] = q(root, "details", data_menu="user")
        text = menu.text()
        for item in ("Settings", "Notifications", "Switch system", "Stop console"):
            assert item in text, item
        assert q(root, "button", data_activity=True)


def test_a_side_panel_is_an_aside_next_to_the_place_ac_122_31(console):  # AC-122.31
    c = console()
    root, _ = c.panel("need", need_id("approve"))
    [panel] = q(root, "aside", data_panel=True)
    assert panel.attrs["role"] == "dialog" and panel.attrs["aria-modal"] == "false" and panel.attrs["aria-label"]


def test_the_palette_offers_go_to_describe_add_and_ask_ac_122_31(console):  # AC-122.31
    c = console()
    st, text = c.get("/palette?q=wish")
    assert st == 200
    root = parse(text)
    assert "014-wishlist" in text
    assert "Describe a change" in text and "Ask" in text
    assert {f.attrs["data-form"] for f in q(root, None, data_form=True)} >= {"component", "api", "resource", "environment", "system"}


def test_the_palette_goes_to_components_runs_and_issues_ac_122_31(console):  # AC-122.31
    c = console()
    _, comps = c.get("/palette?q=shop-web")
    assert "shop-web" in comps
    _, issues = c.get("/palette?q=5xx")
    assert "57" in issues


# ---------------- AC-122.32: one vocabulary ----------------

@pytest.mark.parametrize("path", ["/inbox", "/board", "/board?view=list", "/system"])
def test_stage_names_appear_only_as_data_stage_with_the_same_text_ac_122_32(console, path):  # AC-122.32
    root, _ = console().page(path)
    for n in stage_attrs(root):
        assert n.attrs["data-stage"] in STAGES and n.text() == n.attrs["data-stage"], n.attrs


def test_statuses_and_phases_are_not_names_of_their_own_on_the_board_ac_122_32(console):  # AC-122.32
    root, _ = console().page("/board")
    for card in q(root, None, data_card=True):
        words = set(re.findall(r"[a-z]+", card.text().lower()))
        assert not words & {"draft", "approved", "building", "escalated", "superseded"}, card.text()


# ---------------- Inbox: AC-122.6 ----------------

def test_the_inbox_lists_decisions_oldest_first_with_kind_stage_age_and_reason_ac_122_6(console):  # AC-122.6
    root, _ = console().page("/inbox")
    rows = q(root, None, data_need=True)
    assert [r.attrs["data-need"] for r in rows] == [need_id(k) for k in KINDS_OLDEST_FIRST]
    by_id = {i["id"]: i for i in needs_json()["items"]}
    for r in rows:
        item = by_id[r.attrs["data-need"]]
        assert item["kind"] in r.text() and item["reason"] in r.text()
        [st] = q(r, None, data_stage=True)
        assert st.attrs["data-stage"] == item["stage"]
        assert q(r, "time")


def test_selecting_a_decision_opens_its_detail_in_a_panel_ac_122_6(console):  # AC-122.6
    c = console()
    for kind in KINDS_OLDEST_FIRST:
        root, text = c.panel("need", need_id(kind))
        assert q(root, "aside", data_panel=True), kind


def test_an_unknown_decision_is_404_ac_122_6(console):  # AC-122.6
    assert console().json("GET", "/panel/need/nope%3Anope")[0] == 404


# ---------------- Approving: AC-122.16, AC-122.17, AC-122.34, AC-122.35 ----------------

def test_an_answer_item_shows_each_question_with_options_and_a_free_text_answer_ac_122_16(console):  # AC-122.16
    root, text = console().panel("need", need_id("answer"))
    assert "Should a user be limited?" in text and "Which currency?" in text
    for option in ("50 per user", "no limit", "EUR", "USD"):
        assert option in text, option
    assert len(q(root, "input", type="radio")) >= 4
    assert q(root, "textarea") or q(root, "input", type="text")
    assert q(root, "button", data_action="answer")


def test_approve_and_ship_is_disabled_while_a_question_is_open_and_says_why_ac_122_17(console):  # AC-122.17
    root, _ = console().panel("need", need_id("answer"))
    btn = action(root, "approve-ship")
    assert disabled(btn)
    reasons = q(root, "span", data_disabled_reason=True)
    assert reasons and "question" in " ".join(r.text() for r in reasons).lower()


def test_approve_and_ship_is_disabled_while_the_spec_check_fails_ac_122_17(console):  # AC-122.17
    c = console()
    doc = needs_json()
    doc["items"].append(need("approve", spec="016-bad", reason="draft without open questions", since="2026-10-26T01:00:00Z"))
    c.set("needs", doc)
    root, _ = c.panel("need", "approve:acme/shop-api:016-bad")
    btn = action(root, "approve-ship")
    assert disabled(btn)
    assert "AC-016.1 has no test" in " ".join(r.text() for r in q(root, "span", data_disabled_reason=True))


def test_a_clean_draft_can_be_approved_and_shipped_with_a_budget_ac_122_17(console):  # AC-122.17
    root, _ = console().panel("need", need_id("approve"))
    assert not disabled(action(root, "approve-ship"))
    assert q(root, "input", name="budget") or q(root, "input", data_budget=True)
    approve_only, changes = action(root, "approve"), action(root, "request-changes")
    assert not disabled(approve_only) and not disabled(changes)
    assert q(root, "textarea")


def test_approving_shows_repos_unattended_stages_and_the_estimate_ac_122_34(console):  # AC-122.34
    root, text = console().panel("need", need_id("approve"))
    assert "acme/shop-api" in text
    for stage in ("Plan", "Build", "Land", "Dev", "Staging"):
        assert stage in [n.attrs["data-stage"] for n in stage_attrs(root)], stage
    assert "4.2" in text and "55" in text


def test_without_history_the_estimate_says_no_estimate_yet_ac_122_34(console):  # AC-122.34
    c = console()
    doc = needs_json()
    for i in doc["items"]:
        if i["kind"] == "approve":
            i["consequence"]["estimate"] = None
    c.set("needs", doc)
    assert "no estimate yet" in c.panel("need", need_id("approve"))[1].lower()


def test_approving_names_the_way_back_ac_122_35(console):  # AC-122.35
    _, text = console().panel("need", need_id("approve"))
    assert "paused at any stage" in text and "nothing reaches prod without you" in text


# ---------------- promote: AC-122.34, AC-122.35 ----------------

def test_promoting_shows_what_lies_between_the_versions_ac_122_34(console):  # AC-122.34
    root, text = console().panel("need", need_id("promote"))
    for needle in ("1.3.0", "1.4.0", "23", "7", "012-checkout", "migrations/versions/0005.py"):
        assert needle in text, needle
    assert "not additive" in text.lower()
    assert "staging verified" in text.lower() or "verified in staging" in text.lower()


def test_a_digest_that_staging_did_not_verify_is_said_so_ac_122_34(console):  # AC-122.34
    c = console()
    doc = needs_json()
    for i in doc["items"]:
        if i["kind"] == "promote":
            i["consequence"]["digest_matches"] = False
            i["consequence"]["digest"] = "sha256:bbbb"
    c.set("needs", doc)
    assert "sha256:bbbb" in c.panel("need", need_id("promote"))[1]


def test_promotion_way_back_is_the_command_for_the_previous_version_with_a_warning_ac_122_35(console):  # AC-122.35
    root, text = console().panel("need", need_id("promote"))
    cmds = [n.text() for n in q(root, "code", data_command=True)]
    assert "/instance:promote shop-api --to prod --version 1.4.0" in cmds
    assert "/instance:promote shop-api --to prod --version 1.3.0" in cmds
    assert "0005.py is not additive" in text


def test_the_promote_button_has_its_key_and_shows_it_ac_122_38(console):  # AC-122.38
    root, _ = console().panel("need", need_id("promote"))
    btn = action(root, "promote")
    assert btn.attrs["aria-keyshortcuts"] == "p" and q(btn, "kbd") and q(btn, "kbd")[0].text().lower() == "p"


def test_the_approve_button_has_its_key_ac_122_38(console):  # AC-122.38
    root, _ = console().panel("need", need_id("approve"))
    keyed = [b for b in q(root, "button", aria_keyshortcuts="a")]
    assert len(keyed) == 1 and q(keyed[0], "kbd")[0].text().lower() == "a"


# ---------------- failures: AC-122.33, AC-122.36 ----------------

def test_an_escalation_explains_why_it_stopped_where_it_appears_ac_122_33(console):  # AC-122.33
    root, text = console().panel("need", need_id("escalation"))
    for needle in ("CI stayed red after three fix rounds.", "tests/test_cart.py::test_total", "AC-011.3", "AssertionError: 41 != 42",
                   "rounding in total()"):
        assert needle in text, needle


def test_an_escalation_offers_the_ways_forward_each_with_its_command_ac_122_33(console):  # AC-122.33
    root, _ = console().panel("need", need_id("escalation"))
    for kind in ("take-over", "more-budget", "amend", "open-in-claude"):
        assert q(root, "button", data_action=kind), kind
    assert len(q(root, "code", data_command=True)) >= 3


def test_the_run_panel_explains_the_failure_too_ac_122_33(console):  # AC-122.33
    root, text = console().panel("run", runs_json()["runs"][1]["run_id"])
    assert "rounding in total()" in text and "AC-011.3" in text and q(root, "button", data_action="take-over")


def test_a_failed_smoke_is_explained_with_its_result_ac_122_33(console):  # AC-122.33
    c = console()
    doc = runs_json()
    doc["runs"].append(run_row(spec="020-smoke", run_id="20261026T071500Z-bbbb2222", phase="staging", stage="Staging",
                               smoke={"dev": {"result": "passed", "instance": "shop-api/dev"},
                                      "staging": {"result": "failed", "instance": "shop-api/staging"}}))
    c.set("runs", doc)
    _, text = c.panel("run", "20261026T071500Z-bbbb2222")
    assert "shop-api/staging" in text and "failed" in text.lower() and "smoke" in text.lower()


def test_a_triage_issue_offers_fix_make_a_spec_and_dismiss_with_a_reason_ac_122_33(console):  # AC-122.33
    root, text = console().panel("need", need_id("triage"))
    for kind in ("fix", "make-spec", "dismiss"):
        assert q(root, "button", data_action=kind), kind
    cmds = [n.text() for n in q(root, "code", data_command=True)]
    assert any(c.startswith("/component:fix #57") for c in cmds)
    assert any("/issue:triage 57" in c for c in cmds)
    assert q(root, "textarea") or q(root, "input", type="text")


def test_the_issue_panel_opens_for_the_triage_issue_ac_122_33(console):  # AC-122.33
    st, _ = console().get("/panel/issue/57")
    assert st == 200


def test_stopping_a_run_names_what_stays_ac_122_35(console):  # AC-122.35
    _, text = console().panel("need", need_id("escalation"))
    assert "nothing was deployed" in text and "feature/011-cart" in text or "pull request #41" in text


def test_every_action_shows_its_command_with_a_copy_button_ac_122_37(console):  # AC-122.37
    c = console()
    for kind in KINDS_OLDEST_FIRST:
        root, _ = c.panel("need", need_id(kind))
        kinds = {b.attrs["data-action"] for b in q(root, "button", data_action=True)} - {"retry-source", "palette"}
        cmds = q(root, "code", data_command=True)
        copies = q(root, "button", data_copy=True)
        assert len(cmds) >= len(kinds) - 1 and cmds, (kind, kinds)
        assert len(copies) >= len(cmds) and all(b.attrs.get("aria-label") == "Copy command" for b in copies)


# ---------------- Board: AC-122.10, .9, .11, .12 ----------------

def test_the_board_has_one_column_per_stage_in_order_with_three_decision_columns_ac_122_10(console):  # AC-122.10
    root, _ = console().page("/board")
    cols = q(root, None, data_column=True)
    assert [c.attrs["data-column"] for c in cols] == list(STAGES)
    assert {c.attrs["data-column"] for c in cols if "data-decision" in c.attrs} == {"Spec", "Build", "Prod"}


def test_each_open_item_is_in_exactly_one_column_by_the_rule_ac_122_10(console):  # AC-122.10
    root, _ = console().page("/board")
    assert columns_holding(root, "Checkout") == ["Spec"]
    assert columns_holding(root, "Search") == ["Spec"]
    assert columns_holding(root, "Broken") == ["Spec"]
    assert columns_holding(root, "Wishlist") == ["Land"]
    assert columns_holding(root, "Export") == ["Plan"]
    assert columns_holding(root, "011-cart") == ["Build"]
    assert columns_holding(root, "#57") == ["Issue"]
    assert columns_holding(root, "1.4.0") == ["Prod"]


def test_a_finished_spec_has_no_column_ac_122_10(console):  # AC-122.10
    c = console()
    rows = specs_json() + [spec_row("009-old", "done", title="Oldspec")]
    c.set("specs:acme/shop-api", rows)
    root, _ = c.page("/board")
    assert columns_holding(root, "Oldspec") == []


def test_a_run_card_shows_repo_stage_budget_and_why_it_stopped_ac_122_9(console):  # AC-122.9
    root, _ = console().page("/board")
    cards = q(root, None, data_card=True)
    land = next(c for c in cards if "014" in c.text() or "Wishlist" in c.text())
    assert "acme/shop-api" in land.text() and q(land, None, data_stage="Land")
    assert ("3.1" in land.text() and "15" in land.text()) or ("42" in land.text() and "180" in land.text())
    stopped = next(c for c in cards if "011-cart" in c.text())
    assert q(stopped, None, data_stage="Build") and "CI stayed red after three fix rounds." in stopped.text()
    assert "stopped" in stopped.text().lower()


def test_the_list_view_is_a_table_with_stage_and_current_state_ac_122_11(console):  # AC-122.11
    root, _ = console().page("/board?view=list")
    [table] = q(root, "table")
    heads = [th.text().lower() for th in q(table, "th")]
    assert "stage" in heads and any("state" in h or "status" in h for h in heads)
    body = [tr for tr in q(table, "tr") if q(tr, "td")]
    assert len(body) >= 8
    for tr in body:
        assert q(tr, None, data_stage=True)


def test_a_column_header_explains_its_stage_ac_122_12(console):  # AC-122.12
    from stages import explain
    c = console()
    _, page = c.get("/board")
    for stage in STAGES:
        assert f"/panel/stage/{stage}" in page, stage
    root, text = c.panel("stage", "Build")
    e = explain("Build")
    assert e["what"] in text and e["decision"] in text
    for agent in e["agents"]:
        assert agent in text
    for cmd in e["commands"]:
        assert cmd in text
    _, plan = c.panel("stage", "Plan")
    assert explain("Plan")["what"] in plan
    assert c.json("GET", "/panel/stage/Nowhere")[0] == 404


# ---------------- Done view and search: AC-122.48, AC-122.49 ----------------

def ago(days):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def done_world(console):
    c = console()
    doc = runs_json()
    for sid, days, stage in (("031-recent", 5, "Staging"), ("032-mid", 60, "Dev"), ("033-ancient", 200, "Staging")):
        doc["runs"].append(run_row(spec=sid, run_id=f"r-done-{days}", phase="done", stage=stage, active=False,
                                   outcome="done", ended_at=ago(days), started_at=ago(days + 1),
                                   pr={"number": 70 + days, "url": f"https://github.com/acme/shop-api/pull/{70 + days}"}))
    c.set("runs", doc)
    return c


def test_done_lists_the_last_30_days_newest_first_with_stage_date_and_evidence_ac_122_48(console):  # AC-122.48
    c = done_world(console)
    root, text = c.page("/board?view=done")
    assert "031-recent" in text and "032-mid" not in text and "033-ancient" not in text
    row = row_of(root, "031-recent") or next(n for n in q(root, None, data_card=True) if "031-recent" in n.text())
    assert q(row, None, data_stage="Staging") and q(row, "time")
    assert any("pull/75" in a.attrs.get("href", "") for a in q(row, "a"))


def test_done_takes_90_days_or_all_ac_122_48(console):  # AC-122.48
    c = done_world(console)
    _, ninety = c.page("/board?view=done&period=90")
    assert ninety.count("032-mid") >= 1 and "033-ancient" not in ninety
    root, text = c.page("/board?view=done&period=all")
    assert all(s in text for s in ("031-recent", "032-mid", "033-ancient"))
    assert text.index("031-recent") < text.index("032-mid") < text.index("033-ancient")


@pytest.mark.parametrize("query, shows, hides, stage", [
    ("014", "Wishlist", "Checkout", "Land"),
    ("wishlist", "Wishlist", "Checkout", "Land"),
    ("57", "#57", "Wishlist", "Issue"),
    ("shop-api", "Wishlist", "Nothing-here", "Land"),
])
def test_search_finds_open_items_by_id_title_word_component_or_issue_number_ac_122_49(console, query, shows, hides, stage):  # AC-122.49
    root, text = console().page(f"/board?q={query}")
    assert shows in text and hides not in text
    assert q(root, None, data_stage=stage)


def test_search_finds_done_items_with_the_stage_they_reached_ac_122_49(console):  # AC-122.49
    c = done_world(console)
    root, text = c.page("/board?q=032-mid")
    assert "032-mid" in text and q(root, None, data_stage="Dev")


# ---------------- side panel of a card: AC-122.13, .14, .15, .39 ----------------

def with_smoke_run(console):
    c = console()
    doc = runs_json()
    doc["runs"].append(run_row(spec="012-checkout", run_id="20261025T070000Z-cccc3333", phase="staging", stage="Staging",
                               smoke={"dev": {"result": "passed", "instance": "shop-api/dev"}, "staging": None}))
    c.set("runs", doc)
    rows = specs_json()
    rows[0] = spec_row("012-checkout", "building", title="Checkout")
    c.set("specs:acme/shop-api", rows)
    return c


def test_a_spec_panel_has_a_stage_strip_with_the_current_stage_ac_122_13(console):  # AC-122.13
    root, _ = with_smoke_run(console).panel("spec", "012-checkout")
    strip = [n.attrs["data-stage"] for n in stage_attrs(root)]
    assert strip[:8] == list(STAGES)
    current = [n for n in stage_attrs(root) if n.attrs.get("aria-current")]
    assert len(current) == 1 and current[0].attrs["data-stage"] == "Staging"


def test_a_spec_panel_has_one_line_per_slice_with_stage_and_budget_ac_122_13(console):  # AC-122.13
    root, text = with_smoke_run(console).panel("spec", "012-checkout")
    lines = q(root, None, data_slice=True)
    assert len(lines) == 1 and "acme/shop-api" in lines[0].text() and "3.1" in lines[0].text()
    assert q(lines[0], None, data_stage="Staging")


def test_a_system_spec_panel_lists_each_slice_ac_122_13(console):  # AC-122.13
    c = console()
    rows = specs_json()
    rows[0] = spec_row("012-checkout", "approved", level="system", slices=[{"repo": "acme/shop-api", "spec": "012-checkout", "status": "approved"},
                                                                           {"repo": "acme/shop-web", "spec": "012-checkout", "status": "approved"}])
    c.set("specs:acme/shop-api", rows)
    root, _ = c.panel("spec", "012-checkout")
    assert len(q(root, None, data_slice=True)) == 2


def test_each_criterion_shows_id_text_test_and_verdict_ac_122_14(console):  # AC-122.14
    root, _ = with_smoke_run(console).panel("spec", "012-checkout")
    crit = {n.attrs["data-criterion"]: n for n in q(root, None, data_criterion=True)}
    assert set(crit) == {"AC-012.1", "AC-012.2"}
    first = crit["AC-012.1"].text()
    assert "Given a cart, when paid, then a receipt is sent." in first and "tests/test_cart.py" in first and "met" in first
    assert "not judged" in crit["AC-012.2"].text()


def test_a_smoke_criterion_shows_the_instance_and_the_smoke_result_ac_122_14(console):  # AC-122.14
    root, _ = with_smoke_run(console).panel("spec", "012-checkout")
    smoke = next(n for n in q(root, None, data_criterion=True) if n.attrs["data-criterion"] == "AC-012.2").text()
    assert "shop-api/dev" in smoke and "passed" in smoke


def test_the_evidence_chain_runs_from_issue_to_instance_ac_122_15(console):  # AC-122.15
    root, text = with_smoke_run(console).panel("spec", "012-checkout")
    chain = [n.attrs["data-evidence"] for n in q(root, None, data_evidence=True)]
    assert chain == ["issue", "spec", "plan", "run", "pr", "image", "instance"]
    assert "not yet" in " ".join(n.text() for n in q(root, None, data_evidence="image"))
    assert any("/pull/41" in a.attrs.get("href", "") for a in q(q(root, None, data_evidence="pr")[0], "a"))


def test_the_contract_change_of_the_plan_is_shown_ac_122_15(console):  # AC-122.15
    _, text = with_smoke_run(console).panel("spec", "012-checkout")
    assert "POST /cart" in text


def test_a_panel_links_to_where_the_evidence_lives_ac_122_39(console):  # AC-122.39
    root, _ = with_smoke_run(console).panel("run", "20261025T070000Z-cccc3333")
    hrefs = [a.attrs["href"] for a in q(root, "a", href=True)]
    assert any("/pull/41" in h for h in hrefs) and any("/actions/runs/9" in h for h in hrefs)
    assert any("20261025T070000Z-cccc3333" in a.attrs.get("href", "") or "run record" in a.text().lower() for a in q(root, "a"))


def test_an_instance_links_to_argo_cd_grafana_and_logs_ac_122_39(console, tmp_path):  # AC-122.39
    import yaml
    conf = tmp_path / "config" / "sdlc-foundry"
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "settings.yml").write_text(yaml.safe_dump({"console": {"links": {"staging": {
        "argocd": "https://argocd.example/applications/{system}-{component}-{env}",
        "grafana": "https://grafana.example/d/{component}?var-env={env}", "logs": "https://logs.example/{system}/{component}/{env}"}}}}))
    c = console()
    _, system_page = c.get("/system")
    m = re.search(r'/panel/instance/[^"\'\s<>]+staging[^"\'\s<>]*', system_page) or re.search(r'/panel/instance/[^"\'\s<>]+', system_page)
    assert m, "no instance panel link on the System page"
    root, _ = c.page(m.group(0))
    hrefs = " ".join(a.attrs["href"] for a in q(root, "a", href=True))
    assert "argocd.example" in hrefs and "grafana.example" in hrefs and "logs.example" in hrefs


def test_an_instance_without_link_templates_says_what_to_configure_ac_122_39(console):  # AC-122.39
    c = console()
    _, system_page = c.get("/system")
    m = re.search(r'/panel/instance/[^"\'\s<>]+', system_page)
    assert m
    _, text = c.get(m.group(0))
    assert "console.links" in text


def test_links_for_work_and_instances_come_from_handoff_ac_122_39():  # AC-122.39
    from console import handoff
    links = handoff.links_for_work(run_row())
    blob = str(links)
    assert "/pull/41" in blob and "/actions/runs/9" in blob
    settings = {"console": {"links": {"staging": {"argocd": "https://a.example/{system}/{component}/{env}",
                                                  "grafana": "https://g.example/{component}", "logs": "https://l.example/{env}"}}}}
    got = handoff.links_for_instance("shop", "shop-api", "staging", settings)
    assert "https://a.example/shop/shop-api/staging" in str(got) and "https://g.example/shop-api" in str(got) and "https://l.example/staging" in str(got)
    assert "http" not in str(handoff.links_for_instance("shop", "shop-api", "dev", {}))


# ---------------- hand-off: AC-122.36 ----------------

def test_a_session_is_resumed_in_the_runs_repo_with_the_failure_loaded_ac_122_36():  # AC-122.36
    from console import handoff
    run = run_row(phase="escalated", stopped=True, session_id="sess-1", repo_dir="/tmp/clone",
                  failure={"check": "tests", "test": "tests/test_cart.py::test_total", "criterion": "AC-011.3", "error": "AssertionError: 41 != 42",
                           "excerpt": [], "log": "/tmp/log", "diagnosis": "rounding in total()"})
    argv = handoff.claude_command(run, "docs/specs/011-cart/spec.md", run["failure"])
    assert argv[0].endswith("claude") and argv[1:3] == ["--resume", "sess-1"]
    assert "AssertionError: 41 != 42" in " ".join(argv) and "AC-011.3" in " ".join(argv)


def test_without_a_session_a_new_one_starts_with_spec_run_record_and_failure_ac_122_36():  # AC-122.36
    from console import handoff
    run = run_row(phase="escalated", stopped=True, session_id=None,
                  failure={"check": "tests", "test": "t::x", "criterion": "AC-011.3", "error": "boom-error", "excerpt": [], "log": "l", "diagnosis": "d"})
    argv = handoff.claude_command(run, "docs/specs/011-cart/spec.md", run["failure"])
    joined = " ".join(argv)
    assert "--resume" not in argv and "docs/specs/011-cart/spec.md" in joined and run["run_id"] in joined and "boom-error" in joined


def test_no_terminal_means_the_command_is_shown_instead_ac_122_36(monkeypatch):  # AC-122.36
    from console import handoff
    monkeypatch.delenv("TERMINAL", raising=False)
    monkeypatch.setattr(handoff.shutil, "which", lambda name, *a, **k: None)
    monkeypatch.setattr(handoff.sys, "platform", "linux")
    assert handoff.open_terminal(["claude", "hello"], "/tmp") is False


def test_open_in_claude_starts_a_terminal_and_returns_the_command_ac_122_36(console, monkeypatch):  # AC-122.36
    from console import handoff
    started = []
    monkeypatch.setattr(handoff, "open_terminal", lambda argv, cwd: started.append((list(argv), str(cwd))) or True)
    c = console()
    run_id = runs_json()["runs"][1]["run_id"]
    st, body = c.json("POST", "/api/open-in-claude", {"run_id": run_id})
    assert st == 200 and body["started"] is True and "claude --resume sess-1" in body["command"]
    assert started and started[0][0][1:3] == ["--resume", "sess-1"]
    st, _ = c.json("POST", "/api/open-in-claude", {"run_id": run_id}, token=False)
    assert st == 403


# ---------------- System: AC-122.7, .8, .47 ----------------

def system_rows(root):
    return {row_of(root, n).text(): row_of(root, n) for n in ("shop-api", "shop-web", "postgres") if row_of(root, n)}


def cells(row):
    return {td.attrs["data-env"]: td for td in q(row, "td", data_env=True)}


def test_where_it_runs_has_the_environments_in_order_with_promote_and_policy_ac_122_7(console):  # AC-122.7
    root, _ = console().page("/system")
    head = [th.text() for th in q(root, "th") if any(e in th.text() for e in ("dev", "staging", "prod"))]
    env_heads = [h for h in head if h.split()[0] in ("dev", "staging", "prod")]
    assert [h.split()[0] for h in env_heads] == ["dev", "staging", "prod"]
    by = {h.split()[0]: h for h in env_heads}
    assert "audit" in by["dev"] and "after-dev-smoke" in by["staging"] and "manual" in by["prod"] and "enforce" in by["prod"]


def test_each_cell_shows_version_and_state_as_status_reports_it_ac_122_7(console):  # AC-122.7
    root, _ = console().page("/system")
    api = cells(row_of(root, "shop-api"))
    assert "1.4.0" in api["dev"].text() and "healthy" in api["dev"].text()
    assert "1.4.0" in api["staging"].text() and "verified" in api["staging"].text()
    assert "1.3.0" in api["prod"].text()
    web = cells(row_of(root, "shop-web"))
    assert "NOT VERIFIED" in web["staging"].text()


def test_resources_have_a_row_and_a_library_is_listed_without_cells_ac_122_7(console):  # AC-122.7
    root, text = console().page("/system")
    pg = row_of(root, "postgres")
    assert pg and "healthy" in cells(pg)["dev"].text()
    lib = row_of(root, "shop-lib")
    assert lib is None or not cells(lib)
    assert "shop-lib" in text and "shop-api" in text


def test_the_page_lists_components_apis_and_resources_with_their_relations_ac_122_7(console):  # AC-122.7
    _, text = console().page("/system")
    for needle in ("shop-api", "shop-web", "shop-lib", "postgres", "shop-api-rest"):
        assert needle in text, needle


def test_add_to_the_model_opens_five_forms_in_place_ac_122_7(console):  # AC-122.7
    root, _ = console().page("/system")
    assert {f.attrs["data-form"] for f in q(root, None, data_form=True)} == {"component", "api", "resource", "environment", "system"}


def test_promote_is_offered_on_a_verified_cell_before_a_manual_environment_ac_122_8(console):  # AC-122.8
    root, _ = console().page("/system")
    offered = q(root, "button", data_action="promote")
    assert len(offered) == 1 and not disabled(offered[0])
    assert offered[0] in list(cells(row_of(root, "shop-api"))["staging"].walk())


def test_promote_is_not_offered_where_the_cell_is_not_verified_ac_122_8(console):  # AC-122.8
    root, _ = console().page("/system")
    assert not q(row_of(root, "shop-web"), "button", data_action="promote")
    assert not q(cells(row_of(root, "shop-api"))["dev"], "button", data_action="promote")
    assert not q(cells(row_of(root, "shop-api"))["prod"], "button", data_action="promote")


def with_candidate(console):
    c = console()
    doc = status_json()
    doc["rows"][0]["release_candidate"] = {"version": "1.5.0", "commits": 9, "specs": ["014-x"], "fixes": ["#57"], "digest": "sha256:aaaa"}
    c.set("status", doc)
    return c


def test_a_verified_newer_version_offers_cut_release_on_the_cell_ac_122_47(console):  # AC-122.47
    root, _ = with_candidate(console).page("/system")
    assert len(q(cells(row_of(root, "shop-api"))["staging"], "button", data_action="cut-release")) == 1
    assert not q(row_of(root, "shop-web"), "button", data_action="cut-release")


def test_cut_release_shows_version_specs_fixes_pr_tag_and_the_way_back_ac_122_47(console):  # AC-122.47
    c = with_candidate(console)
    _, system_page = c.get("/system")
    m = re.search(r'/panel/release/[^"\'\s<>]+', system_page)
    assert m
    root, text = c.page(m.group(0))
    for needle in ("1.5.0", "014-x", "#57"):
        assert needle in text, needle
    low = text.lower()
    assert "release pull request" in low and "tag" in low and "digest" in low and "close" in low
    assert "/component:release" in [n.text() for n in q(root, "code", data_command=True)]
    assert q(root, "button", data_action="cut-release")


def test_the_board_card_of_a_release_candidate_offers_cut_release_ac_122_47(console):  # AC-122.47
    root, _ = with_candidate(console).page("/board")
    assert q(root, "button", data_action="cut-release")


# ---------------- AC-122.40: nothing to show is never an empty table ----------------

def empty_data(console, tmp_path):
    data = {"model": None, "status": status_json(), "needs": {"schema": 1, "system": "shop", "read_at": "2026-10-26T08:00:00Z", "items": [],
                                                              "unavailable": []},
            "runs": {"schema": 1, "read_at": "2026-10-26T08:00:00Z", "store": {"state": "ok", "detail": None}, "runs": []},
            "specs:acme/shop-api": [], "doctor": doctor_json()}
    from console_support import model_json
    data["model"] = model_json(tmp_path)
    return console(data)


def test_an_empty_inbox_lists_the_next_steps_to_a_first_change_ac_122_40(console, tmp_path):  # AC-122.40
    root, text = empty_data(console, tmp_path).page("/inbox")
    assert "shop-api" in text                                    # what already runs
    assert "Describe your first change" in text
    assert any("Describe your first change" in b.text() for b in q(root, None, data_action="palette"))
    assert "notification" in text.lower()
    assert not q(root, None, data_need=True)


def test_an_empty_board_keeps_its_columns_with_one_line_each_ac_122_40(console, tmp_path):  # AC-122.40
    from stages import explain
    root, _ = empty_data(console, tmp_path).page("/board")
    cols = q(root, None, data_column=True)
    assert [c.attrs["data-column"] for c in cols] == list(STAGES)
    for c in cols:
        assert explain(c.attrs["data-column"])["what"] in c.text()


def test_an_empty_system_still_shows_its_parts_and_instances_ac_122_40(console, tmp_path):  # AC-122.40
    root, text = empty_data(console, tmp_path).page("/system")
    assert "shop-api" in text and "postgres" in text


@pytest.mark.parametrize("path", ["/inbox", "/board", "/board?view=list", "/system"])
def test_no_page_shows_a_table_with_no_rows_ac_122_40(console, tmp_path, path):  # AC-122.40
    root, _ = empty_data(console, tmp_path).page(path)
    for table in q(root, "table"):
        assert [tr for tr in q(table, "tr") if q(tr, "td")], path


# ---------------- AC-122.41: prerequisites ----------------

def test_the_banner_names_each_missing_piece_with_the_fix_ac_122_41(console):  # AC-122.41
    c = console()
    c.set("doctor", doctor_json(missing=["claude", "gh", "kube:prod"]))
    s = c.json("GET", "/api/state")[1]
    pieces = {b["piece"]: b["fix"] for b in s["banner"]}
    assert set(pieces) >= {"claude", "gh", "kube:prod"}
    assert "Claude Code" in pieces["claude"] and "gh auth login" in pieces["gh"] and "use-context" in pieces["kube:prod"]
    root, text = c.page("/inbox")
    for fix in pieces.values():
        assert fix in text


def test_without_claude_every_action_is_disabled_and_says_which_piece_it_needs_ac_122_41(console, monkeypatch, tmp_path):  # AC-122.41
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    monkeypatch.delenv("CPLAT_CLAUDE", raising=False)
    c = console()
    c.set("doctor", doctor_json(missing=["claude"]))
    root, _ = c.panel("need", need_id("approve"))
    for kind in ("approve-ship", "approve", "request-changes"):
        btn = action(root, kind)
        assert disabled(btn)
    assert "claude" in " ".join(r.text() for r in q(root, "span", data_disabled_reason=True)).lower()
    assert q(root, "code", data_command=True) and q(root, "button", data_copy=True)     # the command can still be copied


def test_everything_that_does_not_need_the_missing_piece_works_ac_122_41(console, monkeypatch, tmp_path):  # AC-122.41
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    c = console()
    c.set("doctor", doctor_json(missing=["claude", "gh", "kube:prod"]))
    for path in ("/inbox", "/board", "/board?view=list", "/system", "/panel/stage/Build", "/palette?q=x"):
        assert c.get(path)[0] == 200, path
    root, _ = c.panel("need", need_id("promote"))
    assert disabled(action(root, "promote"))
