---
title: "Agents and orchestration"
description: "Scripts do the deterministic work; agents orchestrate and ask before anything outward-facing."
sidebar:
  order: 7
---

Two layers:

1. **`cplat`**, a tested CLI grouped by noun (`system`, `component`, `api`, `resource`, `instance`, `issue`, `platform`) plus plumbing (`feedback`, `pr`, `budget`, `validate`, and more). Every command has `--dry-run` and a clear report (what it will do, what it did, how to undo).
2. **Slash commands and agents**, thin prompts that run the script, show you the preview, and relay the result. Orchestration commands (`/component:spec`, `/component:plan`, `/component:build`, `/component:fix`, `/component:release`, and the unattended `/component:ship` and `/system:ship`) spawn specialised agents (product manager, architect, coder, tester, security, deployment, release) in phases, routed by shape.

Runs are lean by default: a headless session starts its coordinator on Sonnet (`--model` or `coordinator_model` in `.platform-settings.yml` or `~/.config/sdlc-foundry/settings.yml` changes it; the architect and reviewer keep their own model), `cplat pr open` commits, pushes and opens the pull request in one step, `cplat quiet <script>` prints one line for a passing check, and agents get a brief with their criteria and task instead of rereading the whole spec. In the platform's benchmark a small change dropped from about $0.48 to $0.15 and a full build from $1.94 to $1.26 (estimated list prices). Run records feed a weekly retro (`cplat platform retro`) that proposes the next specs from evidence.

Runs are also bounded. One budget covers a whole run tree: 180 minutes, 60 invocations, 6 reruns and $15 per ship (`--budget` changes it). A run that fails twice in an equivalent way stops instead of trying a third time, and leaves a recovery snapshot; `cplat budget` shows what is left. In fix rounds `cplat validate` runs only the checks a change can affect, while the final gate and the pull request CI stay full. With `CPLAT_OTLP_ENDPOINT` or `telemetry:` set, a run can export usage metrics (never prompts or tool content) to OpenTelemetry, local endpoints only unless `allow_remote` is set, and the lgtm stack ships a Claude Code usage dashboard. Details: [Unattended delivery](/sdlc-foundry/guides/unattended-delivery/).

Rules every agent follows: use `devbox run <recipe>` and never call tools directly; ask before pushes, pull requests, repository creation and anything that touches a cluster; stop and offer `/issue:report` when a platform template or script misbehaves. The full model, including phases and context hand-offs, is in [the agent model](/sdlc-foundry/guides/agents/).
