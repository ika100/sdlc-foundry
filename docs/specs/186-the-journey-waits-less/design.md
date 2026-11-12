# Design — 186 The journey waits less

## Decisions

- **`answer` is a new scheduler action, ahead of `wait` and `start`** (A1). `appship_sched.next_action` returns it while
  the run as a whole is not escalated and some repo is `escalated` and not `held`. The repo it names is the first such
  repo in plan order. `escalate` keeps its meaning: nothing runs and nothing can start. `next --wait` needs no change of
  its own: it already records each finished repo (`repo result`) and then returns the first action other than `wait`
  (AC-186.1). ADR: `a-system-ship-answers-an-escalated-repo-while-others-run`.
- **Questions are structured data, not prose in the reason.** A component ship escalation can carry questions
  (`cplat component ship escalate … --question '<q> (suggested: <a>)'`, repeatable), parsed with the
  `(suggested: …)` form open questions already use (`spec._question`). They go into the clone's ship state as
  `questions`, `repo result` copies them into the repo entry unchanged, and `next` prints them word for word. If an
  escalation has no `--question` but its reason ends in `(suggested: …)`, the whole reason is read as one question,
  so a session that put its question in the reason is still answerable.
- **The answer reaches the resumed session through its environment and the ship state.** `repo resume` starts the
  repo's headless `/component:ship` again (`appship_proc.spawn`, `starts` reset to 1) with `CPLAT_SHIP_ANSWER=<text>`.
  The session's `cplat component ship start` resumes the escalated run (the existing revive path), appends the answer
  to the ship state's `answers`, and prints `answer from the system ship: <text>`. `describe` repeats the latest answer,
  so later sessions of the same headless run see it too. The answer is also kept in the system ship state
  (`repos.<id>.answers`) and counts as a decision taken for the user (spec 141 report) (AC-186.2).
- **The coordinator settles only `decision` escalations whose questions all have a suggested answer** (A2): it resumes
  with those answers. Every other escalation is held (`repo hold`). A held repo stays `escalated`, so the existing
  `stopped` rule keeps every new repo from starting. When nothing runs, `next` returns `escalate` as today (A3,
  AC-186.3). A run resumed with `/system:ship` clears `held` and `questions` along with the escalation.
- **`cplat plan merge` folds tN into tM and commits only plan.md** (A4). It is the only command that removes a task.
  Unit mode therefore reads a task that is gone from the committed plan as merged: its `task:`/`batch:` unit
  checkpoints, and the work goes on in tM's unit. That way the session that merged does not stall on a unit it can no
  longer finish (AC-186.5). The command also records a `task-merge` event in the run, so the PR's "How this was built"
  block names both tasks and the reason.
- **Images are tagged only after every gate** (A6). The `docker` matrix job loses `needs: [quality, test]` and runs
  alongside the gates. It pushes by digest on `main` only, as today. `docker-publish` (manifest + `sha-<40>`,
  `sha-<7>`, `latest`) needs `quality`, `test`, `security`, `ci-extra` and `docker`. `ci-extra` is in the list because
  it is a gate `devbox run ci` runs too, and it passes when no recipe is defined. The image scan is a step of
  `docker`, so a failed scan step fails `docker`. `pin-dev` keeps `needs: docker-publish`. Required check names do not
  change. `release-image` (spec 106) does not change. ADR: `an-image-is-tagged-only-after-every-gate-passed`.
- **Argo CD's poll is set in `argocd-cm`** (A7): `timeout.reconciliation: 30s`. The jitter key is not touched. The
  application controller reads this key only at start, so the script restarts it when it changes the value. A re-run
  that finds `30s` already set changes nothing.
- **Restore and discard ask for one normal refresh** (A8): a `kubectl annotate … argocd.argoproj.io/refresh=normal
  --overwrite` on `addon-<db>-<env>` right after the merge and pull, before the revision wait. A failure is one line,
  and the wait goes on.
- **The release's gate decision is one `cplat` call**: `cplat component release gates --commit <S>`. It reads `main`'s
  latest `ci` push run on S. If the run is still in progress, the call waits for it. It then answers reuse (exit 0) or
  run locally (exit 1). A run can be reused for 7 days after it finished (A9). The latest attempt is the one judged, so
  a run that went green on a rerun counts. ADR: `a-release-reuses-the-green-ci-run-of-its-commit`.
