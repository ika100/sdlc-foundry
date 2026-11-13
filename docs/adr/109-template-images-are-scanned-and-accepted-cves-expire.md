# ADR-109: Template images are scanned and accepted cves expire

**Status:** Proposed (2026-11-13)

## Context

The templates scan the images of generated repositories, but nothing scanned the platform's own default renders, so a
known CRITICAL CVE in a template's base image reached every new repository (spec 189).

## Decision

The platform scans every template image on PRs and daily; a CRITICAL finding fails unless a reviewed entry with a reason accepts it for at most 90 days

The scan runs in its own workflow, `template-image-scan.yml` (pull request, daily, manual), because `ci.yml` treats every
non-PR event as "run everything". A `decide` job picks the changed templates (as `e2e.yml` does, ADR-080). Trivy reports
CRITICAL and HIGH, fixed and unfixed; `scripts/template-image-scan.py evaluate` fails on an unaccepted CRITICAL. HIGH
findings are listed only. Accepted findings live in `.github/image-scan-accepted.yml`: per template and CVE, with a
reason, an `added` date and a `review_by` date at most 90 days later. An entry with no reason, a passed or too distant
review date, or a CVE the scan no longer finds fails the job.

## Consequences

An accepted CVE cannot be forgotten: it fails the scan when its review date passes or when the base image is fixed, and a
person decides again. A new CVE in a base image can turn the daily run red without any change in the repository. The list
is platform-only and is never rendered into a template.
