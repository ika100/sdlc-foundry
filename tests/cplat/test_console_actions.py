"""Spec 122 acceptance tests: what the console does when the user confirms (AC-122.17, .18, .19, .21, .29, .36, .41, .44, .45, .46).

Contract: design.md "Console HTTP" (actions, 202/409/412/400) and the action-kind table. `actions.command_for(kind, object, args)`
returns `(argv, display, repo)`; the object is the `object` of a needs item and `args["level"]` is `component` or `system`.
Commands that would start `claude` are replaced by a stub process through `actions.command_for`; nothing reaches GitHub."""
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from console_support import ROOT, need, parse, q, disabled

STUB = r'''
import os, sys, time
print("=== step one: planning", flush=True)
open(sys.argv[3], "w").write(str(os.getpid()))
for _ in range(400):
    if os.path.exists(sys.argv[1]):
        break
    time.sleep(0.05)
print("opened https://github.com/acme/shop-api/pull/42", flush=True)
for i in range(30):
    print("line", i, flush=True)
sys.exit(int(sys.argv[2]))
'''
APPROVE_OBJ = need("approve", spec="013-search")["object"]
ESC_OBJ = need("escalation", spec="011-cart", object={"type": "run", "run_id": "r1", "spec": "011-cart"})["object"]
ISSUE_OBJ = need("triage", spec="57", object={"type": "issue", "issue": 57, "spec": None})["object"]
RELEASE_OBJ = need("promote", object={"type": "release", "spec": None, "component": "shop-api", "version": "1.4.0"})["object"]


