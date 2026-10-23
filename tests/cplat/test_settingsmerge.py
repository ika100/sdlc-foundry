"""Spec 086: merging the repo's permission entries into the template's .claude/settings.json (unit level)."""
import json

TEMPLATE = {
    "worktree": {"baseRef": "head"},
    "permissions": {"defaultMode": "default", "allow": ["Bash(cplat *)", "Bash(devbox run *)"], "ask": ["Bash(git push *)"], "deny": []},
}


def lists(d):
    return {k: d["permissions"].get(k, []) for k in ("allow", "ask", "deny")}


def merge(project, template=TEMPLATE, baseline=None):
    import settingsmerge
    return settingsmerge.merge_settings(project, template, baseline)


def test_repo_permission_entries_are_kept_after_the_templates():  # AC-086.10
    project = json.loads(json.dumps(TEMPLATE))
    project["permissions"]["allow"] += ["Bash(helm *)", "Bash(kubectl get *)"]
    project["permissions"]["ask"] += ["Bash(terraform apply *)"]
    project["permissions"]["deny"] += ["Bash(rm -rf *)"]
    merged, report = merge(project, baseline=TEMPLATE)
    assert lists(merged) == {"allow": ["Bash(cplat *)", "Bash(devbox run *)", "Bash(helm *)", "Bash(kubectl get *)"],
                             "ask": ["Bash(git push *)", "Bash(terraform apply *)"], "deny": ["Bash(rm -rf *)"]}
    assert report["kept"] == [{"list": "allow", "entry": "Bash(helm *)"}, {"list": "allow", "entry": "Bash(kubectl get *)"},
                              {"list": "ask", "entry": "Bash(terraform apply *)"}, {"list": "deny", "entry": "Bash(rm -rf *)"}]
    assert report["removed_by_platform"] == [] and report["replaced"] == []


def test_the_templates_entries_are_updated():  # AC-086.10
    template = json.loads(json.dumps(TEMPLATE))
    template["permissions"]["allow"].append("Bash(gh pr view *)")
    project = json.loads(json.dumps(TEMPLATE))
    project["permissions"]["allow"].append("Bash(helm *)")
    merged, _ = merge(project, template, baseline=TEMPLATE)
    assert "Bash(gh pr view *)" in merged["permissions"]["allow"] and "Bash(helm *)" in merged["permissions"]["allow"]


def test_an_entry_the_platform_removed_is_dropped_and_not_kept():  # AC-086.11
    baseline = json.loads(json.dumps(TEMPLATE))
    baseline["permissions"]["allow"].append("Bash(old *)")
    project = json.loads(json.dumps(baseline))
    project["permissions"]["allow"].append("Bash(helm *)")
    merged, report = merge(project, TEMPLATE, baseline)
    assert "Bash(old *)" not in merged["permissions"]["allow"] and "Bash(helm *)" in merged["permissions"]["allow"]
    assert report["removed_by_platform"] == [{"list": "allow", "entry": "Bash(old *)"}]
    assert report["kept"] == [{"list": "allow", "entry": "Bash(helm *)"}]


def test_without_a_baseline_nothing_is_removed():  # AC-086.11
    project = json.loads(json.dumps(TEMPLATE))
    project["permissions"]["allow"].append("Bash(old *)")
    merged, report = merge(project, TEMPLATE, None)
    assert "Bash(old *)" in merged["permissions"]["allow"] and report["removed_by_platform"] == []


def test_other_settings_the_repo_changed_are_replaced_and_reported():  # AC-086.12
    project = json.loads(json.dumps(TEMPLATE))
    project["worktree"] = {"baseRef": "main"}
    project["hooks"] = {"PreToolUse": []}
    project["permissions"]["defaultMode"] = "acceptEdits"
    merged, report = merge(project, TEMPLATE, TEMPLATE)
    assert merged["worktree"] == {"baseRef": "head"} and "hooks" not in merged and merged["permissions"]["defaultMode"] == "default"
    keys = {r["key"]: r["was"] for r in report["replaced"]}
    assert set(keys) == {"worktree", "hooks", "permissions.defaultMode"}
    assert json.loads(keys["worktree"]) == {"baseRef": "main"}


def test_settings_equal_to_the_baseline_are_a_template_change_not_a_loss():  # AC-086.12
    baseline = json.loads(json.dumps(TEMPLATE))
    baseline["worktree"] = {"baseRef": "main"}
    _, report = merge(json.loads(json.dumps(baseline)), TEMPLATE, baseline)
    assert report["replaced"] == []
    _, report = merge(json.loads(json.dumps(baseline)), TEMPLATE, None)
    assert [r["key"] for r in report["replaced"]] == ["worktree"]


def test_the_merged_file_keeps_the_templates_text(tmp_path):  # AC-086.10
    import settingsmerge
    text = json.dumps(TEMPLATE, indent=2) + "\n"
    (tmp_path / ".claude").mkdir()
    f = tmp_path / ".claude" / "settings.json"
    f.write_text(text)
    project = json.loads(text)
    project["permissions"]["allow"].append("Bash(helm *)")
    report, note = settingsmerge.merge_settings_file(tmp_path, json.dumps(project), TEMPLATE)
    out = f.read_text()
    assert note is None and report["kept"] == [{"list": "allow", "entry": "Bash(helm *)"}]
    assert json.loads(out)["permissions"]["allow"][-1] == "Bash(helm *)"
    assert all(line in out.splitlines() for line in text.splitlines() if line.strip().startswith('"Bash(cplat'))   # untouched lines


def test_invalid_project_json_keeps_the_template_and_says_how_to_recover(tmp_path):  # AC-086.12
    import settingsmerge
    text = json.dumps(TEMPLATE, indent=2) + "\n"
    (tmp_path / ".claude").mkdir()
    f = tmp_path / ".claude" / "settings.json"
    f.write_text(text)
    _, note = settingsmerge.merge_settings_file(tmp_path, "{ not json", None)
    assert f.read_text() == text
    assert note.startswith(".claude/settings.json was not valid JSON: replaced by the template's file") and "git show HEAD~1:.claude/settings.json" in note
