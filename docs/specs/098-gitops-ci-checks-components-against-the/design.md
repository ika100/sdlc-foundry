# Design — 098 Gitops CI checks Components against the service branch CRDs

## Decisions

- **The marker is one PR body line, written by `cplat ship gitops pr`.** `ship.py` gets one pure helper (`with_service_ref`) and a few lines in `gitops_pr()`; nothing else in ship changes, so the parallel spec 087 edits of `ship.py` do not collide beyond one function.
- **One new gitops-app script, `scripts/check-service-crds.py`**, owns everything after the marker: parse it, check the repo against `services.yaml`, fetch the CRDs through the GitHub REST API, convert them to JSON schema, and validate every matching Component. It is a uv inline script like `render.py` (dependencies `pyyaml`, `jsonschema`).
- **Components are validated in Python with `jsonschema`, not with kubeconform.** The check must name the file, kind, offending field and `<owner>/<repo>@<ref>` (AC-098.4); it must cover Components anywhere under `applications/` (external kustomize packages are not in the kubeconform loop today); and it must run offline in the platform's tests, where kubeconform is not on the PATH. The conversion mirrors kubeconform's `-strict` (see Schema conversion).
- **"Instead of the catalog" (AC-098.3) is a kubeconform `-skip` list.** The script prints the service CRD kinds as `<apiVersion>/<Kind>` (comma-joined); CI exports them as `SERVICE_CRD_SKIP`, and the `validate` recipe adds `${SERVICE_CRD_SKIP:+-skip "$SERVICE_CRD_SKIP"}` to its kubeconform call. Unset (no marker, no CRDs, push, local run) it expands to nothing: the kubeconform command is byte-for-byte the one before this spec (AC-098.14, AC-098.17).
- **The token lives in its own CI step.** A new step before `devbox run quality` runs `devbox run service-crds` with `PR_BODY` and `SERVICE_REPOS_READ_TOKEN` in its `env:`; the quality step never sees the token (AC-098.13). The step runs only on `pull_request` events; push, `workflow_dispatch` and pin-dev's `workflow_call` are unchanged (AC-098.14). The PR body reaches the script only as an environment variable, never interpolated into the shell (no script injection).
- **The service ref is read through `GITHUB_API_URL`** (set by Actions, default `https://api.github.com`). The platform tests point it at a local fake HTTP server; there is no test-only switch in the shipped script.
- **"The chart's CRDs"** are the files under `<chart>/crds/` (Helm installs them as-is) plus untemplated files under `<chart>/templates/` whose document is a `CustomResourceDefinition`. `<chart>` is `external.helm.path` of every `services.yaml` entry whose `repo` is the marker's repo; when none of them has `external.helm`, every `charts/*/` directory of the service repo.
- **A branch that is gone falls back to the default branch** (AC-098.6); everything else that prevents reading the repo fails (AC-098.11). The check never passes silently on a marker it could not act on.
- **AC-098.15 needs no trigger change.** `ci.yml` already runs on `edited`, and `github.event.pull_request.body` of an `edited` event is the saved body. Edited runs use their own concurrency group (`ci-<pr>-edited`), so a later body edit cancels an earlier edit run and the last saved marker wins; a push run is never cancelled by an edit.
- **`cplat doctor` warns, it does not fail** (AC-098.16): a gitops-app works without the token until a PR carries a marker.
- No ADR: the marker and the token are feature-local; spec 097 consumes them as specified here.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/ship.py` | `with_service_ref()`; `gitops_pr()` writes the marker on create and on reuse | changed |
| `templates/gitops-app/scripts/check-service-crds.py` | marker parsing, allow-list, GitHub fetch, CRD → schema, Component validation, skip list | new |
| `templates/gitops-app/.github/workflows/ci.yml` | `service CRDs` step in the `quality` job | changed |
| `templates/gitops-app/devbox.json` | `service-crds` recipe; `-skip` in `validate` | changed |
| `scripts/cplat/doctor.py` | `check_service_repos_token()` | changed |
| docs | gitops-app CLAUDE.md/README, `docs/unattended-delivery.md`, CHANGELOG | changed |

## Contract

### Marker (AC-098.1, AC-098.2, AC-098.9)

The exact line, written by ship and expected by CI:

```
Service-ref: <owner>/<repo>@<branch>
```

- **Candidate line** (anything that looks like a marker attempt), matched per line, case-insensitive: `^\s*service-ref\s*:`
- **Valid marker** (after stripping a trailing `\r` and trailing whitespace), case-sensitive:
  `^Service-ref: (?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/(?P<repo>[A-Za-z0-9._-]{1,100})@(?P<branch>[A-Za-z0-9._/-]{1,255})$`
  and the branch does not start with `-` or `/`, does not end with `/` or `.lock`, and contains no `..` or `//`.
- Zero candidate lines: no marker. One candidate that is valid: the marker. A candidate that is not valid, or more than one candidate line: an error (AC-098.9).

### `ship.py`

```python
SERVICE_REF = re.compile(r"^\s*service-ref\s*:", re.I | re.M)   # candidate lines

def with_service_ref(body: str, ref: str) -> str:
    """`body` with exactly one line `Service-ref: <ref>` (ref = "<owner>/<repo>@<branch>").
    Every candidate line is removed; the marker takes the place of the first one. Without a candidate it is
    appended as the last line, after one blank line (an empty body becomes just the marker line).
    Every other line is kept byte-for-byte. Idempotent."""
```

`gitops_pr(repo, task_id, title, body_file)`:

- `ref = f"{service_slug(repo)}@{st['branch']}"` (the service repo running the ship and its ship branch, `feature/<spec>`).
- New PR: writes `with_service_ref(body_file.read_text(), ref)` to `<state dir>/cplat-gitops/<task_id>-body.md` and passes that file to `gh pr create ... --body-file`. The given body file is not modified.
- Reused PR: the `gh pr list` call asks for `--json number,url,body`. When `with_service_ref(body, ref) != body`, it writes the new body to the same `<task_id>-body.md` and runs `gh pr edit <url> --body-file <that file>`; otherwise no edit. The reused PR's title is not touched.
- Return value and state are unchanged (`info["pr"]` etc.).

### `check-service-crds.py` (gitops-app)

Invocation: `uv run scripts/check-service-crds.py` from the gitops-app root (recipe `devbox run service-crds`). No arguments.

| Input (env) | Meaning |
|---|---|
| `PR_BODY` | the PR body; unset or empty = no marker |
| `SERVICE_REPOS_READ_TOKEN` | read token; read only when there is a marker |
| `GITHUB_API_URL` | API base, default `https://api.github.com` |
| `GITHUB_ENV` | when set and the skip list is non-empty: appends `SERVICE_CRD_SKIP=<list>` |
| `GITHUB_STEP_SUMMARY` | when set: the same OK/WARNING/ERROR lines as a short Markdown list |

Outputs: **stdout** carries only the skip list (comma-joined `<apiVersion>/<Kind>` for every served version of every service CRD, e.g. `ai-ops.io/v1alpha1/Component,ai-ops.io/v1alpha1/Pipeline`), or nothing. **stderr** carries the log. Exit `0` = pass (or nothing to do), `1` = fail. Every line written to stdout, stderr, `GITHUB_ENV` and the summary passes through a redaction that replaces the token's value with `***`; the token is otherwise only placed in the `Authorization` header of requests to `GITHUB_API_URL` for the marker's repo.

Order of checks; each failure stops before the next step:

1. **No marker** → log `service CRDs: no Service-ref marker; manifests are validated as before`, exit 0, empty stdout. The token is not read (AC-098.14).
2. **Malformed / several markers** → `ERROR: <reason>. Expected one line: Service-ref: <owner>/<repo>@<branch>` where reason is `malformed Service-ref line '<line>'` or `<n> Service-ref lines (one per PR)`; nothing fetched (AC-098.9).
3. **Repo not a service** (case-insensitive compare against every `repo:` in `applications/*/services.yaml`) → `ERROR: Service-ref names <owner>/<repo>, which is not a service repo in applications/*/services.yaml; nothing was fetched` (AC-098.8).
4. **No token** → `ERROR: Service-ref <owner>/<repo>@<branch> needs the secret SERVICE_REPOS_READ_TOKEN to read <owner>/<repo>; add it (run cplat doctor in this repo for how)` (AC-098.10).
5. **Resolve the ref**: `GET /repos/{owner}/{repo}` (failure → step 7 errors); `GET /repos/{owner}/{repo}/branches/{branch}` (branch URL-quoted with `safe=""`). 404 on the branch → `WARNING: branch <branch> no longer exists in <owner>/<repo>; validating against its default branch <default>` and the default branch is used (AC-098.6). The commit sha from the branch response pins every later read. From here `<ref>` in messages is the branch actually used.
6. **Find CRDs**: list `<chart>/crds` and `<chart>/templates` recursively with `GET /repos/{o}/{r}/contents/{path}?ref={sha}` (a 404 directory = empty); read each `*.yaml`/`*.yml` with the same endpoint (`content` base64). A file is a CRD when a YAML document in it has `kind: CustomResourceDefinition`. A `templates/` file containing `{{` and the text `CustomResourceDefinition` is a templated CRD → error (step 8). No CRD → `service CRDs: <owner>/<repo>@<ref> defines no CRDs; manifests are validated as before`, exit 0, empty stdout (AC-098.7).
7. **Read failures** (AC-098.11) → `ERROR: cannot read <owner>/<repo>: <reason>` with reason one of `HTTP 401 (the token is invalid or expired)`, `HTTP 403 (the token may not read this repo, or the rate limit is exhausted)`, `HTTP 404 (repository not found, or the token has no access to it)`, `HTTP <code>`, `network error: <exception text>`. One retry for 5xx and connection errors, timeout 30 s per request. Exception texts never contain request headers.
8. **CRD → schema failure** (AC-098.12) → `ERROR: <owner>/<repo>@<ref>: <path in service repo>: <reason>` with reason `invalid YAML: <parser message>`, `no openAPIV3Schema for version <v>`, `templated CRD (contains {{ }}): ship it in crds/`, or `file too large for the contents API`.
9. **Validate Components** (AC-098.3–5): every YAML document under `applications/**/*.yaml|yml` whose `apiVersion` group and `kind` equal a service CRD's `spec.group` and `spec.names.kind` is validated against the schema of its version. Skipped and not reported: files that do not parse (the other `validate` steps own them) and files named as patches (`patches[].path`, `patchesStrategicMerge`) by a `kustomization.yaml` in the same directory. Errors, one line each:
   `ERROR: <file>: <Kind> <metadata.name> (<apiVersion>) does not match the CRD from <owner>/<repo>@<ref>: <field>: <problem>`
   where `<file>` is relative to the repo root, `<field>` is the dotted path (`spec.build.namespace`, list items as `spec.steps[2].image`, the document itself as `(root)`) and `<problem>` is one of `unknown field`, `missing required field`, `wrong type (want <type>, got <type>)`, `version <v> is not served by the CRD (served: <v,...>)`, or the jsonschema message. For an unknown or missing field the field path ends with that field's name.
   Pass: one line `OK: <Kind> (<group>) from <owner>/<repo>@<ref>: <n> resource(s) valid` per CRD kind with at least one resource, then `service CRDs from <owner>/<repo>@<ref> (commit <sha7>): <Kind>, ...` listing every kind defined.
10. Exit 1 if any ERROR line was written, else print the skip list and exit 0.

### Schema conversion (CRD version → JSON schema, mirrors kubeconform `-strict`)

- Start from `spec.versions[].schema.openAPIV3Schema` (served versions); add `apiVersion` and `kind` (`type: string`) and `metadata` (`type: object`) to the root `properties` when absent.
- An object with `properties` and without `additionalProperties` and without `x-kubernetes-preserve-unknown-fields: true` gets `additionalProperties: false`.
- `x-kubernetes-int-or-string: true` → `anyOf: [{type: integer}, {type: string}]` (replaces the node's `anyOf`/`type`).
- `nullable: true` → `null` added to `type`.
- `x-kubernetes-embedded-resource: true` → `apiVersion`, `kind`, `metadata` allowed as in the root.
- Every other `x-kubernetes-*` key and `format` is dropped; validation uses `jsonschema.Draft7Validator`.

### CI (`templates/gitops-app/.github/workflows/ci.yml`, `quality` job)

A step between the devbox install and `devbox run quality`:

```yaml
      - name: service CRDs (Service-ref marker, spec 098)
        if: github.event_name == 'pull_request'
        env:
          PR_BODY: ${{ github.event.pull_request.body }}
          SERVICE_REPOS_READ_TOKEN: ${{ secrets.SERVICE_REPOS_READ_TOKEN }}
        run: devbox run service-crds
```

The `quality` job name, the triggers and the concurrency group stay as they are. `ci.yml` is copied verbatim (not `.jinja`), so `${{ }}` is written unescaped.

### devbox (`templates/gitops-app/devbox.json`)

- New recipe `"service-crds": "uv run scripts/check-service-crds.py"`.
- `validate`: the kubeconform call becomes `kubeconform -strict -ignore-missing-schemas ${SERVICE_CRD_SKIP:+-skip "$SERVICE_CRD_SKIP"} -schema-location default ...`; nothing else in the recipe changes.

### `cplat doctor` (AC-098.16)

`doctor.check_service_repos_token(repo: Path) -> list[dict]`, called from `run_checks` after `check_gitops_token`:

- `[]` unless `scripts/detect-shape.sh` says `gitops-app`.
- Reads `ship.gh(["secret", "list", "--json", "name"], cwd=repo, check=False)`.
- Present → `check(OK, "secret SERVICE_REPOS_READ_TOKEN", "set: gitops CI can read the service repos named by Service-ref markers")`.
- Missing, or the list cannot be read → `check(WARN, "secret SERVICE_REPOS_READ_TOKEN", "not set: gitops PRs with a Service-ref marker (opened by /svc:ship) fail their CRD check" | "could not be read with this gh login", SERVICE_REPOS_TOKEN_FIX)` with
  `SERVICE_REPOS_TOKEN_FIX = "create a fine-grained token with Contents: read on every service repo in services.yaml, then: gh secret set SERVICE_REPOS_READ_TOKEN -R {slug}"` (`slug` = `ship.service_slug(repo)`).

## Testing notes (for the testers)

- Ship: extend the `Gh` fake in `tests/cplat/test_ship_checks.py` style: assert the `--body-file` passed to `pr create` contains exactly one marker, and that a reused PR whose listed `body` lacks it gets one `pr edit <url> --body-file`. `with_service_ref` is unit-testable directly.
- Script: copy it into a temp gitops repo (as `test_plan.py` does), write `applications/<app>/services.yaml` and Component files, and run it with `uv run` against a fake GitHub API (`http.server` in a thread, `GITHUB_API_URL=http://127.0.0.1:<port>`) that serves the endpoints above from a dict. Assert stdout (skip list), exit code and stderr lines; assert the token value never appears in stdout, stderr, `GITHUB_ENV` or `GITHUB_STEP_SUMMARY` files, and that the fake saw no request for steps 2–4. Network failure: a closed port.
- Recipe/workflow: static checks on `devbox.json` and `ci.yml`; the kubeconform fragment can be run through `sh -c` with a fake `kubeconform` on `PATH` to show `SERVICE_CRD_SKIP` unset yields the old argument list.

## Risks

- A service that templates its CRDs in `templates/` gets a failing check with a clear message until it moves them to `crds/`: intended, the alternative is silently skipping (forbidden by AC-098.10/11).
- Files of a kustomize package that are patches of a Component are skipped by name; a patch referenced from another directory is validated as a full resource and may fail on required fields. Patches live next to their kustomization in every platform layout today.
- The contents API returns no content for files over 1 MB; such a CRD fails with a named reason rather than passing.
