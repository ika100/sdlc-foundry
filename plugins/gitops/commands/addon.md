---
description: "Moved in 5.0: /gitops:addon is /resource:add|remove (addon list: resources: in system.yaml; addon add observability: environments.<env>.observability in system.yaml). Runs nothing."
moved-to: "/resource:add|remove (addon list: resources: in system.yaml; addon add observability: environments.<env>.observability in system.yaml)"
allowed-tools: Read, Glob
---

`/gitops:addon` was renamed in sdlc-foundry 5.0. Run no script, start no agent, change no file.

1. With Read and Glob only, check whether this repo is migrated: it is not when `.platform-version` is missing or its `platform:` is below 5.0.0, or when `applications/*/app.yaml` or `applications/*/services.yaml` exists.
2. Answer with exactly one line and nothing else:
   - migrated: `/gitops:addon` is `/resource:add|remove (addon list: resources: in system.yaml; addon add observability: environments.<env>.observability in system.yaml)` in 5.0.
   - not migrated: `/gitops:addon` is `/resource:add|remove (addon list: resources: in system.yaml; addon add observability: environments.<env>.observability in system.yaml)` in 5.0; run `cplat platform update --migrate` first.
