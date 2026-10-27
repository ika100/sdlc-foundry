# ADR-055: The local console is a stdlib web server over `cplat` JSON; it acts only through Claude Code

**Status:** Accepted (2026-10-26)
**Builds on:** [ADR-053](053-domain-model.md) (the domain model), [ADR-054](054-five-zero-interface-and-proved-migration.md) (the renderer is the only validator of `system.yaml`), [ADR-032](032-private-run-store.md) (run records), [ADR-043](043-one-budget-per-run-tree.md) (budgets), spec 122

## Context

Spec 122 adds a console that a user starts with `cplat ui`: three places (Inbox, Board, System), side panels, a `⌘K` palette, actions and notifications. It runs on the user's machine, from the platform checkout that the marketplace installed, often offline, and it must add no server, no telemetry and no second place where state lives. Four choices in it outlive the spec:

1. **UI technology.** The repo already has an Astro site (`site/`) and a Next.js template. Both need Node, an npm install and a build step. The plugin checkout is not built on install, `devbox run test-fast` runs only pytest, and every third-party asset needs a license entry and a pin.
2. **How the console reads data.** It could import the `cplat` modules or run the CLI. The spec makes the JSON of `cplat model show`, `system status`, `spec list`, `runs` and `needs` the only source.
3. **How it changes anything.** The console could call `git`, `gh` or `kubectl`, or edit `system.yaml`. That would be a second write path next to the slash commands.
4. **Where notifications are sent from.** Webhook URLs and SMTP credentials must stay on the machine, so delivery cannot run in a GitHub workflow.

## Decision

1. **A Python standard-library server with HTML rendered on the server and one hand-written script.** `cplat ui` runs `http.server.ThreadingHTTPServer` bound to `127.0.0.1` on a free port. Pages and side panels are HTML fragments built in Python (`scripts/cplat/console/`), so pytest can test what each page shows. The browser loads one CSS file and one dependency-free JavaScript file from `scripts/cplat/console/static/`. They handle the palette, the keyboard, side panels, polling and the actions panel. There is no npm, no build step, no CDN, no web font and no vendored library. POST requests need a token that is created on each start and embedded in the page, and requests whose `Host` is not `127.0.0.1:<port>` are refused (DNS rebinding).
2. **The console reads only `cplat` JSON, run as a subprocess.** Each source is one `cplat … --json` call with a timeout. It is cached with the time it was read and refreshed in the background, and when it fails it is marked unavailable on its own. A crash or a hang in one source never affects another, and the console sees exactly what a user or an agent sees on the command line. Repo content comes from a snapshot of each system repo's `main` (and of open draft spec pull requests), downloaded with `gh` into the user's cache. The console never reads a working tree and never writes to one.
3. **Every change is a slash command run by Claude Code.** An action shows the exact command (and, for `system.yaml`, the diff that the renderer computed on a scratch copy), and runs it on confirm as `cplat headless "<command>"` in the target repo. That gives budgets, run records and resumes for free. The console itself never runs `git` writes, `gh` writes or `kubectl`. Without `claude` on the PATH it is read-only and says so.
4. **Notifications are delivered locally.** `cplat ui notify` (started by the console as a child process, or from cron or launchd with `--once`) compares `cplat needs`, `cplat runs` and the alert and smoke issues with a local state file and sends to GitHub, a Slack incoming webhook, SMTP e-mail and the desktop. Settings are in `~/.config/sdlc-foundry/notify.yaml`. Secrets come only from the environment or the OS keychain.

## Consequences

- The console has no dependencies outside the Python standard library, plus `pyyaml` and `ruamel.yaml`, which `cplat` already declares. It works offline after the marketplace install, and `reuse lint` needs no new license.
- New views are Python functions that return HTML and are tested with pytest. Behaviour that lives only in the browser (key handling, focus) is kept small and is checked by static tests against the markup contract (`data-key`, `data-action`, `aria-*`).
- Each refresh starts a few short `cplat` processes, about one per source every 30 seconds. That is cheap compared with the `gh` and `kubectl` calls inside them.
- Whatever the console shows can be reproduced from the command line, and whatever it does is a command in a run record.
- A later hosted or multi-user console would need its own ADR. This one stays local, single-user and acts with the user's credentials.

## Not included

- A JavaScript framework, a bundler, or reusing the Astro site for the console.
- Editing files, merging pull requests or promoting through `kubectl` from the console.
- A Slack app (webhooks only) and any telemetry.
