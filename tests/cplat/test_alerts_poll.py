"""Spec 092: `cplat alerts poll` end to end with fakes (skip lines, failures of the poll itself, the three-strikes issue, dry run,
reroute, step summary). GitHub is `FakeTracker` behind `alertissues.tracker`, state artifacts go through a fake `autoissue.gh`,
metrics through a fake `alertsources.http_get`; nothing touches the network."""
import json

import pytest

import autoissue
from alerts_fakes import APP, GITOPS, LGTM, NOW, FakeNet, FakeTracker, make_app, mkalert, seed

API = "acme/shop-api"
Q = 'sum by (job) (rate(http_server_requests_seconds_count{status=~"5.."}[5m])) > 1'
RULE = {"name": "HighErrorRate", "query": Q, "severity": "warning", "summary": "More than one 5xx per second"}
FIRING = [{"job": "shop-api", "deployment_environment_name": "prod"}]
TITLE = "[auto] [alert] HighErrorRate: shop-api in prod"


class World:
    def __init__(self, tmp_path, monkeypatch, capsys):
        import alertissues
        import alertsources
        self.tmp, self.capsys, self.mp = tmp_path, capsys, monkeypatch
        self.artifact_state = ""
        self.net, self.tr = FakeNet(), FakeTracker()
        self.gh_calls: list[list[str]] = []
        self.gh_answer = (0, json.dumps({"artifacts": []}), "")
        self.state = tmp_path / ".alert-poll" / "state.json"
        self.summary = tmp_path / "step-summary.md"
        monkeypatch.setattr(alertsources, "http_get", self.net)
        monkeypatch.setattr(alertsources, "kubectl", lambda args, *, timeout=10.0: (1, "", "tests never call kubectl"))
        monkeypatch.setattr(alertissues, "tracker", lambda gitops_repo: self.tr)
        monkeypatch.setattr(autoissue, "now", lambda: NOW)
        monkeypatch.setattr(autoissue, "gh", self._gh)
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(self.summary))
        for name in ("ALERTS_QUERY_AUTHORIZATION", "ALERTS_PROMETHEUS_URL", "ALERTS_TOKEN", "GITHUB_REPOSITORY"):
            monkeypatch.delenv(name, raising=False)

    def _gh(self, args, **kw):
        self.gh_calls.append(list(args))
        if args[:2] == ["run", "download"]:
            out = args[args.index("-D") + 1]
            (self.tmp / out).mkdir(parents=True, exist_ok=True)
            (self.tmp / out / "state.json").write_text(self.artifact_state)
        return self.gh_answer

    def app(self, addon="default", **kw):
        return make_app(self.tmp, addon={"ui": "lgtm", "rules": [RULE]} if addon == "default" else addon, **kw)

    def poll(self, *extra):
        import alerts
        argv = ["poll", "--repo-dir", str(self.tmp), "--gitops-repo", GITOPS, "--state-file", str(self.state), *extra]
        code = alerts.main(argv)
        return code, self.capsys.readouterr().out

    def saved(self):
        return json.loads(self.state.read_text())

    def seed_state(self, failures, reason="old reason"):
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text(json.dumps({"version": 1, "apps": {APP: {"failures": failures, "last_reason": reason, "at": "2026-10-24T07:45:00Z"}}}))

    def summary_text(self):
        return self.summary.read_text() if self.summary.exists() else ""


@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    return World(tmp_path, monkeypatch, capsys)


# ---------------- AC-092.2 skipped apps ----------------

@pytest.mark.parametrize("addon, reason", [
    ("none", "no environment declares observability"),
    ({"ui": "lgtm", "alerts": False, "rules": [RULE]}, "dev: alerts: false in observability; prod: alerts: false in observability"),
])
def test_a_skipped_app_makes_no_call_and_the_summary_says_why(w, addon, reason):
    """AC-092.2: no addon or `alerts: false`: nothing is filed, commented on or closed, no network or GitHub call, and the run summary says why."""
    w.app(None if addon == "none" else addon)
    code, out = w.poll()
    assert code == 0 and f"alert poll {APP}: skipped: {reason}" in out
    assert reason in w.summary_text() and "## Alert poll" in w.summary_text()
    assert w.net.calls == [] and w.tr.calls == [] and w.gh_calls == []
    assert not w.state.exists()


