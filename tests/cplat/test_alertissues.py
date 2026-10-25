"""Spec 092: alert issues in the owning repo (title, labels, body, signature, routing, dedupe, fired again, resolve, reopen,
cap, redaction, dry run). `alertissues.reconcile` runs against `FakeTracker`, an in-memory GitHub; nothing reaches the network."""
import datetime as dt
import re

import pytest

import autoissue
from alerts_fakes import GITOPS, NOW, FakeTracker, iso, mkalert, resolved_comment, seed

SIG_LINE = re.compile(r"^Signature: (alert:[0-9a-f]{16})$", re.M)
TOKEN = "ghp_" + "a1b2c3d4e5" * 4
API = "acme/shop-api"


@pytest.fixture()
def tr(monkeypatch):
    monkeypatch.setattr(autoissue, "now", lambda: NOW)
    return FakeTracker()


def run(tr, alerts, *, repos=None, dry_run=False, resolve=True):
    import alertissues
    return alertissues.reconcile(alerts, app="shop", gitops_repo=GITOPS, repos=repos or [API, GITOPS], tr=tr, now=NOW,
                                 dry_run=dry_run, resolve=resolve)


def title_of(alert):
    import alertissues
    return alertissues.title(alert)


def outside_fences(body):
    """The Markdown a reader would follow: the body without its fenced blocks."""
    out, fence = [], None
    for line in body.splitlines():
        m = re.match(r"^(`{3,})", line)
        if m and fence is None:
            fence = m.group(1)
        elif m and fence and line.startswith(fence):
            fence = None
        elif fence is None:
            out.append(line)
    return "\n".join(out)


# ---------------- AC-092.20 title, labels, body, signature ----------------

def test_a_firing_alert_is_filed_in_the_service_repo_with_the_088_convention(tr):
    """AC-092.20: title `[auto] [alert] <name>: <service> in <env>`, labels triage/auto-filed/alert/env:<env>, created first if missing."""
    alert = mkalert()
    res = run(tr, [alert])
    ((_, repo, title, _, labels),) = tr.created()
    assert repo == API and title == "[auto] [alert] HighErrorRate: shop-api in prod"
    assert set(labels) == {"triage", "auto-filed", "alert", "env:prod"}
    ensured = tr.of("ensure_labels", API)
    assert ensured and {"triage", "auto-filed", "alert", "env:prod"} <= set(ensured[0][2])
    assert tr.calls.index(ensured[0]) < tr.calls.index(tr.created()[0])
    assert any(line == f"filed https://github.com/{API}/issues/1: {title}" for line in res.lines)
    assert res.errors == [] and res.rerouted == []


def test_the_body_has_severity_environment_start_summary_query_and_exactly_one_signature(tr):
    """AC-092.20: the body gives severity, environment, start time, summary and query, with one `Signature: alert:<16 hex>` line."""
    alert = mkalert()
    run(tr, [alert])
    body = tr.created()[0][3]
    for text in ("warning", "prod", "2026-10-24T07:50:00Z", "More than one 5xx per second", alert.query):
        assert text in body
    assert SIG_LINE.findall(body) == [alert.signature]
    assert alert.signature.startswith("alert:") and re.fullmatch(r"alert:[0-9a-f]{16}", alert.signature)
    assert body.rstrip().splitlines()[-1] == f"Signature: {alert.signature}"


def test_the_signature_comes_from_application_environment_service_and_name_only(tr):
    """AC-092.20 AC-092.24: severity, summary, query, start time and series do not change the signature; each of the four parts does."""
    a = mkalert()
    same = mkalert(severity="critical", summary="other", query="up == 0", started_at=NOW, series=[{"job": "x"}], repo=None)
    assert a.signature == same.signature == autoissue.raw_signature("alert", "shop", "prod", "shop-api", "HighErrorRate")
    others = [mkalert(app="other"), mkalert(environment="dev"), mkalert(service="shop-web"), mkalert(name="Other")]
    assert len({a.signature, *(o.signature for o in others)}) == 5


