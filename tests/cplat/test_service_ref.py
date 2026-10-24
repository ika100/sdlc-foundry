"""Spec 098: `cplat ship gitops pr` writes the Service-ref marker (AC-098.1, AC-098.2); `cplat doctor` checks the
SERVICE_REPOS_READ_TOKEN secret of a gitops-app (AC-098.16)."""
import json
import re
import subprocess

import pytest

import doctor
import ship
import spec
from test_ship import git, repo  # noqa: F401  (repo is a fixture)
from test_ship_checks import GITOPS, gh, gitops_plan  # noqa: F401  (gh is a fixture)

MARKER = re.compile(r"^\s*service-ref\s*:", re.I | re.M)


def _ready(repo):
    gitops_plan(repo)
    ship.start(repo, "7", True)
    d = ship.gitops_prepare(repo, "g1")
    (d / "x.yaml").write_text("a: 1\n")
    git(d, "add", "-A")
    git(d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")
    return d


def _ref(repo):
    return f"acme/shop-api@{ship.load_state(repo)['branch']}"


def _body_files(gh, verb):
    """The contents of the --body-file of every `pr <verb>` call, read now."""
    from pathlib import Path
    return [Path(c[c.index("--body-file") + 1]).read_text() for c in gh.calls if c[:2] == ["pr", verb] and "--body-file" in c]


def _reuse(monkeypatch, gh, body):
    real = ship.gh

    def fake(args, *, cwd, check=True):
        if args[:2] == ["pr", "list"] and "-R" in args and GITOPS in args:
            gh.calls.append(args)
            assert "body" in args[args.index("--json") + 1].split(",")
            return json.dumps([{"number": 3, "url": f"https://github.com/{GITOPS}/pull/3", "body": body}])
        if args[:2] == ["pr", "edit"]:
            gh.calls.append(args)
            from pathlib import Path
            gh.edits.append((args, Path(args[args.index("--body-file") + 1]).read_text()))
            return ""
        return real(args, cwd=cwd, check=check)

    gh.edits = []
    monkeypatch.setattr(ship, "gh", fake)


def test_ac_098_1_with_service_ref_is_pure_and_idempotent():
    """AC-098.1: exactly one marker; candidates replaced by the marker in the first one's place, others kept."""
    ref = "acme/shop-api@feature/x"
    line = f"Service-ref: {ref}"
    assert ship.with_service_ref("", ref) == line or ship.with_service_ref("", ref).strip() == line
    assert ship.with_service_ref("body\n", ref).splitlines() == ["body", "", line]
    out = ship.with_service_ref("a\nservice-ref: x/y@z\nb\n  Service-Ref : q\nc\n", ref)
    assert out.splitlines() == ["a", line, "b", "c"]
    assert ship.with_service_ref(out, ref) == out


def test_ac_098_1_a_new_gitops_pr_carries_exactly_one_marker(repo, gh):
    """AC-098.1: the body file passed to `pr create` has the marker; a marker in the given file is replaced."""
    _ready(repo)
    body = repo / "body.md"
    body.write_text("## What\n\nservice-ref: other/repo@main\nmore\nService-ref: bad\n")
    ship.gitops_pr(repo, "g1", "feat(shop): component", body)
    (sent,) = _body_files(gh, "create")
    assert len(MARKER.findall(sent)) == 1
    assert f"Service-ref: {_ref(repo)}" in sent.splitlines()
    assert "## What" in sent and "more" in sent
    assert "other/repo" not in sent
    assert "service-ref: other/repo@main" in body.read_text()      # the caller's file is not modified


def test_ac_098_1_a_body_without_marker_gets_one(repo, gh):
    """AC-098.1: appended as the last line."""
    _ready(repo)
    (repo / "body.md").write_text("just text")
    ship.gitops_pr(repo, "g1", "feat(shop): component", repo / "body.md")
    (sent,) = _body_files(gh, "create")
    assert sent.splitlines()[-1] == f"Service-ref: {_ref(repo)}" and len(MARKER.findall(sent)) == 1


def test_ac_098_2_a_reused_pr_without_marker_gets_it_and_nothing_else_changes(repo, gh, monkeypatch):
    """AC-098.2: one `pr edit <url> --body-file`; the rest of the body is unchanged."""
    _ready(repo)
    _reuse(monkeypatch, gh, "Keep this\n\nand this\n")
    (repo / "body.md").write_text("ignored")
    info = ship.gitops_pr(repo, "g1", "feat(shop): component", repo / "body.md")
    assert info["pr"] == f"https://github.com/{GITOPS}/pull/3"
    ((args, text),) = gh.edits
    assert f"https://github.com/{GITOPS}/pull/3" in args
    assert text.splitlines()[:3] == ["Keep this", "", "and this"]
    assert text.splitlines()[-1] == f"Service-ref: {_ref(repo)}" and len(MARKER.findall(text)) == 1
    assert not [c for c in gh.calls if c[:2] == ["pr", "create"] and "-R" in c]


def test_ac_098_2_a_different_marker_is_replaced(repo, gh, monkeypatch):
    """AC-098.2: a different marker is replaced in place."""
    _ready(repo)
    _reuse(monkeypatch, gh, "top\nService-ref: acme/old@feature/old\nbottom\n")
    (repo / "body.md").write_text("x")
    ship.gitops_pr(repo, "g1", "feat(shop): component", repo / "body.md")
    ((_, text),) = gh.edits
    assert text.splitlines() == ["top", f"Service-ref: {_ref(repo)}", "bottom"]


def test_ac_098_2_a_reused_pr_with_the_marker_is_not_edited(repo, gh, monkeypatch):
    """AC-098.2: no edit when the body already carries the marker."""
    _ready(repo)
    _reuse(monkeypatch, gh, f"top\nService-ref: {_ref(repo)}\n")
    (repo / "body.md").write_text("x")
    ship.gitops_pr(repo, "g1", "feat(shop): component", repo / "body.md")
    assert gh.edits == []


# --- doctor (AC-098.16) ---

GITOPS_SHAPE = "_src_path: gh:ika100/sdlc-foundry/templates/gitops-app\n"


def _doctor_repo(tmp_path, shape_answers):
    r = tmp_path / "shop-gitops"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    (r / ".copier-answers.yml").write_text(shape_answers)
    subprocess.run(["git", "remote", "add", "origin", f"https://github.com/{GITOPS}.git"], cwd=r, check=True)
    return r


def _secrets(monkeypatch, names):
    calls = []

    def fake(args, *, cwd, check=True):
        calls.append(args)
        if args[:2] == ["secret", "list"]:
            if names is None:
                raise RuntimeError("no access")
            return json.dumps([{"name": n} for n in names])
        return ""

    monkeypatch.setattr(ship, "gh", fake)
    return calls


def test_ac_098_16_missing_secret_is_a_warning_with_the_fix(tmp_path, monkeypatch):
    """AC-098.16: WARN (not FAIL) naming the secret and how to add it."""
    r = _doctor_repo(tmp_path, GITOPS_SHAPE)
    _secrets(monkeypatch, ["GITOPS_TOKEN"])
    (c,) = doctor.check_service_repos_token(r)
    assert c["status"] == doctor.WARN and "SERVICE_REPOS_READ_TOKEN" in c["name"]
    assert "gh secret set SERVICE_REPOS_READ_TOKEN -R acme/shop-gitops" in c["fix"] and "Contents: read" in c["fix"]


def test_ac_098_16_unreadable_secret_list_is_a_warning(tmp_path, monkeypatch):
    """AC-098.16: a list that cannot be read is WARN, never FAIL."""
    r = _doctor_repo(tmp_path, GITOPS_SHAPE)
    monkeypatch.setattr(ship, "gh", lambda args, *, cwd, check=True: "")
    (c,) = doctor.check_service_repos_token(r)
    assert c["status"] == doctor.WARN and "SERVICE_REPOS_READ_TOKEN" in c["name"]


def test_ac_098_16_present_secret_is_ok(tmp_path, monkeypatch):
    """AC-098.16: with the secret present the check is OK."""
    r = _doctor_repo(tmp_path, GITOPS_SHAPE)
    _secrets(monkeypatch, ["GITOPS_TOKEN", "SERVICE_REPOS_READ_TOKEN"])
    (c,) = doctor.check_service_repos_token(r)
    assert c["status"] == doctor.OK and "SERVICE_REPOS_READ_TOKEN" in c["name"]


def test_ac_098_16_other_shapes_do_not_show_the_check(tmp_path, monkeypatch):
    """AC-098.16: a repo of any other shape gets no such line (and the secrets are not even asked for)."""
    r = _doctor_repo(tmp_path, "_src_path: gh:ika100/sdlc-foundry/templates/service-go\n")
    calls = _secrets(monkeypatch, [])
    assert doctor.check_service_repos_token(r) == []
    assert calls == []


def test_ac_098_16_run_checks_includes_it_for_a_gitops_app(tmp_path, monkeypatch):
    """AC-098.16: run_checks calls the check after check_gitops_token."""
    r = _doctor_repo(tmp_path, GITOPS_SHAPE)
    _secrets(monkeypatch, [])
    for name in ("check_tools", "check_gh", "check_docker", "check_kube", "check_plugins", "check_platform_source", "check_repo",
                 "check_gitops_token"):
        monkeypatch.setattr(doctor, name, lambda *a, **k: [])
    import gates
    monkeypatch.setattr(gates, "check_gates", lambda repo: [])
    assert any("SERVICE_REPOS_READ_TOKEN" in c["name"] for c in doctor.run_checks(r))
