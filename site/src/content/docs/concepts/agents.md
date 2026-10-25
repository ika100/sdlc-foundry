---
title: "Agents and orchestration"
description: "Scripts do the deterministic work; agents orchestrate and ask before anything outward-facing."
sidebar:
  order: 7
---

Two layers:

1. **`cplat`**, a tested CLI (`new-service`, `update-service`, `compose`, `promote`, `addon`, `secret`, `doctor`, `status`, `feedback`, `pr open`, `smoke`, `retro`). Every command has `--dry-run` and a clear report (what it will do, what it did, how to undo).
2. **Slash commands and agents**, thin prompts that run the script, show you the preview, and relay the result. Orchestration commands (`/svc:spec`, `/svc:plan`, `/svc:build`, `/svc:quick-task`, `/svc:fix-bug`, `/svc:release`, and the unattended `/svc:ship` and `/app:ship`) spawn specialised agents (product manager, architect, coder, tester, security, deployment, release) in phases, routed by shape.

Runs are lean by default: a headless session starts its coordinator on Sonnet (`--model` or `coordinator_model` in `.platform-settings.yml` or `~/.config/sdlc-foundry/settings.yml` changes it; the architect and reviewer keep their own model), `cplat pr open` commits, pushes and opens the pull request in one step, `cplat quiet <script>` prints one line for a passing check, and agents get a brief with their criteria and task instead of rereading the whole spec. In the platform's benchmark a small change dropped from about $0.48 to $0.15 and a full build from $1.94 to $1.26 (estimated list prices). Run records feed a weekly retro (`cplat retro`) that proposes the next specs from evidence.

Rules every agent follows: use `devbox run <recipe>` and never call tools directly; ask before pushes, pull requests, repository creation and anything that touches a cluster; stop and offer `/shared:report-issue` when a platform template or script misbehaves. The full model, including phases and context hand-offs, is in [the agent model](/sdlc-foundry/guides/agents/).