def test_a_title_is_one_line_and_at_most_100_characters():
    """AC-092.20: a long alert name is cut to 100 characters."""
    import alertissues
    long = alertissues.title(mkalert(name="N" * 200))
    assert len(long) <= 100 and long.startswith("[auto] [alert] N") and "\n" not in long
    assert "\n" not in alertissues.title(mkalert(name="two\nlines"))


# ---------------- AC-092.24 environments ----------------

def test_the_same_alert_in_two_environments_is_two_issues_with_env_labels(tr):
    """AC-092.24: same name and service in dev and prod are separate issues with separate signatures and env labels."""
    dev, prod = mkalert(environment="dev"), mkalert(environment="prod")
    run(tr, [dev, prod])
    created = {c[2]: c for c in tr.created()}
    assert set(created) == {"[auto] [alert] HighErrorRate: shop-api in dev", "[auto] [alert] HighErrorRate: shop-api in prod"}
    assert "env:dev" in created["[auto] [alert] HighErrorRate: shop-api in dev"][4]
    assert "env:prod" in created["[auto] [alert] HighErrorRate: shop-api in prod"][4]
    assert SIG_LINE.findall(created["[auto] [alert] HighErrorRate: shop-api in dev"][3]) != SIG_LINE.findall(
        created["[auto] [alert] HighErrorRate: shop-api in prod"][3])


# ---------------- AC-092.8 unmapped alerts land in the gitops repo ----------------

@pytest.mark.parametrize("notes", [
    ['service label "billing" (or job "billing") is not a service in services.yaml'],
    ["service shop-batch has no repo in services.yaml"],
])
def test_an_unmapped_alert_is_filed_in_the_gitops_repo_and_the_body_says_why(tr, notes):
    """AC-092.8: no services.yaml entry, or an entry without repo: the issue goes to the gitops-app repo and names the unmapped values."""
    run(tr, [mkalert(repo=None, service="billing", unmapped=notes)], repos=[GITOPS])
    ((_, repo, title, body, labels),) = tr.created()
    assert repo == GITOPS and title.startswith("[auto] [alert] HighErrorRate: billing in prod")
    assert {"triage", "auto-filed", "alert"} <= set(labels)
    for note in notes:
        assert note in body
    assert tr.created(API) == []


# ---------------- AC-092.9 no write access to the target repo ----------------

@pytest.mark.parametrize("reason", ["GitHub refused: HTTP 403: Resource not accessible by personal access token", "GitHub refused: HTTP 404: Not Found"])
def test_a_repo_the_credential_cannot_write_to_gets_the_issue_in_the_gitops_repo(tr, reason):
    """AC-092.9: the issue is filed in the gitops-app repo instead, names the intended repo and the reason, and the run ends red."""
    tr.raises[API] = reason
    res = run(tr, [mkalert()])
    assert [c[1] for c in tr.created()] == [GITOPS]
    body = tr.created()[0][3]
    assert API in body and reason.split(": ", 1)[1] in body and "ALERTS_TOKEN" in body
    assert len(res.rerouted) == 1 and res.rerouted[0].startswith(f"{API}: ")
    assert any(f"filed in {GITOPS} instead of {API}" in line for line in res.lines)


def test_other_github_failures_are_errors_not_reroutes(tr):
    """AC-092.9 AC-092.16: only missing access reroutes; any other GitHub failure is reported and never raised."""
    tr.raises[API] = "GitHub refused: HTTP 500: server error"
    res = run(tr, [mkalert()])
    assert tr.created() == [] and res.rerouted == []
    assert res.errors and res.errors[0].startswith(f"{API}: ")


# ---------------- AC-092.10 redaction and quoted data ----------------

def test_secrets_in_alert_text_are_redacted_everywhere(tr):
    """AC-092.10: tokens in labels, annotations, summaries, queries and names never reach the title or the body."""
    alert = mkalert(name=f"Leak{TOKEN}", summary=f"password is {TOKEN}", query=f'up{{token="{TOKEN}"}} == 0',
                    series=[{"job": "shop-api", "auth": TOKEN}], annotations={"description": f"key {TOKEN}"}, source="alertmanager")
    run(tr, [alert])
    ((_, _, title, body, _),) = tr.created()
    assert TOKEN not in title and TOKEN not in body and "a1b2c3d4e5a1b2c3d4e5" not in body


