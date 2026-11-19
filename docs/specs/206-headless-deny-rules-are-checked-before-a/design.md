# Design — 206 Headless deny rules are checked before a session starts

## Decisions

- The refused rules, the two samples, a matcher with Claude Code's deny semantics and the check go into one new module,
  `scripts/cplat/denyrules.py`. `preflight.py` keeps its name for `refused_rules` by importing it from there, so every
  caller and test that uses `preflight.refused_rules` stays as it is.
- `preflight.matches` stays as it is. It is the allow and settings matcher of spec 131. An allow rule must not match past
  `; rm -rf x` or a leading `NAME=value` (`test_184_envprefix.py`), so the deny semantics of AC-206.3 (split compound
  commands, strip assignments and wrappers) live in a separate function, `denyrules.refuses`. The spec's note says what the
  matcher lacks. The design adds those features in the new deny matcher and leaves the allow matcher alone, because Claude
  Code matches allow rules and deny rules differently.
- `Bash(gh api *merge*)` is replaced, at the same position in the list, by three narrower rules (AC-206.6). Each one matches
  only commands the old rule matched, so no new action is refused:
  `Bash(gh api */pulls/*/merge*)` (REST merge of a pull request, method and flags in any order),
  `Bash(gh api */merges*)` (REST merge of a branch, which the old rule also refused) and
  `Bash(gh api *mutation*merge*)` (every GraphQL merge mutation: `mergePullRequest`, `mergeBranch`; a GraphQL query cannot
  change anything without the `mutation` keyword). A read of `.mergeable` or `mergeStateStatus` matches none of them.
- The check is the first check of `preflight.check`, category `deny-rules` (A3). It makes no network call, so it fails
  before the slower gh checks. It checks the exact list `headless` passes as `--disallowedTools`.
- The corrected rule (AC-206.4) comes from a fixed search over narrowing edits of the offending rule (see Contract). Each
  edit only narrows the rule, so a correction never refuses more than the rule it replaces.
