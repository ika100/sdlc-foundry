# ADR-131: An amended spec judges only the tests of its changed criteria

**Status:** Accepted (2026-11-27, spec 205 AC-205.8)

## Context

[ADR-121](121-red-tests-fail-for-the-missing-behaviour-before-they-freeze.md) freezes the acceptance tests only when the
red check classes every one of them `missing behaviour`. When a spec is amended after it was built (#1094), the tests of
its built criteria already pass, so the red check sent them back to the tester as `passes` and the build could not
freeze the tests of the amendment without a person.

## Decision

The red check of an amended spec judges only the tests of criteria new or changed since its last done commit; every other test must pass or the build escalates as a regression

- A spec is amended after a build when its Changelog has a `done` bullet followed by an `amended` bullet. For such a
  spec `cplat component build tests <id> --red` prints `cplat quiet test-fast --red --spec <id> -- <files>`; a spec
  built for the first time keeps the line of ADR-121.
- The last `done` commit is the newest commit whose `spec.md` ends its Changelog with the current last `done` bullet.
  A criterion is judged when it is new since that commit or its text changed (whitespace collapsed); assumptions and
  other sections do not count.
- A test traces to criteria by its own source lines and name first, then by its class, then by its file, so that a new
  test in an old file is judged and the old tests beside it are not.
- A judged test is classed as in ADR-121. An unjudged test that passes prints `passes (not judged: <ids> unchanged)`;
  one that fails in any way prints `regression` and makes the check exit 1.

## Consequences

- A regression escalates with cause `code` before any coder runs, with no tester round, because criteria that were
  already built broke and no spec answer fixes that. The freeze gate needs exit 0, so the tests never freeze over it.
- A spec whose amendment was built without a later `done` line judges that amendment's criteria again on the next
  amendment.
- A clone without the done commit (shallow, rewritten history) gets exit 2 with the hint to fetch the full history,
  because judging every test would repeat #1094 and judging none would freeze unchecked tests.
