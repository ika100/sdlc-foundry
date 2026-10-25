"""Spec 090: the weekly workflow asset, `cplat runs init` installing it, doctor, the store's single-file read and the GitHub tracker."""
import json
import re
from pathlib import Path

import pytest
import yaml

import doctor
import runs
import runs_store
from retro_world import PLATFORM, Lazy
from test_runs import clock, mem, quiet_doctor, store  # noqa: F401  (fixtures)

retro_setup = Lazy("retro_setup")
retro_github = Lazy("retro_github")
autoissue = Lazy("autoissue")

WORKFLOW = ".github/workflows/cplat-retro.yml"
ASSET = Path(__file__).resolve().parents[2] / "scripts" / "cplat" / "assets" / "workflows" / "cplat-retro.yml"


# ---------------- AC-090.12 the workflow asset ----------------

def asset():
    return yaml.safe_load(ASSET.read_text())


def steps():
    return asset()["jobs"]["retro"]["steps"]


def step_running(fragment):
    (s,) = [s for s in steps() if fragment in s.get("run", "")]
    return s


def test_the_workflow_runs_on_monday_0600_utc_on_the_self_hosted_runner():
    """AC-090.12: schedule `0 6 * * 1`, self-hosted runner, read-only token, one run at a time."""
    doc = asset()
    on = doc.get("on", doc.get(True))
    assert on["schedule"] == [{"cron": "0 6 * * 1"}] and "workflow_dispatch" in on
    job = doc["jobs"]["retro"]
    assert "self-hosted" in job["runs-on"] and "CI_RUNNER" in job["runs-on"]
    assert doc["permissions"] == {"contents": "read"} and doc["concurrency"]["cancel-in-progress"] is False


def test_the_workflow_runs_report_then_proposals_then_post_in_this_order():
    """AC-090.12: `cplat retro`, a headless Claude run, then the post."""
    runs_ = [s.get("run", "") for s in steps()]
    order = [next(i for i, r in enumerate(runs_) if frag in r) for frag in ("retro --out", "retro propose --dir", "retro post --dir")]
    assert order == sorted(order) and len(set(order)) == 3


def test_a_failing_report_fails_the_run_and_skips_the_post_but_a_failing_proposal_step_does_not():
    """AC-090.12: only the Claude install and the proposal step continue on error; report and post do not."""
    assert not step_running("retro --out").get("continue-on-error")
    assert not step_running("retro post --dir").get("continue-on-error")
    assert step_running("retro propose --dir")["continue-on-error"] is True
    flagged = [s for s in steps() if s.get("continue-on-error")]
    assert len(flagged) == 2


def test_only_the_proposal_step_sees_the_claude_credential_and_it_sees_no_github_token():
    """AC-090.12: the credential is a secret of the store repo; the job token is the retro token; the proposal step clears GH_TOKEN (AC-090.9)."""
    job = asset()["jobs"]["retro"]
    assert job["env"]["GH_TOKEN"] == "${{ secrets.RETRO_GH_TOKEN }}" and job["env"]["CPLAT_RUNS_REPO"] == "${{ github.repository }}"
    prop = step_running("retro propose --dir")
    assert prop["env"]["GH_TOKEN"] == "" and "secrets.CLAUDE_CODE_OAUTH_TOKEN" in prop["env"]["CLAUDE_CODE_OAUTH_TOKEN"]
    for s in steps():
        if s != prop:
            assert "CLAUDE_CODE_OAUTH_TOKEN" not in json.dumps(s.get("env", {}))


def test_every_action_is_pinned_to_a_commit():
    """AC-090.12: actions are pinned by sha, like everywhere in the platform."""
    uses = re.findall(r"uses:\s*(\S+)", ASSET.read_text())
    assert uses and all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u) for u in uses)


def test_workflow_text_fills_in_the_platform_repo():
    """AC-090.12: the asset is a template with `__PLATFORM_REPO__`; the installed text has the platform repo and no placeholder."""
    assert "__PLATFORM_REPO__" in ASSET.read_text()
    text = retro_setup.workflow_text("acme/platform")
    assert "__PLATFORM_REPO__" not in text and text.count("acme/platform") >= 2
    assert yaml.safe_load(text)["jobs"]["retro"]["env"]["CPLAT_FEEDBACK_REPO"] == "acme/platform"


