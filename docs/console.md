# The local console

A browser page on your machine that shows the system, its process and what needs you. It reads the same data as `cplat ... --json`; every change it makes is a slash command run by `cplat headless` in your local clone, so budgets, run records and resumes apply. It never writes to git, GitHub or the cluster itself. Design: [ADR-055](adr/055-local-console-over-cplat-json.md).

## Start it

In a `gitops-app` clone:

```
/platform:ui                  # or: cplat ui
/platform:ui --no-open        # print the URL, do not open the browser
/platform:ui --port 8800      # fixed port; default is a free one
```

The server listens on `127.0.0.1` only and refuses other hosts. Stop it from the user menu ("Stop console") or by ending the process; actions still running are marked `stopped`. Without `applications/<system>/system.yaml` it says so and exits. Use the user menu's "Switch system" to open another system (a missing clone is made under `workspace`, default `~/src`).

## The three places

- **Inbox:** what waits for you, oldest first: spec approvals, open questions, escalations, promotions to prod. Keys: `j`/`k` move, `Enter` opens, `a` approve, `p` promote, `Escape` closes. `Cmd/Ctrl+K` opens the palette.
- **Board:** every issue and spec as a card in its stage. Switch between columns, list and done; filter by period or text.
- **System:** components by environment: pinned version, CI, sync and health, plus the APIs a component provides and consumes.

## Stages

An item moves through `Issue`, `Spec`, `Plan`, `Build`, `Land`, `Dev`, `Staging`, `Prod`. You decide at three of them: approving a `Spec`, an escalated `Build`, and `Prod`. The rest runs unattended. The stage comes from the issue, the spec status and the run list (phase of the latest run).

## Actions

Buttons on a card or panel start one action: approve, approve and ship, request changes, answer, promote, give more budget, amend, fix, make a spec, dismiss, cut a release, or describe new work. The forms that change the system (`/component:add|set|remove`, `/resource:add|remove`, `/system:set`, `/system:new`) first show a preview: the command, the `system.yaml` diff on a scratch copy, the render check and the consequence. One action runs per object. A missing prerequisite (`claude`, `gh`, a kube context, a clone) is named before anything starts. "Open in Claude Code" hands an item to an interactive session.

## Notifications

`cplat ui` starts the notifier; without the console, schedule it:

```
*/5 * * * *  cplat ui notify --once        # cron; use a launchd StartInterval job on macOS
```

Choose channels in `~/.config/sdlc-foundry/notify.yaml` (also in Settings):

```yaml
preset: recommended          # GitHub and desktop for decisions and alerts
events:                      # approve answer escalation promote alert smoke run-done retro
  promote: {github: instant, slack: digest}
slack: {channels: ["#shop-dev"]}
email: {to: me@example.com, from: cplat@example.com, host: smtp.example.com, port: 587, user: me}
digest: {at: "09:00", days: [mon, tue, wed, thu, fri]}
quiet_hours: "22:00-07:00"
```

Values are `off`, `instant` or `digest` (`digest` for Slack and email only). Quiet hours hold instant sends, except a prod alert. When an item is resolved its issue is closed and the assignment removed.

Secrets never go in the file (it refuses `webhook`, `url`, `password`, `token`). Set `CPLAT_SLACK_WEBHOOK_<CHANNEL>` (`#shop-dev` becomes `SHOP_DEV`) and `CPLAT_SMTP_PASSWORD` in the environment, or store them in the OS keychain under service `sdlc-foundry` (accounts `slack-webhook:#shop-dev`, `smtp:<user>@<host>`).

## Troubleshooting

Run `/platform:doctor`. It checks the console's prerequisites (`claude`, `gh`, kube access) and warns per notification channel that is switched on but lacks a webhook, address, host or password, naming the setting. A source that fails shows as unavailable with its last data marked stale; the rest keeps working. An action that returns "precondition" names what is missing. Server logs and action logs are under `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/console/`.
