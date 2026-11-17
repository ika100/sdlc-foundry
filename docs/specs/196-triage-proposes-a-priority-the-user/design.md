# Design — 196 Triage and new specs propose a priority the user confirms

## Decisions

- **One scale, defined once in `cplat`.** A new module `scripts/cplat/priority.py` holds the three levels, their definitions
  and the fixed definition phrases a reason may name. Triage (batch facts, row validation) and `cplat spec` (proposal,
  skeleton comment) read it, so the prompts carry no definitions and stay within the size limit (spec 168). The existing
  `p0`/`p1`/`p2` label descriptions in `triage.LABELS` already say the same and stay as they are.
- **A proposal reason is `P<n>: <phrase>` with a phrase from the level's list; `cplat` refuses any other wording.** The
  phrases are the user's definitions cut into short names (`P0: data loss`, `P2: easy workaround`), so a reason always names
  the matched definition (AC-196.2) and fits 60 characters (AC-196.1). A reason that is not a proposal is one of the fixed
  texts (`set on the issue`, `changed by you`, `given by you`, `set on the issue #<n>`), so proposal and choice are told
  apart by form alone.
- **Everything mechanical is `cplat`, only the matching is judgement.** The existing-label rule, the multi-label rule, the
  `P1` fallback, the one-label replacement, the `changed by you` reason and the refusal in an unattended run are code; the
  triager and the product-manager only pick the level and phrase whose definition the issue or request matches (Notes for
  the architect, bullets 1 and 3).
- **The product-manager gets the definitions from the spec skeleton, not from its prompt.** `cplat spec new` writes them as
  an HTML comment into the new `spec.md`, which the product-manager reads anyway; its reply block gains one `PRIORITY:` line.
  This costs no prompt bytes.
- **A priority's provenance is its last Changelog line** (A9): `priority P<n> proposed: <reason>`, `priority P<n> given by
  you`, `priority P<n> set on the issue #<n>…`, `priority P<n> changed by you`. A `proposed` priority counts as the user's
  once an `approved` line follows it that is not `approved by cplat dispatch` (A10). Specs without such a line (all specs
  before this change, `--from-plan` slices) have state `unset` and are shown as before.
- **An unattended run is `CPLAT_HEADLESS=1`** (set by `cplat headless` for every session it starts). In it, `cplat spec new`
  records only proposals, `cplat spec priority` (a change) is refused, and `cplat issue triage act`/`apply` refuse any change
  of a `p0`/`p1`/`p2` label (AC-196.4, AC-196.12). That no spec is created in an unconfirmed triage run stays the prompt's
  confirmation gate: specs are written only in step 5, after `OK`.
- **The confirmation line names the reason; the overview stays as it is** (AC-196.1 asks it of the confirmation). The
  exact text of spec 176's confirmation changes, so its fixture (`tests/cplat/test_176_view.py` `PLAN`, and row 563 of
  `support_176.overview_world`, whose reason names `P1` on a `P2` row) is updated in the triage task.
- **The dispatcher's default rules become `label:p0, label:bug, label:p1, spec-order, oldest`** (AC-196.9); nothing else in
  the ordering changes. `prioritize`, `skip` and `resume <item>` already behave as AC-196.9 states.
- No ADR: the scale and the provenance line are this feature's decisions, recorded in the spec's assumptions; no new
  technology or cross-cutting pattern is introduced.
