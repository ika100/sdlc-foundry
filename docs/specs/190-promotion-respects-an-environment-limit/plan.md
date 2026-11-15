---
spec_id: 190-promotion-respects-an-environment-limit
shape: platform
spec_hash: 10ad01ff126d
summary: An `environments:` field in spec front matter that spec check validates, spec show/approve display, and manual and automatic promotion respect, with a person-only override
tasks:
  - id: t1
    title: envlimit module, spec check field errors, spec show and approve output
    files: [scripts/cplat/envlimit.py, scripts/cplat/spec.py]
    covers: [AC-190.1, AC-190.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: instance promote refuses a limited target, dry-run REFUSED lines, --accept-environment-limit
    files: [scripts/cplat/promote.py]
    covers: [AC-190.2, AC-190.3]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: Automatic staging promotion skips on an environment limit
    files: [scripts/cplat/staging.py, scripts/cplat/appship_joint.py]
    covers: [AC-190.4]
    parallel_safe: true
    depends_on: [t1]
  - id: t4
    title: Prompts - product-manager limit rule, spec-format field, approval summaries, /instance:promote rule
    files: [plugins/svc/agents/product-manager.md, plugins/svc/skills/spec-format/references/spec.md, plugins/component/commands/spec.md, plugins/system/commands/spec.md, plugins/instance/commands/promote.md, docs/rules/plugins/svc/agents/product-manager.yml, docs/rules/plugins/svc/skills/spec-format/references/spec.yml, docs/rules/plugins/component/commands/spec.yml, docs/rules/plugins/system/commands/spec.yml, docs/rules/plugins/instance/commands/promote.yml, plugins/svc/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/instance/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-190.5, AC-190.6, AC-190.7]
    parallel_safe: true
    depends_on: [t1]
  - id: t5
    title: Benchmark workflow spec-environments
    files: [scripts/cplat/runs_bench.py, scripts/cplat/benchmark/tasks.json, scripts/cplat/runs.py]
    covers: [AC-190.6]
    parallel_safe: true
    depends_on: []
  - id: t6
    title: Promotion guide and changelog fragment
    files: [site/src/content/docs/scenarios/promote-safely.md, docs/unattended-delivery.md, docs/changelog.d/190-promotion-respects-an-environment-limit.added.md]
    covers: [AC-190.7]
    parallel_safe: true
    depends_on: []
---

# Plan — 190 Promotion respects an environment limit in the spec

The contract (field, lines, flags, JSON keys) is in [design.md](design.md); every task follows it verbatim.

## t1 — envlimit module, spec check field errors, spec show and approve output

**Files:** scripts/cplat/envlimit.py, scripts/cplat/spec.py
**Covers:** AC-190.1, AC-190.5
**Goal:** a new module that owns the `environments:` field and all its lines, and the `cplat spec` surface that checks and
shows it.

**Implementation notes:**
- `envlimit.py` with the public interface of design.md (`ENVIRONMENTS`, `LIMITING`, `Limit`, `field_errors`, `allowed`,
  `limit_of`, `local_limits`, `remote_limits`, `envs_text`, `refusal_line`, `fix_text`, `accepted_line`, `skip_reason`,
  `summary_line`) and the exact texts of its Lines table. Import `model` at the top, `spec` inside `local_limits` /
  `remote_limits` (no cycle).
- `spec.check`: append `envlimit.field_errors(meta)` next to the `explored` check, before the `superseded` early return.
- `spec.summary` gains `"environments"`; `broken_summary` gets `None`.
- New subcommand `show <id> [--json]` printing the four-line text of design.md (the limit line only with the field); `--json`
  prints `detail(...)` for that spec.
- `approve` gains `--json`; text mode prints `summary_line` after `<spec_id>: approved` when the field is present.
- Module docstring of `spec.py`: add `show` to its verb list.

**Done when:** the acceptance tests for AC-190.1 and the `cplat spec show` / `cplat spec approve` parts of AC-190.5 pass, and
`cplat spec check` passes on this repo.

## t2 — instance promote refuses a limited target, dry-run REFUSED lines, --accept-environment-limit

**Files:** scripts/cplat/promote.py
**Covers:** AC-190.2, AC-190.3
**Goal:** `cplat instance promote --to staging|prod` refuses while a `building`/`done` spec of the gitops-app repo leaves the
target out, unless the person overrides it with a reasoned flag that is recorded in the output and the PR body.

**Implementation notes:**
- `--accept-environment-limit REASON` (argparse, default None); validate with `_reason_ok` next to the digest-reason check,
  message and hint as in design.md.
- After the `--smoke` branch and before `require_clean`, for `to in ("staging", "prod")`: `envlimit.local_limits(repo, to)`.
- No flag: without `--dry-run` raise the `PlatformError` of design.md; with `--dry-run` emit the refusal Report and return 1.
- With the flag: `accepted_line` per spec into `will_do` / `did` and as a block in the PR body after the pin list.
- `r.data["environment_limits"]` on every staging/prod promotion (empty list without limits).
- The dev rollback and `--smoke` paths stay untouched.

**Done when:** the acceptance tests for AC-190.2 and AC-190.3 pass, and the existing promote tests (digest, rollback, smoke,
several components) still pass.

## t3 — Automatic staging promotion skips on an environment limit

**Files:** scripts/cplat/staging.py, scripts/cplat/appship_joint.py
**Covers:** AC-190.4
**Goal:** a green dev smoke never dispatches or opens a staging pin while a limiting spec leaves staging out, and the skip
reads `not promoted: environment limit <spec_id> allows <envs>` without turning the step red.

**Implementation notes:**
- `staging.py`: two small readers over `gh api repos/<slug>/contents/<path>` through `_try` (a directory listing returning
  the names of `type: dir` entries or None; a raw text read returning the text or None), passed to
  `envlimit.remote_limits(..., "staging")`.
- `staging.decide`: call it after the nothing-to-pin checks and before `has_workflow`; limits or unreadable dirs return
  `skip(envlimit.skip_reason(limits, unreadable), **where)`.
- `appship_joint._candidates`: `envlimit.local_limits(gitops, "staging")` once before the loop; with limits, each repo that
  passes the pinned/gate check is skipped with `skip_reason(limits)` before any registry lookup.
- No change to `staging_deploy.py`, `smoke.follow_staging` or `_staging`: their existing skip paths print the row and do not
  count it as red.

**Done when:** the acceptance tests for AC-190.4 pass (component ship deploy, `instance verify dev` follow, system ship), and
the existing staging, appship and smoke tests still pass.

## t4 — Prompts - product-manager limit rule, spec-format field, approval summaries, /instance:promote rule

**Files:** plugins/svc/agents/product-manager.md, plugins/svc/skills/spec-format/references/spec.md,
plugins/component/commands/spec.md, plugins/system/commands/spec.md, plugins/instance/commands/promote.md, the five matching
`docs/rules/plugins/**.yml` register files, the four `plugin.json` files, .claude-plugin/marketplace.json
**Covers:** AC-190.5, AC-190.6, AC-190.7
**Goal:** the agents write, show and respect the field: the product-manager never invents a limit, the approval summaries show
it, and `/instance:promote` states the rule, the refusal, the dry run and the person-only override.

**Implementation notes:**
- product-manager: one rule with its reason: a suggested answer or assumption never keeps the feature out of an environment
  the request asked for (e.g. "reachable in every environment"), because promotion refuses what the field leaves out; a
  question whose answer would limit names it as `limits to <envs>`; a limit that is taken becomes `environments: [<envs>]` in
  the front matter. Register entry: next free `R<n>`, class `experience`, source `#688`.
- spec-format `spec.md`: the optional front-matter line `environments: [dev]` with a comment saying what it does.
- `/component:spec` F and `/system:spec` F: the summary includes the `Environment limit:` line `cplat spec show <spec_id>`
  prints when the spec has the field (A prints `cplat spec approve`'s output, which already carries it).
- `/instance:promote`: one paragraph "Environment limit (spec 190)": the rule (a `building`/`done` spec's `environments:`
  without the target refuses staging and prod, automatic staging included), the refusal and `fix:` line, the dry run's
  `REFUSED:` lines, the override `--accept-environment-limit "<reason>"` and its recorded line, and a sentence marked
  `**Hard rule:**`: never pass it without the user's explicit yes and reason, and an unattended run stops and asks, because
  it lets a system run where an approved spec forbids it. Register: class `hard`, `hard: prod-needs-explicit-confirm`,
  source spec 190.
- Every new sentence carries a reason clause; run `cplat platform rules check`. Rule 6 of `docs/rules/README.md`: the changed
  prompt files may not grow in total, so tighten wording in the same files to pay for the new sentences; only if that is not
  possible, follow "Raise the baseline" there.
- Bump the minor version of svc, component, system and instance in `plugin.json` and `marketplace.json`.

**Done when:** the acceptance tests for the prompt parts of AC-190.5, AC-190.6 and AC-190.7 pass, `cplat platform rules
check` passes and `devbox run validate` passes.

## t5 — Benchmark workflow spec-environments

**Files:** scripts/cplat/runs_bench.py, scripts/cplat/benchmark/tasks.json, scripts/cplat/runs.py
**Covers:** AC-190.6
**Goal:** a benchmark case that runs `/component:spec` on a request for every environment and fails when the spec suggests or
carries a limit.

**Implementation notes:**
- `tasks.json`: workflow `spec-environments` as in design.md; the prompt asks for one access-related change on the sample repo
  and names dev, staging and prod as the environments it must work in.
- `runs_bench.py`: `EXPECTED["spec-environments"] = "spec"`, `environments_kept(keep, clone)` as in design.md (git through
  `run`, which tests replace; front matter through `spec.load`), dispatched from `result`; add the workflow to the argparse
  choices.
- `runs.py`: add it to the `benchmark` usage line of the docstring.

**Done when:** the acceptance tests for the benchmark part of AC-190.6 pass and the existing benchmark tests still pass.

## t6 — Promotion guide and changelog fragment

**Files:** site/src/content/docs/scenarios/promote-safely.md, docs/unattended-delivery.md,
docs/changelog.d/190-promotion-respects-an-environment-limit.added.md
**Covers:** AC-190.7
**Goal:** the promotion guide states the environment-limit rule, the refusal, the dry-run output and the override; the
unattended-delivery guide says automatic staging skips on a limit.

**Implementation notes:**
- promote-safely.md: a short section on the field, what is refused (staging and prod, automatic staging too), the
  `environment limit: …` refusal and `fix:` line, the dry run's `REFUSED:` lines, the override and its recorded line, and that
  only a person decides it. Guides carry no spec numbers (check-docs).
- unattended-delivery.md "Deploy gate": one sentence that a limit skips the staging pin with
  `not promoted: environment limit <spec_id> allows <envs>`, not red.
- Changelog fragment in the format of `docs/changelog.d/README.md`.

**Done when:** the acceptance tests for the guide part of AC-190.7 pass and `devbox run quality` (docs and link checks) passes.
