"""Spec 088: platform failures become deduplicated issues (signature, redaction, dedupe, cap, pending retry, off switch).

Nothing here reaches GitHub: `autoissue.tracker()` is replaced by `FakeTracker`, and the clocks by `Clock`."""
import datetime as dt
import hashlib
import json
import re

import pytest

import core
import runs
import triage
from test_runs import MemStore, attach, followups, stored  # noqa: F401  (helpers)
from test_runs import clock as run_clock, mem, store  # noqa: F401  (fixtures)

SIG_LINE = re.compile(r"^Signature: (platform|smoke|alert):[0-9a-f]{16}$", re.M)
PLATFORM_REPO = "ika100/sdlc-foundry"
TOKEN = "ghp_" + "a1b2c3d4e5" * 4


# ---------------- fakes ----------------

class Clock:
    def __init__(self):
        self.t = dt.datetime(2026, 10, 24, 8, 0, 0, tzinfo=dt.timezone.utc)
        self.mono = 0.0

    def now(self):
        return self.t

    def monotonic(self):
        return self.mono

    def tick(self, seconds):
        self.t += dt.timedelta(seconds=seconds)


class FakeTracker:
    """An in-memory GitHub: issues per repo, comments per issue, and a switch that makes every call fail."""

    def __init__(self, ai, clk):
        self.ai, self.clk = ai, clk
        self.issues: dict[str, list] = {}
        self.cmts: dict[tuple[str, int], list[str]] = {}
        self.calls: list[tuple] = []
        self.error: Exception | None = None
        self.cost = 0.0                      # fake seconds that each call takes
        self.n = 0

    def _enter(self, what, *args):
        self.calls.append((what, *args))
        self.clk.mono += self.cost
        if self.error:
            raise self.error

    def find(self, repo, signature, timeout):
        self._enter("find", repo, signature)
        return [i for i in self.issues.get(repo, []) if signature in i.body]

    def comments(self, repo, number, timeout):
        self._enter("comments", repo, number)
        return list(self.cmts.get((repo, number), []))

    def create(self, repo, title, body, labels, timeout):
        self._enter("create", repo, title, body, labels)
        issue = self.add(repo, body=body, title=title, labels=labels)
        return issue.url

    def comment(self, repo, number, body, timeout):
        self._enter("comment", repo, number, body)
        self.cmts.setdefault((repo, number), []).append(body)
        return f"https://github.com/{repo}/issues/{number}#issuecomment-{len(self.cmts[(repo, number)])}"

    # ---- test helpers
    def add(self, repo=PLATFORM_REPO, *, body, title="[auto] x", labels=("triage", "auto-filed", "bug"), state="open",
            created_at=None, closed_at=None):
        self.n += 1
        issue = self.ai.Issue(number=self.n, url=f"https://github.com/{repo}/issues/{self.n}", state=state, labels=list(labels),
                              created_at=created_at or self.clk.t.strftime("%Y-%m-%dT%H:%M:%SZ"), closed_at=closed_at, body=body)
        issue.title = title
        self.issues.setdefault(repo, []).append(issue)
        return issue

    def of(self, what):
        return [c for c in self.calls if c[0] == what]

    def created(self):
        return self.of("create")

    def commented(self):
        return self.of("comment")


@pytest.fixture()
def clk():
    return Clock()


@pytest.fixture()
def ai(monkeypatch, clk):
    import autoissue
    monkeypatch.setattr(autoissue, "now", clk.now)
    monkeypatch.setattr(autoissue, "monotonic", clk.monotonic)
    return autoissue


@pytest.fixture()
def tr(ai, clk, monkeypatch):
    t = FakeTracker(ai, clk)
    monkeypatch.setattr(ai, "tracker", lambda: t)
    return t


def mkdraft(ai, reason="merge conflict in the generated Dockerfile", command="cplat ship land", phase="pr", **kw):
    names = kw.pop("names", {})
    sig = kw.pop("signature", None) or ai.signature("platform", command, phase, reason, names=names)
    kw.setdefault("run_id", "20261024T080000Z-aaaa1111")
    kw.setdefault("environment", ["- platform: 4.4.0", "- OS: Linux 6 (x86_64)"])
    return ai.Draft(kind="platform", signature=sig, reason=reason, command=command, phase=phase, names=names, **kw)


def sig_of(d):
    return d.signature


# ---------------- AC-088.5 signatures ----------------

def test_a_raw_signature_is_the_kind_and_16_hex_of_the_sha256(ai):
    """AC-088.5 AC-088.6: `<kind>:<first 16 hex of sha256 of the parts joined by newline>`; unknown kinds are refused."""
    want = hashlib.sha256("a\nb".encode()).hexdigest()[:16]
    assert ai.raw_signature("platform", "a", "b") == f"platform:{want}"
    assert re.fullmatch(r"(smoke|alert):[0-9a-f]{16}", ai.raw_signature("smoke", "x")) and ai.raw_signature("alert", "x").startswith("alert:")
    with pytest.raises(ValueError):
        ai.raw_signature("other", "a")
    with pytest.raises(ValueError):
        ai.signature("other", "a")


