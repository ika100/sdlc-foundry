"""Spec 189: the platform's template image scan (scripts/template-image-scan.py, its workflow and accepted-finding list)."""
import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "template-image-scan.py"
WORKFLOW = ROOT / ".github" / "workflows" / "template-image-scan.yml"
ACCEPTED = ROOT / ".github" / "image-scan-accepted.yml"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
ALL = ["service-python", "service-java", "service-go", "web-nextjs"]
TODAY = "2026-11-13"


@pytest.fixture()
def scan():
    """The script module, loaded by path (hyphenated name); a missing script fails the test that uses it."""

    class Lazy:
        def __getattr__(self, name):
            assert SCRIPT.is_file(), "scripts/template-image-scan.py does not exist"
            spec = importlib.util.spec_from_file_location("template_image_scan", SCRIPT)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return getattr(mod, name)

    return Lazy()


def _cli(*args: str) -> subprocess.CompletedProcess:
    assert SCRIPT.is_file(), "scripts/template-image-scan.py does not exist"
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60)


def _vuln(cve, sev="CRITICAL", pkg="zlib1g", installed="1:1.2.13", fixed=None):
    v = {"VulnerabilityID": cve, "PkgName": pkg, "InstalledVersion": installed, "Severity": sev}
    if fixed:
        v["FixedVersion"] = fixed
    return v


def _run_evaluate(tmp_path, vulns, entries, template="service-java", today=TODAY, raw_report=None, raw_accepted=None):
    report = tmp_path / "trivy.json"
    report.write_text(raw_report if raw_report is not None else json.dumps({"Results": [{"Target": "x", "Vulnerabilities": vulns}]}))
    accepted = tmp_path / "accepted.yml"
    accepted.write_text(raw_accepted if raw_accepted is not None else yaml.safe_dump({"findings": entries}))
    return _cli("evaluate", "--template", template, "--report", str(report), "--accepted", str(accepted), "--today", today)


def _entry(template="service-java", cve="CVE-2023-45853", reason="won't fix; follow-up #1", added="2026-11-01", review_by="2027-01-15"):
    return {"template": template, "cve": cve, "reason": reason,
            "added": dt.date.fromisoformat(added), "review_by": dt.date.fromisoformat(review_by)}


def _lines(proc):
    return proc.stdout.strip().splitlines()


# --- select ---------------------------------------------------------------------------------------------------------------


def test_select_pr_changing_one_template_selects_only_it(scan):  # AC-189.3
    """AC-189.3: a PR runs the scan only for the changed templates with an image."""
    assert list(scan.select_templates("pull_request", ["templates/web-nextjs/Dockerfile.jinja", "docs/x.md"])) == ["web-nextjs"]


def test_select_pr_keeps_the_fixed_order(scan):  # AC-189.3
    paths = ["templates/web-nextjs/a", "templates/service-go/b", "templates/service-python/c"]
    assert list(scan.select_templates("pull_request", paths)) == ["service-python", "service-go", "web-nextjs"]


def test_select_pr_ignores_templates_without_an_image(scan):  # AC-189.3
    assert list(scan.select_templates("pull_request", ["templates/library-python/x", "templates/gitops-app/y", "README.md"])) == []


@pytest.mark.parametrize("path", ["scripts/template-image-scan.py", ".github/image-scan-accepted.yml",
                                  ".github/workflows/template-image-scan.yml"])
def test_select_pr_changing_the_scan_itself_selects_all(scan, path):  # AC-189.3
    assert list(scan.select_templates("pull_request", [path])) == ALL


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch", "push"])
def test_select_non_pr_event_selects_all_four(scan, event):  # AC-189.4
    """AC-189.4: the daily scheduled run scans all four templates, with no change at all."""
    assert list(scan.select_templates(event, [])) == ALL


def test_select_cli_prints_output_lines_for_a_schedule(): # AC-189.4
    proc = _cli("select", "--event", "schedule")
    assert proc.returncode == 0, proc.stderr
    assert _lines(proc) == ["templates=" + json.dumps(ALL, separators=(",", ":")), "any=true"]


