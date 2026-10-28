"""Spec 109 acceptance tests, local links: the chain output (AC-109.1), the status table (AC-109.2), orphan tests in the chain
(AC-109.3), the verdict links (AC-109.4, AC-109.5) and the exit code (AC-109.11). Contract: docs/specs/109-*/design.md.

Fixture repos use the scratch spec 901 (see chain_support). `spec_chain` / `spec_chain_remote` do not exist before the feature;
they are reached through the verb and the FakeGh seam, never imported at module level."""
import json
import re

import pytest
from chain_support import (LINKS, SPEC_ID, FakeGh, block_ids, build_world, chain, chain_text, links, pr_entry, rendered,
                           run_cplat)

import cplat

LINE = re.compile(r"^  (\S.{0,11}?)\s+(ok|missing|stale|unknown|n/a): (.*)$")


def up(monkeypatch, w=None, **kw):
    """gh usable; the tracked issue is closed; the merged PR is the 'm' commit when a world is given."""
    prs = {f"feature/{SPEC_ID}": [pr_entry(301, w.shas["m"])]} if w else {}
    return FakeGh(issues={164: "CLOSED"}, prs=prs, **kw).install(monkeypatch)


# ---------------- AC-109.1 ----------------

def test_the_chain_prints_one_block_per_active_criterion_with_every_link_ac_109_1(tmp_path, capsys, monkeypatch):  # AC-109.1
    w = build_world(tmp_path)
    up(monkeypatch, w)
    rc, out, err = chain_text(capsys, w.root)
    assert rc == 0, err
    lines = out.splitlines()
    assert lines[0] == f"chain: {SPEC_ID} (done, verification: pass)"
    blocks = [i for i, ln in enumerate(lines) if re.fullmatch(r"AC-901\.\d+", ln)]
    assert [lines[i] for i in blocks] == ["AC-901.1", "AC-901.2", "AC-901.3"]   # active ones only, in spec order (not the withdrawn .4)
    for i in blocks:
        names = []
        for ln in lines[i + 1:i + 1 + len(LINKS)]:
            m = LINE.match(ln)
            assert m, f"not a link line: {ln!r}"
            names.append(m.group(1))
            assert ln[2:14] == m.group(1).ljust(12)          # the name is left-justified to 12 characters
        assert names == LINKS
    assert any(re.fullmatch(r"summary: \d+/3 criteria have a complete chain .*", ln) for ln in lines), out
    assert "missing or stale:" in out
    assert "orphan tests:" in out


def test_the_summary_counts_complete_criteria_and_lists_every_missing_or_stale_link_ac_109_1(tmp_path, capsys, monkeypatch):  # AC-109.1
    w = build_world(tmp_path)
    up(monkeypatch, w)
    rc, doc = chain(capsys, w.root)
    assert rc == 0
    gaps = {(g["criterion"], g["link"], g["state"]) for g in doc["gaps"]}
    assert ("AC-901.3", "tests", "missing") in gaps       # no test names AC-901.3
    expected = {(c["id"], link["link"], link["state"]) for c in doc["criteria"] for link in c["links"] if link["state"] in {"missing", "stale"}}
    assert gaps == expected
    complete = [c for c in doc["criteria"] if c["complete"]]
    assert doc["summary"]["criteria"] == 3 and doc["summary"]["complete"] == len(complete)
    for c in doc["criteria"]:        # complete = every link ok or n/a
        assert c["complete"] == all(link["state"] in {"ok", "n/a"} for link in c["links"])
    assert not [c for c in doc["criteria"] if c["id"] == "AC-901.3"][0]["complete"]
    _, text, _ = chain_text(capsys, w.root)
    tail = text.split("missing or stale:")[1]
    assert "AC-901.3 tests: missing: no test names it" in tail


