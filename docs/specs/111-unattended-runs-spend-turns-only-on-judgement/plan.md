---
spec_id: 111-unattended-runs-spend-turns-only-on-judgement
spec_hash: eee98a6e1783
summary: Headless sessions load only the repo's MCP (strict config, connectors off, optional extra file); a rule-checked
  inline path for trivial quick-tasks; cplat ship continue runs land then deploy without coordinator turns; each part
  benchmarked against the 4.7.0 baseline and kept only if cheaper with the same outcome
tasks:
  - id: t1
    title: Headless sessions — --strict-mcp-config, repo .mcp.json, headless.mcp_config, disableClaudeAiConnectors
    files: [scripts/cplat/headless.py, scripts/cplat/settings.py]
    covers: [AC-111.4, AC-111.5, AC-111.6]
    parallel_safe: false
    depends_on: []
    done: false
  - id: t2
    title: cplat quick-task inline-check and the inline path in quick-task.md
    files: [scripts/cplat/quicktask.py, scripts/cplat/cplat.py, plugins/svc/commands/quick-task.md]
    covers: [AC-111.7, AC-111.8, AC-111.9]
    parallel_safe: false
    depends_on: []
    done: false
  - id: t3
    title: cplat ship continue (land then deploy, exit 0/1/2) and ship.md uses it
    files: [scripts/cplat/ship.py, plugins/svc/commands/ship.md, plugins/svc/references/ship-land-red.md]
    covers: [AC-111.1, AC-111.2, AC-111.3]
    parallel_safe: false
    depends_on: []
    done: false
  - id: b1
    title: Benchmarks per part against the 4.7.0 baseline; keep or revert; benchmarks.md, BASELINES.md, CHANGELOG
    files: [docs/specs/111-unattended-runs-spend-turns-only-on-judgement/benchmarks.md, docs/BASELINES.md, docs/CHANGELOG.md]
    covers: [AC-111.10]
    parallel_safe: false
    depends_on: [t1, t2, t3]
    done: false
---

# Plan — 111 Unattended runs spend turns only on judgement

Design: [design.md](design.md). Red tests first (`tests/cplat/test_spec_111.py`), one coder for t1–t3, reviewer,
then the benchmarks (b1) before the PR is merged.
