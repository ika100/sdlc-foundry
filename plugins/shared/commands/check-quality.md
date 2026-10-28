---
description: "Moved in 5.0: /shared:check-quality is /component:check. Runs nothing."
moved-to: "/component:check"
allowed-tools: Read, Glob
---

`/shared:check-quality` was renamed in sdlc-foundry 5.0. Run no script, start no agent, change no file.

1. With Read and Glob only, check whether this repo is migrated: it is not when `.platform-version` is missing or its `platform:` is below 5.0.0, or when `applications/*/app.yaml` or `applications/*/services.yaml` exists.
2. Answer with exactly one line and nothing else:
   - migrated: `/shared:check-quality` is `/component:check` in 5.0.
   - not migrated: `/shared:check-quality` is `/component:check` in 5.0; run `cplat platform update --migrate` first.
