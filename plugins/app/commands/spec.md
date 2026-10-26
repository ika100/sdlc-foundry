---
description: "Moved in 5.0: /app:spec is /system:spec. Runs nothing."
moved-to: "/system:spec"
allowed-tools: Read, Glob
---

`/app:spec` was renamed in sdlc-foundry 5.0. Run no script, start no agent, change no file.

1. With Read and Glob only, check whether this repo is migrated: it is not when `.platform-version` is missing or its `platform:` is below 5.0.0, or when `applications/*/app.yaml` or `applications/*/services.yaml` exists.
2. Answer with exactly one line and nothing else:
   - migrated: `/app:spec` is `/system:spec` in 5.0.
   - not migrated: `/app:spec` is `/system:spec` in 5.0; run `cplat platform update --migrate` first.
