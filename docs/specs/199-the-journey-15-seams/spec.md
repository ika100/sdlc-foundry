---
spec_id: 199-the-journey-15-seams
title: The journey 15 seams
status: approved
priority: P1
shape: platform
---

# 199 — The journey 15 seams

## Problem

Journey 15 (2026-11-14, platform 5.22.0) found that `cplat` and the local cluster disagree on the Gateway's host port.
`devbox run cluster-up` gives the Gateway the next free port when the preferred one is busy (spec 056) and prints it,
but every local URL `cplat` builds uses `LOCAL_HTTP_PORT` or the preferred default, never the port the cluster really
got. In the journey the cluster ran on another port because a second local cluster held the default: the dev smoke of
`cplat component ship deploy` and of `cplat system ship land`, and the staging smoke of `cplat instance promote --smoke`,
all hit "connection refused", recorded "not run", blocked the staging promotion and escalated the system ship; the prod
PR's evidence then warned "no staging smoke record" although the tests pass on the real port, and the Grafana URL of
spec 197 points at the wrong port too. Agents ran smoke by hand with `--base-url`, which records nothing, so every run on
a machine with a second cluster loses its smoke evidence.

## Stories

As a coordinator shipping a component or a system to a local cluster, I want `cplat` to smoke-test the port the
cluster's Gateway really listens on, so that the smoke is recorded and the promotion proceeds without a hand-run smoke.

As a developer with two local clusters, I want the Grafana link and the prod PR's evidence to match the running cluster,
so that I can trust them without checking the port myself.

## Acceptance criteria

- **AC-199.1** Given a system whose dev environment is local (its host ends in `.localhost`), `LOCAL_HTTP_PORT` unset,
  and a (faked) `docker port k3d-<cluster>-serverlb 80/tcp` that reports a host port other than the default, when
  `cplat component ship deploy` runs its dev smoke, then the smoke runs against `http://<component host>:<that port>`,
  a passing smoke is recorded as passed (not "not run") and the staging promotion proceeds as it does on the default port.
- **AC-199.2** Given the same setup, when `cplat system ship land` runs its dev smoke and `cplat instance promote --smoke`
  runs the staging smoke, then both use the reported port and record their results, the system ship does not escalate
  for an unreachable environment, and the evidence of the following prod promotion PR shows the staging smoke record
  without the "no staging smoke record" warning.
- **AC-199.3** Given the same setup with `observability.ui: lgtm`, when `cplat system set --env <env> --observability lgtm`
  or `cplat system status` runs, then the Grafana line and `grafana_url` in `--json` carry the reported port.
- **AC-199.4** Given a local environment, when `cplat` builds one of its URLs, then the port is `LOCAL_HTTP_PORT` when it
  is all digits (docker is not asked); else the load balancer's reported port; else, when docker is missing, exits
  non-zero, reports no port or the container does not exist, the default 8088 without an error; for a non-local
  environment docker is never asked.
- **AC-199.5** Given a system named `<system>`, when `cplat` looks up the load balancer, then the cluster is `LOCAL_CLUSTER`
  when set, else `<name>` of a configured kube context `k3d-<name>` (`CPLAT_KUBE_CONTEXT` or `kube_context:` in the
  settings files), else `<system>-local`; within one `cplat` invocation docker is asked at most once per cluster.

## Non-goals

- Changing how `devbox run cluster-up` chooses or prints its port (spec 056 stays as it is).
- Port discovery for local clusters other than k3d (kind, Docker Desktop, minikube); they keep `LOCAL_HTTP_PORT` or 8088.
- Recording smoke results from a hand-run smoke with `--base-url`.
- URLs of non-local environments.

## Assumptions

- **A1** The cluster name comes from `LOCAL_CLUSTER`, then a configured `k3d-<name>` kube context, then `<system>-local`,
  the same default `devbox run cluster-up` uses (other option: only `<system>-local`; affects AC-199.5).
- **A2** The looked-up port is cached for one `cplat` invocation only, never on disk, so a recreated cluster on another
  port is picked up by the next command (other option: a cache file per cluster; affects AC-199.5).
- **A3** When docker cannot answer, `cplat` falls back silently to 8088 as today, so machines without docker or a
  running cluster behave exactly as before (other option: print a warning naming the fallback; affects AC-199.4).
- **A4** An explicit all-digit `LOCAL_HTTP_PORT` still wins over the cluster's port, matching spec 056; a non-digit value
  such as `auto` is treated as unset (other option: the cluster's port always wins; affects AC-199.4).
- **A5** Spec 197's AC-197.3 and AC-197.4 already require "the local Gateway port the platform already uses", so they hold
  unchanged and nothing is replaced (other option: supersede them with AC-199.3; affects AC-199.3).
- **A6** Tests fake `docker` on the path as the platform's test fixtures do and need no real cluster; no agent prompt rule
  changes, so no rules-register entry is needed; if the plan changes one, it gets its entry (spec 168) (other option:
  tell the agents to pass `--base-url`; affects AC-199.1 to AC-199.5).

## Open questions

## Changelog

- 2026-11-14 created
- 2026-11-14 approved