def make_exe(path: Path, body: str) -> Path:
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture()
def ready(tmp_path, monkeypatch):
    """claude and gh on the PATH (stubs), a workspace with a clone of acme/shop-api that has an allowlist."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    claude = make_exe(bindir / "claude", 'echo "$@" > "$(dirname "$0")/claude.args"\ncat "$(dirname "$0")/claude.out" 2>/dev/null || true')
    make_exe(bindir / "gh", "exit 0")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("CPLAT_CLAUDE", str(claude))
    ws = tmp_path / "ws"
    for name in ("shop-api", "shop-gitops"):
        (ws / name / ".claude").mkdir(parents=True)
        (ws / name / ".claude" / "settings.json").write_text("{}")
        subprocess.run(["git", "init", "-q", str(ws / name)], check=True)
        subprocess.run(["git", "-C", str(ws / name), "remote", "add", "origin", f"https://github.com/acme/{name}.git"], check=True)
    conf = tmp_path / "config" / "sdlc-foundry"
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "settings.yml").write_text(yaml.safe_dump({"workspace": str(ws)}))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    r = type("Ready", (), {})()
    r.bin, r.ws, r.claude, r.go, r.pidfile = bindir, ws, claude, tmp_path / "go", tmp_path / "pid"
    return r


def stub_command(monkeypatch, ready, code=0, display="cplat headless '/component:spec approve 013'"):
    from console import actions
    monkeypatch.setattr(actions, "command_for", lambda kind, obj, args, repo_dir=None: (
        [sys.executable, "-c", STUB, str(ready.go), str(code), str(ready.pidfile)], display, "acme/shop-api"))


def post_action(c, kind="approve", obj=APPROVE_OBJ, **args):
    return c.json("POST", "/api/actions", {"kind": kind, "object": obj, "args": {"level": "component", **args}})


def finish(ready):
    ready.go.write_text("go")


# ---------------- AC-122.18: the exact command ----------------

def cf(kind, obj, **args):
    from console import actions
    return actions.command_for(kind, obj, {"level": "component", **args})


@pytest.mark.parametrize("kind, obj, args, needles", [
    ("approve", APPROVE_OBJ, {}, ["/component:spec approve 013"]),
    ("approve", APPROVE_OBJ, {"level": "system"}, ["/system:spec approve 013"]),
    ("approve-ship", APPROVE_OBJ, {"budget": "15"}, ["/component:spec approve 013", "/component:ship 013", "cost=15"]),
    ("request-changes", APPROVE_OBJ, {"comment": "Please cap it"}, ["/component:spec --amend 013", "Please cap it"]),
    ("answer", APPROVE_OBJ, {"answers": "limit: 50 per user"}, ["/component:spec --amend 013", "answers to open questions:", "limit: 50 per user"]),
    ("promote", RELEASE_OBJ, {"to": "prod"}, ["/instance:promote shop-api --to prod --version 1.4.0"]),
    ("more-budget", ESC_OBJ, {"limit": "cost", "value": "30"}, ["/component:ship 011", "cost=30"]),
    ("amend", ESC_OBJ, {"text": "drop the retry"}, ["/component:spec --amend 011 drop the retry"]),
    ("fix", ISSUE_OBJ, {}, ["/component:fix #57"]),
    ("make-spec", ISSUE_OBJ, {}, ["/component:spec #57"]),
    ("dismiss", ISSUE_OBJ, {"reason": "not our bug"},
     ["/issue:triage 57 dismiss as wontfix: not our bug (confirmed by the user in the console)"]),
    ("cut-release", RELEASE_OBJ, {}, ["/component:release"]),
    ("describe", {"repo": "acme/shop-gitops"}, {"level": "system", "text": "add a wishlist"}, ["/system:spec add a wishlist"]),
    ("describe", {"repo": "acme/shop-api"}, {"level": "component", "text": "add a wishlist"}, ["/component:spec add a wishlist"]),
    ("describe", {"repo": "acme/shop-api"}, {"level": "decide", "text": "add a wishlist"}, ["Let Claude decide: add a wishlist"]),
    ("model", {"repo": "acme/shop-gitops"}, {"command": "/component:add todo-api --provides orders:grpc"}, ["/component:add todo-api --provides orders:grpc"]),
])
def test_every_action_runs_its_exact_command_through_headless_ac_122_18(ready, kind, obj, args, needles):  # AC-122.18
    argv, display, repo = cf(kind, obj, **args)
    for n in needles:
        assert n in display, (n, display)
    assert "headless" in argv and "--repo" in argv
    assert any(needles[0] in a for a in argv), argv
    assert repo == obj["repo"]
    assert str(ready.ws / obj["repo"].split("/")[1]) in argv


def test_only_ship_runs_use_more_than_one_session_ac_122_18(ready):  # AC-122.18
    for kind, obj, args in (("approve", APPROVE_OBJ, {}), ("fix", ISSUE_OBJ, {}), ("promote", RELEASE_OBJ, {"to": "prod"}), ("cut-release", RELEASE_OBJ, {})):
        argv, _, _ = cf(kind, obj, **args)
        i = argv.index("--max-runs")
        assert argv[i + 1] == "1", kind
    for kind, obj, args in (("approve-ship", APPROVE_OBJ, {"budget": "15"}), ("more-budget", ESC_OBJ, {"limit": "cost", "value": "30"})):
        argv, _, _ = cf(kind, obj, **args)
        assert "--max-runs" not in argv or argv[argv.index("--max-runs") + 1] != "1"


def test_the_budget_is_passed_as_a_headless_budget_flag_ac_122_17(ready):  # AC-122.17
    argv, _, _ = cf("approve-ship", APPROVE_OBJ, budget="15")
    assert "--budget" in argv and argv[argv.index("--budget") + 1] == "cost=15"


def test_the_clone_action_runs_gh_repo_clone_directly_ac_122_29(ready):  # AC-122.29
    argv, display, _ = cf("clone", {"repo": "acme/other-gitops"})
    assert argv == ["gh", "repo", "clone", "acme/other-gitops", str(ready.ws / "other-gitops")]
    assert "headless" not in argv


def test_the_console_code_never_calls_kubectl_or_writes_a_repo_itself_ac_122_18():  # AC-122.18
    mods = sorted((ROOT / "scripts" / "cplat" / "console").glob("*.py"))
    assert len(mods) > 5
    for f in mods:
        text = f.read_text()
        assert not re.search(r"""["']kubectl["']""", text), f.name
        assert not re.search(r"""["'](push|commit|checkout|reset|merge)["']\s*[,\]]""", text), f.name


def test_nothing_runs_until_the_user_confirms_ac_122_18(console, ready, monkeypatch):  # AC-122.18
    stub_command(monkeypatch, ready)
    c = console()
    for path in ("/inbox", "/board", "/system", "/panel/need/" + "approve%3Aacme%2Fshop-api%3A013-search"):
        c.get(path)
    assert c.json("GET", "/api/actions") == (200, [])


def test_an_action_without_the_token_is_refused_ac_122_18(console, ready, monkeypatch):  # AC-122.18
    stub_command(monkeypatch, ready)
    c = console()
    st, _ = c.json("POST", "/api/actions", {"kind": "approve", "object": APPROVE_OBJ, "args": {"level": "component"}}, token=False)
    assert st == 403 and c.json("GET", "/api/actions")[1] == []


def test_a_confirmed_action_returns_202_and_runs_in_the_background_ac_122_18(console, ready, monkeypatch):  # AC-122.18
    stub_command(monkeypatch, ready)
    c = console()
    st, body = post_action(c)
    assert st == 202 and body["id"]
    a = c.json("GET", f"/api/actions/{body['id']}")[1]
    assert a["state"] == "running" and a["command"] == "cplat headless '/component:spec approve 013'" and a["repo"] == "acme/shop-api"
    finish(ready)
    c.wait_action(body["id"])


def test_an_unknown_kind_is_a_400_ac_122_18(console, ready):  # AC-122.18
    st, body = post_action(console(), kind="rm-rf")
    assert st == 400 and "error" in body


# ---------------- AC-122.41: prerequisites ----------------

def test_without_claude_an_action_is_refused_with_412_naming_it_ac_122_41(console, ready, monkeypatch):  # AC-122.41
    (ready.bin / "claude").unlink()
    monkeypatch.delenv("CPLAT_CLAUDE", raising=False)
    monkeypatch.setenv("PATH", str(ready.bin))
    st, body = post_action(console())
    assert st == 412 and body["needs"] == "claude" and "error" in body


def test_without_a_clone_an_action_is_refused_naming_the_repo_ac_122_41(console, ready):  # AC-122.41
    import shutil
    shutil.rmtree(ready.ws / "shop-api")
    st, body = post_action(console())
    assert st == 412 and body["needs"] == "clone:acme/shop-api"


def test_a_clone_without_an_allowlist_is_refused_ac_122_41(console, ready):  # AC-122.41
    (ready.ws / "shop-api" / ".claude" / "settings.json").unlink()
    st, body = post_action(console())
    assert st == 412 and body["needs"] == "clone:acme/shop-api"


def test_prerequisites_lists_what_is_missing_ac_122_41(ready, monkeypatch):  # AC-122.41
    from console import actions
    assert actions.prerequisites("approve", APPROVE_OBJ, dict(os.environ)) == []
    monkeypatch.setenv("PATH", str(ready.bin.parent / "nothing"))
    monkeypatch.delenv("CPLAT_CLAUDE", raising=False)
    missing = actions.prerequisites("approve", APPROVE_OBJ, dict(os.environ))
    assert "claude" in missing and "gh" in missing


def test_clone_resolution_finds_a_valid_sibling_of_the_gitops_clone(ready, tmp_path, monkeypatch):
    from console import actions

    home = tmp_path / "home"
    home.mkdir()
    config = tmp_path / "config"
    (config / "sdlc-foundry").mkdir(parents=True)
    (config / "sdlc-foundry" / "settings.yml").write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    gitops = tmp_path / "project" / "project-gitops"
    sibling = tmp_path / "project" / "shop-api"
    gitops.mkdir(parents=True)
    (sibling / ".claude").mkdir(parents=True)
    (sibling / ".claude" / "settings.json").write_text("{}")
    subprocess.run(["git", "init", "-q", str(sibling)], check=True)
    subprocess.run(["git", "-C", str(sibling), "remote", "add", "origin", "https://github.com/acme/shop-api.git"], check=True)

    argv, _, _ = actions.command_for("approve", APPROVE_OBJ, {"level": "component"}, repo_dir=gitops)
    assert str(sibling) in argv
    assert actions.prerequisites("approve", APPROVE_OBJ, dict(os.environ), {"level": "component"}, repo_dir=gitops) == []


def test_clone_resolution_checks_home_src_after_a_missing_sibling_without_workspace(tmp_path, monkeypatch):
    from console import actions

    home = tmp_path / "home"
    home.mkdir()
    config = tmp_path / "config"
    (config / "sdlc-foundry").mkdir(parents=True)
    (config / "sdlc-foundry" / "settings.yml").write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))

    gitops = tmp_path / "project" / "project-gitops"
    fallback = home / "src" / "shop-api"
    gitops.mkdir(parents=True)
    (fallback / ".claude").mkdir(parents=True)
    (fallback / ".claude" / "settings.json").write_text("{}")
    subprocess.run(["git", "init", "-q", str(fallback)], check=True)
    subprocess.run(
        ["git", "-C", str(fallback), "remote", "add", "origin", "https://github.com/acme/shop-api.git"],
        check=True,
    )

    assert actions.clone_of("acme/shop-api", repo_dir=gitops) == fallback
    assert actions.prerequisites(
        "approve", APPROVE_OBJ, dict(os.environ), {"level": "component"}, repo_dir=gitops
    ) == []


