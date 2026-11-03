# Baselines (v1.1.1) — what v2 is measured against

Measured on the todo end-to-end run (2026-10-06/07, Apple silicon laptop, GitHub-hosted runners). Re-measure after each v2 phase and update the right-hand column.

## Token usage and cost per run (2026-10-25)

Measured with `cplat platform runs benchmark` (spec 099) on `ika100/todo-api`, Claude Code session transcripts, estimated at list prices (output tokens as the transcripts report them, so output cost is a lower bound). Every run counted here finished with a PR and green gates; failed runs and their causes are in [spec 100's benchmarks](specs/100-leaner-runs-cheaper-coordinator-fewer/benchmarks.md).

| Workflow | Before spec 100 (Opus coordinator) | After spec 100 | |
|---|---|---|---|
| quick-task (one small change) | $0.48, 22 calls | **$0.15**, 8 calls | −69% |
| build (plan + build of a two-criterion spec, median of two runs) | $1.94 | **$1.26** | −35% |
| ship (spec to deployed dev, LAN cluster, first measured) | — | **$1.20 to $1.60** per run | |
| A 10-spec delivery round before measuring (085–098, one session) | about $105, 2,287 calls, 42% of it coordination | — | |

**4.7.0 baseline (2026-10-26, sample `ika100/todo-api@9cba320`, plugins at the tag):** quick-task **$0.30** (18 calls: coordinator plus coder, quality and tester, as `/component:fix` prescribes; the $0.15 runs above had the coordinator make the change itself), build **$1.36 and $1.25** (median $1.31, within the ±$0.10 spread of 4.6.0), ship **$1.20 to $1.60** (two runs, 4.6.0 plus the deploy fixes). Run ids are in the run store (`cplat platform runs report --benchmarks`).

Re-measure with `cplat platform runs benchmark quick-task|build` after changes to the commands, agents or `cplat`; `cplat platform runs report --benchmarks` shows the median per workflow and platform version.

## Prompt/token footprint (static)

| Item | v1.1.1 | v2 target |
|---|---|---|
| Always-on tokens, all 7 plugins | ~3.4k (svc 1,057; shared 511; web 503; svc-java 518; gitops 457; app 373) | ≤ 3.4k |
| `/component:new` prompt (on invoke) | 11.3 KB (~3k tokens) | < 2 KB |
| `/platform:update` prompt | 4.8 KB | < 1.5 KB |
| `/instance:promote` command + agent | 6.0 KB + 5.2 KB | < 2 KB total |
| `/component:build` prompt | 14.1 KB (~5.5k tokens) | unchanged in A–F (see Phase G) |
| Prompt files in `plugins/` | 178 KB | tracked |

## Time

| Step | v1.1.1 | v2 target |
|---|---|---|
| Web image build, multi-arch | ≈ 9 min (QEMU) | **≈ 3 min measured** (arm64 104 s ‖ amd64 155 s + 28 s manifest merge, native runners) |
| Java image build (multi-arch) | ≈ 3 min | **≈ 2 min measured** (amd64 116 s ‖ arm64 121 s + 16 s) |
| Generated CI job (quality/test/security) | 2–3 min each | −30 s (leaner devbox) |
| `devbox run cluster-up` from scratch | ≈ 2.5 min | ≈ 2.5 min incl. Gateway provider |
| Platform e2e (`tests/e2e/run.sh`, local) | — | ≈ 6 min (2 image builds + k3d + rollout + probes) |
| Platform CI (PR) | 3–4 min | ≤ 4 min incl. unit + e2e smoke |
| Spec-driven system, empty folder → verified on a local cluster (3 repos, 1 system spec, 6 PRs) | — | **60.5 min measured** 2026-10-08, 10 agent sessions, $17.48 ([run log](e2e/2026-10-08-todo-spec-driven.md); summed per step, slightly high — resumed sessions report cumulative cost) |
| Demo run, one Python service and one spec (empty folder → new endpoint answering in dev on a local cluster) | — | **≈ 85 min measured** 2026-11-03 with v5.6.0; **≈ 28–30 min estimated** without the stalls ([breakdown](#the-2026-11-03-demo-run)) |
| Second feature on an existing system with v4.0.0 (upgrade 3 repos, system spec, 2 repo builds, deploy) | — | **~68 min active** 2026-10-09 (16.5 h wall clock incl. waiting for the user and an overnight usage-limit pause), 10 agent sessions, $12.10 counted per session ([run log](e2e/2026-10-09-todo-second-feature.md)) |

### The 2026-11-03 demo run

The recording in the README and on the docs homepage. One system with one Python service: `/system:new`, `cluster-up`, `/component:spec` with 8 questions, `/component:ship`. Public repos and GitHub-hosted runners. Times come from the recording's clock and the repos' CI runs. The ideal column removes the stalls, so it is an estimate, not a second measured run.

| Step | Measured | Ideal | What made the difference |
|---|---|---|---|
| `/system:new` (2 repos) | 3 min | 3 min | — |
| System PR + `cluster-up` | 6 min | 2 min | waited for the first image build, which can run while the spec is written |
| Expose the API | 2 min | 0 | an extra demo step; not needed when the component is exposed from the start |
| Spec: write, 8 questions, approve, merge | 24 min | 4 min | the questions waited about 20 min for an answer |
| Ship: plan, acceptance tests, 3 coders, review | 16 min | 13 min | a formatter escalation ([#367](https://github.com/ika100/sdlc-foundry/issues/367)) and a merge conflict on the spec status |
| Feature PR CI + `main` CI with the image | 4 min | 4 min | — (each CI run took 1–2.5 min) |
| Pin to dev | 23 min | 1 min | the pin PR waited for a manual approval ([#368](https://github.com/ika100/sdlc-foundry/issues/368)) |
| Argo sync and dev smoke | 4 min | 2 min | smoke was skipped ([#369](https://github.com/ika100/sdlc-foundry/issues/369)) |
| **Total** | **≈ 85 min** | **≈ 28–30 min** | |

Most of the ideal time is agent work (spec and ship, about 17 min). CI is about 7 min in total.

## Defect history

12 defects were found only by running the real chain (see `CHANGELOG.md` [1.1.1]); v2 adds a regression test or contract check for each.