def test_export_to_without_query_url_is_skipped_and_says_queryurl_is_missing(w):
    """AC-092.19 AC-092.2: exportTo with no queryURL (and no alertmanagerURL) skips, and the summary says queryURL is missing."""
    w.app({"exportTo": "https://otlp.example.com", "rules": [RULE]})
    code, out = w.poll()
    assert code == 0 and "queryURL is missing" in out and "queryURL is missing" in w.summary_text()
    assert w.net.calls == [] and w.tr.calls == []


# ---------------- AC-092.19 / AC-092.4 a normal poll ----------------

def test_a_poll_evaluates_the_rules_files_the_issue_and_reports_it(w):
    """AC-092.19 AC-092.4: ui lgtm queries the shared stack; a firing rule becomes an issue; the summary lists what happened."""
    w.app()
    w.net.on(Q, FIRING)
    code, out = w.poll()
    assert code == 0 and w.net.queries() and all(u.startswith(LGTM) for u in w.net.queries())
    assert [c[1] for c in w.tr.created()] == [API] and w.tr.created()[0][2] == TITLE
    assert f"alert poll {APP}: 1 firing in prod (1 from rules, 0 from Alertmanager)" in out
    assert f"filed https://github.com/{API}/issues/1: {TITLE}" in out
    assert "## Alert poll" in w.summary_text() and TITLE in w.summary_text()
    assert w.saved()["version"] == 1 and w.saved()["apps"][APP]["failures"] == 0


def test_alertmanager_alerts_are_counted_separately(w):
    """AC-092.23: alerts read from Alertmanager are filed like rule alerts and counted in the poll line."""
    w.app({"ui": "lgtm", "alertmanagerURL": "https://am.example.com"})
    w.net.am = [{"labels": {"alertname": "DiskFull", "severity": "critical", "service": "shop-api", "deployment_environment_name": "dev"},
                 "annotations": {"summary": "disk"}, "startsAt": "2026-10-24T07:00:00Z", "status": {"state": "active"}}]
    code, out = w.poll()
    assert code == 0 and f"alert poll {APP}: 1 firing in dev (0 from rules, 1 from Alertmanager)" in out
    assert w.tr.created()[0][2] == "[auto] [alert] DiskFull: shop-api in dev"


def test_an_open_issue_for_a_still_firing_alert_makes_the_poll_quiet(w):
    """AC-092.11: the next poll with the same alert writes nothing."""
    w.app()
    w.net.on(Q, FIRING)
    w.poll()
    before = len(w.tr.writes())
    code, _ = w.poll()
    assert code == 0 and len(w.tr.writes()) == before


# ---------------- AC-092.16 failure of the poll itself ----------------

def test_an_unreachable_endpoint_ends_red_and_resolves_nothing(w):
    """AC-092.16: the run ends red with the endpoint and the reason; the issue of a quiet-looking alert is not resolved or closed."""
    w.app()
    alert = mkalert()
    seed(w.tr, alert)
    w.net.prom_error = (0, "connection refused")
    code, out = w.poll()
    assert code == 1
    assert f"ERROR: {LGTM}: connection refused" in out and "no issue was resolved or closed in this run" in out
    assert w.tr.writes() == []
    assert w.saved()["apps"][APP]["failures"] == 1 and "connection refused" in w.saved()["apps"][APP]["last_reason"]


def test_a_refused_credential_ends_red(w):
    """AC-092.16: a 401 from the query API is reported as a refused credential."""
    w.app()
    w.net.prom_error = (401, "unauthorized")
    code, out = w.poll()
    assert code == 1 and "refused the credential (HTTP 401)" in out


