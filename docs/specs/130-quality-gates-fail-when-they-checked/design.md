# Design — 130 Quality gates fail when they checked nothing

## Decisions

1. **Count from the tool's own report, decide in one helper.** Each covered gate counts what it checked from what the tool reports
   (JUnit XML, `go test -v` result lines, Vitest's JSON report, kubeconform's summary, the rendered file set, `git ls-files`) and fails
   on 0. Shell recipes go through one helper, `scripts/gate.sh`, so the message format and the "runner broke vs. ran nothing" rule exist
   once. ADR: [073](../../adr/074-a-gate-that-checked-nothing-fails.md).
2. **One byte-identical `scripts/gate.sh` in all 7 templates.** Source: `templates/gitops-app/scripts/gate.sh`; copies in the other six
   templates, kept equal by `scripts/sync-template-copies.py` (already run by CI with `--check`). One file to review, one file the
   platform test targets. It holds the counting for all four test runners even though each template uses one; that costs ~30 lines and
   saves six variants.
3. **pytest and Maven share one JUnit parser.** pytest gets `--junitxml=<tmp>` appended by the helper; Maven already writes surefire /
   failsafe XML. No pytest plugin, no change to `pyproject.toml` or `pom.xml` (both `_skip_if_exists`, they would never reach existing
   repos).
4. **Go runs with `-v`.** The `--- PASS:` / `--- FAIL:` lines are the count (skips are `--- SKIP:` and do not count). `-json` would
   need a converter program to keep the output readable; `-v` needs nothing. Cached runs replay the same lines. failsum's Go parser
   (ADR-071) keys on `--- FAIL:` lines, which `-v` keeps.
5. **Vitest writes a JSON report only under the gate.** `vitest.config.mts` (platform-owned, re-applied by updates) adds the `json`
   reporter when `VITEST_GATE_REPORT` is set; the helper sets it. `package.json` (project-owned) is not touched.
6. **The renderers count compared files themselves** (`render.py --check` in gitops-app, its copy `system_render.py`, and the
   cluster-gitops `render.py`). The gate name comes from `GATE_NAME` (default `render-check`), because the cluster `render.py` accepts
   exactly one flag; recipes that run the check inside another gate set it (`GATE_NAME=test-fast`, `GATE_NAME=validate`).
7. **gitops-app `validate` stops at the first failing step.** Today `A && B && C && for…; for… && D` runs the kubeconform loop and the
   policy check even after the render check failed, and its exit is the policy check's: a red render check can end green. Counting
   resources needs a well-formed chain, so every step gets `|| exit 1`. The recipe stays inline (existing spec 098 / 125 tests read it).
8. **The #278 line in cluster-gitops `validate` becomes the AC-130.1 line** (AC-130.1 allows one line on stderr). Exit and
   kubeconform's printed summary are unchanged.
9. **Composite recipes are unchanged.** `ci`, `quality`, `security` already chain with `&&` (AC-130.11); the tasks verify, not edit.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/gate.sh` (+ 6 copies) | message line; `files`, `tests` checks | new |
| `scripts/sync-template-copies.py` | also keeps the 6 `gate.sh` copies equal | changed |
| `templates/{service-python,library-python,service-go,service-java,web-nextjs}/devbox.json[.jinja]` | `test`, `test-fast`, `secrets-scan` through `gate.sh` | changed |
| `templates/web-nextjs/vitest.config.mts` | JSON reporter under `VITEST_GATE_REPORT` | changed |
| `templates/gitops-app/devbox.json` | `validate` counts resources and stops on failure; `GATE_NAME`; `secrets-scan` | changed |
| `templates/cluster-gitops/devbox.json` | AC line in `validate`; `GATE_NAME`; `secrets-scan` | changed |
| `templates/gitops-app/scripts/render.py`, `templates/cluster-gitops/scripts/{render,system_render}.py` | `--check` fails on 0 compared files | changed |
| `.github/workflows/ci.yml` (platform) | template smoke jobs run the real `test`/`test-fast` recipes, plus one empty-tests run | changed |
| `CONTRIBUTING.md`, `docs/templates.md`, `docs/CHANGELOG.md`, `docs/adr/README.md` | the rule, the pointer, the behaviour change | changed |

## Contract

### The line (AC-130.1)

Exactly one line on **stderr**, nothing else added to stderr by the check:

```
<gate>: checked nothing: <what> - <fix>
```

| Gate (recipe) | Template(s) | `<what>` | `<fix>` (exact text) |
|---|---|---|---|
| `test`, `test-fast` | service-python, library-python, service-go, service-java, web-nextjs | `0 tests ran` | `add at least one test` |
| `validate` | gitops-app | `0 resources` | ``run `devbox run render` and check that the system has components`` |
| `validate` | cluster-gitops | `0 resources` | ``run `devbox run render` and check that cluster/kustomization.yaml lists resources`` |
| `render-check` (or `GATE_NAME`) | gitops-app | `0 files compared` | ``run `devbox run render` and check that applications/<system>/system.yaml exists`` |
| `render-check` (or `GATE_NAME`) | cluster-gitops | `0 files compared` | ``run `devbox run render` and check cluster.yaml`` |
| `secrets-scan` | all 7 | `0 files to scan` | ``commit at least one file that the scan does not exclude (`git add`)`` |

`<gate>` is the recipe that ran the check: `test` or `test-fast` for the test runners; for the render check `GATE_NAME`, default
`render-check`, set to `test-fast` by gitops-app/cluster-gitops `test-fast` and to `validate` by their `validate`.

### `scripts/gate.sh` (bash, `bash scripts/gate.sh …`)

```
gate.sh nothing <gate> <what> <fix>
    prints the line to stderr, exit 1.

