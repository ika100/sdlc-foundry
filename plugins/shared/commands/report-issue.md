---
description: "Moved in 5.0: /shared:report-issue is /issue:report. Runs nothing."
moved-to: "/issue:report"
allowed-tools: Read, Glob
---

`/shared:report-issue` was renamed in sdlc-foundry 5.0. Run no script, start no agent, change no file.

1. With Read and Glob only, check whether this repo is migrated: it is not when `.platform-version` is missing or its `platform:` is below 5.0.0, or when `applications/*/app.yaml` or `applications/*/services.yaml` exists.
2. Answer with exactly one line and nothing else:
   - migrated: `/shared:report-issue` is `/issue:report` in 5.0.
   - not migrated: `/shared:report-issue` is `/issue:report` in 5.0; run `cplat platform update --migrate` first.