@pytest.mark.parametrize("a, b", [
    ("build 12 failed after 3m 20s", "build 981 failed after 45s"),
    ("image sha256:" + "a" * 64 + " not found", "image sha256:" + "0" * 64 + " not found"),
    ("checkout 3f9c2ab1 failed", "checkout 0b17de94 failed"),
    ("PR #123 did not merge, see issue #77", "PR #9 did not merge, see issue #1204"),
    ("failed on 2026-10-24", "failed on 2026-11-02"),
    ("failed at 2026-10-24T08:00:01Z", "failed at 2026-11-02T17:45:59+02:00"),
    ("pull of https://ghcr.io/acme/a:1 failed", "pull of http://example.org/other/path failed"),
    ("cannot read /home/anna/work/x/spec.md", "cannot read /Users/bob/dev/y/spec.md"),
    ("cannot read ./docs/specs/a.md", "cannot read ../tmp/zz/b.md"),
    ("platform 4.4.0 cannot render", "platform 4.5.1 cannot render"),
    ("platform v4.4.0-rc1 cannot render", "platform v5.0.0 cannot render"),
    ("gate failed after 12.5s", "gate failed after 3 minutes"),
])
def test_signatures_ignore_volatile_parts(ai, a, b):
    """AC-088.5: numbers, hashes, PR/issue numbers, dates, durations, URLs, paths and versions do not change the signature."""
    assert ai.signature("platform", "cplat ship land", "pr", a) == ai.signature("platform", "cplat ship land", "pr", b)


def test_signatures_ignore_repo_spec_and_branch_names(ai):
    """AC-088.5: the consumer's repo, spec and branch names are volatile."""
    n1 = ai.private_names("acme/shop-api", "007-price-alerts", "feature/007-price-alerts")
    n2 = ai.private_names("other/billing", "031-invoices", "feature/031-invoices")
    a = ai.signature("platform", "cplat ship land", "pr", "render failed for shop-api in 007-price-alerts on feature/007-price-alerts", names=n1)
    b = ai.signature("platform", "cplat ship land", "pr", "render failed for billing in 031-invoices on feature/031-invoices", names=n2)
    assert a == b


@pytest.mark.parametrize("a, b", [
    (("cplat ship land", "pr", "merge failed"), ("cplat ship pr", "pr", "merge failed")),
    (("cplat ship land", "pr", "merge failed"), ("cplat ship land", "build", "merge failed")),
    (("cplat ship land", "pr", "merge failed"), ("cplat ship land", "pr", "render failed")),
    (("cplat ship land", "pr", "merge failed"), ("cplat ship land", "pr", "Merge failed")),
])
def test_signatures_differ_with_command_phase_or_text(ai, a, b):
    """AC-088.5: a different command, phase or remaining failure text (also by letter case) is a different failure."""
    assert ai.signature("platform", *a) != ai.signature("platform", *b)


def test_a_signature_depends_on_the_kind_but_not_on_the_shape(ai):
    """AC-088.5 AC-088.6: the same parts under another kind differ; the shape is not an input of the draft's signature."""
    assert ai.signature("platform", "a", "b") != ai.signature("smoke", "a", "b")
    assert mkdraft(ai, shape="service-go").signature == mkdraft(ai, shape="service-python").signature


def test_normalise_replaces_volatile_parts_with_fixed_placeholders(ai):
    """AC-088.5: normalise is deterministic and leaves the stable words alone."""
    out = ai.normalise("copier failed in 12.5s on 2026-10-24 for #77 (see https://github.com/a/b) at /home/x/y/z")
    assert out == ai.normalise("copier failed in 90s on 2025-01-01 for #3 (see https://example.org/q) at /tmp/a/b")
    assert "copier failed" in out and "12.5" not in out and "2026" not in out and "https://" not in out


# ---------------- AC-088.5 crash signatures ----------------

def boom(frame_file, func, exc):
    """Raise `exc` from a function that looks as if it lived in scripts/cplat/<frame_file>."""
    src = f"def {func}():\n    raise EXC\n"
    ns = {"EXC": exc}
    exec(compile(src, str(core.PLATFORM_ROOT / "scripts" / "cplat" / frame_file), "exec"), ns)  # noqa: S102
    try:
        ns[func]()
    except Exception as e:  # noqa: BLE001
        return e


def test_a_crash_signature_is_command_exception_type_and_innermost_platform_frame(ai, tmp_path):
    """AC-088.5: another message, line or argument value keeps the signature; another type, frame or command changes it."""
    d1 = ai.crash_draft(["component", "ship", "land", "--repo", "/x/a"], boom("ship.py", "land", ValueError("one 12")), "r1", tmp_path)
    d2 = ai.crash_draft(["component", "ship", "land", "--repo", "/y/b"], boom("ship.py", "land", ValueError("two 99")), "r2", tmp_path)
    assert d1.signature == d2.signature and SIG_LINE.fullmatch("Signature: " + d1.signature)
    assert d1.signature == ai.raw_signature("platform", "cplat component ship land", "ValueError", "ship.py:land")
    others = [
        ai.crash_draft(["component", "ship", "land"], boom("ship.py", "land", KeyError("one")), "r", tmp_path),
        ai.crash_draft(["component", "ship", "land"], boom("ship.py", "open_pr", ValueError("one")), "r", tmp_path),
        ai.crash_draft(["component", "ship", "land"], boom("pr.py", "land", ValueError("one")), "r", tmp_path),
        ai.crash_draft(["component", "ship", "pr"], boom("ship.py", "land", ValueError("one")), "r", tmp_path),
    ]
    assert len({d1.signature, *(o.signature for o in others)}) == 5


