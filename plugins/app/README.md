# app plugin (tombstones)

Since 5.0 this plugin contains only tombstone command files: `/app:spec`, `/app:plan`, `/app:build`, `/app:ship` and `/app:specs` print where the command went and do nothing else. The planner agent and the work moved to the `system` plugin. The plugin leaves the marketplace in 6.0.

| 4.x command | 5.0 command |
|---|---|
| `/app:spec` | `/system:spec` |
| `/app:plan` | `/system:plan` |
| `/app:build` | `/system:ship` (attended builds: `/component:build` per component) |
| `/app:ship` | `/system:ship` |
| `/app:specs` | `/system:spec` |

Remove `app@sdlc-foundry` from `.claude/settings.json` and enable `system@sdlc-foundry` (`cplat platform update --migrate` does it for a repo, see [docs/ADOPTING.md](../../docs/ADOPTING.md)).
