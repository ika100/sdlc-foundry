"""Spec 095: the pure part of `cplat deps` -- version order, per-tool report parsers at the gate's threshold, grouping, major flags."""
import json
from pathlib import Path

import pytest

import core

FIX = Path(__file__).parent / "fixtures" / "deps"


def text(name):
    return (FIX / name).read_text()


def by_pkg(findings):
    out = {}
    for f in findings:
        out.setdefault(f.package, []).append(f)
    return out


# ---------------- version order ----------------

def test_version_order_numeric_and_prerelease():  # AC-095.12
    import deps_parse as dp
    assert dp.version_key("v1.10.0") > dp.version_key("1.9.3")
    assert dp.version_key("2.0.0") > dp.version_key("1.26.18")
    assert dp.version_key("1.0rc1") < dp.version_key("1.0")
    assert dp.version_key("1.0.0-beta") < dp.version_key("1.0.0")
    dp.version_key("not.a.version~")  # never raises


def test_lowest_fixed_is_the_lowest_candidate_above_installed():  # AC-095.12
    import deps_parse as dp
    assert dp.lowest_fixed("1.26.5", ["2.0.7", "1.26.18"]) == "1.26.18"
    assert dp.lowest_fixed("1.26.5", ["1.26.5", "1.0.0"]) is None
    assert dp.lowest_fixed("1.26.5", []) is None


def test_shape_tables_cover_every_non_gitops_shape():  # AC-095.16
    import deps_parse as dp
    assert dp.TOOLS == {"service-python": "pip-audit", "library-python": "pip-audit", "web-nextjs": "pnpm-audit",
                        "service-go": "govulncheck", "service-java": "trivy"}
    assert "gitops-app" not in dp.TOOLS and "gitops-app" not in dp.DEP_FILES
    assert dp.DEP_FILES["service-python"] == ("pyproject.toml", "uv.lock")
    assert dp.DEP_FILES["service-java"] == ("pom.xml",)


# ---------------- pip-audit ----------------

def test_pip_audit_every_vuln_is_a_finding_with_the_lowest_fixed_version():  # AC-095.12
    import deps_parse as dp
    fs = by_pkg(dp.parse("pip-audit", text("pip-audit.json"), {"requests", "flask"}))
    assert sorted(fs) == ["certifi", "flask", "idna", "urllib3"]  # clean packages and the skipped project are not findings
    assert sorted((f.advisories, f.fixed) for f in fs["urllib3"]) == [(["GHSA-aaaa-1111-bbbb"], "1.26.18"), (["PYSEC-2024-2"], "1.26.19")]
    assert fs["idna"][0].fixed == "3.7" and fs["idna"][0].installed == "3.6"
    assert {f.severity for fl in fs.values() for f in fl} == {"UNRATED"}


def test_transitive_flag_follows_the_manifest():  # AC-095.2
    import deps_parse as dp
    fs = by_pkg(dp.parse("pip-audit", text("pip-audit.json"), {"requests", "flask"}))
    assert fs["urllib3"][0].transitive is True and fs["idna"][0].transitive is True
    assert fs["flask"][0].transitive is False


def test_a_vulnerability_without_a_fixed_version_has_fixed_none():  # AC-095.13
    import deps_parse as dp
    f = by_pkg(dp.parse("pip-audit", text("pip-audit.json"), set()))["certifi"][0]
    assert f.fixed is None and f.installed == "2024.1.1" and f.advisories == ["PYSEC-2099-1"]


def test_major_is_a_fix_in_a_higher_major_version():  # AC-095.17
    import deps_parse as dp
    fs = by_pkg(dp.parse("pip-audit", text("pip-audit.json"), {"flask"}))
    assert fs["flask"][0].major is True and fs["idna"][0].major is False and fs["urllib3"][0].major is False


