---
spec_id: 186-the-journey-waits-less
title: The journey waits less
status: done
priority: P1
shape: platform
tracks: [681, 684]
---

# 186 — The journey waits less

## Problem

Journey 11 (5.18.0) took 131 minutes and 35.0 M tokens. 68.4 of those minutes were waiting: CI 26.1, deploy 20.9, restore 9.5 and promotion 4.4. Several of these waits were not needed. When the API repo escalated on a decision while the web repo was still building, `cplat system ship next --wait` returned only when web finished, so the answer came about 10 minutes late (#684). That decision was itself needless: the plan split a store (t2) from the switch to it (t3), so t2's checks could never pass alone (#681). Component CI builds the image only after quality and test, so every main build runs about 4 minutes in series. Local Argo CD polls git only every 3 minutes, and the restore drill waits for that poll after its PR merged. `/component:release` reruns quality, test and security with three agents on a commit whose main CI already passed those gates. The round's target is at least 20 % below journey 10 (138 min, 43.4 M tokens): at most 110 minutes and 34.7 M tokens, in a journey with no platform defect.

## Stories

As someone shipping a system unattended, I want an escalated repo answered and resumed while the other repos keep building, so that one repo's decision does not wait for another repo's build.

As someone shipping a repo, I want a plan task that cannot pass before a later task to be merged with that task, so that the ship never stops to ask me about it.

As a component owner, I want the image built alongside the gates and Argo CD to see a merge within seconds, so that a merge reaches `dev` sooner, and no untested image is ever tagged.

As a component owner releasing a version, I want the release to rely on the tagged commit's green CI, so that the release does not repeat gates that already passed on the same commit.

**Repos:** sdlc-foundry (the platform: `cplat`, the system and component plugins, and the service-python, service-java, service-go, web-nextjs, gitops-app and cluster-gitops templates).

## Acceptance criteria

Escalated repos are answered while others build (#684).

- **AC-186.1** Given a system ship with repo A escalated (its ship ended with a reason or open questions, recorded by `repo result`) and repo B still running, when `cplat system ship next --json` runs, then the action is `answer`. The output gives A's id, cause, reason and questions word for word (each with its suggested answer, if it has one) and lists B under `running`. `cplat system ship next --wait` returns this action at its first poll after A's result is recorded and does not wait for B's phase to change. With no escalated repo that is still unanswered, `next` returns what it returns today.
- **AC-186.2** Given the action `answer`, when the coordinator runs `cplat system ship repo resume <A> --answer '<text>'`, then A's ship starts again in its own session from where it stopped, and that session receives the answer. The answer is recorded in the system ship run, A shows `running`, B's session is not touched, and the next `next` is `wait`. A resume of a repo that is not escalated, or that is unknown, exits 1 with one line naming the repo and its state, and changes nothing. The system ship instructions (with a rules-register entry, spec 168) answer an escalation of cause `decision` that has a suggested answer by resuming with that answer. Every other escalation is held (AC-186.3).
- **AC-186.3** Given the action `answer` for repo A, when the coordinator runs `cplat system ship repo hold <A>`, then A stays escalated and `next` no longer returns `answer` for it. Repos already running finish and no repo that depends on A starts. Once nothing runs and nothing can start, `next` returns `escalate` and the run ends escalated with the repo table, as AC-097.10 and AC-155.6 say.

A plan task that cannot pass alone (#681).

- **AC-186.4** Given a plan with tasks tN and tM, both not done, where tM depends on tN, when `cplat plan merge tN tM` runs, then tN is removed and tM takes the union of both tasks' files, covers and dependencies (without tN). Every task that depended on tN now depends on tM, the plan's `spec_hash` is unchanged, the plan check passes on the result, and the output names the merged tasks. If tN or tM is done or unknown, or tM does not depend on tN, the command exits 1 with one line giving the reason, and the plan is unchanged.
- **AC-186.5** Given a build whose task tN's checks fail only because a later task tM that depends on tN has not landed yet, when the build handles it, then the session runs `cplat plan merge tN tM` and goes on with the merged task. It does not escalate or ask the person, and the PR's "How this was built" block names both tasks and the reason. The run allowlist printed by `cplat headless --dry-run` allows `cplat plan merge`. The architect's instructions hold a rule, with a rules-register entry (spec 168), that a change and the change that makes its checks pass are one task.

Component CI builds the image alongside the gates.

- **AC-186.6** Given a project rendered from service-python, service-java, service-go or web-nextjs, when its CI runs on a pull request or on `main`, then the `docker` job does not wait for quality, test or security and builds each architecture while they run. The required check names stay the same (`docker` included). On a pull request no image is pushed.
- **AC-186.7** Given the same project's CI on `main`, when `docker` has pushed the images by digest, then the multi-arch manifest and its tags (`sha-<40>`, `latest`) are published only after every gate job of the run has passed: quality, test, security, `docker` and the image scan. `pin-dev` runs only after that publish. In a run where any gate is red or cancelled, no tag is created or moved and the dev pin is unchanged; the image exists only by digest.

Local Argo CD sees a merge sooner.

- **AC-186.8** Given a local cluster set up by the local-cluster script of the gitops-app or cluster-gitops template, when Argo CD is installed, then its git poll interval is 30 seconds. This holds on a fresh install and when the script runs again over an existing install. Both templates ship the same script.
- **AC-186.9** Given a database restore or discard by `cplat`, when its PR has merged, then `cplat` asks Argo CD once for a refresh of the addon app right away and says so in one line. It then waits for the app's revision as before. A refresh request that fails is reported in one line and the wait goes on.

The release reuses the tagged commit's green CI.

- **AC-186.10** Given `/component:release` for commit S, and a `ci` run of `main` on S whose latest attempt passed (quality, test, security, and the image build and scan when the repo has a Dockerfile) and finished at most 7 days ago, when the release reaches its gates, then it starts no quality, tester or security agent and runs no gate locally. It prints one line `gates: reused CI run <url> on <short sha>` naming the jobs, then goes on to the tag. The decision is one `cplat` call.
- **AC-186.11** Given the same release, when S has no `ci` run on `main`, or the run's latest attempt failed or was cancelled, or a gate job is missing or skipped, or the run finished more than 7 days ago, then the gates run as today (AC-148.8 included), after one line `gates: run locally (<reason>)`. A run that is still in progress is waited for with `cplat` (spec 143), and then this criterion or AC-186.10 applies.

## Non-goals

- The journey's own wall clock and token numbers are the round's goal, measured in the next journey, not acceptance criteria of this spec.
- A static plan-check rule that guesses whether a task's checks can pass alone (see A5).
- Changing which gates exist, the release-image re-tag of spec 106, or the tag-push scan.
- The git poll interval of non-local clusters (staging, prod or a remote cluster repo).
- Running quality, test and security in parallel with each other, or speeding up any single job.
- The library-python template, which builds no image.

## Assumptions

- **A1** `next` returns a new action `answer` for an escalated repo whether or not other repos are running. `escalate` keeps its meaning: nothing can start and nothing runs (other option: reuse `escalate` with a `running` list; affects AC-186.1, AC-186.3).
- **A2** The coordinator settles on its own only `decision` escalations that have a suggested answer. Causes `code`, `environment`, `platform` and `unknown`, and questions with no suggestion, are held for the user (other option: also retry `environment` once by resuming; affects AC-186.2, AC-186.3).
- **A3** A held repo reaches the user only when the run escalates as a whole, with the full repo table, not as a separate stop while other repos run (other option: escalate the run at once and let running sessions finish unobserved; affects AC-186.3).
- **A4** `cplat plan merge` merges into the later task (tM keeps its id and title) and only when tM depends directly on tN (other option: a transitive dependency too, or a new merged id; affects AC-186.4).
- **A5** #681 is handled by the architect's rule plus a merge the build may do on its own, not by a static plan check, because whether a task's checks can pass alone is known only when they run (other option: a plan-check heuristic on shared test entry points; affects AC-186.4, AC-186.5).
- **A6** On `main`, images are pushed by digest before the gates pass. An untagged digest is not deployable through any pin, so tagging is the gate (other option: build in parallel but push only after the gates, which costs the push time on the critical path; affects AC-186.7).
- **A7** The 30-second poll is set through Argo CD's reconciliation timeout, and the jitter stays at its default (other option: 60 seconds; affects AC-186.8).
- **A8** Right after the merge, restore and discard ask for a normal refresh, not a hard one. The existing 45-second hard refresh in the deploy waits (AC-153.1) is unchanged (other option: a hard refresh; affects AC-186.9).
- **A9** A CI run is reused for at most 7 days after it finished, so that the dependency audit result is not stale. A run green on a later attempt counts as green (other option: no age limit, relying on the tag-push scan; affects AC-186.10, AC-186.11).

## Open questions

## Changelog

- 2026-11-12 created
- 2026-11-12 approved
- 2026-11-12 building
- 2026-11-12 done
