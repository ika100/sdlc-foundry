"""Spec 193 acceptance tests: the Build step shows the queue and its choices (AC-193.1) and the set-up without a policy (AC-193.2).

Screens and the `--json` document of `cplat next`; the queue is the read-only twin of `cplat dispatch plan`
(`dispatch_cycle.preview`), replaced here by fixed entries. Estimates come from `state.json` `history`."""
import re

import pytest

from support_193 import BuildWorld, by_label, entry, labels, question

POLICY_FILE = """# The run queue's policy (docs/dispatch.md), written by /platform:next.
budget:
  tokens_per_day: 21000000
sources: [issues, specs]
gates:
  approve_specs: human
"""


@pytest.fixture
def world(tmp_path, monkeypatch):
    return BuildWorld(tmp_path, monkeypatch)


def three(world):
    world.queue(entry(1, "#712", title="Fix the label"), entry(2, "spec 188", kind="ship", title="Queue screen"),
                entry(3, "spec 189", kind="ship", title="Progress screen", after="spec 188"))


# ---------------- AC-193.1: the queue ----------------

def test_queue_is_numbered_in_plan_order_with_what_you_get(world, capsys, tmp_path):  # AC-193.1
    three(world)
    j = world.judgement(tmp_path, {"issue-712": {"you_get": "A label that stays"}, "spec-188": {"you_get": "A queue screen"},
                                   "spec-189": {"you_get": "A progress screen"}})
    screen = world.screen(capsys, "--judgement", j)
    assert "3 items are ready to build." in screen
    lines = [ln for ln in screen.splitlines() if re.match(r"\s+\d\. ", ln)]
    assert lines == ["  1. A label that stays (#712)", "  2. A queue screen (spec 188)", "  3. A progress screen (spec 189)"]
    assert "Your part: choose how many items build at once." in screen


def test_without_judgement_the_title_is_the_what_you_get_line(world, capsys):  # AC-193.1
    three(world)
    screen = world.screen(capsys)
    assert "  1. Fix the label (#712)" in screen
    assert "  2. Queue screen (spec 188)" in screen


def test_estimates_only_from_three_comparable_runs(world, capsys):  # AC-193.1
    world.queue(entry(1, "#712", title="Fix a"), entry(2, "#713", title="Fix b"))
    for minutes, tokens in ((20, 1_000_000), (25, 1_200_000), (30, 1_400_000)):
        world.history("fix", minutes, tokens)
    screen = world.screen(capsys)
    assert "  1. Fix a (#712), about 25 min" in screen and "  2. Fix b (#713), about 25 min" in screen
    assert "Total: about 50 min of work." in screen
    assert "this queue needs about 2,400,000" in screen
    doc = world.doc(capsys)["build"]
    assert [q["minutes"] for q in doc["queue"]] == [25, 25] and doc["total_minutes"] == 50
    assert [q["tokens"] for q in doc["queue"]] == [1_200_000, 1_200_000] and doc["need_tokens"] == 2_400_000


def test_two_comparable_runs_give_no_estimate_and_no_total(world, capsys):  # AC-193.1
    world.queue(entry(1, "#712", title="Fix a"))
    world.history("fix", 20, 1_000_000)
    world.history("fix", 30, 1_400_000)
    screen = world.screen(capsys)
    assert "  1. Fix a (#712)" in screen and "(#712), about" not in screen
    assert "Total:" not in screen and "needs about" not in screen
    doc = world.doc(capsys)["build"]
    assert doc["queue"][0]["minutes"] is None and doc["total_minutes"] is None and doc["need_tokens"] is None


def test_only_runs_of_the_same_kind_are_comparable_and_a_total_needs_every_entry(world, capsys):  # AC-193.1
    world.queue(entry(1, "#712", title="Fix a"), entry(2, "spec 188", kind="ship", title="Ship b"))
    world.history("fix", 25, 1_200_000, n=3)          # three fix runs, no ship run
    screen = world.screen(capsys)
    assert "  1. Fix a (#712), about 25 min" in screen
    assert "Ship b (spec 188)" in screen and "Ship b (spec 188), about" not in screen
    assert "Total:" not in screen and "needs about" not in screen
    doc = world.doc(capsys)["build"]
    assert doc["queue"][1]["minutes"] is None and doc["total_minutes"] is None


def test_tokens_today_line_and_the_need_only_when_known(world, capsys):  # AC-193.1
    three(world)
    world.used(4_200_000)
    screen = world.screen(capsys)
    assert "Tokens today: 4,200,000 of 20,000,000" in screen
    assert "needs about" not in screen
    assert world.doc(capsys)["build"]["tokens"] == {"used": 4_200_000, "limit": 20_000_000, "raised": False}


def test_a_ship_behind_another_ship_says_when_it_starts(world, capsys):  # AC-193.1  (A2)
    three(world)
    screen = world.screen(capsys)
    assert "starts after spec 188: one spec builds at a time" in screen
    assert world.doc(capsys)["build"]["queue"][2]["after"] == "spec 188"


def test_build_question_choices_and_steps(world, capsys):  # AC-193.1
    three(world)
    q = question(world.doc(capsys), "build")
    assert q["header"] == "Build"
    assert labels(q) == ["Two at a time", "One at a time", "Show details", "Not now"]
    assert q["options"][0]["recommended"] is True
    assert by_label(q, "Two")["steps"] == ["cplat dispatch build --slots 2"]
    assert by_label(q, "One")["steps"] == ["cplat dispatch build --slots 1"]
    assert "cplat dispatch pause --drain" in " ".join(by_label(q, "Two")["undo"])