def test_a_crash_command_names_the_group_subcommand_but_not_option_values(ai, tmp_path):
    """AC-088.5: `cplat <argv[0]>`, plus the first later word of a subcommand group that is not an option's value."""
    e = boom("ship.py", "land", ValueError("x"))
    assert ai.crash_draft(["component", "ship", "--repo", "land", "escalate", "why"], e, "r", tmp_path).command == "cplat component ship escalate"
    assert ai.crash_draft(["system", "status"], e, "r", tmp_path).command == "cplat system status"
    assert ai.crash_draft(["system", "status", "extra"], e, "r", tmp_path).command == "cplat system status"


def test_a_crash_without_a_platform_frame_is_outside(ai, tmp_path):
    """AC-088.5: no frame in scripts/cplat gives `<outside>:<function of the last frame>`."""
    def elsewhere():
        raise ValueError("x")
    try:
        elsewhere()
    except ValueError as e:
        d = ai.crash_draft(["status"], e, "r", tmp_path)
    assert d.signature == ai.raw_signature("platform", "cplat status", "ValueError", "<outside>:elsewhere")


# ---------------- AC-088.6 title, body, labels ----------------

def test_the_body_has_exactly_one_signature_line_and_the_title_is_auto_prefixed(ai):
    """AC-088.6: `Signature: platform:<16 hex>` once; title `[auto] <reason>`."""
    d = mkdraft(ai)
    title, body = ai.render(d)
    assert title == "[auto] merge conflict in the generated Dockerfile"
    assert SIG_LINE.findall(body) == ["platform"] and body.count("Signature:") == 1
    assert f"Signature: {d.signature}" in body.splitlines()


def test_a_long_or_multiline_reason_gives_a_title_of_at_most_100_characters(ai):
    """AC-088.6: first line only, 100 characters at the most, cut with an ellipsis."""
    title, _ = ai.render(mkdraft(ai, reason="x" * 300))
    assert len(title) == 100 and title.startswith("[auto] xxx") and title.endswith("…")
    title, _ = ai.render(mkdraft(ai, reason="first line\nsecond line"))
    assert title == "[auto] first line"
    title, _ = ai.render(mkdraft(ai, reason="y" * 93))
    assert title == "[auto] " + "y" * 93 and len(title) == 100


def test_evidence_that_quotes_a_signature_line_cannot_add_a_second_one(ai):
    """AC-088.6 AC-088.9: a `Signature:` line inside evidence or reason is quoted."""
    other = "Signature: platform:ffffffffffffffff"
    _, body = ai.render(mkdraft(ai, evidence=f"log\n{other}\n  {other}", reason=f"r\n{other}"))
    assert len(SIG_LINE.findall(body)) == 1 and "ffffffffffffffff" in body


def test_smoke_and_alert_drafts_use_the_same_line_with_their_kind(ai):
    """AC-088.6: specs 091 and 092 reuse the line with kinds smoke and alert and their own labels."""
    for kind, label in (("smoke", "smoke-failure"), ("alert", "alert")):
        d = ai.Draft(kind=kind, signature=ai.signature(kind, "x"), reason="r", command="c", phase="p", environment=[])
        _, body = ai.render(d)
        assert f"Signature: {kind}:" in body and len(SIG_LINE.findall(body)) == 1
        assert ai.BASE_LABELS == ["triage", "auto-filed"] and ai.KIND_LABELS[kind] == [label]


# ---------------- AC-088.10 body sections, labels ----------------

def test_a_new_issue_has_the_required_sections_in_order(ai):
    """AC-088.10: reason, command and phase, evidence, environment, run id."""
    d = mkdraft(ai, evidence="line one\nline two", shape="service-go")
    _, body = ai.render(d)
    heads = [ln for ln in body.splitlines() if ln.startswith("## ")]
    assert heads == ["## Reason", "## Command and phase", "## Evidence", "## Environment", "## Run"]
    assert "- command: `cplat ship land`" in body and "- phase: `pr`" in body
    assert "line one\nline two" in body and "- shape: service-go" in body and "- platform: 4.4.0" in body
    assert "- run id: 20261024T080000Z-aaaa1111" in body


def test_evidence_is_cut_to_80_lines_and_6000_characters(ai):
    """AC-088.10: the tail of the evidence."""
    _, body = ai.render(mkdraft(ai, evidence="\n".join(f"line {i}" for i in range(500))))
    ev = body.split("## Evidence", 1)[1].split("## Environment", 1)[0]
    lines = [ln for ln in ev.splitlines() if ln.startswith("line ")]
    assert lines[0] == "line 420" and lines[-1] == "line 499" and len(lines) == 80
    _, body = ai.render(mkdraft(ai, evidence="A" * 3000 + "B" * 9000))
    ev = body.split("## Evidence", 1)[1].split("## Environment", 1)[0]
    assert ev.count("B") <= 6000 and "A" not in ev and ev.count("B") >= 5000


def test_a_missing_evidence_or_run_is_said_so(ai):
    """AC-088.10: `(none)` for no evidence, `none` for no run."""
    _, body = ai.render(mkdraft(ai, evidence="", run_id=None))
    assert "(none)" in body and "- run id: none" in body


