# resource plugin

The `resource` noun of the domain model: things a system provides to its components. 5.0 supports one, the `postgres` database, declared under `resources:` in `system.yaml`.

| Command | Does |
|---|---|
| `/resource:add` | `cplat resource add postgres [--version N]`: declare the database, one PR |
| `/resource:remove` | `cplat resource remove postgres`: refused while a component uses it |

Observability is not a resource: it is set per environment under `environments.<env>.observability` in `system.yaml`.

Needs the `shared` plugin (it puts `cplat` on the Bash PATH).
