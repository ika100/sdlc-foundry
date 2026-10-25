# Design — 103 Validation runs what a change can affect

## Decisions

- **One deterministic planner in cplat, `cplat validate`.** The plan is pure code over three inputs: the diff
  (`git diff --name-only <base>...HEAD` plus the working tree and untracked files), the repo's shape entry in
  `shapes.yml`, and the declared mapping (below). No model decides anything; an agent's risk level is an input that
  can only add checks (AC-103.5). ADR: [044](../../adr/044-change-aware-validation-in-the-inner-loop.md).
- **Checks are the repo's own devbox scripts.** The planner lists the checks of `devbox run ci` by name: `lint`,
  `typecheck` (when present), `test` (unit, `test-fast` when present), `acceptance` (the criterion-tagged tests),
  `security`, `image` (`image-build`, when a Dockerfile exists), `ci-extra` (when present). A check the planner does
  not know is always `run` (`no rule`).
- **Rules, first match decides, every check gets one** (AC-103.1):
  1. `full` — `--full`, or `validation: full` in `.platform-settings.yml` (AC-103.9): everything `run`.
  2. `mandatory:<category>` (AC-103.3): a changed Dockerfile, dependency manifest or lock file (`pyproject.toml`,
     `uv.lock`, `package.json`, `pnpm-lock.yaml`, `package-lock.json`, `pom.xml`, `go.mod`, `go.sum`), a CI workflow
     (`.github/workflows/**`), secrets or auth configuration (`.secrets.baseline.json`, `**/auth*`, `**/security*`,
     `**/*secret*`), a spec (`docs/specs/**`) or an acceptance test (a test file naming an `AC-` id) → `test`,
     `acceptance` and `security` run in full. Per shape (new `validation.mandatory` globs in `shapes.yml`): service —
     the API contract (`**/openapi*`, `**/api/**`, `**/routes*`, `**/schemas*`) and migrations (`migrations/**`,
     `**/migrations/**`); gitops-app — `environments/**`, `apps/**`, `base/**`; web — `app/**/page.*`,
     `app/**/route.*`, `pages/**`, `next.config.*`, `tsconfig*.json`, `vite*.config.*`.
  3. `docs-only` (AC-103.2): every changed file is documentation (`*.md`, `docs/**` except `docs/specs/**`,
     `LICENSE`) → `lint` runs, `test`, `acceptance`, `image` are `skipped`, `security` runs (secret scan).
  4. `mapped` (AC-103.2): every changed source file maps to tests → `acceptance` runs the test files that name the
     criteria of the plan tasks whose `files` contain the changed file (via `cplat spec trace`), `test` runs the unit
     tests of the component (`src/<pkg>/<mod>.py` → `tests/**/test_<mod>*.py`; web `foo.ts` → `**/foo.test.*`), and
     changed test files themselves. `lint`, `typecheck` and `security` always run.
  5. `no rule` (AC-103.4): a file nothing maps, an unreadable diff or missing plan/trace data → the full default set.
- **Only shapes with a selector select.** `shapes.yml` gains `validation.selector`: `pytest` (service-python,
  library-python) and `vitest` (web-nextjs) run a file list; other shapes have none, so rule 4 becomes `no rule`
  there and everything runs. Nothing else changes for them.
- **Reuse** (AC-103.6): a check that passed records evidence in `<git common dir>/cplat-evidence/<check>.json`:
  `{inputs, result, run_id, at}`, where `inputs` is the sha256 over the check's command, the content of the files it
  reads (the selected test files and the changed source files, or every tracked file for a full run), the
  configuration and lock files of rule 2, and `devbox.lock`. Equal hash and `passed` → `reused`, naming the run;
  anything else runs. The folder is local, never pushed, never read from another clone.
- **Run and record** (AC-103.7): `cplat validate run` executes the plan with `cplat quiet`-style output (one line per
  check, tail and log on red), writes evidence for passes, and sets the `validation` section on the current run
  (`runs.current`): `{"base", "checks": [{name, decision, rule, reason, from_run?}], "counts": {run, reused, skipped},
  "misses": []}`. No logs. `cplat runs report` prints counts per rule and misses per rule.
- **Inner loop only** (AC-103.8): build Phase 2 (after coders) and Phase 3 fix rounds, and ship's CI fix rounds, call
  `cplat validate run` instead of `cplat quiet test-fast`. The final gate is unchanged: `cplat quiet ci` in build
  Phase 3's last pass and `ship.run_ci` before every push run the whole `devbox run ci`; PR CI is untouched.
- **Misses** (AC-103.10): the final gate calls `cplat validate final --check <name> passed|failed` (build) or
  `ship.run_ci` does it in code: a failed check that the last loop plan `skipped` or `reused` appends
  `{check, rule}` to `validation.misses`.
- **Benchmark** (AC-103.11): `cplat runs benchmark <wf> --compare-validation` runs the task twice (on, then `--full`
  through `CPLAT_VALIDATION=full`), reports duration, tokens, cost and checks per run, writes both into the
  benchmark record's `validation_compare`, and exits 1 if a rule-required check did not run or pass in the
  change-aware run. No savings target.

## Contract

```
cplat validate plan [--base REF] [--full] [--risk low|medium|high] [--json]   the plan; exit 0
cplat validate run  [--base REF] [--full] [--risk …]                          run it; exit 0 green, 1 red
cplat validate final --check NAME passed|failed                               record a final-gate result (misses)
cplat runs benchmark <wf> --compare-validation
shapes.yml: validation: {selector: pytest|vitest|null, mandatory: {<category>: [globs]}}
.platform-settings.yml: validation: full | selective (default selective)
```

Plan JSON: `{"base", "files": [...], "checks": [{"name", "decision": "run|reused|skipped", "rule", "reason",
"targets": [paths] | null, "from_run": id | null}], "risk": {"level", "added": [...], "note"}}`.
