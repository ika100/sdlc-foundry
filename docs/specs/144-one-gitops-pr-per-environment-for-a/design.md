# Design — 144 One gitops PR per environment for a system ship

The system ship (`cplat system ship`, spec 097, ADR-042) keeps its phases and its scheduler. What changes is where dev is
changed: the gitops entry's `compose/<spec>` branch stays open, every component build of the plan is pinned on it by the
system ship itself, and one PR lands it all after the last component merged. The component ships keep their own repos, PRs
and CI (non-goal). The measurement this starts from is spec 136's design, § AC-136.11 (journey 2: #12 entry, #13 and #14
`pin-dev`).

## Decisions

1. **Joint mode is per run, from the gitops-app's `pin-dev.yml`.** `system ship start` of a new run sets `st["joint"]` to
   whether `origin/main:.github/workflows/pin-dev.yml` knows the marker (it contains `refs/heads/ship/`). A gitops-app
   rendered before this spec gets `joint: false`: everything works as before (one dev PR per component, the entry merged
   first), and `start` prints one line: `one dev PR per component: this gitops-app's pin-dev.yml predates spec 144; run
   /platform:update to get one dev PR per system spec`. A resumed run keeps the mode it started with (answered question 5).
2. **The marker** is a branch `ship/<spec>/<component>-<sha7>` of the gitops-app, at the head of its `main` (no commit of
   its own). The component ship pushes it from the system ship's gitops clone right after its PR merged (`land`), so it
   exists minutes before the component's CI dispatches `pin-dev` (after tests and the image). `pin-dev.yml` lists the
   remote heads and, when `ship/<anything>/<service>-<sha7>` exists for the dispatched build, prints a notice and exits 0
   without a PR. Any other build of the same component (a fix, a release commit, a component ship of its own) has no marker
   and is pinned as today (AC-144.6). The system ship deletes the run's markers after the joint dev PR merged. A failed
   marker push is a line, not an error: if `pin-dev` opens its own PR anyway, the system ship closes it when it pins that
   build (comment: pinned in the system ship's dev PR).
3. **The joint dev PR** is the PR of `compose/<spec>`: the entry's PR when the plan has a gitops entry, else the PR the
   first pin opens (`chore(dev): <spec> — the builds of the system spec`). `st["joint_pr"]` holds its URL.
4. **The entry in joint mode.** `entry land` waits for the entry PR's checks (green → the entry is `passed`, its
   dependents start; red → escalated as today) but does not merge it, keeps the worktree and installs no operators yet
   (answered question 2: resources and components land together). No sync wave is added: render makes every resource its
   own Argo CD app (`addon-<name>-dev`, its own ApplicationSet) and every component another, and waves only order the
   resources inside one app. A component whose database secret does not exist yet stays in `CreateContainerConfigError`
   and starts once the resource app made it; `land` waits until every one of these apps is `Synced`/`Healthy` (decision 8),
   so a component is never smoked before its resource runs.
5. **The component ship in joint mode** (`st["product"]["joint"]`, set by `product_link`): `deploy` waits for the
   component's CI on `main` for the merge commit to pass (the image `sha-<40>` is published by it), red → fails as today;
   then it pushes the marker again if it is missing, merges the plan's `after-release` gitops tasks as today, and ends
   `done` with `dev: pinned in the system ship's dev PR (compose/<spec>): <component> sha-<40>`, `Smoke (dev): with the
   system ship` and `Promotion (staging): with the system ship`. It never waits for a `pin-dev` run, Argo CD or a smoke
   (AC-144.3). Outside a system ship nothing changes (AC-144.6).
6. **Pinning (system ship).** `repo result <id>` (also run by `next --wait`) of a deployable component whose ship ended
   with the deferred smoke pins it on `compose/<spec>` in the entry worktree, under a lock: `devbox run -- uv run
   scripts/pin.py dev <component> sha-<40>`, commit `chore(dev): pin <component> to sha-<40> (<spec>)` (signed off), push;
   it closes an open `pin/dev-<component>-<sha7>` PR, opens the joint PR when there is none, and sets the repo `pinned`.
   `pinned` counts as delivered: dependents start and the scheduler moves on (AC-144.3).
7. **Action `land`.** `next` answers `land` when the run is joint, every repo is past its gate (`passed`, `pinned`,
   `done-before`), the joint PR exists and has not landed. `complete` refuses until it has.
