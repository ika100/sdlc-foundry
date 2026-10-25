# Self-hosted CI runners

Every template's workflows run on GitHub-hosted runners unless the repository says otherwise. A repository moves its
CI to self-hosted runners with two [repository variables](https://docs.github.com/en/actions/learn-github-actions/variables)
and no change to the workflow files, so `/shared:update-service` keeps working:

| Variable | Effect | Example |
|---|---|---|
| `CI_RUNNER` | `runs-on` of every job | `lan-myrepo` |
| `CI_DOCKER_MATRIX` | replaces the `docker` job's architecture matrix (JSON); needed when the self-hosted runners cannot build every architecture natively | `[{"arch":"amd64","runner":"lan-myrepo"}]` |

```bash
gh variable set CI_RUNNER --body lan-myrepo
gh variable set CI_DOCKER_MATRIX --body '[{"arch":"amd64","runner":"lan-myrepo"}]'   # service shapes with a docker job
```

Unset both to go back to GitHub-hosted runners.

## Why

Self-hosted runners cost no Actions minutes and keep working when GitHub-hosted runners are blocked, for example by
an account's billing lock (tested 2026-10-21: hosted jobs fail with "recent account payments have failed", self-hosted
jobs run). They also run next to the cluster they deploy to.

## What the runner image needs

The workflows assume what a GitHub-hosted Ubuntu runner has, except where noted:

- **devbox and Nix.** The `devbox-install-action` step runs only on GitHub-hosted runners
  (`runner.environment == 'github-hosted'`); a self-hosted image must ship devbox and a Nix the runner user can use.
  Runner containers have no systemd, so install single-user Nix owned by the runner user, without the build sandbox
  and seccomp filter (unprivileged containers cannot use them; jobs fetch prebuilt packages from the binary cache).
- `xz` (Nix's installer) and `gh` (the gitops-app's `pin-dev` workflow). The official runner image
  `ghcr.io/actions/actions-runner` has neither.
- **Docker** for the `docker` job of service shapes and for workflow `services:`: a Docker daemon next to the runner
  (Docker in Docker on Kubernetes).

- **Network access to the query API** for the gitops-app's alert poll (`alerts.yml`, spec 092, [ADR-038](adr/038-alert-poll-on-the-gitops-runner.md)):
  the runner must reach Prometheus (`lgtm.observability.svc:9090` in-cluster) and `gh`. The poll never runs on
  GitHub-hosted runners. For an app.yaml `querySecret`, the runner's ServiceAccount needs `get` on that Secret.

A reference image (official runner + xz, gh, single-user Nix, devbox) is
[`runner-image/Dockerfile` in stock-manager-gitops](https://github.com/ika100/stock-manager-gitops/blob/main/runner-image/Dockerfile).

## Runners on Kubernetes (ARC)

[Actions Runner Controller](https://github.com/actions/actions-runner-controller) (charts `gha-runner-scale-set-controller`
and `gha-runner-scale-set`) runs ephemeral runner pods that scale to zero. Things learned on the first setup
(stock-manager-gitops `environments/lan/arc-*.yaml`):

- **Personal accounts only have repository-level runners.** Each repository needs its own scale set; only an
  organization can share one. The scale set's resource is named after `runnerScaleSetName`, so names must be unique
  per namespace (`lan-<repo>`); that name is the `CI_RUNNER` value.
- **Credential:** a fine-grained token with repository permission *Administration: read and write* on those
  repositories (or a GitHub App with the same permission), from the secret store, never from Git.
- **Speed.** An ephemeral pod starts empty, so cache what jobs download on persistent volumes:
  - `/nix` for devbox packages (seed it from the image in an init container and re-seed when the image changes):
    a devbox job drops from ~7 min to ~45 s.
  - Docker's `/var/lib/docker` (spell the dind sidecar out: the chart's `containerMode: dind` cannot mount a volume;
    guard it with a lock so only one daemon uses it) and the package manager's cache: the image build drops from
    ~10 min to ~30 s with buildx `driver: docker`.
  - The template's `docker` job uses the GitHub Actions cache (`type=gha`) only on GitHub-hosted runners. On a
    self-hosted runner the export of every layer (`mode=max`) goes over the site's uplink: 4–6 min per build on the
    lan runners, and one export hung. Without a persistent Docker volume the build simply starts cold (~4 min for a
    Go service).
  - **Recommended for every runner set that builds images:** one persistent dind `/var/lib/docker` volume per
    runner set, under the lock above (one daemon per volume). It is the build cache. A registry cache
    (`cache-to: type=registry,mode=max`) is not a substitute: it uploads every layer to GHCR on each main build,
    the uplink cost #95 removed (spec 074).
  - `/tmp` as a memory `emptyDir` when tests write SQLite or other fsync-heavy files and the node's disk syncs slowly
    (~7 ms per synced write on a ZFS-backed VM disk made pytest 3× slower).
- **Isolation.** Cache volumes are shared between jobs, so a job can leave something behind for the next one. Keep
  pull requests from untrusted authors off runners with shared caches.
- **Keep the runner version current.** GitHub stops accepting runner versions some time after a newer release; rebuild
  the image when `ghcr.io/actions/actions-runner` moves on.