def test_clone_resolution_rejects_a_sibling_with_the_wrong_origin(ready, tmp_path, monkeypatch):
    from console import actions

    home = tmp_path / "home"
    home.mkdir()
    config = tmp_path / "config"
    (config / "sdlc-foundry").mkdir(parents=True)
    (config / "sdlc-foundry" / "settings.yml").write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    gitops = tmp_path / "project" / "project-gitops"
    sibling = tmp_path / "project" / "shop-api"
    gitops.mkdir(parents=True)
    (sibling / ".claude").mkdir(parents=True)
    (sibling / ".claude" / "settings.json").write_text("{}")
    subprocess.run(["git", "init", "-q", str(sibling)], check=True)
    subprocess.run(["git", "-C", str(sibling), "remote", "add", "origin", "https://github.com/acme/not-shop-api.git"], check=True)

    assert actions.prerequisites("approve", APPROVE_OBJ, dict(os.environ), {"level": "component"}, repo_dir=gitops) == ["clone:acme/shop-api"]

# ---------------- AC-122.44: the actions you started ----------------

def test_a_running_action_shows_command_step_and_the_indicator_ac_122_44(console, ready, monkeypatch):  # AC-122.44
    stub_command(monkeypatch, ready)
    c = console()
    _, body = post_action(c)
    for _ in range(100):
        a = c.json("GET", f"/api/actions/{body['id']}")[1]
        if a["step"]:
            break
        time.sleep(0.1)
    assert a["state"] == "running" and "planning" in a["step"] and a["ended_at"] is None and a["started_at"]
    assert c.json("GET", "/api/state")[1]["actions"] == {"running": 1, "failed": 0}
    for path in ("/inbox", "/board", "/system"):
        root, _ = c.page(path)
        [ind] = q(root, "button", data_activity=True)
        assert (ind.attrs["data-running"], ind.attrs["data-failed"]) == ("1", "0")
    finish(ready)
    c.wait_action(body["id"])


