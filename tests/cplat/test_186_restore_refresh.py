"""Spec 186 acceptance tests: a restore or discard asks Argo CD for one refresh once its PR has merged (AC-186.9).

Seams: the restore world of spec 117 (`test_backup_117_restore`: a committed gitops checkout, `FakeKube` behind `backupstate.kubectl`, the
scripted clock), `gitops.open_pr` and `pr.wait` (replaced: the PR merges at once) and an Argo CD application of the fake cluster that
reports the checkout's head as its synced revision.
"""
import json

import gitops
from backup_fixtures import argo_app, cnpg_cluster, clock, kube  # noqa: F401  (fixtures)
from test_backup_117_restore import head_of, restore, switch_world, window
from test_backup_117_restore import repo  # noqa: F401  (fixture)

APP = "addon-orders-db-dev"
REFRESH = "argocd.argoproj.io/refresh=normal"


def merged_pr(monkeypatch, kube):
    """The PR opens and merges; the number of kubectl calls made by then is kept, so that what comes after it can be told."""
    import pr
    seen = {"calls_at_merge": None, "waits": 0}
    monkeypatch.setattr(gitops, "open_pr", lambda r, branch, title, body: "https://github.com/acme/shop-gitops/pull/7")

    def wait(*a, **k):
        seen["waits"] += 1
        seen["calls_at_merge"] = len(kube.calls)
        return True, ["GREEN", "merged"]
    monkeypatch.setattr(pr, "wait", wait)
    return seen


ARGO_KIND = "applications.argoproj.io"   # a kubectl resource kind, compared as a whole argument


def annotations(kube):
    return [(i, args) for i, (args, _, _) in enumerate(kube.calls) if "annotate" in args and REFRESH in args]


def app_reads(kube, after):
    return [i for i, (args, _, _) in enumerate(kube.calls) if i > after and args[:1] == ["get"] and args.count(ARGO_KIND) > 0]


def restore_world(repo, kube, monkeypatch):
    seen = merged_pr(monkeypatch, kube)
    window(kube)
    kube.put("application", argo_app(APP, revision=head_of(repo)))
    kube.put("cluster", cnpg_cluster("shop-orders-db-g1"))
    return seen


def test_a_restore_asks_argo_cd_once_for_a_refresh_right_after_the_merge_ac_186_9(repo, kube, capsys, clock, monkeypatch):  # AC-186.9
    seen = restore_world(repo, kube, monkeypatch)
    rc, out = restore(repo, capsys, "--to", "2026-10-27T09:59:00Z", "--json")
    assert rc == 0, out
    asked = annotations(kube)
    assert len(asked) == 1, [a for _, a in asked]
    i, args = asked[0]
    assert APP in args and args.count(ARGO_KIND) == 1 and REFRESH in args and "--overwrite" in args and "argocd" in args
    assert "hard" not in " ".join(args)                                    # a normal refresh, not a hard one
    assert i >= seen["calls_at_merge"]                                     # after the PR merged, never before
    assert app_reads(kube, i), "the wait for the app's revision goes on after the request"
    did = json.loads(out[out.index("{"):])["did"]
    assert f"asked Argo CD to refresh {APP} now" in did


def test_a_discard_asks_argo_cd_once_for_a_refresh_right_after_the_merge_ac_186_9(repo, kube, capsys, clock, monkeypatch):  # AC-186.9
    seen = merged_pr(monkeypatch, kube)
    switch_world(repo, kube)
    kube.put("application", argo_app(APP, revision=head_of(repo)))
    rc, out = restore(repo, capsys, "--discard")
    assert rc == 0, out
    asked = annotations(kube)
    assert len(asked) == 1 and APP in asked[0][1] and REFRESH in asked[0][1]
    assert asked[0][0] >= seen["calls_at_merge"] and app_reads(kube, asked[0][0])


def test_a_refresh_request_that_fails_is_one_line_and_the_wait_goes_on_ac_186_9(repo, kube, capsys, clock, monkeypatch):  # AC-186.9
    restore_world(repo, kube, monkeypatch)
    kube.hooks.append(lambda args, stdin: (1, "", "forbidden: cannot annotate applications") if "annotate" in args else None)
    rc, out = restore(repo, capsys, "--to", "2026-10-27T09:59:00Z", "--json")
    assert rc == 0, out                                                    # the wait found the revision, as before
    did = json.loads(out[out.index("{"):])["did"]
    (line,) = [d for d in did if d.startswith("could not ask Argo CD to refresh")]
    assert APP in line and "forbidden" in line and line.endswith("waiting for its poll") and "\n" not in line
    assert not [d for d in did if d.startswith("asked Argo CD to refresh")]
    assert len(annotations(kube)) == 1                                     # one request, not a retry loop
