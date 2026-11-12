"""Spec 180 acceptance tests: `cplat platform rules check` resolves the targets a prompt names (AC-180.1).

Seam: small trees under tmp_path; `promptrefs.problems(root, rel, text)` and `rulescheck.check(root)` (failure kinds
broken-link, broken-anchor, unknown-cplat, unknown-slash). The new modules are imported inside the tests."""
from rules_support import GOOD_BODY, PROMPT, Lazy, check, fv, good_repo, of_kind, prompt_text, put

promptrefs = Lazy("promptrefs")


def tree(tmp_path, extra=""):
    root = good_repo(tmp_path)
    # every .md under commands/ and references/ is a prompt: it carries the statement so that only the targets decide the check
    put(root, "plugins/svc/commands/other.md", prompt_text("# Other\n\n## First part\n\n## First part\n"))
    put(root, "plugins/svc/references/ref.md", prompt_text("# Ref\n"))
    return root


def probs(root, text, rel="plugins/svc/commands/demo.md"):
    return promptrefs.problems(root, rel, text)


def kinds_of(found):
    return sorted(p[0] for p in found)


def test_a_link_to_a_missing_file_is_a_broken_link_with_line_and_target_ac_180_1(tmp_path):  # AC-180.1
    root = tree(tmp_path)
    [(kind, line, raw, msg)] = probs(root, "intro\n\nSee [the ref](missing.md) now.\n")
    assert kind == "broken-link" and line == 3 and "missing.md" in msg


def test_links_to_existing_files_and_directories_resolve_ac_180_1(tmp_path):  # AC-180.1
    root = tree(tmp_path)
    text = ("[a](other.md) [b](../references/ref.md) [c](/plugins/svc/references/ref.md) [d](../references)\n"
            "[e](${CLAUDE_PLUGIN_ROOT}/references/ref.md) [w](https://example.com/x) [m](mailto:a@b.c)\n")
    assert probs(root, text) == []


def test_a_link_inside_code_is_not_read_ac_180_1(tmp_path):  # AC-180.1
    root = tree(tmp_path)
    assert probs(root, "Use `[x](nope.md)` here.\n\n```\n[y](nope2.md)\n```\n") == []


def test_a_plugin_root_path_that_does_not_exist_is_broken_ac_180_1(tmp_path):  # AC-180.1
    root = tree(tmp_path)
    found = probs(root, "Read `${CLAUDE_PLUGIN_ROOT}/references/gone.md`.\n")
    assert kinds_of(found) == ["broken-link"] and found[0][1] == 1
    assert probs(root, "Read `${CLAUDE_PLUGIN_ROOT}/references/ref.md`.\n") == []


def test_an_anchor_must_match_a_heading_slug_of_the_target_ac_180_1(tmp_path):  # AC-180.1
    root = tree(tmp_path)
    ok = "# Top `code` Title\n\n[a](#top-code-title) [b](other.md#first-part) [c](other.md#first-part-1)\n"
    assert probs(root, ok) == []
    found = probs(root, "# Top\n\n[a](#nothing) [b](other.md#nothing-here)\n")
    assert kinds_of(found) == ["broken-anchor", "broken-anchor"] and {p[1] for p in found} == {3}
    assert "nothing-here" in found[1][3] or "nothing-here" in found[0][3]


def test_headings_in_fences_are_no_anchors_ac_180_1(tmp_path):  # AC-180.1
    root = tree(tmp_path)
    assert kinds_of(probs(root, "```\n# Hidden\n```\n\n[a](#hidden)\n")) == ["broken-anchor"]


def test_a_cplat_command_that_is_not_offered_fails_ac_180_1(tmp_path):  # AC-180.1
    root = tree(tmp_path)
    found = probs(root, "Run `cplat component frobnicate` then `cplat nonesuch`.\n")
    assert kinds_of(found) == ["unknown-cplat", "unknown-cplat"]
    assert any("frobnicate" in p[3] for p in found) and any("nonesuch" in p[3] for p in found)


def test_offered_cplat_commands_pass_and_prose_is_not_read_ac_180_1(tmp_path):  # AC-180.1
    root = tree(tmp_path)
    text = ("Run `cplat component build`, `cplat platform rules check`, `cplat quiet test-fast`, `cplat runs` and\n"
            "`cplat instance promote|verify`.\n\n```bash\ncplat spec trace 1\n```\n\nThe cplat gizmo wobble is prose.\n")
    assert probs(root, text) == []
    assert kinds_of(probs(root, "`cplat instance promote|bogus`\n")) == ["unknown-cplat"]


def test_a_slash_command_no_plugin_defines_fails_ac_180_1(tmp_path):  # AC-180.1
    root = tree(tmp_path)
    found = probs(root, "Run /svc:other, then /svc:missing and /nop:other.\n")
    assert kinds_of(found) == ["unknown-slash", "unknown-slash"]
    assert any("/svc:missing" in p[3] for p in found)


def test_a_prompt_with_all_targets_present_passes_the_check_ac_180_1(tmp_path):  # AC-180.1
    root = tree(tmp_path)
    put(root, PROMPT, (root / PROMPT).read_text() + "\nSee [other](other.md#first-part) and `cplat platform rules check`, /svc:other.\n")
    res = check(root)
    assert of_kind(res, "broken-link") == [] and of_kind(res, "unknown-cplat") == [] and of_kind(res, "unknown-slash") == []
    assert res.ok, res.failures


def test_the_rules_check_reports_prompt_file_line_and_missing_target_ac_180_1(tmp_path):  # AC-180.1
    root = tree(tmp_path)
    text = (root / PROMPT).read_text()
    put(root, PROMPT, text + "\nSee [x](missing.md).\n\nRun `cplat component frobnicate` or /svc:missing.\n")
    res = check(root)
    n = len(text.splitlines())
    [link] = of_kind(res, "broken-link")
    [cp] = of_kind(res, "unknown-cplat")
    [sl] = of_kind(res, "unknown-slash")
    assert not res.ok
    assert (fv(link, "file"), fv(link, "line")) == (PROMPT, n + 2) and "missing.md" in fv(link, "message")
    assert (fv(cp, "file"), fv(cp, "line")) == (PROMPT, n + 4) and "frobnicate" in fv(cp, "message")
    assert fv(sl, "file") == PROMPT and "/svc:missing" in fv(sl, "message")


def test_only_limits_the_target_checks_to_the_prompts_in_scope_ac_180_1(tmp_path):  # AC-180.1
    root = tree(tmp_path)
    put(root, "plugins/svc/commands/other.md", prompt_text("See [x](missing.md).\n"))
    assert of_kind(check(root, only=[PROMPT]), "broken-link") == []
    assert len(of_kind(check(root, only=["plugins/svc/commands/other.md"]), "broken-link")) == 1
    assert GOOD_BODY