def test_a_successful_action_links_to_the_run_and_the_pull_request_ac_122_44(console, ready, monkeypatch):  # AC-122.44
    stub_command(monkeypatch, ready)
    c = console()
    _, body = post_action(c)
    finish(ready)
    a = c.wait_action(body["id"])
    assert a["state"] == "done" and a["links"]["pr"] == "https://github.com/acme/shop-api/pull/42" and "run" in a["links"]
    assert c.json("GET", "/api/state")[1]["actions"] == {"running": 0, "failed": 0}


def test_a_failed_action_has_the_reason_and_the_last_lines_ac_122_44(console, ready, monkeypatch):  # AC-122.44
    stub_command(monkeypatch, ready, code=1)
    c = console()
    _, body = post_action(c)
    finish(ready)
    a = c.wait_action(body["id"])
    assert a["state"] == "failed" and a["reason"]
    assert 0 < len(a["tail"]) <= 20 and a["tail"][-1].endswith("29")
    assert c.json("GET", "/api/state")[1]["actions"] == {"running": 0, "failed": 1}
    root, _ = c.page("/inbox")
    assert q(root, "button", data_activity=True)[0].attrs["data-failed"] == "1"


def test_retry_starts_the_same_command_again_ac_122_44(console, ready, monkeypatch):  # AC-122.44
    stub_command(monkeypatch, ready, code=1)
    c = console()
    _, first = post_action(c)
    finish(ready)
    old = c.wait_action(first["id"])
    ready.go.unlink()
    st, again = c.json("POST", f"/api/actions/{first['id']}/retry")
    assert st == 202 and again["id"] != first["id"]
    finish(ready)
    new = c.wait_action(again["id"])
    assert new["command"] == old["command"]
    assert [a["id"] for a in c.json("GET", "/api/actions")[1]].count(again["id"]) == 1