- Every bullet of "Notes for the architect" is followed; no departure.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/priority.py` | levels, definitions, phrases; reason check, most urgent label, batch list, skeleton comment | new |
| `scripts/cplat/spec_priority.py` | the spec's priority provenance: resolve at `new`, `state`, `propose`, `change` | new |
| `scripts/cplat/spec.py` | `spec new` resolution and Changelog line, skeleton comment, `spec priority`, `show`/`summary` fields | changed |
| `scripts/cplat/triage_batch.py` | `priority_levels` in the batch | changed |
| `scripts/cplat/triage_view.py` | label override, fallback, reason check, confirmation reason, `--set` | changed |
| `scripts/cplat/triage.py` | `confirm --set`; `apply_one`: one priority label, replace others, refuse unattended | changed |
| `scripts/cplat/triage_act.py` | refuse unattended priority changes before any write; spec-priority difference in the summary | changed |
| `scripts/cplat/dispatch_policy.py` | default `priority` rules | changed |
| `scripts/cplat/console/panels.py` | priority line in the spec panel | changed |
| `plugins/issue/commands/triage.md` | reason format, `confirm --set` | changed |
| `plugins/component/commands/spec.md`, `plugins/system/commands/spec.md` | `--priority`, `spec priority --propose`, `Priority:` line, change choice | changed |
| `plugins/svc/agents/product-manager.md` | `PRIORITY:` line in the reply (mode `new`) | changed |

## Contract

### `priority.py` (shared)

```python
LEVELS = {   # order = urgency
  "P0": {"definition": "an outage, data loss, a security problem, or something that blocks all other work",
         "phrases": ["outage", "data loss", "security problem", "blocks all other work"]},
  "P1": {"definition": "a normal bug or feature; the fallback when nothing signals urgency",
         "phrases": ["normal bug or feature"]},
  "P2": {"definition": "cosmetic, a convenience, or something with an easy workaround",
         "phrases": ["cosmetic", "convenience", "easy workaround"]},
}
FALLBACK_REASON = "P1: normal bug or feature"
def proposal_reason_ok(level: str, reason: str) -> bool   # reason == f"{level}: {phrase}" for a phrase of that level
def most_urgent(labels: list[str]) -> str | None           # ["p2","p0"] -> "P0"; no p0/p1/p2 -> None
def label_of(level: str) -> str                            # "P1" -> "p1";  level_of("p1") -> "P1"
def levels_json() -> list[dict]                            # [{"level", "definition", "phrases"}] in urgency order
def skeleton_comment() -> str                              # the one-line HTML comment of `spec new`
```

### `cplat issue triage`

- `batch --json` adds `"priority_levels": [{"level": "P0", "definition": str, "phrases": [str]}, …]` (P0, P1, P2).
- **Proposals file row** (existing keys unchanged): `priority`, `priority_reason`, new optional `priority_decided: bool`
  (written by `confirm --set`, never by hand). Effective row after loading, for `bug`, `small-change`, `feature`:
  1. the issue carries one of `p0`/`p1`/`p2` and the row is not `priority_decided` → `priority` = that level,
     `priority_reason` = `set on the issue`, whatever the row said (AC-196.3);
  2. it carries several → the most urgent, reason `set on the issue`, the row stays in the decide group and is marked
     `decide` until `priority_decided` (AC-196.3);
  3. otherwise `priority` is required (`P0`/`P1`/`P2`, error as today); a missing `priority_reason` with `P1` becomes
     `P1: normal bug or feature`; a missing one with `P0`/`P2` is an error (`priority_reason is missing`);
  4. a reason that is neither `changed by you`, `set on the issue` nor `proposal_reason_ok(priority, reason)` is an error:
     `priority_reason must be "<P>: <phrase>" with a phrase of <P>: <phrases>`; longer than 60 characters stays the
     existing error.
  Other classes: unchanged (`a <class> row has no priority`).
- **`confirm`** text line of a priority row: `#<n>  <class>, <P> (<reason>): <phrase>`; a row marked decide:
  `#<n>  <class>, <P> (set on the issue; p0, p2: decide): <phrase>` (the issue's priority labels in urgency order). Other
  rows unchanged. Example: `  #560  bug, P0 (P0: data loss): queue the fix, it runs on its own`.
  `--json` lines: `{"number", "class", "text", "priority": "P0"|null, "priority_reason": str|null, "decide": bool}`.
- **`confirm --proposals F --set N=P [--set N=P …]`** (`P` in `P0 p0 P1 p1 P2 p2`): writes into F for row N `priority`,
  `priority_decided: true` and `priority_reason` = `changed by you` when P differs from the row's effective priority, else
  the effective reason; then prints the confirmation as without `--set` (text or `--json`). Errors, F unchanged, exit 1:
  `#N is not an issue of the batch`, `#N is a <class>: it gets no priority`, `--set takes N=P0|P1|P2`.
- **`apply N --add … --remove …`** (and `act` through `apply_one`):
  - two or more of `p0`/`p1`/`p2` in `--add` → exit 1 before any GitHub call:
    `ERROR: more than one priority label: p0, p1` / `fix: an issue carries one of p0, p1, p2` (AC-196.5);
  - one priority label added → every other priority label the issue carries is removed in the same edit;
  - `CPLAT_HEADLESS=1` and the edit adds or removes a priority label → exit 1, nothing changed:
    `ERROR: a priority label needs the user's confirmation` / `fix: run /issue:triage in a Claude Code session`.
- **`act`** computes the actions of all named rows first; under `CPLAT_HEADLESS=1` any priority-label change among them
  raises the error above before the first write. A confirmed `feature` row whose `spec` is an existing spec
  (`new_spec` not set) with a `priority` different from the row's adds to the summary, after the `Done` groups:

  ```
  Priority
    #560 p1, spec 123 P2: the spec keeps P2; change it with cplat spec priority 123 P1
  ```

  and to `--json` `"priority_notes": [{"number": 560, "label": "p1", "spec": "123-x", "spec_priority": "P2",
  "command": "cplat spec priority 123 P1"}]` (empty list when none) (AC-196.7).

### `cplat spec`

- **`spec new`**: `--priority` has no default any more and accepts `P0 P1 P2` (any case). The priority and one Changelog
  line, after `created`, are resolved in this order (`--from-plan`: unchanged, no line):

  | Source | attended | `CPLAT_HEADLESS=1` |
  |---|---|---|
  | `--priority P` | `priority P given by you` | `priority P proposed: P: named in the request` |
  | tracked issues' labels, one level | `priority P set on the issue #<n>` | `priority P proposed: P: set on the issue #<n>` |
  | tracked issues' labels, several levels | most urgent, `priority P set on the issue #<n> (p0, p2: decide)` | `priority P proposed: P: set on the issue #<n>` |
  | none of the above | `priority P1 proposed: P1: normal bug or feature` | same |

  Labels are read with `gh issue view <n> --json labels` per tracked issue; a failed read counts as no label and prints
  `note: could not read the labels of #<n>; the priority is a proposal` on stderr. Standard output is unchanged.
  The skeleton gains, directly above `## Changelog`, one comment rendered from `priority.LEVELS`:
  `<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: P0 <definition>; P1 <definition>; P2 <definition>. A reason is "P<n>: <phrase>", one of: <phrases per level>. -->`
- **`spec priority <id> <P> [--propose REASON] [--json]`** (new):
  - with `--propose` (the product-manager's proposal): REASON must satisfy `proposal_reason_ok(P, REASON)` (else exit 1,
    `ERROR: the reason must be "<P>: <phrase>" …`). Applied only when the spec is `draft`, its state is `proposed` and the
    current proposal's reason is a definition phrase (the fallback or an earlier `--propose`): `priority` = P and that
    Changelog line is replaced by `priority P proposed: REASON`; output `<id>: priority P proposed (REASON)`. Otherwise
    nothing is written and the output is `<id>: priority kept <P'> (<reason'>); a proposal replaces only a proposal`,
    exit 0. Allowed under `CPLAT_HEADLESS=1`.
  - without `--propose` (the user's change): `priority` = P and a Changelog line `priority P changed by you`; output
    `<id>: priority P (changed by you)`. Same level and state not `proposed` → `<id>: priority already P`, nothing written.
    Refused (exit 1, nothing written) under `CPLAT_HEADLESS=1` (`ERROR: a priority change needs the user` / `fix: run it
    in a Claude Code session`) and for `done`/`superseded` specs.
  - `--json`: `{"id", "priority", "priority_state", "priority_reason", "written": bool}`.
- **State** (`spec_priority.state(spec) -> {"state", "reason", "decide"}`): from the last Changelog line matching
  `priority (P[0-2]) (proposed: (.+)|given by you|changed by you|set on the issue #\d+.*)`:
  `proposed` (→ `approved` when a later line is `approved` or `approved by <x>` with `<x>` ≠ `cplat dispatch`), `given`,
  `changed`, `issue` (`decide` true when the line ends in `: decide)`); no such line → `unset`. The reason is the text after
  `proposed: `, or `given by you`, `changed by you`, `set on the issue #<n>…`.
- **`spec show`** prints, after the counts line and when the state is not `unset`, `Priority: <P> (<reason>)`
  (e.g. `Priority: P1 (P1: normal bug or feature)`, `Priority: P0 (changed by you)`). **`spec show --json`**,
  **`spec list --json`** (with or without `--detail`) add `"priority_state"` and `"priority_reason"` to each spec
  (`"unset"`, `""` for old specs; broken specs the same).

### Console spec panel

`panel_spec` renders `<p data-priority="<state>">Priority: <P> (<reason>)</p>` below the title, adding ` - proposed, not yet
approved` when the state is `proposed`; nothing for `unset` (AC-196.12).

### Prompts

- `/issue:triage`: the reason is `P<n>: <phrase>` from the batch's `priority_levels`; a priority change (the change choice
  or typed `560 p0`) runs `confirm --set 560=P0`; a priority answer on a question page is stored the same way.
- `/component:spec`, `/system:spec` (B, new spec): a request naming `P0`, `P1` or `P2` literally adds `--priority` (A11);
  after the product-manager, `cplat spec priority <spec_id> <P> --propose "<reason>"` with its `PRIORITY:` line; F prints
  the `Priority:` line of `cplat spec show` with the `Environment limit:` line; a typed `priority P<n>` at the change choice
  runs `cplat spec priority <spec_id> P<n>`, commits, publishes and shows F again. `--amend` and `--from-plan` call no
  `spec priority` (AC-196.11).
- product-manager reply block, mode `new`: `PRIORITY: P<n> (P<n>: <phrase>)`, the level whose definition in the skeleton's
  priority comment the request matches.
- Each changed prompt keeps its byte size or shrinks (docs/rules/README.md, rule 6), with register entries for new rule
  sentences.

### Dispatcher

`dispatch_policy` default `priority`: `["label:p0", "label:bug", "label:p1", "spec-order", "oldest"]`; `docs/dispatch.md`
and `docs/specs/167-a-dispatcher-runs-the-backlog-in/design.md` show the new default.

## Data

No new store. Spec front matter keeps `priority`; the provenance is a Changelog line. The triage proposals file gains the
optional row key `priority_decided`.
