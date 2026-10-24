---
spec_id: 098-gitops-ci-checks-components-against-the
spec_hash: 8fbd29bcf989
summary: Service-ref marker on ship's gitops PRs; gitops CI validates Components against the service ref's CRDs; doctor warns about SERVICE_REPOS_READ_TOKEN
tasks:
- id: t1
  title: cplat ship gitops pr writes the Service-ref marker
  files: [scripts/cplat/ship.py]
  covers: [AC-098.1, AC-098.2]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: check-service-crds.py validates Components against the service ref's CRDs
  done: true
  files: [templates/gitops-app/scripts/check-service-crds.py]
  covers: [AC-098.3, AC-098.4, AC-098.5, AC-098.6, AC-098.7, AC-098.8, AC-098.9, AC-098.10, AC-098.11, AC-098.12,
    AC-098.13]
  parallel_safe: true
  depends_on: []
- id: t3
  title: Gitops CI step and devbox recipes for the service CRD check
  files: [templates/gitops-app/.github/workflows/ci.yml, templates/gitops-app/devbox.json]
  covers: [AC-098.3, AC-098.10, AC-098.13, AC-098.14, AC-098.15, AC-098.17]
  parallel_safe: true
  depends_on: []
  done: true
- id: t4
  title: cplat doctor checks SERVICE_REPOS_READ_TOKEN in gitops-apps
  files: [scripts/cplat/doctor.py]
  covers: [AC-098.16]
  parallel_safe: true
  depends_on: []
  done: true
- id: t5
  title: Document the marker, the CRD check and the token
  files: [templates/gitops-app/CLAUDE.md.jinja, templates/gitops-app/README.md.jinja, docs/unattended-delivery.md,
    docs/CHANGELOG.md]
  covers: [AC-098.10, AC-098.16]
  parallel_safe: true
  depends_on: []
  done: true
---

# Plan — 098 Gitops CI checks Components against the service branch CRDs

The contract (marker regex, script inputs/outputs and messages, CI step, recipes, doctor check) is in
[design.md](design.md); every task builds against it, so all five run in parallel on disjoint files.

## t1 — cplat ship gitops pr writes the Service-ref marker

**Files:** scripts/cplat/ship.py
**Covers:** AC-098.1, AC-098.2
**Goal:** every gitops PR that ship opens or reuses carries exactly one `Service-ref: <owner>/<repo>@<branch>` line naming the service repo and its ship branch.

**Implementation notes:**
- Add `SERVICE_REF` (candidate-line regex) and the pure `with_service_ref(body, ref)` exactly as in design.md, next to the gitops section.
- In `gitops_pr()`: `ref = f"{service_slug(repo)}@{st['branch']}"`; write the marked body to `gitops_checkout(repo, t["repo"]).parent / f"{task_id}-body.md"` and pass that to `gh pr create --body-file`; never modify the caller's body file.
- Reuse path: add `body` to the `gh pr list --json` fields; edit with `gh pr edit <url> --body-file <file>` only when the marked body differs.
- Keep the change inside `gitops_pr()` plus the helper: spec 087 edits `ship.py` in parallel.

**Done when:** the AC-098.1/AC-098.2 tests in `tests/cplat/` pass and the existing spec 076 ship tests stay green.

## t2 — check-service-crds.py validates Components against the service ref's CRDs

**Files:** templates/gitops-app/scripts/check-service-crds.py
**Covers:** AC-098.3, AC-098.4, AC-098.5, AC-098.6, AC-098.7, AC-098.8, AC-098.9, AC-098.10, AC-098.11, AC-098.12, AC-098.13
**Goal:** the gitops-app script that turns a PR body marker into a validation of every matching Component against the CRDs of the service ref, with the messages, exit codes and stdout skip list of design.md.