def test_the_activity_panel_offers_retry_and_open_in_claude_code_ac_122_44():  # AC-122.44
    js = (ROOT / "scripts" / "cplat" / "console" / "static" / "console.js").read_text()
    assert "Retry" in js and "Open in Claude Code" in js and "/api/actions" in js and "/api/open-in-claude" in js


# ---------------- AC-122.45: one action per object ----------------

def test_a_second_action_on_the_same_object_is_refused_until_the_first_ends_ac_122_45(console, ready, monkeypatch):  # AC-122.45
    stub_command(monkeypatch, ready)
    c = console()
    _, first = post_action(c, "approve")
    st, body = post_action(c, "approve-ship", budget="15")
    assert st == 409 and "error" in body
    other = dict(APPROVE_OBJ, spec="099-other")
    assert post_action(c, "approve", other)[0] == 202
    finish(ready)
    c.wait_action(first["id"])
    assert post_action(c, "approve")[0] == 202
    finish(ready)


def test_the_object_shows_its_other_actions_disabled_and_says_so_ac_122_45(console, ready, monkeypatch):  # AC-122.45
    stub_command(monkeypatch, ready)
    c = console()
    _, first = post_action(c, "approve")
    root, _ = c.panel("need", "approve:acme/shop-api:013-search")
    for kind in ("approve-ship", "approve", "request-changes"):
        [btn] = q(root, "button", data_action=kind)
        assert disabled(btn), kind
    assert "running" in " ".join(r.text() for r in q(root, "span", data_disabled_reason=True)).lower()
    finish(ready)
    c.wait_action(first["id"])
    root, _ = c.panel("need", "approve:acme/shop-api:013-search")
    assert not disabled(q(root, "button", data_action="approve")[0])


# ---------------- AC-122.46: stopping ----------------

def test_stopping_with_a_running_action_lists_it_and_asks_first_ac_122_46(console, ready, monkeypatch):  # AC-122.46
    stub_command(monkeypatch, ready)
    c = console()
    _, a = post_action(c)
    st, body = c.json("POST", "/api/shutdown", {"confirm": False})
    assert st == 409 and body["running"] and "cplat headless" in json.dumps(body["running"])
    assert c.json("GET", f"/api/actions/{a['id']}")[1]["state"] == "running"
    finish(ready)
    c.wait_action(a["id"])


def test_a_confirmed_stop_ends_the_actions_and_the_next_start_shows_them_stopped_ac_122_46(console, ready, monkeypatch):  # AC-122.46
    stub_command(monkeypatch, ready)
    c = console()
    _, a = post_action(c)
    for _ in range(100):
        if ready.pidfile.exists() and ready.pidfile.read_text():
            break
        time.sleep(0.1)
    pid = int(ready.pidfile.read_text())
    st, _ = c.json("POST", "/api/shutdown", {"confirm": True})
    assert st == 202
    for _ in range(150):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("the action's process is still running")
    again = console(repo_dir=c.repo_dir)
    assert next(x for x in again.json("GET", "/api/actions")[1] if x["id"] == a["id"])["state"] == "stopped"


def test_stopping_without_actions_needs_no_confirmation_ac_122_46(console, ready):  # AC-122.46
    assert console().json("POST", "/api/shutdown", {"confirm": False})[0] == 202


# ---------------- AC-122.19: describe a change ----------------

