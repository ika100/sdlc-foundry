---
spec_id: 186-the-journey-waits-less
shape: platform
spec_hash: "22129676bd6d"
summary: Escalated repos answered while others build, cplat plan merge for a task that cannot pass alone, the image built alongside the gates and tagged after them, a 30 s local Argo CD poll and a refresh after restore, and a release that reuses the commit's green CI
tasks:
  - id: t1
    title: cplat plan merge, its run event and hand-back line
    files: [scripts/cplat/plancmd.py, scripts/cplat/cplat.py, scripts/cplat/runs_agents.py, scripts/cplat/runs_built.py]
    covers: [AC-186.4, AC-186.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Ship escalations carry questions; a resumed ship records and shows the answer
    files: [scripts/cplat/ship.py]
    covers: [AC-186.1, AC-186.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: The answer action, hold and resume in the system ship scheduler
    files: [scripts/cplat/appship_sched.py, scripts/cplat/appship_proc.py, scripts/cplat/appship_state.py]
    covers: [AC-186.1, AC-186.2, AC-186.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: Run allowlist allows cplat plan merge
    files: [scripts/cplat/preflight.py]
    covers: [AC-186.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: Unit mode reads a task gone from the plan as merged
    files: [scripts/cplat/units.py]
    covers: [AC-186.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: Restore and discard ask Argo CD for one refresh after the merge
    files: [scripts/cplat/dbrestore.py]
    covers: [AC-186.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: Local Argo CD polls git every 30 seconds
    files: [templates/gitops-app/scripts/local-cluster.sh, templates/cluster-gitops/scripts/local-cluster.sh]
    covers: [AC-186.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t8
    title: Component CI builds the image alongside the gates and tags it after them
    files: [templates/service-python/.github/workflows/ci.yml, templates/service-java/.github/workflows/ci.yml, templates/service-go/.github/workflows/ci.yml, templates/web-nextjs/.github/workflows/ci.yml]
    covers: [AC-186.6, AC-186.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t9
    title: cplat component release gates decides reuse or local gates
    files: [scripts/cplat/comprelease.py]
    covers: [AC-186.10, AC-186.11]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t10
    title: System ship CLI for answer, hold, resume and escalation questions
    files: [scripts/cplat/appship.py, scripts/cplat/appship_report.py]
    covers: [AC-186.1, AC-186.2, AC-186.3]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t11
    title: Component ship prompt passes questions and applies the system ship's answer
    files: [plugins/component/commands/ship.md, docs/rules/plugins/component/commands/ship.yml]
    covers: [AC-186.1, AC-186.2]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t12
    title: Build merges a task that cannot pass alone; the architect plans them as one
    files: [plugins/component/commands/build.md, plugins/svc/agents/architect.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/svc/agents/architect.yml]
    covers: [AC-186.5]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t13
    title: Release prompt reuses the green CI run through cplat
    files: [plugins/component/commands/release.md, docs/rules/plugins/component/commands/release.yml]
    covers: [AC-186.10, AC-186.11]
    parallel_safe: true
    depends_on: [t9]
    done: true
  - id: t14
    title: System ship prompt answers or holds an escalated repo
    files: [plugins/system/commands/ship.md, docs/rules/plugins/system/commands/ship.yml]
    covers: [AC-186.2, AC-186.3]
    parallel_safe: true
    depends_on: [t10]
    done: true
  - id: t15
    title: Guides, changelog fragment and plugin versions
    files: [docs/unattended-delivery.md, docs/AGENTS.md, docs/changelog.d/186-the-journey-waits-less.changed.md, .claude-plugin/marketplace.json, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json]
    covers: [AC-186.2, AC-186.5, AC-186.10]
    parallel_safe: true
    depends_on: [t11, t12, t13, t14]
    done: true
---

# Plan — 186 The journey waits less

Contract and decisions: [design.md](design.md). Level 1: t1–t9 (the cplat modules, the templates). Level 2: t10 (system
ship CLI), t11–t13 (prompts whose `cplat` commands now exist). Level 3: t14 (system ship prompt, after its CLI). Level 4:
t15 (docs, versions). The prompt tasks depend on their commands because `cplat platform rules check` fails a prompt
that names an unknown `cplat` command. No two tasks of a level share a file.

## t1 — cplat plan merge, its run event and hand-back line

**Files:** scripts/cplat/plancmd.py, scripts/cplat/cplat.py, scripts/cplat/runs_agents.py, scripts/cplat/runs_built.py
**Covers:** AC-186.4, AC-186.5 (the "How this was built" line)
**Goal:** a build can fold task tN into a later task tM that depends on it in one command. The plan stays valid and
the run's PR block names the merge.

**Implementation notes:**
- `plancmd.main(argv)`: subcommand `merge` with the arguments, checks, result, prose edit, commit and output lines
  exactly as in design.md, Contract, "`cplat plan merge`".
- Read the plan through `spec.find(repo, ref).plan`. Build the merged metadata in memory, run `spec.check_plan` on a
  `Spec` carrying it (write to a temp copy, or check before writing) and refuse on the first error before touching the
  file.
- Write the metadata with `spec.save` and keep `spec_hash` as the same quoted string (it is read from the text,
  `spec.plan_hash`). Edit the prose by `## <id> — ` section boundaries.
- Commit with `core.git_identity`, `-s`, `-- <plan path>` only.
- `parallel_safe` rule: after the merge, compute `spec.topo_levels`. If tM shares a file with a `parallel_safe` task of
  its level, set tM to `false`.
- `cplat.py`: `PLUMBING["plan"] = "plancmd"`. Add docstring lines for `cplat plan merge <tN> <tM> [--spec ID] [--reason R]`
  and for `cplat component release target|wait|gates` (t9's verb; the docstring lives here).
- `runs_agents.task_merge(run_id, repo, task, into, reason)`: event `task-merge` under the architect identity, through
  `_change`/`_guard` like `replan`. Never raises.
- `runs_built.collect`: a `task-merge` event becomes the hand-back `merged task <task> into <into>: <reason>`.

**Done when:** the AC-186.4 acceptance tests pass. A unit test of the dependant rewrite and of the cycle refusal passes.
A `runs_built.render` test shows the hand-back line.

## t2 — Ship escalations carry questions; a resumed ship records and shows the answer

**Files:** scripts/cplat/ship.py
**Covers:** AC-186.1 (questions on the repo's escalation), AC-186.2 (the session receives the answer)
**Goal:** a component ship's escalation states its questions in a form the system ship can show verbatim, and the
session resumed by the system ship is given the answer.

**Implementation notes:**
- `escalate(..., questions: list[str] | None = None)`: when given, `st["questions"] = [{"text": q["text"],
  "suggested": (q["options"] or [None])[0]} for q in map(specmod._question, questions)]`. A later escalation without
  questions removes the key.
- CLI `escalate`: `--question` (repeatable, `action="append"`).
- `start`, resume branch (`st and st["spec"] == sp.id`): pop `questions` with `escalated`/`cause`. Read
  `os.environ.get("CPLAT_SHIP_ANSWER")`. If it is set, append `{"at", "text"}` to `answers` unless the last one has the
  same text, and `say("answer from the system ship: <text>")`.
- `describe`: the line `  answer from the system ship: <latest>` when `answers` is non-empty.
- Nothing else changes in the module.

**Done when:** unit tests cover escalate with and without `--question` (suggested and not), and a resume with
`CPLAT_SHIP_ANSWER` printing and recording the answer once over two starts. The ship tests stay green.

## t3 — The answer action, hold and resume in the system ship scheduler

**Files:** scripts/cplat/appship_sched.py, scripts/cplat/appship_proc.py, scripts/cplat/appship_state.py
**Covers:** AC-186.1, AC-186.2, AC-186.3
**Goal:** `next` names an escalated repo to answer while others run. The repo can then be resumed with an answer in
its own session, or held until the run escalates.

**Implementation notes:**
- `next_action`: add `held` and the `answer` action and object exactly as in design.md, Contract, "`next --json`".
  `answer` is checked after `done` and before `running`. Starts stay blocked while any repo is escalated (the existing
  `stopped`).
- `questions_of(reason, stored)` as in the contract. `result` copies `sh.get("questions")` onto the entry with
  `reason`/`cause` (escalated outcome), and removes it otherwise. `escalate_repo(..., questions=None)` stores
  parsed questions.
- `hold_repo(gitops, id) -> str` and `resume_repo(gitops, id, answer) -> dict` with the refusals, state changes and
  lines of the contract. Refusals raise `PlatformError` with no hint (one line). Resume calls `launch(gitops, id, 1,
  answer=answer)` after the state update. `launch` passes `answer` on.
- `appship_proc.spawn(..., answer: str | None = None)`: `env["CPLAT_SHIP_ANSWER"] = answer` when given, and otherwise
  removes an inherited one.
- `appship_state.start` (resume of the whole run): pop `held` and `questions` with `reason`/`cause`. `next_step`
  for `repos` mentions the `answer` action (`repo resume` / `repo hold`).
- `shipwait.next_wait` needs no change (it returns the first non-`wait` action). Confirm this with a test, do not edit
  it.

**Done when:** the AC-186.1–3 acceptance tests that drive the module functions pass. One test covers A escalated
with B running: `answer` → resume → `wait`, B's entry unchanged. Another covers hold: B ends, then `escalate`. The
spec 097/155/169 system ship tests stay green.

## t4 — Run allowlist allows cplat plan merge

**Files:** scripts/cplat/preflight.py
**Covers:** AC-186.5 (`cplat headless --dry-run` allows it)
**Goal:** an unattended build or ship session may run `cplat plan merge` without a permission prompt.

**Implementation notes:**
- `run_allowlist`: append `Bash(cplat plan merge *)` for `/component:build`, `/component:ship` and `/system:ship`,
  after the git rules. Keep the order stable and de-duplicated.
- `_self_check`: assert no refused rule matches `cplat plan merge t2 t3`.

**Done when:** a `run_allowlist` test and the AC-186.5 dry-run acceptance test (through the existing headless
dry-run path) show the rule.

## t5 — Unit mode reads a task gone from the plan as merged

**Files:** scripts/cplat/units.py
**Covers:** AC-186.5 (the session goes on with the merged task)
**Goal:** after `cplat plan merge tN tM` in tN's unit session, tN's unit checkpoints and tM's unit carries the work,
instead of stalling on a task that no longer exists.

**Implementation notes:**
- `_evaluate`, task branch: `ids = {str(t["id"]) for t in _plan_tasks(sp)}`. A task counts as finished when it is
  `_done_in` or not in `ids` (and the committed plan exists). `open_` lists only tasks present and not done.
- `_derive`: the same rule when marking units of a `build` phase.
- No change to `_ids_from`: a later `prepare` drops the gone unit by itself.

**Done when:** a unit test with a committed plan where t2 was merged into t3 shows `detect(..., "task:t2")` returns
the head and `task:t3` still needs t3 done.

## t6 — Restore and discard ask Argo CD for one refresh after the merge

**Files:** scripts/cplat/dbrestore.py
**Covers:** AC-186.9
**Goal:** a restore or discard does not wait for Argo CD's next git poll after its PR merged.

**Implementation notes:**
- In `_publish` on the Argo CD path, after `head` and before the deadline loop: the annotate call and the two lines
  of design.md, Contract, "Restore refresh", through `backupstate.kubectl` (the seam the tests replace).
- Exactly one refresh request per `_publish`. The loop, its timeout and `_only_prune_left` are unchanged.

**Done when:** the AC-186.9 acceptance tests pass (refresh asked once, before the first status read; a failing
annotate is one line and the wait still completes).

## t7 — Local Argo CD polls git every 30 seconds

**Files:** templates/gitops-app/scripts/local-cluster.sh, templates/cluster-gitops/scripts/local-cluster.sh
**Covers:** AC-186.8
**Goal:** Argo CD on a local cluster sees a merge within about 30 seconds, on a fresh install and on a re-run.

**Implementation notes:**
- Insert the block of design.md, Contract, "Local Argo CD", after the `rollout status` loop of the `with_argo` install,
  in both scripts identically (both files must stay byte-identical where they are today).
- Use the script's `k` wrapper. Do not touch `timeout.reconciliation.jitter`.
- `shellcheck` clean (the template lint of spec 184 runs it when it is configured).

**Done when:** the AC-186.8 acceptance tests pass and `devbox run smoke-gitops` (or the template lint) stays green.

## t8 — Component CI builds the image alongside the gates and tags it after them

**Files:** templates/service-python/.github/workflows/ci.yml, templates/service-java/.github/workflows/ci.yml, templates/service-go/.github/workflows/ci.yml, templates/web-nextjs/.github/workflows/ci.yml
**Covers:** AC-186.6, AC-186.7
**Goal:** the image build no longer waits for quality and test. No tag and no dev pin exist for a run with a red or
cancelled gate.

**Implementation notes:**
- Per file, exactly the changes of design.md, Contract, "Component CI". Remove `needs: [quality, test]` from `docker`.
  Set `docker-publish` to `needs: [quality, test, security, ci-extra, docker]` with `if: success() && …`.
- Keep the Jinja escaping (`${{ '{{' }} … {{ '}}' }}`) exactly as written. No job is renamed, and `release-image` and
  `pin-dev` do not change.
- Update the comment above the docker matrix only if it names the old order.

**Done when:** the AC-186.6/7 acceptance tests (parsing the rendered workflows) pass, `actionlint` on a rendered
project passes, and `scripts/pin-actions.py --check` passes.

## t9 — cplat component release gates decides reuse or local gates

**Files:** scripts/cplat/comprelease.py
**Covers:** AC-186.10, AC-186.11
**Goal:** one `cplat` call tells `/component:release` whether main's green CI run on the commit replaces its local
gates.

**Implementation notes:**
- `gates(repo, sha, timeout, interval, now=None) -> tuple[int, dict]` and the `gates` subparser, with the calls, gate
  rules, lines, exit codes and JSON of design.md, Contract, "`cplat component release gates`".
- `gh` through `ship.gh(..., check=False)` and the slug from `ship.service_slug`. If a call fails, give the
  `cannot read the ci runs` reason (never reuse on doubt).
- Age from the run's `updatedAt` against `now` (a parameter for tests). `MAX_AGE_DAYS = 7`.
- Polling through `waits.sleep`/`waits.now`. Record the whole call with `waits.record(repo, "component release gates", …)`.
- Update the module docstring with the verb. The `cplat.py` docstring line is t1's.

**Done when:** the AC-186.10/11 acceptance tests pass: reuse, each local reason (no run, failed attempt, cancelled,
missing gate, skipped job, older than 7 days), a green rerun attempt reused, a repo without a Dockerfile needing no
docker job, and an in-progress run waited for.

## t10 — System ship CLI for answer, hold, resume and escalation questions

**Files:** scripts/cplat/appship.py, scripts/cplat/appship_report.py
**Covers:** AC-186.1, AC-186.2, AC-186.3
**Goal:** the coordinator can read `answer`, then resume or hold the repo, through `cplat system ship`.

**Implementation notes:**
- Subparsers: `repo resume <id> --answer TEXT` (required), `repo hold <id>`, and `--question` (repeatable) on
  `repo escalate`. Wire them to `appship_sched.resume_repo`/`hold_repo`/`escalate_repo` and print their lines.
- `show_next`: the text form of `answer` and `held` per design.md. JSON prints the object as is.
- Module docstring: the two new verbs.
- `appship_report.decision_count`: add `len(answers)` per repo. `final_report`: under the existing "Decisions taken
  for you" block, one line per answer, `<repo>: answered "<text>" (<cause>: <reason>)`.

**Done when:** the AC-186.1–3 acceptance tests through the CLI pass (`next --json`, `next --wait`, `repo resume`,
`repo hold`, the one-line refusals with exit 1).

## t11 — Component ship prompt passes questions and applies the system ship's answer

**Files:** plugins/component/commands/ship.md, docs/rules/plugins/component/commands/ship.yml
**Covers:** AC-186.1, AC-186.2 (the repo session's side)
**Goal:** a repo session states a decision's questions so that the coordinator can answer them, and acts on the answer
when it is resumed.

**Implementation notes:**
- Escalate section: for cause `decision`, pass each question as `--question '<question> (suggested: <answer>)'`, with
  a reason clause (so that the system ship can answer it while other repos build).
- One rule: an `answer from the system ship:` line printed by `ship start` is the user's decision for the escalation
  that stopped the run; apply it and go on, because the coordinator answered it in the user's place. Add both register
  entries (`practice`, `source: "#684"`).
- Keep the file's bytes: tighten existing sentences of the same file to pay for the added text (rules README, rule 6).

**Done when:** `cplat platform rules check --only plugins/component/commands/ship.md` passes.

## t12 — Build merges a task that cannot pass alone; the architect plans them as one

**Files:** plugins/component/commands/build.md, plugins/svc/agents/architect.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/svc/agents/architect.yml
**Covers:** AC-186.5
**Goal:** a task whose checks fail only because a later dependent task has not landed is merged with it, without
asking or escalating. Future plans do not split such a pair.

**Implementation notes:**
- build.md, 2.4 (after a task's checks fail): if they fail only because a later task tM that depends on tN has not
  landed, run `cplat plan merge tN tM --reason '<why>'` and go on with tM, without asking or escalating, because the
  split was the plan's mistake, not a decision. Register entry `experience`, `source: "#681"`.
- architect.md, Workflow step 4 or Principles: "A change and the change that makes its checks pass are one task, because
  a task whose checks cannot pass alone stops the build." Register entry `experience`, `source: "#681"`.
- Keep the bytes of the changed files in total (rule 6). Tighten sentences in these files.

**Done when:** `cplat platform rules check --only plugins/component/commands/build.md --only plugins/svc/agents/architect.md`
passes.

## t13 — Release prompt reuses the green CI run through cplat

**Files:** plugins/component/commands/release.md, docs/rules/plugins/component/commands/release.yml
**Covers:** AC-186.10, AC-186.11
**Goal:** `/component:release` starts no gate agent when main's CI on the tagged commit already passed the same gates.

**Implementation notes:**
- Before Phase 2: `cplat component release gates --commit <TAG_COMMIT>`, then print its line. Exit 0 → skip Phases 2–4,
  because the same commit already passed them in CI. Exit 1 → Phases 2–4 as today. Exit 2 → the same call again, at
  most twice, then run locally. Register entry `practice`, `source: "spec 186"`.
- Update the Final Summary's gate line for the reused case (`Gates: reused CI run <url>`) and the description
  frontmatter if it names the gates.
- Keep the file's bytes (rule 6).

**Done when:** `cplat platform rules check --only plugins/component/commands/release.md` passes.

## t14 — System ship prompt answers or holds an escalated repo

**Files:** plugins/system/commands/ship.md, docs/rules/plugins/system/commands/ship.yml
**Covers:** AC-186.2, AC-186.3
**Goal:** the coordinator answers a decision that has a suggested answer at once and holds every other escalation, so
other repos keep building.

**Implementation notes:**
- Phase `repos`, a new bullet `action: answer`. If the cause is `decision` and every question has a suggested answer,
  run `cplat system ship repo resume <id> --answer '<the suggested answers>'`. Otherwise run
  `cplat system ship repo hold <id>`. Then go on with `next`. Reason clause: one repo's decision does not wait for
  another repo's build, and only a suggested answer is one the user approved with the spec. Register entry `practice`,
  `source: "#684"`.
- Reword the rule "Never answer a repo spec's questions" so that it does not contradict the new bullet (it is about
  the repo spec's open questions, which `repo start` never leaves). Update its register `text`.
- `action: escalate`: unchanged in meaning (held repos reach the user here).
- Keep the file's bytes (rule 6).

**Done when:** `cplat platform rules check --only plugins/system/commands/ship.md` passes.

## t15 — Guides, changelog fragment and plugin versions

**Files:** docs/unattended-delivery.md, docs/AGENTS.md, docs/changelog.d/186-the-journey-waits-less.changed.md, .claude-plugin/marketplace.json, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json
**Covers:** AC-186.2, AC-186.5, AC-186.10 (what a person reads and runs, documented and released)
**Goal:** the new actions and commands are documented, and the changed plugins carry new versions.

**Implementation notes:**
- docs/unattended-delivery.md: the `answer` action, `repo resume`/`repo hold`, what is answered unattended and what is
  held, `cplat plan merge`, and the release reusing CI (`gates: reused …` / `gates: run locally (…)`). docs/AGENTS.md:
  the system ship's action list gains `answer`. No spec numbers in guide prose. Name only commands that exist
  (`scripts/check-docs.py`).
- Fragment per `docs/changelog.d/README.md`: also the template changes (image tagged after every gate, 30 s local
  Argo CD poll), which reach repos through `/platform:update`.
- Minor bumps for component, system and svc in their `plugin.json` and `.claude-plugin/marketplace.json`.
- Run `cplat platform rules check` over all prompts. If the change as a whole grew the prompts, tighten the changed
  prompts until it passes. Do not raise the baseline.

**Done when:** `scripts/check-links.py`, `scripts/check-docs.py`, `devbox run validate`, `cplat platform rules check`
and `cplat platform pr-check` (fragment, versions) pass.
