---
spec_id: 189-the-web-image-has-no-known-critical-cve
shape: platform
spec_hash: "387c4d5c81eb"
summary: Distroless Node runtime for the web template, a platform workflow that scans the four template images daily and on PRs against an expiring accepted-finding list, and an honest Dependabot header
tasks:
  - id: t1
    title: Web runtime stage on distroless Node (no shell, no npm)
    files: [templates/web-nextjs/Dockerfile.jinja, tests/cplat/test_generated_repos.py, docs/adr/005-node-version-policy.md, plugins/web/agents/deployment.md, plugins/web/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-189.1, AC-189.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Template image scan workflow, evaluator script and accepted-finding list
    files: [scripts/template-image-scan.py, .github/image-scan-accepted.yml, .github/workflows/template-image-scan.yml, docs/adr/README.md]
    covers: [AC-189.3, AC-189.4, AC-189.5, AC-189.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Dependabot header names the template image scan; changelog fragment
    files: [.github/dependabot.yml, docs/changelog.d/682-web-image-distroless.fixed.md]
    covers: [AC-189.7]
    parallel_safe: true
    depends_on: []
    done: true
human_steps:
  - For each service template that gets an accepted-finding entry in t2, open one follow-up issue (decided 2026-11-12) and put its number in the entry's reason
---

## t1 — Web runtime stage on distroless Node (no shell, no npm)

**Files:** templates/web-nextjs/Dockerfile.jinja, tests/cplat/test_generated_repos.py, docs/adr/005-node-version-policy.md, plugins/web/agents/deployment.md, plugins/web/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
**Covers:** AC-189.1, AC-189.2
**Goal:** The rendered web image has no CRITICAL finding and no shell, package manager or npm. It still starts as UID 1000 on a read-only root filesystem, gets healthy and passes the browser smoke.

**Implementation notes:**
- Runtime stage: `FROM gcr.io/distroless/nodejs{{ node_major }}-debian13 AS runtime`. Keep the LABELs, ENV, EXPOSE and the three standalone COPYs, but `--chown=1000:1000`, because there is no `node` user name in distroless. Keep `USER 1000:1000` and fix its comment (no longer "the image's node user").
- Drop the `apt-get upgrade` RUN and the npm/corepack `rm -rf` RUN, together with their comments.
- `HEALTHCHECK ... CMD ["/nodejs/bin/node", "-e", "fetch('http://localhost:{{ port }}/api/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"]` (exec form), and `CMD ["server.js"]`. The entrypoint is distroless's node.
- Leave the deps and builder stages on `node:{{ node_major }}-slim` (non-goal).
- `tests/cplat/test_generated_repos.py`: replace `test_web_runtime_image_ships_no_npm` with a check that the runtime stage is `distroless/nodejs{{ node_major }}` with no `RUN`. Restrict `test_slim_runtime_images_take_the_debian_security_updates` to service-python. Keep the issue/journey references in the docstrings.
- ADR-005: change the "Dockerfile base image" bullet to say the build stages use `node:<major>-slim` and the runtime uses `gcr.io/distroless/nodejs<major>-debian13` (spec 189).
- `plugins/web/agents/deployment.md`: say the runtime is distroless `nodejs<major>` and not `node:<major>-slim`, with no net growth of the prompt (`cplat platform rules check` size gate). Bump the web plugin 0.8.0 → 0.8.1 in plugin.json and marketplace.json.

**Done when:** the static acceptance tests for AC-189.1/AC-189.2 and `tests/cplat/test_generated_repos.py` pass, and `cplat platform rules check` is green. Where Docker is available, the rendered default image builds and `docker run --rm <img> sh` fails. The runtime part of AC-189.1/2 (scan, health, smoke, Node major) is proven by the PR's `smoke-test-web-nextjs` and `scan web-nextjs` jobs.

## t2 — Template image scan workflow, evaluator script and accepted-finding list

**Files:** scripts/template-image-scan.py, .github/image-scan-accepted.yml, .github/workflows/template-image-scan.yml, docs/adr/README.md
**Covers:** AC-189.3, AC-189.4, AC-189.5, AC-189.6
**Goal:** Every PR that changes an image template, and a daily run for all four, scans the default render's image. The run fails on an unaccepted CRITICAL or a bad accepted entry, as specified in design.md "Contract".

**Implementation notes:**
- `scripts/template-image-scan.py` (PEP 723 header with pyyaml, like the other `uv run scripts/*.py`) has the `select` and `evaluate` subcommands, with output lines, problem strings and exit codes exactly as in design.md. Pure functions (`select_templates(event, changed_paths)`, `evaluate(template, report, entries, today)`) sit behind a thin CLI, so the tests need no Docker or git.
- `.github/image-scan-accepted.yml`: the header comment from the design, then `findings:`. The web-nextjs template gets no entry (AC-189.1 needs zero CRITICALs). For service-python, service-java and service-go, add an entry with `added` = the build date and `review_by` ≤ 90 days later for each CRITICAL finding that has no fix ("won't fix") and that the scan finds. Get the list from a local `trivy image` run when Docker is available, otherwise from the PR's first `scan <template>` logs. A fixable CRITICAL in those images is a BLOCKER to report, not an entry.
- `.github/workflows/template-image-scan.yml` follows design.md "Workflow". Pin actions with the same SHAs as `ci.yml`, and trivy-action with the templates' SHA. It must pass `pin-actions.py --check` (least-privilege `permissions`) and actionlint.
- Run `cplat adr add template-images-are-scanned-and-accepted-cves-expire --decision "The platform scans every template image on PRs and daily; a CRITICAL finding fails unless a reviewed entry with a reason accepts it for at most 90 days"`. Fill in Context, Decision and Consequences from design.md "Decisions". The new `docs/adr/<n>-...md` belongs to this task.

**Done when:** the acceptance tests for AC-189.3–AC-189.6 pass against the script. `pin-actions.py --check`, `check-links.py` and `reuse lint` are green. The PR's `scan <template>` jobs pass for the templates it changed.

## t3 — Dependabot header names the template image scan; changelog fragment

**Files:** .github/dependabot.yml, docs/changelog.d/682-web-image-distroless.fixed.md
**Covers:** AC-189.7
**Goal:** The Dependabot header no longer claims Docker base images. It says the template image scan checks them (spec 189), and a changelog fragment records the change.

**Implementation notes:**
- Header: drop "and Docker base images". Add one line saying that Dependabot cannot read the templates' Jinja Dockerfiles, so their base images are checked by the template image scan (`.github/workflows/template-image-scan.yml`, spec 189).
- The fragment (format per `docs/changelog.d/README.md`) names the distroless Node runtime of web-nextjs (no shell, no npm, CVE-2023-45853 gone, existing repos pick it up with `/platform:update`) and the platform's new template image scan with the expiring accepted list (A8).

**Done when:** the AC-189.7 acceptance test passes and `cplat platform pr-check` accepts the fragment.
