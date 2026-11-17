"""#783: `cplat next` in the platform repo took 138 s: one `gh api` per spec folder for the drafts (~225 calls), one `gh pr list`
per unfinished run without a PR (85 calls), and its sources one after the other. Spec texts are now read in batched GraphQL
queries, PRs listed once per repo within `shared_reads`, and the sources asked at once."""
import json
import re
import types

import needs
import runlist

SPEC = "---\nstatus: {status}\n---\n# {name}\n"


def fake_gh(names, drafts, calls):
    def gh(args):
        calls.append(args)
        if args[:2] == ["api", "graphql"]:
            query = next(a for a in args if a.startswith("query="))
            found = re.findall(r's(\d+): object\(expression: "HEAD:docs/specs/([^/]+)/spec.md"\)', query)
            repo = {f"s{n}": {"text": SPEC.format(status="draft" if d in drafts else "approved", name=d)} for n, d in found}
            return json.dumps({"data": {"repository": repo}})
        if args[0] == "api" and args[1].endswith("/contents/docs/specs"):
            return json.dumps([{"name": n, "type": "dir"} for n in names])
        if args[:2] == ["pr", "list"]:
            return "[]"
        raise AssertionError(f"unexpected gh call {args}")
    return gh


def test_drafts_of_120_spec_folders_are_read_in_three_queries(monkeypatch):
    names = [f"{n:03d}-thing" for n in range(1, 121)]
    calls: list = []
    monkeypatch.setattr(needs, "gh", fake_gh(names, {"007-thing", "120-thing"}, calls))
    monkeypatch.setattr(needs, "_parse", lambda sid, text: types.SimpleNamespace(status=re.search(r"status: (\w+)", text)[1]))
    monkeypatch.setattr(needs, "_created", lambda parsed: None)
    found = needs._drafts("acme/shop-api")
    assert sorted(d["spec"].status for d in found) == ["draft", "draft"] and len(found) == 2
    assert len([c for c in calls if c[:2] == ["api", "graphql"]]) == 3
    assert not [c for c in calls if c[0] == "api" and c[1].endswith("/spec.md")]


def test_a_failing_query_falls_back_to_one_read_per_folder(monkeypatch):
    names = ["001-a", "002-b"]
    calls: list = []
    good = fake_gh(names, set(), calls)

    def gh(args):
        if args[:2] == ["api", "graphql"]:
            raise RuntimeError("HTTP 502")
        if args[0] == "api" and args[1].endswith("/spec.md"):
            calls.append(args)
            return SPEC.format(status="draft", name="x")
        return good(args)
    monkeypatch.setattr(needs, "gh", gh)
    monkeypatch.setattr(needs, "_created", lambda parsed: None)
    monkeypatch.setattr(needs, "_parse", lambda sid, text: types.SimpleNamespace(status="draft"))
    assert len(needs._drafts("acme/shop-api")) == 2 and len([c for c in calls if c[1].endswith("/spec.md")]) == 2


def test_within_shared_reads_a_repo_s_prs_are_listed_once(monkeypatch):
    import core
    asked: list = []

    def run(cmd, **kw):
        asked.append(cmd)
        prs = [{"number": 9, "url": "https://github.com/acme/a/pull/9", "headRefName": "feature/001-a", "state": "MERGED"},
               {"number": 8, "url": "https://github.com/acme/a/pull/8", "headRefName": "feature/002-b", "state": "OPEN"}]
        return types.SimpleNamespace(stdout=json.dumps(prs), returncode=0)
    monkeypatch.setattr(core, "run", run)
    with runlist.shared_reads():
        assert runlist.lookup_pr("acme/a", "feature/001-a", state="merged")["number"] == 9
        assert runlist.lookup_pr("acme/a", "feature/002-b")["number"] == 8
        assert runlist.lookup_pr("acme/a", "feature/002-b", state="merged") is None
        assert runlist.lookup_pr("acme/a", "feature/003-c") is None
    assert len(asked) == 1 and "--head" not in asked[0]
