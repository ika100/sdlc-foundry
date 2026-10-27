"""spec (ADR-026): spec/plan validation, lifecycle, drift, test trace, backlog index, legacy migration."""
import json

import pytest

import core
import spec

SPEC = """---
spec_id: 007-price-alerts
title: Price alerts
status: {status}
priority: P1
shape: service-python
tracks: [42]
---

# 007 — Price alerts

## Problem

Traders miss moves.

## Acceptance criteria

- **AC-007.1** Given a rule, when the price crosses it, then an email is sent.
- **AC-007.2** Given a rule, when a webhook is set, then it is called.
- ~~**AC-007.3**~~ withdrawn: SMS is out of scope.

## Non-goals

- SMS

## Open questions

{questions}

## Changelog

- 2026-10-01 created
"""

PLAN = """---
spec_id: 007-price-alerts
shape: service-python
spec_hash: {hash}
tasks:
  - {{id: t1, title: model, files: [a.py], covers: [AC-007.1], parallel_safe: true, depends_on: []}}
  - {{id: t2, title: hook, files: [b.py], covers: [AC-007.2], parallel_safe: true, depends_on: []}}
  - {{id: t3, title: wire, files: [a.py, c.py], covers: [AC-007.1, AC-007.2], parallel_safe: false, depends_on: [t1, t2]}}
---

## t1 — model
"""


@pytest.fixture(autouse=True)
def no_shape(monkeypatch):
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)


def make(root, status="draft", questions="None.", plan=True, hash_=None):
    d = root / "docs" / "specs" / "007-price-alerts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(SPEC.format(status=status, questions=questions))
    if plan:
        (d / "plan.md").write_text(PLAN.format(hash=hash_ or spec.read(d).ac_hash()))
    return spec.read(d)


def edit_plan(root, old, new):
    p = root / "docs" / "specs" / "007-price-alerts" / "plan.md"
    p.write_text(p.read_text().replace(old, new))
    return spec.read(p.parent)


# ---------------- parsing ----------------

def test_criteria_open_questions_and_withdrawn(tmp_path):
    s = make(tmp_path, questions="- Which mail provider?\n- ~~Rate limit?~~ 10/min, see AC-007.1")
    assert [a.id for a in s.acs()] == ["AC-007.1", "AC-007.2", "AC-007.3"]
    assert s.active_acs() == ["AC-007.1", "AC-007.2"]
    assert s.open_questions() == ["Which mail provider?"]


def test_a_valid_spec_and_plan_pass(tmp_path):
    assert spec.check(make(tmp_path, status="approved")) == []


def test_find_by_number_slug_or_id(tmp_path):
    make(tmp_path)
    assert {spec.find(tmp_path, r).id for r in ("7", "007", "price-alerts", "007-price-alerts")} == {"007-price-alerts"}
    with pytest.raises(core.PlatformError):
        spec.find(tmp_path, "8")


# ---------------- spec checks ----------------

def test_approval_is_refused_with_open_questions(tmp_path):
    s = make(tmp_path, questions="- Which mail provider?")
    with pytest.raises(core.PlatformError, match="open question"):
        spec.approve(s, None)
    assert spec.read(s.dir).status == "draft"


def test_approve_sets_status_and_logs_it(tmp_path):
    s = make(tmp_path)
    spec.approve(s, None)
    s = spec.read(s.dir)
    assert s.status == "approved" and "approved" in s.body.split("## Changelog")[1]


def test_approve_needs_a_criterion(tmp_path):
    s = spec.new(tmp_path, "Empty thing", shape=None, priority="P1", tracks=[], parent=None)
    assert s.acs() == [] and s.open_questions() == []  # the skeleton's examples are HTML comments
    with pytest.raises(core.PlatformError, match="at least one acceptance criterion"):
        spec.approve(s, None)


def test_require_status(tmp_path):
    s = make(tmp_path)
    assert any("needs 'approved'" in e for e in spec.check(s, require="approved"))
    assert spec.check(make(tmp_path, status="building"), require="approved") == []
    assert any("needs 'approved'" in e for e in spec.check(make(tmp_path, status="superseded"), require="approved"))


