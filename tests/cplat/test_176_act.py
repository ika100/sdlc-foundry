"""Spec 176 acceptance tests: `cplat issue triage act` applies exactly the confirmed rows and hands fixes over without starting
one (AC-176.3, AC-176.8), prints the hand-over summary (AC-176.15), and `publish-specs` publishes the new specs of a run as one
draft PR (AC-176.4). GitHub is the fake of `support_176`; git and gh of `publish-specs` go through the seams of `triage_act`."""
import json

import pytest

import core
from support_176 import FORBIDDEN, SLUG, ago, comment, load, overview_world, row, world  # noqa: F401  (fixture)


def acted(w):
    """The overview scenario with its feature rows tied to specs: #563 to the new spec 201, #571 to the existing spec 176."""
    rows = overview_world(w)
    w.spec("201-new-thing", status="draft", title="Dark mode")
    for r in rows:
        if r["number"] == 563:
            r.update(spec="201-new-thing", new_spec=True)
        if r["number"] == 571:
            r.update(spec="176-triage-x")        # keeps its question, so #571 stays under "Needs your decision"
    w.batch()
    w.set_specs_pr()
    return rows


def act(w, rows, *extra, rows_arg="all"):
    return w.run("act", "--proposals", w.proposals(rows), "--rows", rows_arg, *extra)


# ---------------- AC-176.8 what act does per class ----------------

def test_act_adds_the_labels_and_posts_the_comment_of_every_confirmed_row_ac_176_8(world):  # AC-176.8
    rows = acted(world)
    assert act(world, rows).rc == 0
    edits, comments = world.edits(), world.comments()
    assert edits[560] == ({"bug", "triaged", "p1"}, {"triage"}) and edits[562] == ({"bug", "triaged", "p1"}, {"triage"})
    assert edits[563] == ({"enhancement", "tracked", "triaged", "p2"}, {"triage"})
    assert edits[571] == ({"enhancement", "tracked", "triaged", "p1"}, {"triage"})
    assert edits[564] == ({"question"}, {"triage"}) and edits[548] == ({"tracked"}, {"triage"})
    assert 551 not in edits and 551 not in comments and 548 not in comments
    assert comments[563] == "Tracked as spec 201-new-thing" and comments[571] == "Tracked as spec 176-triage-x"
    assert comments[564] == "Run cplat rotate."


def test_the_triage_comment_holds_the_task_in_the_triagers_words_whoever_the_author_is_ac_176_8(world):  # AC-176.8
    rows = acted(world)
    rows[0]["answers"] = ["Only Safari"]                 # #560 comes from a contributor, #562 from the owner
    act(world, rows)
    comments = world.comments()
    assert comments[562] == "Triage: Crash when the config file is empty\n\nClass: bug, priority P1.\nExpected result: Issue 562 works"
    assert comments[560] == ("Triage: Login fails after the token refresh on Safari\n\nClass: bug, priority P1.\n"
                             "Answers: Only Safari\nExpected result: Issue 560 works")


def test_a_small_change_is_labelled_enhancement_and_triaged_ac_176_8(world):  # AC-176.8
    world.issue(1)
    world.batch()
    act(world, [row(1, **{"class": "small-change", "priority": "P2"})])
    assert world.edits()[1] == ({"enhancement", "triaged", "p2"}, {"triage"}) and world.comments()[1].startswith("Triage:")


def test_a_fix_is_never_started_and_nothing_is_closed_ac_176_8(world):  # AC-176.8
    rows = acted(world)
    n = len(world.calls)                                     # the batch read is not part of the act
    act(world, rows)
    after = world.calls[n:]
    assert {tuple(c[:2]) for c in after} <= {("issue", "view"), ("label", "list"), ("issue", "edit"), ("issue", "comment")}
    assert not any("close" in c for c in after)


def test_only_real_label_changes_are_made_and_another_priority_is_replaced_ac_176_8(world):  # AC-176.8
    world.issue(1, labels=("triage", "triaged", "p2"))
    world.batch()
    act(world, [row(1, priority="P0")])
    assert world.edits()[1] == ({"bug", "p0"}, {"triage", "p2"})


def test_question_duplicate_wontfix_and_needs_info_label_and_comment_ac_176_3(world):  # AC-176.3
    for n in (1, 2, 3, 4):
        if n == 1:           # parked as needs-info and answered by the reporter, so it is queued again
            world.issue(n, labels=("triage", "needs-info"), author="rep", created=ago(days=9),
                        comments=[comment("me", "Which version?", "OWNER", ago(days=4)), comment("rep", "2.1", "NONE", ago(days=1))])
        else:
            world.issue(n, labels=("triage",))
    world.batch()
    extra = {"priority": None, "expected": None, "comment": "the text"}
    rows = [row(1, **{"class": "question", **extra}), row(2, **{"class": "duplicate", "duplicate_of": 9, **extra}),
            row(3, **{"class": "wontfix", **extra}), row(4, **{"class": "needs-info", **extra})]
    act(world, rows)
    edits = world.edits()
    assert edits[1] == ({"question"}, {"triage", "needs-info"}) and edits[2] == ({"duplicate"}, {"triage"})
    assert edits[3] == ({"wontfix"}, {"triage"}) and edits[4] == ({"needs-info"}, {"triage"})
    assert set(world.comments().values()) == {"the text"} and len(world.comments()) == 4


