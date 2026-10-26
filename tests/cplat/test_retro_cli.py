"""Spec 090: `cplat retro` (report, propose, post) against a fake run store and a fake platform repo; nothing touches GitHub."""
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import cplat
import core
import doctor
import runs
import runs_store
from retro_world import (CONSUMER_SPEC, MONDAY, PLATFORM, SECRET, SHOP, STORE, WEBUI, WEEK, FakeRetroTracker, Lazy, fill,
                         tracker)  # noqa: F401  (fixture)
from test_runs import clock, mem, store  # noqa: F401  (fixtures)

autoissue = Lazy("autoissue")
COD = "agents.svc:coder|service-python|sonnet"
ISSUE_TITLE = f"Weekly retro {WEEK}"


@pytest.fixture()
def world(store, clock, tracker):
    """Monday 2026-10-26 08:00 UTC; the store holds the records of 2026-W42 and W43; the platform repo holds the auto-filed issues."""
    clock.set(MONDAY)
    fill(store)
    return SimpleNamespace(store=store, tracker=tracker, clock=clock)


def cli(*argv):
    return cplat.main(["platform", "retro", *argv])


def spec_p(title="Merges stop failing", **over):
    p = {"title": title, "problem": "Merges fail often.", "priority": "P1", "spec_line": "Merges land on a fresh base",
         "evidence": [{"ref": "escalations.platform.reason1", "value": 2}], "covers": None}
    p.update(over)
    return p


def prompt_p(change="Run the linter first.", **over):
    p = {"agent": "svc:coder", "shape": "service-python", "metrics": [{"ref": f"{COD}.fix_rounds.avg", "value": 0.5}], "change": change}
    p.update(over)
    return p


def prepared(world, tmp_path, proposals=None):
    """`cplat retro --out DIR`, then optionally a proposals.json the agent would have written."""
    d = tmp_path / "retro"
    assert cli("--out", str(d)) == 0
    if proposals is not None:
        (d / "proposals.json").write_text(json.dumps(proposals))
    return d


def issue_body(world, number=201):
    return world.tracker.get(number)["body"]


# ---------------- AC-090.1 report mode ----------------

def test_retro_prints_the_report_of_the_last_complete_week_and_changes_nothing(world, capsys):
    """AC-090.1: no --post: the report of 2026-W43 is printed; no issue, no comment, no store write."""
    before = dict(world.store.files)
    assert cli() == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "Weekly retro 2026-W43 (2026-10-19 to 2026-10-25): 9 run(s) in 2 repo(s)"
    assert "Proposals: not generated" in out and SHOP in out                    # the text report is for the maintainer: private detail is fine
    assert world.tracker.writes == [] and world.store.puts == [] and world.store.files == before


def test_the_week_is_the_one_before_the_current_date_whatever_the_weekday(world, capsys):
    """AC-090.1: on a Wednesday and on a Sunday the covered week is still the last complete one."""
    world.clock.set("2026-10-28T15:30:00Z")
    assert cli() == 0 and "Weekly retro 2026-W43 (" in capsys.readouterr().out
    world.clock.set("2026-11-01T23:00:00Z")
    assert cli() == 0 and "Weekly retro 2026-W43 (" in capsys.readouterr().out
    world.clock.set("2026-10-25T23:00:00Z")
    assert cli() == 0 and "Weekly retro 2026-W42 (2026-10-12 to 2026-10-18)" in capsys.readouterr().out


def test_week_selects_another_complete_week(world, capsys):
    """AC-090.1: --week 2026-W42 reports that week against the one before."""
    assert cli("--week", "2026-W42") == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first == "Weekly retro 2026-W42 (2026-10-12 to 2026-10-18): 4 run(s) in 1 repo(s)"


@pytest.mark.parametrize("week", ["2026-W44", "2026-W60", "2027-W01", "2026W42", "last", "2026-W4"])
def test_a_week_that_is_not_complete_is_an_error(world, capsys, week):
    """AC-090.1: only a complete ISO week before today."""
    assert cli("--week", week) == 1
    assert "--week must be a complete ISO week before today, like 2026-W42" in capsys.readouterr().err
    assert world.tracker.writes == []


