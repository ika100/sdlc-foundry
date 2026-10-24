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
              deploy   cplat ship deploy: the service's CI publishes sha-<40>, pin-dev merges the pin PR after CI, Argo syncs
you:        check dev  →  /gitops:promote <svc> dev staging   (reviewed PR, as before)
```

The run stops on its own only when it is done or escalated. While it is unfinished, the shared plugin's Stop hook refuses to let the session end (spec 066). It escalates (`cplat ship escalate '<reason>'`) when a rule needs you: a merge conflict, a changed acceptance test, a security finding with no fix released, or a bump that breaks a gate, a decision the spec does not answer, red CI after three fix rounds, a closed pin PR. `/svc:ship <NNN>` resumes where it stopped. `cplat ship status` shows the phase at any time.

### Dependency patches

When the security gate is red because of dependencies with a released fix, the run bumps them itself (`cplat deps patch`, spec 095), re-runs the gates and commits the bump, or reverts it exactly. The PR body lists each bump under "Dependency patches" (a major bump is marked) and the run record has a `patches` section. At most 2 rounds; a finding without a fix, or a bump that breaks a gate, escalates.

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
| The `SERVICE_REPOS_READ_TOKEN` secret in each gitops-app (spec 098) | `cplat ship gitops pr` marks its PRs with `Service-ref: <owner>/<repo>@<branch>`; the gitops CI reads that branch's CRDs with this token (fine-grained, Contents: read on the service repos) and validates the Components against them. Without it a marked PR fails its check | `cplat doctor` in the gitops-app (a warning when missing) |
| The service is in the gitops-app's `services.yaml` | pin-dev pins only composed services; for services the generator cannot express, use an `external` entry ([ADR-029](adr/029-external-services.md)) | `/shared:status` in the gitops-app |
| Actions may open PRs in the gitops-app | pin-dev opens the pin PR | `gh api repos/<org>/<gitops>/actions/permissions/workflow` |
| Optional: a kube context | `cplat ship deploy --context <ctx>` also waits for Argo `Synced/Healthy` | `kubectl --context <ctx> -n argocd get applications` |

## Run records

Every run is recorded as one JSON record in a private GitHub repo (spec 087, [ADR-032](adr/032-private-run-store.md)).

- **Setup:** `cplat runs init <owner/name>` creates the repo private (or checks an existing one) and prints `export CPLAT_RUNS_REPO=<owner/name>`. Put that line in the shell profile your Claude sessions read.
- **A record holds** kind, repo, spec, phases with durations, CI rounds, reruns, the escalation reason and cause, and the outcome. **It never holds** secrets (redacted), file contents or logs.
- **Offline:** without a store, or when it is unreachable, records wait in a local buffer (1000) and one warning line says so. The run itself is never affected. `cplat runs flush` writes the buffer; `cplat doctor` shows what is waiting.
- **Read it:** `cplat runs report [--json] [--since DAYS]`.

### Agent metrics

A build record also says how each agent did (spec 089), per agent, shape and model: `cplat runs report --agents [--json] [--since DAYS] [--repo R] [--agent NAME] [--shape SHAPE]`.

- **What is counted, against whom:**
  - coder: hand-backs (`fix rounds` by cause lint/type, test, ci, verification), red PR CI rounds (`cplat ship land` records them, always against the coder), review findings (first pass and after a fix) and refused acceptance-test diffs;
  - architect: files outside the plan, merge conflicts (and the share that was resolved) and re-plans;
  - quality: refused test diffs; tester: untraced criteria and tests that failed for the wrong reason.
- **Not measured:** a metric whose point the run never reached (an escalated Phase 0, a ship that never built, a record from before spec 089) is `n/a`, never 0, and is left out of the averages.
- **`few runs`** marks a row with fewer than 5 runs: do not read a trend into it.
- **Releases:** `--by-version` splits every row by platform version, versions side by side, so you can compare before and after a release.
- **Incomplete:** a recording call that failed or was malformed never stops the build; it marks the run `incomplete` (counted in the row) and the report still shows what was recorded.

### Weekly retro

Every Monday the platform looks back at the last complete week and proposes what to build next (spec 090, [ADR-035](adr/035-weekly-retro-evidence-checked-proposals.md)).

- **Three steps, one directory:** `cplat retro --out DIR` builds the report (`report.json`, `report.md`, `prompt.md`), `cplat retro propose --dir DIR` lets headless Claude write `proposals.json`, `cplat retro post --dir DIR` checks and posts. A failed proposal step still posts the report with `Proposals: not generated (<reason>)`.
- **The report** covers ISO week Monday to Sunday UTC, every figure next to the week before: runs per kind and outcome, phase durations, CI rounds and reruns, escalations by cause with the top reasons, reruns by check, platform issues counted again in the week, and the per-agent metrics of spec 089.
- **Proposals are checked:** each cites evidence refs of the report with their exact values. A proposal without a matching ref, with a bad format, or over the limit (5 specs, 3 prompt changes) is refused and counted. A finding an open spec or issue already covers is shown as `amends spec NNN` or `see #N`.
- **Public and private:** the issue `Weekly retro <week>` in `ika100/sdlc-foundry` has counts and placeholders only. A leak check stops the post if a repo, spec or store name remains. The full report goes to `retros/<week>.md` and `.json` in the run store. An earlier week's open retro issue is commented on and closed.
- **Setup:** `cplat runs init <owner/name>` adds `.github/workflows/cplat-retro.yml` to the store (it needs `gh auth refresh -h github.com -s workflow` once). Give the store repo a self-hosted runner (variable `CI_RUNNER`) and the secrets `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`) and `RETRO_GH_TOKEN` (fine-grained: Issues read/write on the platform repo, Contents read/write on the store). `cplat doctor` warns about what is missing.
- **By hand:** `cplat retro` prints the report and writes nothing; `cplat retro --week 2026-W42` picks another complete week.