def test_a_row_to_explore_makes_no_call_at_all_ac_176_3(world):  # AC-176.3
    world.issue(7)
    world.issue(8)
    world.batch()
    n = len(world.calls)
    act(world, [row(7, **{"class": "needs-exploring", "priority": None, "expected": None}), row(8)])
    mine = [c for c in world.calls[n:] if "7" in c[:3]]
    assert mine == []


# ---------------- AC-176.3 exactly the confirmed rows ----------------

def test_rows_names_the_issues_and_nothing_else_is_touched_ac_176_3(world):  # AC-176.3
    rows = acted(world)
    act(world, rows, rows_arg="562,564")
    assert set(world.edits()) == {562, 564} and set(world.comments()) == {562, 564}
    assert {c[2] for c in world.writes()} == {"562", "564"}


def test_a_number_outside_the_batch_is_refused_and_writes_nothing_ac_176_3(world):  # AC-176.3
    rows = acted(world)
    with pytest.raises(core.PlatformError):
        act(world, rows, rows_arg="562,999")
    assert world.writes() == []


def test_one_invalid_named_row_stops_everything_before_any_write_ac_176_3(world):  # AC-176.3
    rows = acted(world)
    rows[2].pop("spec")                                      # #563 is a feature without a spec
    with pytest.raises(core.PlatformError) as err:
        act(world, rows)
    assert "563" in str(err.value) + (err.value.hint or "") and world.writes() == []
    rows[2]["spec"] = "999-missing"
    with pytest.raises(core.PlatformError):
        act(world, rows)
    assert world.writes() == []


def test_rows_not_named_are_not_validated_nor_touched_ac_176_3(world):  # AC-176.3
    rows = acted(world)
    rows[2].pop("spec")
    assert act(world, rows, rows_arg="562").rc == 0 and set(world.edits()) == {562}


def test_dry_run_writes_nothing_and_says_will_do_ac_176_3(world):  # AC-176.3
    rows = acted(world)
    out = act(world, rows, "--dry-run").out
    assert world.writes() == [] and "Will do" in out and "Done" not in out and "Next" in out


# ---------------- AC-176.15 the summary ----------------

def parts(text):
    sections, name = {}, None
    for line in text.splitlines():
        if line in ("Done", "Will do", "Next", "Undo"):
            name = line
            sections[name] = []
        elif name:
            sections[name].append(line.strip())
    return sections


def test_the_summary_lists_what_was_done_per_group_ac_176_15(world):  # AC-176.15
    rows = acted(world)
    out = act(world, rows).out
    done = parts(out)["Done"]
    assert any(l.startswith("Clear:") and "#562 queued for a fix (bug, P1)" in l for l in done)
    assert any(l.startswith("Needs your decision:") and "#560 queued for a fix (bug, P1)" in l and "#571 tracked in spec 176" in l for l in done)
    assert "Already handled: #548 labelled tracked" in done


def test_the_summary_ends_with_the_next_step_and_who_takes_it_ac_176_15(world):  # AC-176.15
    rows = acted(world)
    nxt = parts(act(world, rows).out)["Next"]
    assert "fix runs on its own: #560, #562 (cplat dispatch status, or the console Board)" in nxt
    assert "approve spec 201 (you): /component:spec approve 201 (draft PR #640)" in nxt
    nothing = next(l for l in nxt if l.startswith("nothing:"))
    assert all(f"#{n}" in nothing for n in (548, 564, 571))
    assert [l.split(":")[0] for l in nxt] == ["fix runs on its own", "approve spec 201 (you)", "nothing"]


def test_the_summary_names_how_to_undo_each_change_ac_176_15(world):  # AC-176.15
    rows = acted(world)
    undo = parts(act(world, rows).out)["Undo"]
    assert ("#562: gh issue edit 562 --remove-label bug --remove-label triaged --remove-label p1 --add-label triage") in undo
    assert "#562: delete the comment in the browser (issue comments cannot be removed with gh)" in undo
    assert "specs: close draft PR #640 and delete branch docs/triage-2026-11-13" in undo