def test_group_makes_one_bump_per_package_that_fixes_all_its_advisories():  # AC-095.12
    import deps_parse as dp
    grouped = dp.group(dp.parse("pip-audit", text("pip-audit.json"), {"flask"}))
    assert [g.package for g in grouped] == ["certifi", "flask", "idna", "urllib3"]
    u = next(g for g in grouped if g.package == "urllib3")
    assert (u.installed, u.fixed, u.advisories, u.severity) == ("1.26.5", "1.26.19", ["GHSA-aaaa-1111-bbbb", "PYSEC-2024-2"], "UNRATED")
    assert next(g for g in grouped if g.package == "certifi").fixed is None
    assert next(g for g in grouped if g.package == "flask").major is True


def test_group_with_one_unfixable_advisory_has_no_fix_and_the_highest_severity():  # AC-095.13
    import deps_parse as dp
    mk = lambda adv, fixed, sev: dp.Finding("p", "1.0", fixed, [adv], sev, False, False)  # noqa: E731
    g = dp.group([mk("A-1", "1.2", "HIGH"), mk("A-2", None, "CRITICAL"), mk("A-3", "1.1", "LOW")])[0]
    assert g.fixed is None and g.severity == "CRITICAL" and g.advisories == ["A-1", "A-2", "A-3"]


# ---------------- pnpm audit ----------------

def test_pnpm_audit_keeps_only_high_and_critical():  # AC-095.16
    import deps_parse as dp
    fs = by_pkg(dp.parse("pnpm-audit", text("pnpm-audit.json"), set()))
    assert "lodash" not in fs  # moderate: the gate (`--audit-level high`) does not fail on it
    assert sorted(fs) == ["minimist", "next", "qs", "semver"]


def test_pnpm_audit_fixed_versions_and_one_finding_per_installed_version():  # AC-095.12
    import deps_parse as dp
    fs = by_pkg(dp.parse("pnpm-audit", text("pnpm-audit.json"), {"next"}))
    assert {f.installed for f in fs["qs"]} == {"6.9.0", "6.11.0"} and len(fs["qs"]) == 2
    assert {f.fixed for f in fs["qs"]} == {"6.11.3"} and {f.severity for f in fs["qs"]} == {"HIGH"}
    assert fs["semver"][0].fixed == "5.7.2"  # `>=5.7.2 <6.0.0`: the lowest bound counts
    assert fs["next"][0].advisories == ["npm-5"] and fs["next"][0].severity == "CRITICAL"
    assert fs["qs"][0].transitive is True and fs["next"][0].transitive is False


def test_pnpm_audit_no_patched_version_means_no_fix():  # AC-095.13
    import deps_parse as dp
    assert by_pkg(dp.parse("pnpm-audit", text("pnpm-audit.json"), set()))["minimist"][0].fixed is None


def test_pnpm_audit_major_bump():  # AC-095.17
    import deps_parse as dp
    fs = by_pkg(dp.parse("pnpm-audit", text("pnpm-audit.json"), set()))
    assert fs["next"][0].major is True and fs["qs"][0].major is False


def test_pnpm_audit_empty_report_is_no_findings_and_unknown_shape_raises():  # AC-095.12
    import deps_parse as dp
    assert dp.parse("pnpm-audit", '{"advisories": {}}', set()) == []
    with pytest.raises(core.PlatformError, match="unrecognised pnpm audit report"):
        dp.parse("pnpm-audit", '{"something": "else"}', set())


# ---------------- govulncheck ----------------

def test_govulncheck_only_called_symbols_count():  # AC-095.16
    import deps_parse as dp
    fs = by_pkg(dp.parse("govulncheck", text("govulncheck.jsonl"), set()))
    assert "golang.org/x/text" not in fs  # imported but never called: the gate does not fail on it
    assert fs["golang.org/x/net"][0].fixed == "v0.23.0" and fs["golang.org/x/net"][0].installed == "v0.20.0"
    assert fs["golang.org/x/net"][0].advisories == ["GO-2024-2687"] and fs["golang.org/x/net"][0].severity == "UNRATED"