- **Prompts stay within their bytes**: every prompt sentence this spec adds gets a register entry. Its bytes are won
  back by tightening prose in the same change (rules README, rule 6). The baseline is not raised.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/plancmd.py` | `cplat plan merge`: fold a task into a later one that depends on it, commit plan.md, record the event | new |
| `scripts/cplat/cplat.py` | `plan` plumbing; docstring lines for `plan merge` and `component release gates` | changed |
| `scripts/cplat/runs_agents.py` | `task_merge` event | changed |
| `scripts/cplat/runs_built.py` | the `task-merge` hand-back line | changed |
| `scripts/cplat/ship.py` | `escalate --question`; `start` records `CPLAT_SHIP_ANSWER`; `describe` shows the latest answer | changed |
| `scripts/cplat/appship_sched.py` | `answer` action; `questions_of`; `hold_repo`; `resume_repo`; `result`/`escalate_repo` keep questions | changed |
| `scripts/cplat/appship_proc.py` | `spawn(..., answer=None)` sets `CPLAT_SHIP_ANSWER` | changed |
| `scripts/cplat/appship_state.py` | whole-run resume clears `held`/`questions`; `next_step` names `answer` | changed |
| `scripts/cplat/appship.py` | CLI `repo hold`, `repo resume --answer`, `repo escalate --question`; text output of `answer` | changed |
| `scripts/cplat/appship_report.py` | answers count as decisions taken for the user | changed |
| `scripts/cplat/units.py` | a task gone from the committed plan counts as merged | changed |
| `scripts/cplat/preflight.py` | run allowlist adds `cplat plan merge` | changed |
| `scripts/cplat/dbrestore.py` | one normal refresh after the merge | changed |
| `scripts/cplat/comprelease.py` | `gates` verb | changed |
| `templates/{gitops-app,cluster-gitops}/scripts/local-cluster.sh` | 30 s reconciliation | changed |
| `templates/{service-python,service-java,service-go,web-nextjs}/.github/workflows/ci.yml` | docker alongside the gates; tags after them | changed |
| prompts: `plugins/system/commands/ship.md`, `plugins/component/commands/{ship,build,release}.md`, `plugins/svc/agents/architect.md` | the new steps and rules | changed |

## Contract

### `cplat system ship next --json` (AC-186.1)

The object as today, plus `held: [<id>…]` (always present) and, only when `action` is `answer`, `answer`:

```json
{"phase": "repos", "start": [], "running": ["web"], "blocked": [], "escalated": ["api"], "held": [],
 "action": "answer",
 "answer": {"id": "api", "cause": "decision", "reason": "<the repo's reason, verbatim>",
            "questions": [{"text": "<question, verbatim, without the suggestion>", "suggested": "<answer>" }],
            "resume": "cplat system ship repo resume api --answer '<text>'",
            "hold": "cplat system ship repo hold api"}}