def test_a_new_issue_is_filed_with_the_three_labels(ai, tr):
    """AC-088.10: triage, bug and auto-filed (and nothing else for a platform failure)."""
    ai.file(mkdraft(ai), record=False)
    ((_, repo, _title, _body, labels),) = tr.created()
    assert repo == PLATFORM_REPO and sorted(labels) == ["auto-filed", "bug", "triage"]


def test_setup_labels_creates_auto_filed(monkeypatch, capsys):
    """AC-088.10: `cplat triage setup-labels` creates the `auto-filed` label."""
    from test_triage import FakeGh
    assert "auto-filed" in triage.LABELS
    fake = FakeGh(labels=[n for n in triage.LABELS if n != "auto-filed"])
    monkeypatch.setattr(triage, "gh", fake)
    assert triage.main(["setup-labels"]) == 0
    assert [c[2] for c in fake.calls if c[:2] == ["label", "create"]] == ["auto-filed"]


def test_an_auto_filed_issue_is_in_the_intake_queue_like_a_form_filed_one(monkeypatch, capsys):
    """AC-088.10: `cplat triage list` shows it."""
    from test_triage import FakeGh, issue
    assert "auto-filed" in triage.LABELS
    fake = FakeGh(issues=[issue(7, ["triage", "auto-filed", "bug"], title="[auto] merge failed"), issue(8, ["triage", "bug"], title="by form"),
                          issue(9, ["triage", "auto-filed", "wontfix"])])
    monkeypatch.setattr(triage, "gh", fake)
    assert [i["number"] for i in triage.queue(fake.issues)] == [7, 8]
    assert triage.main(["list", "--json"]) == 0
    assert [i["number"] for i in json.loads(capsys.readouterr().out)["issues"]] == [7, 8]


# ---------------- AC-088.7 dedupe on open issues ----------------

def test_the_first_filing_is_new_and_prints_its_url(ai, tr):
    """AC-088.7 AC-088.1: a new issue; the line is `issue: <url> new`."""
    out = ai.file(mkdraft(ai), record=False)
    assert out.result == "new" and out.url == f"https://github.com/{PLATFORM_REPO}/issues/1" and out.number == 1
    assert out.lines == [f"issue: https://github.com/{PLATFORM_REPO}/issues/1 new"]
    assert len(tr.created()) == 1 and not tr.commented()


def test_a_repeat_within_a_minute_is_a_comment_not_a_second_issue(ai, tr, clk):
    """AC-088.7: occurrence 2 with date, platform version, shape and run id; the line is `issue: <url> +1`."""
    ai.file(mkdraft(ai, run_id="r-1", shape="service-go"), record=False)
    clk.tick(30)
    out = ai.file(mkdraft(ai, run_id="r-2", shape="service-python"), record=False)
    assert len(tr.created()) == 1 and len(tr.commented()) == 1
    assert out.result == "+1" and out.lines == [f"issue: https://github.com/{PLATFORM_REPO}/issues/1 +1"]
    assert out.url and "issuecomment" in out.url
    ((_, repo, number, text),) = tr.commented()
    assert (repo, number) == (PLATFORM_REPO, 1)
    assert "Occurrence 2" in text and "2026-10-24" in text and core.platform_version() in text
    assert "service-python" in text and "r-2" in text


def test_the_occurrence_number_counts_up(ai, tr, clk):
    """AC-088.7: 2, 3, 4 …"""
    for n in range(4):
        ai.file(mkdraft(ai, run_id=f"r-{n}"), record=False)
        clk.tick(5)
    texts = [c[3] for c in tr.commented()]
    assert [bool(re.search(rf"Occurrence {k}\b", t)) for k, t in zip((2, 3, 4), texts)] == [True] * 3 and len(tr.created()) == 1


def test_the_comment_goes_to_the_oldest_open_issue(ai, tr):
    """AC-088.7: with several open issues of one signature, the oldest gets it."""
    sig = mkdraft(ai).signature
    tr.add(body=f"Signature: {sig}", created_at="2026-10-02T00:00:00Z")
    old = tr.add(body=f"Signature: {sig}", created_at="2026-10-01T00:00:00Z")
    tr.add(body=f"Signature: {sig}", created_at="2026-10-03T00:00:00Z")
    out = ai.file(mkdraft(ai), record=False)
    assert out.result == "+1" and [(c[1], c[2]) for c in tr.commented()] == [(PLATFORM_REPO, old.number)] and not tr.created()
    assert out.lines == [f"issue: {old.url} +1"]


def test_another_signature_in_the_issue_text_does_not_match(ai, tr):
    """AC-088.7: a candidate counts only with the exact `Signature:` line."""
    sig = mkdraft(ai).signature
    tr.add(body=f"quoted: Signature: {sig} in prose, not on its own line")
    out = ai.file(mkdraft(ai), record=False)
    assert out.result == "new" and not tr.commented()


def test_filing_the_same_run_twice_is_idempotent(ai, tr):
    """AC-088.7: a retry for the same run and signature neither creates nor comments again."""
    first = ai.file(mkdraft(ai, run_id="r-1"), record=False)
    again = ai.file(mkdraft(ai, run_id="r-1"), record=False)
    assert again.result == "new" and again.url == first.url and len(tr.created()) == 1 and not tr.commented()
    ai.file(mkdraft(ai, run_id="r-2"), record=False)
    ai.file(mkdraft(ai, run_id="r-2"), record=False)
    assert len(tr.commented()) == 1