def test_not_now_starts_nothing_and_the_queue_stays_a_waiting_item(world, capsys):  # AC-193.1
    three(world)
    doc = world.doc(capsys)
    not_now = by_label(question(doc, "build"), "Not now")
    assert not not_now["steps"] and not_now["then"][:2] == ["cplat", "next"]
    assert "build:o/n" in not_now["then"] and "--later" in not_now["then"]
    after = world.doc(capsys, "--later", "build:o/n")
    assert after["waiting"]["later"] == 1 and not any(q["id"] == "build" for q in after["questions"])
    world.stuck(500)                                           # another group is shown first: the queue is still counted
    assert "Build: 3 ready" in world.screen(capsys)


def test_queue_screen_changes_nothing(world, capsys):  # AC-193.1
    three(world)
    before = world.snapshot()
    assert "3 items are ready to build." in world.screen(capsys)
    assert world.doc(capsys)["build"]["queue"]
    assert world.snapshot() == before and world.writes() == []


def test_no_queue_no_build_document(world, capsys):  # AC-193.1
    world.queue()
    doc = world.doc(capsys)
    assert doc["build"] is None and not any(q["id"] == "build" for q in doc["questions"])


def test_build_json_document_keys(world, capsys):  # AC-193.1
    three(world)
    doc = world.doc(capsys)["build"]
    assert doc["policy"] is True and doc["setup"] is None
    assert {"queue", "total_minutes", "need_tokens", "tokens", "loop", "slots", "paused", "current", "events", "running"} <= set(doc)
    first = doc["queue"][0]
    assert {"n", "key", "ref", "kind", "title", "you_get", "after", "minutes", "tokens"} <= set(first)
    assert first["key"] == "issue-712" and first["you_get"] == "Fix the label"


def test_judge_items_ask_the_session_for_the_what_you_get_lines(world, capsys):  # AC-193.1  (A6)
    three(world)
    doc = world.doc(capsys)
    assert [j["key"] for j in doc["judge_items"]] == ["issue-712", "spec-188", "spec-189"]
    assert all("you_get" in j["wants"] and j["text"] for j in doc["judge_items"])
    assert doc["judgement_wanted"] is True


def test_the_how_tells_the_session_about_typed_values_and_free_answers(world, capsys):  # AC-193.1
    how = world.doc(capsys)["how"]
    # `how` is the procedure `cplat next --json` hands the session; `input`, `other` and `<answer>` are contract words
    for word in ("input", "other", "<answer>", "cplat dispatch"):
        assert word in how


# ---------------- AC-193.2: no policy file ----------------

@pytest.fixture
def bare(tmp_path, monkeypatch):
    w = BuildWorld(tmp_path, monkeypatch, policy=False)
    w.queue(entry(1, "#712", title="Fix the label"), entry(2, "#713", title="Fix b"))
    return w


def test_without_policy_the_screen_offers_set_up_not_a_guide(bare, capsys):  # AC-193.2
    bare.hint(None, 20_300_000, 12_000_000)
    screen = bare.screen(capsys)
    assert "Building needs a run policy; I can set one up." in screen
    assert "Your part: set up the build, or leave it for now." in screen
    assert "docs/dispatch.md" not in screen and "http" not in screen
    q = question(bare.doc(capsys), "build-setup")
    assert q["header"] == "Set up" and labels(q) == ["Set up and build", "Show details", "Not now"]
    assert q["options"][0]["recommended"] is True
    assert by_label(q, "Set up")["steps"] == ["cplat dispatch setup --tokens-per-day 21000000"]


def test_set_up_document_has_the_file_and_the_suggested_number(bare, capsys):  # AC-193.2
    bare.hint(None, 20_300_000, 12_000_000)
    doc = bare.doc(capsys)["build"]
    assert doc["policy"] is False and doc["setup"]["tokens_per_day"] == 21_000_000
    assert doc["setup"]["file"] == POLICY_FILE
    assert len(doc["queue"]) == 2


def test_set_up_details_print_the_exact_file(bare, capsys):  # AC-193.2
    bare.hint(20_300_000)
    screen = bare.screen(capsys, "--show", "details:build-setup")
    assert "It commits this file through a pull request that merges on green CI:" in screen
    block = "\n".join(("  " + ln) if ln else ln for ln in POLICY_FILE.splitlines())
    assert block in screen


def test_without_usage_the_set_up_asks_for_the_number_and_recommends_none(bare, capsys):  # AC-193.2  (A4)
    bare.hint(None, None, 0)
    doc = bare.doc(capsys)
    assert doc["build"]["setup"]["tokens_per_day"] is None
    opt = by_label(question(doc, "build-setup"), "Set up")
    assert opt["input"]["name"] == "tokens" and opt["input"]["prompt"]
    assert opt["steps"] == ["cplat dispatch setup --tokens-per-day <tokens>"]
    assert "<your number>" in bare.screen(capsys, "--show", "details:build-setup")


def test_not_now_without_a_policy_writes_nothing(bare, capsys):  # AC-193.2
    bare.hint(20_300_000)
    before = bare.snapshot()
    not_now = by_label(question(bare.doc(capsys), "build-setup"), "Not now")
    assert not not_now["steps"] and "build:o/n" in not_now["then"]
    assert bare.snapshot() == before and bare.writes() == []
    assert not (bare.repo / ".platform" / "dispatch.yml").exists()
