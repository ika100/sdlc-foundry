# Design — 189 The web image has no known critical CVE and the platform scans template images

## Decisions

- The web runtime stage is `gcr.io/distroless/nodejs{{ node_major }}-debian13` (A1). Debian 13 ships zlib 1.3.1, which has the
  CVE-2023-45853 fix that Debian 12 marks "won't fix". The deps and builder stages stay on `node:{{ node_major }}-slim`
  (non-goal). The `apt-get upgrade` and npm-removal steps go: the image has no apt, no npm and no corepack. The `:nonroot` tag is
  not used, because the image keeps `USER 1000:1000` (AC-189.2, the UID the gitops entries already expect).
- The image entrypoint is distroless's `/nodejs/bin/node`, so `CMD ["server.js"]`. `docker run <img> sh` then runs
  `node sh` and fails, and there is no `/bin/sh` for `--entrypoint sh` either (AC-189.1).
- The health check is exec form `["/nodejs/bin/node", "-e", "fetch(...)"]`, because the image has no shell (AC-189.2).
- The platform scan runs in its own workflow `.github/workflows/template-image-scan.yml` with `pull_request`, a daily
  `schedule` (`17 3 * * *`, the same slot as the nightly e2e) and `workflow_dispatch`. Not in `ci.yml`, because `ci.yml` treats
  every non-PR event as "run everything", and a schedule there would run the whole suite daily (A4).
- The workflow has no `paths` filter. A `decide` job picks the templates, as `e2e.yml` does (ADR-080), so a PR always gets
  the check and the job runs only for the templates it changed.
- Trivy runs through `aquasecurity/trivy-action` at the same commit SHA as the templates' CI. `pin-actions.py` keeps the
  platform and template pins equal, so the platform and generated repos use the same trivy version (A7). The action is not
  given a `version:` input.
- The decision logic (select templates, evaluate a trivy JSON report against the accepted list) is one tested script,
  `scripts/template-image-scan.py`. The workflow only renders, builds, scans and calls it, which keeps AC-189.3–6 testable
  without Docker.
- An accepted-finding entry carries an explicit `added` date. Without it, "no more than 90 days after it was added"
  (AC-189.5/6) cannot be checked offline, and git history is not reliable in a shallow checkout.
- An entry is "found" when its CVE appears in the template's report at any scanned severity (CRITICAL or HIGH). That is the
  literal reading of AC-189.6.
- The accepted list lives at `.github/image-scan-accepted.yml`: platform-only, never rendered into a template (non-goal), and
  reviewed like any other PR file (A5).
- ADR: "Template images are scanned by the platform, and an accepted CVE expires in 90 days". t2 creates it with
  `cplat adr add`, because the architect run had no shell.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/web-nextjs/Dockerfile.jinja` | distroless runtime stage | changed |
| `scripts/template-image-scan.py` | `select` and `evaluate` subcommands | new |
| `.github/image-scan-accepted.yml` | accepted-finding list | new |
| `.github/workflows/template-image-scan.yml` | decide → render, build, scan, evaluate per template | new |
| `.github/dependabot.yml` | header comment | changed |
| `docs/adr/005-node-version-policy.md` | the Dockerfile pin is now build stages `node:<major>-slim` plus runtime `distroless/nodejs<major>` | changed |

## Contract

### Accepted-finding list (`.github/image-scan-accepted.yml`)

```yaml
# Accepted CRITICAL findings of the platform's template image scan (spec 189). Each entry needs a reason and a review-by
# date at most 90 days after it was added; it covers only the template it names.
findings:
  - template: service-java        # one of service-python, service-java, service-go, web-nextjs
    cve: CVE-2023-45853           # the trivy VulnerabilityID
    reason: "zlib1g in distroless debian12, Debian: won't fix; follow-up #NNN"
    added: 2026-11-13             # YAML date
    review_by: 2027-02-10         # YAML date, added < review_by <= added + 90 days