def test_json_prints_one_document_with_the_contract_keys_ac_109_1(tmp_path, capsys, monkeypatch):  # AC-109.1
    w = build_world(tmp_path)
    up(monkeypatch, w)
    rc, out, err = run_cplat(capsys, w.root, "trace", "901", "--chain", "--json")
    assert rc == 0, err
    doc = json.loads(out)       # one JSON document, nothing else on stdout
    assert {"spec", "status", "verification", "repo", "criteria", "summary", "gaps", "orphans", "unreached", "note"} <= set(doc)
    assert doc["spec"] == SPEC_ID and doc["status"] == "done" and doc["verification"] == "pass"
    assert doc["repo"] == "acme/shop-api"
    assert block_ids(doc) == ["AC-901.1", "AC-901.2", "AC-901.3"]
    for c in doc["criteria"]:
        assert [link["link"] for link in c["links"]] == LINKS
        assert all({"link", "state", "text"} <= set(link) for link in c["links"])
        assert all(link["state"] in {"ok", "missing", "stale", "unknown", "n/a"} for link in c["links"])
    assert {"criteria", "complete", "missing", "stale", "unknown"} <= set(doc["summary"])
    ids = links(doc, "AC-901.1")
    assert ids["spec"]["state"] == "ok" and ids["spec"]["text"] == "done"
    assert ids["criterion"]["text"] == "AC-901.1"
    assert ids["tests"]["files"] == ["tests/test_demo.py"]


def test_the_chain_is_a_flag_and_plain_trace_keeps_its_output_and_exit_code_ac_109_1(tmp_path, capsys, monkeypatch):  # AC-109.1
    w = build_world(tmp_path, orphan_tests=False)
    rc, out, _ = run_cplat(capsys, w.root, "trace", "901")
    assert rc == 1       # AC-901.3 is not named by any test: the exit code `cplat ship` reads
    assert out == ("ok   AC-901.1  tests/test_demo.py\nok   AC-901.2  tests/test_demo.py\nMISS AC-901.3  (no test names it)\n"
                   "2/3 criteria traced to tests\n")
    rc, out, _ = run_cplat(capsys, w.root, "trace", "901", "--json")
    assert rc == 1 and set(json.loads(out)) == {"spec", "criteria", "missing"}
    # ... and the same verb with the flag prints the chain and exits 0 whatever is missing
    up(monkeypatch, w)
    rc, out, _ = run_cplat(capsys, w.root, "trace", "901", "--chain")
    assert rc == 0 and out.startswith("chain: ")


# ---------------- AC-109.2 ----------------

@pytest.mark.parametrize("status,tests3,later", [
    ("draft", "n/a", "spec not yet built"),
    ("approved", "missing", "spec not yet built"),
    ("building", "missing", "spec not yet done"),
])
def test_links_that_cannot_exist_yet_are_not_applicable_ac_109_2(tmp_path, capsys, monkeypatch, status, tests3, later):  # AC-109.2
    w = build_world(tmp_path, status=status, verification=None)
    up(monkeypatch, w)
    rc, doc = chain(capsys, w.root)
    assert rc == 0
    for ac in ("AC-901.1", "AC-901.2", "AC-901.3"):
        ls = links(doc, ac)
        for name in ("verdict", "pr", "release", "env dev", "env staging", "env prod"):
            assert rendered(ls[name]) == f"n/a: {later}", (ac, name)
        assert ls["spec"]["text"] == status
    assert links(doc, "AC-901.1")["tests"]["state"] == "ok"
    assert links(doc, "AC-901.3")["tests"]["state"] == tests3
    if tests3 == "missing":
        assert links(doc, "AC-901.3")["tests"]["text"] == "no test names it"


def test_a_pre_done_spec_asks_github_for_no_pr_ac_109_2(tmp_path, capsys, monkeypatch):  # AC-109.2
    w = build_world(tmp_path, status="building", verification=None)
    gh = up(monkeypatch, w)
    chain(capsys, w.root)
    assert not [c for c in gh.calls if c[:2] == ["pr", "list"]]


# ---------------- AC-109.3 ----------------

def test_tests_naming_a_withdrawn_or_unknown_id_are_listed_as_stale_orphans_ac_109_3(tmp_path, capsys, monkeypatch):  # AC-109.3
    w = build_world(tmp_path)
    up(monkeypatch, w)
    rc, doc = chain(capsys, w.root)
    assert rc == 0
    got = {(o["file"], o["id"]): o for o in doc["orphans"]}
    assert set(got) == {("tests/test_orphans.py", "AC-901.4"), ("tests/test_orphans.py", "AC-901.9")}   # AC-777.1 matches no spec here
    assert got[("tests/test_orphans.py", "AC-901.4")]["kind"] == "withdrawn"
    assert got[("tests/test_orphans.py", "AC-901.9")]["kind"] == "unknown"
    assert all(o["state"] == "stale" for o in doc["orphans"])
    assert got[("tests/test_orphans.py", "AC-901.4")]["text"] == "names withdrawn AC-901.4"
    assert got[("tests/test_orphans.py", "AC-901.9")]["text"] == "names unknown AC-901.9"
    _, text, _ = chain_text(capsys, w.root)
    tail = text.split("orphan tests:")[1]
    assert "tests/test_orphans.py AC-901.4: stale: names withdrawn AC-901.4" in tail
    assert "tests/test_orphans.py AC-901.9: stale: names unknown AC-901.9" in tail
    assert "AC-777" not in text