def test_foreign_or_duplicate_criterion_ids(tmp_path):
    s = make(tmp_path, plan=False)
    (s.dir / "spec.md").write_text((s.dir / "spec.md").read_text().replace("AC-007.2", "AC-008.2").replace("AC-007.3", "AC-007.1"))
    errs = spec.check(spec.read(s.dir))
    assert any("AC-008.2 belongs to spec 008" in e for e in errs)
    assert any("duplicate acceptance criterion AC-007.1" in e for e in errs)


def test_shape_must_match_the_repo(tmp_path):
    assert any("this repo is 'web-nextjs'" in e for e in spec.check(make(tmp_path), shape="web-nextjs"))


def test_folder_and_spec_id_must_agree(tmp_path):
    s = make(tmp_path, plan=False)
    (s.dir / "spec.md").write_text((s.dir / "spec.md").read_text().replace("spec_id: 007-price-alerts", "spec_id: 007-other"))
    assert any("must equal the folder name" in e for e in spec.check(spec.read(s.dir)))


# ---------------- plan checks ----------------

def test_plan_drift_is_detected(tmp_path):
    s = make(tmp_path, status="approved")
    (s.dir / "spec.md").write_text((s.dir / "spec.md").read_text().replace("an email is sent", "an email is sent within 1 min"))
    assert any("changed after this plan was written" in e for e in spec.check(spec.read(s.dir)))


def test_every_active_criterion_needs_a_task(tmp_path):
    make(tmp_path)
    s = edit_plan(tmp_path, "covers: [AC-007.1, AC-007.2]", "covers: [AC-007.1]")
    s = edit_plan(tmp_path, "covers: [AC-007.2]", "covers: []")
    assert "plan.md: AC-007.2 is not covered by any task" in spec.check(s)


def test_tasks_cannot_cover_withdrawn_or_unknown_criteria(tmp_path):
    make(tmp_path)
    s = edit_plan(tmp_path, "covers: [AC-007.2]", "covers: [AC-007.2, AC-007.3, AC-007.9]")
    errs = spec.check(s)
    assert "plan.md: task t2: covers withdrawn criterion 'AC-007.3'" in errs
    assert "plan.md: task t2: covers unknown criterion 'AC-007.9'" in errs


def test_parallel_tasks_must_not_share_files(tmp_path):
    make(tmp_path)
    s = edit_plan(tmp_path, "files: [b.py]", "files: [a.py]")
    assert any("t1 and t2 are parallel_safe at the same level but share a.py" in e for e in spec.check(s))


def test_dependency_cycle(tmp_path):
    make(tmp_path)
    s = edit_plan(tmp_path, "covers: [AC-007.1], parallel_safe: true, depends_on: []", "covers: [AC-007.1], parallel_safe: true, depends_on: [t3]")
    assert any("dependency cycle" in e for e in spec.check(s))


def test_task_done_marks_progress(tmp_path):
    s = make(tmp_path, status="building")
    spec.task_done(s, "t2")
    s = spec.read(s.dir)
    assert [t.get("done", False) for t in s.plan[0]["tasks"]] == [False, True, False]
    assert spec.check(s) == []  # the rewritten plan is still valid
    with pytest.raises(core.PlatformError):
        spec.task_done(s, "t9")


# ---------------- lifecycle ----------------

def test_transitions(tmp_path):
    s = make(tmp_path)
    with pytest.raises(core.PlatformError, match="not allowed"):
        spec.set_status(s, "approved", None)  # only through approve
    spec.approve(s, None)
    (s.dir / "verification.md").write_text(PASSING)
    for st in ("building", "done", "draft"):  # done -> draft is an amendment
        spec.set_status(spec.read(s.dir), st, "amend" if st == "draft" else None)
    assert spec.read(s.dir).status == "draft"


PASSING = "# Verification — 007 Price alerts\n\n**Result:** pass\n"


# ---------------- spec 068: done means verified ----------------

