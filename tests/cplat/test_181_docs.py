"""Spec 181 AC-181.7: the performance record recommends the per-step table and carries the corrected split of journeys 9 and 10."""
import re
from pathlib import Path

PERF = (Path(__file__).resolve().parents[2] / "docs" / "PERFORMANCE.md").read_text()


def section(start: str, stop: str) -> str:
    i = PERF.index(start)
    return PERF[i:PERF.index(stop, i)]


def test_recording_a_journey_uses_the_measure_verb_and_the_steps_table_ac_181_7():  # AC-181.7
    text = PERF[PERF.index("## Recording a journey"):]
    assert "journey measure" in text and "--steps" in text


def test_a_note_under_the_wall_clock_table_corrects_journeys_9_and_10_ac_181_7():  # AC-181.7
    body = section("**Where the wall clock went**", "**CI on GitHub**")
    table_end = body.rindex("\n|")
    note = body[table_end:].split("\n", 1)[1]
    assert re.search(r"[Jj]ourneys? 9", note) and re.search(r"\b10\b", note) and re.search(r"correct|re-measured", note)
    for word in ("person", "agents", "coordinator", "children", "waiting"):
        assert word in note, word
    assert note.count("deploy") >= 1 and "CI" in note                              # waiting per kind


def test_the_existing_rows_of_journeys_9_and_10_stay_unchanged_ac_181_7():  # AC-181.7
    body = section("**Where the wall clock went**", "**CI on GitHub**")
    rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| (9|10) \|.*$", body, re.M)}
    assert rows["9"].startswith("| 9 | 4 (3 %): answers, the gaps until the next sentence and one reply; nothing blocked | 88 (63 %): deploys and Argo 50")
    assert rows["10"].startswith("| 10 | 4 (3 %): answers, the gaps until the next sentence and one reply; nothing blocked | 91 (66 %): deploys and Argo 48")
    assert len(rows) == 2                                                          # one row per journey: the correction is a note