def test_describe_runs_the_spec_command_with_the_sentence_ac_122_19(console, ready, monkeypatch):  # AC-122.19
    c = console()
    from console import actions
    seen = []
    real = actions.command_for
    monkeypatch.setattr(actions, "command_for", lambda kind, obj, args, repo_dir=None: seen.append(real(kind, obj, args, repo_dir)) or (
        [sys.executable, "-c", "print('ok')"], seen[-1][1], seen[-1][2]))
    st, body = c.json("POST", "/api/actions", {"kind": "describe", "object": {"repo": "acme/shop-gitops"},
                                               "args": {"level": "system", "text": "add a wishlist"}})
    assert st == 202
    c.wait_action(body["id"])
    assert "/system:spec add a wishlist" in seen[0][1]


def test_the_palette_shows_open_issues_that_match_the_sentence_before_confirming_ac_122_19(console):  # AC-122.19
    st, text = console().get("/palette?q=fix%20the%20checkout%205xx%20alert")
    assert st == 200 and "#57" in text and "Let Claude decide" in text
    assert "System" in text and "Component" in text


def test_a_new_draft_appears_on_the_board_in_spec_and_in_the_inbox_ac_122_19(console):  # AC-122.19
    from console_support import needs_json, spec_row, specs_json
    c = console()
    rows = specs_json() + [spec_row("017-wishlist-2", "draft", title="Wishlist two")]
    c.set("specs:acme/shop-api", rows)
    doc = needs_json()
    doc["items"].append(need("approve", spec="017-wishlist-2", reason="draft without open questions; fresh", since="2026-10-26T07:00:00Z"))
    c.set("needs", doc)
    board, _ = c.page("/board")
    [spec_col] = [col for col in q(board, None, data_column="Spec")]
    assert "Wishlist two" in spec_col.text()
    inbox, _ = c.page("/inbox")
    assert any("017-wishlist-2" in r.attrs["data-need"] for r in q(inbox, None, data_need=True))


# ---------------- AC-122.21: ask ----------------

def test_ask_answers_with_read_only_tools_and_proposes_commands_without_running_them_ac_122_21(console, ready):  # AC-122.21
    (ready.bin / "claude.out").write_text("Two replicas would help.\n\n```command\n/component:set shop-api --replicas 2\n```\n")
    c = console()
    st, body = c.json("POST", "/api/ask", {"question": "why is shop-api slow?"})
    assert st == 200 and "Two replicas would help." in body["answer"]
    [s] = body["suggestions"]
    assert s["command"] == "/component:set shop-api --replicas 2" and "diff" in s and "repo" in s
    args = (ready.bin / "claude.args").read_text()
    assert " -p " in f" {args}" or args.startswith("-p")
    tools = re.search(r"--allowedTools\s+(.+?)(?:\s--|\s*$)", args).group(1)
    assert "Read" in tools and not re.search(r"Write|Edit|git push|kubectl|NotebookEdit", tools)
    assert c.json("GET", "/api/actions")[1] == []


def test_ask_needs_the_token_ac_122_21(console, ready):  # AC-122.21
    assert console().json("POST", "/api/ask", {"question": "x"}, token=False)[0] == 403


def test_a_suggestion_runs_only_through_the_confirmed_action_path_ac_122_21(console, ready, monkeypatch):  # AC-122.21
    stub_command(monkeypatch, ready)
    c = console()
    st, body = c.json("POST", "/api/actions", {"kind": "model", "object": {"repo": "acme/shop-gitops"},
                                               "args": {"level": "system", "command": "/component:set shop-api --replicas 2"}})
    assert st == 202
    finish(ready)
    c.wait_action(body["id"])


# ---------------- AC-122.29: the system switcher ----------------

