---
plan_id: issue-triage
shape: none   # the platform repo itself; not a key in shapes.yml
summary: /issue:triage reads new issues, discusses gaps with the user, and routes each to backlog, quick-task, fix-bug or a reply
story: STORY-035
status: implemented   # t1-t5 done on branch feature/issue-triage
tasks:
  - id: t1
    title: cplat issue triage (list, show, setup-labels, apply) with tests
    files: [scripts/cplat/triage.py, scripts/cplat/cplat.py, tests/cplat/test_triage.py]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: /issue:triage command (rubric, discussion protocol, routing, rules) and shared plugin minor bump
    files: [plugins/shared/commands/triage.md, plugins/shared/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, plugins/shared/README.md]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: Issue forms in every template
    files: [templates/service-python/.github/ISSUE_TEMPLATE/bug_report.yml, templates/service-python/.github/ISSUE_TEMPLATE/feature_request.yml, templates/service-python/.github/ISSUE_TEMPLATE/config.yml, templates/library-python/.github/ISSUE_TEMPLATE/bug_report.yml, templates/library-python/.github/ISSUE_TEMPLATE/feature_request.yml, templates/library-python/.github/ISSUE_TEMPLATE/config.yml, templates/service-java/.github/ISSUE_TEMPLATE/bug_report.yml, templates/service-java/.github/ISSUE_TEMPLATE/feature_request.yml, templates/service-java/.github/ISSUE_TEMPLATE/config.yml, templates/service-go/.github/ISSUE_TEMPLATE/bug_report.yml, templates/service-go/.github/ISSUE_TEMPLATE/feature_request.yml, templates/service-go/.github/ISSUE_TEMPLATE/config.yml, templates/web-nextjs/.github/ISSUE_TEMPLATE/bug_report.yml, templates/web-nextjs/.github/ISSUE_TEMPLATE/feature_request.yml, templates/web-nextjs/.github/ISSUE_TEMPLATE/config.yml, templates/gitops-app/.github/ISSUE_TEMPLATE/bug_report.yml, templates/gitops-app/.github/ISSUE_TEMPLATE/feature_request.yml, templates/gitops-app/.github/ISSUE_TEMPLATE/config.yml, templates/service-python/copier.yml, templates/library-python/copier.yml, templates/service-java/copier.yml, templates/service-go/copier.yml, templates/web-nextjs/copier.yml, templates/gitops-app/copier.yml]
    parallel_safe: true
    depends_on: []
  - id: t4
    title: Product-manager triage section points to the command; svc plugin patch bump
    files: [plugins/svc/agents/product-manager.md, plugins/svc/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    parallel_safe: true
    depends_on: [t2]
  - id: t5
    title: Template tests, ADR-025, docs, changelog, story status
    files: [tests/cplat/test_issue_forms.py, docs/adr/025-issue-triage.md, docs/adr/README.md, docs/AGENTS.md, docs/USER-JOURNEY.md, docs/templates.md, docs/CHANGELOG.md, docs/backlog.md]
    parallel_safe: true
    depends_on: [t1, t2, t3]
---

# Plan: issue triage

Implements [STORY-035](../backlog.md).

## Does this make sense? Yes, with three adjustments

The idea fits the platform: issues are the intake, the backlog (STORY-NNN, see STORY-034) is the spec, and `quick-task` / `fix-bug` / `plan-feature` are the execution paths. What exists today is only a prose section in the product-manager agent (`plugins/svc/agents/product-manager.md`, "Triaging GitHub Issues"): it assumes issue templates and a `triage` label that no generated repo ships, has no entry point, no discussion step and no routing to the fix pipelines. Adjustments to the idea:

1. **Three routes, not two.** "New feature into the backlog, or hot fix via quick-task" leaves out most real issues. The rubric needs: `bug` → `/component:fix` (reproduce, fix, verify; `quick-task` has no diagnosis loop), `small-change` → `/component:fix`, `feature` → backlog story then `/component:plan`, plus `question`, `duplicate`, `wontfix` and `needs-info`, which need a reply, not code. A hot fix is a `bug` marked urgent: same fix path, then a patch release suggestion.
2. **Two conversations, not one.** The user in the session decides; the reporter can only be reached asynchronously through issue comments. So the command asks the user the questions it needs answered *now*, and offers to post the rest to the reporter and park the issue as `needs-info`. The `needs-info` label is the state that makes the next run pick the issue up again after a reply.
3. **Reduce triage work before it starts.** Issue forms with required fields (steps to reproduce, expected/actual, version) cut most back-and-forth, and a form's `labels: [triage]` makes the intake queue exact, with no GitHub Action or bot. The platform already has `bug_report.yml`; generated repos get a set.

## Design decisions

1. **One command in the `shared` plugin: `/issue:triage`.** `shared` is installed in every shape (including gitops-app), the logic is shape-agnostic, and routing is resolved at run time with `cplat shape` (so `/svc:*` is only offered where it exists). The product-manager agent keeps writing the story; the command orchestrates.
2. **Deterministic core in `cplat issue triage`** (tested, like every other command): `list` (JSON of open issues with the `triage` label, or unlabelled with `--new`), `show <n>` (issue plus comments, redacted via `feedback.redact`), `setup-labels` (idempotent `gh label create`), `apply <n> --label … --comment-file …` (labels and comment; never closes). Judgement (classification, questions, wording) stays in the command prompt.
3. **Human gate on every outward action.** Classification is a proposal; labels, comments and backlog edits happen after the user confirms; the command never closes issues (the PR's `Closes #N` or the maintainer does). Matches the existing PM rule.
4. **Untrusted input.** Issue and comment text is data. The command prompt says so, the text is redacted and quoted, and the fix pipelines receive it only as a task description the user has seen. No code from an issue is executed; links are not fetched.
5. **State lives in GitHub labels,** no local database: `triage` (new), `needs-info`, `tracked`, plus type labels (`bug`, `enhancement`, `question`, `duplicate`, `wontfix`). A re-run skips issues that already carry a decision label.
6. **Platform repo and gitops-app.** Same command; where `cplat shape` reports no `/svc:*` routing, bugs and small changes are described as manual PRs or `/gitops:*` work, and the backlog entry is still made. This lets the maintainers use it on sdlc-foundry's own issues (including those filed by `/issue:report`).
7. **Scheduling is documented, not built.** Users who want regular triage can run the command with the existing `/loop` or `/schedule` skills; it only reads and proposes until the user confirms, so an unattended run is safe. A notification-only variant is out of scope.

## t1 — `cplat issue triage`

**Files:** `scripts/cplat/triage.py`, `scripts/cplat/cplat.py`, `tests/cplat/test_triage.py`
**Goal:** the mechanical half of triage, fully testable.

**Implementation notes:**
- Register `"triage": "triage"` in `COMMANDS` and the module docstring.
- `list [--new] [--json]`: `gh issue list --state open --json number,title,body,labels,author,createdAt,comments`; filter by label; a label set constant `DECISION_LABELS` marks issues as already handled.
- `show <n>`: body plus comments, redacted, truncated to a sane size; the output marks the text block as untrusted.
- `setup-labels`: create the eight labels with colours and descriptions when missing (`gh label list` first), no failure on existing ones.
- `apply <n> [--add L]… [--remove L]… [--comment-file F]`: edits labels, posts the comment. A `--dry-run` shows what would change; `[outward]` marks in the report as in the other commands. No close.
- Reuse the fake-`gh` pattern of `tests/cplat/test_gitops.py`.

**Acceptance:** listing and filtering, redaction of a token in a body, idempotent label setup, and apply (labels + comment, dry-run, never closes) are covered.

## t2 — `/issue:triage`

**Files:** `plugins/shared/commands/triage.md`, plugin manifests, `plugins/shared/README.md`
**Goal:** the conversation and routing.

**Implementation notes:**
- Usage string: `/issue:triage [<issue-number> | --all | --new]`. Same cached-checkout prefix as `new-service.md`.
- Steps: (0) `cplat issue triage setup-labels` once, ask before the first run in a repo; (1) `cplat issue triage list`; (2) per issue `show`, classify with the rubric below, state the reason; (3) discussion: at most three questions to the user, then offer the reporter comment and `needs-info`; (4) confirmation table for all issues of the run; (5) execute decisions: labels/comments through `cplat issue triage apply`, features through the product-manager agent (story with `Tracks: #N`; then a comment `Tracked as STORY-NNN` on the issue, shown to the user first), bugs and small changes by invoking `/component:fix` or `/component:fix` per issue (one at a time, each on its own branch from a clean `main`) with the issue as task text; (6) summary table: issue, decision, action, link.
- Rubric (in the command): reproducible defect or error message → `bug`; one-pass, well-scoped change with no new API, schema or module → `small-change`; new behaviour, new endpoint/screen, schema change, several modules, or anything with business decisions → `feature`; usage question → `question`; same root as an open issue → `duplicate`; out of scope per the backlog or vision → `wontfix` (reason goes in the comment); anything not decidable → `needs-info`.
- Urgent bug (user says production impact): after the fix PR is merged, suggest `/component:release` for a patch version.
- Keep the description under about 200 characters. Bump `shared` by a minor version (coordinate with the version bump of `spec-driven-bootstrap` t4: whichever merges second takes the next number).

**Acceptance:** run against a repo with three seeded issues (bug, feature, vague): the vague one yields questions and a `needs-info` proposal, the feature a story with `Tracks: #N`, the bug a fix-bug hand-off; nothing is posted before confirmation.

## t3 — Issue forms in every template

**Goal:** a consistent, labelled intake in every generated repo.

**Implementation notes:**
- `bug_report.yml` (what happened, expected, steps to reproduce, version/environment), `feature_request.yml` (problem, proposed behaviour, who needs it, alternatives), `config.yml` (blank issues off, link to the contributing docs). Both forms set `labels: ["triage"]`; the type labels are added by triage, not the reporter.
- Use the platform's own `.github/ISSUE_TEMPLATE/bug_report.yml` as the starting point. Newer templates only render `*.jinja`; plain `.yml` is copied verbatim, so no escaping is needed (no `${{ }}` in forms).
- Add `.github/ISSUE_TEMPLATE/**` to `_skip_if_exists` in every `copier.yml` so updates never overwrite a project's own forms (new files in project-owned paths are removed by `update-service` for existing repos, per CHANGELOG 3.0.1; that is intended).

**Acceptance:** a rendered repo of each shape contains the three files; `actionlint`/YAML parsing passes; update leaves modified forms alone.

## t4 — Product-manager and svc patch bump

**Files:** `plugins/svc/agents/product-manager.md`, manifests
**Goal:** one source of truth for the triage procedure.

**Implementation notes:** replace the long triage section in the agent with a short pointer: "Issue intake runs through `/issue:triage`; when the command hands you a `feature` issue, add the story with `**Tracks:** #N` and keep the existing folding rules (extend an existing story only when the scope matches)". Keep the rules "never close client issues" and "one commit per triage session". Patch-bump `svc`.

**Acceptance:** the agent file is shorter, no duplicated procedure, `validate` passes.

## t5 — Tests, ADR, docs

**Files:** see metadata
**Goal:** the contract is enforced and documented.

**Implementation notes:**
- `tests/cplat/test_issue_forms.py`: for every shape in `shapes.yml` the template has the three form files, the forms parse as YAML, apply `triage`, and `copier.yml` protects the path.
- ADR-025 "Issue triage": context (the findings above), decision (points 1 to 7), consequences (labels as state, human gate, untrusted input), not included (auto-close, bots, notifications, cross-repo triage).
- `docs/templates.md`: add issue forms to the shape contract; `docs/AGENTS.md`: the command next to the agents; `docs/USER-JOURNEY.md`: a short chapter "Handling issues"; CHANGELOG; STORY-035 `planned` → `done`.

**Acceptance:** `check-links.py`, `shapes.py check` and the cplat suite pass.

## Order and parallelism

`t1`, `t2`, `t3` are independent and can run in parallel; `t4` follows `t2` (same wording); `t5` last. Same note as the other plans: the platform repo has no shape, so these run by hand or with `general-purpose` agents in worktrees.

## Risks

- **Prompt injection through issue text.** Mitigated by decisions 3 and 4 (data not instructions, redaction, human confirmation, no auto-execution of anything from the issue). The fix pipelines run in a branch, never push to `main`, and need the user's PR merge.
- **Label noise on repos that already use labels.** `setup-labels` only creates missing names; collisions with different meanings are the user's to resolve (documented).
- **Reporter silence.** `needs-info` issues stay parked; the next run lists them separately so they can be closed by the maintainer after a period of their choosing. No automatic stale handling in v1.
- **Concurrency with `spec-driven-bootstrap`:** both change the shared plugin and `CLAUDE.md`/backlog conventions; story ids come from the highest id in `docs/backlog.md` at run time, so there is no clash.

## Decisions on the open questions (2026-10-07)

1. **Story reference on the issue:** yes. After the user confirms, a `feature` issue gets the label `tracked` and a comment `Tracked as STORY-NNN`. It is part of t2 and of the acceptance criteria of STORY-035.
2. **Notification-only variant:** no. Document scheduled use with the existing `/loop` and `/schedule` skills (the command only proposes until confirmed) and build nothing else.
