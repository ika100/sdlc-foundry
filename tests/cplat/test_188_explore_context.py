"""Spec 188 acceptance tests: `cplat explore context "<topic>" --json` (AC-188.2).

Contract: design.md, section `cplat explore context`. A tmp repo with specs, ADRs and a fake `gh` on PATH; the command runs
through `cplat.main`, so a missing command fails the test that needs it, never the collection."""
import json
import os
import stat

import pytest

import cplat
import waiting
from system_fixtures import write_system

SPEC = """---
spec_id: {name}
title: {title}
status: {status}
priority: P1
tracks: {tracks}
---

# {num}

## Problem

Something.

## Acceptance criteria

- **AC-{num}.1** {criterion}
- ~~**AC-{num}.2**~~ withdrawn: {withdrawn}

## Non-goals

- None

## Open questions

None.

## Changelog

- 2026-11-01 created
"""
ISSUES = [{"number": 11, "title": "Export invoices as CSV"}, {"number": 12, "title": "Unrelated crash"}]


def add_spec(root, name, title, criterion="Given a thing, when it runs, then it works.", status="approved", tracks="[]",
             withdrawn="nothing"):
    d = root / "docs" / "specs" / name
    d.mkdir(parents=True)
    (d / "spec.md").write_text(SPEC.format(name=name, num=name[:3], title=title, criterion=criterion, status=status, tracks=tracks,
                                           withdrawn=withdrawn))


def add_adr(root, number, title, status="Accepted"):
    d = root / "docs" / "adr"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{number:03d}-x.md").write_text(f"# ADR-{number:03d}: {title}\n\n**Status:** {status}\n\nBody.\n")


def fake_gh(tmp_path, monkeypatch, *, issues=None, views=None, fail=False):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    views = views or {}
    cases = "".join(f"    {n}) cat <<'EOF'\n{json.dumps(v)}\nEOF\n;;\n" for n, v in views.items())
    body = "#!/bin/sh\nexit 1\n" if fail else (
        "#!/bin/sh\nif [ \"$1 $2\" = \"issue list\" ]; then cat <<'EOF'\n" + json.dumps(issues or []) + "\nEOF\nexit 0; fi\n"
        "if [ \"$1 $2\" = \"issue view\" ]; then case \"$3\" in\n" + cases + "  esac; exit 0; fi\nexit 1\n")
    script = bin_dir / "gh"
    script.write_text(waiting.with_prelude(body))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".platform-settings.yml").write_text("shape: platform\n")
    for d in ("src", "docs", "tests", ".github", "node_modules", "vendor"):
        (root / d).mkdir()
    add_spec(root, "001-csv-export", "Export invoices", "Given an invoice, when exported, then a CSV file is produced.")
    add_spec(root, "002-login", "Login page", "Given a user, when logging in, then a session starts.", status="done")
    add_spec(root, "003-reports", "Weekly reports", "Given a week, when it ends, then a report is mailed.", tracks="[11]",
             withdrawn="CSV dumps are out")
    add_adr(root, 5, "Use CSV for exports")
    add_adr(root, 6, "Pick a database")
    fake_gh(tmp_path, monkeypatch, issues=ISSUES, views={11: {"number": 11, "title": "Export invoices as CSV", "body": "Please.",
                                                              "state": "OPEN"}})
    return root


def context(capsys, root, *topic, extra=()):
    capsys.readouterr()
    rc = cplat.main(["explore", "context", *topic, "--json", "--repo", str(root), *extra])
    out = capsys.readouterr()
    return rc, out.out, out.err


def ok(capsys, root, *topic, extra=()):
    rc, out, err = context(capsys, root, *topic, extra=extra)
    assert rc == 0, err
    return json.loads(out)


def test_context_has_shape_project_map_specs_issues_adrs_ac_188_2(repo, capsys):  # AC-188.2
    data = ok(capsys, repo, "CSV", "export")
    assert data["shape"] == "platform" and data["topic"] == "CSV export"
    assert data["project_map"] == ["docs/", "src/", "tests/"]       # sorted, no dot dirs, no vendored dirs
    assert [s["id"] for s in data["specs"]][0] == "001-csv-export"
    assert set(data["specs"][0]) == {"id", "title", "status"} and data["specs"][0]["status"] == "approved"
    assert data["issues"] == [{"number": 11, "title": "Export invoices as CSV"}]
    assert data["adrs"] == [{"number": 5, "title": "Use CSV for exports", "status": "Accepted"}]
    assert data["warnings"] == [] and "components" not in data and "resources" not in data and "apis" not in data