def test_json_prints_the_report_document(world, capsys):
    """AC-090.1: --json prints report.json."""
    assert cli("--json") == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == 1 and doc["week"] == WEEK and doc["records"]["current"] == 9 and doc["generated_at"] == "2026-10-26T08:00:00Z"
    assert doc["store"] == STORE


def test_out_writes_the_directory_and_removes_stale_proposals(world, tmp_path):
    """AC-090.1: --out DIR writes report.json, report.md and prompt.md, deletes a stale proposals.json/.error, and still writes nowhere else."""
    d = tmp_path / "retro"
    d.mkdir()
    (d / "proposals.json").write_text("{}")
    (d / "proposals.error").write_text("old\n")
    assert cli("--out", str(d)) == 0
    assert json.loads((d / "report.json").read_text())["week"] == WEEK
    assert SHOP in (d / "report.md").read_text() and str(d) in (d / "prompt.md").read_text()
    assert not (d / "proposals.json").exists() and not (d / "proposals.error").exists()
    assert world.tracker.writes == [] and world.store.puts == []


def test_the_report_file_is_deterministic_apart_from_the_timestamp(world, tmp_path, clock):
    """AC-090.2: two runs over the same records give the same report.json except `generated_at`."""
    a, b = tmp_path / "a", tmp_path / "b"
    cli("--out", str(a))
    clock.set("2026-10-26T09:45:10Z")
    cli("--out", str(b))
    ja, jb = json.loads((a / "report.json").read_text()), json.loads((b / "report.json").read_text())
    assert ja["generated_at"] != jb["generated_at"]
    ja["generated_at"] = jb["generated_at"] = ""
    assert ja == jb


# ---------------- AC-090.5 no data ----------------

def test_a_week_without_runs_still_produces_a_report(world, capsys):
    """AC-090.5: no records in the week: exit 0, the first line says so, the sections say `no data for this week`."""
    assert cli("--week", "2026-W40") == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "Weekly retro 2026-W40 (2026-09-28 to 2026-10-04): no runs this week"
    assert out.count("no data for this week") >= 4


def test_a_failed_issue_read_is_an_error_not_no_data(world, capsys):
    """AC-090.5: unreadable platform issues are reported as such, never as an empty section."""
    world.tracker.error = autoissue.TrackerError("GitHub refused: rate limited")
    assert cli() == 1
    err = capsys.readouterr().err
    assert f"platform issues of {PLATFORM} cannot be read: GitHub refused: rate limited" in err and "fix: gh auth status" in err
    assert world.tracker.writes == []


# ---------------- AC-090.6 the store ----------------

def test_without_a_store_setting_the_retro_names_it_and_the_doctor_hint(world, monkeypatch, capsys):
    """AC-090.6: not configured: non-zero, the missing setting, the hint cplat doctor gives, nothing posted."""
    monkeypatch.delenv("CPLAT_RUNS_REPO")
    assert cli() == 1
    err = capsys.readouterr().err
    assert "run store not usable for the retro: CPLAT_RUNS_REPO is not set" in err and "fix: cplat runs init <owner/name>" in err
    assert world.tracker.writes == []


def test_an_unreachable_store_names_the_repo_and_the_doctor_hint(world, capsys):
    """AC-090.6: unreachable store."""
    world.store.reachable = False
    assert cli() == 1
    err = capsys.readouterr().err
    assert "run store not usable for the retro: acme/runs unreachable" in err and "fix: gh repo view acme/runs" in err
    assert world.tracker.writes == []


def test_a_public_store_is_refused_with_the_visibility_hint(world, capsys):
    """AC-090.6: a public store is not usable."""
    world.store.vis = "public"
    assert cli() == 1
    err = capsys.readouterr().err
    assert "acme/runs is public" in err and "gh repo edit acme/runs --visibility private" in err