def test_a_github_failure_ends_red_with_the_repo_and_the_reason(w):
    """AC-092.16: GitHub refusing a repo is an ERROR line naming it, and the exit code is 1."""
    w.app()
    w.net.on(Q, FIRING)
    w.tr.raises[API] = "GitHub refused: HTTP 500: server error"
    code, out = w.poll()
    assert code == 1 and f"ERROR: {API}: " in out and w.tr.created() == []


def test_unreadable_poll_state_is_a_red_run_that_resolves_nothing_and_keeps_the_counter(w):
    """AC-092.16 AC-092.17: when the state artifact cannot be loaded (GitHub down) the run is red, nothing is resolved, and no state is saved."""
    w.app()
    seed(w.tr, mkalert())
    w.gh_answer = (1, "", "HTTP 502: bad gateway")
    code, out = w.poll()
    assert code == 1 and "ERROR" in out and w.tr.writes() == [] and not w.state.exists()


def test_an_unexpected_exception_is_an_error_line_not_a_traceback(w):
    """AC-092.16: the poll never raises out of main; the state is not saved."""
    w.app()

    def boom(app_dir):
        raise RuntimeError("kaboom")

    import alertsources
    w.mp.setattr(alertsources, "load_app", boom)
    code, out = w.poll()
    assert code == 1 and "ERROR: unexpected failure: RuntimeError: kaboom" in out and not w.state.exists()


# ---------------- AC-092.17 three polls in a row ----------------

def failing_issues(w):
    return [i for i in w.tr.issues.get(GITOPS, []) if "alert poll is failing" in i.title]


def test_the_third_failed_poll_in_a_row_files_one_alert_poll_is_failing_issue(w):
    """AC-092.17: after three failed polls one deduplicated `alert poll is failing` issue is filed in the gitops repo with the last reason."""
    w.app()
    w.net.prom_error = (0, "connection refused")
    for expected in (1, 2):
        code, out = w.poll()
        assert code == 1 and failing_issues(w) == [] and w.saved()["apps"][APP]["failures"] == expected
        assert "alert poll is failing for" not in out
    code, out = w.poll()
    assert code == 1 and w.saved()["apps"][APP]["failures"] == 3
    (issue,) = failing_issues(w)
    assert issue.title == f"[auto] [alert] alert poll is failing: {APP}"
    assert {"triage", "auto-filed", "alert"} <= set(issue.labels)
    assert "3 times in a row" in issue.body and "connection refused" in issue.body
    assert "alert poll is failing for 3 polls in a row" in out
    code, _ = w.poll()                                         # a fourth failure does not add a second issue
    assert code == 1 and len(failing_issues(w)) == 1 and w.saved()["apps"][APP]["failures"] == 4


def test_the_next_successful_poll_resolves_the_alert_poll_is_failing_issue(w):
    """AC-092.17: marked resolved (and closed while untriaged) at the next successful poll; the counter returns to 0."""
    w.app()
    w.net.prom_error = (0, "connection refused")
    for _ in range(3):
        w.poll()
    (issue,) = failing_issues(w)
    w.net.prom_error = None
    code, _ = w.poll()
    assert code == 0 and w.saved()["apps"][APP]["failures"] == 0
    comments = w.tr.cmts[(GITOPS, issue.number)]
    assert any(c.startswith("**Resolved** at ") for c in comments) and issue.state == "closed"


def test_two_failures_then_a_success_start_counting_again(w):
    """AC-092.17: only polls in a row count."""
    w.app()
    w.net.prom_error = (0, "connection refused")
    w.poll()
    w.poll()
    w.net.prom_error = None
    w.poll()
    w.net.prom_error = (0, "connection refused")
    w.poll()
    assert failing_issues(w) == [] and w.saved()["apps"][APP]["failures"] == 1


