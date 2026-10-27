# cluster plugin

A **cluster repo** (shape `cluster-gitops`) owns what a cluster shares between systems: the operators it installs (Kyverno, External Secrets, ...), the secret store, and the list of systems that run on it (`cluster.yaml`). Argo CD syncs the rendered manifests; each listed system's own gitops repo then delivers that system. See [docs/CLUSTERS.md](../../docs/CLUSTERS.md).

## Commands

| Command | Purpose |
|---|---|
| `/cluster:new <name> [--org <owner>] [--public]` | Create the cluster repo from the `cluster-gitops` template, with no systems yet |
| `/cluster:add <owner>/<repo> [--name <system>]` | Register a system's gitops repo in `cluster.yaml`, render, and open one PR |
| `/cluster:remove <system>` | Remove the entry and its rendered application in one PR; nothing is deleted in the cluster |

All three run `cplat cluster <verb>`, preview with `--dry-run` first, and change nothing when they fail.
