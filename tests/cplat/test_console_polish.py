"""The console polish: readable card titles, rounded amounts, state tones, named sources and the Inbox before its first read."""
from types import SimpleNamespace

import pytest

from console import board, inbox
from console.html import money, source_label, unavailable


@pytest.mark.parametrize("slug, words", [
    ("013-ai-ops-serves-as-the-platform-s-autonomy", "Ai ops serves as the platform's autonomy"),
    ("001-stock-move", "Stock move"),
    ("#12", ""),
    ("shop-api sha-1234567", ""),
    ("20261027T071349Z-1a6f269d", ""),
])
def test_a_spec_slug_reads_as_words(slug, words):
    assert board.readable(slug) == words


@pytest.mark.parametrize("value, shown", [(33.7487, "33.75"), (60, "60"), (170.0, "170"), (0.5, "0.5"), (None, "None")])
def test_amounts_show_at_most_two_decimals(value, shown):
    assert money(value) == shown


@pytest.mark.parametrize("item, tone", [
    ({"stopped": True, "state": "Stopped", "stage": "Build"}, "stopped"),
    ({"stopped": False, "state": "Running", "stage": "Build"}, "running"),
    ({"stopped": False, "state": "Not started", "stage": "Build"}, "idle"),
    ({"stopped": False, "state": "2 open questions", "stage": "Spec"}, "decide"),
    ({"stopped": False, "state": "Verified in staging, waits to be promoted", "stage": "Prod"}, "decide"),
])
def test_a_card_tone_follows_its_state_not_its_column(item, tone):
    assert board.tone(item) == tone


def test_an_unavailable_part_names_its_source_in_words():
    part = unavailable("needs", "2026-11-04T10:05:55Z", "timed out after 60 s")
    assert "The list of open decisions is not available" in part and 'data-source="needs"' in part
    assert source_label("specs:ika100/ai-ops") == "The specs of ika100/ai-ops"
    assert source_label("cluster:prod") == "cluster:prod"


def _ctx(source):
    return SimpleNamespace(source=lambda name: source if name == "needs" else None,
                           data=lambda name: None, state=lambda: {"read_at": None, "badge": 0})


def test_the_inbox_does_not_claim_nothing_waits_before_it_read_the_decisions():
    html = inbox.page(_ctx(SimpleNamespace(data=None, read_at=None, error=None, unavailable_since=None)), {})
    assert "Reading the open decisions" in html and "Nothing waits for you" not in html


def test_the_inbox_says_nothing_waits_once_it_read_an_empty_list():
    src = SimpleNamespace(data={"items": []}, read_at="2026-11-04T10:00:00Z", error=None, unavailable_since=None)
    ctx = _ctx(src)
    ctx.data = lambda name: {"items": []} if name == "needs" else None
    assert "Nothing waits for you" in inbox.page(ctx, {})


# ---------------- the glossary: one text per term, for the ? tips and the How it works page ----------------

import re
from pathlib import Path

from console import glossary
from console_support import parse, q

CONSOLE = Path(__file__).resolve().parents[2] / "scripts" / "cplat" / "console"


def test_every_tip_and_legend_names_a_term_of_the_glossary():
    used = set()
    for path in CONSOLE.glob("*.py"):
        text = path.read_text()
        used |= set(re.findall(r"""glossary\.tip\(["'](\w+)["']""", text))
        for keys in re.findall(r"glossary\.legend\(\(([^)]*)\)", text):
            used |= set(re.findall(r"""["'](\w+)["']""", keys))
    assert used and used <= set(glossary.TERMS), used - set(glossary.TERMS)


def test_every_term_is_on_the_how_it_works_page_once():
    listed = [k for _, _, _, keys in glossary.SECTIONS for k in keys]
    assert sorted(listed) == sorted(glossary.TERMS) and len(listed) == len(set(listed))


def test_a_tip_is_a_labelled_button_with_its_text_and_a_link_to_the_term():
    html = glossary.tip("verified")
    assert 'aria-label="What is verified?"' in html and 'role="tooltip"' in html and 'href="/help#t-verified"' in html
    with pytest.raises(KeyError):
        glossary.tip("no-such-term")


def test_how_it_works_lists_the_eight_stages_and_anchors_every_term(console):
    root, text = console().page("/help")
    assert [n.attrs["data-stage"] for n in q(root, None, data_stage=True) if any(a.tag == "ol" for a in n.ancestors())] == \
        ["Issue", "Spec", "Plan", "Build", "Land", "Dev", "Staging", "Prod"]
    for key in glossary.TERMS:
        assert q(root, None, id=f"t-{key}"), key


@pytest.mark.parametrize("path, keys", [
    ("/inbox", {"decision", "waiting", "read_at"}),
    ("/board", {"running", "stopped", "waits", "not_started", "decision_stage", "budget"}),
    ("/system", {"promote_rule", "policy", "verified", "not_verified", "model"}),
])
def test_each_page_explains_its_terms_where_they_appear(console, path, keys):
    root, _ = console().page(path)
    assert keys <= {n.attrs["data-tip"] for n in q(root, None, data_tip=True)}


def test_the_menu_links_how_it_works(console):
    root, _ = console().page("/inbox")
    assert any(a.attrs.get("href") == "/help" for a in q(root, "a"))


# ---------------- the model forms pick existing things from lists ----------------

def _options(select):
    return [o.attrs.get("value") for o in q(select, "option")]