def test_label_values_are_quoted_data_not_markdown(tr):
    """AC-092.10: label and annotation values appear inside fences; mentions, links and emphasis in the name and service list never render."""
    alert = mkalert(name="Bad_Name*[x](http://evil.example)", service="a_b*c`d`<e>@octocat",
                    series=[{"job": "x", "note": "[click](http://evil.example) @octocat"}],
                    annotations={"summary": "[click](http://evil.example) @octocat"}, source="alertmanager")
    run(tr, [alert])
    body = tr.created()[0][3]
    prose = outside_fences(body)
    assert "@octocat" not in prose and "](" not in prose and "<e>" not in prose and "`d`" not in prose
    assert "[click](http://evil.example)" in body          # still shown, as data inside a fence
    service_line = next(ln for ln in body.splitlines() if ln.startswith("- service: "))
    assert not set("`*_[]<>@") & set(service_line[len("- service: "):])


def test_a_signature_line_in_alert_text_cannot_add_a_second_signature(tr):
    """AC-092.10 AC-092.20: text that looks like a signature line is quoted, so the body keeps exactly one."""
    alert = mkalert(summary="boom\nSignature: alert:0123456789abcdef", annotations={"x": "\nSignature: alert:fedcba9876543210"},
                    source="alertmanager")
    run(tr, [alert])
    assert SIG_LINE.findall(tr.created()[0][3]) == [alert.signature]


# ---------------- AC-092.11 still firing ----------------

def test_an_alert_still_firing_with_an_open_issue_adds_nothing(tr):
    """AC-092.11: an open issue with the signature and a still-firing alert: no new issue and no comment."""
    alert = mkalert()
    seed(tr, alert)
    res = run(tr, [alert])
    assert tr.writes() == [] and res.errors == []


def test_firing_alert_after_a_fired_again_comment_stays_quiet(tr):
    """AC-092.11 AC-092.21: when the last poll comment is `Fired again`, the alert is firing and nothing is written."""
    import alertissues
    alert = mkalert()
    seed(tr, alert, comments=[resolved_comment(alert), alertissues.render_fired_again(alert, 2, NOW)])
    run(tr, [alert])
    assert tr.writes() == []


# ---------------- AC-092.21 fired again ----------------

def test_a_resolved_alert_that_fires_again_gets_one_counted_comment(tr):
    """AC-092.21: the last poll comment says resolved, the alert fires: one `Fired again` comment with occurrence 2 and the time."""
    alert = mkalert()
    issue = seed(tr, alert, comments=[resolved_comment(alert, NOW - dt.timedelta(hours=2))])
    res = run(tr, [alert])
    ((_, repo, number, body),) = tr.commented()
    assert (repo, number) == (API, issue.number) and tr.created() == []
    assert body.startswith("**Fired again** (occurrence 2) at 2026-10-24T08:00:00Z")
    assert any(line == f"fired again {issue.url}: {title_of(alert)}" for line in res.lines)


def test_the_occurrence_number_counts_earlier_fired_again_comments(tr):
    """AC-092.21: occurrence numbers go 2, 3, ... (2 plus the earlier `Fired again` comments)."""
    import alertissues
    alert = mkalert()
    seed(tr, alert, comments=[resolved_comment(alert), alertissues.render_fired_again(alert, 2, NOW), resolved_comment(alert)])
    run(tr, [alert])
    assert tr.commented()[0][3].startswith("**Fired again** (occurrence 3)")


def test_the_oldest_open_issue_with_the_signature_gets_the_comment(tr):
    """AC-092.21: with several open issues for the signature, only the oldest is commented on."""
    alert = mkalert()
    old = seed(tr, alert, comments=[resolved_comment(alert)], created_at="2026-10-20T08:00:00Z")
    seed(tr, alert, comments=[resolved_comment(alert)], created_at="2026-10-22T08:00:00Z")
    run(tr, [alert])
    assert [(c[1], c[2]) for c in tr.commented()] == [(API, old.number)]


