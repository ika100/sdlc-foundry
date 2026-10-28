"""Spec 109 acceptance tests, remote links: the PR (AC-109.6), the release (AC-109.7), the environments (AC-109.8), unreachable
remotes (AC-109.9), the tracked issues (AC-109.10) and read-only / time (AC-109.12). Contract: docs/specs/109-*/design.md,
"Links and states" and "Remote module API".

All remote reads go through the `gh` seam of `spec_chain_remote`, replaced by chain_support.FakeGh: no network. Fixture repos
use the scratch spec 901. The new modules are imported inside the tests only."""
import importlib
import re
import time

import pytest
from chain_support import (APP_SLUG, BRANCH, ENVS, SLUG, FakeGh, build_gitops, build_world, chain, chain_text, links, pr_entry,
                           rendered)

ACS = ("AC-901.1", "AC-901.2", "AC-901.3")


def gh_with(monkeypatch, w, *, prs="m", issues=None, gitops=None, **kw):
    """A usable gh: the PR is the 'm' commit (or the given entries), the issue 164 closed, the gitops-app served."""
    entries = [pr_entry(301, w.shas["m"])] if prs == "m" else (prs or [])
    repos = {APP_SLUG: gitops} if gitops else {}
    return FakeGh(issues=issues if issues is not None else {164: "CLOSED"}, prs={BRANCH: entries}, repos=repos, **kw).install(monkeypatch)


# ---------------- AC-109.6 ----------------

def test_the_pr_is_the_merged_pr_from_the_feature_branch_ac_109_6(tmp_path, capsys, monkeypatch):  # AC-109.6
    w = build_world(tmp_path)
    gh = gh_with(monkeypatch, w)
    rc, doc = chain(capsys, w.root)
    assert rc == 0
    pr = links(doc, "AC-901.1")["pr"]
    assert pr["state"] == "ok"
    assert pr["text"] == f"#301 merged 2026-10-30 (merge {w.shas['m'][:7]})"
    assert (pr["number"], pr["merge_commit"], pr["merged_at"], pr["others"]) == (301, w.shas["m"], "2026-10-30T10:00:00Z", [])
    assert pr["url"].endswith("/pull/301")
    pr_calls = [c for c in gh.calls if c[:2] == ["pr", "list"]]
    assert pr_calls and all(c[c.index("--head") + 1] == BRANCH and "merged" in c and SLUG in c for c in pr_calls)


def test_no_merged_pr_from_the_branch_is_missing_and_ends_the_chain_ac_109_6(tmp_path, capsys, monkeypatch):  # AC-109.6
    w = build_world(tmp_path)
    gh_with(monkeypatch, w, prs=[])
    _, doc = chain(capsys, w.root)
    ls = links(doc, "AC-901.1")
    assert rendered(ls["pr"]) == f"missing: no merged PR from {BRANCH}"
    assert rendered(ls["release"]) == "n/a: no merged PR"
    assert all(rendered(ls[f"env {e}"]) == "n/a: no merged PR" for e in ENVS)


def test_several_merged_prs_show_the_newest_and_list_the_others_ac_109_6(tmp_path, capsys, monkeypatch):  # AC-109.6
    w = build_world(tmp_path)
    older = pr_entry(290, w.shas["c1"], merged_at="2026-10-20T08:00:00Z")
    newer = pr_entry(301, w.shas["m"], merged_at="2026-10-30T10:00:00Z")
    gh_with(monkeypatch, w, prs=[older, newer])        # in the wrong order on purpose
    _, doc = chain(capsys, w.root)
    pr = links(doc, "AC-901.1")["pr"]
    assert pr["state"] == "ok" and pr["number"] == 301
    assert pr["text"].endswith("; also merged: #290")
    assert pr["others"] == [290] or [o["number"] if isinstance(o, dict) else o for o in pr["others"]] == [290]