def test_the_summary_fits_80_columns_and_keeps_the_plain_words_ac_176_15(world):  # AC-176.15
    rows = acted(world)
    sections = parts(act(world, rows).out)
    for name in ("Done", "Next"):
        for line in sections[name]:
            assert len(line) <= 80, line
            for word in FORBIDDEN:
                assert word not in line.lower(), (word, line)


def test_the_summary_json_holds_done_next_undo_and_the_choice_ac_176_15(world):  # AC-176.15
    rows = acted(world)
    data = act(world, rows, "--json").json()
    done = {d["number"]: d for d in data["done"]}
    assert done[562]["group"].lower() == "clear" and done[562]["class"] == "bug" and done[562]["commented"] is True
    assert set(done[562]["added"]) == {"bug", "triaged", "p1"} and done[562]["removed"] == ["triage"]
    assert [(n["kind"], n["who"]) for n in data["next"]] == [("fix runs on its own", "on its own"), ("approve spec 201 (you)", "you"),
                                                             ("nothing", "nobody")]
    assert data["next"][0]["numbers"] == [560, 562] and data["next"][1]["command"] == "/component:spec approve 201"
    assert any("gh issue edit 562" in u for u in data["undo"])


def test_the_hand_over_choice_offers_the_persons_next_step_with_new_specs_ac_176_15(world):  # AC-176.15
    rows = acted(world)
    choice = act(world, rows, "--json").json()["choice"]
    assert [o["label"] for o in choice["options"]] == ["Approve the new specs now (Recommended)", "Read them first", "Later"]
    assert [o["recommended"] for o in choice["options"]] == [True, False, False] and choice["text"]


def test_without_new_specs_the_choice_is_done_or_show_the_fix_runs_ac_176_15(world):  # AC-176.15
    world.issue(1)
    world.batch()
    data = act(world, [row(1)], "--json").json()
    assert [o["label"] for o in data["choice"]["options"]] == ["Done (Recommended)", "Show the fix runs"]
    assert data["choice"]["options"][1]["command"] == "cplat dispatch status"


def test_a_row_to_explore_names_the_command_for_the_person_ac_176_15(world):  # AC-176.15
    world.issue(7)
    world.batch()
    data = act(world, [row(7, **{"class": "needs-exploring", "priority": None, "expected": None})], "--json").json()
    assert data["next"] == [{"kind": "explore #7 (you)", "who": "you", "numbers": [7], "command": "/component:explore #7"}]
    assert [o["label"] for o in data["choice"]["options"]] == ["Explore #7 now (Recommended)", "Later"]


def test_a_question_to_the_reporter_is_waiting_for_the_reporter_ac_176_15(world):  # AC-176.15
    world.issue(8)
    world.batch()
    data = act(world, [row(8, **{"class": "needs-info", "priority": None, "expected": None, "comment": "Which version?"})], "--json").json()
    assert [(n["kind"], n["who"], n["numbers"]) for n in data["next"]] == [("reporter answers", "reporter", [8])]


# ---------------- AC-176.4 publish-specs ----------------

class Seams:
    """The git and gh seams of `triage_act`: they answer like a repo on a docs branch and record every call."""

    def __init__(self, branch="docs/triage-2031-05-17", existing=()):      # a date that is not today: the title takes it from the branch
        self.branch, self.existing, self.git_calls, self.gh_calls, self.bodies = branch, list(existing), [], [], []
        self.url = f"https://github.com/{SLUG}/pull/640"

    def git(self, args, cwd=None):
        self.git_calls.append(list(args))
        if args[0] == "rev-parse" or "--show-current" in args:
            return 0, self.branch + "\n"
        if args[0] == "status":
            return 0, " M docs/specs/201-new-thing/spec.md\n"
        if args[0] == "diff" and "--quiet" in args:
            return 1, ""
        return 0, ""

    def gh(self, args, cwd=None):
        self.gh_calls.append(list(args))
        if args[:2] == ["pr", "list"]:
            head = self.flag(args, "--head", "-H")           # a build may filter on the server or match on the client
            return 0, json.dumps([p for p in self.existing if head is None or p["headRefName"] == head])
        if args[:2] == ["pr", "create"]:
            self.bodies.append(self.flag(args, "--body", "-b", file=("--body-file", "-F")))
            return 0, self.url + "\n"
        if args[:2] == ["pr", "view"]:
            return 0, json.dumps({"number": 640, "url": self.url})
        if args[:2] == ["pr", "edit"]:
            self.bodies.append(self.flag(args, "--body", "-b", file=("--body-file", "-F")))
        return 0, ""

    @staticmethod
    def flag(args, *names, file=()):
        for i, a in enumerate(args):
            if a in names and i + 1 < len(args):
                return args[i + 1]
            if a.split("=")[0] in names and "=" in a:
                return a.split("=", 1)[1]
            if a in file and i + 1 < len(args):
                return open(args[i + 1]).read()
        return None

    def calls(self, kind, name):
        return [c for c in (self.git_calls if kind == "git" else self.gh_calls) if c[:len(name)] == list(name)]