def test_render_helpers_fired_again_and_resolved_comments():
    """AC-092.21 AC-092.13: the comments start with the markers the poll reads back, with UTC times."""
    import alertissues
    alert = mkalert()
    assert alertissues.FIRED_AGAIN == "**Fired again** " and alertissues.RESOLVED == "**Resolved** at "
    assert alertissues.render_fired_again(alert, 4, NOW).startswith("**Fired again** (occurrence 4) at 2026-10-24T08:00:00Z")
    assert alertissues.render_resolved("t", NOW, closed=False).startswith("**Resolved** at 2026-10-24T08:00:00Z")
    closed = alertissues.render_resolved("t", NOW, closed=True)
    assert "Closed by the alert poll because it was still untriaged" in closed
    assert "Closed by the alert poll" not in alertissues.render_resolved("t", NOW, closed=False)


# ---------------- AC-092.13 resolve and close ----------------

def test_an_alert_that_stopped_firing_is_resolved_and_closed_while_untriaged(tr):
    """AC-092.13: one `resolved at <time>` comment, and the issue is closed because it still carries `triage`."""
    alert = mkalert()
    issue = seed(tr, alert)
    res = run(tr, [])
    ((_, repo, number, body),) = tr.commented()
    assert (repo, number) == (API, issue.number)
    assert body.startswith("**Resolved** at 2026-10-24T08:00:00Z") and "Closed by the alert poll" in body
    assert tr.of("close") == [("close", API, issue.number)] and tr.get(API, issue.number).state == "closed"
    assert any(line == f"resolved {issue.url}: {title_of(alert)}" for line in res.lines)
    assert any(line == f"closed {issue.url}: {title_of(alert)}" for line in res.lines)


def test_a_triaged_issue_is_commented_but_never_closed(tr):
    """AC-092.13: once `triage` is gone somebody routed the issue: the poll comments the resolution and leaves it open."""
    alert = mkalert()
    issue = seed(tr, alert, labels=["auto-filed", "alert", "env:prod", "bug"])
    run(tr, [])
    assert [c[2] for c in tr.commented()] == [issue.number] and tr.commented()[0][3].startswith("**Resolved** at ")
    assert "Closed by the alert poll" not in tr.commented()[0][3]
    assert tr.of("close") == [] and tr.get(API, issue.number).state == "open"


def test_a_resolved_but_still_untriaged_open_issue_is_closed_without_a_second_comment(tr):
    """AC-092.13: never comment twice; an already resolved issue that still has `triage` is only closed."""
    alert = mkalert()
    issue = seed(tr, alert, comments=[resolved_comment(alert)])
    run(tr, [])
    assert tr.commented() == [] and tr.of("close") == [("close", API, issue.number)]


def test_a_resolved_triaged_issue_is_left_alone(tr):
    """AC-092.13: already resolved and already routed: nothing to do."""
    alert = mkalert()
    seed(tr, alert, comments=[resolved_comment(alert)], labels=["auto-filed", "alert", "env:prod", "bug"])
    run(tr, [])
    assert tr.writes() == []


def test_resolving_only_touches_this_apps_alert_issues_that_are_not_firing(tr):
    """AC-092.13: another application's issue, a firing alert's issue and a plain issue are not resolved."""
    firing, other = mkalert(), mkalert(name="Other")
    seed(tr, firing)
    seed(tr, other, gitops="acme/other-gitops")                                     # another application
    tr.add(API, title="a bug", body="not an alert", labels=["triage", "auto-filed", "alert"])    # no signature line
    run(tr, [firing])
    assert tr.writes() == []


def test_the_poll_looks_for_resolved_issues_in_every_repo_it_was_given(tr):
    """AC-092.13: issues in the gitops repo and in a service repo are both resolved."""
    in_api, in_gitops = mkalert(), mkalert(name="Meta", repo=None)
    a, b = seed(tr, in_api), seed(tr, in_gitops)
    run(tr, [])
    assert {(c[1], c[2]) for c in tr.commented()} == {(API, a.number), (GITOPS, b.number)}


