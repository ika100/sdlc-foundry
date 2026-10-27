# ADR-060: Autonomy is declared in system.yaml; an engine is bound by a contract and only signals can act before a merge

**Status:** Accepted (2026-10-27)
**Builds on:** [ADR-053](053-domain-model.md) (the domain model), [ADR-054](054-five-zero-interface-and-proved-migration.md) (the renderer is the only validator of `system.yaml`), [ADR-032](032-private-run-store.md) (run records), [ADR-055](055-local-console-over-cplat-json.md) (the console acts only through slash commands), spec 124

## Context

Spec 124 lets an always-on engine fix the running system without a person. In 5.x that engine is ai-ops, a separate repository built from `service-go`. Before this, its AutonomyPolicy lived in a cluster resource, which could disagree with the promotion rules in `system.yaml` and could not be reviewed. Four choices in the spec outlive it:

1. **Where the policy lives and who validates it.**
2. **How an engine reads it.** An engine in Go cannot run `cplat`, and recomputing defaults and effective levels in the engine gives two definitions that drift apart.
3. **How a person stops it in an incident.** Every other change on the platform waits for a merged pull request (AC-122.18).
4. **Where an engine's history lives.** The engine has its own tamper-evident store, but the console and `cplat` must still work when the cluster is down.

## Decision

1. **The policy is part of `system.yaml` and the renderer validates it.** `environments.<env>.autonomy` (level, guardrails, `engine` address), a top-level `autonomy: {paused: true}`, and a per-instance cap `components.<c>.instances.<env>.autonomy: {max}` that can only lower the level. Prod is capped at `act`. `promote` (spec 093) still decides every promotion, at any level. An engine never promotes forward. Its only pin change is the rollback of a failed dev smoke to a tag dev ran before.
2. **The renderer writes the effective policy as one JSON file, `applications/<system>/autonomy.json`, when a system declares autonomy.** It holds the defaults filled in, the effective level of each environment and instance, and the promotion rule. It equals the autonomy part of `cplat model show --json`, and the engine reads it at `main` with that commit's SHA. A missing file means `observe` everywhere, so systems without autonomy render as before. `cplat`'s `autonomy.py` holds the same table, and a test keeps the two equal.
3. **Signals act at once, but only downward, and a pull request records each one.** `pause`, `resume` and `lower` go over HTTP to the environment's engine. A signal can only set an environment at or below the merged policy: `lower` carries the tighter value of each field, the engine refuses one that loosens anything, and `resume` only lifts a pause back to the merged policy. Every signal is followed by a pull request, so git stays the record. These are the only changes that act before their pull request merges.
4. **The engine writes its runs and audit events into the platform's private run store.** Runs go to `runs/` (kind `fix`, `actor` = the engine) and audit events to `audit/`, each with the policy level, the guardrails and the commit that allowed it, plus a reference into the engine's own tamper-evident store. `cplat` reads history only from the run store. Only the heartbeat and the signal answer come from the engine directly.

## Consequences

- A person reviews every change to autonomy as a `system.yaml` diff, and every tool reads the same effective values. A gitops repo needs the renderer of this release before it can declare autonomy.
- A second engine (another vendor) can serve a system by implementing the same contract: `autonomy.json`, the signal and status endpoints, the issue format, and the run and audit records. Nothing in the platform names ai-ops except as the example.
- Raising autonomy always waits for a merge, while lowering and pausing never do. When an engine cannot be reached, the pull request still records the person's intent, and the console shows the environment as not confirmed until the engine catches up.
- The run store gains a rewritten record kind (engine runs are rewritten per phase) and a second prefix (`audit/`). `cplat platform runs report` counts engine runs like any other run.
- The engine's tamper-evident store stays the authority for its own integrity. The run store is the readable copy the platform depends on.

## Not included

- How an engine detects, triages and fixes. That is specified in the engine's repository against this contract.
- `improve` beyond acting as `act`, which waits for a later spec.
- Promotion to prod by an engine, at any level.
