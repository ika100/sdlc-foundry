# resource plugin

The `resource` noun of the domain model: things a system provides to its components. A resource has a name and a type and is declared under `resources:` in `system.yaml`. The type `database` is built (CloudNativePG, majors 15–18, or `external`); `bucket`, `cache` and `broker` are reserved for specs 116, 118 and 119.

| Command | Does |
|---|---|
| `/resource:add` | `cplat resource add <name> --type database [--version N] [--external [--path P]]`: declare a resource, one PR |
| `/resource:remove` | `cplat resource remove <name>`: refused while a component uses it |

Observability is not a resource: it is set per environment under `environments.<env>.observability` in `system.yaml`.

Needs the `shared` plugin (it puts `cplat` on the Bash PATH).
