# 112 — Measurements

Baseline: merge base `e3c3d54` (2026-10-26). Machine: 12-core Mac, the same for before and after. Command for the
local runs: `uv run --with pytest --with pytest-xdist --with pyyaml --with ruamel.yaml pytest tests/cplat -q -n auto`.

## AC-112.1 — same test ids

`pytest tests/cplat --collect-only -q`, sorted, before and after: 2470 → 2511 ids. The diff is exactly the 41 new
tests of `tests/cplat/test_fast_suite_112.py`; no id was removed or renamed. No test got a skip, xfail or
deselection (the shard plugin deselects only under `--shard`, and `check-shards.py` proves the union).

## AC-112.3 — order and isolation

| Run | Result |
|---|---|
| full suite, reverse order (`--with pytest-reverse … --reverse`) | 2504 passed, 7 skipped |
| each of the 101 `tests/cplat/test_*.py` files on its own | all pass |

## AC-112.7 — fixture setup time

Sum of the `setup` lines of `--durations=0 --durations-min=0.05`:

| | setup | call | wall |
|---|---|---|---|
| before (`e3c3d54`) | 479.2 s | 879.7 s | 149 s |
| after | 211.4 s (44%) | 946.3 s | 90–103 s |

Target at most 50% (239.6 s): met. Call time rose slightly with the 41 new tests (they run real pytest
subprocesses) and with load from other sessions on the same machine during the after-run.

## AC-112.12 — shard balance (PR ci run)

| Shard | pytest step |
|---|---|
| 1/4 | _filled from the PR run_ |
| 2/4 | |
| 3/4 | |
| 4/4 | |

Average, slowest/average (≤ 1.5) and slowest (≤ 75 s) are computed with
`gh run view <run-id> --json jobs | jq '.jobs[] | select(.name|test("shard")) | {name, steps: [.steps[] | select(.name=="pytest") | ((.completedAt|fromdate)-(.startedAt|fromdate))]}'`.

## AC-112.9 — ci wall time

Wall time of one ci run = first job `startedAt` to `ci-success` `completedAt`:

```bash
gh run view <run-id> --json jobs | jq '[.jobs[] | select(.startedAt != null and .conclusion != "skipped")] as $j
  | ((($j | map(select(.name == "ci-success")) | .[0].completedAt | fromdate))
  - ($j | map(.startedAt | fromdate) | min))'
```

Before: 185–246 s on pull requests (the 12 runs before 2026-10-26).

| Pull request | ci run | wall time |
|---|---|---|
| this PR (first sample) | _filled from the PR run_ | |
| 1 | | |
| 2 | | |
| 3 | | |
| 4 | | |
| 5 | | |

AC-112.9 holds when the median of rows 1–5 (code PRs that touch no smoke-tested template) is at most 120 s. Those
rows are filled after the merge (plan `human_steps`).