# ---------------- AC-092.22 closed issues ----------------

def test_an_issue_the_poll_closed_as_resolved_is_reopened_within_seven_days(tr):
    """AC-092.22: closed by the poll as resolved in the last 7 days: reopened, with a counted `fired again` comment."""
    alert = mkalert()
    when = NOW - dt.timedelta(days=2)
    issue = seed(tr, alert, state="closed", closed_at=iso(when), comments=[resolved_comment(alert, when, closed=True)])
    res = run(tr, [alert])
    assert tr.of("reopen") == [("reopen", API, issue.number)] and tr.created() == []
    assert tr.commented()[0][3].startswith("**Fired again** (occurrence 2)")
    assert any(line == f"reopened {issue.url}: {title_of(alert)}" for line in res.lines)


def test_an_issue_the_poll_closed_more_than_seven_days_ago_is_not_reopened(tr):
    """AC-092.22: older than 7 days: a new issue says `Seen again after #<n> was closed`."""
    alert = mkalert()
    when = NOW - dt.timedelta(days=8)
    issue = seed(tr, alert, state="closed", closed_at=iso(when), comments=[resolved_comment(alert, when, closed=True)])
    run(tr, [alert])
    assert tr.of("reopen") == []
    ((_, repo, _, body, _),) = tr.created()
    assert repo == API and f"Seen again after #{issue.number} was closed" in body
    assert SIG_LINE.findall(body) == [alert.signature]


def test_an_issue_closed_by_a_person_is_not_reopened(tr):
    """AC-092.22: closed by hand (no poll comment), even a day ago: a new issue that links the closed one."""
    alert = mkalert()
    issue = seed(tr, alert, state="closed", closed_at=iso(NOW - dt.timedelta(days=1)), labels=["auto-filed", "alert", "env:prod", "bug"])
    run(tr, [alert])
    assert tr.of("reopen") == []
    assert f"Seen again after #{issue.number} was closed" in tr.created()[0][3]


def test_a_wontfix_issue_suppresses_the_alert(tr):
    """AC-092.22: the most recently closed issue carries `wontfix`: nothing is filed and the summary notes `suppressed by #<n>`."""
    alert = mkalert()
    issue = seed(tr, alert, state="closed", closed_at=iso(NOW - dt.timedelta(days=30)), labels=["auto-filed", "alert", "wontfix"])
    res = run(tr, [alert])
    assert tr.writes() == []
    assert any(line == f"suppressed by #{issue.number} (wontfix): {title_of(alert)}" for line in res.lines)


def test_the_most_recently_closed_issue_decides(tr):
    """AC-092.22: an older wontfix issue does not suppress when a newer closed issue was closed by the poll within 7 days."""
    alert = mkalert()
    seed(tr, alert, state="closed", closed_at=iso(NOW - dt.timedelta(days=60)), labels=["auto-filed", "alert", "wontfix"])
    when = NOW - dt.timedelta(days=1)
    newer = seed(tr, alert, state="closed", closed_at=iso(when), comments=[resolved_comment(alert, when, closed=True)])
    run(tr, [alert])
    assert tr.of("reopen") == [("reopen", API, newer.number)]


# ---------------- AC-092.15 cap of 10 ----------------

def twelve():
    out = []
    for i, sev in enumerate(["critical"] * 3 + ["warning"] * 4 + ["info"] * 5):
        out.append(mkalert(name=f"Alert{i:02d}", severity=sev, started_at=NOW - dt.timedelta(hours=1) + dt.timedelta(minutes=i)))
    return out


