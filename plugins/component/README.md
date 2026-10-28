# component

The commands that work on one component (a service, a website or a library) and on the `components:` of a system. Version 1.0.0 (platform 5.0).

| Command | What it does |
|---|---|
| `/component:new <name> <description> [--type T] [--lang L] [--system OWNER/REPO]` | Create a component repo from its template (default `service`/`python`) |
| `/component:add`, `set`, `remove` | Edit `components:` of `system.yaml` in a gitops-app repo; one PR; `--provides NAME[:TYPE]` and `--consumes NAME` declare the APIs of one component (`openapi`, `grpc`, `graphql`, `events`); `/component:spec` publishes the spec as a draft PR for review (`set <component> --instance <env> --replicas <n>` changes one instance; `--replicas` is refused on a component or instance with a `scale`, which is edited in `system.yaml`) |
| `/component:spec [<description> \| --amend <id> <change> \| approve <id> \| --from-plan <plan> \| --all \| index \| migrate]` | Write, amend, approve or list feature specs |
| `/component:plan <spec-id>` | Architect writes `design.md` and `plan.md` |
| `/component:build <spec-id>` | Failing acceptance tests, coders, quality/tests/security, verification, PR |
| `/component:verify [<spec-id>]` | Check the code against a spec; writes `verification.md` |
| `/component:ship <spec-id> [--no-merge]` | Plan, build, PR, merge after green CI, wait for dev, unattended |
| `/component:fix <description>` | Bug or small change: coder, quality, tester, PR |
| `/component:check` | Read-only quality and security audit |
| `/component:release` | Gates, version bump, changelog, release PR, tag |

`references/` holds the long procedures the build, ship and fix commands read on demand (`${CLAUDE_PLUGIN_ROOT}/references/…`). The agents stay in `svc`, `svc-java`, `svc-go`, `web` and `shared`; the `cplat` launcher comes from `shared`, so keep it enabled.