def test_govulncheck_stdlib_is_a_toolchain_finding_never_bumped():  # AC-095.16
    import deps_parse as dp
    f = by_pkg(dp.parse("govulncheck", text("govulncheck.jsonl"), set()))["stdlib"][0]
    assert f.kind == "toolchain" and f.fixed == "go1.22.5"
    assert by_pkg(dp.parse("govulncheck", text("govulncheck.jsonl"), set()))["golang.org/x/net"][0].kind == "dependency"


def test_govulncheck_without_fixed_version_and_major_flag():  # AC-095.13 AC-095.17
    import deps_parse as dp
    fs = by_pkg(dp.parse("govulncheck", text("govulncheck.jsonl"), set()))
    assert fs["github.com/acme/lib"][0].fixed is None
    assert fs["github.com/acme/major"][0].major is True and fs["golang.org/x/net"][0].major is False


# ---------------- trivy ----------------

def test_trivy_keeps_high_and_critical_only():  # AC-095.16
    import deps_parse as dp
    fs = by_pkg(dp.parse("trivy", text("trivy.json"), set()))
    assert "com.acme:medium" not in fs
    assert sorted(fs) == ["com.acme:major", "com.acme:nofix", "org.apache.commons:commons-text", "org.apache.logging.log4j:log4j-core"]


def test_trivy_fixed_version_comma_list_takes_the_lowest_above_installed():  # AC-095.12
    import deps_parse as dp
    fs = by_pkg(dp.parse("trivy", text("trivy.json"), set()))
    log4j = fs["org.apache.logging.log4j:log4j-core"][0]
    assert (log4j.installed, log4j.fixed, log4j.severity, log4j.advisories) == ("2.14.1", "2.17.1", "HIGH", ["CVE-2021-44228"])
    assert fs["org.apache.commons:commons-text"][0].fixed == "1.10.0"


def test_trivy_no_fixed_version_and_major_bump():  # AC-095.13 AC-095.17
    import deps_parse as dp
    fs = by_pkg(dp.parse("trivy", text("trivy.json"), set()))
    assert fs["com.acme:nofix"][0].fixed is None
    assert fs["com.acme:major"][0].major is True and fs["org.apache.commons:commons-text"][0].major is False


# ---------------- declared ----------------

def test_declared_python_names_are_pep503_normalised(tmp_path):  # AC-095.2
    import deps_parse as dp
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\ndependencies = ["Foo_Bar>=1", "uvicorn[standard]>=0.3"]\n'
        '[project.optional-dependencies]\ndev = ["pytest>=8"]\n[dependency-groups]\nlint = ["Ruff.Tool>=0.1"]\n')
    assert {"foo-bar", "uvicorn", "pytest", "ruff-tool"} <= dp.declared("service-python", tmp_path)


def test_declared_npm_go_and_maven(tmp_path):  # AC-095.2
    import deps_parse as dp
    web, go, java = tmp_path / "web", tmp_path / "go", tmp_path / "java"
    for d in (web, go, java):
        d.mkdir()
    (web / "package.json").write_text(json.dumps({"dependencies": {"next": "14"}, "devDependencies": {"vitest": "2"}}))
    assert dp.declared("web-nextjs", web) == {"next", "vitest"}
    (go / "go.mod").write_text("module m\n\ngo 1.22\n\nrequire github.com/go-chi/chi/v5 v5.0.0\n\n"
                               "require (\n\tgithub.com/a/b v1.0.0\n\tgolang.org/x/text v0.14.0 // indirect\n)\n")
    assert dp.declared("service-go", go) == {"github.com/go-chi/chi/v5", "github.com/a/b"}
    (java / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion><groupId>g</groupId><artifactId>a</artifactId>'
        '<version>1</version><dependencies><dependency><groupId>org.x</groupId><artifactId>y</artifactId><version>1</version></dependency>'
        '</dependencies></project>')
    assert dp.declared("service-java", java) == {"org.x:y"}
