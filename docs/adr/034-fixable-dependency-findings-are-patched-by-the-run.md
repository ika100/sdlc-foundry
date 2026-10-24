# ADR-034 — Fixable dependency findings are patched by the run

**Status:** accepted (2026-10-24, spec 095)

## Context

Every template's security gate fails on dependency findings: pip-audit on any finding, `pnpm audit --audit-level
high`, OWASP Dependency-Check at CVSS 7, and trivy at HIGH. Unattended `/svc:build` and `/svc:ship` runs stopped at
the first such finding, even when the advisory named a fixed version. The fix is almost always the same mechanical
step: bump the package and re-run the gates. The user decided that this step needs no human (spec 095, round decision
6). The run should stop only where there is a real decision.

## Decision

- Every non-gitops shape ships two recipes with one contract: `devbox run deps-findings <out>` writes the gate
  scanner's machine-readable report, and `devbox run deps-bump <package> <version>` moves one package to one version
  and updates the lock. For a transitive package, the recipe adds an override or constraint for that one package, and
  only when the shape cannot force the version otherwise. An unknown package is refused before any file changes.
  `gitops-app` has no such recipes and never bumps.
- `cplat deps patch` is the only thing that bumps dependencies in a run. It patches what turns the gate red, at the
  gate's own threshold, to the lowest fixed version. A major bump is allowed and marked. It makes one commit per bump,
  then re-runs the CI gates, and makes at most 2 rounds per run. A bump that turns any gate red is reverted to the
  exact files from before the bump. The run escalates when no fix exists, when a bump breaks a gate, or when the
  rounds are used up.
- Agents never bump dependencies. The security agent still only reports.
- Base-image OS packages, the image scan, secrets and bandit findings are not dependency findings. They keep their
  current handling (spec 059 for base images).

## Consequences

- A run reaches dev without waiting for the user on a mechanical bump. The PR body and the final report list every
  bump with its advisory and versions, and mark major bumps. The run record's `patches` section shows how often runs
  patch, what fails, and which packages recur.
- A new shape must ship `deps-findings` and `deps-bump`: `shapes.py check` enforces it.
- `/svc:release` and `/shared:check-quality` are unchanged. A red security gate still stops a release.

## Not included

- Patching repos at rest (a scheduled or fleet-wide audit): a later spec, after spec 096.
- Upgrading dependencies that have no finding, and changing base images.
