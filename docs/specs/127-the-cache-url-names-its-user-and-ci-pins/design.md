# Design — 127 The cache URL names its user and CI pins its test tools

Two independent loose ends. No new API, no new data model, no ADR (see Decisions).

## Decisions

- **The url template names `default`** (AC-127.1). `cache_files()` in `templates/gitops-app/scripts/render.py` writes
  `redis://default:{{ .password }}@<system>-<name>.<system>-<env>.svc:6379/0` into the ExternalSecret template; the
  cluster-gitops copy follows through `scripts/sync-template-copies.py`. Keys, variables, Secret name, `refreshPolicy:
  CreatedOnce` and the generator stay as spec 118 defines them. External caches are untouched (their url is the user's).
- **An existing cache Secret keeps its url** (AC-127.2, see Risks: this is the reading of the criterion). The Secret is
  written by External Secrets with `refreshPolicy: CreatedOnce`: ESO syncs it once per ExternalSecret and does not
  re-sync on a template change (only when the target Secret is deleted or edited, and that re-sync runs the `Password`
  generator again, i.e. a new password the running Valkey does not know). So a re-render changes the ExternalSecret,
  not the Secret, and running or restarted pods keep `redis://:<password>@…`, which client libraries accept and which
  authenticates as the same user `default`. Switching the policy to `OnChange` would rotate the password on every
  re-render and break components until the cache restarts, so the platform does not move existing Secrets; new caches
  (and new environments of an existing cache) get the new form. `tests/e2e/upgrade.sh` keeps its rewrite for exactly
  this reason.
- **The change list detects the url from the rendered files**, not from a version comparison: `render_and_compare()` in
  `scripts/cplat/update.py` already reads every instance before and after the re-render; for a cache it also reads
  `spec.target.template.data.url` of `addons/<env>/<name>/externalsecret.yaml`. A differing value adds one row per
  cache and environment to the existing `versions` rows. This reuses the report, `--json` and the fleet PR body
  (`fleet_pr.py` prints `versions.lines` verbatim), needs no table of platform versions, and fires for any later url
  change too.
- **Test tools come from one compiled file** (AC-127.4, AC-127.5). `requirements-test.in` lists the four top-level
  packages unpinned; `requirements-test.txt` is `uv pip compile --universal requirements-test.in -o requirements-test.txt`
  (exact `==` pins with environment markers, so macOS, Linux and every Python devbox or CI uses resolve the same set;
  no `--generate-hashes`: the criterion asks for exact versions and hashes would double the Dependabot diff for no gain
  inside a CI that already pins its runner tools). The three suite commands become
  `uv run --with-requirements requirements-test.txt pytest tests/cplat -q -n auto …`.
- **The guard is a fourth part of `scripts/check-pins.py`** (AC-127.5). It is the platform's pin check (spec 121,
  ADR-069: everything the platform runs is pinned), it already has the finding format and runs in CI on every PR
  (`validate-shapes`, always, not path-filtered) and in `devbox run validate`. `pin-actions.py` is about Action SHAs in
  template and platform workflows alike, and the templates' test tools are a non-goal; a new script would be one more
  CI step for six lines of logic.
- **Dependabot** (AC-127.6): one `pip` entry for `/`, monthly, one group `test-tools` with `patterns: ["*"]`. Its PR
  changes `requirements-test.txt` (and `.in` never), which the `changes` job counts as `code`, so the full CI runs.
- **No ADR.** The url form is a spec 118 amendment that ADR-064 does not fix (it names keys and variables, not the
  form); pinning the platform's own test tools applies ADR-069's rule to one more file.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` (+ `templates/cluster-gitops/scripts/system_render.py` copy) | the cache ExternalSecret's `url` template | changed |
| `scripts/cplat/update.py` | `_instances()` records a cache's rendered `url` template; `render_and_compare()` adds a `url` row | changed |
| `tests/e2e/run.sh` | the Secret check expects the new form; the probe's rewrite is gone | changed |
| `plugins/resource/commands/add.md` | the cache bullet names the in-cluster url form | changed |
| `requirements-test.in`, `requirements-test.txt` | the platform's test tools, top-level and compiled | new |
| `.github/workflows/ci.yml`, `scripts/ci-local.sh`, `devbox.json` | install the suite's tools from `requirements-test.txt` | changed |
| `scripts/check-pins.py` | part 4: the suite commands install only from `requirements-test.txt` | changed |
| `.github/dependabot.yml` | the `pip` entry | changed |

## Contract

### Rendered Secret template (AC-127.1)

`applications/<system>/addons/<env>/<name>/externalsecret.yaml`, `spec.target.template.data.url`:

```
redis://default:{{ .password }}@<system>-<name>.<system>-<env>.svc:6379/0
```

`host`, `port`, `password`, the Secret name `<system>-<name>-app` and the variables `REDIS_URL` / `<NAME>_REDIS_URL` are
unchanged. The resulting Secret value is `redis://default:<32-character password>@<host>:6379/0`.

