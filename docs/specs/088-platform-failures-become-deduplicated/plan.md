---
spec_id: 088-platform-failures-become-deduplicated
spec_hash: bb480ba7ec39
summary: autoissue.py files platform failures as deduplicated issues (Signature line, oldest-open +1, closed → linked new unless wontfix, 10 per 24 h cap, pending retry through the run store); ship escalate files cause platform, cplat crashes inside a recorded run file at once
tasks:
- id: t1
  title: autoissue module (signature, redaction, dedupe, cap, pending retry, GitHub seam)
  files: [scripts/cplat/autoissue.py, tests/cplat/conftest.py]
  covers: [AC-088.4, AC-088.5, AC-088.6, AC-088.7, AC-088.8, AC-088.9, AC-088.10, AC-088.11, AC-088.12, AC-088.13, AC-088.14]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: runs.current and the suppressed note in filed
  files: [scripts/cplat/runs.py]
  covers: [AC-088.4, AC-088.8, AC-088.11, AC-088.12]
  parallel_safe: true
  depends_on: []
  done: true
- id: t3
  title: auto-filed triage label
  files: [scripts/cplat/triage.py]
  covers: [AC-088.10]
  parallel_safe: true
  depends_on: []
  done: true
- id: t4
  title: ship escalate files cause platform and coerces unknown causes
  files: [scripts/cplat/ship.py]
  covers: [AC-088.1, AC-088.2, AC-088.3, AC-088.9, AC-088.11, AC-088.12, AC-088.13, AC-088.14]
  parallel_safe: true
  depends_on: [t1]
  done: true
- id: t5
  title: cplat crash hook files inside a recorded run
  files: [scripts/cplat/cplat.py]
  covers: [AC-088.4]
  parallel_safe: true
  depends_on: [t1, t2]
  done: true
- id: t6
  title: ship command text and docs for auto-filed issues
  files: [plugins/svc/commands/ship.md, docs/CHANGELOG.md, docs/unattended-delivery.md]
  covers: [AC-088.1]
  parallel_safe: true
  depends_on: []
  done: true
---

The contract for every task is [design.md](design.md). ADR: [033](../../adr/033-auto-filed-issues-with-signatures.md).
Filing must never change an escalation's or a crash's exit code. `autoissue.file()` never raises and never prints:
callers print `Outcome.lines`. No test may reach GitHub. Every GitHub call goes through `autoissue.tracker()` /
`autoissue.gh()`, and the clock goes through `autoissue.now()` / `autoissue.monotonic()`.

Note for the test phase: AC-088.3 replaces the argparse rejection of an unknown `--cause`. 087's
`tests/cplat/test_runs.py::test_the_cause_must_be_one_of_the_known_ones` must be rewritten by the tester to the
088 behaviour (`unknown` plus the message). Coders do not edit it.

## t1 — autoissue module (signature, redaction, dedupe, cap, pending retry, GitHub seam)

**Files:** scripts/cplat/autoissue.py, tests/cplat/conftest.py
**Covers:** AC-088.4, AC-088.5, AC-088.6, AC-088.7, AC-088.8, AC-088.9, AC-088.10, AC-088.11, AC-088.12, AC-088.13, AC-088.14
**Goal:** the public API of design.md "Python API". Specs 091 and 092 import this module, so keep the names exactly.

**Implementation notes:**
- `normalise` uses the 13 ordered steps of the Signature table. `raw_signature` is sha256 of the `\n`-joined parts,
  first 16 hex. `signature` normalises each part first. An unknown kind → `ValueError`.
- `private_names` and `scrub`, as in Redaction. Names are replaced longest first, literal and case-insensitive. A
  default branch is skipped, and `runs.configured_repo()` becomes `<run-store>`. Lines starting with `Signature:` in
  any piece are quoted.
- `Draft` with `to_payload` / `from_payload` (JSON-safe, environment rendered). `render`, `render_comment` and the
  title rule (`[auto] `, at most 100 characters with `…`) give the exact body sections, the fence, the "Seen again"
  first line, and the single `Signature:` line last.
- `file()` follows steps 1–7. It checks the run id idempotency for both new and +1. The oldest open issue is chosen by
  `(created_at, number)`, and the latest closed one by `closed_at`. `wontfix` → `suppressed`. The cap ledger is
  per target repo, under an `fcntl` lock in `runs.state_dir()`. It records through
  `runs.filed(..., filer="autoissue", payload=...)`, and the output lines are those of the contract table.
