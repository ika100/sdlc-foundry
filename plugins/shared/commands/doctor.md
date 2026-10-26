---
description: "Moved in 5.0: /shared:doctor is /platform:doctor. Runs nothing."
moved-to: "/platform:doctor"
allowed-tools: Read, Glob
---

`/shared:doctor` was renamed in sdlc-foundry 5.0. Run no script, start no agent, change no file.

1. With Read and Glob only, check whether this repo is migrated: it is not when `.platform-version` is missing or its `platform:` is below 5.0.0, or when `applications/*/app.yaml` or `applications/*/services.yaml` exists.
2. Answer with exactly one line and nothing else:
   - migrated: `/shared:doctor` is `/platform:doctor` in 5.0.
   - not migrated: `/shared:doctor` is `/platform:doctor` in 5.0; run `cplat platform update --migrate` first.
