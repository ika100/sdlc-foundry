# ADR-036 — The coordinator runs on Sonnet; project and user settings choose otherwise

**Status:** accepted (2026-10-25, spec 100)

## Context

A headless session starts on the user's default model, usually Opus. In the spec-099 benchmarks the coordinator (the
main session that runs the slash command) made most of the calls and most of the cost (quick-task: $0.36 of $0.48;
build: $1.03 of $1.64), although its work is orchestration: run cplat, brief agents, read their reports. The agents
that need judgement (architect, reviewer, product-manager) already pin `model: opus` in their frontmatter. cplat had
no settings file: user configuration was environment variables, per-repo facts were files read ad hoc.

## Decision

- `cplat headless` always passes `--model` to `claude -p`. Default `sonnet`.
- Accepted values: `sonnet`, `opus`, `haiku`. Anything else is refused before a run starts.
- Precedence: `--model` flag, then the project setting `coordinator_model` in `<repo>/.platform-settings.yml`, then the
  user setting in `${XDG_CONFIG_HOME:-~/.config}/sdlc-foundry/settings.yml`, then the default. Each file's
  `coordinator_model` is a string or a map of workflow name to model with an optional `default`; within a file the
  workflow entry beats the general one.
- These two files are the platform's settings files from now on; later settings (budgets, #144) go there, read by
  `scripts/cplat/settings.py`.
- Subagents keep the model of their frontmatter; the coordinator setting never changes them.

## Consequences

- Runs cost less without any configuration; a project that wants Opus for `build` writes one line.
- The run record names the model and where it came from, so benchmarks and reports can compare like with like.
- Interactive sessions are not affected: the user picks their model there.