- No ADR. This extends ADR-076 (checked run allowlist) with a startup check. The decision about which actions are refused
  is unchanged.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/denyrules.py` | `refused_rules`, `must_allow`, `must_refuse`, `refuses`, `problem`, `correction` | new |
| `scripts/cplat/preflight.py` | re-exports `refused_rules`; `check(..., deny=None)` runs `deny-rules` first | changed |
| `scripts/cplat/headless.py` | passes its `deny` list to `preflight.check`; docstring names the check | changed |
| `tests/cplat/test_184_allowlist.py` | `REFUSED_BEFORE` gets the three `gh api` rules (spec 206 changes the list on purpose) | changed |

## Contract

### `denyrules.refused_rules(default_branch: str) -> list[str]`

This is the list `preflight.refused_rules` returned before, in the same order. The one difference is that
`"Bash(gh api *merge*)"` is replaced, at its position, by
`"Bash(gh api */pulls/*/merge*)", "Bash(gh api */merges*)", "Bash(gh api *mutation*merge*)"`.
`preflight.refused_rules is denyrules.refused_rules`.

### `denyrules.must_allow(default: str, branch: str) -> list[str]` / `must_refuse(default: str, branch: str) -> list[str]`

Each returns its sample with `D` = `default` and `B` = `branch`, in exactly the order and text of AC-206.1 or AC-206.2.
The sample's literals stay as they are: `feature/x-fix`, `feature/D-page`, `acme/x`, `acme/shop-api`, `7`, `v1.2.0`,
`tests/test_x.py`.

### `denyrules.refuses(rule: str, command: str) -> bool` (AC-206.3)

- `Bash` and `Bash(*)` match everything. A rule that is not `Bash(...)` matches nothing.
- Pattern `P` = the text inside `Bash(...)`. `glob(P, text)`:
  - if `P` ends with `:*`: `text == P[:-2]` or `text` starts with `P[:-2] + " "`;
  - otherwise `*` matches any text, spaces and newlines included, and the whole of `text` must match;
  - in addition, if `P` ends with ` *`, then `text == P[:-2]` also matches.
- The candidates are the whole command plus each part of it, split on `&&`, `||`, `;`, `|` and newline outside single and
  double quotes, each part trimmed.
- Each candidate is also tried after stripping its leading words, repeated until nothing changes:
  - `NAME=value` assignments, where the value may be quoted;
  - one of the wrappers `timeout`, `time`, `nice`, `nohup`, `stdbuf`, together with its options (words starting with
    `-`; `timeout -s/-k`, `nice -n` and `stdbuf -i/-o/-e` written with a separate value also drop that value) and, for
    `timeout`, the duration word (`\d+(\.\d+)?[smhd]?`).

  The stripped text is the rest of the original string from that offset, with quoting kept as typed.
- `refuses` is true when `glob` matches any candidate, stripped or not.

### `denyrules.problem(rules: list[str], default: str, branches: list[str]) -> str | None` (AC-206.4, AC-206.5, AC-206.7)

It returns the detail that follows `deny-rules: `, or None when the rules pass. The first failure wins, in this order:

1. `default` contains `*`, `(`, `)`, `,` or whitespace → `default branch "<default>" cannot be guarded by a rule`.
2. For each branch in order, each `must_allow` command in order, and each rule in list order, the first rule that refuses
   the command → `<rule> refuses "<command>", which the run needs; use: <correction>`. `<rule>` is written in full, as
   `Bash(...)`. `<correction>` is `correction(...)`, or the text `remove the rule` when that is None.
3. For each branch in order and each `must_refuse` command in order, the first command no rule refuses →
   `no rule refuses "<command>"; add: <rule>`. `<rule>` is the first rule of `refused_rules(default)` that refuses the
   command, or `Bash(<command>)` when none does.

`branches` uses `feature/x` for the system ship's `feature/*`.

### `denyrules.correction(rule: str, rules: list[str], default: str, branches: list[str]) -> str | None`

The search tries candidate edits of `P` in a fixed order. For each `*` at index `i`, left to right:

1. (a) insert `" "` after it, when the next character exists and is not a space;
2. (b) insert `"/"` after it, when the next character exists and is not a space or `/`;
3. (c) drop it, when it is the last character;
4. (d) replace it with `" *"`, when it is the last character and the character before it is not a space.

A candidate passes when the list with `rule` replaced in place by `Bash(<candidate>)` gives `problem(...) is None` for
the same `default` and `branches`. The search returns the first passing candidate as `Bash(<candidate>)`, or None.

### Preflight

`preflight.check(repo, command, specs, targets=None, deny=None)`. When `deny` is None it uses
`refused_rules(default_branch(repo))`. It runs `problem(deny, default_branch(repo), branches)` before every other check,
where `branches` is `branches_of(command, specs)` with `feature/*` mapped to `feature/x`. A problem gives
`Failure("deny-rules", <detail>)`:

- the printed line is `preflight failed: deny-rules: <detail>`;
- the reason is `preflight failed: deny-rules`;
- `headless` exits 1, starts no session and makes no model call (the existing preflight path).

`headless._main` calls `preflight.check(repo, command, ids, targets, deny=deny)`. `check_repo` (a system ship's later
repos) is unchanged.

Examples, with default branch `main`:

```
# today's generated list plus the old Bash(gh api *merge*): the three new gh api rules still refuse every merge
preflight failed: deny-rules: Bash(gh api *merge*) refuses "gh api repos/acme/x/pulls/7 --jq .mergeable", which the run needs; use: Bash(gh api * merge*)
# the old list of spec 131 (no other gh api rule): no single narrower rule keeps the GraphQL and the REST merge refused
preflight failed: deny-rules: Bash(gh api *merge*) refuses "gh api repos/acme/x/pulls/7 --jq .mergeable", which the run needs; use: remove the rule
preflight failed: deny-rules: no rule refuses "git push origin main"; add: Bash(git push * main)
preflight failed: deny-rules: default branch "release (old)" cannot be guarded by a rule
```