gate.sh files <gate> <pathspec>...
    exit 0 when `git ls-files -- <pathspec>...` lists at least one file;
    `git ls-files` itself fails (not a git repo): git's message, exit git's code, no line;
    else `nothing <gate> "0 files to scan" "<fix>"` (exit 1).

gate.sh tests <gate> <runner> -- <command> [args...]
    runner: pytest | maven | go | vitest
    runs <command> [args...] (stdout/stderr shown as they are produced), then counts the tests that ran
    (passed + failed; skipped, xfail and todo do not count) and exits:
      ran > 0                                    -> exit <command's exit>
      ran = 0 and the runner reported "no tests" -> the line (`0 tests ran`, `add at least one test`),
                                                    exit <command's exit> if non-zero, else 1
      ran = 0 and the runner failed otherwise    -> exit <command's exit>, no line (a broken build is not "add a test")
    any other usage: a usage line on stderr, exit 2.
```

Per runner (a missing report always counts 0):

| runner | before | appended / env | count | "no tests" means |
|---|---|---|---|---|
| `pytest` | — | appends `--junitxml=<tmp>/junit.xml` after all args | sum over `<testsuite …>` elements of `tests` − `skipped` | exit 0 or 5 (5 is passed through) |
| `maven` | `rm -rf target/surefire-reports target/failsafe-reports` | — | same JUnit sum over `target/{surefire,failsafe}-reports/TEST-*.xml` | exit 0 |
| `go` | — | (the recipe passes `-v`) | lines matching `^[[:space:]]*--- (PASS\|FAIL):` in the command's stdout | exit 0 |
| `vitest` | — | env `VITEST_GATE_REPORT=<tmp>/vitest.json` (always overwritten) | `numPassedTests` + `numFailedTests` from the report | exit 0, or the output contains `No test files found` |

Implementation constraints: bash 3.2 compatible (macOS); only `git`, `grep`, `sed`, `tee`, `mktemp` and the runner itself (no `jq`,
`node`, `python` for parsing: no new tool dependencies, and stub tests can fake just the runner); temp files removed on exit; extra
args from `devbox run test-fast -- <targets>` (`cplat validate run`, mapped targets) reach the runner unchanged. The file is rendered by
Jinja in the two Python templates (they render every file), so it must contain no `{{`, `{%` or `{#` (no `${#var}`): the rendered copy
must be byte-identical to the source. Executable bit not required (always called through `bash`).

### Recipes (target text; `<flags>` = the unchanged `--baseline … --disable-filter …` flags)

| Template | `test` | `test-fast` |
|---|---|---|
| service-python | `SMOKE_BASE_URL= bash scripts/gate.sh tests test pytest -- uv run python -m pytest tests/ -p scripts.smoke_pytest --cov={{ module_name }} --cov-report=term-missing` | `SMOKE_BASE_URL= bash scripts/gate.sh tests test-fast pytest -- uv run python -m pytest tests/ -p scripts.smoke_pytest -q --tb=line` |
| library-python | `bash scripts/gate.sh tests test pytest -- uv run pytest tests/ --cov={{ module_name }} --cov-report=term-missing` | `bash scripts/gate.sh tests test-fast pytest -- uv run pytest tests/ -q --tb=line` |
| service-go | `SMOKE_BASE_URL= bash scripts/gate.sh tests test go -- go test -v -race -cover ./...` | `SMOKE_BASE_URL= bash scripts/gate.sh tests test-fast go -- go test -v ./...` |
| service-java | `SMOKE_BASE_URL= bash scripts/gate.sh tests test maven -- mvn -B verify` | `SMOKE_BASE_URL= bash scripts/gate.sh tests test-fast maven -- mvn -B test` |
| web-nextjs | `SMOKE_BASE_URL= bash scripts/gate.sh tests test vitest -- pnpm test` | `SMOKE_BASE_URL= bash scripts/gate.sh tests test-fast vitest -- pnpm test:fast` |

`secrets-scan` in every template: `bash scripts/gate.sh files secrets-scan <pathspec> && git ls-files -z <pathspec> | xargs -0 detect-secrets-hook <flags>`,
with the template's current pathspec (`':!*.lock'`, `':!go.sum'`, `':!pnpm-lock.yaml'`, or none — then `gate.sh files secrets-scan .`).
`detect-secrets-hook <flags>` stays literally in the recipe (`tests/cplat/test_ci_templates.py` reads the flags after it).
No recipe passes `-DskipTests`, `--passWithNoTests` or any skip switch.

gitops-app `validate` (one inline recipe, shape):

```
GATE_NAME=validate uv run scripts/render.py --check || exit 1; uv run scripts/plan.py validate || exit 1;
uv run scripts/check-k8s-labels.py . || exit 1; n=0;
for d in <same globs>; do [ -f "$d/kustomization.yaml" ] || continue; echo "kustomize build $d";
  out=$(kustomize build "$d") || exit 1; n=$((n + <count of '^kind:' lines in $out>)); done;
for f in <same globs>; do [ -f "$f" ] || continue;
  out=$(kubeconform -strict -ignore-missing-schemas ${SERVICE_CRD_SKIP:+…} -schema-location default -schema-location '…' -summary "$f"); rc=$?;
  printf '%s\n' "$out"; [ $rc -eq 0 ] || exit 1; n=$((n + <N of '^Summary: N resource'>)); done;
[ "$n" -gt 0 ] || { bash scripts/gate.sh nothing validate '0 resources' '<fix>'; exit 1; };
bash scripts/check-policies.sh
```

The `kubeconform -strict … -summary "$f"` text stays contiguous and unchanged (spec 098 tests extract it by regex); `render.py
--check`, `plan.py validate`, `check-k8s-labels.py`, `kustomize build`, `check-policies.sh` stay in the recipe.
gitops-app `test-fast`: `GATE_NAME=test-fast uv run scripts/render.py --check && uv run scripts/plan.py validate`; `render-check` unchanged.

cluster-gitops `validate`: unchanged except `GATE_NAME=validate uv run scripts/render.py --check` at the start and the #278 `echo
'validate: kubeconform checked 0 resources' >&2` replaced by `bash scripts/gate.sh nothing validate '0 resources' '<fix>'` (its exit
ignored, `rc=1` as before). `kustomize build cluster > "$dir/cluster.yaml"` stays (spec 125 test regex). `test-fast`:
`GATE_NAME=test-fast uv run scripts/render.py --check`.

### `render.py --check` (gitops-app, `system_render.py`, cluster-gitops)

- compared = the number of rendered paths the check compared (gitops-app: every path of every app's render plus the operator files;
  cluster-gitops: `len(files)`).
- `--check` with compared = 0, and gitops-app `--check` with no `applications/*/system.yaml`: the line with `0 files compared`, exit 1,
  no `OK: up to date`. Render errors and drift keep their current messages and exit 1.
- Write mode (no flag) and the other flags are unchanged, including `ERROR: no applications/*/system.yaml found`.

### `vitest.config.mts`

When `process.env.VITEST_GATE_REPORT` is set: `test.reporters = ["default", "json"]` and `test.outputFile = { json: <that path> }`;
otherwise reporters are left at Vitest's default. No `passWithNoTests` key.

### Platform test (written by the testers, AC-130.14)

`tests/cplat/test_130_empty_gates.py`: one coverage table `template → covered gates`; it asserts the table's templates equal the
templates in `shapes.yml`, renders each template once (shared renders, spec 112), and runs each covered recipe with `sh -c "<recipe>"`
in the rendered repo against empty input, with stub runners first on `PATH` (`uv`, `go`, `mvn`, `pnpm`, `kustomize`, `kubeconform`,
`detect-secrets-hook`; `git`, `bash`, `grep`, `sed` real). Empty input: a stub runner that reports no tests or only skipped tests;
stub kustomize/kubeconform that report nothing / `Summary: 0 resource…`; a git repo with an empty index; a render with no system.
Asserts exit ≠ 0 and the exact line on stderr. The docs point to this file (AC-130.15).

## Risks

- **Runner report formats.** Stub tests cannot prove that Vitest 5 prints `No test files found` or writes the JSON report, or that
  pytest's JUnit has `skipped`. The platform smoke jobs (plan t4) run the real recipes with the real runners, once with the shipped
  tests (must pass, AC-130.12) and once with the tests removed (must fail with the line).
- **Template smoke and e2e cost.** All seven templates change, so every smoke job runs, and e2e runs for gitops-app/cluster-gitops
  changes. The render.py change is a few lines in `main()`.
- **Updates.** Every changed file is platform-owned (not in any `_skip_if_exists`): `devbox.json` (template recipes win in the merge,
  spec 060), `scripts/gate.sh` (new file, added by the update), `scripts/render.py`, `vitest.config.mts`. A repo whose own
  `package.json` test script sets `--reporter` overrides the config reporters; the report is then missing and the gate fails with the
  line when the run was otherwise green (conservative, named in the changelog).
