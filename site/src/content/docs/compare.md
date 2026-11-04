---
title: "Compared with other frameworks"
description: "A platform team for a small team: what sdlc-foundry does that the spec-driven frameworks, coding agents and DevOps agents we compared do not, ranked by value, with the method and the sources."
sidebar:
  label: Compared with others
  order: 5
---

AI coding tools in 2026 fall into three groups, and each covers one part of the way from an idea to running software:

- **Spec-driven frameworks** ([GitHub Spec Kit](https://github.com/github/spec-kit), [Kiro](https://kiro.dev/docs/specs/), [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD), [OpenSpec](https://github.com/Fission-AI/OpenSpec), Claude Code plugin sets such as [ClosedLoop](https://github.com/closedloop-ai/claude-plugins)) turn a request into a spec, a plan and code. They stop at the code or the pull request.
- **Coding agents** (GitHub Copilot's coding agent, Devin, Cursor's cloud agents) take an issue and return a pull request. Merging, deploying and checking the result stay with you.
- **DevOps and GitOps agents** (GitLab Duo Agent Platform, Harness, kagent, Akuity) work on pipelines and clusters. They do not build a feature from a spec.

sdlc-foundry is both halves: **a platform team for a small team**. Agents build the feature, the platform runs it, and you decide only what matters. A spec you approve becomes tested code that is merged, deployed through GitOps and checked in a running environment, and what happens there comes back as the next issue. The platform half is included: one `system.yaml` renders every Kubernetes manifest, with secrets created in the cluster (no value in git), Postgres, cache, broker and buckets, OpenTelemetry, Kyverno policies, autoscaling and backups. Coding frameworks render no infrastructure, and developer platforms (Backstage, Port, Humanitec) do not build features with agents.

That combination shows in ten things none of the compared tools does.

## Ten things none of them does, ranked by value

Ranked by what each saves a small team: the work it takes off people, and the risk it removes.

| # | What sdlc-foundry does | Why it matters | What the others do |
|---|---|---|---|
| 1 | **From an approved spec to a feature running in dev, unattended.** `/component:ship` plans, writes failing acceptance tests, builds, reviews, opens the PR, merges on green CI, deploys through GitOps and runs the spec's smoke tests in dev. Your one decision is the spec. | The work after "the PR is open" (CI rounds, merge, pin, sync, smoke) is where features wait for days. | Spec Kit, Kiro, BMAD and OpenSpec stop at code; Copilot, Cursor and Devin stop at a pull request (Devin can auto-merge after review, none deploys). |
| 2 | **Acceptance tests are written first and locked.** `cplat spec test-diff` refuses any change to them beyond formatting; only you can approve one. | An agent that may edit the tests can make any build green. | Spec Kit asks for tests first; nothing we found stops an agent from weakening them later. Standalone lock tools exist ([agent-referee](https://github.com/vanovri/agent-referee)) but are not part of a delivery flow. |
| 3 | **Every criterion traces to production.** `cplat spec trace --chain` shows, per acceptance criterion: issue, spec, tests, reviewer verdict, merged PR, release and the version running in dev, staging and prod. | An audit or a "is this live?" question has one answer instead of an afternoon of digging. | Spec Kit links design choices to requirements; none links a criterion to what is deployed. |
| 4 | **Everything that can be code is tested code.** Checks, pushes, CI waits, merges, pins, smoke tests and promotions are `cplat` commands with more than 7,500 tests; agents do only the judgement work. | A prompt-only gate is skipped or misread on a bad day; a script answers the same every time. | Spec Kit's and BMAD's gates are checklists the model applies to itself; Kiro hooks run your own shell commands. |
| 5 | **Running systems file their own issues.** Red smoke tests, firing alerts (polled every 15 minutes), platform failures (one issue per signature) and a weekly retro with evidence-checked spec proposals all end as deduplicated issues you route in one triage. | Problems reach the backlog without someone watching dashboards. | BMAD Loop runs a retro per epic and ClosedLoop captures patterns; none turns production signals into issues. |
| 6 | **Prod runs the exact image staging tested.** Promotion compares registry digests and pins a release tag through a reviewed pull request that shows the evidence. | "It worked in staging" stays true in prod. | Not covered by the spec-driven frameworks or coding agents; DevOps platforms leave it to your pipeline design. |
| 7 | **One spec across several repos.** A system spec is split into one slice per repo with a validated, dependency-ordered plan and the contract between them; `/system:ship` ships them in that order to a running system. | Cross-service features are where hand-coordinated agents drift apart. | OpenSpec's Stores (beta) plan one change across repos; none ships them in order to a running system. |
| 8 | **Every generated repo stays current.** `/platform:fleet update` brings each repo built from the templates to the current release, one reviewed PR per repo, keeping the files the project owns. | Templates usually rot the day after scaffolding. | Spec Kit, BMAD and OpenSpec update one project at a time when you run their update inside it. |
| 9 | **Runs have a budget and stop on repeated failure.** One budget per run tree (default 180 minutes, 60 agent calls, 6 CI reruns, $15), a stop after two equivalent failures without progress, and the cost of every delivered feature in the run records. | Unattended runs cannot loop silently or burn money. | Hosted agents meter usage per seat or credit; none of the frameworks we read budgets a run or stops on a repeated failure. |
| 10 | **Autonomy is declared per environment, in git.** `system.yaml` sets per environment how far an always-on engine may fix a running system (observe, advise, propose, act), with limits: changed files and lines, a regression test, a second review, merges per day, a time window. Every action can be undone within a window, a pause acts at once, and an engine never promotes forward. | Letting automation fix production is safe only when the limits are reviewed like code and can be taken back. | The operations agents we read (kagent, Akuity, Harness) act through your existing pull request approvals; we found none that declares levels and limits per environment with an undo window and a pause. |

## Where others are ahead

- **Portability.** Spec Kit works with more than 30 coding agents; sdlc-foundry runs on Claude Code only.
- **An IDE experience.** Kiro builds specs into its editor; sdlc-foundry works in the terminal, with an optional [local console](/sdlc-foundry/guides/console/).
- **Any stack, any host.** The frameworks above work in any repository. sdlc-foundry generates Python, Java, Go and Next.js components, needs GitHub, and deploys to Kubernetes.
- **Maturity.** It is a young, single-maintainer project; see the [honest limits](/sdlc-foundry/value/#honest-limits).

## How we compared

Compared on 2026-11-04 from each tool's own documentation (README, docs pages) and, where none covered a point, recent independent write-ups. A tool counts as "not doing" something when its documentation does not describe it; tell us in an [issue](https://github.com/ika100/sdlc-foundry/issues/new/choose) when that is out of date and we will correct the page.

Sources: [Spec Kit](https://github.com/github/spec-kit) and its [method](https://github.com/github/spec-kit/blob/main/spec-driven.md) · [Kiro specs](https://kiro.dev/docs/specs/) and [hooks](https://kiro.dev/docs/hooks/) · [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) · [OpenSpec](https://github.com/Fission-AI/OpenSpec) · [ClosedLoop plugins](https://github.com/closedloop-ai/claude-plugins) · [Copilot coding agent limits (Microsoft Learn)](https://learn.microsoft.com/en-us/training/modules/github-copilot-code-agent/2-security-risks-limitations-copilot-code-agent) · [Cursor and Windsurf background agents and deployment](https://bex.co/blog/2026/07/18/ai-ide-background-agents-deploy-gap) · [Devin and its deployment flow](https://www.deployhq.com/guides/devin) · [GitLab Duo issue to merge request flow](https://docs.gitlab.com/user/duo_agent_platform/flows/issue_to_mr/) · [GitLab Duo deployment agent](https://about.gitlab.com/blog/automate-deployment-with-duo-agent-platform/) · [Harness AI agents](https://www.harness.io/press-and-news/harness-adds-autonomous-ai-agents-to-automate-devops-workflows) · [kagent](https://kagent.dev/) · [Akuity agents](https://akuity.io/blog/beyond-dashboards-ai-agents-for-gitops-operations) · [autonomy per environment](/sdlc-foundry/guides/autonomy/) · [developer portals in 2026](https://northflank.com/blog/top-internal-developer-portals) · [agent-referee](https://github.com/vanovri/agent-referee).