def test_existing_components_resources_and_apis_are_chosen_from_a_list(console):
    root, _ = console().page("/system")
    [form] = q(root, "form", data_form="component")
    [remove] = [s for s in q(form, "select", name="component")]
    assert remove.attrs.get("disabled") is not None and _options(remove)[0] == "" and len(_options(remove)) > 1
    [box] = [p for p in q(form, None, data_show_when="action=remove")]
    assert "hidden" in box.attrs
    [api] = q(root, "form", data_form="api")
    assert q(api, "select", name="component") and q(api, "select", name="consumes")
    assert _options(q(api, "select", name="provides_type")[0]) == ["", "openapi", "grpc", "graphql", "events"]
    [res] = q(root, "form", data_form="resource")
    assert _options(q(res, "select", name="type")[0]) == ["", "database", "bucket", "cache", "broker"]


def test_each_environment_offers_only_the_promote_rules_it_allows(console):
    root, _ = console().page("/system")
    [form] = q(root, "form", data_form="environment")
    for box in q(form, None, data_show_when=True):
        env = box.attrs["data-show-when"].split("=")[1]
        for select in q(box, "select", name="promote"):
            values = _options(select)[1:]
            assert set(values) <= {"dev": set(), "prod": {"manual"}}.get(env, {"after-dev-smoke", "manual"}), (env, values)


def test_a_provided_api_gets_its_type_from_the_list():
    from console import preview
    words = preview.command_of("api", {"action": "set", "component": "shop-api", "provides": "orders", "provides_type": "grpc"})
    assert words == ["/component:set", "shop-api", "--provides", "orders:grpc"]


def test_a_refresh_keeps_a_form_that_is_being_filled_in():
    js = (CONSOLE / "static" / "console.js").read_text()
    assert "form[data-form][data-dirty]" in js and "applyConditions" in js


# ---------------- System as a tree: each item a row, changes start from the item, forms in the drawer ----------------

import json as _json


def test_the_system_is_a_tree_of_groups_with_an_add_button_each(console):
    root, _ = console().page("/system")
    groups = [n.text() for n in q(root, "tr") if "group" in n.attrs.get("class", "").split()]
    assert [g.split()[0] for g in groups][:1] == ["Components"] and any(g.startswith("Resources") for g in groups)
    adds = {b.attrs["data-form-open"]: _json.loads(b.attrs["data-prefill"]) for b in q(root, "button", data_form_open=True)
            if b.text().startswith("+ Add")}
    assert adds == {"component": {"action": "add"}, "resource": {"action": "add"}, "api": {}}


def test_a_component_row_opens_its_details_with_remove_and_change_apis_filled_in(console):
    root, _ = console().page("/system")
    [toggle] = [b for b in q(root, "button", data_toggle="component:shop-api")]
    assert toggle.attrs["aria-expanded"] == "false" and toggle.attrs.get("aria-label")
    [detail] = [tr for tr in q(root, "tr") if tr.attrs.get("data-detail-of") == "component:shop-api"]
    assert "hidden" in detail.attrs and "Repo" in detail.text()
    opens = {(b.attrs["data-form-open"], b.text()): _json.loads(b.attrs["data-prefill"]) for b in q(detail, "button", data_form_open=True)}
    assert opens == {("api", "Change APIs"): {"component": "shop-api"},
                     ("component", "Remove"): {"action": "remove", "component": "shop-api"}}


def test_the_forms_wait_in_the_drawer_one_box_each(console):
    root, _ = console().page("/system")
    [drawer] = q(root, "aside", id="model-drawer")
    assert "hidden" in drawer.attrs
    boxes = {s.attrs["data-form-box"] for s in q(drawer, "section", data_form_box=True)}
    assert boxes == {"component", "api", "resource", "environment", "system"}
    assert q(drawer, "button", data_action="close-drawer")


def test_the_palette_keeps_the_forms_as_disclosures(tmp_path):
    from console import system_page
    model = {"system": {"name": "shop", "owner": "acme"}, "components": [{"name": "shop-api"}],
             "environments": [{"name": "dev"}, {"name": "prod", "promotion": "manual"}]}
    ctx = SimpleNamespace(data=lambda name: model if name == "model" else None, repo_dir=tmp_path)
    html = system_page.model_forms(ctx)
    assert html.count("<details") == 5 and html.count('data-form="') == 5 and 'id="form-' not in html


def test_a_budget_line_keeps_usd_in_capitals():
    info = board._run_info({"budget": {"used": {"cost": 3.1, "minutes": 42}, "limit": {"cost": 15, "minutes": 180}}})
    assert info["budget"] == "Cost 3.1 of 15 USD, 42 min of 180 min"


# ---------------- the palette: its search box is the only text field ----------------

def test_the_palette_asks_for_the_sentence_once(console):
    _, text = console().get("/palette?q=add%20a%20wishlist")
    root = parse(text)
    for section in ("describe", "ask"):
        [sec] = q(root, "section", data_palette=section)
        assert not [i for i in q(sec, "input") if i.attrs.get("type") in (None, "text")], section
        [hidden] = q(sec, "input", data_from_palette=True)
        assert hidden.attrs["type"] == "hidden" and hidden.attrs["value"] == "add a wishlist"
        assert "“add a wishlist”" in sec.text()


def test_with_an_empty_box_describe_and_ask_say_what_to_do(console):
    _, text = console().get("/palette?q=")
    root = parse(text)
    [sec] = q(root, "section", data_palette="describe")
    buttons = q(sec, "button", data_action="describe")
    assert buttons and all("disabled" in b.attrs for b in buttons)
    assert "Type what should change in the box above first." in sec.text()
    [ask] = q(root, "section", data_palette="ask")
    assert "disabled" in q(ask, "button")[0].attrs


def test_the_script_sends_the_search_boxs_current_text():
    js = (CONSOLE / "static" / "console.js").read_text()
    assert "data-from-palette" in js and "fromPalette(form)" in js
