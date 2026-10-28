---
spec_id: 109-every-requirement-traces-to-its-evidence
title: Every requirement traces to its evidence
status: approved
priority: P2
tracks: [164]
---

# 109 — Every requirement traces to its evidence

## Problem

Issue #164 asks that traceability from requirements to evidence stay native, because it is core product data. Spec 107 leaves it out for that reason, and no spec covers it yet. Most links already exist, but each lives in a different place, and nothing shows the whole chain for one criterion.

Already linked today:

- issue → spec: `tracks:` in the front matter, the issue claim of spec 082, and `Closes #n` in the PR body;
- spec → criterion: `AC-<NNN>.<n>` ids, checked by `cplat spec check` (ADR-026);
- criterion → task: `covers:` and `spec_hash` in the plan;
- criterion → test: `cplat spec trace <id>` lists the test files that name each active criterion, including smoke tests (spec 091), and `cplat spec ci` warns about untraced criteria of specs that are being built or are done;
- criterion → verdict: the per-criterion table in `verification.md`, and `done` needs `**Result:** pass` (spec 068);
- run → spec: run records (spec 087) name the spec and the outcome; the ship state holds the PR and merge commit while the run lasts;
- release → environment: the prod evidence summary of spec 093 shows, for one release, which commit staging runs and the smoke outcomes there.

Missing:

- a single view per criterion;
- tests that name a criterion that no longer exists or was withdrawn;
- a verdict per criterion (today only the overall result is read);
- a verification made before the criteria last changed;
- the PR that delivered a spec, found once the ship state is gone;
- whether a release contains that PR's merge commit;
- whether an environment runs that release;
- any way to tell a missing link from one that could not be checked.

## Stories

As the platform owner, I want one command that shows, for every criterion of a spec, the chain from the issue to the environment running it, so that I can show where each requirement stands without reading five files and three systems.

As a reviewer, I want every missing or stale link named, so that a gap (no test, an orphan test, an old verification, an unreleased merge) is fixed before anyone relies on it.

As a developer working offline, I want the local links checked and the remote ones marked `unknown`, so that the report never claims evidence it could not see.

## Acceptance criteria

The chain. For one spec, the chain per active criterion is: issue(s) the spec tracks → spec (status) → criterion → test(s) naming it → its verdict in `verification.md` → the PR that delivered it → the release that contains the PR's merge commit → the environment(s) whose pinned image is that release or a later one. Each link has one state: `ok`, `missing`, `stale`, `unknown` (with the reason) or `n/a` (with the reason, for example "spec not yet done" or "library: no environments").

- **AC-109.1** Given a spec, when `cplat spec trace <id> --chain` runs, then it prints one block per active criterion with every link of the chain and its state, followed by a summary line counting criteria whose chain is complete, and a list of every link that is `missing` or `stale`. With `--json` the same data is printed as one JSON document. The chain is a flag on the existing verb, not a new verb, and the existing `cplat spec trace <id>` without `--chain` keeps its output and exit code, which `cplat ship` reads.
- **AC-109.2** Given a spec whose status is `draft` or `approved`, when the chain is shown, then the links after "criterion" that cannot exist yet (verdict, PR, release, environments) are `n/a: spec not yet built`, and a missing test is `n/a` for `draft` and `missing` from `approved` on. Given `building`, then verdict, PR, release and environments are `n/a: spec not yet done`.
- **AC-109.3** Given a test file that names an id of this spec that is not an active criterion (withdrawn or never defined), when the chain is shown, then it is listed under "orphan tests" with the file and the id, and marked `stale` ("names withdrawn AC-109.4" or "names unknown AC-109.14").
- **AC-109.4** Given a `done` spec, when the chain is shown, then the verdict link of each criterion is read from the criterion's row in `verification.md`. `met` is `ok`, `not met` or `partial` is `missing` with the verdict, and a criterion without a row is `missing: not verified`. A `done` spec without `verification.md` (accepted with `--unverified`, spec 068) shows the recorded reason on every verdict link.
- **AC-109.5** Given a `verification.md` whose recorded commit is older than the last commit that changed the spec's criteria, or that has a row for an id that is no longer an active criterion, when the chain is shown, then the verdict links are `stale: criteria changed after verification (<commit>)` or `stale: verified a withdrawn criterion`.
- **AC-109.6** Given a `done` spec, when the PR link is resolved, then the PR is the merged PR whose head branch is `feature/<spec_id>` in the spec's repo, the branch convention `cplat ship` uses; a spec delivered from any other branch shows the PR link as `missing: no merged PR from feature/<spec_id>`. With `gh` available and authenticated, its number, merge commit and merge date are shown. With no merged PR the link is `missing`, and with several the newest is shown and the others are listed.
- **AC-109.7** Given a PR with a merge commit present in the local clone, when the release link is resolved, then the release is the oldest `vX.Y.Z` tag in the local clone that contains the merge commit. No such tag gives `missing: merged, not in a release`. When the merge commit is not in the local clone, the link is `unknown: merge commit not fetched`.
- **AC-109.8** Given a service whose repo is registered in a gitops-app that can be reached (a local checkout or, with `gh`, its default branch), when the environment links are resolved, then for each of `dev`, `staging` and `prod` the pinned image tag is shown. The pins are read from the gitops-app, never from the cluster. An environment counts as `ok` when its tag is the release or any later `vX.Y.Z` release (a later release contains the merge commit), or a `sha-<40>` commit that contains the merge commit. It is `missing: runs <tag>, older than <release>` when the tag is older, and `n/a: not deployed to <env>` when the service is not pinned there.
- **AC-109.9** Given `gh` missing, not authenticated or offline, or a gitops-app that cannot be reached, when the chain is shown, then every link that needs them is `unknown: <reason>` (for example `unknown: gh not authenticated`). The command still checks every local link, prints one note naming what it could not reach, and never shows an unchecked link as `ok` or as `missing`.
- **AC-109.10** Given a spec with `tracks:`, when the issue link is resolved, then each issue number is shown. With `gh` available, its state is also shown, and an issue that is still open on a `done` spec is `stale: issue still open`. Given a spec without `tracks:`, then the issue link is `n/a: no tracked issue`.
- **AC-109.11** Given any result, when `--chain` finishes, then the exit code is 0 when the chain was printed, whatever links are missing, stale or unknown. It is non-zero only when the spec cannot be found or read, with the error naming the spec. There is no option (such as `--strict`) that makes the chain exit non-zero because of its links.
- **AC-109.12** Given the chain, when it runs, then it changes no file, issue, PR, tag or environment, and its only remote calls are reads through `gh`. Given no remote access at all, it finishes within 30 seconds on a repo with 100 specs.
- **AC-109.13** Given a repo of any shape whose test files name an id `AC-<NNN>.<n>` where `<NNN>` is a spec in that repo but the id is not an active criterion of it (withdrawn or never defined), when `cplat spec ci` runs, then it prints one warning per orphan naming the file, the id and whether it is withdrawn or unknown. The warning stays a warning with `--strict`, it never changes the exit code, and ids whose number matches no spec in the repo are not reported.