def test_more_than_ten_new_alerts_file_the_ten_most_severe_and_list_the_rest(tr):
    """AC-092.15: critical before warning before info, then oldest first; one summary issue in the gitops repo lists the rest."""
    alerts = twelve()
    res = run(tr, list(reversed(alerts)))
    filed = [c[2] for c in tr.created(API)]
    assert sorted(filed) == sorted(title_of(a) for a in alerts[:10])
    assert filed[:3] == [title_of(a) for a in alerts[:3]]                      # critical first
    summaries = tr.created(GITOPS)
    assert len(summaries) == 1
    _, _, title, body, labels = summaries[0]
    assert title == "[auto] [alert] more than 10 new alerts: shop" and {"triage", "auto-filed", "alert"} <= set(labels)
    assert all(a.name in body for a in alerts[10:]) and not any(a.name in body for a in alerts[:10])
    assert SIG_LINE.findall(body) == [autoissue.raw_signature("alert", "shop", "*", "alert-poll", "AlertsDeferred")]
    assert len([line for line in res.lines if line.startswith("deferred (cap of 10 new issues per poll): ")]) == 2


def test_the_rest_is_filed_at_later_polls_and_the_open_summary_gets_a_comment(tr):
    """AC-092.15: the deferred alerts are filed next time; a comment on the open summary issue replaces a second summary issue."""
    alerts = [mkalert(name=f"Alert{i:02d}", started_at=NOW - dt.timedelta(hours=1) + dt.timedelta(minutes=i)) for i in range(25)]
    run(tr, alerts)
    assert len(tr.created(API)) == 10 and len(tr.created(GITOPS)) == 1
    summary = tr.issues[GITOPS][0]
    run(tr, alerts)
    assert len(tr.created(API)) == 20 and len(tr.created(GITOPS)) == 1
    deferred = [c for c in tr.commented(GITOPS) if c[2] == summary.number and c[3].startswith("**Deferred** at ")]
    assert len(deferred) == 1 and "Alert24" in deferred[0][3]
    run(tr, alerts)
    assert len(tr.created(API)) == 25


def test_comments_on_existing_issues_are_not_capped(tr):
    """AC-092.15: twelve `fired again` comments are all written and no summary issue appears."""
    alerts = twelve()
    for a in alerts:
        seed(tr, a, comments=[resolved_comment(a)])
    run(tr, alerts)
    assert len(tr.commented(API)) == 12 and tr.created() == []


# ---------------- AC-092.16 no resolve when the poll could not read everything ----------------

def test_nothing_is_resolved_or_closed_when_a_source_failed(tr):
    """AC-092.16: with resolve=False (an endpoint was unreachable) no issue is commented on or closed, however quiet it looks."""
    alert = mkalert()
    seed(tr, alert)
    res = run(tr, [], resolve=False)
    assert tr.writes() == [] and tr.of("close") == [] and res.errors == []


def test_github_failures_are_reported_and_never_raised(tr):
    """AC-092.16: a GitHub failure while looking up issues ends up in `errors`; reconcile never raises."""
    tr.raises[API] = "GitHub refused: HTTP 502: bad gateway"
    tr.raises[GITOPS] = "gh is not logged in"
    res = run(tr, [mkalert()])
    assert tr.writes() == [] and len(res.errors) >= 1


# ---------------- AC-092.18 dry run ----------------

def test_a_dry_run_prints_every_action_and_writes_nothing(tr):
    """AC-092.18: DRY RUN lines for file, comment, reopen, resolve and close with repo and title; no write call at all."""
    new = mkalert(name="NewOne")
    again = mkalert(name="Again")
    reopened = mkalert(name="Reopened")
    gone = mkalert(name="Gone")
    again_issue = seed(tr, again, comments=[resolved_comment(again)])
    when = NOW - dt.timedelta(days=1)
    reopen_issue = seed(tr, reopened, state="closed", closed_at=iso(when), comments=[resolved_comment(reopened, when, closed=True)])
    gone_issue = seed(tr, gone)
    res = run(tr, [new, again, reopened], dry_run=True)
    assert tr.writes() == []
    assert f"DRY RUN: would file in {API}: {title_of(new)}" in res.lines
    assert f"DRY RUN: would comment on {API}#{again_issue.number} (fired again): {title_of(again)}" in res.lines
    assert f"DRY RUN: would reopen {API}#{reopen_issue.number}: {title_of(reopened)}" in res.lines
    assert f"DRY RUN: would comment on {API}#{gone_issue.number} (resolved): {title_of(gone)}" in res.lines
    assert f"DRY RUN: would close {API}#{gone_issue.number}: {title_of(gone)}" in res.lines
    assert tr.get(API, gone_issue.number).state == "open"


