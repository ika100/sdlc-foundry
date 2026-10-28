# resource plugin

The `resource` noun of the domain model: things a system provides to its components. A resource has a name and a type and is declared under `resources:` in `system.yaml`. The types `database` (CloudNativePG, majors 15–18, or `external`) and `bucket` (S3 object storage, SeaweedFS per instance, or `external`), and `cache` (Redis-compatible, runs Valkey 8 or 9, or `external`) and `broker` (NATS with JetStream, bound to events APIs through `apis.<api>.broker`, or `external`) are built.

| Command | Does |
|---|---|
| `/resource:add` | `cplat resource add <name> --type database|bucket|cache|broker [--version V] [--replicas N] [--storage S] [--versioning] [--external [--path P]]`: declare a resource, one PR |
| `/resource:remove` | `cplat resource remove <name>`: refused while a component uses it |
| `/resource:backup` | `cplat resource backup <db> --env <env>`: one on-demand database backup now |
| `/resource:upgrade` | `cplat resource upgrade <name> --to <major> [--env <env>] --pr --wait`: move one environment of a database or cache to a new major, one PR per environment, then verify (a database needs a backup from the last 60 minutes) |
| `/resource:restore` | `cplat resource restore <db> --env <env> (--to <time\|latest> \| --switch \| --discard) [--confirm prod]`: restore by generation |

Observability is not a resource: it is set per environment under `environments.<env>.observability` in `system.yaml`.

Needs the `shared` plugin (it puts `cplat` on the Bash PATH).
