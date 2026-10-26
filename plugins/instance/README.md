# instance plugin

The `instance` noun of the domain model: a component running in one environment.

| Command | Does |
|---|---|
| `/instance:promote` | `cplat instance promote`: pin a verified image in the next environment, one PR; production needs an explicit yes |
| `/instance:secret` | `cplat instance secret set\|list`: values of remote secrets in the local cluster |
| `/instance:verify` | `cplat instance verify [<env>]`: run the component's smoke tests against an environment |

Needs the `shared` plugin (it puts `cplat` on the Bash PATH).