```

An empty list is `findings: []`. A file that is missing, not YAML, or has no `findings` list is a usage error (exit 2).

### `scripts/template-image-scan.py select`

```
uv run scripts/template-image-scan.py select --event <github event name> [--base <sha>]
```

- `--event` other than `pull_request` (schedule, workflow_dispatch, push) selects all four.
- `pull_request` reads `git diff --name-only <base>...HEAD`. It selects every template `t` of the four with a path under
  `templates/<t>/`. Any change to `scripts/template-image-scan.py`, `.github/image-scan-accepted.yml` or
  `.github/workflows/template-image-scan.yml` selects all four.
- It prints two lines for `$GITHUB_OUTPUT`: `templates=<compact JSON list, fixed order service-python, service-java, service-go, web-nextjs>`
  and `any=true|false`. Exit 0.

### `scripts/template-image-scan.py evaluate`

```
uv run scripts/template-image-scan.py evaluate --template <t> --report <trivy.json> [--accepted <path>] [--today YYYY-MM-DD]
```

`--accepted` defaults to `.github/image-scan-accepted.yml`, and `--today` to the current UTC date. The report is trivy's
`--format json`. It reads `Results[].Vulnerabilities[]` (which may be null) and uses `VulnerabilityID`, `PkgName`,
`InstalledVersion`, `FixedVersion` and `Severity`. Findings are de-duplicated by (CVE, package, installed version).

It only checks entries whose `template` equals `--template` (AC-189.5). The output goes to stdout, one line each, in
this order:

| Line | When |
|---|---|
| `CRITICAL: <CVE> in <template>: <pkg> <installed> (fixed in <fixed>)` or `(no fix)` | a CRITICAL finding with no valid entry for its CVE |
| `HIGH: <CVE> in <template>: <pkg> <installed> (fixed in <fixed>)` or `(no fix)` | every HIGH finding (report only, A2) |
| `accepted: <CVE> in <template>: <reason> (review by <YYYY-MM-DD>)` | a CRITICAL finding covered by a valid entry, once per CVE |
| `entry <CVE> in <template>: <problem>` | one line per problem of an entry for this template |
| `scan <template>: <c> critical, <h> high, <a> accepted, <e> entry problems` | always last |

`<problem>` is one of the following:
- `no reason`: the reason is missing or blank.
- `review date passed`: `review_by` < today.
- `review date too far`: `review_by` > `added` + 90 days.
- `no longer found`: the CVE is not in this report at any severity.

An entry with a problem is not valid, so its CVE counts as unaccepted CRITICAL as well.

Exit codes:
- `0`: no unaccepted CRITICAL and no entry problem.
- `1`: at least one of those (AC-189.3, AC-189.6).
- `2`: usage or input error (unreadable report, malformed list, an entry missing `template`, `cve`, `added` or `review_by`, or
  naming an unknown template). The message goes to stderr.

### Workflow (`template-image-scan.yml`)

- `permissions: contents: read`, actions pinned by SHA, concurrency group `template-image-scan-<pr|ref>` (cancels only on
  PRs).
- Job `decide` (`timeout-minutes: 2`): checkout with `fetch-depth: 0`, `select --event "$EVENT" --base "$BASE"`, and the
  output goes to `$GITHUB_OUTPUT`.
- Job `scan` (named `scan <template>`): it needs `decide`, runs `if: needs.decide.outputs.any == 'true'`, and has a matrix
  `template: fromJSON(needs.decide.outputs.templates)`, `fail-fast: false` and `timeout-minutes: 30`. Steps:
  1. Render the default with `copier copy ./templates/<t> /tmp/img --defaults --trust --skip-tasks --data project_name=scan-<t>`
     (service-python also gets `--data module_name=scan_svc`).
  2. Build with `docker build -t scan:<t> /tmp/img` (service-go also gets `--build-arg VERSION=v0.0.0`).
  3. Scan with trivy-action: `image-ref: scan:<t>`, `scanners: vuln`, `severity: CRITICAL,HIGH`, `ignore-unfixed: false`,
     `format: json`, `output: trivy-<t>.json`, `exit-code: 0`.
  4. Run `evaluate --template <t> --report trivy-<t>.json`. Its exit code is the job's result.