8. **`cplat system ship land [--timeout S] [--wait-timeout S]`** (AC-144.2, AC-144.4): waits for every check of the joint
   PR and merges it through the merge slot (red → the run escalates with cause `code`; a conflict likewise); then, on
   `main`, applies changed operators (spec 142, moved from `entry land`), deletes the markers and waits once for Argo CD:
   the dev apps of the plan's components plus the dev resources and observability, synced to the merge commit and running
   the pinned images (spec 143's `envwait.watch`). RED → escalated (`environment`), TIMEOUT → exit 2 and nothing escalated
   (run `land` again; it resumes after the merge). Then the dev smoke of every pinned component in plan order, as
   `cplat instance verify dev` records it (`smoke.run_smoke`, then `smoke.record` with the pinned tag), against the URL of
   the merged `system.yaml`: an exposed component needs a passing smoke, an internal one is judged by Argo CD as before.
   A red smoke files the `smoke-failure` issue in the component repo (as a component ship does), escalates that repo and,
   after every component was smoked, the run, naming the components. A passed smoke of the same digest is not run again on
   a resume.
9. **Staging in one PR (AC-144.7).** After every dev smoke passed, `land` collects the components whose staging rule is
   `after-dev-smoke`, that have a staging instance, whose staging pin differs from the build and is not newer, and whose
   registry digest is the one dev smoked (spec 105). None → one `Promotion (staging): not promoted: <reason>` per
   component. Otherwise one branch `promote/staging-<spec>` from `main` with `pin.py staging` for each, one PR
   `chore(staging): promote <spec> (automatic, spec 093)`, landed like the dev PR, then one Argo CD wait for those staging
   apps and the staging smoke of each; a red staging smoke escalates with cause `code` (no rollback, as spec 093). `pin-staging`
   is not dispatched by a joint run.
10. **A failed component (AC-144.5)** escalates as today: no new repo starts, `next` answers `escalate`, and the joint PR is
    never merged, so dev keeps its builds. The markers of the merged components stay: they name only those commits.
    Resuming (`/system:ship <spec>`) continues with the joint PR still open.
11. **The report** shows the pinned tag in `dev` once it landed, `Promotion (staging)` per component in a joint run, and
    the last line says what the run promoted (`dev` or `dev and staging`).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/appship_joint.py` | joint mode, markers, pinning on `compose/<spec>`, the component ship's joint deploy, `land` (dev PR, Argo CD, dev smokes, staging PR) | new |
| `scripts/cplat/appship.py` | `start` sets the mode and prints the legacy line, `entry land` in joint mode, `land` subcommand, `complete` refuses before landing | changed |
| `scripts/cplat/appship_sched.py` | action `land`, `pinned` as delivered, `result` pins a deferred component | changed |
| `scripts/cplat/appship_state.py` | `PASSED` holds `pinned`; next step names `land` | changed |
| `scripts/cplat/appship_report.py` | `dev` and staging rows, last line | changed |
| `scripts/cplat/ship.py` | `product_link` carries the mode and spec; `land` pushes the marker; `deploy` hands a joint run to `appship_joint` | changed |
| `templates/gitops-app/.github/workflows/pin-dev.yml` | skips a build that has a marker | changed |
| `plugins/system/commands/ship.md`, `plugins/component/commands/ship.md`, `templates/gitops-app/CLAUDE.md.jinja`, `docs/AGENTS.md` | the texts | changed |

## Contract

- Marker ref: `refs/heads/ship/<system spec id>/<component>-<sha7>`; `pin-dev.yml` match:
  `git ls-remote --heads origin | grep -q "refs/heads/ship/[^/]*/$SERVICE-${sha::7}$"`.
- State (`cplat-app-ship.json`): `joint` (bool), `joint_pr` (URL), `dev_landed` (merge commit sha or absent),
  `staging_pr` (URL), per repo `pinned` (tag), `component`, `smoke` (`{outcome, digest}`), `staging_row`; repo state `pinned`.
- Ship state (`cplat-ship.json`) of a joint component ship: `product.joint: true`, `product.spec`; `smoke.outcome:
  "deferred"`, `joint: {"tag": "sha-<40>", "marker": "<ref>"}`.
- `cplat system ship land` exit codes: 0 landed (dev, and staging when promoted), 1 escalated, 2 Argo CD timeout.

## AC-144.8

The journey record of the next part 2 run (after the release) shows it; here it is covered by a simulated system ship of a
gitops entry and two components that counts the gitops PRs opened for dev (one) besides the spec/plan and done PRs.

## Risks

- A marker push that fails and a `pin-dev` PR that merges before the system ship pins: dev runs that build early; the
  joint PR then has no diff for it (harmless).
- A gitops-app whose CI does not run on `compose/*` PRs: the joint PR waits like the entry PR did before.
