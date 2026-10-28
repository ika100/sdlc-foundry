"""Spec 122 verification fix round B: consequences before one-click actions, real stages, evidence and issues in the views."""
import re

from console_support import needs_json, q, row_of, run_row, runs_json, spec_row, specs_json, status_json


def cells(row):
    return {td.attrs["data-env"]: td for td in q(row, "td", data_env=True)}


def test_promote_and_cut_release_on_a_cell_open_their_panel_instead_of_acting_ac_122_8_47(console):
    c = console()
    doc = status_json()
    doc["rows"][0]["release_candidate"] = {"version": "1.5.0", "commits": 9, "specs": [], "fixes": [], "digest": "sha256:aaaa"}
    c.set("status", doc)
    root, _ = c.page("/system")
    staging = cells(row_of(root, "shop-api"))["staging"]
    [promote] = q(staging, "button", data_action="promote")
    assert promote.attrs["data-open"].startswith("/panel/need/promote") and "data-confirm" not in promote.attrs
    [cut] = q(staging, "button", data_action="cut-release")
    assert cut.attrs["data-open"].startswith("/panel/release/") and "data-confirm" not in cut.attrs
    panel, _ = c.panel("need", re.sub(r"^/panel/need/", "", promote.attrs["data-open"]).replace("%3A", ":").replace("%2F", "/"))
    assert q(panel, "button", data_action="promote")[0].attrs.get("data-confirm")


def test_a_resource_cell_without_state_is_derived_from_argo_ac_122_7(console):
    c = console()
    doc = status_json()
    doc["resources"] = [{"resource": "postgres", "cells": {"dev": {"argo": "Synced/Healthy"}, "staging": {"argo": "missing"},
                                                          "prod": {"argo": "unknown"}}}]
    c.set("status", doc)
    root, _ = c.page("/system")
    got = {env: td.attrs["data-state"] for env, td in cells(row_of(root, "postgres")).items() if "data-state" in td.attrs}
    assert got == {"dev": "healthy", "staging": "not deployed", "prod": "unknown"}


def test_edit_rules_names_its_environment_ac_122_7(console):
    root, text = console().page("/system")
    assert 'data-edit-env="staging"' in text and "{esc(" not in text


def test_a_slice_is_selectable_and_shows_its_own_run_ac_122_13(console):
    c = console()
    rows = specs_json()
    rows[0] = spec_row("012-checkout", "approved", level="system", slices=[{"repo": "acme/shop-api", "spec": "012-checkout", "status": "approved"}])
    c.set("specs:acme/shop-api", rows)
    runs = runs_json()
    runs["runs"].append(run_row(spec="012-checkout", repo="acme/shop-api", run_id="20261027T070000Z-bbbb2222",
                                activity=[{"at": "2026-10-27T07:30:00Z", "agent": "svc:coder", "text": "slice work"}]))
    c.set("runs", runs)
    root, _ = c.panel("spec", "012-checkout")
    [line] = q(root, None, data_slice=True)
    _, text = c.panel("slice", re.sub(r"^/panel/slice/", "", line.attrs["data-open"]).replace("%3A", ":").replace("%2F", "/"))
    assert "slice work" in text


def test_a_finished_spec_says_done_outside_the_stage_vocabulary_ac_122_32(console):
    c = console()
    rows = specs_json()
    rows[0] = spec_row("012-checkout", "done")
    c.set("specs:acme/shop-api", rows)
    root, text = c.panel("spec", "012-checkout")
    [line] = q(root, None, data_slice=True)
    assert "Done" in line.text() and not q(line, None, data_stage=True)


def test_untracked_issues_fill_the_issue_column_and_closed_ones_the_done_view_ac_122_10_48(console):
    c = console()
    doc = needs_json()
    doc["issues"] = [
        {"repo": "acme/shop-api", "number": 77, "title": "Cart total wrong", "labels": [], "state": "OPEN", "created_at": "2026-10-20T00:00:00Z",
         "closed_at": None, "url": "https://github.com/acme/shop-api/issues/77"},
        {"repo": "acme/shop-api", "number": 78, "title": "Typo in footer", "labels": [], "state": "CLOSED", "created_at": "2026-10-01T00:00:00Z",
         "closed_at": "2099-01-01T00:00:00Z", "url": "https://github.com/acme/shop-api/issues/78"}]
    c.set("needs", doc)
    root, _ = c.page("/board")
    [col] = [x for x in q(root, None, data_column=True) if x.attrs["data-column"] == "Issue"]
    assert "#77" in col.text() and "#78" not in col.text()
    _, done = c.page("/board?view=done&period=all")
    assert "#78" in done and "Typo in footer" in done
    _, found = c.page("/board?q=%2377")
    assert "Cart total wrong" in found


def test_the_board_shows_only_the_systems_repos_and_one_line_stop_reasons_ac_122_9(console):
    c = console()
    runs = runs_json()
    runs["runs"].append(run_row(spec="099-other", repo="acme/ai-ops", run_id="20261027T070000Z-cccc3333"))
    runs["runs"][1]["escalation"]["summary"] = "First line\nsecond line " + "x" * 300
    runs["runs"][1]["budget"]["used"]["cost"] = None
    c.set("runs", runs)
    root, text = c.page("/board")
    assert "ai-ops" not in text and "099-other" not in text
    assert "None" not in text and "cost unknown" in text.lower()
    assert "second line" not in text


def test_the_new_system_form_checks_the_manifest_and_shows_it_as_the_diff_ac_122_20(tmp_path, monkeypatch):
    from console import preview
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    bad = preview.preview(tmp_path, "system", {"name": "Bad Name", "owner": "acme", "component": "api", "type": "service", "lang": "python"})
    assert bad["valid"] is False and bad["checks"][0]["key"] == "system" and "kebab-case" in bad["checks"][0]["rule"]
    good = preview.preview(tmp_path, "system", {"name": "shop", "owner": "acme", "component": "shop-api", "type": "service", "lang": "python",
                                          "description": "Shop API"})
    assert good["checks"][0]["ok"], good["checks"]
    assert good["valid"] is True and "+system: shop" in good["diff"]


def test_a_sha_pin_is_shown_as_sha_and_seven_characters():
    from console.html import short_version
    assert short_version("sha-" + "a" * 40) == "sha-aaaaaaa" and short_version("1.4.0") == "1.4.0"


def test_a_missing_clone_falls_back_with_a_reason(tmp_path, monkeypatch):
    from console import actions, server
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "sdlc-foundry").mkdir()
    (tmp_path / "sdlc-foundry" / "settings.yml").write_text(f"workspace: {tmp_path / 'ws'}\n")
    clone = actions.clone_of("acme/shop-api")
    clone.mkdir(parents=True)

    class Fake:
        ctx = type("C", (), {"repo_dir": tmp_path})()

    assert server.Handler.claude_cwd(Fake, {"repo": "acme/shop-api"}) == (str(clone), "")
    cwd, note = server.Handler.claude_cwd(Fake, {"repo": "acme/other"})
    assert cwd == str(tmp_path) and "No local clone of acme/other" in note