def test_a_repo_without_a_github_origin_has_an_unknown_pr_ac_109_6(tmp_path, capsys, monkeypatch):  # AC-109.6
    w = build_world(tmp_path, origin=None)
    gh_with(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    pr = links(doc, "AC-901.1")["pr"]
    assert pr["state"] == "unknown" and "no GitHub origin remote" in pr["text"]


# ---------------- AC-109.7 ----------------

def test_the_release_is_the_oldest_release_tag_containing_the_merge_commit_ac_109_7(tmp_path, capsys, monkeypatch):  # AC-109.7
    # v1.9.0 and v1.10.0 both contain the merge; the oldest is 1.9.0 by version, not by text. Pre-releases and other tags do not count.
    tags = {"v1.0.0": "c0", "v1.9.0": "later", "v1.10.0": "later2", "v1.2.0-rc1": "m", "nightly": "m"}
    w = build_world(tmp_path, tags=tags)
    gh_with(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    rel = links(doc, "AC-901.1")["release"]
    assert rel["state"] == "ok" and rel["text"] == "v1.9.0" and rel["tag"] == "v1.9.0"


def test_the_release_that_holds_the_merge_itself_counts_ac_109_7(tmp_path, capsys, monkeypatch):  # AC-109.7
    w = build_world(tmp_path)        # default tags: v1.0.0 (before), v1.1.0 (the merge), v1.2.0
    gh_with(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    assert rendered(links(doc, "AC-901.1")["release"]) == "ok: v1.1.0"


def test_a_merge_in_no_release_is_missing_ac_109_7(tmp_path, capsys, monkeypatch):  # AC-109.7
    w = build_world(tmp_path, tags={"v1.0.0": "c0", "v1.2.0-rc1": "later"})
    gh_with(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    assert rendered(links(doc, "AC-901.1")["release"]) == "missing: merged, not in a release"


def test_a_merge_commit_not_in_the_clone_is_unknown_not_missing_ac_109_7(tmp_path, capsys, monkeypatch):  # AC-109.7
    w = build_world(tmp_path)
    gh_with(monkeypatch, w, prs=[pr_entry(301, "f" * 40)])
    _, doc = chain(capsys, w.root)
    assert rendered(links(doc, "AC-901.1")["release"]) == "unknown: merge commit not fetched"


# ---------------- AC-109.8 ----------------

def _env(doc, env, ac="AC-901.1"):
    return links(doc, ac)[f"env {env}"]


def test_each_environment_shows_its_pin_and_is_judged_against_the_release_ac_109_8(tmp_path, capsys, monkeypatch):  # AC-109.8
    w = build_world(tmp_path)        # release v1.1.0
    g = build_gitops(w, {"dev": "sha-" + w.shas["m"], "staging": "1.2.0", "prod": "v1.0.0"})
    gh_with(monkeypatch, w, gitops=g)
    rc, doc = chain(capsys, w.root)
    assert rc == 0
    assert (_env(doc, "dev")["state"], _env(doc, "dev")["text"]) == ("ok", f"runs sha-{w.shas['m']}")        # a commit that contains the merge
    assert (_env(doc, "staging")["state"], _env(doc, "staging")["text"]) == ("ok", "runs 1.2.0")             # a later release
    assert rendered(_env(doc, "prod")) == "missing: runs v1.0.0, older than v1.1.0"                          # an older release
    assert _env(doc, "prod")["tag"] == "v1.0.0"


def test_a_release_pin_equal_to_the_release_is_ok_ac_109_8(tmp_path, capsys, monkeypatch):  # AC-109.8
    w = build_world(tmp_path)
    g = build_gitops(w, {"dev": "v1.1.0", "staging": "v1.1.0", "prod": "v1.1.0"})
    gh_with(monkeypatch, w, gitops=g)
    _, doc = chain(capsys, w.root)
    assert [_env(doc, e)["state"] for e in ENVS] == ["ok", "ok", "ok"]


def test_a_commit_pin_is_judged_by_whether_it_contains_the_merge_ac_109_8(tmp_path, capsys, monkeypatch):  # AC-109.8
    w = build_world(tmp_path)
    g = build_gitops(w, {"dev": "sha-" + w.shas["later"], "staging": "sha-" + w.shas["c1"], "prod": "sha-" + "a" * 40})
    gh_with(monkeypatch, w, gitops=g)
    _, doc = chain(capsys, w.root)
    assert _env(doc, "dev")["state"] == "ok"          # a descendant of the merge
    assert _env(doc, "staging")["state"] == "missing"  # an ancestor of the merge
    assert rendered(_env(doc, "prod")) == f"unknown: pinned commit {'a' * 7} not fetched"


def test_a_tag_that_is_no_release_and_no_commit_is_unknown_ac_109_8(tmp_path, capsys, monkeypatch):  # AC-109.8
    w = build_world(tmp_path)
    g = build_gitops(w, {"dev": "latest", "staging": "v1.2.0", "prod": "v1.2.0"})
    gh_with(monkeypatch, w, gitops=g)
    _, doc = chain(capsys, w.root)
    assert _env(doc, "dev")["state"] == "unknown" and "latest" in _env(doc, "dev")["text"]


def test_an_environment_without_an_instance_is_not_deployed_ac_109_8(tmp_path, capsys, monkeypatch):  # AC-109.8
    w = build_world(tmp_path)
    g = build_gitops(w, {"dev": "v1.2.0", "staging": "v1.2.0"}, environments=("dev", "staging"))
    gh_with(monkeypatch, w, gitops=g)
    _, doc = chain(capsys, w.root)
    assert rendered(_env(doc, "prod")) == "n/a: not deployed to prod"
    assert _env(doc, "dev")["state"] == "ok"


def test_a_library_has_no_environments_ac_109_8(tmp_path, capsys, monkeypatch):  # AC-109.8
    w = build_world(tmp_path, shape="library-python", linked=False)
    gh_with(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    assert all(rendered(_env(doc, e)) == "n/a: library: no environments" for e in ENVS)


def test_a_repo_not_linked_to_a_gitops_app_has_no_environments_ac_109_8(tmp_path, capsys, monkeypatch):  # AC-109.8
    w = build_world(tmp_path, linked=False)
    gh_with(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    assert all(rendered(_env(doc, e)) == "n/a: not linked to a gitops-app (no .platform-app.yml)" for e in ENVS)


def test_a_service_the_gitops_app_does_not_list_is_missing_ac_109_8(tmp_path, capsys, monkeypatch):  # AC-109.8
    w = build_world(tmp_path)
    g = build_gitops(w, {"dev": "v1.2.0"}, environments=("dev",), component="other-api", repo="acme/other-api")
    gh_with(monkeypatch, w, gitops=g)
    _, doc = chain(capsys, w.root)
    for e in ENVS:
        assert _env(doc, e)["state"] == "missing" and f"{SLUG} is not a component in {APP_SLUG}" in _env(doc, e)["text"]


def test_the_pins_come_from_the_gitops_app_default_branch_or_a_local_checkout_ac_109_8(tmp_path, monkeypatch):  # AC-109.8
    rm = importlib.import_module("spec_chain_remote")
    w = build_world(tmp_path)
    g = build_gitops(w, {"dev": "v1.2.0", "staging": "v1.1.0", "prod": "v1.0.0"})
    # gh usable: read through the seam from the default branch
    FakeGh(repos={APP_SLUG: g}).install(monkeypatch)
    pins = rm.Remote(w.root).pins([APP_SLUG], "shop-api")
    assert isinstance(pins, rm.Pins) and "default branch" in pins.source and APP_SLUG in pins.source
    assert (pins.system, pins.component) == ("shop", "shop-api")
    assert pins.tags == {"dev": "v1.2.0", "staging": "v1.1.0", "prod": "v1.0.0"}
    # gh missing: the sibling checkout whose origin is that slug
    FakeGh(installed=False).install(monkeypatch)
    pins = rm.Remote(w.root).pins([APP_SLUG], "shop-api")
    assert isinstance(pins, rm.Pins) and "local checkout" in pins.source
    assert pins.tags == {"dev": "v1.2.0", "staging": "v1.1.0", "prod": "v1.0.0"}


def test_a_gitops_app_nobody_can_reach_is_a_reason_not_pins_ac_109_8(tmp_path, monkeypatch):  # AC-109.8
    rm = importlib.import_module("spec_chain_remote")
    w = build_world(tmp_path)
    FakeGh(installed=False).install(monkeypatch)
    r = rm.Remote(w.root)
    got = r.pins([APP_SLUG], "shop-api")
    assert isinstance(got, str) and got.startswith(f"gitops-app {APP_SLUG} not reachable")
    assert any(APP_SLUG in u["what"] for u in r.unreached)


# ---------------- AC-109.9 ----------------

REMOTE_LINKS = ("issue", "pr", "release", "env dev", "env staging", "env prod")


@pytest.mark.parametrize("kw,reason", [
    ({"installed": False}, "gh not installed"),
    ({"authed": False}, "gh not authenticated"),
    ({"reachable": False}, "GitHub not reachable"),
    ({"probe_timeout": True}, "GitHub not reachable"),
])
def test_without_a_usable_gh_every_remote_link_is_unknown_and_local_links_still_work_ac_109_9(tmp_path, capsys, monkeypatch, kw, reason):  # AC-109.9
    w = build_world(tmp_path)
    gh = FakeGh(issues={164: "CLOSED"}, prs={BRANCH: [pr_entry(301, w.shas["m"])]}, **kw).install(monkeypatch)
    rc, doc = chain(capsys, w.root)
    assert rc == 0
    ls = links(doc, "AC-901.1")
    for name in REMOTE_LINKS:
        assert ls[name]["state"] == "unknown", (name, rendered(ls[name]))      # never ok, never missing
    assert reason in ls["pr"]["text"] and reason in ls["issue"]["text"]
    assert ls["tests"]["state"] == "ok" and ls["verdict"]["state"] == "ok" and ls["spec"]["state"] == "ok"   # local links are checked
    assert links(doc, "AC-901.3")["tests"]["state"] == "missing"
    assert doc["note"] and "not reached" in doc["note"] and reason in doc["note"]
    assert doc["unreached"] and doc["unreached"][0]["what"] == "gh" and reason in doc["unreached"][0]["reason"]
    assert len(gh.network_calls()) <= 1       # one probe; nothing after a failed probe


def test_the_note_is_the_last_line_and_names_what_could_not_be_reached_ac_109_9(tmp_path, capsys, monkeypatch):  # AC-109.9
    w = build_world(tmp_path)
    FakeGh(authed=False).install(monkeypatch)
    rc, out, err = chain_text(capsys, w.root)
    assert rc == 0
    lines = out.rstrip("\n").splitlines()
    assert lines[-1].startswith("note: not reached: gh (gh not authenticated)")
    assert lines[-1].endswith("; the links that need them are unknown")
    assert sum(ln.startswith("note:") for ln in lines) == 1
    assert re.search(r"summary: .*[1-9]\d* unknown", out)
    assert "unknown: gh not authenticated" in out


def test_a_gitops_app_that_cannot_be_reached_makes_only_the_environments_unknown_ac_109_9(tmp_path, capsys, monkeypatch):  # AC-109.9
    w = build_world(tmp_path)
    gh_with(monkeypatch, w)           # gh works, but serves no repository content for the gitops-app, and there is no checkout
    rc, doc = chain(capsys, w.root)
    assert rc == 0
    ls = links(doc, "AC-901.1")
    assert ls["pr"]["state"] == "ok" and ls["release"]["state"] == "ok"
    for e in ENVS:
        assert ls[f"env {e}"]["state"] == "unknown" and f"gitops-app {APP_SLUG} not reachable" in ls[f"env {e}"]["text"]
    assert APP_SLUG in doc["note"]
    assert {u["what"] for u in doc["unreached"]} >= {f"gitops-app {APP_SLUG}"} or any(APP_SLUG in u["what"] for u in doc["unreached"])


def test_with_everything_reachable_there_is_no_note_ac_109_9(tmp_path, capsys, monkeypatch):  # AC-109.9
    w = build_world(tmp_path)
    g = build_gitops(w, {"dev": "v1.2.0", "staging": "v1.2.0", "prod": "v1.2.0"})
    gh_with(monkeypatch, w, gitops=g)
    _, doc = chain(capsys, w.root)
    assert doc["note"] is None and doc["unreached"] == []
    _, out, _ = chain_text(capsys, w.root)
    assert "note:" not in out


def test_a_timed_out_call_stops_all_later_calls_ac_109_9(tmp_path, monkeypatch):  # AC-109.9
    rm = importlib.import_module("spec_chain_remote")
    w = build_world(tmp_path)
    calls = []

    def slow(args, *, cwd, timeout=10):
        calls.append(list(args))
        if args[:2] == ["auth", "token"]:
            return 0, "tok", ""
        if "rate_limit" in args:
            return 0, "{}", ""
        return 124, "", "timed out"          # the first real call times out
    monkeypatch.setattr(rm, "gh", slow)
    monkeypatch.setattr(rm, "which", lambda tool: "/usr/bin/gh")
    r = rm.Remote(w.root)
    first = r.issues([164])
    assert isinstance(first, str)
    n = len(calls)
    assert r.down() is not None and "not reachable" in r.down()
    assert isinstance(r.merged_prs(BRANCH), str)
    assert len(calls) == n                    # no further gh call in this run


# ---------------- AC-109.10 ----------------

def test_a_closed_tracked_issue_is_ok_and_shows_its_state_ac_109_10(tmp_path, capsys, monkeypatch):  # AC-109.10
    w = build_world(tmp_path)
    gh_with(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    issue = links(doc, "AC-901.1")["issue"]
    assert rendered(issue) == "ok: #164 closed"
    assert issue["issues"] == [{"number": 164, "state": "closed"}]


def test_an_open_issue_on_a_done_spec_is_stale_ac_109_10(tmp_path, capsys, monkeypatch):  # AC-109.10
    w = build_world(tmp_path, tracks=(164, 170))
    gh_with(monkeypatch, w, issues={164: "CLOSED", 170: "OPEN"})
    _, doc = chain(capsys, w.root)
    assert rendered(links(doc, "AC-901.1")["issue"]) == "stale: issue still open (#170)"


def test_an_open_issue_on_a_spec_being_built_is_just_shown_ac_109_10(tmp_path, capsys, monkeypatch):  # AC-109.10
    w = build_world(tmp_path, status="building", verification=None)
    gh_with(monkeypatch, w, issues={164: "OPEN"})
    _, doc = chain(capsys, w.root)
    assert rendered(links(doc, "AC-901.1")["issue"]) == "ok: #164 open"


def test_a_spec_without_tracks_has_no_tracked_issue_ac_109_10(tmp_path, capsys, monkeypatch):  # AC-109.10
    w = build_world(tmp_path, tracks=())
    gh = gh_with(monkeypatch, w)
    _, doc = chain(capsys, w.root)
    assert rendered(links(doc, "AC-901.1")["issue"]) == "n/a: no tracked issue"
    assert not [c for c in gh.calls if c[:2] == ["issue", "view"]]


def test_tracked_issues_without_gh_are_unknown_with_their_numbers_ac_109_10(tmp_path, capsys, monkeypatch):  # AC-109.10
    w = build_world(tmp_path)
    FakeGh(installed=False).install(monkeypatch)
    _, doc = chain(capsys, w.root)
    assert rendered(links(doc, "AC-901.1")["issue"]) == "unknown: gh not installed (#164)"


# ---------------- AC-109.12 ----------------

def _fingerprint(*dirs):
    out = {}
    for d in dirs:
        for p in sorted(d.rglob("*")):
            rel = p.relative_to(d)
            if ".git" in rel.parts:
                continue
            out[str(p)] = (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
    return out


def _refs(w):
    return (w.git("for-each-ref"), w.git("tag", "--list"), w.git("rev-parse", "HEAD"), w.git("status", "--porcelain"))


@pytest.mark.parametrize("json_out", [False, True])
def test_the_chain_changes_no_file_ref_or_tag_and_makes_only_reads_ac_109_12(tmp_path, capsys, monkeypatch, json_out):  # AC-109.12
    w = build_world(tmp_path)
    g = build_gitops(w, {"dev": "v1.2.0", "staging": "v1.1.0", "prod": "v1.0.0"})
    gh = gh_with(monkeypatch, w, gitops=g)
    before = _fingerprint(w.root, g)
    refs_before = _refs(w)
    g_before = _fingerprint(g)
    assert refs_before[3] == ""            # the fixture is clean, so any later change shows
    time.sleep(0.05)
    if json_out:
        chain(capsys, w.root)
    else:
        chain_text(capsys, w.root)
    assert gh.calls, "the fixture must make the chain use gh"
    assert gh.only_reads(), gh.calls
    assert _fingerprint(w.root, g) == before        # no file created, removed, rewritten or touched (content and mtime)
    assert _refs(w) == refs_before
    assert _fingerprint(g) == g_before


def test_a_run_without_any_remote_access_changes_nothing_either_ac_109_12(tmp_path, capsys, monkeypatch):  # AC-109.12
    w = build_world(tmp_path)
    FakeGh(installed=False).install(monkeypatch)
    before, refs_before = _fingerprint(w.root), _refs(w)
    chain_text(capsys, w.root)
    assert _fingerprint(w.root) == before and _refs(w) == refs_before


def test_offline_with_100_specs_it_finishes_within_30_seconds_ac_109_12(tmp_path, capsys, monkeypatch):  # AC-109.12
    w = build_world(tmp_path, extra_specs=100)
    gh = FakeGh(reachable=False, authed=True).install(monkeypatch)       # installed and authenticated, but the network is down
    start = time.monotonic()
    rc, doc = chain(capsys, w.root)
    elapsed = time.monotonic() - start
    assert rc == 0 and elapsed < 30, elapsed
    assert len(gh.network_calls()) == 1          # exactly one network attempt (the probe)
    assert links(doc, "AC-901.1")["tests"]["state"] == "ok"
    assert links(doc, "AC-901.1")["pr"]["state"] == "unknown"


def test_without_gh_at_all_100_specs_make_no_remote_call_ac_109_12(tmp_path, capsys, monkeypatch):  # AC-109.12
    w = build_world(tmp_path, extra_specs=100)
    gh = FakeGh(installed=False).install(monkeypatch)
    start = time.monotonic()
    rc, _ = chain(capsys, w.root)
    assert rc == 0 and time.monotonic() - start < 30
    assert gh.calls == []
