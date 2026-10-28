# gitops plugin (tombstones)

Since 5.0 this plugin contains only tombstone command files: `/gitops:promote`, `/gitops:compose`, `/gitops:addon` and `/gitops:secret` print where the command went and do nothing else. It has no agents and no hooks any more. The plugin leaves the marketplace in 6.0.

| 4.x command | 5.0 command |
|---|---|
| `/gitops:promote` | `/instance:promote` |
| `/gitops:compose` | `/component:add`, `/component:remove` |
| `/gitops:addon` | `/resource:add`, `/resource:remove` |
| `/gitops:secret` | `/instance:secret` |

The gitops-app repo is now a **system** repo described by `system.yaml`; its plugin is `system`. Remove `gitops@sdlc-foundry` from `.claude/settings.json` and enable `system@sdlc-foundry` (`cplat platform update --migrate` does it for a repo, see [docs/ADOPTING.md](../../docs/ADOPTING.md)).