@pytest.fixture()
def seams(world, monkeypatch):
    world.spec("201-new-thing", status="draft", title="Dark mode")
    world.spec("202-other", status="draft", title="Other thing")
    world.issue(563)
    try:
        world.batch()
    except (SystemExit, core.PlatformError):     # `batch` is not there yet: the command of the test fails, not the fixture
        world.data = {"batch_file": str(world.tmp / "none.json")}
    s = Seams()
    try:
        triage_act = load("triage_act")
    except ImportError:          # the module is not there yet: the command of the test fails, not the fixture
        return s
    monkeypatch.setattr(triage_act, "git", s.git)
    monkeypatch.setattr(triage_act, "gh", s.gh)
    return s


def test_new_specs_go_out_as_one_draft_pr_on_one_docs_branch_ac_176_4(world, seams):  # AC-176.4
    res = world.run("publish-specs", "201-new-thing", "202-other")
    assert res.out.strip() == f"specs 201, 202: {seams.url}"
    [create] = seams.calls("gh", ["pr", "create"])
    assert "--draft" in create
    assert seams.flag(create, "--title") == "docs(spec): triage 2031-05-17 — specs 201, 202"
    body = seams.bodies[0]
    assert "- 201-new-thing: Dark mode" in body and "- 202-other: Other thing" in body
    assert body.rstrip().endswith("<!-- cplat:triage-specs -->") and "<!-- cplat:spec " not in body
    assert seams.flag(create, "--head", "-H") in (None, seams.branch)


def test_each_spec_is_committed_signed_off_and_pushed_without_force_ac_176_4(world, seams):  # AC-176.4
    world.run("publish-specs", "201-new-thing", "202-other")
    commits = seams.calls("git", ["commit"])
    assert len(commits) == 2 and all("-s" in c or "--signoff" in c for c in commits)
    flat = [a for c in commits for a in c]
    assert "docs(spec): 201-new-thing — Dark mode" in flat and "docs(spec): 202-other — Other thing" in flat
    pushes = seams.calls("git", ["push"])
    assert len(pushes) >= 1 and not any(a in ("-f", "--force", "--force-with-lease") or a.startswith("--force") for c in pushes for a in c)


def test_the_pr_is_written_into_the_batch_and_printed_as_json_ac_176_4(world, seams):  # AC-176.4
    data = world.run("publish-specs", "201-new-thing", "202-other", "--json").json()
    assert data == {"pr": 640, "url": seams.url, "branch": seams.branch, "specs": ["201-new-thing", "202-other"]}
    saved = json.loads(world.batch_path().read_text())
    assert saved["specs_pr"] == {"number": 640, "url": seams.url, "branch": seams.branch, "specs": ["201-new-thing", "202-other"]}


def test_an_existing_triage_pr_is_found_by_its_marker_and_branch_and_updated_ac_176_4(world, seams):  # AC-176.4
    seams.existing = [{"number": 12, "url": "u12", "headRefName": "docs/other", "body": "x\n<!-- cplat:triage-specs -->", "title": "t"},
                      {"number": 640, "url": seams.url, "headRefName": seams.branch, "body": "old\n<!-- cplat:triage-specs -->",
                       "title": "t"}]
    data = world.run("publish-specs", "201-new-thing", "--json").json()
    assert data["pr"] == 640 and seams.calls("gh", ["pr", "create"]) == []


@pytest.mark.parametrize("branch", ["main", "docs/other", "docs/triage-2026-11-1", "feature/triage-2026-11-13"])
def test_a_branch_that_is_not_a_triage_docs_branch_is_refused_ac_176_4(world, seams, branch):  # AC-176.4
    seams.branch = branch
    with pytest.raises(core.PlatformError) as err:
        world.run("publish-specs", "201-new-thing")
    assert "git checkout -b docs/triage-" in (err.value.hint or "")
    assert seams.calls("git", ["commit"]) == [] and seams.calls("git", ["push"]) == [] and seams.calls("gh", ["pr", "create"]) == []


@pytest.mark.parametrize("branch", ["docs/triage-2026-11-13", "docs/triage-2026-11-13-2"])
def test_the_dated_branch_names_are_accepted_ac_176_4(world, seams, branch):  # AC-176.4
    seams.branch = branch
    assert world.run("publish-specs", "201-new-thing", "--json").json()["branch"] == branch


def test_a_spec_that_is_not_there_is_refused_before_anything_is_committed_ac_176_4(world, seams):  # AC-176.4
    with pytest.raises(core.PlatformError):
        world.run("publish-specs", "201-new-thing", "999-missing")
    assert seams.calls("git", ["commit"]) == [] and seams.calls("gh", ["pr", "create"]) == []