def test_a_dry_run_names_the_reroute(tr):
    """AC-092.18 AC-092.9: a reroute shows up as a DRY RUN line too, still without writes."""
    tr.raises[API] = "GitHub refused: HTTP 403: Resource not accessible"
    res = run(tr, [mkalert()], dry_run=True)
    assert tr.writes() == []
    assert any(line.startswith(f"DRY RUN: would file in {GITOPS} instead of {API}: ") for line in res.lines)


# ---------------- AC-092.23 Alertmanager alerts are handled like rule alerts ----------------

def am_alert(**kw):
    base = dict(source="alertmanager", name="DiskFull", severity="critical", query="Alertmanager https://am.example.com",
                summary="disk is full", annotations={"summary": "disk is full", "runbook": "https://wiki.example.com/disk"},
                series=[{"alertname": "DiskFull", "service": "shop-api"}])
    base.update(kw)
    return mkalert(**base)


def test_an_alertmanager_alert_is_filed_like_a_rule_alert_and_names_its_source(tr):
    """AC-092.23: mapped, labelled and signed as in AC-092.20; the body names Alertmanager and shows the annotations as data."""
    alert = am_alert()
    run(tr, [alert])
    ((_, repo, title, body, labels),) = tr.created()
    assert repo == API and title == "[auto] [alert] DiskFull: shop-api in prod"
    assert set(labels) == {"triage", "auto-filed", "alert", "env:prod"}
    assert "Alertmanager" in body and "Alertmanager https://am.example.com" in body and "## Annotations" in body
    assert 'runbook="https://wiki.example.com/disk"' in body
    assert SIG_LINE.findall(body) == [alert.signature]


def test_an_alertmanager_alert_is_deduplicated_resolved_and_capped_like_rule_alerts(tr):
    """AC-092.23: open issue and still firing: quiet; gone: resolved and closed; the cap of 10 counts them too."""
    alert = am_alert()
    seed(tr, alert)
    run(tr, [alert])
    assert tr.writes() == []
    run(tr, [])
    assert tr.commented()[0][3].startswith("**Resolved** at ") and len(tr.of("close")) == 1
    tr2 = FakeTracker()
    run(tr2, [am_alert(name=f"Am{i:02d}") for i in range(11)])
    assert len(tr2.created(API)) == 10 and len(tr2.created(GITOPS)) == 1


# ---------------- tracker additions of autoissue (token, open_issues, close, reopen, ensure_labels) ----------------

class FakeGh:
    def __init__(self, answers=None):
        self.calls: list[tuple[list[str], dict]] = []
        self.answers = answers or {}

    def __call__(self, args, **kw):
        self.calls.append((list(args), kw))
        for prefix, answer in self.answers.items():
            if args[: len(prefix)] == list(prefix):
                return answer
        return 0, "", ""


def test_the_tracker_can_write_with_a_chosen_token(monkeypatch):
    """AC-092.9: `GhTracker(token=...)` passes the token to gh for every call; without a token gh is called as in 088."""
    fake = FakeGh({("issue", "comment"): (0, "https://github.com/acme/shop-api/issues/1#issuecomment-1\n", "")})
    monkeypatch.setattr(autoissue, "gh", fake)
    autoissue.GhTracker(token="tok").comment(API, 1, "hello", 5.0)
    assert fake.calls[0][1].get("token") == "tok"
    fake.calls.clear()
    autoissue.GhTracker().comment(API, 1, "hello", 5.0)
    assert "token" not in fake.calls[0][1]


def test_gh_with_a_token_sets_gh_token_and_drops_github_token(monkeypatch):
    """AC-092.9: with a token the child gets GH_TOKEN=<token> and no GITHUB_TOKEN."""
    seen = {}

    def fake_run(cmd, **kw):
        seen["env"] = kw.get("env")
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(autoissue.subprocess, "run", fake_run)
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-token")
    autoissue.gh(["issue", "list"], token="fine-grained")
    assert seen["env"]["GH_TOKEN"] == "fine-grained" and "GITHUB_TOKEN" not in seen["env"]