# ---------------- AC-088.8 closed issues ----------------

def test_after_a_closed_issue_a_new_one_says_seen_again(ai, tr):
    """AC-088.8: new issue whose body starts `Seen again after #<n> was closed`."""
    sig = mkdraft(ai).signature
    old = tr.add(body=f"Signature: {sig}", state="closed", closed_at="2026-10-20T00:00:00Z")
    out = ai.file(mkdraft(ai), record=False)
    assert out.result == "new" and not tr.commented()
    ((_, _repo, _title, body, _labels),) = tr.created()
    assert f"Seen again after #{old.number} was closed" in body and len(SIG_LINE.findall(body)) == 1


def test_the_most_recently_closed_issue_is_the_one_linked(ai, tr):
    """AC-088.8: of several closed issues, the one closed last."""
    sig = mkdraft(ai).signature
    tr.add(body=f"Signature: {sig}", state="closed", closed_at="2026-10-20T00:00:00Z")
    late = tr.add(body=f"Signature: {sig}", state="closed", closed_at="2026-10-22T00:00:00Z")
    tr.add(body=f"Signature: {sig}", state="closed", closed_at="2026-10-21T00:00:00Z")
    ai.file(mkdraft(ai), record=False)
    assert f"Seen again after #{late.number} was closed" in tr.created()[0][3]


def test_a_wontfix_issue_suppresses_the_filing(ai, tr):
    """AC-088.8: nothing is filed or commented; the result is suppressed and names the issue."""
    sig = mkdraft(ai).signature
    wf = tr.add(body=f"Signature: {sig}", state="closed", closed_at="2026-10-20T00:00:00Z", labels=["triage", "auto-filed", "bug", "wontfix"])
    out = ai.file(mkdraft(ai), record=False)
    assert out.result == "suppressed" and out.number == wf.number and out.url == wf.url
    assert not tr.created() and not tr.commented()
    assert out.lines == [f"issue: not filed again: suppressed by #{wf.number} (wontfix) {wf.url}"]


def test_wontfix_counts_only_on_the_most_recently_closed_issue(ai, tr):
    """AC-088.8: an older wontfix does not suppress when a later one was closed without it."""
    sig = mkdraft(ai).signature
    tr.add(body=f"Signature: {sig}", state="closed", closed_at="2026-10-10T00:00:00Z", labels=["wontfix"])
    tr.add(body=f"Signature: {sig}", state="closed", closed_at="2026-10-20T00:00:00Z", labels=["bug"])
    assert ai.file(mkdraft(ai), record=False).result == "new"


def test_an_open_issue_wins_over_closed_ones(ai, tr):
    """AC-088.8 AC-088.7: closed issues matter only when no open one carries the signature."""
    sig = mkdraft(ai).signature
    tr.add(body=f"Signature: {sig}", state="closed", closed_at="2026-10-20T00:00:00Z", labels=["wontfix"])
    op = tr.add(body=f"Signature: {sig}")
    out = ai.file(mkdraft(ai), record=False)
    assert out.result == "+1" and tr.commented()[0][2] == op.number


def test_the_run_record_notes_who_suppressed(ai, tr, store):
    """AC-088.8 AC-088.11: `filed` holds result suppressed and the note `suppressed by #<n>`."""
    d = mkdraft(ai)
    wf = tr.add(body=f"Signature: {d.signature}", state="closed", closed_at="2026-10-20T00:00:00Z", labels=["wontfix"])
    rid = runs.start("ship", repo="acme/shop-api")
    d.run_id = rid
    ai.file(d, run_id=rid)
    runs.finish(rid, "escalated", escalation={"reason": "r", "cause": "platform"})
    (r,) = stored(store)
    assert r["filed"] == [{"signature": d.signature, "url": wf.url, "result": "suppressed", "note": f"suppressed by #{wf.number}"}]


# ---------------- AC-088.9 redaction ----------------

PRIVATE = dict(repo="acme/shop-api", spec="007-price-alerts", branch="feature/007-price-alerts")


def test_private_names_maps_repo_spec_and_branch_to_placeholders(ai):
    """AC-088.9."""
    assert ai.private_names("acme/shop-api", "007-price-alerts", "feature/x") == {
        "acme/shop-api": "<repo>", "007-price-alerts": "<spec>", "feature/x": "<branch>"}
    assert ai.private_names(None, None, None) == {}
    assert ai.private_names("acme/shop-api", None, "main") == {"acme/shop-api": "<repo>"}      # a default branch is not private
    assert {"master", "trunk", "develop"} <= ai.DEFAULT_BRANCHES


def test_the_run_store_is_a_private_name_when_configured(ai, monkeypatch):
    """AC-088.9 AC-088.11: the run store's name becomes <run-store>."""
    monkeypatch.setenv("CPLAT_RUNS_REPO", "acme/runs-private")
    assert ai.private_names(None, None, None) == {"acme/runs-private": "<run-store>"}
    assert "runs-private" not in ai.scrub("see acme/runs-private for it", ai.private_names(None, None, None))