# --- evaluate -------------------------------------------------------------------------------------------------------------


def test_unaccepted_critical_fails_and_names_template_cve_package_version(tmp_path):  # AC-189.3
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2023-45853", installed="1:1.2.13")], [])
    assert proc.returncode == 1
    assert _lines(proc)[0] == "CRITICAL: CVE-2023-45853 in service-java: zlib1g 1:1.2.13 (no fix)"
    assert _lines(proc)[-1] == "scan service-java: 1 critical, 0 high, 0 accepted, 0 entry problems"


def test_critical_with_a_fix_names_the_fixed_version(tmp_path):  # AC-189.3
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2030-1", pkg="libx", installed="1.0", fixed="1.1")], [])
    assert proc.returncode == 1
    assert "CRITICAL: CVE-2030-1 in service-java: libx 1.0 (fixed in 1.1)" in _lines(proc)


def test_high_findings_are_listed_but_do_not_fail(tmp_path):  # AC-189.3
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2030-2", sev="HIGH", pkg="libh", installed="2.0", fixed="2.1")], [])
    assert proc.returncode == 0, proc.stdout
    assert _lines(proc) == ["HIGH: CVE-2030-2 in service-java: libh 2.0 (fixed in 2.1)",
                            "scan service-java: 0 critical, 1 high, 0 accepted, 0 entry problems"]


def test_scheduled_run_fails_and_names_the_template(tmp_path):  # AC-189.4
    """AC-189.4: the same evaluation runs on the scheduled scan; an unaccepted CRITICAL fails it and names the template."""
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2030-3")], [], template="service-go")
    assert proc.returncode == 1
    assert "CRITICAL: CVE-2030-3 in service-go:" in proc.stdout


def test_clean_report_passes(tmp_path):  # AC-189.3
    proc = _run_evaluate(tmp_path, [], [])
    assert proc.returncode == 0
    assert _lines(proc) == ["scan service-java: 0 critical, 0 high, 0 accepted, 0 entry problems"]


def test_null_vulnerabilities_are_no_findings(tmp_path):  # AC-189.3
    proc = _run_evaluate(tmp_path, None, [])
    assert proc.returncode == 0
    assert _lines(proc) == ["scan service-java: 0 critical, 0 high, 0 accepted, 0 entry problems"]


def test_findings_are_deduplicated_by_cve_package_and_version(tmp_path):  # AC-189.3
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2030-4"), _vuln("CVE-2030-4"), _vuln("CVE-2030-4", installed="9")], [])
    assert len([ln for ln in _lines(proc) if ln.startswith("CRITICAL:")]) == 2
    assert _lines(proc)[-1].startswith("scan service-java: 2 critical")


def test_accepted_entry_passes_and_prints_the_finding(tmp_path):  # AC-189.5
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2023-45853")], [_entry()])
    assert proc.returncode == 0, proc.stdout
    assert _lines(proc) == ["accepted: CVE-2023-45853 in service-java: won't fix; follow-up #1 (review by 2027-01-15)",
                            "scan service-java: 0 critical, 0 high, 1 accepted, 0 entry problems"]


def test_accepted_entry_is_printed_once_per_cve(tmp_path):  # AC-189.5
    vulns = [_vuln("CVE-2023-45853"), _vuln("CVE-2023-45853", pkg="zlib1g-dev")]
    proc = _run_evaluate(tmp_path, vulns, [_entry()])
    assert proc.returncode == 0
    assert len([ln for ln in _lines(proc) if ln.startswith("accepted:")]) == 1


def test_an_entry_covers_only_the_template_it_names(tmp_path):  # AC-189.5
    """AC-189.5: an entry for service-go does not accept the CVE in service-java, and is not checked there at all."""
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2023-45853")], [_entry(template="service-go")], template="service-java")
    assert proc.returncode == 1
    assert _lines(proc)[0].startswith("CRITICAL: CVE-2023-45853 in service-java:")
    assert not any(ln.startswith("entry ") for ln in _lines(proc))