def test_done_needs_a_passing_verification(tmp_path):
    """AC-068.1: a build spec cannot become done without verification.md saying pass."""
    s = make(tmp_path, status="building")
    with pytest.raises(core.PlatformError, match="has no verification.md") as e:
        spec.set_status(s, "done", None)
    assert "/component:verify 007" in e.value.hint
    (s.dir / "verification.md").write_text(PASSING.replace("pass", "fail"))
    with pytest.raises(core.PlatformError, match="does not say"):
        spec.set_status(spec.read(s.dir), "done", None)
    (s.dir / "verification.md").write_text(PASSING)
    spec.set_status(spec.read(s.dir), "done", None)
    assert spec.read(s.dir).status == "done"


def test_an_unverified_done_is_an_explicit_recorded_exception(tmp_path):
    """AC-068.2: --unverified needs a reason, and the reason lands in the changelog."""
    s = make(tmp_path, status="building")
    with pytest.raises(core.PlatformError, match="needs --reason"):
        spec.set_status(s, "done", None, unverified=True)
    spec.set_status(spec.read(s.dir), "done", "infra-only change, checked on lan", unverified=True)
    body = spec.read(s.dir).body
    assert "done: unverified: infra-only change, checked on lan" in body


def test_product_specs_need_no_verification(tmp_path):
    """AC-068.1: product specs (gitops-app) are verified in their component repos."""
    s = make(tmp_path, status="building")
    s.meta["shape"] = "gitops-app"
    spec.set_status(s, "done", None)
    assert spec.read(s.dir).status == "done"


def test_done_without_verification_points_to_verify(tmp_path):
    """AC-068.3: specs that were closed without evidence show `/component:verify` as their next step; verified ones show none."""
    s = make(tmp_path, status="done")
    assert spec.next_step(s) == "/component:verify 007"
    (s.dir / "verification.md").write_text(PASSING)
    assert spec.next_step(spec.read(s.dir)) == "—"


@pytest.mark.parametrize("kw, step", [
    ({"questions": "- ?"}, "/component:spec --amend 007"),
    ({}, "/component:spec approve 007"),
    ({"status": "approved", "plan": False}, "/component:plan 007"),
    ({"status": "building"}, "/component:build 007"),
    ({"status": "done"}, "/component:verify 007"),
])
def test_next_step(tmp_path, kw, step):
    assert spec.next_step(make(tmp_path, **kw)) == step


# ---------------- new ----------------

def test_new_continues_after_legacy_story_ids(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "backlog.md").write_text("#### STORY-012 — old\n")
    s = spec.new(tmp_path, "Price Alerts!", shape="service-python", priority="P0", tracks=[3], parent=None)
    assert s.id == "013-price-alerts"
    assert s.meta == {"spec_id": "013-price-alerts", "title": "Price Alerts!", "status": "draft", "priority": "P0",
                      "shape": "service-python", "tracks": [3]}
    assert spec.check(s) == []
    assert (s.dir / "spec.md").read_text().startswith("---\nspec_id: 013-price-alerts\ntitle: Price Alerts!\n")
    assert "tracks: [3]" in (s.dir / "spec.md").read_text()


def test_slugs_are_cut_at_a_word_boundary():
    assert spec.slugify("Create a repo of any shape with one command") == "create-a-repo-of-any-shape-with-one"
    assert len(spec.slugify("x" * 60)) == 40


# ---------------- trace ----------------