def test_scrub_removes_secrets_mail_and_home_paths(ai):
    """AC-088.9: the redaction of /issue:report applies."""
    out = ai.scrub(f"{TOKEN} password=hunter2hunter2 mail me@example.com in /Users/eike/dev/x and /home/anna/y")
    for leak in (TOKEN, "hunter2", "me@example.com", "/Users/eike", "/home/anna"):
        assert leak not in out


def test_scrub_replaces_names_longest_first_and_ignoring_case(ai):
    """AC-088.9."""
    names = {"acme/shop-api": "<repo>", "007-price-alerts": "<spec>", "feature/007-price-alerts": "<branch>"}
    out = ai.scrub("Feature/007-Price-Alerts of ACME/shop-api builds 007-price-alerts", names)
    assert out == "<branch> of <repo> builds <spec>"


def test_nothing_private_reaches_the_issue(ai, tr):
    """AC-088.9: token, password, e-mail, home path, repo, spec and branch are gone from title, reason, command, phase and evidence."""
    names = ai.private_names(PRIVATE["repo"], PRIVATE["spec"], PRIVATE["branch"])
    reason = f"clone of acme/shop-api failed on feature/007-price-alerts for {TOKEN}"
    d = mkdraft(ai, reason=reason, command="cplat ship land --spec 007-price-alerts", names=names,
                evidence=f"GH_TOKEN={TOKEN}\npassword = s3cr3tvalue\nowner anna@example.com\n/Users/anna/dev/shop-api/x.go\nbranch feature/007-price-alerts spec 007-price-alerts repo acme/shop-api")
    ai.file(d, record=False)
    ((_, _repo, title, body, _labels),) = tr.created()
    text = title + "\n" + body
    for leak in (TOKEN, "s3cr3tvalue", "anna@example.com", "/Users/anna", "acme/shop-api", "007-price-alerts", "feature/007"):
        assert leak not in text, leak
    assert "<repo>" in text and "<spec>" in text and "<branch>" in text


def test_nothing_private_reaches_the_occurrence_comment(ai, tr):
    """AC-088.9: the comment is redacted like the issue."""
    names = ai.private_names(PRIVATE["repo"], PRIVATE["spec"], PRIVATE["branch"])
    ai.file(mkdraft(ai, reason="x", names=names, signature="platform:" + "1" * 16), record=False)
    ai.file(mkdraft(ai, reason=f"x {TOKEN} acme/shop-api me@example.com", names=names, signature="platform:" + "1" * 16, run_id="r-2"), record=False)
    ((_, _r, _n, text),) = tr.commented()
    assert TOKEN not in text and "acme/shop-api" not in text and "me@example.com" not in text


# ---------------- AC-088.11 the run record ----------------

def test_the_record_holds_signature_url_and_result_and_the_issue_never_links_the_run_store(ai, tr, store, monkeypatch):
    """AC-088.11: `filed` has signature, url and new / +1; the issue and comment name the run id, not the private repo."""
    monkeypatch.setenv("CPLAT_RUNS_REPO", store.slug)
    d = mkdraft(ai)
    rid1, rid2 = runs.start("ship", repo="acme/shop-api"), runs.start("ship", repo="acme/shop-api")
    d1, d2 = mkdraft(ai, run_id=rid1), mkdraft(ai, run_id=rid2)
    ai.file(d1, run_id=rid1)
    ai.file(d2, run_id=rid2)
    runs.finish(rid1, "escalated", escalation={"reason": "r", "cause": "platform"})
    runs.finish(rid2, "escalated", escalation={"reason": "r", "cause": "platform"})
    r1, r2 = sorted(stored(store), key=lambda r: r["run_id"] != rid1)
    url = f"https://github.com/{PLATFORM_REPO}/issues/1"
    assert r1["filed"] == [{"signature": d.signature, "url": url, "result": "new"}]
    assert r2["filed"][0]["result"] == "+1" and r2["filed"][0]["url"].startswith(url) and r2["filed"][0]["signature"] == d.signature
    body, comment = tr.created()[0][3], tr.commented()[0][3]
    assert rid1 in body and rid2 in comment
    assert store.slug not in body + comment and "runs-private" not in body + comment


# ---------------- AC-088.12 filing fails ----------------

@pytest.mark.parametrize("reason", ["gh is missing", "gh is not logged in", "timed out", "GitHub refused: HTTP 403"])
def test_a_failing_tracker_keeps_the_filing_pending(ai, tr, reason):
    """AC-088.12: never raises; the line says `not filed: <reason>`; the record says pending."""
    tr.error = ai.TrackerError(reason)
    out = ai.file(mkdraft(ai), record=False)
    assert out.result == "pending" and out.url is None
    assert len(out.lines) == 1 and f"not filed: {reason}" in out.lines[0] and "report-issue" not in out.lines[0]


def test_any_other_exception_is_pending_too(ai, tr):
    """AC-088.12: file() never raises."""
    tr.error = RuntimeError("boom")
    out = ai.file(mkdraft(ai), record=False)
    assert out.result == "pending" and "RuntimeError: boom" in out.lines[0]