## Non-goals

- An external traceability tool, a database or a new store; the chain is read each time from the repo, git, `gh` and the gitops-app.
- A new CI gate or a required check that blocks merges, or a `--strict` mode for the chain; the chain only reports, and `cplat spec ci` only gains the orphan-test warning of AC-109.13.
- A repo-wide summary (`--chain` for all specs, one line per spec); a possible follow-up once the single-spec view proves useful.
- Changes to the spec, plan, test-tagging or `verification.md` formats.
- Tracing product specs (gitops-app shape) across their component repos; each component repo's slice is traced in that repo.
- Proving that tests pass. The chain shows that a test names the criterion and what the reviewer recorded; CI and the build prove that tests pass (ADR-026).
- Smoke outcomes per environment, which the prod evidence summary of spec 093 already shows.
- Reading the cluster directly (Argo CD or the Kubernetes API); environments are read from the gitops-app's pins only.

## Open questions

- ~~Should the chain be a flag on the existing `cplat spec trace` or a new verb?~~ Answered: a flag, `cplat spec trace <id> --chain`, with plain `trace` unchanged because `cplat ship` reads its output and exit code, see AC-109.1.
- ~~Should the chain ever fail, for example with a `--strict` flag that exits 1 on any `missing` or `stale` link?~~ Answered: no, report only, see AC-109.11 and the non-goals.
- ~~How is the PR that delivered a spec found?~~ Answered: the merged PR from branch `feature/<spec_id>`, the convention `cplat ship` uses; a spec delivered on another branch shows `missing`, see AC-109.6.
- ~~Should `cplat spec ci` also warn about orphan tests (AC-109.3) in every repo?~~ Answered: yes, as a warning only, which adds no blocking gate, see AC-109.13.
- ~~Should there be a repo-wide summary (`--chain` for all specs, one line per spec)?~~ Answered: not in this spec; a follow-up if the single-spec view proves useful, see the non-goals.
- ~~Should an environment count as `ok` when it runs a later release than the one that contains the PR?~~ Answered: yes, a later release contains the merge commit, see AC-109.8.
- ~~Confirm: reading the cluster (Argo CD) is out of scope, and environments are read from the gitops-app pins.~~ Answered: yes, see AC-109.8 and the non-goals.
- ~~Confirm: the 30-second offline limit for a repo with 100 specs.~~ Answered: yes, see AC-109.12.

## Changelog

- 2026-10-25 created
- 2026-10-25 open questions answered (suggested answers)
- 2026-10-25 approved
- 2026-10-28 reading for 5.x: "a service whose repo is registered in a gitops-app" is a component of a system; its pinned tags are read from `instances.<env>` in `system.yaml`
