---
name: spec-format
user-invocable: false
description: "Reference for feature specs in docs/specs/<NNN>-<slug>/ (spec.md, design.md, plan.md, verification.md): acceptance criteria ids AC-<NNN>.<n>, lifecycle, plan task metadata, test tagging. Use when writing, reviewing or explaining a spec, design, plan or verification report."
---

# Feature specs (ADR-026)

A feature is described, planned, built and verified from one folder: `docs/specs/<NNN>-<slug>/`.

| File | Written by | Holds | Format |
|---|---|---|---|
| `spec.md` | product-manager | **What**: problem, stories, acceptance criteria, non-goals, assumptions, open questions, changelog | [spec.md](${CLAUDE_PLUGIN_ROOT}/skills/spec-format/references/spec.md) |
| `design.md` | architect (optional) | **How**: decisions, module boundaries, the contract (API, events, errors), data changes | [design.md](${CLAUDE_PLUGIN_ROOT}/skills/spec-format/references/design.md) |
| `plan.md` | architect | **Tasks**: files, dependencies, parallel safety, which criteria each task covers | [plan.md](${CLAUDE_PLUGIN_ROOT}/skills/spec-format/references/plan.md) |
| `verification.md` | reviewer | **Evidence**: per criterion met / not met, with tests and code | [verification.md](${CLAUDE_PLUGIN_ROOT}/skills/spec-format/references/verification.md) |

Tests name the criteria they prove: [testing.md](${CLAUDE_PLUGIN_ROOT}/skills/spec-format/references/testing.md).

## Lifecycle

```
draft ──approve──► approved ──► building ──► done
  ▲                   │            │          │
  └──── amend ────────┴────────────┴──────────┘        any ──► superseded
```

- `draft`: being written. Open questions are allowed.
- `approved`: the user reviewed it, with its assumptions. Approval is refused while open questions remain or no criterion exists. **Hard rule:** only an approved spec can be planned and built, because a build without approval overrides the user's consent.
- `building`: the build started; tasks in `plan.md` are marked `done` as they merge, so a re-run resumes.
- `done`: built, verified, PR opened.
- Amending an approved, building or done spec moves it back to `draft`.

Status is never edited by hand or by an agent, because the checks run in `cplat spec approve` and `cplat spec set-status`.

## Ids

- Spec numbers continue the highest spec or legacy `STORY-NNN` id; the folder is `<NNN>-<slug>` and equals `spec_id`.
- Criteria are `AC-<NNN>.<n>` with the spec's own number. An id is never reused or renumbered, because tests and plans cite it. A withdrawn criterion stays in place, struck through: `- ~~**AC-007.3**~~ withdrawn: <reason>`.

## Deterministic checks (`cplat spec`)

| Command | Does |
|---|---|
| `new <title> [--priority P] [--tracks N…]` | create the folder and a draft `spec.md` skeleton |
| `check [<id>…] [--require approved]` | validate spec + plan: ids, shape, coverage of every criterion by a task, cycles, file overlap of parallel tasks, `spec_hash` drift |
| `hash <id>` | the value a plan records as `spec_hash` |
| `approve <id>` | draft → approved, refused with open questions |
| `set-status <id> <status>` / `task-done <id> <task>` | lifecycle and task progress |
| `trace <id>` | every active criterion is named by at least one test |
| `list` / `index` | status overview with the next command / the table in `docs/backlog.md` |

Agents never validate a spec in prose, because only `cplat spec check` is exact: the orchestrator runs it and hands back its errors.
