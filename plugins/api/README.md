# api plugin

The `api` noun of the domain model: the APIs a system declares under `apis:` in `system.yaml`.

| Command | Does |
|---|---|
| `/api:list` | `cplat api list`: one line per API with its type, provider and consumers; a bound events API ends with `  broker <b>` |

Needs the `shared` plugin (it puts `cplat` on the Bash PATH). Contract checks between provider and consumers are not built yet.