- `retry_filing(entry, timeout)` rebuilds the draft and calls `file(record=False)`. It raises for `pending` / `off`.
- `default_repo()` and `enabled()` read the environment at call time.
- `GhTracker` over `gh()`: the issue list with the `auto-filed` label, search for closed issues, comments, create
  (body on stdin), and comment. Missing labels are created once from `triage.LABELS` + `EXTRA_LABELS`, then it
  retries. Errors map to `TrackerError` as in the contract. `gh()` never raises.
- `crash_draft` / `file_crash`:
  - command with `SUBCOMMAND_GROUPS`
  - innermost `scripts/cplat` frame as `file.py:function`
  - `raw_signature("platform", command, type name, frame)`
  - the last 20 traceback lines as evidence
  - phase from `runs.active(rid)`, names from the record and the git branch
- `conftest.py`, an autouse fixture:
  - `monkeypatch.setattr(autoissue, "tracker", ...)` with a tracker whose every method raises
    `TrackerError("tests never call GitHub")`
  - `delenv` for `CPLAT_AUTO_ISSUES` and `CPLAT_FEEDBACK_REPO`
  - import `autoissue` inside the fixture

  Tests that need GitHub behaviour install their own fake.

**Done when:** with a fake tracker and clock, the acceptance tests for AC-088.5–.9, .13 and .14 pass at module level:
- signatures equal and different
- the title, body and labels
- oldest-open +1 with the occurrence count
- closed → linked, and `wontfix` → suppressed
- redaction
- off and the repo override
- the cap with pending

`retry_filing` also turns a pending filing into `new` / `+1` once the fake recovers (AC-088.12 module part).

## t2 — runs.current and the suppressed note in filed

**Files:** scripts/cplat/runs.py
**Covers:** AC-088.4, AC-088.8, AC-088.11, AC-088.12
**Goal:** a command can tell whether it runs inside a recorded run. A `suppressed` filing notes which issue suppressed it.

**Implementation notes:**
- `current(repo_dir)`: the candidates, in order, are `attach_point(repo_dir)`, the `cplat runs begin` pointer's
  `run_id` (`_read_pointer(_pointer(repo_dir))`), and `$CPLAT_RUN_PARENT`. Return the first with
  `active(rid) is not None`. Never raises. Add it to the module docstring's API list.
- `filed(...)` with result `suppressed` adds `"note": "suppressed by #<n>"` (`n` = the trailing digits of `url`; no
  note when there are none).
- `_retry_filings`: when a retry returns `suppressed`, set the same `note` in the active record's entry and in the
  follow-up line.
- Nothing else in 087's behaviour changes (`test_runs.py` stays green, except the one cause test noted above).

**Done when:** the AC-088.8 "run record notes `suppressed by #<n>`" assertion and the `runs.current` parts of the
AC-088.4 tests pass. Inside a ship run, a pointer run or `CPLAT_RUN_PARENT` gives a run id. A ship state without an
active record gives `None`.

## t3 — auto-filed triage label

**Files:** scripts/cplat/triage.py
**Covers:** AC-088.10
**Goal:** `cplat triage setup-labels` creates `auto-filed`, and auto-filed issues sit in the intake queue.

**Implementation notes:**
- `LABELS["auto-filed"] = ("c5def5", "Filed automatically by the platform (spec 088)")`. It is not a decision label,
  so `queue()` keeps an issue labelled `triage` + `auto-filed` + `bug`.
- No other change. `list` already shows any open `triage` issue without a decision label.

**Done when:** the AC-088.10 tests for `setup-labels` (creates `auto-filed`) and `list` (shows an auto-filed issue)
pass, and `test_triage.py` stays green.

## t4 — ship escalate files cause platform and coerces unknown causes

**Files:** scripts/cplat/ship.py
**Covers:** AC-088.1, AC-088.2, AC-088.3, AC-088.9, AC-088.11, AC-088.12, AC-088.13, AC-088.14
**Goal:** `cplat ship escalate <reason> --cause platform` files or +1's the failure before the run record ends, and
prints the issue line. Other causes only record. A missing or unknown cause becomes `unknown` with the message. See
design.md "`cplat ship escalate`".

**Implementation notes:**
- `ESCALATION_CAUSES = ("platform", "code", "decision", "environment")`. `escalate(repo, reason, cause=None, *,
  command=None, evidence="", report=None)` coerces the cause and appends the cause message to `report`.