## Auto-filed platform issues

When a run stops because the platform itself misbehaves, the failure is filed as an issue in `ika100/sdlc-foundry` (spec 088, [ADR-033](adr/033-auto-filed-issues-with-signatures.md)).

- **What is filed:** an escalation with `--cause platform`, and a crash (stack trace) of any `cplat` command inside a recorded run. **Never filed:** causes `code`, `decision`, `environment` and `unknown`, and crashes outside a recorded run (those print the `/shared:report-issue` hint).
- **One issue per failure:** the body has a `Signature:` line. A repeat adds a +1 comment (occurrence number, date, platform version, shape, run id) to the oldest open issue. After the issue was closed, a repeat files a new issue that says `Seen again after #<n> was closed`, unless the closed one is labelled `wontfix`: then nothing is filed and the run record notes `suppressed by #<n>`.
- **Redaction:** tokens, passwords, e-mail addresses and home paths are removed, and your repo, spec and branch are replaced by `<repo>`, `<spec>` and `<branch>`. The issue names the run id but never links the private run store.
- **Cap:** at most 10 new issues per 24 h per machine. +1 comments are not capped.
- **Offline:** if filing fails (`gh` missing or not logged in, no network) or the cap is reached, the escalation still completes with the same exit status, prints `not filed: <reason>`, and the filing is retried at the next `cplat runs flush`.
- **Off switch:** `CPLAT_AUTO_ISSUES=off` sends nothing and prints the draft instead. `CPLAT_FEEDBACK_REPO=<owner/name>` files in another repo. Run `cplat triage setup-labels` once so the `auto-filed` label exists.

## Safety on the free plan

`main` cannot be protected on GitHub Free for private repos, so a human with write access can still push to it. Unattended runs cannot: the allowlist refuses `git push origin main`. Every automated merge (feature PRs through `cplat ship land`, pin PRs through `pin-dev`) happens only after its checks passed. A merge happens without a human review of the PR. The approved spec, the acceptance tests written before the code, and the reviewer's `verification.md` (required for `done`, spec 068) are the review. Use `/svc:ship <NNN> --no-merge` to read the PR yourself first.