def test_without_orphans_the_list_says_none_ac_109_3(tmp_path, capsys, monkeypatch):  # AC-109.3
    w = build_world(tmp_path, orphan_tests=False)
    up(monkeypatch, w)
    _, text, _ = chain_text(capsys, w.root)
    assert "orphan tests: none" in text
    _, doc = chain(capsys, w.root)
    assert doc["orphans"] == []


# ---------------- AC-109.4 ----------------

def test_the_verdict_comes_from_the_criterions_row_ac_109_4(tmp_path, capsys, monkeypatch):  # AC-109.4
    rows = [("AC-901.1", "met (cluster part pending CI)"), ("AC-901.2", "partial (smoke missing)")]
    w = build_world(tmp_path, rows=rows)
    up(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    v1, v2, v3 = (links(doc, f"AC-901.{n}")["verdict"] for n in (1, 2, 3))
    assert v1["state"] == "ok" and v1["text"].startswith("met") and "cluster part pending CI" in v1["text"]
    assert v1["verdict"] == "met"
    assert v2["state"] == "missing" and "partial" in v2["text"] and v2["verdict"] == "partial"
    assert v3["state"] == "missing" and v3["text"] == "not verified"


def test_a_not_met_row_is_missing_with_the_verdict_ac_109_4(tmp_path, capsys, monkeypatch):  # AC-109.4
    w = build_world(tmp_path, rows=[("AC-901.1", "**not met**"), ("AC-901.2", "`met`"), ("AC-901.3", "met")], verification="fail")
    up(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    v = links(doc, "AC-901.1")["verdict"]
    assert v["state"] == "missing" and "not met" in v["text"] and v["verdict"] == "not met"
    assert links(doc, "AC-901.2")["verdict"]["state"] == "ok"      # backticks and emphasis do not matter
    assert doc["verification"] == "fail"


@pytest.mark.parametrize("cols", [3, 5])
def test_both_table_shapes_in_use_are_read_ac_109_4(tmp_path, capsys, monkeypatch, cols):  # AC-109.4
    rows = [("AC-901.1 (amended)", "met"), ("AC-901.2", "met"), ("AC-901.3", "not met")]
    w = build_world(tmp_path, rows=rows, cols=cols)
    up(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    assert links(doc, "AC-901.1")["verdict"]["state"] == "ok"      # `AC-901.1 (amended)` reads as AC-901.1
    assert links(doc, "AC-901.3")["verdict"]["state"] == "missing"


def test_the_first_row_of_an_id_wins_ac_109_4(tmp_path, capsys, monkeypatch):  # AC-109.4
    rows = [("AC-901.1", "not met"), ("AC-901.1", "met"), ("AC-901.2", "met"), ("AC-901.3", "met")]
    w = build_world(tmp_path, rows=rows)
    up(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    assert links(doc, "AC-901.1")["verdict"]["state"] == "missing"


def test_a_done_spec_without_verification_shows_the_recorded_reason_on_every_verdict_ac_109_4(tmp_path, capsys, monkeypatch):  # AC-109.4
    w = build_world(tmp_path, verification=None, changelog="- 2026-10-02 done: unverified: no cluster to test against\n")
    up(monkeypatch, w)
    rc, doc = chain(capsys, w.root)
    assert rc == 0
    assert doc["verification"] == "none"
    for ac in ("AC-901.1", "AC-901.2", "AC-901.3"):
        v = links(doc, ac)["verdict"]
        assert v["state"] == "missing"
        assert "no cluster to test against" in v["text"] and v["text"].startswith("no verification.md")


# ---------------- AC-109.5 ----------------

def test_a_verification_older_than_the_criteria_makes_every_verdict_stale_ac_109_5(tmp_path, capsys, monkeypatch):  # AC-109.5
    w = build_world(tmp_path)
    p = w.spec_dir / "spec.md"
    p.write_text(p.read_text().replace("Given d, when e, then f.", "Given d, when e, then something else."))
    w.commit("change AC-901.2")
    changed = w.short_of_last_commit_touching(f"docs/specs/{SPEC_ID}/spec.md")
    up(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    for ac in ("AC-901.1", "AC-901.2", "AC-901.3"):
        v = links(doc, ac)["verdict"]
        assert v["state"] == "stale", ac
        assert v["text"] == f"criteria changed after verification ({changed})"


def test_criteria_changed_in_the_working_tree_read_uncommitted_ac_109_5(tmp_path, capsys, monkeypatch):  # AC-109.5
    w = build_world(tmp_path)
    p = w.spec_dir / "spec.md"
    p.write_text(p.read_text().replace("Given g, when h, then i.", "Given g, when h, then j."))
    up(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    v = links(doc, "AC-901.1")["verdict"]
    assert v["state"] == "stale" and v["text"] == "criteria changed after verification (uncommitted)"


def test_a_change_outside_the_criteria_does_not_make_the_verification_stale_ac_109_5(tmp_path, capsys, monkeypatch):  # AC-109.5
    w = build_world(tmp_path)
    p = w.spec_dir / "spec.md"
    p.write_text(p.read_text().replace("Something.", "Something else entirely.").replace("- Nothing", "- Nothing at all"))
    w.commit("reword the problem")
    up(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    assert all(links(doc, ac)["verdict"]["state"] == "ok" for ac in ("AC-901.1", "AC-901.2", "AC-901.3"))


@pytest.mark.parametrize("row,text", [("AC-901.4", "verified a withdrawn criterion"), ("AC-901.9", "verified an unknown criterion")])
def test_a_row_for_an_id_that_is_no_longer_a_criterion_makes_it_stale_ac_109_5(tmp_path, capsys, monkeypatch, row, text):  # AC-109.5
    rows = [("AC-901.1", "met"), ("AC-901.2", "met"), ("AC-901.3", "met"), (row, "met")]
    w = build_world(tmp_path, rows=rows)
    up(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    for ac in ("AC-901.1", "AC-901.2", "AC-901.3"):
        v = links(doc, ac)["verdict"]
        assert v["state"] == "stale" and v["text"] == f"{text} ({row})"


# ---------------- AC-109.11 ----------------

def test_the_exit_code_is_zero_whatever_the_links_are_and_there_is_no_strict_ac_109_11(tmp_path, capsys, monkeypatch):  # AC-109.11
    w = build_world(tmp_path, verification=None)
    FakeGh(installed=False).install(monkeypatch)      # unknown, missing and stale links at once
    rc, out, err = chain_text(capsys, w.root)
    assert rc == 0 and err == ""
    assert "missing" in out and "unknown" in out
    with pytest.raises(SystemExit) as exc:             # there is no option that turns links into a failure
        cplat.main(["spec", "--repo", str(w.root), "trace", "901", "--chain", "--strict"])
    assert exc.value.code == 2


def test_a_spec_that_cannot_be_found_fails_naming_it_ac_109_11(tmp_path, capsys):  # AC-109.11
    w = build_world(tmp_path)
    rc, out, err = run_cplat(capsys, w.root, "trace", "999", "--chain")
    assert rc == 1 and out == ""
    assert "999" in err and err.startswith("ERROR: no single spec matches '999'")


def test_a_spec_that_cannot_be_read_fails_naming_it_ac_109_11(tmp_path, capsys):  # AC-109.11
    w = build_world(tmp_path)
    broken = w.root / "docs" / "specs" / "902-broken"
    broken.mkdir()
    (broken / "spec.md").write_text("no front matter here\n")
    rc, out, err = run_cplat(capsys, w.root, "trace", "902", "--chain")
    assert rc == 1 and out == ""
    assert "902-broken" in err


def test_a_resolver_that_raises_turns_into_an_unknown_link_not_a_crash_ac_109_11(tmp_path, capsys, monkeypatch):  # AC-109.11
    import spec_chain_remote
    w = build_world(tmp_path)
    up(monkeypatch, w)

    def boom(self, branch):
        raise RuntimeError("boom")
    monkeypatch.setattr(spec_chain_remote.Remote, "merged_prs", boom)
    rc, doc = chain(capsys, w.root)
    assert rc == 0
    pr = links(doc, "AC-901.1")["pr"]
    assert pr["state"] == "unknown" and pr["text"] == "RuntimeError: boom"
    assert links(doc, "AC-901.1")["tests"]["state"] == "ok"        # the other links are still resolved