def test_entry_without_a_reason_fails(tmp_path):  # AC-189.6
    for reason in ("", "   ", None):
        proc = _run_evaluate(tmp_path, [_vuln("CVE-2023-45853")], [_entry(reason=reason)])
        assert proc.returncode == 1
        assert "entry CVE-2023-45853 in service-java: no reason" in _lines(proc)
        assert any(ln.startswith("CRITICAL: CVE-2023-45853") for ln in _lines(proc))
        assert _lines(proc)[-1].endswith("1 entry problems")


def test_entry_with_a_passed_review_date_fails(tmp_path):  # AC-189.6
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2023-45853")], [_entry(added="2026-09-01", review_by="2026-11-12")])
    assert proc.returncode == 1
    assert "entry CVE-2023-45853 in service-java: review date passed" in _lines(proc)


def test_review_date_today_is_still_valid(tmp_path):  # AC-189.6
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2023-45853")], [_entry(added="2026-09-01", review_by=TODAY)])
    assert proc.returncode == 0, proc.stdout


def test_entry_with_a_review_date_too_far_fails(tmp_path):  # AC-189.6
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2023-45853")], [_entry(added="2026-11-01", review_by="2027-02-01")])
    assert proc.returncode == 1
    assert "entry CVE-2023-45853 in service-java: review date too far" in _lines(proc)


def test_review_date_exactly_90_days_after_added_is_valid(tmp_path):  # AC-189.5
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2023-45853")], [_entry(added="2026-11-01", review_by="2027-01-30")])
    assert proc.returncode == 0, proc.stdout


def test_entry_for_a_cve_no_longer_found_fails(tmp_path):  # AC-189.6
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2030-9")], [_entry(), _entry(cve="CVE-2030-9")])
    assert proc.returncode == 1
    assert "entry CVE-2023-45853 in service-java: no longer found" in _lines(proc)
    assert _lines(proc)[-1] == "scan service-java: 0 critical, 0 high, 1 accepted, 1 entry problems"


def test_entry_is_found_at_any_severity(tmp_path):  # AC-189.6
    """A CVE that the report lists as HIGH is still found, so its entry is not 'no longer found'."""
    proc = _run_evaluate(tmp_path, [_vuln("CVE-2023-45853", sev="HIGH")], [_entry()])
    assert proc.returncode == 0, proc.stdout
    assert not any("no longer found" in ln for ln in _lines(proc))


@pytest.mark.parametrize("missing", ["template", "cve", "added", "review_by"])
def test_entry_missing_a_required_field_is_a_usage_error(tmp_path, missing):  # AC-189.6
    entry = _entry()
    del entry[missing]
    proc = _run_evaluate(tmp_path, [], [entry])
    assert proc.returncode == 2
    assert proc.stderr.strip()


def test_entry_naming_an_unknown_template_is_a_usage_error(tmp_path):  # AC-189.6
    assert _run_evaluate(tmp_path, [], [_entry(template="library-python")]).returncode == 2


@pytest.mark.parametrize("raw", ["{not json", ""])
def test_unreadable_report_is_a_usage_error(tmp_path, raw):  # AC-189.3
    assert _run_evaluate(tmp_path, [], [], raw_report=raw).returncode == 2


@pytest.mark.parametrize("raw", ["findings: oops", "other: []", "- a\n- b", ": : :"])
def test_malformed_accepted_list_is_a_usage_error(tmp_path, raw):  # AC-189.6
    assert _run_evaluate(tmp_path, [], [], raw_accepted=raw).returncode == 2


def test_missing_accepted_list_is_a_usage_error(tmp_path):  # AC-189.6
    report = tmp_path / "t.json"
    report.write_text('{"Results": []}')
    proc = _cli("evaluate", "--template", "web-nextjs", "--report", str(report), "--accepted", str(tmp_path / "none.yml"))
    assert proc.returncode == 2


def test_evaluate_function_is_importable_with_the_planned_signature(scan):  # AC-189.5
    assert callable(scan.evaluate) and callable(scan.select_templates)