class Gh:
    def __init__(self):
        self.calls = []
        self.repos = {"bob": [("bob/dev-gitops", True), ("bob/notes", False)], "acme": [("acme/shop-gitops", True), ("acme/other", False)]}

    def __call__(self, args):
        self.calls.append(list(args))
        jq = args[args.index("-q") + 1] if "-q" in args else (args[args.index("--jq") + 1] if "--jq" in args else None)
        if args[:2] == ["api", "user"]:
            return "bob" if jq else json.dumps({"login": "bob"})
        if args[:2] == ["api", "user/orgs"]:
            return "acme" if jq else json.dumps([{"login": "acme"}])
        if args[:2] == ["repo", "list"]:
            owner = args[2]
            rows = [r for r, topic in self.repos[owner] if topic or "gitops-app" not in args]
            return "\n".join(rows) if jq else json.dumps([{"nameWithOwner": r} for r in rows])
        return ""


def test_the_switcher_lists_gitops_app_repos_of_the_account_and_its_organisations_ac_122_29(tmp_path, ready, monkeypatch):  # AC-122.29
    from console import switcher
    gh = Gh()
    monkeypatch.setattr(switcher, "gh", gh)
    (ready.ws / "shop-gitops" / "applications").mkdir()
    entries = switcher.list_systems()
    assert {e["repo"] for e in entries} == {"bob/dev-gitops", "acme/shop-gitops"}
    assert all("gitops-app" in c for c in gh.calls if c[:2] == ["repo", "list"])


def test_choosing_a_system_opens_its_clone_or_offers_to_clone_first_ac_122_29(tmp_path, ready, monkeypatch):  # AC-122.29
    from console import switcher
    monkeypatch.setattr(switcher, "gh", Gh())
    by_repo = {e["repo"]: e for e in switcher.list_systems()}
    have, missing = by_repo["acme/shop-gitops"], by_repo["bob/dev-gitops"]
    assert have["clone"] == str(ready.ws / "shop-gitops") and have["action"] == "open"
    assert missing["clone"] is None and missing["action"] == "clone"


def test_switcher_finds_system_clone_in_home_src_by_origin_without_component_allowlist(tmp_path, monkeypatch):
    from console import switcher

    home = tmp_path / "home"
    home.mkdir()
    config = tmp_path / "config"
    (config / "sdlc-foundry").mkdir(parents=True)
    (config / "sdlc-foundry" / "settings.yml").write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))

    gitops = tmp_path / "projects" / "project-gitops"
    system = home / "src" / "shop-gitops"
    gitops.mkdir(parents=True)
    system.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(system)], check=True)
    subprocess.run(
        ["git", "-C", str(system), "remote", "add", "origin", "https://github.com/acme/shop-gitops.git"],
        check=True,
    )
    monkeypatch.setattr(switcher, "gh", Gh())

    entries = switcher.list_systems(repo_dir=gitops)
    found = next(entry for entry in entries if entry["repo"] == "acme/shop-gitops")
    assert found == {"repo": "acme/shop-gitops", "clone": str(system), "action": "open"}


def test_clone_resolution_accepts_ssh_url_remotes(ready, tmp_path, monkeypatch):
    from console import actions

    home = tmp_path / "home"
    home.mkdir()
    config = tmp_path / "config"
    (config / "sdlc-foundry").mkdir(parents=True)
    (config / "sdlc-foundry" / "settings.yml").write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    gitops = tmp_path / "project" / "project-gitops"
    sibling = tmp_path / "project" / "shop-api"
    gitops.mkdir(parents=True)
    (sibling / ".claude").mkdir(parents=True)
    (sibling / ".claude" / "settings.json").write_text("{}")
    subprocess.run(["git", "init", "-q", str(sibling)], check=True)
    subprocess.run(["git", "-C", str(sibling), "remote", "add", "origin", "ssh://git@github.com/acme/shop-api.git"], check=True)

    assert actions.clone_of("acme/shop-api", repo_dir=gitops) == sibling


def test_configured_workspace_keeps_accepting_fork_origins(ready, monkeypatch):
    from console import actions

    clone = ready.ws / "shop-api"
    subprocess.run(
        ["git", "-C", str(clone), "remote", "set-url", "origin", "https://github.com/my-fork/shop-api.git"],
        check=True,
    )

    assert actions.clone_of("acme/shop-api", repo_dir=ready.ws / "shop-gitops") == clone
    assert actions.prerequisites(
        "approve", APPROVE_OBJ, dict(os.environ), {"level": "component"}, repo_dir=ready.ws / "shop-gitops"
    ) == []