def test_open_issues_lists_open_issues_by_label_and_drops_pull_requests(monkeypatch):
    """AC-092.13: the resolve phase lists open issues by label through the REST list; pull requests are dropped."""
    page = ('[{"number": 3, "html_url": "https://github.com/acme/shop-api/issues/3", "state": "open", "labels": [{"name": "alert"}], '
            '"created_at": "2026-10-24T07:00:00Z", "closed_at": null, "body": "b"}, '
            '{"number": 4, "pull_request": {}, "state": "open", "labels": [], "created_at": "", "body": ""}]')
    fake = FakeGh({("api",): (0, page, "")})
    monkeypatch.setattr(autoissue, "gh", fake)
    issues = autoissue.GhTracker().open_issues(API, ["auto-filed", "alert"], 5.0)
    assert [i.number for i in issues] == [3]
    assert fake.calls[0][0] == ["api", "--paginate", f"repos/{API}/issues?labels=auto-filed,alert&state=open&per_page=100"]


def test_close_and_reopen_use_gh_issue(monkeypatch):
    """AC-092.13 AC-092.22: close is `gh issue close N -R repo --reason completed`, reopen is `gh issue reopen N -R repo`."""
    fake = FakeGh()
    monkeypatch.setattr(autoissue, "gh", fake)
    t = autoissue.GhTracker()
    t.close(API, 7, 5.0)
    t.reopen(API, 7, 5.0)
    assert fake.calls[0][0] == ["issue", "close", "7", "-R", API, "--reason", "completed"]
    assert fake.calls[1][0] == ["issue", "reopen", "7", "-R", API]
    monkeypatch.setattr(autoissue, "gh", FakeGh({("issue", "close"): (1, "", "HTTP 404: Not Found")}))
    with pytest.raises(autoissue.TrackerError):
        autoissue.GhTracker().close(API, 7, 5.0)


def test_ensure_labels_creates_each_label_and_ignores_existing_ones(monkeypatch):
    """AC-092.20: labels are created first if missing; `already exists` is success, any other failure is a TrackerError."""
    fake = FakeGh({("label", "create", "alert"): (1, "", 'label with name "alert" already exists')})
    monkeypatch.setattr(autoissue, "gh", fake)
    autoissue.GhTracker().ensure_labels(API, {"alert": ("d93f0b", "An alert"), "env:prod": ("5319e7", "Environment prod (spec 092)")}, 5.0)
    created = [c[0] for c in fake.calls]
    assert ["label", "create", "env:prod", "-R", API, "--color", "5319e7", "--description", "Environment prod (spec 092)"] in created
    assert any(c[:3] == ["label", "create", "alert"] for c in created)
    monkeypatch.setattr(autoissue, "gh", FakeGh({("label", "create"): (1, "", "HTTP 403: forbidden")}))
    with pytest.raises(autoissue.TrackerError):
        autoissue.GhTracker().ensure_labels(API, {"alert": ("d93f0b", "An alert")}, 5.0)


def test_the_default_tracker_writes_other_repos_with_alerts_token(monkeypatch):
    """AC-092.9: `alertissues.tracker()` writes the gitops repo with the workflow token and a service repo with ALERTS_TOKEN when set."""
    import alertissues
    fake = FakeGh({("issue", "comment"): (0, "https://github.com/x/y/issues/1#issuecomment-1\n", "")})
    monkeypatch.setattr(autoissue, "gh", fake)
    monkeypatch.setenv("ALERTS_TOKEN", "svc-token")
    t = alertissues.tracker(GITOPS)
    t.comment(API, 1, "x", 5.0)
    t.comment(GITOPS, 1, "x", 5.0)
    assert fake.calls[0][1].get("token") == "svc-token" and "token" not in fake.calls[1][1]
    monkeypatch.delenv("ALERTS_TOKEN")
    fake.calls.clear()
    alertissues.tracker(GITOPS).comment(API, 1, "x", 5.0)
    assert "token" not in fake.calls[0][1]
