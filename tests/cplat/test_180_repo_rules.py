"""Spec 180 acceptance tests: the platform repo itself passes the extended `cplat platform rules check` and keeps its criteria
tested (AC-180.4). These stay red until the rewrite tasks of the spec are done."""
import json
import re
import subprocess

import cplat
import spec
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


BASE = "b4d184a4efd47495f27094564ed3a571af08b2b3"  # the commit before the rewrite


def test_every_criterion_id_tested_at_the_base_commit_is_still_tested_ac_180_4():  # AC-180.4
    have_base = subprocess.run(["git", "cat-file", "-e", BASE], cwd=ROOT, capture_output=True).returncode == 0
    base_text = ""
    if have_base:  # a shallow clone may lack the base; the check above still holds then
        base_text = subprocess.run(["git", "grep", "-h", "-I", "-e", "AC-[0-9]*[.][0-9]*", BASE, "--", "tests"],
                                   cwd=ROOT, capture_output=True, text=True).stdout
    tested_then = set(re.findall(r"AC-\d+\.\d+(?!\d)", base_text))
    lost = []
    for s in spec.all_specs(ROOT):
        if s.id == "180":
            continue
        traced = spec.trace(ROOT, s, spec.test_globs(spec.spec_shape(s, spec.repo_shape(ROOT))))
        lost += [ac for ac, files in traced.items() if ac in tested_then and not files]
    assert lost == []
