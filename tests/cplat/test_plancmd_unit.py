"""Unit tests of `plancmd` (spec 186): the dependant rewrite, the cycle refusal and the hand-back line."""
import pytest

import plancmd
import runs_built
from core import PlatformError


def tasks():
    return [
        {"id": "t1", "files": ["a.py"], "covers": ["AC-1.1"], "depends_on": [], "parallel_safe": True},
        {"id": "t2", "files": ["b.py"], "covers": ["AC-1.2"], "depends_on": ["t1"], "parallel_safe": True},
        {"id": "t3", "files": ["c.py"], "covers": [], "depends_on": ["t1", "t2"], "parallel_safe": False},
        {"id": "t4", "files": ["d.py"], "covers": [], "depends_on": ["t1"], "parallel_safe": True},
    ]


def test_dependants_of_the_merged_task_move_to_the_target_without_duplicates():
    new, merged, moved = plancmd.merged_tasks(tasks(), "t1", "t2")
    by = {t["id"]: t for t in new}
    assert "t1" not in by and moved == ["t3", "t4"]
    assert by["t3"]["depends_on"] == ["t2"] and by["t4"]["depends_on"] == ["t2"]
    assert merged["files"] == ["b.py", "a.py"] and merged["depends_on"] == []


def test_a_merge_through_a_task_between_them_is_a_cycle_and_is_refused():
    new, merged, _ = plancmd.merged_tasks(tasks(), "t1", "t3")
    with pytest.raises(PlatformError, match="cycle"):
        plancmd._settle_parallel(new, {**merged, "parallel_safe": True})


def test_the_merged_task_loses_parallel_safe_when_it_shares_a_file_with_a_sibling():
    ts = [{"id": "t1", "files": ["a.py"], "depends_on": []},
          {"id": "t2", "files": ["b.py"], "depends_on": ["t1"], "parallel_safe": True},
          {"id": "t3", "files": ["a.py"], "depends_on": [], "parallel_safe": True}]
    new, merged, _ = plancmd.merged_tasks(ts, "t1", "t2")
    plancmd._settle_parallel(new, merged)
    assert merged["parallel_safe"] is False


def test_the_hand_back_line_names_both_tasks_and_the_reason():
    f = {"run_id": "r1", "kind": "build", "wall": "1m", "runs": 1, "execution": "x", "replans": 0, "ci_rounds": 0, "reruns": 0,
         "gates": "none", "budget": "budget: x", "agents": [], "decisions": [],
         "handbacks": ["merged task t1 into t2: only together"], "deviations": None}
    assert "- merged task t1 into t2: only together" in runs_built.render(f)