def test_a_store_that_cannot_be_read_names_the_error(world, monkeypatch, capsys):
    """AC-090.6: the read error is in the message, with the repo and a command to check it."""
    def broken(days, deadline=None):
        raise runs_store.StoreUnreachable("api down")
    monkeypatch.setattr(world.store, "read", broken)
    assert cli() == 1
    err = capsys.readouterr().err
    assert "run store acme/runs cannot be read: api down" in err and "fix: gh repo view acme/runs" in err
    assert world.tracker.writes == []


def test_the_retro_and_doctor_give_the_same_store_hint(world, monkeypatch):
    """AC-090.6: `doctor.run_store_check(status)` is the one place the hint comes from."""
    monkeypatch.delenv("CPLAT_RUNS_REPO")
    c = doctor.run_store_check(runs.store_status())
    assert c["name"] == "run store" and "cplat runs init <owner/name>" in c["fix"]


# ---------------- AC-090.7 / AC-090.9 posting proposals ----------------

def test_a_proposal_without_evidence_is_refused_by_post_and_named_on_stderr(world, tmp_path, capsys):
    """AC-090.7: `post` drops the proposal and names it; the other proposal and the report are still posted."""
    d = prepared(world, tmp_path, {"specs": [spec_p("Fine plan"), spec_p("Bogus plan", evidence=[{"ref": "records", "value": 12345}])],
                                   "prompts": []})
    capsys.readouterr()
    assert cli("post", "--dir", str(d)) == 0
    err = capsys.readouterr().err
    assert 'refused spec proposal 2 "Bogus plan": no evidence from this report' in err
    body = issue_body(world)
    assert "Fine plan" in body and "Bogus plan" not in body and "1 proposal(s) refused" in body
    assert 'refused spec proposal 2 "Bogus plan"' in world.store.files[f"retros/{WEEK}.md"]


def test_at_most_five_specs_reach_the_issue(world, tmp_path):
    """AC-090.7: seven valid proposals: five are posted, ranked 1 to 5."""
    d = prepared(world, tmp_path, {"specs": [spec_p(f"Plan {i}") for i in range(1, 8)], "prompts": []})
    assert cli("post", "--dir", str(d)) == 0
    body = issue_body(world)
    assert len(re.findall(r"^\d+\. \*\*Plan \d\*\*", body, re.M)) == 5 and "Plan 6" not in body and "2 proposal(s) refused" in body


def test_a_proposal_that_names_an_open_issue_says_see_it(world, tmp_path):
    """AC-090.8: a finding the open issue #101 covers is proposed as `see #101`, not as a new spec."""
    d = prepared(world, tmp_path, {"specs": [spec_p("Gate check", evidence=[{"ref": "issues.#101", "value": 2}])], "prompts": []})
    assert cli("post", "--dir", str(d)) == 0
    assert "**Gate check** (P1) — see #101" in issue_body(world)