**Implementation notes:**
- uv inline script header (`dependencies = ["pyyaml", "jsonschema"]`), `ROOT` = repo root as in `render.py`; no arguments.
- Steps 1–10 of the design contract in that order; nothing is fetched before steps 2–4 pass.
- GitHub access only through `GITHUB_API_URL` (default `https://api.github.com`) with `urllib.request`: headers `Authorization: Bearer`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`; one retry on 5xx/connection errors; 30 s timeout. No other host ever gets the token.
- Branch 404 → default branch from `GET /repos/{o}/{r}` with the WARNING line; pin reads to the commit sha.
- CRD discovery: `external.helm.path` of the marker repo's services, else every `charts/*/`; files under `crds/` and untemplated CRD files under `templates/`; templated CRD → error.
- Schema conversion per design.md (strict `additionalProperties: false`, int-or-string, nullable, embedded resource, root apiVersion/kind/metadata); `Draft7Validator`; map errors to `unknown field` / `missing required field` / `wrong type (...)` with the dotted field path ending in the field's name.
- Scan `applications/**/*.y{a,}ml` multi-document; skip unparsable files and kustomize patch files of the same directory.
- One `emit()` for all output that redacts the token value, and writes `GITHUB_ENV` (`SERVICE_CRD_SKIP=...`) and `GITHUB_STEP_SUMMARY` when those are set.

**Done when:** the AC-098.3–AC-098.13 script tests (fake GitHub API on localhost, no kubeconform needed) pass.

## t3 — Gitops CI step and devbox recipes for the service CRD check

**Files:** templates/gitops-app/.github/workflows/ci.yml, templates/gitops-app/devbox.json
**Covers:** AC-098.3, AC-098.10, AC-098.13, AC-098.14, AC-098.15, AC-098.17
**Goal:** pull request runs execute the check with the token in a separate step and hand the skip list to kubeconform; every other run is unchanged.

**Implementation notes:**
- `ci.yml`: add the `service CRDs` step of design.md to the `quality` job between devbox install and `devbox run quality`; `if: github.event_name == 'pull_request'`; `PR_BODY` and `SERVICE_REPOS_READ_TOKEN` only in that step's `env:`. Leave job names, triggers (already include `edited`) and the concurrency group unchanged.
- `devbox.json`: add `"service-crds": "uv run scripts/check-service-crds.py"`; in `validate` insert `${SERVICE_CRD_SKIP:+-skip "$SERVICE_CRD_SKIP"}` after `-ignore-missing-schemas`, nothing else.
- Run `devbox run security` on a rendered gitops-app (`devbox run smoke-gitops` or the copier command in CLAUDE.md): if detect-secrets flags the new `env:` line, add `# pragma: allowlist secret` to it.

**Done when:** the AC-098.14/15/17 template tests pass (static checks on `ci.yml`/`devbox.json`; the kubeconform fragment with `SERVICE_CRD_SKIP` unset gives the previous arguments) and a rendered gitops-app still passes `devbox run quality`.

## t4 — cplat doctor checks SERVICE_REPOS_READ_TOKEN in gitops-apps

**Files:** scripts/cplat/doctor.py
**Covers:** AC-098.16
**Goal:** `cplat doctor` in a gitops-app shows an OK or a WARN line for `SERVICE_REPOS_READ_TOKEN`, and nothing in other shapes.

**Implementation notes:**
- `check_service_repos_token(repo)` and `SERVICE_REPOS_TOKEN_FIX` as in design.md; shape from `scripts/detect-shape.sh` (as `check_repo` does); the secret list through `ship.gh` (as `check_gitops_token`).
- WARN for missing and for an unreadable list, never FAIL; append it to `run_checks` after `check_gitops_token`.

**Done when:** the AC-098.16 doctor tests pass (gitops-app with/without the secret, a service repo shows no such line).

## t5 — Document the marker, the CRD check and the token

**Files:** templates/gitops-app/CLAUDE.md.jinja, templates/gitops-app/README.md.jinja, docs/unattended-delivery.md, docs/CHANGELOG.md
**Covers:** AC-098.10, AC-098.16
**Goal:** users and agents know what the marker does, why a PR fails on it, and how to add the token.

**Implementation notes:**
- gitops-app `CLAUDE.md.jinja`: add `service-crds` to the recipe table; one paragraph on `Service-ref:` (written by `/svc:ship`, never hand-edited unless intended) and `SERVICE_REPOS_READ_TOKEN`. Plain Jinja file: no `${{` to escape.
- `README.md.jinja`: one line on the token next to the quality command.
- `docs/unattended-delivery.md`: a row in "What has to be in place" for `SERVICE_REPOS_READ_TOKEN` in the gitops-app (Contents: read on the service repos; check: `cplat doctor` in the gitops-app).
- `docs/CHANGELOG.md`: a `Feat (098)` bullet under `[Unreleased]` in the 4.4.0 style, with the action for existing products (`/shared:update-service` in the gitops-app, then set the secret as `cplat doctor` says). No plugin or marketplace version bumps.

**Done when:** `devbox run validate` (Markdown links) passes.
