# Design — 110 A product's repos agree on the contract between them

## Decisions

- **The rules and the error contract are YAML blocks inside the plan's contract** (`### Rules` and `### Errors`, a
  fenced ```` ```yaml ```` block each), not new front-matter keys: they sit next to the prose they belong to, the plan
  stays readable, and `check_contract` already finds the contract in the plan body or in the spec's `design.md` (design
  wins, as today). ADR: [ADR-118](../../adr/118-shared-input-rules-live-in-the-plan-contract.md) (created by plan task t8 with
  `cplat adr add`).
- **One parser, in the gitops-app template's `scripts/plan.py`.** plan-check, the pin check (`import plan`, a sibling
  script, as `pin.py` imports `render`) and `cplat spec new --from-plan` all use it. cplat runs it as a subprocess
  (`plan.py contract`, contract 2) instead of importing it, because `plan.py` registers a global YAML string representer
  that would change cplat's own YAML output. cplat always runs the platform's copy
  (`core.PLATFORM_ROOT/templates/gitops-app/scripts/plan.py`), so an older gitops-app checkout still gets a copy.
  The parser stays inside `plan.py` (no new module), because several test suites copy `plan.py` alone into a temp repo.
- **A repo's copy is `contract/<plan_id>.json`**, JSON so that Python (stdlib) and TypeScript (`JSON.parse`) read it with
  no dependency; one file per plan, because a repo takes part in several plans over time and the pin check compares
  each with its own plan.
- **Repo-local checks live in template-owned engine files plus a thin, project-owned test file and adapter.**
  `tests/**` is `_skip_if_exists` in both templates, so the engine that must follow platform updates goes to
  `scripts/contract_pytest.py` (service-python, loaded with `-p` like `scripts.smoke_pytest`) and
  `lib/contract/engine.ts` (web-nextjs); Copier still creates the missing project-owned files on update.
  The repo supplies only what no contract can know: a valid base body per endpoint, how to send a request
  (path parameters, auth) and how its form shows errors.
- **The checks run inside `devbox run test` / `test-fast`**, so the repo's existing `test` CI job turns the PR red
  (AC-110.8); the provider check calls the app in-process (FastAPI `TestClient`), the consumer check runs the form in
  jsdom: no network, no other repo.
- **The pin check is a new gitops-app CI job `contract-pins`** that compares the image tags a PR changes (pin-dev PRs,
  the system ship's compose PR, staging pins) against every plan that is not `abandoned`. It reads the copy at the pinned
  commit through the GitHub contents API with the same token and client pattern as `check-service-crds.py` (spec 098).
  Draft plans are checked too, as AC-110.9 names no status.
- **Rules apply to JSON request bodies of `POST`, `PUT` and `PATCH` endpoints**; a field is a body key, dots address
  nested objects (`address.city`). Query parameters and responses beyond the error contract are out of scope
  (Non-goals).
- **The error block is required only when the plan has at least one rule**: a plan that states `No shared rules: …`
  has no rule violation to describe, so its `### Errors` may stay prose (spec 053 still requires the heading).
- **A rule may carry its own `status`**; otherwise `errors.status` applies; a rule with neither is refused (AC-110.2).
- **"Product context" in AC-110.4 is the repo spec's existing `## System context` section** (the 5.x name of the same
  section that `cplat spec new --from-plan` writes); the rules go into a new `### Contract rules` part of it.
- Decimal value rules state their `step` (the distance "just past" the limit); integers default to step 1. YAML loses a
  value's written precision, so the step cannot be derived from it.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/plan.py` | parse and check `### Rules` and the `### Errors` block; finished-plan warning; `contract` subcommand | changed |
| `templates/gitops-app/scripts/check-contract-pins.py` | compare the pinned commit's copies with the plans | new |
| `templates/gitops-app/.github/workflows/ci.yml`, `devbox.json` | job `contract-pins`, recipe `contract-pins` | changed |
| `scripts/cplat/contract_copy.py` | run `plan.py contract`, add the commit, write or remove `contract/<plan_id>.json`, render the `### Contract rules` part | new |
| `scripts/cplat/spec.py` | `new_from_plan` calls `contract_copy` | changed |
| `templates/service-python/scripts/contract_pytest.py` | provider cases, assertions, default fixtures | new |
| `templates/service-python/tests/test_contract.py` | one parametrized test over the cases | new (project-owned) |
| `templates/web-nextjs/lib/contract/engine.ts` | consumer cases, error-response cases, comparison | new |
| `templates/web-nextjs/tests/contract.test.ts`, `tests/contract/adapter.ts` | the test file and the repo's adapter | new (project-owned) |
| `plugins/system/agents/planner.md`, `docs/adr/011-…` amendment | the format and the worked example (AC-110.11) | changed |

## Contract

### 1. The plan's contract (AC-110.1, AC-110.2, AC-110.3, AC-110.11)

Worked example (the one the planner text and the ADR-011 amendment show):

````markdown
## Contract

`POST /todos` creates a todo; `PATCH /todos/{id}` changes it. …

### Rules

```yaml
rules:
  - id: title-max
    endpoint: POST /todos
    field: title
    kind: max_length
    value: 200
    provider: todo-api
    consumers: [todo-web]
  - id: title-required
    endpoint: POST /todos
    field: title
    kind: required
    value: true
    provider: todo-api
    consumers: [todo-web]
  - id: status-values
    endpoint: PATCH /todos/{id}
    field: status
    kind: allowed
    value: [open, done]
    provider: todo-api
    consumers: [todo-web]
```

Titles must not be blank after trimming (prose: patterns and formats are not checked).

### Errors

```yaml
errors:
  status: 422
  body:
    list: errors        # the body is {"errors": [ {...}, ... ]}; omit `list` when the body is one error object
    field: field        # key naming the field that failed
    rule: rule          # key naming the rule id
    message: message    # key holding the message to show
  unlisted:
    message: "Something went wrong. Please try again."
```

Any other non-2xx: the UI shows the unlisted message above the form and keeps the input.

### Timeouts

…
````

A plan with no shared rules writes, under `### Rules`, one line: `No shared rules: <reason>` (reason non-empty).

Rule entry keys:

| Key | Required | Value |
|---|---|---|
| `id` | yes | `[a-z0-9][a-z0-9-]*`, unique in the plan |
| `endpoint` | yes | `POST\|PUT\|PATCH /<path>` |
| `field` | yes | non-empty; dots address nested objects |
| `kind` | yes | `required`, `min_length`, `max_length`, `min_value`, `max_value`, `allowed` (the only ones) |
| `value` | yes | `required`: `true`; `min_length`/`max_length`: integer ≥ 0 (`max_length` ≥ 1); `min_value`/`max_value`: number (not a boolean); `allowed`: non-empty list of distinct strings or numbers |
| `step` | for decimal values | positive number; value kinds only; default 1 for an integer `value` |
| `status` | no | integer 400–599; overrides `errors.status` for this rule |
| `provider` | yes | a repo id of the plan |
| `consumers` | yes | non-empty list of repo ids of the plan, not containing the provider |

Error block keys: `status` (integer 400–599, or absent when every rule has its own), `body.field`, `body.rule`,
`body.message` (non-empty strings), optional `body.list` (non-empty string), `unlisted.message` (non-empty string).

When the rules apply: `spec:` is set and the plan has two or more repos (the condition of spec 053). plan-check messages
(each is one `ERROR:` line; `<id>` is the rule id, `#<n>` the 1-based position when the id is missing):

- `the contract has no \`### Rules\` section: add \`### Rules\` under \`## Contract\` with a yaml block \`rules:\` of the shared input rules, or the line \`No shared rules: <reason>\` (spec 110)`
- `### Rules has neither a yaml block with \`rules:\` nor the line \`No shared rules: <reason>\` (spec 110)` (also for a
  `No shared rules:` line with no reason, and for YAML that does not parse: then the parser message is appended)
- `rule #<n>: missing id` · `rule <id>: duplicate id`
- `rule <id>: missing <key>` for `endpoint`, `field`, `kind`, `provider`, `consumers`
- `rule <id>: no concrete value` (missing, `null`, empty list, or of the wrong type for its kind)
- `rule <id>: unknown kind '<kind>' (allowed: allowed, max_length, max_value, min_length, min_value, required)`
- `rule <id>: endpoint must be 'POST|PUT|PATCH /path', got '<endpoint>'`
- `rule <id>: a decimal value needs \`step\``
- `rule <id>: provider '<repo>' is not a repo of this plan` · `rule <id>: consumer '<repo>' is not a repo of this plan` ·
  `rule <id>: the provider '<repo>' is also a consumer`
- `### Errors has no yaml block with \`errors:\`: state the status code, the body fields (field, rule, message) and \`unlisted.message\` (spec 110)`
- `### Errors: \`body.<key>\` is missing` (`field`, `rule`, `message`) · `### Errors: \`unlisted.message\` is missing` ·
  `### Errors: status must be a code 400-599`
- `rule <id>: no status code for a violation: add \`status:\` to the \`errors:\` block or to the rule (spec 110)`

AC-110.3: for a `completed` or `abandoned` plan every spec 110 finding is part of the existing finished-plan warning
(spec 061), whose list of missing parts gains `no \`### Rules\``; exit code 0. Active plans fail as above.

### 2. `plan.py contract <plan-file> <repo-id>` (AC-110.4)

Reads the plan at `<plan-file>` (any path; the spec dir is `<plan-file>/../../specs/<spec>`), prints one JSON document
on stdout (keys sorted, indent 2):

```json
{"plan_id": "003-todos", "gitops_app": "ika100/todo", "repo": "todo-web",
 "rules": [ <rule objects, see 3, only those where repo-id is provider or consumer, sorted by id> ],
 "errors": <the errors object, or null when rules is empty>}
```

Exit 0 also when the plan has no `### Rules` block, says `No shared rules`, has no `spec:` or the repo takes part in no
rule (`"rules": []`). Exit 1 with the plan-check messages of section 1 on stderr when the block exists and is invalid;
exit 1 with `ERROR: unknown repo id '<repo-id>'` for a repo not in the plan; exit 2 on wrong usage.

### 3. The copy `contract/<plan_id>.json` in a component repo (AC-110.4, AC-110.10)

Written by `cplat spec new --from-plan <plan> <repo-id>` (and so by `/system:ship`'s `repo_spec_of`, which calls
`new_from_plan`): the document of 2 plus `commit` (`git -C <dir of the plan> rev-parse HEAD`, 40 hex), keys sorted,
indent 2, trailing newline. Each rule object:

```json
{"id": "title-max", "endpoint": "POST /todos", "field": "title", "kind": "max_length", "value": 200,
 "status": 422, "provider": "todo-api", "consumers": ["todo-web"], "role": "consumer"}
```

`status` is resolved (rule's own, else `errors.status`); `step` is present for `min_value`/`max_value` only (resolved,
default 1); `role` is `provider` or `consumer` for this repo. `errors` is the error object as written in the plan
(`list` absent when not written).

- A repo that takes part in no rule of the plan gets no copy; an existing `contract/<plan_id>.json` is deleted, so a
  stale copy never survives a contract change.
- Re-running overwrites the copy with the plan's current values (AC-110.10); the repo's contract check then fails until
  the code follows.
- Errors: `plan.py contract` exit 1 → `PlatformError("the contract of <plan_id> does not pass plan-check: <first
  message>", hint="fix docs/plan/<plan_id>.md in the gitops-app repo (devbox run plan-check)")`, and no spec is written.
  No commit readable while rules exist → `PlatformError("cannot read the gitops-app commit of <plan>: the plan must be
  in a git checkout")`.
- The CLI prints, after the spec line: `contract copy: contract/<plan_id>.json (<n> rules, <gitops_app>@<sha7>)` or
  `contract copy: none (<repo-id> takes part in no rule of <plan_id>)`.

The repo spec's `## System context` gains, after `### Contract`, when the repo takes part in a rule:

```markdown
### Contract rules

Copy: `contract/<plan_id>.json`, from plan `<plan_id>` at `<gitops_app>@<sha7>`. The repo's contract check reads it.

| Rule | Endpoint | Field | Kind | Value | Status | Role |
|---|---|---|---|---|---|---|
| title-max | POST /todos | title | max_length | 200 | 422 | consumer |

Errors: status <status>; body <`<list>[]` of objects | one object> with `<field>`, `<rule>`, `<message>`; responses the
contract does not list: show "<unlisted.message>".
```

### 4. Provider check, service-python (AC-110.5, AC-110.8)

`scripts/contract_pytest.py` (pytest plugin, added as `-p scripts.contract_pytest` to the `test` and `test-fast`
recipes) offers `contract_cases(root=Path.cwd()) -> list[Case]` (every rule with `role: provider` in every
`contract/*.json`), `check_case(case, send, base) -> None` and two default fixtures a repo overrides in
`tests/conftest.py`:

```python
@pytest.fixture
def contract_send() -> Callable[[str, dict], tuple[int, Any]]:   # (endpoint "POST /todos", body) -> (status, json or text)
    # default: TestClient(<module>.main.app); an endpoint with a {param} fails: "override contract_send in tests/conftest.py"
@pytest.fixture
def contract_base() -> Callable[[str], dict]:                    # endpoint -> a valid request body; default {}
```

`tests/test_contract.py`: `@pytest.mark.parametrize("case", contract_cases(), ids=str)` →
`check_case(case, contract_send, contract_base)`. No copy → no cases (pytest reports the empty parameter set as skipped).

Cases per rule (body = `contract_base(endpoint)` with the field set or removed), id `<plan_id>:<rule_id>:<case>`:

| Kind | Accepted (2xx) | Rejected |
|---|---|---|
| `required` | `present`: the base value, else a value derived from the field's other rules (first allowed value, `"x"` × max(min_length, 1), the min value, else `"x"`) | `missing`: field removed |
| `min_length` n | `at-limit`: `"x"` × n | `past-limit`: `"x"` × (n − 1); no case when n = 0 |
| `max_length` n | `at-limit`: `"x"` × n | `past-limit`: `"x"` × (n + 1) |
| `min_value` v | `at-limit`: v | `past-limit`: v − step |
| `max_value` v | `at-limit`: v | `past-limit`: v + step |
| `allowed` | `allowed=<v>` for every value | `not-allowed`: strings: first value + `-not-allowed` (suffix repeated until not in the set); numbers: max + 1 |

A rejection passes when the status equals the rule's `status` and the error object (`body[list]` must be a list holding
it, or the body itself without `list`) has `body.field` key = the rule's field, `body.rule` key = the rule id and a
non-empty string under `body.message`. Values stepped by a decimal step are rounded to the step's decimals.

Failure message (pytest assertion text, one per case):
`contract <plan_id> rule <rule_id> field <field>: <case> (<value or "field removed">) on <endpoint>: expected <accepted (2xx) | rejected <status> with <field-key>=<field> <rule-key>=<rule_id> and a message>, got <status> <body, at most 200 chars>`.

### 5. Consumer check, web-nextjs (AC-110.6, AC-110.7, AC-110.8)

`lib/contract/engine.ts` (template-owned):

```ts
export type FieldErrors = Record<string, string>;            // field -> message shown; {} = valid
export interface ContractAdapter {
  base(endpoint: string): Record<string, unknown>;           // a valid body
  validate(endpoint: string, body: Record<string, unknown>): FieldErrors | Promise<FieldErrors>;  // the front end's own validation
  showResponse(endpoint: string, response: { status: number; body: unknown }):
    Promise<{ fields: FieldErrors; form?: string }>;         // render the form, answer the submit with this response, read what is shown
}
export interface ContractCase { name: string; run(adapter: ContractAdapter): Promise<string | null> }  // null = pass, else the failure message
export function contractCases(dir?: string): ContractCase[]; // every rule with role "consumer" in contract/*.json, plus response cases
```

`tests/contract/adapter.ts` (project-owned) exports `adapter: ContractAdapter`; the template's default returns `{}` from
`base` and throws `wire tests/contract/adapter.ts to your form (spec 110)` from the other two.
`tests/contract.test.ts` (project-owned) runs `it(case.name, …)` per case and fails with the returned message; with no
copy it runs one passing test named `contract: no copy in contract/ (nothing to check)`.

- Validation cases (AC-110.6): the same values as the table in 4, names `<plan_id>:<rule_id>:<case>`. Accepted means no
  entry for the rule's field in the returned `FieldErrors`; rejected means an entry for it. Failure:
  `contract <plan_id> rule <rule_id> field <field>: <case> (<value>) on <endpoint>: expected <valid | error at <field>>, got <valid | error at <field>: "<message>">`.
- Response cases (AC-110.7), per consumer rule `<plan_id>:<rule_id>:response`: status = the rule's status, body built
  from `errors.body` with field = the rule's field, rule = the rule id, message = `<rule_id> violated (contract check)`;
  passes when `fields[<field>]` equals that message. Per consumer endpoint `<plan_id>:<endpoint>:unlisted`: status = the
  first of 500, 503, 502 not used as a status in the copy, body `{}`; passes when `form` equals `unlisted.message` and
  `fields` is empty. Failure: `contract <plan_id> rule <rule_id> field <field>: response <status>: expected message "<m>" at <field>, got <fields and form as JSON>`
  (for unlisted: `contract <plan_id> <endpoint>: unlisted response <status>: expected form message "<m>", got …`).

### 6. Pin check, gitops-app (AC-110.9)

`devbox run contract-pins` = `uv run scripts/check-contract-pins.py`. Environment: `BASE_REF` (default `origin/main`),
`SERVICE_REPOS_READ_TOKEN`, `GITHUB_API_URL` (default `https://api.github.com`), `GITHUB_STEP_SUMMARY` (optional).

1. Changed pins: every `applications/*/overlays/<env>/<component>/kustomization.yaml` whose `images[0].newTag` differs
   between `git merge-base BASE_REF HEAD` and the working tree. None → `contract pins: no component pin changed: nothing to check`, exit 0.
2. Ref of a tag: `sha-<40>` / `sha-<7>` → that commit; `X.Y.Z` → git tag `vX.Y.Z` (the service template's release tags).
3. Plans: `docs/plan/*.md` whose status is not `abandoned` and whose contract has a valid `rules:` block (parsed with
   `plan`'s functions). The component takes part in a plan when its system.yaml key, or the repo name of its `repo:`,
   equals a rule's provider or a consumer. None → `contract pins: <component> takes part in no rule: not checked`.
4. The component's `repo:` (system.yaml) gives `owner/name`; no token → `ERROR: contract pins: <component> needs the
   secret SERVICE_REPOS_READ_TOKEN to read <owner/name>; add it (run cplat doctor in this repo for how)`.
5. Read `contract/<plan_id>.json` at the ref. Missing (404) →
   `ERROR: <component>: plan <plan_id> assigns it rule(s) <ids>, but <owner/name>@<sha7> has no contract/<plan_id>.json: run /component:spec --from-plan docs/plan/<plan_id>.md <repo-id> in <owner/name>`.
6. Compare each rule of the plan concerning the component with the copy's rule of the same id, attribute by attribute
   (`endpoint`, `field`, `kind`, `value`, `step`, `status`, `provider`, `consumers` as a sorted list), and the error
   object (`errors.status`, `errors.body.*`, `errors.unlisted.message`, compared under the rule id `errors`). One line per
   difference: `ERROR: <component>: plan <plan_id> rule <rule_id>: plan <attr>=<value>, pinned <owner/name>@<sha7> <attr>=<value>`;
   a rule missing from the copy prints `pinned … (missing)`, a rule only in the copy prints `plan (none)`. Values are
   JSON-encoded.
7. A match prints `contract pins: <component>@<sha7> matches plan <plan_id> (<n> rules)`. Exit 1 when any `ERROR:` line
   was printed, else 0. Every line also goes to the step summary; the token is redacted as in `check-service-crds.py`.

CI: a job `contract-pins` in `.github/workflows/ci.yml`, `if: github.event_name == 'pull_request' || inputs.ref != ''`
(pin-dev calls ci.yml with `ref`), checkout with `ref: ${{ inputs.ref }}` and `fetch-depth: 0`, env
`BASE_REF: origin/${{ github.base_ref || 'main' }}` and
`SERVICE_REPOS_READ_TOKEN: ${{ secrets.SERVICE_REPOS_READ_TOKEN || github.token }}`, run `devbox run contract-pins`.
A red job keeps the pin PR open (pin-dev's merge job already acts on `needs.ci.result`).