def test_a_tracker_that_eats_the_time_budget_is_a_timeout(ai, tr):
    """AC-088.12: less than a second left of the 20 s budget: pending, `timed out`."""
    tr.cost = 19.5
    out = ai.file(mkdraft(ai), record=False)
    assert out.result == "pending" and "not filed: timed out" in out.lines[0] and not tr.created()


def test_a_pending_filing_is_stored_with_its_draft_and_retried_at_the_flush(ai, tr, store, monkeypatch):
    """AC-088.12: kept in the run store's pending filings; the next flush files it and appends the follow-up."""
    monkeypatch.setenv("CPLAT_RUNS_REPO", store.slug)
    rid = runs.start("ship", repo="acme/shop-api")
    tr.error = ai.TrackerError("gh is missing")
    d = mkdraft(ai, run_id=rid)
    out = ai.file(d, run_id=rid)
    assert out.result == "pending" and runs.pending_count() == 1
    runs.finish(rid, "escalated", escalation={"reason": "r", "cause": "platform"})
    (r,) = stored(store)
    assert r["filed"] == [{"signature": d.signature, "url": None, "result": "pending"}]
    tr.error = None
    res = runs.flush()
    assert res.followups == 1 and runs.pending_count() == 0
    (f,) = followups(store)
    assert f["run_id"] == rid and f["signature"] == d.signature and f["result"] == "new" and f["url"].startswith(f"https://github.com/{PLATFORM_REPO}/issues/")
    assert len(tr.created()) == 1 and rid in tr.created()[0][3]


def test_a_retry_is_deduplicated_against_an_issue_filed_meanwhile(ai, tr, store, monkeypatch):
    """AC-088.12 AC-088.7: the retried filing becomes a +1 when an open issue of the signature exists by then."""
    monkeypatch.setenv("CPLAT_RUNS_REPO", store.slug)
    rid = runs.start("ship", repo="acme/shop-api")
    d = mkdraft(ai, run_id=rid)
    tr.error = ai.TrackerError("no network")
    ai.file(d, run_id=rid)
    runs.finish(rid, "escalated", escalation={"reason": "r", "cause": "platform"})
    tr.error = None
    other = tr.add(body=f"Signature: {d.signature}")
    runs.flush()
    assert not tr.created() and [c[2] for c in tr.commented()] == [other.number]
    assert followups(store)[0]["result"] == "+1"


def test_retry_filing_raises_while_it_is_still_pending(ai, tr):
    """AC-088.12: the 087 filer raises for pending (the entry stays), and returns (url, result) when it works."""
    d = mkdraft(ai)
    entry = {"run_id": d.run_id, "signature": d.signature, "payload": {"draft": d.to_payload(), "cap": ai.CAP, "window": ai.WINDOW_S}}
    tr.error = ai.TrackerError("gh is missing")
    with pytest.raises(RuntimeError, match="gh is missing"):
        ai.retry_filing(entry, 10.0)
    tr.error = None
    url, result = ai.retry_filing(entry, 10.0)
    assert result == "new" and url.endswith("/issues/1")


def test_a_draft_survives_the_json_payload_round_trip(ai):
    """AC-088.12: the pending filing is stored as JSON and rebuilt."""
    d = mkdraft(ai, evidence="e", shape="service-go", names={"acme/x": "<repo>"}, sections=[("Smoke", "text")])
    again = ai.Draft.from_payload(json.loads(json.dumps(d.to_payload())))
    assert ai.render(again) == ai.render(d) and again.signature == d.signature


# ---------------- AC-088.13 off switch and repo ----------------

@pytest.mark.parametrize("value", ["off", "OFF", "0", "false", "No"])
def test_auto_issues_off_sends_nothing_and_prints_the_draft(ai, tr, monkeypatch, value):
    """AC-088.13: the draft and the /issue:report hint; no tracker call; nothing recorded."""
    monkeypatch.setenv("CPLAT_AUTO_ISSUES", value)
    assert ai.enabled() is False
    out = ai.file(mkdraft(ai), record=False)
    assert out.result == "off" and tr.calls == [] and out.url is None
    text = "\n".join(out.lines)
    assert f"Draft issue for {PLATFORM_REPO}" in text and "[auto] merge conflict" in text and "triage" in text and "Signature: platform:" in text
    assert "/issue:report" in text


def test_auto_issues_are_on_unless_switched_off(ai, monkeypatch):
    """AC-088.13: unset or anything else means on; read at call time."""
    assert ai.enabled() is True
    for v in ("on", "1", "yes", "", "maybe"):
        monkeypatch.setenv("CPLAT_AUTO_ISSUES", v)
        assert ai.enabled() is True
    monkeypatch.setenv("CPLAT_AUTO_ISSUES", "off")
    assert ai.enabled() is False


def test_the_feedback_repo_moves_filing_and_dedupe(ai, tr, monkeypatch):
    """AC-088.13: issues are filed in and deduplicated against CPLAT_FEEDBACK_REPO."""
    assert ai.default_repo() == PLATFORM_REPO
    monkeypatch.setenv("CPLAT_FEEDBACK_REPO", "me/fork")
    assert ai.default_repo() == "me/fork"
    tr.add(PLATFORM_REPO, body=f"Signature: {mkdraft(ai).signature}")       # an issue in the default repo is not a duplicate
    out = ai.file(mkdraft(ai), record=False)
    assert out.result == "new" and tr.created()[0][1] == "me/fork" and out.url.startswith("https://github.com/me/fork/issues/")
    assert ai.file(mkdraft(ai, run_id="r-2"), record=False).result == "+1" and tr.commented()[0][1] == "me/fork"
    assert {c[1] for c in tr.calls} == {"me/fork"}