def test_specs_match_criteria_text_and_tracks_but_not_withdrawn_ac_188_2(repo, capsys):  # AC-188.2
    assert [s["id"] for s in ok(capsys, repo, "mailed")["specs"]] == ["003-reports"]          # an active criterion's word
    assert ok(capsys, repo, "dumps")["specs"] == []                                          # a withdrawn criterion's word
    assert "003-reports" in [s["id"] for s in ok(capsys, repo, "#11")["specs"]]              # tracks: [11]


def test_a_topic_that_matches_nothing_gives_empty_lists_ac_188_2(repo, capsys):  # AC-188.2
    data = ok(capsys, repo, "zebra", "quantum")
    assert data["specs"] == [] and data["issues"] == [] and data["adrs"] == []


def test_matching_is_whole_words_ranked_and_limited_ac_188_2(repo, capsys):  # AC-188.2
    assert ok(capsys, repo, "the", "and")["specs"] == []                    # stop words and short words are no topic words
    assert ok(capsys, repo, "expor")["specs"] == []                          # whole words only
    for n in range(10, 22):
        add_spec(repo, f"{n:03d}-more-{n}", f"More csv {n}")
    ids = [s["id"] for s in ok(capsys, repo, "csv", "invoice")["specs"]]
    assert len(ids) == 10 and ids[0] == "001-csv-export"                     # two words matched first, then newest first
    assert ids[1:] == sorted(ids[1:], reverse=True)


def test_an_issue_token_adds_the_topic_issue_ac_188_2(repo, capsys):  # AC-188.2
    data = ok(capsys, repo, "#11")
    [t] = data["topic_issues"]
    assert t["number"] == 11 and t["state"] == "OPEN" and "untrusted issue text" in t["body"]
    assert {"number": 11, "title": "Export invoices as CSV"} in data["issues"]               # its title words join the topic


def test_an_empty_topic_exits_2_with_a_usage_line_ac_188_2(repo, capsys):  # AC-188.2
    for topic in ((), ("  ",)):
        rc, out, err = context(capsys, repo, *topic)
        assert rc == 2 and out == "" and err.strip() == 'usage: cplat explore context "<topic>" [--json]'


def test_a_failing_gh_warns_and_still_exits_0_ac_188_2(repo, tmp_path, monkeypatch, capsys):  # AC-188.2
    fake_gh(tmp_path, monkeypatch, fail=True)
    data = ok(capsys, repo, "csv")
    assert data["issues"] == [] and data["topic_issues"] == []
    [w] = data["warnings"]
    assert w.startswith("open issues not read: ") and [s["id"] for s in data["specs"]] == ["001-csv-export"]


def test_context_without_json_prints_sections_ac_188_2(repo, capsys):  # AC-188.2
    capsys.readouterr()
    assert cplat.main(["explore", "context", "zebra", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    for head in ("shape:", "project map:", "specs:", "issues:", "adrs:"):
        assert head in out
    assert "none" in out


def gitops(root, systems=("shop",)):
    for name in systems:
        doc = {"system": name, "owner": "acme", "environments": {"dev": {}},
               "components": {"api": {"type": "service", "lang": "python", "provides": ["orders"]},
                              "web": {"type": "website", "lang": "typescript", "consumes": ["orders"]}},
               "resources": {"db": {"type": "database"}}, "apis": {"orders": {"type": "rest"}}}
        d = write_system(root, doc, name)
        (d / "applicationset.yaml").write_text("kind: ApplicationSet\n")


def test_a_gitops_app_repo_adds_components_resources_and_apis_ac_188_2(tmp_path, monkeypatch, capsys):  # AC-188.2
    root = tmp_path / "ops"
    root.mkdir()
    gitops(root)
    fake_gh(tmp_path, monkeypatch, issues=[])
    data = ok(capsys, root, "zebra")
    assert data["shape"] == "gitops-app" and data["system"] == "shop"
    assert data["components"] == [{"name": "api", "type": "service", "lang": "python"},
                                  {"name": "web", "type": "website", "lang": "typescript"}]
    assert data["resources"] == [{"name": "db", "type": "database"}]
    assert data["apis"] == [{"name": "orders", "type": "rest", "provider": "api", "consumers": ["web"]}]


def test_several_systems_need_system_ac_188_2(tmp_path, monkeypatch, capsys):  # AC-188.2
    root = tmp_path / "ops"
    root.mkdir()
    gitops(root, ("shop", "blog"))
    fake_gh(tmp_path, monkeypatch, issues=[])
    rc, _, err = context(capsys, root, "zebra")
    assert rc == 1 and err.startswith("ERROR:") and "fix: pass --system NAME" in err
    assert ok(capsys, root, "zebra", extra=("--system", "blog"))["system"] == "blog"