def test_trace_finds_ids_in_names_and_comments_but_not_prefixes(tmp_path):
    s = make(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_alerts.py").write_text("def test_email():  # AC-007.1\n    ...\ndef test_x():  # AC-007.20\n    ...\n")
    nm = tmp_path / "tests" / "node_modules"
    nm.mkdir()
    (nm / "x.py").write_text("AC-007.2")
    assert spec.trace(tmp_path, s, ["tests/**/*.py"]) == {"AC-007.1": ["tests/test_alerts.py"], "AC-007.2": []}


def test_trace_cli_fails_on_a_missing_criterion(tmp_path, capsys):
    make(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("# AC-007.1\n")
    assert spec.main(["--repo", str(tmp_path), "trace", "7", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["missing"] == ["AC-007.2"]


def test_every_shape_declares_test_globs():
    assert all(s.get("test_globs") for s in core.registry.load() if s["status"] != "planned")


# ---------------- index / list ----------------

def test_index_keeps_text_outside_the_markers(tmp_path):
    make(tmp_path)
    (tmp_path / "docs" / "backlog.md").write_text(f"# Backlog\n\nintro\n\n{spec.START}\nold\n{spec.END}\n\n## Decisions\n\nkeep\n")
    text = spec.write_index(tmp_path).read_text()
    assert "intro" in text and "keep" in text and "old" not in text
    assert "| [007-price-alerts](specs/007-price-alerts/spec.md) — Price alerts | P1 | draft | 2 | #42 |" in text


def test_index_refuses_legacy_stories(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "backlog.md").write_text("#### STORY-001 — x\n")
    with pytest.raises(core.PlatformError, match="still holds STORY-NNN") as e:
        spec.write_index(tmp_path)
    assert "migrate" in e.value.hint


def test_list_hides_done_unless_all(tmp_path, capsys):
    make(tmp_path, status="done")
    spec.main(["--repo", str(tmp_path), "list", "--json"])
    assert json.loads(capsys.readouterr().out) == []
    spec.main(["--repo", str(tmp_path), "list", "--all", "--json"])
    assert json.loads(capsys.readouterr().out)[0]["tasks"] == 3


# ---------------- migrate ----------------

LEGACY = """# Product backlog

Intro text.

---

## Epic A. Alerts

#### STORY-004: Price alerts
**Status:** done · **Priority:** P0 · **Tracks:** #42, #43 · **Source:** PRD

As a trader, I want alerts, so that I react in time.

**Acceptance criteria:**
- [x] An email is sent.
- [ ] A webhook is called.

## Epic B. Reports

### Notes on reports

Keep me.

#### STORY-005 — Reports
**Status:** open · **Priority:** P2

As a user, I want reports.

## Decisions

1. keep this
"""


def test_migrate_dry_run_writes_nothing(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "backlog.md").write_text(LEGACY)
    out = spec.migrate(tmp_path, None, write=False)
    assert out[0] == "would create docs/specs/004-price-alerts/spec.md  [done, 2 criteria]"
    assert not (tmp_path / "docs" / "specs").exists()


def test_migrate_converts_stories_and_keeps_other_sections(tmp_path):
    (tmp_path / "docs" / "plan").mkdir(parents=True)
    (tmp_path / "docs" / "backlog.md").write_text(LEGACY)
    (tmp_path / "docs" / "plan" / "alerts.md").write_text("---\nplan_id: alerts\nstories: [STORY-004]\n---\n")
    spec.migrate(tmp_path, "service-python", write=True)
    a = spec.find(tmp_path, "4")
    assert a.meta == {"spec_id": "004-price-alerts", "title": "Price alerts", "status": "done", "priority": "P0",
                      "shape": "service-python", "tracks": [42, 43]}
    assert a.active_acs() == ["AC-004.1", "AC-004.2"]
    assert "Legacy plan: `docs/plan/alerts.md`" in a.body and "**Source:** PRD" in a.body
    b = spec.find(tmp_path, "5")
    assert b.status == "draft" and b.acs() == [] and "As a user" in b.body
    assert spec.check(a) == [] and spec.check(b) == []
    backlog = (tmp_path / "docs" / "backlog.md").read_text()
    assert "STORY-00" not in backlog and "Intro text." in backlog and "1. keep this" in backlog
    assert "## Epic A" not in backlog                       # emptied by the move
    assert "## Epic B" in backlog and "Keep me." in backlog  # still has content
    assert backlog.index(spec.START) < backlog.index("## Epic B") and "004-price-alerts" in backlog
    with pytest.raises(core.PlatformError, match="no STORY-NNN"):
        spec.migrate(tmp_path, None, write=True)


# ---------------- product specs and per-repo slices (STORY-040) ----------------

PRODUCT = """---
spec_id: 012-billing
title: Billing
status: approved
priority: P0
shape: gitops-app
---

# 012 — Billing

## Problem

Customers cannot pay.

## Acceptance criteria

- **AC-012.1** Given a cart, when the customer checks out, then a Stripe session URL is returned.
- **AC-012.2** Given a paid session, when the webhook arrives, then the order is marked paid.
- **AC-012.3** Given the checkout page, when the customer clicks Pay, then they are redirected to Stripe.
- ~~**AC-012.4**~~ withdrawn: invoices later.

## Open questions

## Changelog

- 2026-10-08 created
"""

PRODUCT_PLAN = """---
plan_id: 012-billing
spec: 012-billing
feature: billing
gitops_app: acme/shop-gitops
status: draft
repos:
  - {id: shop-api, shape: service-python, summary: Checkout and webhook API, acs: [AC-012.1, AC-012.2], arguments: "Use the existing orders table.", depends_on: [], done: false}
  - {id: shop-web, shape: web-nextjs, summary: Pay button, acs: [AC-012.3], depends_on: [], done: false}
gitops_pin: []
---

## Contract

POST /billing/checkout -> 201 {"url": str}
"""


@pytest.fixture()
def product(tmp_path):
    app = tmp_path / "shop-gitops"
    (app / "docs" / "specs" / "012-billing").mkdir(parents=True)
    (app / "docs" / "specs" / "012-billing" / "spec.md").write_text(PRODUCT)
    (app / "docs" / "plan").mkdir()
    (app / "docs" / "plan" / "012-billing.md").write_text(PRODUCT_PLAN)
    return app


def test_a_repo_spec_is_sliced_from_the_product_plan(tmp_path, product):
    repo = tmp_path / "shop-api"
    repo.mkdir()
    s = spec.new_from_plan(repo, product / "docs" / "plan" / "012-billing.md", "shop-api", shape="service-python")
    assert s.meta == {"spec_id": "001-checkout-and-webhook-api", "title": "Checkout and webhook API", "status": "draft",
                      "priority": "P0", "shape": "service-python", "parent": "acme/shop-gitops:012-billing"}
    ctx = spec.sections(s.body)["system context"]
    assert "**AC-012.1**" in ctx and "**AC-012.2**" in ctx and "AC-012.3" not in ctx
    assert "POST /billing/checkout" in ctx and "existing orders table" in ctx
    assert spec.sections(s.body)["problem"].strip() == "Customers cannot pay."
    assert s.acs() == []  # product criteria are context; the product-manager writes this repo's own
    assert spec.check(s) == []


def test_slice_of_an_unknown_repo(tmp_path, product):
    with pytest.raises(core.PlatformError, match="no repo 'shop-x'"):
        spec.slice_from_plan(product / "docs" / "plan" / "012-billing.md", "shop-x")


def test_slice_of_a_legacy_plan_uses_its_prompt(tmp_path, product):
    legacy = product / "docs" / "plan" / "old.md"
    legacy.write_text(PRODUCT_PLAN.replace("spec: 012-billing\n", "").replace("plan_id: 012-billing", "plan_id: old"))
    sl = spec.slice_from_plan(legacy, "shop-api")
    assert sl["parent"] == "acme/shop-gitops:old" and "existing orders table" in sl["context"]
    assert "System criteria" not in sl["context"]


def test_product_specs_point_to_the_app_commands(product):
    s = spec.read(product / "docs" / "specs" / "012-billing")
    assert spec.next_step(s) == "/system:ship 012"
    (product / "docs" / "plan" / "012-billing.md").unlink()
    assert spec.next_step(s) == "/system:plan 012"


# ---------------- ci (STORY-041) ----------------

def test_ci_without_specs_is_quiet(tmp_path, capsys):
    assert spec.main(["--repo", str(tmp_path), "ci", "--strict"]) == 0
    assert "nothing to check" in capsys.readouterr().out


def test_ci_warns_by_default_and_fails_when_strict(tmp_path, capsys):
    make(tmp_path, status="building")  # nothing traces its criteria yet
    assert spec.main(["--repo", str(tmp_path), "ci"]) == 0
    out = capsys.readouterr().out
    assert "::warning file=docs/specs/007-price-alerts/spec.md,title=spec 007-price-alerts::AC-007.1 is not named by any test" in out
    assert spec.main(["--repo", str(tmp_path), "ci", "--strict"]) == 1
    assert "::error file=" in capsys.readouterr().out


def test_ci_traces_only_specs_that_are_built(tmp_path):
    make(tmp_path, status="approved")
    assert spec.ci_problems(tmp_path) == []


def test_ci_does_not_trace_product_specs(tmp_path, product):
    s = spec.read(product / "docs" / "specs" / "012-billing")
    spec.set_status(s, "building", None)
    assert spec.ci_problems(product) == []


@pytest.mark.parametrize("text, status", [("done", "done"), ("Done", "done"), ("done (superseded by STORY-037)", "superseded"),
                                          ("in progress", "building"), ("partial", "building"), ("planned", "draft"),
                                          ("open", "draft"), ("not built", "draft")])
def test_legacy_status_words(text, status):
    assert spec.legacy_status(text) == status


def test_migrated_links_still_resolve():
    text = "[ADR](adr/024-x.md) [web](https://x.io/a) [here](#top) [abs](/docs/a.md) [up](../README.md) [mail](mailto:a@b.c)"
    assert spec.relink(text) == ("[ADR](../../adr/024-x.md) [web](https://x.io/a) [here](#top) [abs](/docs/a.md) "
                                 "[up](../../../README.md) [mail](mailto:a@b.c)")


def test_trace_ignores_bytecode_caches(tmp_path):
    """Found while verifying specs 043-059: the default glob tests/**/* also matched __pycache__/*.pyc."""
    s = make(tmp_path)
    (tmp_path / "tests" / "__pycache__").mkdir(parents=True)
    (tmp_path / "tests" / "__pycache__" / "test_a.cpython-313.pyc").write_bytes(b"\x00AC-007.1\x00")
    (tmp_path / "tests" / "test_a.py").write_text("# AC-007.1\n")
    assert spec.trace(tmp_path, s, ["tests/**/*"])["AC-007.1"] == ["tests/test_a.py"]


# ---------------- spec 048: acceptance tests may be reformatted, never weakened ----------------

PY_BEFORE = '''import os
import json


def test_alert():  # AC-007.1
    assert send(rule("AAPL", 200), price=200.01, timeout=60) == {"sent": 1, "to": "owner"}
'''


@pytest.mark.parametrize("after, same", [
    # reflowed call and wrapped assert: formatting only
    ('''import os
import json


def test_alert():  # AC-007.1
    assert send(
        rule("AAPL", 200),
        price=200.01,
        timeout=60,
    ) == {"sent": 1, "to": "owner"}
''', True),
    # imports sorted by the formatter: formatting only
    (PY_BEFORE.replace("import os\nimport json", "import json\nimport os"), True),
    # a changed literal weakens the test
    (PY_BEFORE.replace("200.01", "199.0"), False),
    # a removed assertion
    (PY_BEFORE.replace('    assert send(rule("AAPL", 200), price=200.01, timeout=60) == {"sent": 1, "to": "owner"}\n', "    pass\n"), False),
    # the criterion id changed (only in a comment)
    (PY_BEFORE.replace("AC-007.1", "AC-007.2"), False),
])
def test_python_test_diff(after, same):
    """AC-048.2 AC-048.3"""
    ok, _ = spec.formatting_only(PY_BEFORE, after, "test_x.py")
    assert ok is same


@pytest.mark.parametrize("after, same", [
    ('it("AC-007.1 sends",()=>{\n  expect(send(200.01)).toBe(1)\n})\n', True),
    ('it("AC-007.1 sends", () => { expect(send(199)).toBe(1) })\n', False),
])
def test_other_languages_ignore_only_whitespace(after, same):
    """AC-048.3"""
    ok, _ = spec.formatting_only('it("AC-007.1 sends", () => {\n  expect(send(200.01)).toBe(1)\n})\n', after, "x.test.ts")
    assert ok is same


def test_test_diff_cli_compares_against_a_commit(tmp_path, capsys):
    """AC-048.2 AC-048.3: exit 0 for formatting, 1 with the reason otherwise."""
    import subprocess
    make(tmp_path, status="building")
    (tmp_path / "tests").mkdir()
    f = tmp_path / "tests" / "test_x.py"
    f.write_text(PY_BEFORE)
    g = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q"); g("add", "."); g("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "red")
    f.write_text(PY_BEFORE.replace("import os\nimport json", "import json\nimport os"))
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD"]) == 0
    assert "tests/test_x.py: formatting only" in capsys.readouterr().out
    f.write_text(PY_BEFORE.replace("200.01", "1"))
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD"]) == 1
    assert "tests/test_x.py: changed" in capsys.readouterr().out



# ---------------- spec 063: test-diff looks only at test files ----------------

def _committed_repo(tmp_path):
    import subprocess
    make(tmp_path, status="building")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(PY_BEFORE)
    g = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q"); g("add", "."); g("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "red")
    return tmp_path / "docs" / "specs" / "007-price-alerts"


def test_test_diff_ignores_plan_and_spec_documents(tmp_path, capsys):
    """AC-063.1: `done: true` in plan.md (which names criteria) is not an acceptance-test change."""
    d = _committed_repo(tmp_path)
    assert spec.main(["--repo", str(tmp_path), "task-done", "007", "t1"]) == 0   # what the build does after each task
    (d / "verification.md").write_text("AC-007.1 passes\n")
    (d / "spec.md").write_text((d / "spec.md").read_text() + "\n- AC-007.1 noted\n")
    capsys.readouterr()
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD"]) == 0
    assert "no acceptance test changed" in capsys.readouterr().out


def test_test_diff_still_fails_on_a_changed_test(tmp_path, capsys):
    """AC-063.2: a test under the shape's test_globs that changed beyond formatting fails."""
    d = _committed_repo(tmp_path)
    assert spec.main(["--repo", str(tmp_path), "task-done", "007", "t1"]) == 0   # what the build does after each task
    f = tmp_path / "tests" / "test_x.py"
    f.write_text(PY_BEFORE.replace("200.01", "1"))
    capsys.readouterr()
    assert spec.main(["--repo", str(tmp_path), "test-diff", "HEAD"]) == 1
    out = capsys.readouterr().out
    assert "tests/test_x.py: changed" in out and "plan.md" not in out


def _add(root, rel, text):
    import subprocess
    (root / rel).write_text(text)
    subprocess.run(["git", "-C", str(root), "add", rel], check=True, capture_output=True)


def test_test_diff_leaves_out_a_new_test_file_the_plan_creates(tmp_path, monkeypatch):
    """A file the plan's tasks create after the red commit is the build's own, not a changed acceptance test."""
    d = _committed_repo(tmp_path)
    monkeypatch.setattr(spec, "test_globs", lambda shape: ["tests/**"])
    plan = d / "plan.md"
    plan.write_text(plan.read_text().replace("files: [b.py]", "files: [b.py, tests/e2e.sh]"))
    _add(tmp_path, "tests/e2e.sh", "# AC-007.2: the alert fires end to end\n")
    assert spec.test_diff(tmp_path, "HEAD", []) == {}


def test_test_diff_still_flags_a_new_test_file_no_task_lists(tmp_path, monkeypatch):
    """A new file naming a criterion that no task of the plan lists is still reported."""
    _committed_repo(tmp_path)
    monkeypatch.setattr(spec, "test_globs", lambda shape: ["tests/**"])
    _add(tmp_path, "tests/test_y.py", "def test_y():  # AC-007.1\n    pass\n")
    assert spec.test_diff(tmp_path, "HEAD", []) == {"tests/test_y.py": (False, "new or deleted file")}


def test_test_diff_never_selects_docs_even_under_broad_globs(tmp_path, monkeypatch):
    """AC-063.3: without a recorded shape (default globs) nothing under docs/ or *.md is selected."""
    d = _committed_repo(tmp_path)
    monkeypatch.setattr(spec, "test_globs", lambda shape: ["**/*"])
    assert spec.main(["--repo", str(tmp_path), "task-done", "007", "t1"]) == 0   # what the build does after each task
    (tmp_path / "tests" / "NOTES.md").write_text("AC-007.1\n")
    assert spec.test_diff(tmp_path, "HEAD", []) == {}


# ---------------- spec 052: repo specs know the gitops wiring ----------------

def _with_gitops_entry(product):
    plan = product / "docs" / "plan" / "012-billing.md"
    plan.write_text(plan.read_text().replace("gitops_pin: []", """  - id: shop-gitops
    shape: gitops-app
    summary: wiring
    acs: [AC-012.1]
    gitops:
      - {resource: postgres}
      - {uses: postgres, component: shop-api}
      - {expose: shop-web, host: shop}
      - {env: {API_URL: 'http://shop-api'}, component: shop-web}
    depends_on: []
    done: false
gitops_pin: []""", 1).replace("repos:\n", "repos:\n", 1))
    return plan


def test_the_slice_lists_what_the_product_provides(tmp_path, product):
    """AC-052.1: env and addon env from the gitops operations, per repo."""
    plan = _with_gitops_entry(product)
    api = spec.slice_from_plan(plan, "shop-api")["context"]
    web = spec.slice_from_plan(plan, "shop-web")["context"]
    provided_api = api.split("### Provided by the system", 1)[1]
    assert "postgres" in provided_api and "DATABASE_URL" in provided_api and "PGPASSWORD" in provided_api
    assert "API_URL" not in provided_api
    provided_web = web.split("### Provided by the system", 1)[1]
    assert "API_URL=http://shop-api" in provided_web and "shop" in provided_web and "DATABASE_URL" not in provided_web


def test_no_gitops_operations_means_no_provided_section(tmp_path, product):
    """AC-052.1"""
    assert "Provided by the system" not in spec.slice_from_plan(product / "docs" / "plan" / "012-billing.md", "shop-api")["context"]


@pytest.mark.parametrize("front, expect", [
    ("tasks:\n  - {id: t1, title: a, files: [x.py], done: false}\n  - {id: t2, title: b, files: [y.py]}\n",
     "tasks:\n  - {id: t1, title: a, files: [x.py], done: true}\n  - {id: t2, title: b, files: [y.py]}\n"),
    ("tasks:\n  - {id: t1, title: a, files: [x.py]}\n  - {id: t2, title: b}\n",
     "tasks:\n  - {id: t1, title: a, files: [x.py], done: true}\n  - {id: t2, title: b}\n"),
    ("summary: a long summary that stays on one line and is never rewrapped by the tool because nobody asked it to do so at all\n"
     "tasks:\n- id: t1\n  title: a\n  done: false\n- id: t2\n  title: b\n",
     "summary: a long summary that stays on one line and is never rewrapped by the tool because nobody asked it to do so at all\n"
     "tasks:\n- id: t1\n  title: a\n  done: true\n- id: t2\n  title: b\n"),
    ("tasks:\n- id: t1\n  title: a\n- id: t2\n  title: b\n", "tasks:\n- id: t1\n  title: a\n  done: true\n- id: t2\n  title: b\n"),
])
def test_task_done_changes_only_the_done_flag_of_that_task(tmp_path, front, expect):
    """AC-094: `spec task-done` leaves plan.md byte for byte as it was, except the task's done flag."""
    s = make(tmp_path, status="approved")
    p = s.dir / "plan.md"
    head, rest = p.read_text().split("tasks:", 1)
    body = rest.split("---\n", 2)[-1] if rest.count("---\n") else ""
    p.write_text(f"{head.rstrip()}\n{front}---\n{body}")
    before = p.read_text()
    spec.task_done(spec.read(s.dir), "t1")
    assert p.read_text() == before.replace(front, expect)