# --- accepted-finding list ------------------------------------------------------------------------------------------------


def test_accepted_list_parses_and_every_entry_is_valid():  # AC-189.5
    data = yaml.safe_load(ACCEPTED.read_text())
    assert isinstance(data["findings"], list)
    for e in data["findings"]:
        assert e["template"] in ALL, e
        assert str(e["cve"]).startswith("CVE-"), e
        assert str(e["reason"]).strip(), e
        added, review_by = e["added"], e["review_by"]
        assert isinstance(added, dt.date) and isinstance(review_by, dt.date), e
        assert added < review_by <= added + dt.timedelta(days=90), e


# --- workflow -------------------------------------------------------------------------------------------------------------


def _workflow() -> dict:
    wf = yaml.safe_load(WORKFLOW.read_text())
    wf["on"] = wf.get("on", wf.get(True))  # PyYAML reads the key `on` as True
    return wf


def test_workflow_runs_on_pull_requests_daily_and_on_demand():  # AC-189.4
    on = _workflow()["on"]
    assert "pull_request" in on and "workflow_dispatch" in on
    crons = [s["cron"] for s in on["schedule"]]
    assert crons == ["17 3 * * *"]
    assert "paths" not in (on["pull_request"] or {})


def test_workflow_decide_job_selects_templates_with_the_script():  # AC-189.3
    wf = _workflow()
    decide = wf["jobs"]["decide"]
    assert decide["timeout-minutes"] == 2
    text = yaml.safe_dump(decide)
    assert "fetch-depth: 0" in text.replace("'", "") or decide["steps"][0]["with"]["fetch-depth"] == 0
    assert "template-image-scan.py select" in text and "GITHUB_OUTPUT" in text


def test_workflow_scan_job_is_a_matrix_over_the_four_templates():  # AC-189.3
    wf = _workflow()
    scan = wf["jobs"]["scan"]
    assert scan["needs"] == "decide" or scan["needs"] == ["decide"]
    assert "any" in scan["if"] and "true" in scan["if"]
    assert "fromJSON(needs.decide.outputs.templates)" in str(scan["strategy"]["matrix"]["template"])
    assert scan["strategy"]["fail-fast"] is False
    assert scan["timeout-minutes"] == 30
    text = WORKFLOW.read_text()
    assert "--build-arg VERSION=v0.0.0" in text and "module_name=scan_svc" in text


def test_workflow_scans_critical_and_high_with_unfixed_included_and_evaluates():  # AC-189.3
    scan = _workflow()["jobs"]["scan"]
    trivy = [s for s in scan["steps"] if str(s.get("uses", "")).startswith("aquasecurity/trivy-action@")]
    assert len(trivy) == 1
    w = trivy[0]["with"]
    assert str(w["ignore-unfixed"]).lower() == "false"
    assert w["severity"] == "CRITICAL,HIGH"
    assert str(w["exit-code"]) == "0"
    assert w["format"] == "json" and w["scanners"] == "vuln"
    steps = scan["steps"]
    assert steps.index(trivy[0]) < max(i for i, s in enumerate(steps) if "template-image-scan.py evaluate" in str(s.get("run", "")))


def test_workflow_pins_trivy_like_the_templates():  # AC-189.3
    tmpl = (ROOT / "templates" / "web-nextjs" / ".github" / "workflows" / "ci.yml").read_text()
    pin = next(ln.split("uses:")[1].strip() for ln in tmpl.splitlines() if "aquasecurity/trivy-action@" in ln)
    assert pin in WORKFLOW.read_text()


def test_workflow_has_least_privilege_permissions():  # AC-189.3
    assert _workflow()["permissions"] == {"contents": "read"}


# --- dependabot header ----------------------------------------------------------------------------------------------------


def test_dependabot_header_names_the_template_image_scan():  # AC-189.7
    header = "\n".join(ln for ln in DEPENDABOT.read_text().splitlines() if ln.startswith("#")).lower()
    header = " ".join(header.replace("#", " ").split())
    assert "docker base images" not in header
    assert "template image scan" in header