```

- `questions[].suggested` is `null` when the question has none. `questions` is `[]` when the escalation has none.
- Order of the actions: `done`, then `answer` (some repo `escalated`, not `held`, and `st.escalated` empty), then
  `wait`, `start`, `land`/`complete`, `escalate`, all as today. With no unanswered escalated repo, the object equals
  today's plus `"held": []`.
- Text form (`next` without `--json`): `action: answer`, then `answer <id> (cause <cause>): <reason>`, then one
  `  question: <text>` line per question, with ` (suggested: <s>)` appended when it has one, then the usual
  `running`/`blocked`/`escalated` lines, then `held <id>` for each held repo.
- `next --wait` returns `answer` at the first poll after the escalated repo's result is recorded (exit 0, `REACHED`).

`questions_of(reason: str, stored: list | None) -> list[dict]`: `stored` (each `{"text", "suggested"}`) when it is a
non-empty list. Otherwise, a reason that ends in `(suggested: …)` gives
`[{"text": <reason before it>, "suggested": <first option>}]`. Otherwise `[]`.

### `cplat system ship repo resume <id> --answer '<text>'` (AC-186.2)

- Allowed when the run is not escalated as a whole and the repo is `escalated`, held or not. It sets the repo entry
  to `state: running`, removes `reason`, `cause`, `questions` and `held`, and appends
  `{"at": <iso seconds>, "text": <text>, "cause": <old cause>, "reason": <old reason>, "questions": <old questions>}`
  to `answers`. It then spawns the session (`appship_proc.spawn(clone, spec, gitops, run_id, 1, answer=text)`), stores
  `proc`, and prints `<id>: resumed with your answer (pid <pid>, log <log>); next: cplat system ship next --wait`.
  No other repo entry is touched.
- Refusals: exit 1, exactly one line on stderr (`ERROR: …`, no `fix:` line), nothing written:
  - unknown: `ERROR: '<id>' is not a repo of the plan of <spec>`
  - not escalated: `ERROR: <id> is <state>, not escalated: nothing to resume`
  - run escalated: `ERROR: the run of <spec> is escalated: resume it with /system:ship <spec>`
- A spawn failure escalates the repo with cause `environment`, as `launch` does today.

### `cplat system ship repo hold <id>` (AC-186.3)

- The repo must be `escalated`. The command sets `held: true`, prints
  `<id>: held for you (<reason>); the run escalates once nothing runs`, exits 0.
- Refusals as for resume (unknown; `ERROR: <id> is <state>, not escalated: nothing to hold`). A repo already held is
  held again (exit 0).

### Questions on escalations (AC-186.1)

- `cplat component ship escalate <reason…> --cause C [--question '<q>']…` stores
  `questions: [{"text", "suggested"}]` in the ship state (parsed with `spec._question`: `text`, `options[0]` or
  `null`). Without `--question` it stores no `questions` key.
- `cplat system ship repo escalate <id> <reason> --cause C [--question '<q>']…` stores them on the repo entry.
- `repo result` copies the clone ship's `questions` (or removes the key) together with `reason` and `cause`.

### The answer in the repo session (AC-186.2)

- `cplat component ship start`: when `CPLAT_SHIP_ANSWER` is set and non-empty and the run is resumed, it appends
  `{"at", "text"}` to `answers` unless the last entry has the same text, and prints
  `answer from the system ship: <text>` before the phase line.
- `describe(st)` adds `  answer from the system ship: <latest text>` when `answers` is non-empty.

### `cplat plan merge <tN> <tM> [--spec <id>] [--reason '<text>'] [--repo DIR]` (AC-186.4)

- Spec: `--spec`, else the `feature/<id>` branch, else the ship state's spec. If none of these gives a spec, exit 1.
- Checks, in order, each refusal exit 1 with one line and no change:
  - `ERROR: unknown task '<t>' in <spec>`
  - `ERROR: <t> is done: a done task is not merged`
  - `ERROR: <tM> does not depend on <tN>: only a task that depends directly on another is merged into it`
  - `ERROR: <plan path> has uncommitted changes: commit them first`
  - `ERROR: the merged plan does not check: <first error>` (for example a cycle through a task between them).
- Result: tN is removed. tM keeps `id` and `title`. `files` and `covers` are tM's in order, followed by tN's entries
  not yet present. `depends_on` is tM's followed by tN's, without tN and tM. Every other task's `depends_on` has tN
  replaced by tM (no duplicates). If tM's new files overlap a `parallel_safe` task of its level, tM becomes
  `parallel_safe: false`. `spec_hash` is written as the same quoted string, and no other metadata key changes.
- Prose: tN's `## tN — …` section is removed. Its body is appended to tM's section after a line
  `**Merged from tN — <tN title>** (<reason>):`. tM's `**Files:**` and `**Covers:**` lines are rewritten from the
  merged lists when present.
- Commit, only plan.md, signed off:
  `chore(plan): <spec> merge <tN> into <tM>`, body `<reason>`, trailer `Plan-Merge: <tN> into <tM>`.
- Output (exit 0): `MERGED <tN> into <tM>: <reason>`, then
  `  files: <merged list>; covers: <merged list>; depends_on: <merged list or none>`, then
  `  dependants moved to <tM>: <ids or none>`, then `  committed <sha7>`.
- Default reason: `the checks of <tN> pass only together with <tM>`.
- Run record: `runs_agents.task_merge(run_id, repo, tN, tM, reason)` adds an event
  `{"kind": "task-merge", "task": tN, "into": tM, "reason": reason}` under the architect's entry. Recording failures
  never change the result. `runs_built` renders it in "Hand-backs and fix rounds" as
  `merged task <tN> into <tM>: <reason>` (AC-186.5).

### Unit mode after a merge (AC-186.5)

`units._evaluate` for a `task:`/`batch:` unit: a task id that is absent from the committed plan counts as done (merged
away). The unit checkpoints when every one of its tasks is done or absent.

