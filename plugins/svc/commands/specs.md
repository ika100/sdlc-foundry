---
description: "Moved in 5.0: /svc:specs is /component:spec. Runs nothing."
moved-to: "/component:spec"
allowed-tools: Read, Glob
---

`/svc:specs` was renamed in sdlc-foundry 5.0. Run no script, start no agent, change no file.

1. With Read and Glob only, check whether this repo is migrated: it is not when `.platform-version` is missing or its `platform:` is below 5.0.0, or when `applications/*/app.yaml` or `applications/*/services.yaml` exists.
2. Answer with exactly one line and nothing else:
   - migrated: `/svc:specs` is `/component:spec` in 5.0.
   - not migrated: `/svc:specs` is `/component:spec` in 5.0; run `cplat platform update --migrate` first.
