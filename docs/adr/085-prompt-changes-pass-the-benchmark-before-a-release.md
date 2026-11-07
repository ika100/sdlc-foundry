# ADR-085: Prompt changes pass the benchmark before a release

**Status:** Accepted (2026-11-07, spec 151)
**Builds on:** [ADR-035](035-token-usage-from-session-transcripts.md) (the benchmark and its records)

## Context

The platform's behaviour lives in prompts: agent definitions, commands, references and skills. Unit tests check their
text; only a run shows whether an agent still finishes and what it costs. The benchmark of spec 099 runs fixed tasks on a
pinned sample repo with a checkout's plugins and records outcome and tokens, but nothing asked for it, so a prompt change
was first measured in a journey or by a user.

## Decision

1. **Prompts are `plugins/*/{agents,commands,references,skills}/**/*.md`.** When one changed since the last tag, a release
   needs a `done` benchmark record of `quick-task` and `build` whose plugins had exactly this `plugins/` tree.
2. **Cost is part of the result:** such a run may use at most 1.5 times the median tokens of the last release's `done`
   runs of the same workflow.
3. **`cplat platform eval-gate` decides, `cplat platform release` asks it** before it creates the release branch;
   `--skip-eval "<why>"` overrides it and puts the reason into the release PR.

## Consequences

- A release that changed prompts costs two benchmark runs (minutes, a few dollars) before the release PR.
- The benchmark tasks become the platform's regression suite for prompts; new tasks (for example replays of past
  escalations) strengthen the gate without changing it.
