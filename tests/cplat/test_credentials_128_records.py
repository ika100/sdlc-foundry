"""Spec 128 acceptance tests, tests, records and release notes: the e2e scripts (AC-128.11, text checks; they need a cluster to run), the
decision record (AC-128.13) and the changelog entry (AC-128.14).

Contract: design.md "e2e harness (what Argo CD would do)". The e2e scripts are only read. The ADR is `docs/adr/072-*.md`."""
import re

from system_fixtures import ROOT

E2E = ROOT / "tests" / "e2e"
ADR = ROOT / "docs" / "adr"


def upgrade() -> str:
    return (E2E / "upgrade.sh").read_text()


def run() -> str:
    return (E2E / "run.sh").read_text()


# ---------------- AC-128.11: the e2e scripts ----------------

def test_the_settle_cache_workaround_is_gone_ac_128_11():  # AC-128.11
    text = upgrade()
    assert "settle_cache" not in text
    assert "settled-" not in text and "did not settle" not in text
    assert "#316" not in text or "WORKAROUND" not in text


def test_no_e2e_script_restarts_a_server_to_make_passwords_match_ac_128_11():  # AC-128.11
    assert "rollout restart" not in upgrade(), "upgrade.sh restarts a server"
    for name, text in (("upgrade.sh", upgrade()), ("run.sh", run())):
        assert not re.search(r"wait[^\n]*(stop|stays?) (changing|unchanged)|stays? unchanged for|Secret[^\n]*settle", text), name


def test_both_scripts_apply_the_credentials_files_first_and_wait_for_the_job_ac_128_11():  # AC-128.11
    for name, text in (("upgrade.sh", upgrade()), ("run.sh", run())):
        assert "credentials-job.yaml" in text, name
        assert re.search(r"wait\s+--for=condition=complete\s+job/\S+\s+--timeout=180s", text), name
        assert re.search(r"apply\s+-f[^\n]*credentials-", text) or "credentials-*.yaml" in text, name
        first_wait = re.search(r"--for=condition=complete", text).start()
        assert text.index("credentials-") < first_wait, name


def test_a_failed_job_shows_its_logs_ac_128_11():  # AC-128.11
    for name, text in (("upgrade.sh", upgrade()), ("run.sh", run())):
        assert re.search(r"logs\s+job/", text), name


def test_both_scripts_force_one_more_write_of_a_caches_secret_and_compare_ac_128_11():  # AC-128.11
    for name, text in (("upgrade.sh", upgrade()), ("run.sh", run())):
        assert "AC-128.3" in text, name
        assert re.search(r"delete\s+job", text), name
        assert "resourceVersion" in text, name


def test_both_scripts_check_the_server_the_component_and_the_broker_in_every_environment_ac_128_11():  # AC-128.11
    for name, text in (("upgrade.sh", upgrade()), ("run.sh", run())):
        for ac in ("AC-128.1", "AC-128.2", "AC-128.4"):
            assert ac in text, f"{name} does not check {ac}"
        assert "WRONGPASS" in text, name
        assert re.search(r"PING", text) and "PONG" in text, name


def test_the_checks_come_before_the_deliberate_restarts_of_other_specs_ac_128_11():  # AC-128.11
    text = run()
    checks = [text.index(a) for a in ("AC-128.1", "AC-128.2", "AC-128.4") if a in text]
    assert len(checks) == 3
    for restart in ("delete pod e2e-sessions-0 e2e-ratelimit-0", 'delete pod $store_pods'):
        assert max(checks) < text.index(restart), restart
    assert text.index("AC-128.3") < text.index("delete pod e2e-sessions-0 e2e-ratelimit-0")


def test_the_upgrade_script_checks_before_the_later_steps_ac_128_11():  # AC-128.11
    text = upgrade()
    assert "AC-128.1" in text
    assert text.index("AC-128.1") < text.index('step "3 Update')


# ---------------- AC-128.13: the ADR ----------------

def adr_path():
    found = sorted(ADR.glob("072-*.md"))
    assert len(found) == 1, f"docs/adr/072-*.md: {found}"
    return found[0]


def test_the_adr_records_the_cause_with_the_version_of_external_secrets_ac_128_13():  # AC-128.13
    text = adr_path().read_text()
    assert text.startswith("# ADR-072:")
    assert "#316" in text and "External Secrets" in text
    assert re.search(r"\bv?\d+\.\d+\.\d+\b", text.split("## Decision")[0]), "the examined External Secrets version"
    assert re.search(r"upstream|fixed in|no fixed version", text, re.I)


def test_the_adr_records_the_mechanism_the_exception_and_the_rights_ac_128_13():  # AC-128.13
    text = adr_path().read_text()
    assert re.search(r"exactly once|written once", text)
    assert re.search(r"cannot write it twice|create if absent", text)
    assert "ADR-018" in text and re.search(r"exception", text, re.I) and "every Secret comes from External Secrets" in text
    assert re.search(r"\bRole\b", text) and "create" in text and "get" in text and "patch" in text and "secrets" in text
    assert re.search(r"no `?update`?|never `?update`?|without `?update`?", text)


def test_the_adr_amends_adr_064_065_and_059_ac_128_13():  # AC-128.13
    text = adr_path().read_text()
    assert "**Amends:**" in text
    head = text.split("## Context")[0]
    for n in ("064", "065", "059"):
        assert re.search(rf"ADR-{n}\b", head), n
    assert re.search(r"ADR-064[^\n]*point 3|point 3[^\n]*ADR-064", head)


def test_the_amended_adrs_point_to_adr_072_ac_128_13():  # AC-128.13
    for pat in ("018-*.md", "059-*.md", "064-*.md", "065-*.md"):
        (p,) = ADR.glob(pat)
        text = p.read_text()
        assert re.search(r"ADR-072|072-[a-z]", text), f"{p.name} does not point to ADR-072"
        assert re.search(r"[Aa]mended", text), f"{p.name} is not marked as amended"


def test_the_adr_index_lists_adr_072_ac_128_13():  # AC-128.13
    text = (ADR / "README.md").read_text()
    name = adr_path().name
    assert re.search(rf"\|\s*\[072\]\({re.escape(name)}\)", text)


# ---------------- AC-128.14: the changelog ----------------

def unreleased() -> str:
    text = (ROOT / "docs" / "CHANGELOG.md").read_text()
    return text.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]


def entry() -> str:
    hits = [p for p in re.split(r"\n\s*\n", unreleased()) if "#316" in p]
    assert hits, "no entry in [Unreleased] names #316"
    return "\n\n".join(hits)


def test_the_changelog_entry_names_the_issue_and_the_symptom_ac_128_14():  # AC-128.14
    e = entry()
    assert "#316" in e
    assert "WRONGPASS" in e or re.search(r"authori[sz]ation (error|violation)", e, re.I)
    assert re.search(r"restart", e)


def test_the_changelog_entry_names_the_resource_types_and_releases_ac_128_14():  # AC-128.14
    e = entry().lower()
    for word in ("cache", "broker", "bucket", "generated"):
        assert word in e, word
    assert re.search(r"5\.\d(\.x|\.\d+)?", e), "the affected releases"


def test_the_changelog_entry_names_the_fix_and_that_nothing_is_to_do_ac_128_14():  # AC-128.14
    e = entry()
    assert re.search(r"written once|exactly once", e) and re.search(r"credentials Job|Job", e)
    assert re.search(r"nothing to do|no action|nothing (is )?(needed|required)|need to do nothing", e, re.I)
    assert re.search(r"[Ff]ixed", unreleased()), "the entry is under Fixed"
