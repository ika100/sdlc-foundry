# resource plugin

The `resource` noun of the domain model: things a system provides to its components. A resource has a name and a type and is declared under `resources:` in `system.yaml`. The types `database` (CloudNativePG, majors 15–18, or `external`) and `bucket` (S3 object storage, SeaweedFS per instance, or `external`) are built; `cache` and `broker` are reserved for specs 118 and 119.

| Command | Does |
|---|---|
| `/resource:add` | `cplat resource add <name> --type database|bucket [--version N] [--storage S] [--versioning] [--external [--path P]]`: declare a resource, one PR |
| `/resource:remove` | `cplat resource remove <name>`: refused while a component uses it |

Observability is not a resource: it is set per environment under `environments.<env>.observability` in `system.yaml`.

Needs the `shared` plugin (it puts `cplat` on the Bash PATH).