### Run allowlist (AC-186.5)

`preflight.run_allowlist` adds `Bash(cplat plan merge *)` for `/component:build`, `/component:ship` and `/system:ship`.
It is not in `refused_rules`. `cplat headless --dry-run` prints it in the allowlist block.

### Component CI (AC-186.6, AC-186.7)

In each of the four templates' `ci.yml`:

- `docker`: no `needs`, the `if` unchanged (`github.ref_type != 'tag'`), matrix, steps and `name` unchanged. It pushes
  by digest only when `PUBLISH`, so a pull request pushes nothing.
- `docker-publish`: `needs: [quality, test, security, ci-extra, docker]`,
  `if: success() && github.event_name == 'push' && github.ref == 'refs/heads/main'`. Its tags are unchanged.
- `pin-dev`: `needs: docker-publish`, unchanged. A red or cancelled gate skips `docker-publish`, so no tag moves and dev
  is not pinned.
- `release-image` unchanged.

### Local Argo CD (AC-186.8)

After the Argo CD rollout waits, in both `local-cluster.sh` (identical blocks):

```sh
cur=$(k -n argocd get configmap argocd-cm -o jsonpath='{.data.timeout\.reconciliation}' 2>/dev/null || true)
if [ "$cur" != 30s ]; then
  k -n argocd patch configmap argocd-cm --type merge -p '{"data":{"timeout.reconciliation":"30s"}}' >/dev/null
  k -n argocd rollout restart statefulset/argocd-application-controller >/dev/null
  k -n argocd rollout status statefulset/argocd-application-controller --timeout=300s
fi
echo "Argo CD polls git every 30s (timeout.reconciliation)"
```

### Restore refresh (AC-186.9)

In `dbrestore._publish`, after the checkout/pull and `head`, before the loop:
`backupstate.kubectl(["-n", "argocd", "annotate", "applications.argoproj.io", app, "argocd.argoproj.io/refresh=normal", "--overwrite"], ctx)`.
Success adds `asked Argo CD to refresh <app> now` to `r.did`. Failure adds
`could not ask Argo CD to refresh <app> (<why>); waiting for its poll`. The wait loop is unchanged.

### `cplat component release gates --commit <S> [--repo DIR] [--timeout S] [--json]` (AC-186.10, AC-186.11)

- Runs: `gh run list -R <slug> --workflow ci --branch main --commit <S> --event push --json databaseId,status,conclusion,attempt,updatedAt,url`.
  The newest run (highest `databaseId`) is the one judged. A run not `completed` is polled every `--interval`
  (10 s) up to `--timeout` (540 s). Then `gh run view <id> -R <slug> --json databaseId,attempt,conclusion,updatedAt,url,jobs`
  (the jobs of the latest attempt).
- Gates: `quality`, `test`, `security`, and `docker` when `git cat-file -e <S>:Dockerfile` succeeds. A job belongs to
  gate `g` when its name is `g` or starts with `g + " "`. Each gate needs at least one job, and all of its jobs must
  have conclusion `success`.
- Reuse (exit 0), one line:
  `gates: reused CI run <url> on <sha7> (<job names, comma-separated, in run order>)`.
- Run locally (exit 1), one line `gates: run locally (<reason>)`, where reason is one of:
  - `no ci run on main for <sha7>`
  - `ci run <id> <conclusion> on attempt <n>`
  - `gate <g> has no job in ci run <id>`
  - `gate job <name> <conclusion> in ci run <id>`
  - `ci run <id> finished <n> days ago (more than 7)`
  - `cannot read the ci runs: <error line>`
- TIMEOUT (exit 2): `TIMEOUT: main's ci run on <sha7> is still running after <n>s`, then `run the same call again`.
- `--json`: `{"reuse": bool, "line": str, "reason": str|null, "run": {"id", "url", "attempt", "conclusion", "finished_at"}|null, "jobs": [{"name", "conclusion"}]}`.
- `MAX_AGE_DAYS = 7`. The wait is recorded with `waits.record(repo, "component release gates", …)`.
- `/component:release`: the call comes before Phase 2. Exit 0 → print the line and skip Phases 2–4 (no quality,
  tester or security agent, no local gate). Exit 1 → print the line and run Phases 2–4 as today. Exit 2 → the same call
  again, at most twice, then run locally.
