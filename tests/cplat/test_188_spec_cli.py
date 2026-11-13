"""Spec 188 acceptance tests: `cplat spec` additions for explored specs (AC-188.5 check side, AC-188.7).

`new --explored`, the `explored` field of `list --json`, `check` of the key and of the `## Notes for the architect` section, and
`discard`. Git worlds and the fake `gh` come from support_183."""
import json

import pytest

import spec
from support_183 import SPEC_TEXT, add_spec, commit_all, fake_gh, world


@pytest.fixture(autouse=True)
def no_shape(monkeypatch):
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)


def run(repo, capsys, *argv):
    capsys.readouterr()
    rc = spec.main(["--repo", str(repo), *argv])
    out = capsys.readouterr()
    return rc, out.out, out.err


def front(repo, name):
    text = (repo / "docs" / "specs" / name / "spec.md").read_text()
    return text.split("---")[1]


def rows(repo, capsys, *extra):
    rc, out, _ = run(repo, capsys, "list", "--all", "--json", *extra)
    assert rc == 0
    return {r["id"]: r for r in json.loads(out)}


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    r = world(tmp_path, main_specs=("175-base",))
    fake_gh(tmp_path, monkeypatch, prs={})
    return r


def test_new_explored_sets_the_front_matter_key_ac_188_7(repo, capsys):  # AC-188.7
    rc, out, err = run(repo, capsys, "new", "--no-shape", "--explored", "Fresh feature")
    assert rc == 0, err
    name = out.strip().splitlines()[0].split("/")[2]
    assert "explored: true" in front(repo, name).splitlines()
    rc, out, _ = run(repo, capsys, "new", "--no-shape", "Plain feature")
    assert rc == 0 and "explored" not in front(repo, out.strip().splitlines()[0].split("/")[2])


def test_explored_is_not_allowed_with_from_plan_ac_188_7(repo, capsys):  # AC-188.7
    with pytest.raises(SystemExit) as e:
        spec.main(["--repo", str(repo), "new", "--explored", "--from-plan", "p", "r"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "unrecognized arguments" not in err and "--explored" in err and "--from-plan" in err   # a refusal, not an unknown flag


def test_list_json_reports_explored_for_every_spec_ac_188_7(repo, capsys):  # AC-188.7
    run(repo, capsys, "new", "--no-shape", "--explored", "Fresh feature")
    broken = repo / "docs" / "specs" / "180-broken"
    broken.mkdir()
    (broken / "spec.md").write_text("no front matter at all\n")
    table = rows(repo, capsys)
    assert table["175-base"]["explored"] is False
    assert table["176-fresh-feature"]["explored"] is True
    assert table["180-broken"]["explored"] is False
    assert all(isinstance(r["explored"], bool) for r in table.values())
    assert all(isinstance(r["explored"], bool) for r in rows(repo, capsys, "--detail").values())


def test_check_rejects_an_explored_that_is_not_a_boolean_ac_188_7(repo, capsys):  # AC-188.7
    d = add_spec(repo, "177-odd")
    p = d / "spec.md"
    p.write_text(p.read_text().replace("status: draft\n", "status: draft\nexplored: maybe\n"))
    rc, out, err = run(repo, capsys, "check", "177-odd")
    assert rc != 0 and "spec.md: explored must be true or false" in out + err
    p.write_text(p.read_text().replace("explored: maybe", "explored: true"))
    assert run(repo, capsys, "check", "177-odd")[0] == 0


def test_discard_removes_a_never_committed_draft_ac_188_9(repo, capsys):  # AC-188.9
    run(repo, capsys, "new", "--no-shape", "--explored", "Fresh feature")
    folder = repo / "docs" / "specs" / "176-fresh-feature"
    assert folder.is_dir()
    rc, out, err = run(repo, capsys, "discard", "176-fresh-feature")
    assert rc == 0, err
    assert out.strip() == "176-fresh-feature: discarded" and not folder.exists()


def test_discard_releases_the_claims_on_the_tracked_issues_ac_188_9(repo, capsys, monkeypatch):  # AC-188.9
    import claim
    run(repo, capsys, "new", "--no-shape", "--explored", "--tracks", "5", "Fresh feature")
    calls = []
    monkeypatch.setattr(claim, "release", lambda root, issues, reason: calls.append((list(issues), reason)))
    rc, _, err = run(repo, capsys, "discard", "176-fresh-feature")
    assert rc == 0, err
    assert calls == [([5], "discarded: explore first")]


def test_discard_refuses_a_committed_or_a_non_draft_spec_ac_188_9(repo, capsys):  # AC-188.9
    rc, out, err = run(repo, capsys, "discard", "175-base")          # a draft, but committed
    assert rc == 1 and (err + out).startswith("ERROR:") and "fix:" in err + out
    assert (repo / "docs" / "specs" / "175-base").is_dir()
    d = add_spec(repo, "177-approved")
    (d / "spec.md").write_text((d / "spec.md").read_text().replace("status: draft", "status: approved"))
    rc, out, err = run(repo, capsys, "discard", "177-approved")       # never committed, but not a draft
    assert rc == 1 and "ERROR:" in err + out and d.is_dir()
    commit_all(repo)


NOTES = SPEC_TEXT.replace(
    "## Non-goals", "## Assumptions\n\n- **A1** The export is CSV. (affects AC-001.1) (decided in explore)\n\n"
    "## Notes for the architect\n\n- Use a streaming writer.\n- **AC-001.9** Given a hint, when read, then it is no criterion.\n\n"
    "## Non-goals")


def spec_of(repo, text):
    d = add_spec(repo, "177-notes", text)
    return spec.read(d)


def test_a_notes_for_the_architect_section_passes_check_ac_188_5(repo, capsys):  # AC-188.5
    spec_of(repo, NOTES.format(name="177-notes", num="177", title="Notes"))
    rc, out, err = run(repo, capsys, "check", "177-notes")
    assert rc == 0, out + err


def test_notes_bullets_are_no_criteria_and_outside_the_hash_ac_188_5(repo):  # AC-188.5
    with_notes = spec_of(repo, NOTES.format(name="177-notes", num="177", title="Notes"))
    plain = spec.Spec(with_notes.dir, with_notes.meta, with_notes.body.split("## Notes for the architect")[0] + "## Non-goals"  # interface: the section heading cplat spec splits on
                      + with_notes.body.split("## Non-goals", 1)[1])
    assert with_notes.active_acs() == ["AC-177.1"] == plain.active_acs()
    assert with_notes.ac_hash() == plain.ac_hash()
    assert "notes for the architect" in spec.sections(with_notes.body)
