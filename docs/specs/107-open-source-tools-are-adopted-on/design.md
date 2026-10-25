# Design — 107 Open-source tools are adopted on measured value

## Decisions

- **The evaluation is benchmark runs plus decision records; the code is only what makes an arm measurable.** Nothing
  in templates, plugins or `cplat` defaults changes (AC-107.9, AC-107.11). The one code change is a benchmark
  *arm*: a named, local modification of the sample repo applied before a benchmark run and removed by the reset that
  already follows every run.
- **Arms** live in `scripts/cplat/benchmark/arms/<name>.json`:
  `{"name", "candidate", "workflows": [...], "files": {<path>: <content>}, "commands": [[...]], "note"}`.
  `cplat runs benchmark <wf> --arm <name>` applies the arm after `_prepare` checks out the pinned revision. It writes
  the files and runs the commands in the clone (for example adding `pytest-testmon` to the test recipe), commits
  `bench: arm <name>` and pushes it to the sample repo's `main`. The session then starts from a main that contains the
  arm. `reset_sample` already force-resets `main` to the pinned revision after the run, so the arm leaves nothing
  behind. The record's `benchmark` section gets `arm` (`baseline` without `--arm`), and `cplat runs report
  --benchmarks` adds the arm to the row key (`<version> [<plugins>] (<model>) {<arm>}`). An unknown arm, an arm that
  does not list the workflow, or a failing arm command exits non-zero before any session and writes no record.
- **Arms for the candidates** (AC-107.1, AC-107.3, in the agreed order):
  1. `testmon`: the sample's `test-fast` recipe runs `pytest --testmon` (workflows `build`); measure: validation time
     (sum of `cplat quiet test-fast` durations from the transcript tool results) and affected-test recall against the
     full suite, computed by `cplat runs benchmark … --arm testmon --recall`. That flag runs the full suite after the
     session and fails the arm's record when a failing test was deselected.
  2. `pytest-impact`: the same with pytest-impact's selection. It is a separate record from testmon, from the same
     trial.
  3. `semgrep` and `trivy`: the sample's `security` recipe also runs `semgrep scan --config p/python --error` /
     `trivy fs --scanners vuln,secret,misconfig --exit-code 0 --format json`. Measure: findings the existing gates
     (pip-audit, detect-secrets, bandit) do not report, with false positives counted by hand in the record, plus run
     time and tokens. Existing gates stay unchanged (AC-107.4).
  4. `codebase-memory`: the sample gets the MCP server in `.mcp.json` and its tool in the allowlist (only if the tool
     installs non-interactively; otherwise the record is `defer` with that reason, no trial). The native alternative
     is compared on paper (AC-107.3).
  5. Tracing: no arm. The record lists the visibility questions the run store and the OTel export of spec 101 cannot
     answer, each with a concrete run. With none, the decision is `reject: no demonstrated gap` (AC-107.5).
- **Runs** (AC-107.1, AC-107.2): the baseline is 5 `build` runs and 5 `quick-task` runs on the current release with
  the current sample revision. Each arm gets 5 runs of each workflow it lists. A difference counts as a benefit only
  when it lies outside the baseline's min–max spread. `cplat runs report --benchmarks --json` gives the figures, and
  the records cite run ids (AC-107.10).
- **Decision records are ADRs** (AC-107.6, AC-107.8): `docs/adr/0NN-evaluate-<tool>.md`, one per tool, listed in
  `docs/adr/README.md`. Each record has: hypothesis (written before the trial), decisive measure, figures with run ids,
  licence, last release date, added setup, and a decision of `adopt`, `pilot further`, `defer` or `reject`, with the
  rules of AC-107.7. `docs/evaluations.md` is the index the AC asks for: candidate, decision, date, platform version,
  the baseline, links to the ADRs. A decision `adopt` names the proposed follow-up spec; it is not written here.
- **Budget:** a trial is ~10 builds (~$12, ~2 h) per arm at today's prices. Arms run in the order above, and the
  evaluation stops cleanly at a session limit with the progress recorded in `docs/evaluations.md`.

## Contract

```
cplat runs benchmark <wf> [--arm NAME] [--recall]      arm applied before the session, reset after; record benchmark.arm
scripts/cplat/benchmark/arms/<name>.json               {name, candidate, workflows, files, commands, note}
docs/evaluations.md                                    index: baseline + one row per candidate
docs/adr/0NN-evaluate-<tool>.md                        one decision record per tool
```
