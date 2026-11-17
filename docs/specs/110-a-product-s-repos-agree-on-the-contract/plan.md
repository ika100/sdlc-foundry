---
spec_id: 110-a-product-s-repos-agree-on-the-contract
shape: platform
spec_hash: 8d3e1536cb50
summary: The plan's contract states shared input rules and the error contract as data; each repo gets a copy, checks itself against it in CI, and the gitops-app pin PR refuses a stale copy
tasks:
  - id: t1
    title: plan-check checks the Rules part and the Errors block; plan.py contract prints a repo's slice
    files: [templates/gitops-app/scripts/plan.py, tests/cplat/test_plan.py]
    covers: [AC-110.1, AC-110.2, AC-110.3, AC-110.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: service-python provider contract check from the copy
    files: [templates/service-python/scripts/contract_pytest.py, templates/service-python/tests/test_contract.py, templates/service-python/devbox.json, templates/service-python/CLAUDE.md]
    covers: [AC-110.5, AC-110.8, AC-110.10]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: web-nextjs consumer contract check (validation and error display) from the copy
    files: [templates/web-nextjs/lib/contract/engine.ts, templates/web-nextjs/tests/contract.test.ts, templates/web-nextjs/tests/contract/adapter.ts, templates/web-nextjs/CLAUDE.md.jinja]
    covers: [AC-110.6, AC-110.7, AC-110.8, AC-110.10]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: Planner and spec-from-plan prompts show the rules, the error block and the worked example
    files: [plugins/system/agents/planner.md, docs/rules/plugins/system/agents/planner.yml, plugins/component/references/spec-from-plan.md, docs/rules/plugins/component/references/spec-from-plan.yml, docs/rules/register.yml]
    covers: [AC-110.11, AC-110.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: The system benchmark plan states its rules and error block
    files: [scripts/cplat/benchmark/system/plan.md]
    covers: [AC-110.1]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t8
    title: ADR for contract rules and the ADR-011 format amendment with the worked example
    files: [docs/adr/README.md, docs/adr/*-shared-input-rules-live-in-the-plan-contract.md, docs/adr/011-multi-repo-plan-format.md, docs/specs/110-a-product-s-repos-agree-on-the-contract/design.md]
    covers: [AC-110.11]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t9
    title: Plugin versions and changelog fragment
    files: [plugins/system/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/changelog.d/110-contract-rules-between-repos.added.md]
    covers: []
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: cplat spec new --from-plan writes contract/<plan_id>.json and lists the rules in the System context
    files: [scripts/cplat/contract_copy.py, scripts/cplat/spec.py]
    covers: [AC-110.4, AC-110.10]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t5
    title: gitops-app CI job contract-pins compares pinned copies with the plans
    files: [templates/gitops-app/scripts/check-contract-pins.py, templates/gitops-app/.github/workflows/ci.yml, templates/gitops-app/devbox.json, templates/gitops-app/CLAUDE.md.jinja]
    covers: [AC-110.9]
    parallel_safe: true
    depends_on: [t1]
    done: true
---

# Plan — 110 A product's repos agree on the contract between them

The contract is [design.md](design.md). Level 0 runs seven tasks with disjoint files: the parser and plan-check in
`plan.py` (t1), the two repo-local checks (t3, t4; they build against the copy format of design 3, not against code),
the prompts (t6), the benchmark plan (t7), the ADRs (t8) and the release bookkeeping (t9). Level 1 holds the two
consumers of t1's parser: the copy writer in cplat (t2, runs `plan.py contract`) and the pin check (t5, `import plan`).

## t1 — plan-check checks the Rules part and the Errors block; plan.py contract prints a repo's slice

**Files:** templates/gitops-app/scripts/plan.py, tests/cplat/test_plan.py
**Covers:** AC-110.1, AC-110.2, AC-110.3, AC-110.4
**Goal:** a plan with `spec:` and two or more repos must state its shared input rules and its error contract as the
YAML blocks of design 1, or say `No shared rules: <reason>`; finished plans only warn; `plan.py contract <plan-file>
<repo-id>` prints the repo's slice as JSON (design 2) for cplat.

**Implementation notes:**
- Pure functions, importable by `check-contract-pins.py`: `subsection(contract, "Rules")` (text until the next `###`/`##`),
  `yaml_block(text, key)` (first fenced `yaml` block whose mapping has `key`), `parse_rules(contract, repo_ids) ->
  (rules: list[dict] | None, no_rules_reason: str | None, errors: list[str])`, `parse_errors(contract) -> (dict | None,
  list[str])`, `resolved(rules, errors_block)` (status and step filled in), `repo_slice(rules, errors_block, repo_id)`.
- `contract_text(meta, body, spec_dir)`: the design.md `## Contract` wins over the plan body, as `check_contract` does
  today; reuse it there.
- `check_contract` adds the spec 110 findings to `late`; messages exactly as design 1, rule id in each.
- Finished-plan warning: the missing list gains `no \`### Rules\`` (keep the existing parts and wording).
- `contract` subcommand: path argument (not slug), spec dir from the plan's location; exit codes as design 2; JSON with
  `sort_keys=True, indent=2`.
- Never import a sibling module: several suites copy `plan.py` alone.
- `tests/cplat/test_plan.py`: the shared `CONTRACT` constant and the active-plan cases gain a valid `### Rules` and
  error block so the spec 053 / 061 tests keep testing what they tested.

**Done when:** the AC-110.1 to AC-110.3 tests and the plan.py part of AC-110.4 (`contract` output) pass, and the
existing `test_plan.py`, `test_units_131.py`, `test_appship_097.py` and `test_154_journey_6_findings.py` still pass.

## t3 — service-python provider contract check from the copy

**Files:** templates/service-python/scripts/contract_pytest.py, templates/service-python/tests/test_contract.py, templates/service-python/devbox.json, templates/service-python/CLAUDE.md
**Covers:** AC-110.5, AC-110.8, AC-110.10
**Goal:** a provider repo's `devbox run test` (and `test-fast`) sends the boundary values of every provider rule of
`contract/*.json` to the app in-process and fails naming the rule id, field, expected and actual result (design 4).

**Implementation notes:**
- `contract_cases`, `check_case`, the `Case` type (its `str` is the case id) and the default fixtures `contract_send`
  (`TestClient(app)` from `{{ module_name }}.main`) and `contract_base` in `scripts/contract_pytest.py`; the file is
  rendered by Copier (the template renders every file).
- Value generation and the rejection check exactly as design 4's table; dotted fields set/remove nested keys; decimal
  steps rounded to the step's decimals.
- `tests/test_contract.py`: the one parametrized test; it is created on update (tests/** only skips existing files).
- `devbox.json`: `-p scripts.contract_pytest` in `test` and `test-fast` next to `-p scripts.smoke_pytest`.
- `CLAUDE.md`: a short "Contract check" section: where the copy comes from (`/component:spec --from-plan`), how to
  override `contract_send` / `contract_base` in `tests/conftest.py`, never edit the copy by hand.
- Passes ruff and mypy of the rendered template (`devbox run smoke-service`).

**Done when:** the AC-110.5 and AC-110.8 tests pass against a rendered service with a copy and a small app that
agrees / disagrees; a rendered service without a copy still passes `devbox run test`.

## t4 — web-nextjs consumer contract check (validation and error display) from the copy

**Files:** templates/web-nextjs/lib/contract/engine.ts, templates/web-nextjs/tests/contract.test.ts, templates/web-nextjs/tests/contract/adapter.ts, templates/web-nextjs/CLAUDE.md.jinja
**Covers:** AC-110.6, AC-110.7, AC-110.8, AC-110.10
**Goal:** a consumer repo's `devbox run test` runs its own validation with the boundary values of every consumer rule
and feeds its form the contract's error response and one unlisted response, failing with the messages of design 5.

**Implementation notes:**
- `engine.ts`: `ContractAdapter`, `ContractCase`, `contractCases(dir = "contract")` reading `contract/*.json` with
  `node:fs`; the same value table as design 4 (keep the generation rules identical to t3's).
- Response cases build the body from `errors.body` (with or without `list`); unlisted status = first of 500, 503, 502
  not used in the copy.
- `tests/contract/adapter.ts`: default adapter as design 5 (throws the wiring message only when a case calls it).
- `tests/contract.test.ts`: one `it` per case; the placeholder test when there is no copy (vitest refuses an empty file).
- `CLAUDE.md.jinja`: a short "Contract check" section (copy origin, wiring the adapter with Testing Library, never edit the copy).
- Plain `.ts`/`.tsx` files (not `.jinja`): JSX and `${}` must not pass through Jinja. Passes eslint and `tsc --noEmit`.

**Done when:** the AC-110.6, AC-110.7 and AC-110.8 tests pass against a rendered web app with a copy and a small form
that agrees / disagrees; a rendered web app without a copy still passes `devbox run test`.

## t6 — Planner and spec-from-plan prompts show the rules, the error block and the worked example

**Files:** plugins/system/agents/planner.md, docs/rules/plugins/system/agents/planner.yml, plugins/component/references/spec-from-plan.md, docs/rules/plugins/component/references/spec-from-plan.yml, docs/rules/register.yml
**Covers:** AC-110.11, AC-110.4
**Goal:** the planner writes `### Rules` and the `errors:` block (step 5 and the step 8 template show the worked example
of design 1: a title with `max_length` and a status with `allowed` values); spec-from-plan says the new spec comes with
`contract/<plan_id>.json`, committed with the spec, and that a re-run updates it.

**Implementation notes:**
- Step 8 template: replace the `### Errors` placeholder with the `errors:` block and add `### Rules` with the example
  rules; step 5 names the six kinds, the `No shared rules: <reason>` line and that plan-check refuses the rest (spec 110).
- Keep the words `### Errors`, `### Timeouts` and "not list" (pinned by `test_spec_agents.py`).
- Every new or changed rule sentence gets its register entry with a reason clause (`docs/rules/README.md`).
- Bytes: pay for the example by tightening other sentences of the two prompts; if it still exceeds
  `baseline.prompt_bytes`, raise it with `cplat platform rules rebaseline --reason "<why>"` after the two benchmarks
  (docs/rules/README.md, Raise the baseline).

**Done when:** the AC-110.11 prompt tests pass, `cplat platform rules check` passes, and the existing planner prompt
tests still pass.

## t7 — The system benchmark plan states its rules and error block

**Files:** scripts/cplat/benchmark/system/plan.md
**Covers:** AC-110.1
**Goal:** the benchmark's draft plan, copied into a gitops-app clone by `runs_bench_system.py`, passes the new plan-check.

**Implementation notes:**
- Add `### Rules` with the rules the existing contract text already states (limits on label names, if any) as the YAML
  block, or `No shared rules: <reason>`; add the `errors:` block matching the error body the contract already describes.
- Change no other part of the plan, so the benchmark measures the same work.

**Done when:** `plan.py validate` on a copy of the benchmark spec and plan passes once t1 is merged.

## t8 — ADR for contract rules and the ADR-011 format amendment with the worked example

**Files:** docs/adr/README.md, docs/adr/*-shared-input-rules-live-in-the-plan-contract.md, docs/adr/011-multi-repo-plan-format.md, docs/specs/110-a-product-s-repos-agree-on-the-contract/design.md
**Covers:** AC-110.11
**Goal:** the decision that outlives this spec is recorded, and the plan format doc shows the new parts.

**Implementation notes:**
- `cplat adr add shared-input-rules-live-in-the-plan-contract --decision "Shared input rules and the error contract are YAML data in the plan's contract; each repo keeps a copy it checks in CI, and the gitops-app pin PR refuses a stale copy"`
  (writes the file and the README row); fill Context, Decision (the source, the copy, the two repo checks, the pin
  check, the six kinds), Consequences (Java/Go providers follow in a later spec, patterns stay prose, draft plans are
  checked at pins too).
- ADR-011: `## Amendment (spec 110)` with `### Rules`, the `errors:` block and the worked example of design 1.
- design.md, first decision: replace the placeholder ADR path with the link to the new file.

**Done when:** `devbox run quality` (Markdown links) passes.

## t9 — Plugin versions and changelog fragment

**Files:** plugins/system/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/changelog.d/110-contract-rules-between-repos.added.md
**Covers:** none (release bookkeeping)
**Goal:** the PR passes `cplat platform pr-check`.

**Implementation notes:**
- System plugin 1.22.0 → 1.23.0 (planner format); component plugin 1.24.0 → 1.24.1 (reference wording); the matching
  `marketplace.json` entries.
- Fragment per `docs/changelog.d/README.md`: `### Rules` and the `errors:` block in plans, the copy written by
  `--from-plan`, the service-python and web-nextjs contract checks, the gitops-app `contract-pins` job; upgrade note:
  active multi-repo plans need `### Rules` after `/platform:update`.

**Done when:** `devbox run validate` and `cplat platform pr-check` (versions, fragment) pass.

## t2 — cplat spec new --from-plan writes contract/<plan_id>.json and lists the rules in the System context

**Files:** scripts/cplat/contract_copy.py, scripts/cplat/spec.py
**Covers:** AC-110.4, AC-110.10
**Goal:** every `cplat spec new --from-plan` (by hand or from `/system:ship`) writes or removes the repo's copy as
design 3 says and adds `### Contract rules` to the System context.

**Implementation notes:**
- `contract_copy.slice(plan_path, repo_id) -> dict` runs `[sys.executable, core.PLATFORM_ROOT/templates/gitops-app/scripts/plan.py, "contract", plan, repo_id]`; exit 1 → the `PlatformError` of design 3.
- `contract_copy.commit(plan_path)` (`git -C <plan dir> rev-parse HEAD`), only when the slice has rules.
- `contract_copy.write(root, doc) -> str` (the CLI line) and `contract_copy.section(doc) -> str` (the markdown of design 3).
- `slice_from_plan` returns the slice; `new_from_plan` calls `slice` before `new()` (a bad contract writes no spec),
  appends `section` after `### Contract`, writes or deletes `contract/<plan_id>.json`.
- `main`: print the `contract copy:` line after the spec line; `--json` output (if any) gains `contract_copy`.
- `appship_sched.repo_spec_of` needs no change: its `git add -A` commits the copy.

**Done when:** the AC-110.4 and AC-110.10 tests pass, and the existing from-plan tests (`test_spec.py`,
`test_188_spec_cli.py`, `test_183_replaces.py`, the appship 155 tests) still pass.

## t5 — gitops-app CI job contract-pins compares pinned copies with the plans

**Files:** templates/gitops-app/scripts/check-contract-pins.py, templates/gitops-app/.github/workflows/ci.yml, templates/gitops-app/devbox.json, templates/gitops-app/CLAUDE.md.jinja
**Covers:** AC-110.9
**Goal:** a PR that changes a component's pinned tag fails when the pinned commit's copy differs from a plan's current
rules or error contract, or is missing for a repo the plan assigns a rule (design 6).

**Implementation notes:**
- uv script (pyyaml), `import plan` for `contract_text`, `parse_rules`, `parse_errors`, `resolved`, `repo_slice`.
- GitHub reading: copy `check-service-crds.py`'s `api_get`/`NoRedirect`/redaction pattern (no shared import, the
  scripts stay independent); contents API with `ref=<sha>` or `ref=v<X.Y.Z>`.
- Changed pins from `git merge-base $BASE_REF HEAD` vs the working tree; messages, order of steps and exit codes
  exactly as design 6.
- `ci.yml`: job `contract-pins` as design 6, pinned action SHAs as in the existing jobs; `devbox.json`: recipe
  `contract-pins` (not in `ci`, since a local run has no PR); `CLAUDE.md.jinja`: the recipe row.

**Done when:** the AC-110.9 tests pass with a fake GitHub API (`GITHUB_API_URL` to a local server) and a git repo with
a base and a pin commit; the rendered gitops-app still passes `devbox run validate` and the pinned-Actions check passes.