def test_the_asset_directory_is_checked_by_the_pin_check():
    """AC-090.12: `pin-actions.py` covers scripts/cplat/assets by default."""
    src = (Path(__file__).resolve().parents[2] / "scripts" / "pin-actions.py").read_text()
    assert "scripts/cplat/assets" in src


# ---------------- AC-090.14 cplat runs init ----------------

def test_init_of_a_new_store_adds_the_schedule(mem, monkeypatch, capsys):
    """AC-090.14: the store repo gets the weekly retro workflow; the export line stays last."""
    mem.exists = False
    monkeypatch.setattr(runs, "open_store", lambda slug: mem)
    assert runs.main(["init", "acme/runs"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert mem.files[WORKFLOW] == retro_setup.workflow_text(core_platform_repo()) and len(mem.puts) == 1 and mem.messages == ["retro: weekly schedule (spec 090)"]
    assert "retro schedule: added .github/workflows/cplat-retro.yml (Mondays 06:00 UTC)" in lines
    assert any(ln.startswith("retro: set the secrets CLAUDE_CODE_OAUTH_TOKEN") and "RETRO_GH_TOKEN" in ln for ln in lines)
    assert lines[-1].startswith("export CPLAT_RUNS_REPO=acme/runs")


def core_platform_repo():
    import autoissue as ai
    return ai.default_repo()


def test_init_of_an_existing_store_without_the_schedule_adds_only_it(mem, monkeypatch, capsys):
    """AC-090.14: an existing store gets the schedule when it is missing and nothing else changes; the output never says `created`."""
    mem.files["runs/2026/10/20/a.json"] = "{}\n"
    monkeypatch.setattr(runs, "open_store", lambda slug: mem)
    assert runs.main(["init", "acme/runs"]) == 0
    out = capsys.readouterr().out
    assert set(mem.files) == {"runs/2026/10/20/a.json", WORKFLOW} and list(mem.puts[0]) == [WORKFLOW]
    assert not mem.created and "created" not in out and "retro schedule: added" in out


def test_init_again_changes_nothing(mem, monkeypatch, capsys):
    """AC-090.14: with the workflow present, init writes nothing and does not touch the file, even when it was edited."""
    mem.files[WORKFLOW] = "name: edited by hand\n"
    monkeypatch.setattr(runs, "open_store", lambda slug: mem)
    assert runs.main(["init", "acme/runs"]) == 0
    out = capsys.readouterr().out
    assert mem.puts == [] and mem.files[WORKFLOW] == "name: edited by hand\n"
    assert "retro schedule: present (.github/workflows/cplat-retro.yml)" in out and "created" not in out
    assert runs.main(["init", "acme/runs"]) == 0 and mem.puts == []


def test_a_rejected_workflow_write_is_a_warning_with_the_scope_fix(mem, monkeypatch, capsys):
    """AC-090.14: without the `workflow` scope init still succeeds and says how to fix it."""
    mem.reject = True
    monkeypatch.setattr(runs, "open_store", lambda slug: mem)
    assert runs.main(["init", "acme/runs"]) == 0
    out = capsys.readouterr().out
    assert "WARNING: retro schedule not added: " in out and "gh auth refresh -h github.com -s workflow, then cplat runs init acme/runs" in out
    assert out.splitlines()[-1].startswith("export CPLAT_RUNS_REPO=acme/runs")


def test_a_public_store_gets_no_schedule(mem, monkeypatch, capsys):
    """AC-090.14: the public-repo refusal comes before anything is written."""
    mem.vis = "public"
    monkeypatch.setattr(runs, "open_store", lambda slug: mem)
    import cplat
    assert cplat.main(["runs", "init", "acme/runs"]) == 1
    assert mem.puts == [] and WORKFLOW not in mem.files


def test_install_schedule_never_raises(mem):
    """AC-090.14: even a store that cannot be read gives the warning lines."""
    mem.reachable = False
    lines = retro_setup.install_schedule(mem, "acme/runs")
    assert any(ln.startswith("WARNING: retro schedule not added: ") for ln in lines) and lines[-1].startswith("retro: set the secrets")


def test_a_workflow_rejection_is_no_write_race():
    """AC-090.14: GitHub refusing a workflow file without the scope is reported, not retried as a concurrent write."""
    assert runs_store._ApiError(422, "gh: refusing to allow an OAuth App to create or update workflow `.github/workflows/x.yml` without `workflow` scope (HTTP 422)").race is False
    assert runs_store._ApiError(422, "gh: Update is not a fast forward (HTTP 422)").race is True


def test_the_store_reads_one_file(monkeypatch):
    """AC-090.14: `read_file` returns the text, None for a missing file, and raises for any other failure."""
    calls = []

    def fake(args, *, input=None, timeout=10.0):
        calls.append(list(args))
        if "present.txt" in args[1]:
            return 0, "hello\n", ""
        if "missing.txt" in args[1]:
            return 1, "", "gh: Not Found (HTTP 404)"
        return 1, "", "gh: boom (HTTP 500)"

    monkeypatch.setattr(runs_store, "gh", fake)
    s = runs_store.GitHubStore("acme/runs")
    assert s.read_file("present.txt") == "hello\n" and s.read_file("missing.txt") is None
    assert calls[0][:2] == ["api", "repos/acme/runs/contents/present.txt"] and "Accept: application/vnd.github.raw+json" in calls[0]
    with pytest.raises(runs_store.StoreUnreachable):
        s.read_file("other.txt")


# ---------------- AC-090.14 doctor ----------------

def secrets(monkeypatch, names, code=0):
    def fake(args, *, input=None, timeout=10.0):
        assert args[:2] == ["secret", "list"] and "acme/runs" in args
        return (code, json.dumps([{"name": n} for n in names]), "") if code == 0 else (code, "", "gh: no access")
    monkeypatch.setattr(runs_store, "gh", fake)


def schedule_check():
    res = doctor.check_retro_schedule()
    (c,) = [x for x in res if x["name"] == "retro schedule"]
    return c


def test_doctor_warns_naming_everything_that_is_missing(store, monkeypatch):
    """AC-090.14: no schedule, no Claude credential, no GitHub token: one warning that names all three, with the fixes."""
    secrets(monkeypatch, [])
    c = schedule_check()
    assert c["status"] == doctor.WARN and c["detail"].startswith("acme/runs: ")
    assert c["detail"] == ("acme/runs: no retro schedule (.github/workflows/cplat-retro.yml); "
                           "no Claude credential secret (CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY); no RETRO_GH_TOKEN secret")
    assert "cplat runs init acme/runs" in c["fix"] and "claude setup-token, then gh secret set CLAUDE_CODE_OAUTH_TOKEN -R acme/runs" in c["fix"]
    assert "gh secret set RETRO_GH_TOKEN -R acme/runs" in c["fix"] and " ; " in c["fix"]


def test_doctor_names_only_the_missing_secret(store, monkeypatch):
    """AC-090.14: the schedule is there; the Claude credential is not."""
    store.files[WORKFLOW] = "name: cplat retro\n"
    secrets(monkeypatch, ["RETRO_GH_TOKEN"])
    c = schedule_check()
    assert c["status"] == doctor.WARN and "no Claude credential secret" in c["detail"] and "no retro schedule" not in c["detail"]
    assert "cplat runs init" not in c["fix"] and "RETRO_GH_TOKEN" not in c["detail"]


@pytest.mark.parametrize("claude", ["CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"])
def test_doctor_is_ok_when_schedule_and_secrets_are_there(store, monkeypatch, claude):
    """AC-090.14: either Claude secret will do."""
    store.files[WORKFLOW] = "name: cplat retro\n"
    secrets(monkeypatch, [claude, "RETRO_GH_TOKEN"])
    c = schedule_check()
    assert c["status"] == doctor.OK and c["detail"] == "acme/runs: weekly retro scheduled (Mondays 06:00 UTC)"


def test_doctor_warns_when_the_secrets_cannot_be_read(store, monkeypatch):
    """AC-090.14: an unreadable secret list is a warning, not a pass and not a failure."""
    store.files[WORKFLOW] = "name: cplat retro\n"
    secrets(monkeypatch, [], code=1)
    c = schedule_check()
    assert c["status"] == doctor.WARN and "secrets of acme/runs could not be read with this gh login" in c["detail"]


def test_doctor_is_silent_without_a_usable_store(clock, mem, monkeypatch):
    """AC-090.14: not configured, public or unreachable: the run store line already says so."""
    assert doctor.check_retro_schedule() == []
    monkeypatch.setenv("CPLAT_RUNS_REPO", mem.slug)
    monkeypatch.setattr(runs, "open_store", lambda slug: mem)
    mem.vis = "public"
    assert doctor.check_retro_schedule() == []
    mem.vis, mem.reachable = "private", False
    assert doctor.check_retro_schedule() == []


def test_the_retro_check_is_part_of_doctor_and_never_fails_it(quiet_doctor, store, monkeypatch, tmp_path):
    """AC-090.14: it comes after the run store check in `run_checks`, and a warning leaves doctor's exit code at 0."""
    secrets(monkeypatch, [])
    names = [c["name"] for c in doctor.run_checks(tmp_path)]
    assert names.index("retro schedule") == names.index("run store") + 1
    assert doctor.main(["--repo", str(tmp_path)]) == 0


# ---------------- AC-090.3 / AC-090.10 / AC-090.13 the GitHub tracker ----------------

class FakeGh:
    """Replaces `retro_github.gh`: answers REST reads from a table and records every call."""

    def __init__(self):
        self.calls: list[tuple[list[str], str | None]] = []
        self.replies: list[tuple[str, tuple[int, str, str]]] = []

    def on(self, fragment, reply):
        self.replies.append((fragment, reply))

    def __call__(self, args, *, input=None, timeout=30.0):
        self.calls.append((list(args), input))
        line = " ".join(args)
        for fragment, reply in self.replies:
            if fragment in line:
                return reply
        return 0, "", ""


@pytest.fixture()
def ghx(monkeypatch):
    import retro_github as rg
    g = FakeGh()
    monkeypatch.setattr(rg, "gh", g)
    return g


def item(number, labels=(), pr=False, **over):
    d = {"number": number, "title": f"issue {number}", "html_url": f"https://github.com/{PLATFORM}/issues/{number}", "state": "open",
         "labels": [{"name": n} for n in labels], "created_at": "2026-10-20T09:00:00Z", "body": f"body {number}"}
    if pr:
        d["pull_request"] = {"url": "x"}
    d.update(over)
    return d


def test_auto_issues_are_read_with_their_comments_and_pull_requests_are_dropped(ghx):
    """AC-090.3: auto-filed issues of every state since the previous Monday, each with its comments; no pull requests."""
    ghx.on("labels=auto-filed", (0, json.dumps([item(1, ["auto-filed", "triage"]), item(2, ["auto-filed"], pr=True)]), ""))
    ghx.on("issues/1/comments", (0, json.dumps([{"created_at": "2026-10-21T09:00:00Z", "body": "**Occurrence 2** again", "user": {}}]), ""))
    out = retro_github.tracker().auto_issues(PLATFORM, "2026-10-12")
    assert [i["number"] for i in out] == [1]
    i = out[0]
    assert i["title"] == "issue 1" and i["state"] == "open" and i["url"].endswith("/issues/1") and i["body"] == "body 1"
    assert set(i["labels"]) == {"auto-filed", "triage"} and i["created_at"] == "2026-10-20T09:00:00Z"
    assert i["comments"] == [{"created_at": "2026-10-21T09:00:00Z", "body": "**Occurrence 2** again"}]
    query = next(a for a, _ in ghx.calls if "labels=auto-filed" in " ".join(a))
    joined = " ".join(query)
    assert "--paginate" in query and f"repos/{PLATFORM}/issues" in joined and "state=all" in joined and "since=2026-10-12" in joined


def test_open_issues_leave_out_pull_requests(ghx):
    """AC-090.8: the open issues a proposal may cover: number, title, labels."""
    ghx.on("state=open", (0, json.dumps([item(7, ["bug"]), item(8, pr=True)]), ""))
    assert retro_github.tracker().open_issues(PLATFORM) == [{"number": 7, "title": "issue 7", "labels": ["bug"]}]


def test_retro_issues_are_the_ones_with_the_label_in_any_state(ghx):
    """AC-090.13: the issues labelled `retro`, open and closed."""
    ghx.on("labels=retro", (0, json.dumps([item(5, ["retro"], state="closed", title="Weekly retro 2026-W41")]), ""))
    (i,) = retro_github.tracker().retro_issues(PLATFORM)
    assert i["number"] == 5 and i["title"] == "Weekly retro 2026-W41" and i["state"] == "closed" and i["url"].endswith("/issues/5")
    assert "state=all" in " ".join(next(a for a, _ in ghx.calls))


def test_create_makes_an_issue_with_the_retro_label_and_the_body_on_stdin(ghx):
    """AC-090.10: `gh issue create` with the title, the label retro (never triage) and the body on stdin; the url comes back."""
    ghx.on("issue create", (0, f"https://github.com/{PLATFORM}/issues/12\n", ""))
    url = retro_github.tracker().create(PLATFORM, "Weekly retro 2026-W43", "the body", ["retro"])
    assert url == f"https://github.com/{PLATFORM}/issues/12"
    args, body = ghx.calls[0]
    assert args[:2] == ["issue", "create"] and "-R" in args and PLATFORM in args and "Weekly retro 2026-W43" in args
    assert args[args.index("--label") + 1] == "retro" and "triage" not in args and "--body-file" in args and body == "the body"


def test_create_makes_the_label_when_it_is_missing_and_tries_again(monkeypatch):
    """AC-090.10: a missing `retro` label is created (colour 5319e7) and the issue is created again."""
    state = {"n": 0}

    def create(args, **kw):
        state["n"] += 1
        return (1, "", "could not add label: 'retro' not found") if state["n"] == 1 else (0, f"https://github.com/{PLATFORM}/issues/13\n", "")

    class Seq(FakeGh):
        def __call__(self, args, *, input=None, timeout=30.0):
            self.calls.append((list(args), input))
            if args[:2] == ["issue", "create"]:
                return create(args)
            return 0, "", ""

    import retro_github as rg
    g = Seq()
    monkeypatch.setattr(rg, "gh", g)
    url = rg.tracker().create(PLATFORM, "Weekly retro 2026-W43", "b", ["retro"])
    kinds = [a[:2] for a, _ in g.calls]
    assert url.endswith("/issues/13") and kinds == [["issue", "create"], ["label", "create"], ["issue", "create"]]
    label = g.calls[1][0]
    assert "retro" in label and "5319e7" in label and "--force" in label and "Weekly platform retro (spec 090)" in label


def test_edit_comment_and_close_use_gh_issue_commands(ghx):
    """AC-090.10 AC-090.13: the body is replaced, the comment is added, the issue is closed; all against the platform repo."""
    ghx.on("issue edit", (0, f"https://github.com/{PLATFORM}/issues/5\n", ""))
    t = retro_github.tracker()
    t.edit_body(PLATFORM, 5, "new body")
    t.comment(PLATFORM, 5, "Superseded by the retro for 2026-W43: https://x")
    t.close(PLATFORM, 5)
    (edit, eb), (com, cb), (close, _) = ghx.calls
    assert edit[:3] == ["issue", "edit", "5"] and "-R" in edit and PLATFORM in edit and "--body-file" in edit and eb == "new body"
    assert com[:3] == ["issue", "comment", "5"] and cb == "Superseded by the retro for 2026-W43: https://x"
    assert close[:3] == ["issue", "close", "5"] and PLATFORM in close


def test_a_failing_gh_call_is_a_tracker_error(ghx):
    """AC-090.3: failures raise the TrackerError of autoissue, never an empty list."""
    ghx.on("labels=auto-filed", (1, "", "gh: Bad credentials"))
    with pytest.raises(autoissue.TrackerError):
        retro_github.tracker().auto_issues(PLATFORM, "2026-10-12")
    ghx.replies.clear()
    ghx.on("issue close", (4, "", "gh auth login"))
    with pytest.raises(autoissue.TrackerError, match="not logged in"):
        retro_github.tracker().close(PLATFORM, 1)