def test_at_most_three_prompt_proposals_and_no_agent_file_or_pull_request(world, tmp_path):
    """AC-090.9: four valid prompt changes: three are posted; no agent file changes and the retro only talks to its own issue."""
    agents = Path(core.PLATFORM_ROOT) / "plugins"

    def digest():
        h = hashlib.sha256()
        for p in sorted(agents.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                h.update(str(p).encode() + p.read_bytes())
        return h.hexdigest()

    before = digest()
    d = prepared(world, tmp_path, {"specs": [], "prompts": [prompt_p(f"Change number {i}.") for i in range(4)]})
    assert cli("post", "--dir", str(d)) == 0
    body = issue_body(world)
    assert len(re.findall(r"^- \*\*svc:coder\*\* on service-python: ", body, re.M)) == 3 and "Change number 3." not in body
    assert digest() == before
    assert {c[0] for c in world.tracker.calls} <= {"auto_issues", "open_issues", "retro_issues", "create", "edit_body", "comment", "close"}


# ---------------- AC-090.10 the issue ----------------

def test_post_creates_the_issue_with_the_retro_label_and_no_triage(world, capsys):
    """AC-090.10: no issue for the week: one is created, titled `Weekly retro 2026-W43`, labelled `retro`, not `triage`."""
    assert cli("post") == 0
    (call,) = [c for c in world.tracker.calls if c[0] == "create"]
    _, repo, title, body, labels = call
    assert (repo, title) == (PLATFORM, ISSUE_TITLE) and labels == ["retro"] and "triage" not in labels
    assert body.splitlines()[0].startswith("Weekly retro 2026-W43 (2026-10-19 to 2026-10-25)")
    assert "Proposals: not generated (no proposal step ran)" in body
    assert f"retro: https://github.com/{PLATFORM}/issues/201 (created); closed 0 earlier retro issue(s); report in the run store" in capsys.readouterr().out


def test_post_again_replaces_the_body_instead_of_creating_a_second_issue(world, capsys):
    """AC-090.10: the issue exists: its body is replaced; no second issue."""
    assert cli("post") == 0
    world.tracker.get(201)["body"] = "hand edit"
    capsys.readouterr()
    assert cli("post") == 0
    assert [c[0] for c in world.tracker.calls].count("create") == 1
    assert world.tracker.get(201)["body"].startswith("Weekly retro 2026-W43") and len(world.tracker.retros) == 1
    assert "(updated)" in capsys.readouterr().out


def test_an_existing_closed_issue_of_the_week_is_edited_and_stays_closed(world):
    """AC-090.10: the lowest-numbered issue with the title is edited, state and labels are left alone."""
    world.tracker.add_retro(50, ISSUE_TITLE, state="closed")
    world.tracker.add_retro(60, ISSUE_TITLE)
    assert cli("post") == 0
    assert [c[:3] for c in world.tracker.calls if c[0] == "edit_body"] == [("edit_body", PLATFORM, 50)]
    assert world.tracker.get(50)["state"] == "closed" and world.tracker.get(50)["labels"] == ["retro"] and world.tracker.get(60)["body"] == "old"
    assert "create" not in [c[0] for c in world.tracker.calls]


def test_nothing_is_written_when_the_report_cannot_be_built(world):
    """AC-090.10: every read happens before the first GitHub write."""
    world.store.reachable = False
    assert cli("post") == 1
    assert world.tracker.writes == []


# ---------------- AC-090.11 public issue, private store ----------------

def test_the_public_issue_has_no_private_name_and_the_store_has_the_full_report(world, tmp_path):
    """AC-090.11: the issue names no consumer repo, spec, record text or store; the store gets the detailed report and links the issue."""
    d = prepared(world, tmp_path, {"specs": [spec_p()], "prompts": [prompt_p()]})
    assert cli("post", "--dir", str(d)) == 0
    body = issue_body(world).lower()
    for private in (SHOP, WEBUI, "shop-api", "web-ui", CONSUMER_SPEC, STORE, "merge failed", "stale base", "disk full", "ci / test", "sdlc-runs"):
        assert private.lower() not in body, private
    assert "service-python" in body and "reason 1" in body

    url = f"https://github.com/{PLATFORM}/issues/201"
    files = world.store.files
    assert len(world.store.puts) == 1 and set(world.store.puts[0]) == {f"retros/{WEEK}.md", f"retros/{WEEK}.json", "retros/README.md"}
    assert world.store.messages == [f"retro: {WEEK}"]
    md = files[f"retros/{WEEK}.md"]
    assert md.splitlines()[1] == f"Issue: {url}" and SHOP in md and "merge failed" in md
    doc = json.loads(files[f"retros/{WEEK}.json"])
    assert doc["issue"] == url and doc["report"]["week"] == WEEK and set(doc) >= {"report", "proposals", "refused", "issue"}
    assert f"| {WEEK} | [report]({WEEK}.md) | {url} |" in files["retros/README.md"]
    assert files["retros/README.md"].startswith("# Retros\n\n| Week | Report | Issue |\n|---|---|---|\n")


def test_the_retro_index_keeps_other_weeks_and_replaces_this_one(world):
    """AC-090.11: the existing index is parsed, the row of the week is replaced, rows are sorted by week, newest first."""
    world.store.files["retros/README.md"] = ("# Retros\n\n| Week | Report | Issue |\n|---|---|---|\n"
                                             "| 2026-W44 | [report](2026-W44.md) | https://x/44 |\n"
                                             "| 2026-W43 | [report](2026-W43.md) | https://x/old |\n"
                                             "| 2026-W42 | [report](2026-W42.md) | https://x/42 |\n")
    assert cli("post") == 0
    rows = [ln for ln in world.store.files["retros/README.md"].splitlines() if ln.startswith("| 2026-")]
    assert [r.split("|")[1].strip() for r in rows] == ["2026-W44", "2026-W43", "2026-W42"]
    assert rows[1] == f"| 2026-W43 | [report](2026-W43.md) | https://github.com/{PLATFORM}/issues/201 |" and "x/old" not in "".join(rows)


def test_posted_text_from_the_agent_is_redacted_and_scrubbed(world, tmp_path):
    """AC-090.11: a secret, a repo name or a consumer spec in a proposal never reaches the issue."""
    p = spec_p(problem=f"{SHOP} fails with {SECRET} in {CONSUMER_SPEC}.", spec_line=f"Fix {SHOP}")
    d = prepared(world, tmp_path, {"specs": [p], "prompts": []})
    assert cli("post", "--dir", str(d)) == 0
    body = issue_body(world)
    assert SECRET not in body and SHOP not in body and CONSUMER_SPEC not in body


def test_a_store_that_cannot_be_updated_is_reported_after_the_issue_is_posted(world, capsys):
    """AC-090.11: the issue is posted first; a rejected store write is an error that names the issue and how to retry."""
    world.store.reject = True
    assert cli("post") == 1
    err = capsys.readouterr().err
    assert f"retro posted as https://github.com/{PLATFORM}/issues/201, but the run store could not be updated" in err
    assert "fix: cplat platform retro post --dir" in err or "cplat platform retro post" in err


# ---------------- AC-090.12 propose, and the fallbacks ----------------

@pytest.fixture()
def fake_claude(tmp_path, monkeypatch):
    """A script standing in for `claude`: logs how it was called, then writes (or does not write) proposals.json in its cwd."""
    script = tmp_path / "bin" / "claude"
    script.parent.mkdir()
    script.write_text(f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
Path(os.environ["FAKE_CLAUDE_LOG"]).write_text(json.dumps({{"argv": sys.argv[1:], "cwd": os.path.realpath(os.getcwd()),
    "env": {{k: os.environ.get(k) for k in ("GH_TOKEN", "GITHUB_TOKEN", "RETRO_GH_TOKEN", "CPLAT_HEADLESS", "CLAUDE_CODE_OAUTH_TOKEN")}}}}))
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "exit3":
    print("Invalid API key")
    sys.exit(3)
if mode == "ok":
    Path("proposals.json").write_text(os.environ["FAKE_PROPOSALS"])
if mode == "bad":
    Path("proposals.json").write_text("[1, 2")
""")
    script.chmod(0o755)
    log = tmp_path / "claude.log"
    monkeypatch.setenv("CPLAT_CLAUDE", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_PROPOSALS", json.dumps({"specs": [spec_p()], "prompts": [prompt_p()]}))
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token")
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "RETRO_GH_TOKEN"):
        monkeypatch.setenv(name, "gh-secret")
    return SimpleNamespace(log=lambda: json.loads(log.read_text()), script=script)


def test_propose_runs_claude_headless_with_read_and_write_only_and_no_github_token(world, tmp_path, fake_claude, capsys):
    """AC-090.12: the headless run gets the prompt, may only read and write, runs in the directory, and sees no GitHub token (AC-090.9)."""
    d = prepared(world, tmp_path)
    capsys.readouterr()
    assert cli("propose", "--dir", str(d)) == 0
    assert "proposals: written (1 spec(s), 1 prompt change(s))" in capsys.readouterr().out
    call = fake_claude.log()
    argv = call["argv"]
    assert argv[0] == "-p" and str(d) in argv[1] and "proposals.json" in argv[1]
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk" and argv[argv.index("--allowedTools") + 1] == "Read,Write"
    assert argv[argv.index("--output-format") + 1] == "text"
    assert call["cwd"] == os.path.realpath(d)
    assert call["env"] == {"GH_TOKEN": None, "GITHUB_TOKEN": None, "RETRO_GH_TOKEN": None, "CPLAT_HEADLESS": "1",
                           "CLAUDE_CODE_OAUTH_TOKEN": "oauth-token"}
    assert (d / "proposals.json").is_file() and not (d / "proposals.error").exists() and (d / "propose.log").exists()


def test_propose_passes_the_model(world, tmp_path, fake_claude):
    """AC-090.12: --model is handed to claude."""
    d = prepared(world, tmp_path)
    assert cli("propose", "--dir", str(d), "--model", "opus") == 0
    argv = fake_claude.log()["argv"]
    assert argv[argv.index("--model") + 1] == "opus"


def test_the_proposals_are_posted_with_the_report(world, tmp_path, fake_claude):
    """AC-090.12: report, propose, post: the issue carries the proposals."""
    d = prepared(world, tmp_path)
    assert cli("propose", "--dir", str(d)) == 0 and cli("post", "--dir", str(d)) == 0
    body = issue_body(world)
    assert "## Proposed specs" in body and "Merges stop failing" in body and "Proposals: not generated" not in body


def test_without_a_claude_credential_the_report_is_still_posted(world, tmp_path, fake_claude, monkeypatch, capsys):
    """AC-090.12: no credential: propose exits 0 and says why; post still posts `Proposals: not generated (<reason>)`; claude is not run."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = prepared(world, tmp_path)
    capsys.readouterr()
    reason = "no Claude credential (CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY is not set)"
    assert cli("propose", "--dir", str(d)) == 0
    assert f"proposals: not generated ({reason})" in capsys.readouterr().out
    assert (d / "proposals.error").read_text().strip() == reason and not Path(str(d / "proposals.json")).exists()
    assert not Path(fake_claude.script.parent.parent / "claude.log").exists()
    assert cli("post", "--dir", str(d)) == 0
    assert f"Proposals: not generated ({reason})" in issue_body(world)


@pytest.mark.parametrize("mode, reason", [("exit3", "claude exited with 3"), ("none", "no proposals.json written")])
def test_a_failed_proposal_step_still_posts_the_deterministic_report(world, tmp_path, fake_claude, monkeypatch, mode, reason):
    """AC-090.12: claude fails or writes nothing: the reason is the error file and the posted line."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    d = prepared(world, tmp_path)
    assert cli("propose", "--dir", str(d)) == 0
    assert (d / "proposals.error").read_text().strip() == reason
    assert cli("post", "--dir", str(d)) == 0
    body = issue_body(world)
    assert f"Proposals: not generated ({reason})" in body and "Weekly retro 2026-W43" in body


def test_a_failing_claude_shows_its_output_in_the_job_log_but_not_in_the_posted_reason(world, tmp_path, fake_claude, monkeypatch, capsys):
    """AC-090.12: `claude exited with N` alone cannot be diagnosed on an ephemeral runner; the issue keeps the short reason."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "exit3")
    d = prepared(world, tmp_path)
    capsys.readouterr()
    assert cli("propose", "--dir", str(d)) == 0
    assert "  claude: Invalid API key" in capsys.readouterr().out
    assert cli("post", "--dir", str(d)) == 0
    assert "Invalid API key" not in issue_body(world)


def test_an_unreadable_proposals_file_is_not_generated_with_the_reason(world, tmp_path, fake_claude, monkeypatch):
    """AC-090.12: claude wrote something that is not JSON: `proposals.json: <why>`."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "bad")
    d = prepared(world, tmp_path)
    assert cli("propose", "--dir", str(d)) == 0
    assert (d / "proposals.error").read_text().startswith("proposals.json: ")
    assert cli("post", "--dir", str(d)) == 0
    assert "Proposals: not generated (proposals.json: " in issue_body(world)


def test_claude_that_is_not_installed_and_a_missing_report_are_reasons_not_crashes(world, tmp_path, fake_claude, monkeypatch, capsys):
    """AC-090.12: propose always exits 0 and writes the reason."""
    d = prepared(world, tmp_path)
    monkeypatch.setenv("CPLAT_CLAUDE", str(tmp_path / "nowhere" / "claude"))
    assert cli("propose", "--dir", str(d)) == 0
    assert (d / "proposals.error").read_text().strip() == "claude is not installed on this machine"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli("propose", "--dir", str(empty)) == 0
    assert (empty / "proposals.error").read_text().strip() == f"no report in {empty}"
    assert "proposals: not generated (no report in" in capsys.readouterr().out


def test_when_the_report_step_fails_nothing_is_created_or_changed(world, tmp_path):
    """AC-090.12: `cplat retro --out` fails (store down): non-zero, no report in the directory, no issue created or changed."""
    world.store.reachable = False
    d = tmp_path / "retro"
    assert cli("--out", str(d)) == 1
    assert not (d / "report.json").exists() and world.tracker.writes == []


def test_post_without_any_proposal_step_says_so(world, tmp_path):
    """AC-090.12: no proposals.json and no proposals.error."""
    d = prepared(world, tmp_path)
    assert cli("post", "--dir", str(d)) == 0
    assert "Proposals: not generated (no proposal step ran)" in issue_body(world)


# ---------------- AC-090.13 earlier retro issues ----------------

def test_earlier_open_retro_issues_get_one_comment_with_the_link_and_are_closed(world, capsys):
    """AC-090.13: open retro issues of earlier weeks: one comment linking the new issue, then closed; ascending order; the rest untouched."""
    t = world.tracker
    t.add_retro(5, "Weekly retro 2026-W41")
    t.add_retro(6, "Weekly retro 2026-W42")
    t.add_retro(7, "Weekly retro 2026-W40", state="closed")
    t.add_retro(8, "Weekly retro 2026-W44")
    t.add_retro(9, "Weekly retro 2026-W38", labels=("bug",))          # not a retro issue
    assert cli("post") == 0
    url = f"https://github.com/{PLATFORM}/issues/201"
    touched = [(c[0], c[2]) for c in t.calls if c[0] in ("comment", "close") ]
    assert touched == [("comment", 5), ("close", 5), ("comment", 6), ("close", 6)]
    comments = {c[2]: c[3] for c in t.calls if c[0] == "comment"}
    assert all(f"Superseded by the retro for {WEEK}: {url}" in text for text in comments.values())
    assert [i["number"] for i in t.retros if i["state"] == "closed"] == [5, 6, 7]
    assert t.get(8)["state"] == "open" and t.get(9)["state"] == "open" and t.get(9)["body"] == "old"
    names = [c[0] for c in t.calls]
    assert names.index("create") < names.index("comment")
    assert "closed 2 earlier retro issue(s)" in capsys.readouterr().out


def test_a_second_post_does_not_comment_again(world):
    """AC-090.13: the earlier issue is closed by the first post, so the second one leaves it alone."""
    world.tracker.add_retro(5, "Weekly retro 2026-W41")
    assert cli("post") == 0
    assert cli("post") == 0
    assert [c for c in world.tracker.calls if c[0] == "comment"] == [("comment", PLATFORM, 5, f"Superseded by the retro for {WEEK}: https://github.com/{PLATFORM}/issues/201")]