def test_the_failure_counter_is_loaded_from_the_state_artifact(w):
    """AC-092.17: without a local state file the newest `alert-poll-state` artifact is downloaded and its counter used."""
    w.app()
    w.artifact_state = json.dumps({"version": 1, "apps": {APP: {"failures": 2, "last_reason": "old", "at": "2026-10-24T07:45:00Z"}}})
    w.gh_answer = (0, json.dumps({"artifacts": [
        {"id": 1, "name": "alert-poll-state", "expired": False, "created_at": "2026-10-23T07:45:00Z", "workflow_run": {"id": 111}},
        {"id": 2, "name": "alert-poll-state", "expired": False, "created_at": "2026-10-24T07:45:00Z", "workflow_run": {"id": 222}},
    ]}), "")
    w.net.prom_error = (0, "connection refused")
    code, _ = w.poll()
    downloads = [c for c in w.gh_calls if c[:2] == ["run", "download"]]
    assert downloads and "222" in downloads[0] and "alert-poll-state" in downloads[0]
    assert code == 1 and len(failing_issues(w)) == 1 and w.saved()["apps"][APP]["failures"] == 3


def test_a_seeded_state_file_is_used_without_asking_github(w):
    """AC-092.17: an existing state file wins; a second failure is counted from it."""
    w.app()
    w.seed_state(1)
    w.net.prom_error = (0, "connection refused")
    w.poll()
    assert w.saved()["apps"][APP]["failures"] == 2 and not [c for c in w.gh_calls if c[:1] == ["run"]]


# ---------------- AC-092.18 dry run ----------------

def test_a_dry_run_prints_what_it_would_do_and_changes_nothing(w):
    """AC-092.18: DRY RUN lines with target repo and title; no write call, no state file."""
    w.app()
    w.net.on(Q, FIRING)
    gone = mkalert(name="Gone")
    issue = seed(w.tr, gone)
    code, out = w.poll("--dry-run")
    assert code == 0
    assert f"DRY RUN: would file in {API}: {TITLE}" in out
    assert f"DRY RUN: would comment on {API}#{issue.number} (resolved): [auto] [alert] Gone: shop-api in prod" in out
    assert f"DRY RUN: would close {API}#{issue.number}: [auto] [alert] Gone: shop-api in prod" in out
    assert w.tr.writes() == [] and not w.state.exists()
    assert "DRY RUN" in w.summary_text()


def test_the_command_is_routed_by_the_cplat_launcher():
    """AC-092.18 AC-092.1: `cplat alerts poll` is a known command (the workflow runs it)."""
    import cplat
    assert cplat.PLUMBING.get("alerts") == "alerts"
    assert "alerts poll" in cplat.__doc__


# ---------------- AC-092.9 reroute makes the run red ----------------

def test_a_rerouted_issue_ends_the_run_red(w):
    """AC-092.9: no write access to the service repo: the issue lands in the gitops repo, names the intended repo, and the run ends red."""
    w.app()
    w.net.on(Q, FIRING)
    w.tr.raises[API] = "GitHub refused: HTTP 403: Resource not accessible by personal access token"
    code, out = w.poll()
    assert code == 1
    assert f"filed in {GITOPS} instead of {API}: " in out
    ((_, repo, _, body, _),) = w.tr.created()
    assert repo == GITOPS and API in body


# ---------------- apps ----------------

def test_each_app_is_polled_on_its_own_and_app_selects_one(w):
    """AC-092.2 AC-092.24: a skipped app does not stop another; `--app` polls just one."""
    w.app()
    make_app(w.tmp, addon=None, app="other")
    w.net.on(Q, FIRING)
    code, out = w.poll()
    assert code == 0 and "alert poll other: skipped: no environment declares observability" in out
    assert f"alert poll {APP}: 1 firing in prod" in out
    code, out = w.poll("--app", "other")
    assert f"alert poll {APP}:" not in out and "alert poll other: skipped" in out
