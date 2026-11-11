"""Spec 180 acceptance tests: a test file may not pin prompt wording (AC-180.2, AC-180.3).

Seam: a tree under tmp_path with a plugin prompt and test files under `tests/`; `promptpins.scan(root)` and the check
(failure kinds sentence-pin, short-interface, stray-interface)."""
from rules_support import PROMPT, Lazy, check, fv, good_repo, of_kind, put

promptpins = Lazy("promptpins")

WORDS = "the merge queue waits for a green build"      # 8 words
TEST = "tests/cplat/test_demo.py"


def tree(tmp_path, test_text):
    root = good_repo(tmp_path)
    put(root, PROMPT, (root / PROMPT).read_text() + f"\nNote that {WORDS} here.\n")
    put(root, TEST, test_text)
    return root


def scan_of(tmp_path, test_text):
    return promptpins.scan(tree(tmp_path, test_text))


def by_kind(scan, kind):
    return [f for f in scan.failures if f[0] == kind]


def test_a_literal_of_four_words_from_a_prompt_is_a_pin_ac_180_2(tmp_path):  # AC-180.2
    scan = scan_of(tmp_path, f'def test_x(text):\n    assert "{WORDS}" in text\n')
    [(kind, file, line, text, msg)] = scan.failures
    assert (kind, file, line, text) == ("sentence-pin", TEST, 2, WORDS)
    assert "interface" in msg and "structure" in msg and scan.interface_pins == 0


def test_whitespace_is_collapsed_and_implicit_concatenation_is_one_literal_ac_180_2(tmp_path):  # AC-180.2
    scan = scan_of(tmp_path, 'X = ("the merge queue waits"\n     "  for a green build")\n')
    [(kind, _, line, _, _)] = scan.failures
    assert kind == "sentence-pin" and line == 1


def test_short_unrelated_docstring_and_fstring_literals_are_no_pins_ac_180_2(tmp_path):  # AC-180.2
    text = (f'"""{WORDS}"""\n\n'
            f'def test_x():\n    """{WORDS}"""\n    a = "the merge queue"\n    b = "another long sentence that is in no prompt"\n'
            f'    c = f"{WORDS} {{a}}"\n')
    assert scan_of(tmp_path, text).failures == []


def test_a_file_that_does_not_parse_is_skipped_ac_180_2(tmp_path):  # AC-180.2
    assert scan_of(tmp_path, f'def broken(:\n    "{WORDS}"\n').failures == []


def test_a_marker_on_the_line_or_the_line_above_covers_the_pin_ac_180_2(tmp_path):  # AC-180.2
    text = (f'def test_x(t):\n    assert "{WORDS}" in t  # interface: the wording is the public contract\n'
            f'    # interface: the wording is the public contract\n    assert "{WORDS}" in t\n')
    scan = scan_of(tmp_path, text)
    assert scan.failures == [] and scan.interface_pins == 2


def test_a_marker_two_lines_away_does_not_cover_the_pin_ac_180_2(tmp_path):  # AC-180.2
    text = f'# interface: the wording is the public contract\n\nX = "{WORDS}"\n'
    scan = scan_of(tmp_path, text)
    assert sorted(f[0] for f in scan.failures) == ["sentence-pin", "stray-interface"]


def test_the_marker_covers_a_multi_line_literal_ac_180_2(tmp_path):  # AC-180.2
    text = 'X = ("the merge queue waits"\n     " for a green build")  # interface: public wording contract\n'
    scan = scan_of(tmp_path, text)
    assert scan.failures == [] and scan.interface_pins == 1


def test_a_marker_with_fewer_than_three_words_fails_ac_180_3(tmp_path):  # AC-180.3
    scan = scan_of(tmp_path, f'X = "{WORDS}"  # interface: too short\n')
    [(kind, file, line, text, msg)] = scan.failures        # the pin is neither counted nor reported again
    assert (kind, file, line) == ("short-interface", TEST, 1) and "3 words" in msg and scan.interface_pins == 0


def test_a_marker_on_a_line_without_a_prompt_literal_fails_ac_180_3(tmp_path):  # AC-180.3
    scan = scan_of(tmp_path, 'X = 1  # interface: nothing here pins anything\nY = "unrelated words in no prompt"  # interface: no pin on this line\n')
    assert [(f[0], f[1], f[2]) for f in scan.failures] == [("stray-interface", TEST, 1), ("stray-interface", TEST, 2)]


def test_the_rules_check_reports_pins_and_markers_with_file_and_line_ac_180_2(tmp_path):  # AC-180.3
    root = tree(tmp_path, f'A = "{WORDS}"\nB = "{WORDS}"  # interface: too short\nC = 1  # interface: no literal at all here\n')
    res = check(root)
    assert not res.ok
    assert [(fv(f, "file"), fv(f, "line")) for f in of_kind(res, "sentence-pin")] == [(TEST, 1)]
    assert [(fv(f, "file"), fv(f, "line")) for f in of_kind(res, "short-interface")] == [(TEST, 2)]
    assert [(fv(f, "file"), fv(f, "line")) for f in of_kind(res, "stray-interface")] == [(TEST, 3)]


def test_only_skips_the_global_pin_scan_ac_180_2(tmp_path):  # AC-180.2
    root = tree(tmp_path, f'A = "{WORDS}"\n')
    res = check(root, only=[PROMPT])
    assert of_kind(res, "sentence-pin") == [] and res.counts["interface_pins"] == 0


def test_the_counts_carry_targets_and_interface_pins_ac_180_2(tmp_path):  # AC-180.2
    root = tree(tmp_path, f'A = "{WORDS}"  # interface: the wording is public\n')
    res = check(root)
    assert res.ok, res.failures
    assert res.counts["interface_pins"] == 1 and res.counts["targets"] >= 0