- For `platform`, before `save_state`:
  - `_ensure_run(repo, st)`
  - build the `Draft`: the signature over `(command or "/svc:ship", st["phase"], reason)` with
    `private_names(runs.repo_slug(repo), st["spec"], st["branch"])`, the shape from the stamp, and
    `environment=feedback.diagnostics(repo)`
  - `autoissue.file(draft, run_id=st["run_id"])`
  - extend `report` with `outcome.lines`

  Wrap all of it in `try/except Exception`, so an escalation always completes.
- The CLI drops `choices=` from `--cause` (default `None`) and adds `--command` and `--evidence-file` (`-` = stdin; an
  unreadable file gives `""`). It prints the escalated line, then the report lines. Exit 0.
- The gate's escalate hint: ``run `cplat ship escalate '<reason>' --cause <platform|code|decision|environment>`, then stop.``
- `cause` is stored in the state as the coerced value, so 087's `_record` passes it on unchanged.

**Done when:** the acceptance tests for AC-088.1, .2, .3, .12 and the escalation parts of .9, .11, .13 and .14 pass
through `ship.main([... "escalate" ...])` with a fake tracker. `test_ship.py`, `test_ship_checks.py` and the 087
escalation tests (except the rewritten cause test) stay green.

## t5 — cplat crash hook files inside a recorded run

**Files:** scripts/cplat/cplat.py
**Covers:** AC-088.4
**Goal:** an unexpected exception in any command, inside a recorded run, is filed or +1'd at once as cause `platform`.
Outside a recorded run, the output is exactly as today.

**Implementation notes:**
- In `except Exception as e`, after the `ERROR: unexpected failure …` line:
  `rid = runs.current(Path.cwd())` (guarded).
  - With a `rid`: `autoissue.file_crash(argv, e, rid, Path.cwd())`, and print its lines to stderr. Print no
    `/shared:report-issue` hint unless the result is `off` (the hint is in its lines).
  - Without one: today's hint.
- The hook's own failure falls back to today's hint. `CPLAT_DEBUG` re-raises after the hook. Exit 70.
- `core.PlatformError` (an error the platform reports with a hint) never files.
- Import `runs` and `autoissue` lazily inside the branch, so a broken import cannot stop `cplat` from starting.

**Done when:** the AC-088.4 tests pass. Inside an active ship run, a crashing command files with the exception type and
the last 20 traceback lines. A `PlatformError` files nothing. Outside a run, the hint is unchanged
(`test_feedback.py::test_an_unexpected_crash_points_to_the_report_command` stays green).

## t6 — ship command text and docs for auto-filed issues

**Files:** plugins/svc/commands/ship.md, docs/CHANGELOG.md, docs/unattended-delivery.md
**Covers:** AC-088.1
**Goal:** the orchestrator states the cause, and it no longer offers `/shared:report-issue` for platform failures
that cplat files itself. Users learn what gets filed and how to switch it off.

**Implementation notes:**
- `ship.md`, Escalate:
  - Always pass `--cause`: `platform` (a platform template, script or command misbehaved), `code`, `decision` or
    `environment` (runner, cluster, network, a missing secret or login).
  - For `platform`, also pass `--command '<the failing command>'`, and the failing output through
    `--evidence-file -` or a file.
  - cplat files or +1's the issue and prints `issue: <url> new|+1`. Report that line, and only what the user must
    decide.
- `ship.md`: replace the closing `> If a step fails because a platform … offer /shared:report-issue` paragraph with:
  escalate with `--cause platform`. The issue is filed automatically (spec 088), and with `CPLAT_AUTO_ISSUES=off` the
  draft and the `/shared:report-issue` hint are printed instead.
- `docs/CHANGELOG.md`: one bullet under `[Unreleased]`: **Feature (088): platform failures become deduplicated
  issues.** It covers:
  - `cplat ship escalate --cause platform`, and crashes inside a recorded run
  - the `Signature:` line and the `auto-filed` label
  - +1 on the oldest open issue, a new linked issue after close (not after `wontfix`)
  - the cap of 10 per 24 h, pending retry at `cplat runs flush`
  - `CPLAT_AUTO_ISSUES=off`, `CPLAT_FEEDBACK_REPO`, and ADR-033

  Run `cplat triage setup-labels` once to create `auto-filed`.
- `docs/unattended-delivery.md`: an "Auto-filed platform issues" section after "Run records" (what is filed and never
  filed, redaction, the run id without a link, the cap, offline behaviour, switching it off).
- No plugin or marketplace version bumps.

**Done when:** `devbox run validate` and the Markdown link check pass, and ship.md no longer tells the orchestrator to
offer `/shared:report-issue` for a `platform` escalation.
