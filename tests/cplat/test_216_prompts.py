"""Spec 216 acceptance tests: the `/system:ship` instructions with the driver (AC-216.7, the prompt side of AC-216.10) and the
recordable part of the measure (AC-216.12).

By structure, as spec 168 and ADR-103 ask: the prompt names the `cplat` verbs and the output words it reacts to, in the order the spec
gives; the reference `ship-loop.md` holds today's loop; the register files hold entries (source `spec 216`) that quote the prompt;
`cplat platform rules check` passes. No sentence is pinned. AC-216.12 is measured on the first journey after the release
(`cplat platform runs journey measure`); what can be checked now is that the kill rule is written down where the spec says, as spec 126
and 131 did for their measurements.
"""
import re

import rulescheck
from prompts186_support import ROOT, collapsed, entries, prompt, sourced
from structure import headings, points_to

SHIP = "plugins/system/commands/ship.md"
LOOP = "plugins/system/references/ship-loop.md"
ENTRY = "plugins/system/references/ship-entry.md"
SHIP_BYTES_BEFORE = 7452              # bytes of ship.md at the branch base (4a217287), the size to end below
DRIVER_ONLY = re.compile(r"cplat system ship (next --json|repo start|repo resume|repo hold|land|phase complete|complete|finish)\b")
VERB = re.compile(r"cplat system ship (start|phase publish|drive|wait|next --json|next --wait|publish|repo start|repo resume|repo hold|"
                  r"phase complete|complete|finish|land|escalate)\b")
RESULTS = ("WAIT:", "TIMEOUT:", "ENTRY:", "ENDED:", "DONE:", "ESCALATED:", "STOPPED:")


def mentions(path):
    return [m.group(1) for m in VERB.finditer(prompt(path))]


def is_subsequence(wanted, found):
    it = iter(found)
    return all(w in it for w in wanted)


# ---------------- AC-216.7: the session's instructions ----------------

def test_the_session_runs_phase_publish_drive_and_wait_in_that_order_ac_216_7():  # AC-216.7
    assert is_subsequence(["start", "phase publish", "drive", "wait"], mentions(SHIP))
    assert (ROOT / LOOP).is_file()                                          # the loop the session no longer runs is in the reference


def test_the_session_reacts_to_every_result_of_the_wait_ac_216_7():  # AC-216.7
    text = prompt(SHIP)
    for word in RESULTS:
        assert word in text, word
    body = collapsed(text)
    assert re.search(r"three\b.*\bin a row", body) and "--cause environment" in body
    assert "cplat next --json" in body                                       # the hand-over after DONE:, ESCALATED: and STOPPED:


def test_the_session_builds_the_entry_and_follows_the_reference_for_it_ac_216_7():  # AC-216.7
    assert points_to(SHIP, "references/ship-entry.md") and (ROOT / ENTRY).is_file()
    assert "ENTRY:" in prompt(SHIP) and is_subsequence(["drive", "wait"], mentions(SHIP))        # the entry is built on the wait's result


def test_the_per_action_rules_moved_out_of_the_instructions_ac_216_7():  # AC-216.7
    assert "`action: " not in prompt(SHIP) and prompt(LOOP).count("`action: ") >= 6
    for old in ("Phase `publish`", "Phase `repos`", "Phase `complete`"):
        assert old not in headings(SHIP) and old in headings(LOOP), old


def test_the_session_is_not_told_to_run_the_drivers_verbs_ac_216_7():  # AC-216.7
    assert (ROOT / LOOP).is_file()
    units = [u for u in re.split(r"\n\s*\n|\n(?=\s*[-*] )", prompt(SHIP)) if DRIVER_ONLY.search(u)]
    for unit in units:                                    # a driver-only verb may be named only with the driver and its reason
        assert "driver" in unit.lower(), unit
    assert len(units) <= 1                                # listed once, not once per action