### `/platform:update` change list row (AC-127.2)

For every in-cluster cache instance `(system, name, env)` whose rendered `url` template before the re-render differs
from the one after it (both present), one row is appended to `versions.rows`, in the same per-instance order as the pin
rows (system, resource, then environment in `model.ENVIRONMENTS` order), after that instance's pin row if any. The row
is emitted even when the instance has no pin row (the pin skip must not skip it). `<from>` and `<to>` are the two
templates with `{{ .password }}` replaced by the literal `<password>`.

JSON (`versions.rows[]`):

```json
{"env": "<env>", "resource": "<name>", "kind": "url", "from": "<from>", "to": "<to>", "moves": false, "text": "<text>"}
```

`text` (also the line in `versions.lines`, the printed block and the fleet PR body):

```
f"{env:<8} {name}: url {to} (was {from}); the Secret {system}-{name}-app was written once and keeps its url, which authenticates as the same user default: running pods need nothing, new Secrets get the new form"
```

Example: `dev      sessions: url redis://default:<password>@shop-sessions.shop-dev.svc:6379/0 (was redis://:<password>@shop-sessions.shop-dev.svc:6379/0); the Secret shop-sessions-app was written once and keeps its url, which authenticates as the same user default: running pods need nothing, new Secrets get the new form`

When the only rows are `url` rows, `versions` is still returned (not `None`), and `did` reads
`re-rendered with the new renderer; <n> version change(s) listed below` as today (`<n>` counts all rows).

### Test-tool pins (AC-127.4, AC-127.5)

- `requirements-test.in`: exactly `pytest`, `pytest-xdist`, `pyyaml`, `ruamel.yaml`, one per line, unpinned.
- `requirements-test.txt`: uv's header (`# This file was autogenerated by uv via the following command:` /
  `#    uv pip compile --universal requirements-test.in -o requirements-test.txt`); every requirement line is
  `<name>==<version>` (optionally `; <marker>`), covering the four packages and each of their dependencies.
- Suite commands: `.github/workflows/ci.yml` (job `platform-tests`, step `pytest`), `scripts/ci-local.sh` and
  `devbox.json` `shell.scripts.test-fast` each run `uv run --with-requirements requirements-test.txt pytest tests/cplat …`
  and carry no `--with <pkg>` / `--with=<pkg>` for any of the four packages.
- `scripts/check-pins.py` part 4: in each of the three files, a *suite line* is a line containing `pytest tests/cplat`.
  Findings, in the existing format `ERROR: <file>:<line>: <reference>: <reason>`:
  - a file without a suite line: `ERROR: <file>:0: pytest tests/cplat: the cplat suite command is missing`;
  - a suite line without `--with-requirements requirements-test.txt`: reason `installs the test tools without requirements-test.txt`;
  - a suite line with `--with <p>` or `--with=<p>` for `p` in {pytest, pytest-xdist, pyyaml, ruamel.yaml}: reference
    `--with <p>`, reason `installs <p> without requirements-test.txt`;
  - a requirement line of `requirements-test.txt` that is not `<name>==<version>`: reference the line, reason `not pinned to an exact version`.
  Each suite line and requirement line counts as a checked reference. Any finding makes the script exit 1, as today.

### Dependabot (AC-127.6)

```yaml
  - package-ecosystem: pip
    directory: "/"
    schedule: {interval: monthly}
    groups:
      test-tools:
        patterns: ["*"]
```

## Risks

- **Reading of AC-127.2.** The criterion says running pods take the new form on their next restart. With
  `refreshPolicy: CreatedOnce` (ESO controller: `shouldRefresh` is false after the first sync, and a template change does
  not invalidate the Secret) that is not true for caches created before this release, and making it true means a new
  password. The design reports what really happens; the criterion's wording is flagged to the user (see the plan's
  report). Nothing fails either way: both forms authenticate as `default`.
- Dependabot's `pip` ecosystem recognises uv-compiled requirement files by their header; if it does not regenerate the
  file, it still bumps the `==` pins in place and the PR's CI (including part 4) proves the set.