# ---------------- AC-088.14 cap ----------------

def distinct(ai, n, **kw):
    return mkdraft(ai, reason=f"failure kind {'x' * n}", **kw)


def test_the_11th_new_issue_within_24_hours_stays_pending_with_a_warning(ai, tr, clk):
    """AC-088.14: 10 new issues per 24 h; the next is pending and the output warns."""
    for n in range(10):
        assert ai.file(distinct(ai, n), record=False).result == "new"
        clk.tick(60)
    out = ai.file(distinct(ai, 10), record=False)
    assert out.result == "pending" and len(tr.created()) == 10
    assert any("cap of 10 new issues per 24 h reached" in ln for ln in out.lines) and all("report-issue" not in ln for ln in out.lines)


def test_plus_ones_are_not_capped(ai, tr, clk):
    """AC-088.14: comments on open issues go through at the cap."""
    for n in range(10):
        ai.file(distinct(ai, n), record=False)
    for n in range(3):
        assert ai.file(distinct(ai, 0, run_id=f"again-{n}"), record=False).result == "+1"
    assert len(tr.commented()) == 3 and len(tr.created()) == 10


def test_the_window_lets_a_pending_filing_through_later(ai, tr, clk):
    """AC-088.14: retried once 24 hours after the first of the ten."""
    for n in range(10):
        ai.file(distinct(ai, n), record=False)
        clk.tick(600)
    d = distinct(ai, 10)
    entry = {"run_id": d.run_id, "signature": d.signature, "payload": {"draft": d.to_payload(), "cap": ai.CAP, "window": ai.WINDOW_S}}
    with pytest.raises(RuntimeError, match="cap of 10"):
        ai.retry_filing(entry, 10.0)
    clk.tick(24 * 3600 - 10 * 600 + 1)
    url, result = ai.retry_filing(entry, 10.0)
    assert result == "new" and len(tr.created()) == 11


def test_cap_and_window_are_parameters(ai, tr, clk):
    """AC-088.14: callers (092) pass their own."""
    assert ai.CAP == 10 and ai.WINDOW_S == 24 * 3600
    assert ai.file(distinct(ai, 0), record=False, cap=1, window=100).result == "new"
    out = ai.file(distinct(ai, 1), record=False, cap=1, window=100)
    assert out.result == "pending" and "cap of 1 new issues per 100 s reached" in "\n".join(out.lines)
    clk.tick(101)
    assert ai.file(distinct(ai, 1), record=False, cap=1, window=100).result == "new"


def test_the_cap_counts_per_target_repo(ai, tr):
    """AC-088.14: another target repo has its own budget."""
    for n in range(10):
        ai.file(distinct(ai, n), record=False)
    assert ai.file(distinct(ai, 11, repo="acme/other"), record=False).result == "new"


def test_a_capped_filing_is_kept_pending_in_the_run_record(ai, tr, store):
    """AC-088.14 AC-088.11: the record says pending; nothing was sent."""
    for n in range(10):
        ai.file(distinct(ai, n), record=False)
    rid = runs.start("ship", repo="acme/shop-api")
    d = distinct(ai, 10, run_id=rid)
    ai.file(d, run_id=rid)
    assert runs.pending_count() == 1
    runs.finish(rid, "escalated", escalation={"reason": "r", "cause": "platform"})
    (r,) = stored(store)
    assert r["filed"][0]["result"] == "pending" and r["filed"][0]["signature"] == d.signature


def test_scrub_redacts_a_token_shaped_string_glued_to_a_long_run(ai):
    """AC-088.9: padding survives, but a run glued to other word characters is still redacted."""
    pad = "B" * 50
    assert ai.scrub(f"x\n{pad}\ny") == f"x\n{pad}\ny"
    assert "A" * 40 not in ai.scrub("token ghp_" + "A" * 40)
    assert "0" * 40 not in ai.scrub("abcDEF123" + "0" * 40 + "xyz")


def test_a_repo_name_is_not_replaced_inside_a_longer_name(ai):
    """AC-088.9: bare `todo` is replaced as a word only, not inside `todo-api` or `mytodo`."""
    out = ai.scrub("todo, todo-api and mytodo", {"todo": "<repo>"})
    assert out == "<repo>, todo-api and mytodo"
    assert ai.normalise("todo-api failed in todo", {"acme/todo": "<repo>"}) == "todo-api failed in <path>"


@pytest.mark.parametrize("code, err, message", [
    (127, "", "gh is missing"),
    (124, "timeout", "timed out"),
    (4, "", "gh is not logged in"),
    (1, "To get started with GitHub CLI, run: gh auth login", "gh is not logged in"),
    (1, "HTTP 403\n\nrate limit exceeded\n", "GitHub refused: rate limit exceeded"),
    (1, "", "GitHub refused: no details"),
])
def test_gh_errors_map_to_a_tracker_error_message(ai, code, err, message):
    """AC-088: every gh failure becomes a TrackerError with a short, specific message."""
    with pytest.raises(ai.TrackerError, match=message):
        ai._check(code, err)