def test_the_instructions_read_at_the_start_end_shorter_than_before_ac_216_7():  # AC-216.7
    assert (ROOT / LOOP).is_file()
    assert len((ROOT / SHIP).read_bytes()) < SHIP_BYTES_BEFORE


def test_the_reference_holds_todays_loop_in_todays_order_ac_216_7():  # AC-216.7
    wanted = ["publish", "next --json", "repo start", "next --wait", "repo resume", "repo hold", "land", "phase complete", "complete",
              "finish"]
    assert (ROOT / LOOP).is_file(), f"{LOOP} is missing"
    assert is_subsequence(wanted, mentions(LOOP))
    body = collapsed(prompt(LOOP))
    assert re.search(r"three\b.*\bin a row", body) and "--cause environment" in body and "TIMEOUT:" in body and "WAIT:" in body
    assert points_to(LOOP, "references/ship-entry.md")


def test_the_changed_rules_have_register_entries_that_quote_the_instructions_ac_216_7():  # AC-216.7
    found = sourced(SHIP, "spec 216")
    assert found and all(e["class"] == "practice" for e in found)
    assert any("TIMEOUT" in e["text"] and "three" in e["text"] for e in found)


def test_the_moved_rules_keep_their_entries_in_the_reference_register_ac_216_7():  # AC-216.7
    moved = entries(LOOP)
    assert {"R9", "R11", "R14", "R16"} <= {e["id"] for e in moved}
    body = collapsed(prompt(LOOP))
    assert all(collapsed(str(e["text"])) in body for e in moved if e.get("class") != "retired")
    assert not {"R9", "R11", "R14", "R16"} & {e["id"] for e in entries(SHIP)}


def test_the_rule_register_checks_and_the_prompts_stay_within_their_size_ac_216_7():  # AC-216.7
    assert sourced(SHIP, "spec 216") and entries(LOOP)
    result = rulescheck.check(ROOT)
    assert result.ok, [f"{f.file}:{f.line} {f.kind}" for f in result.failures][:5]


# ---------------- AC-216.10: the switch, on the prompt side ----------------

def test_the_instructions_read_the_loop_reference_after_the_off_line_ac_216_10():  # AC-216.10
    text = prompt(SHIP)
    assert "driver: off" in text and points_to(SHIP, "references/ship-loop.md")
    body = collapsed(text)
    at = body.index("driver: off")
    assert "ship-loop.md" in body[max(0, at - 400):at + 400]                          # named next to the off line
    for heading in ("Phase `publish`", "Phase `repos`", "Phase `complete`"):
        assert heading in headings(LOOP), heading


def test_the_attended_answer_path_goes_through_the_switch_ac_216_10():  # AC-216.10
    assert "CPLAT_SYSTEM_DRIVER=0" in prompt(SHIP)



# ---------------- AC-216.12: the kill rule is written down ----------------

def test_the_adr_states_the_kill_rule_of_the_measure_ac_216_12():  # AC-216.12
    found = list((ROOT / "docs" / "adr").glob("*-a-system-ships-mechanical-loop-runs-in-cplat.md"))
    assert len(found) == 1, f"one ADR for the mechanical loop, found {found}"
    adr = found[0]
    text = collapsed(adr.read_text())
    assert "ADR-082" in text and "ADR-086" in text and "CPLAT_SYSTEM_DRIVER=0" in text
    for number in ("40", "4.0 M", "journey 23"):
        assert number in text, number
    assert "One spec for the whole system" in text and "journey measure" in text
    index = (ROOT / "docs" / "adr" / "README.md").read_text()
    assert adr.name in index


def test_the_changelog_fragment_names_the_switch_and_the_measure_ac_216_12():  # AC-216.12
    folder = ROOT / "docs" / "changelog.d"
    found = [*folder.glob("216-*.added.md"), *folder.glob("216-*.changed.md")]
    assert len(found) == 1, f"one changelog fragment for spec 216, found {found}"
    fragment = found[0]
    text = collapsed(fragment.read_text())
    assert "CPLAT_SYSTEM_DRIVER" in text and "measure" in text.lower()
