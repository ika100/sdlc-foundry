# starter plugin

Installs the sdlc-foundry starter set in one step. It holds no commands, agents, skills, hooks or `bin/` of its own; it only declares dependencies.

## What it installs

- `shared`: the `cplat` launcher, the quality and security agents and the session hooks.
- `system`: the system commands (`/system:new`, `/system:spec`, `/system:plan`, `/system:ship`).
- `component`: the component commands (`/component:new`, `/component:spec`, `/component:build`, `/component:ship`).
- `platform`: the platform commands (`/platform:doctor`, `/platform:update`).

Requires Claude Code 2.1.311 or later.

```text
/plugin marketplace add ika100/sdlc-foundry
/plugin install starter@sdlc-foundry
```

## Installing one plugin on its own

Each plugin can still be installed on its own, for example `/plugin install component@sdlc-foundry`. It brings `shared` with it, because every live plugin declares `shared` as a dependency.

## Removing the set

Remove the set with `claude plugin uninstall starter@sdlc-foundry --prune`. This also removes the dependencies that no other installed plugin needs.
