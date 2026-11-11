"""Spec 180 acceptance tests: the platform repo itself passes the extended `cplat platform rules check` and keeps its criteria
tested (AC-180.4). These stay red until the rewrite tasks of the spec are done."""
import json
import re

import cplat
from conftest import ROOT


def run(capsys, *argv):
    rc = cplat.main(list(argv))
    return rc, capsys.readouterr().out


def test_the_repo_rules_check_passes_and_reports_the_interface_pins_ac_180_4(capsys):  # AC-180.4
    rc, out = run(capsys, "platform", "rules", "check", "--repo", str(ROOT))
    assert rc == 0, out
    m = re.fullmatch(r"OK: \d+ rule sentences classified, \d+ hard rules; \d+ prompt targets resolve; (\d+) interface pins; "
                     r"prompts \d+ bytes \(baseline \d+\)\n", out)
    assert m, out


def test_the_repo_rules_check_json_gives_targets_and_interface_pins_ac_180_4(capsys):  # AC-180.4
    rc, out = run(capsys, "platform", "rules", "check", "--repo", str(ROOT), "--json")
    doc = json.loads(out)
    assert rc == 0 and doc["ok"] is True and doc["failures"] == []
    assert isinstance(doc["counts"]["interface_pins"], int) and doc["counts"]["targets"] > 0


def test_the_text_and_json_pin_counts_agree_ac_180_4(capsys):  # AC-180.4
    _, text = run(capsys, "platform", "rules", "check", "--repo", str(ROOT))
    _, js = run(capsys, "platform", "rules", "check", "--repo", str(ROOT), "--json")
    assert f"{json.loads(js)['counts']['interface_pins']} interface pins" in text


def test_spec_check_stays_green_ac_180_4(capsys):  # AC-180.4
    rc, out = run(capsys, "spec", "check")
    assert rc == 0, out
