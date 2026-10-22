# Unattended delivery: from an approved spec to dev

How to let Claude take a feature from spec approval to a running `dev` without you watching. This works on GitHub Free with private repos ([ADR-028](adr/028-unattended-delivery-without-branch-protection.md)).

## The flow

```
you:        /svc:spec <feature>  →  answer its questions  →  /svc:spec approve <NNN>     (the only decision)
unattended: /svc:ship <NNN>
              plan     architect writes plan.md (skipped when a valid plan exists)
              build    failing acceptance tests → coders until green → QA → reviewer (verification.md) → image
              pr       cplat ship pr: pushes feature/<spec>, opens the PR
              land     cplat ship land: waits for every check; red → logs → coder → push (≤ 3 rounds); green → squash merge
              deploy   cplat ship deploy: the service's CI publishes sha-<7>, pin-dev merges the pin PR after CI, Argo syncs
you:        check dev  →  /gitops:promote <svc> dev staging   (reviewed PR, as before)
```

The run stops on its own only when it is done or escalated. While it is unfinished, the shared plugin's Stop hook refuses to let the session end (spec 066). It escalates (`cplat ship escalate '<reason>'`) when a rule needs you: a merge conflict, a changed acceptance test, a CRITICAL security finding, a decision the spec does not answer, red CI after three fix rounds, a closed pin PR. `/svc:ship <NNN>` resumes where it stopped. `cplat ship status` shows the phase at any time.

## Run it without a terminal session

```bash
cplat headless "/svc:ship 012"                         # in the repo; resumes in fresh sessions until done or escalated
cplat headless "/svc:ship 012" --quiet 23:30-07:00     # never start inside that window (wait for it to end)
cplat headless "/svc:ship 012" --max-runs 6 --max-minutes 240 --model opus
```

Each session is `claude -p <prompt> --permission-mode dontAsk`: the repo's committed allowlist (`.claude/settings.json`) applies, and everything else is refused instead of prompting. `git push origin main` and `gh pr create` are `ask` rules there, so they are refused; `cplat ship` does the narrow pushes and the PR itself. Logs are in `~/.cache/sdlc-foundry/headless/<repo>/`; `summary.log` has one line per run, and a desktop notification says how it ended (exit 0 shipped, 1 needs you, 3 inside the quiet window with `--no-wait`).

Open the repo interactively once before the first headless run: Claude Code ignores a project's allowlist in a workspace it has not trusted yet ([ADOPTING.md → Unattended runs](ADOPTING.md#unattended-runs)).

### On a schedule (macOS launchd)

```xml
<!-- ~/Library/LaunchAgents/com.me.shop-api-ship.plist -->
<plist version="1.0"><dict>
  <key>Label</key><string>com.me.shop-api-ship</string>
  <key>WorkingDirectory</key><string>/Users/me/Dev/shop-api</string>
  <key>ProgramArguments</key><array>
    <string>/bin/zsh</string><string>-lc</string>
    <string>cplat headless "/svc:ship 012" --quiet 23:30-07:00 --no-wait</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
</dict></plist>
```

Outside a Claude session `cplat` is not on the PATH: use the plugin's launcher (`~/.claude/plugins/marketplaces/sdlc-foundry/plugins/shared/bin/cplat`), or `uv run <sdlc-foundry checkout>/scripts/cplat/cplat.py`.

## What has to be in place

| Piece | Why | Check |
|---|---|---|
| The repo is a platform repo (`.copier-answers.yml`) | shape routing, recipes, allowlist | `/shared:doctor`; existing repos: `cplat adopt --type <shape>` |
| CI on pull requests reports checks | `land` never merges without a check | a PR shows checks; self-hosted runners: `vars.CI_RUNNER` ([guide](self-hosted-runners.md)) |
| `.platform-app.yml` and the `GITOPS_TOKEN` secret | the service's CI asks the gitops-app for the dev pin (ADR-027) | the `pin-dev` job on `main` does not print a notice |
| The service is in the gitops-app's `services.yaml` | pin-dev pins only composed services; for services the generator cannot express, use an `external` entry ([ADR-029](adr/029-external-services.md)) | `/shared:status` in the gitops-app |
| Actions may open PRs in the gitops-app | pin-dev opens the pin PR | `gh api repos/<org>/<gitops>/actions/permissions/workflow` |
| Optional: a kube context | `cplat ship deploy --context <ctx>` also waits for Argo `Synced/Healthy` | `kubectl --context <ctx> -n argocd get applications` |

## Safety on the free plan

`main` cannot be protected on GitHub Free for private repos, so a human with write access can still push to it. Unattended runs cannot: the allowlist refuses `git push origin main`. Every automated merge (feature PRs through `cplat ship land`, pin PRs through `pin-dev`) happens only after its checks passed. A merge happens without a human review of the PR. The approved spec, the acceptance tests written before the code, and the reviewer's `verification.md` (required for `done`, spec 068) are the review. Use `/svc:ship <NNN> --no-merge` to read the PR yourself first.
