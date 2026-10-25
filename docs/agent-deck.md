# Optional: watching agents live with dot-agent-deck

[vfarcic/dot-agent-deck](https://github.com/vfarcic/dot-agent-deck) is a local dashboard for agent sessions: one card per agent with its status (Thinking, Working, Needs Input, Idle, Error, Blocked), its terminal, and a way to type into it or stop it. Next to the platform it is an **operator cockpit**: it shows what the sessions are doing right now. It is not part of the platform, nothing installs it, and every command works the same without it.

This guide was written against **dot-agent-deck v0.48.1** (2026-10-25) and its documentation at that tag. Upstream changes quickly (several releases a week), so when something here disagrees with your installed version, trust `dot-agent-deck docs <topic>`, which always matches the binary. Several unrelated tools are called "Agent Deck"; this page means only vfarcic/dot-agent-deck.

## What it adds, and what stays with the platform

| Question | Where the answer comes from |
|---|---|
| Which sessions are running, which is waiting for me, which is stuck? | dot-agent-deck (live status from Claude Code hooks) |
| Type into a session, or stop one | dot-agent-deck (the agent's pane, `Ctrl+w` in command mode, `dot-agent-deck close`) |
| Did the run finish, with which outcome, PR and gates? | The run store: `cplat runs report`, `cplat ship status` ([run records](unattended-delivery.md#run-records)) |
| What did it cost in tokens and dollars? | `cplat runs usage` and the run record's `usage` section (spec 099), never the dashboard |
| Is the change correct and safe? | Tests, the reviewer's `verification.md`, CI, `cplat pr wait`, and the ship gates |
| Is the run within its limits? | The platform's own budgets (spec 102), not the dashboard |

The deck shows activity; it does not enforce anything. Approval policies (the allowlists in `settings.json`, `--permission-mode`), quality and security gates and budget limits work the same whether or not the deck is open, and seeing a session in the deck is not evidence that it did the right thing.

## Install

macOS or Linux with Homebrew ([other methods](https://github.com/vfarcic/dot-agent-deck/blob/v0.48.1/docs/installation.md)):

```bash
brew tap vfarcic/tap && brew install dot-agent-deck
dot-agent-deck --version      # prints: dot-agent-deck 0.48.1 (or newer)
```

To stay on the release this guide was checked against, download the `v0.48.1` binary from the [release page](https://github.com/vfarcic/dot-agent-deck/releases/tag/v0.48.1) instead of tracking Homebrew.

**What gets installed in your Claude Code setup.** Whenever the deck's TUI or daemon starts, it writes hook entries into `~/.claude/settings.json` (`SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, `PreCompact`, `SubagentStart`, `SubagentStop`, and `StopFailure` on Claude Code 2.1.78+). They call the binary by its absolute path. Your own hooks, and the platform's plugin hooks (the shared plugin's `SessionStart` and the `Stop` gate of `/svc:ship`), are left as they are. Because these are user-level hooks, they also fire in `cplat headless` and `cplat runs benchmark` sessions, which then show up on the dashboard too. To install them by hand or remove them:

```bash
dot-agent-deck hooks install      # Claude Code is the default agent
dot-agent-deck hooks uninstall --agent claude-code
```

## Minimal setup for a platform repo

No project file is needed to watch sessions. Set the command new agents start with, once:

```bash
dot-agent-deck config set default_command "claude"
dot-agent-deck config get default_command     # prints: claude
```

This writes `~/.config/dot-agent-deck/config.toml`. A project's `.dot-agent-deck.toml` is only for the deck's own orchestrations (several cooperating agents it starts and delegates between). The platform already coordinates its agents (`/svc:build`, `/svc:ship`), so don't add one to a generated repo. If you experiment with it, `dot-agent-deck init` creates it and adds `.dot-agent-deck/` to `.git/info/exclude`, and `dot-agent-deck validate` checks it. Unknown keys are silently ignored, so check against the [configuration reference](https://github.com/vfarcic/dot-agent-deck/blob/v0.48.1/docs/configuration.md#dot-agent-decktoml-reference).

## A session with the deck open

1. Set up the repo as usual (`/shared:doctor` green, the plugins installed).
2. Start the deck: `dot-agent-deck`. On a first run it shows `No active agents. Press Ctrl+n to create an agent.`
3. `Ctrl+n`, pick the repo's directory, accept the name, submit the command (`claude`). In that pane, run the platform command, for example `/svc:build 042`.
4. Watch the card: subagents (coder, tester, reviewer) show as activity of that session, and **Needs Input** means the session is waiting for you, for example on a permission prompt.
5. To step in, select the card and type into its pane. To stop it, close the pane (`Ctrl+w` in command mode; it asks to confirm) or, from another terminal, `dot-agent-deck close`. A `/svc:ship` run stopped this way is unfinished, not lost: its state is in `<git dir>/cplat-ship.json`, and `/svc:ship <id>` or `cplat headless` resumes it.
6. Judge the result the normal way: the PR's CI (`cplat pr wait <pr>`), `verification.md`, and `cplat runs report` for the run's outcome and cost.

`dot-agent-deck daemon status` prints the same view as text (pane, agent, role, status, current tool, directory) without starting anything. That is handy for checking over ssh whether a headless run is still working.

## Local data and security

- **Local by default.** The daemon owns the agent processes and talks to their hooks over a local socket; it opens no network port. Session state is under `~/.config/dot-agent-deck/` (`session.toml`, `config.toml` and a few small state files).
- **Remote hosts** (`dot-agent-deck remote add`, `connect`) run a daemon on the other machine over ssh with key-based login. Anyone who can ssh into that account as you can drive the agents running there, with that host's agent credentials. Register only machines you control.
- **Telemetry is off** unless the daemon's environment sets `OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`). It then sends metadata only (no prompts, file contents or output), and the agents it starts inherit those variables. If you also export Claude Code's own usage over OpenTelemetry (spec 101), point both at the same private collector, and remember that the cost figures of record still come from the run store.
- **Credentials** are the agents' own; the deck does not hold an API key. Keep secrets out of `OTEL_RESOURCE_ATTRIBUTES`, which is sent as written.

## Limitations

- It is a local tool for one operator, not a shared control plane, an audit log or a multi-tenant dashboard. What happened in a run is recorded in the run store and in GitHub (PRs, CI, issues).
- It sees only sessions on machines where its hooks are installed; CI jobs on the ARC runners and the weekly retro in the run store repo are invisible to it.
- Status comes from hooks. A session started before the hooks were installed needs a restart, and a card that never changes state means the hooks are not reaching the daemon ([upstream troubleshooting](https://github.com/vfarcic/dot-agent-deck/blob/v0.48.1/docs/troubleshooting.md#hooks)).
- Upstream moves fast. After an upgrade, a hook that calls an older copy is reported in the TUI with the fix (`brew upgrade dot-agent-deck` or `hooks install` from the copy you want).

## Troubleshooting

Start with `dot-agent-deck docs troubleshooting` (it matches your version), then the [upstream issues](https://github.com/vfarcic/dot-agent-deck/issues). Problems with the platform commands themselves go to `/shared:report-issue`; check first that they also happen with the deck closed.
