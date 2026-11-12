---
spec_id: 189-the-web-image-has-no-known-critical-cve
title: The web image has no known critical CVE and the platform scans template images
status: approved
priority: P1
shape: platform
tracks: [682]
---

# 189 — The web image has no known critical CVE and the platform scans template images

## Problem

In journey 11 on 5.18.0, scanning the image of a repo generated from the web-nextjs template reported a critical CVE (CVE-2023-45853, zlib) in the Debian base image of its runtime stage. Debian marks it "won't fix", so no newer `node:<major>-slim` tag will remove it. Every web repo made from the template ships this finding. The platform found it only in a journey, because its own CI builds template images without scanning them. Dependabot cannot catch it either: it moves image tags and never looks at OS packages. Also, the platform's Dependabot configuration has no Docker entry for templates (it cannot read Jinja Dockerfiles), although its header comment says it covers "Docker base images".

## Stories

As a developer who generates a web repo, I want its image to have no known critical vulnerability, so that my first image scan and release are not blocked by a finding I cannot fix.

As a platform maintainer, I want the platform's CI to scan every template's built image, so that a critical CVE in a template base image fails a platform run instead of first showing up in a downstream repo or a journey.

As a platform maintainer, I want an accepted "won't fix" finding to need a written reason and a review date, so that an exception stays visible and gets looked at again.

## Acceptance criteria

- **AC-189.1** Given a repo generated from the web-nextjs template with default answers, when its image is built and scanned for CRITICAL vulnerabilities (fixed and unfixed), then the scan finds no CRITICAL vulnerability, CVE-2023-45853 is not among the findings, and the runtime image has no shell, no package manager and no npm (starting the image with `sh` as the command fails).
- **AC-189.2** Given that image, when it is started as UID 1000 with a read-only root filesystem, then `/api/health` answers 200 within 60 seconds, the image's health check reports `healthy`, the browser smoke prints `smoke: 1 passed, 0 failed, 0 skipped`, and the running Node's major version equals the template's pinned `node_major` (ADR-005).
- **AC-189.3** Given a pull request that changes a template with an image (service-python, service-java, service-go, web-nextjs), when the platform's CI runs, then a job builds the image of each changed template's default render and scans it for CRITICAL and HIGH vulnerabilities, fixed and unfixed. A CRITICAL finding that is not on the accepted-finding list fails the job, and the job log names the template, CVE id, package and installed version. HIGH findings are listed but do not fail the job.
- **AC-189.4** Given no change to any template, when the platform's daily scheduled run happens, then the images of all four templates are scanned under the AC-189.3 rules, and a CRITICAL finding that is not accepted makes that run fail and names the template.
- **AC-189.5** Given an accepted-finding list entry with template, CVE id, reason and a review-by date no more than 90 days after the entry was added, when the scan finds that CVE in that template's image, then the job passes and prints the finding as `accepted: <CVE> in <template>: <reason> (review by <date>)`. Each entry covers only the template it names.
- **AC-189.6** Given an accepted-finding entry with no reason, a review-by date that has passed or is more than 90 days after it was added, or a CVE the scan no longer finds in that template's image, when the scan of that template runs, then the job fails and names the entry and what is wrong with it (`no reason`, `review date passed`, `review date too far`, `no longer found`).
- **AC-189.7** Given the platform repo's Dependabot configuration, when a maintainer reads its header comment, then it no longer says it updates Docker base images, and it says template base images are checked by the template image scan (AC-189.3).

## Non-goals

- Fixing HIGH or lower findings in any template image; the scan reports them, and they get their own issues.
- Changing the base images of the service-python, service-java or service-go templates. The only exception is a critical finding that the answer to the open question does not accept.
- Changing the deps and builder stages of the web template; they are not shipped, so they stay on `node:<major>-slim`.
- Shipping the accepted-finding list to generated repos, or changing the generated repos' own image scan rules (they block fixable HIGH/CRITICAL findings on release, as today).
- A Dependabot Docker entry for templates (Dependabot cannot read Jinja Dockerfiles).
- Scanning the gitops-app, cluster-gitops and library-python templates, which build no image.

## Assumptions

- **A1** The web runtime stage uses a distroless Node image of the same pinned Node major; the upgrade and npm-removal steps that the slim image needed are dropped, because the distroless image has neither (other option: a different minimal base such as Alpine; affects AC-189.1, AC-189.2).
- **A2** The platform scan fails on CRITICAL only, fixed or unfixed, and HIGH is report-only (other option: also fail on fixable HIGH, like a generated repo's release scan; affects AC-189.3).
- **A3** The scan covers unfixed findings, unlike a generated repo's CI (`ignore-unfixed`), because "won't fix" is exactly the case this spec is about (other option: fixable only; affects AC-189.3, AC-189.4).
- **A4** The scan runs on pull requests that change a template with an image, and on the existing daily schedule for all four, because new CVEs are published without any code change (other option: weekly, or PRs only; affects AC-189.3, AC-189.4).
- **A5** The accepted-finding list is a reviewed file in the platform repo. An entry has template, CVE id, reason and review-by date, at most 90 days out, and adding or extending one goes through a normal PR review (other option: no expiry; affects AC-189.5, AC-189.6).
- **A6** An entry whose CVE is no longer found fails the scan, so that the list does not keep stale exceptions (other option: a warning only; affects AC-189.6).
- **A7** The scan uses the same scanner and version the templates already pin for their own image scan (trivy), so that the platform and the generated repos agree on findings (other option: a second scanner; affects AC-189.3).
- **A8** The build adds a changelog fragment `682-web-image-distroless.fixed.md` that names the distroless runtime and the new platform scan. A web repo picks up the change with `/platform:update` (other option: `changed` section; affects no criterion).
- Decided by the user (2026-11-12): a critical "won't fix" finding in the service-python, service-java or service-go image is accepted on the list with a reason and a review-by date, and one follow-up issue is opened per template; switching those base images is a non-goal of this spec.

## Open questions

None.

## Changelog

- 2026-11-12 created
- 2026-11-12 approved
