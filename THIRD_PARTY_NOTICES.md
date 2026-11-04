# Third-party notices

sdlc-foundry is licensed under the [Apache License 2.0](LICENSE). The following third-party material is included in this repository (or copied into repositories generated from its templates) under its own terms. Full license texts are in [`LICENSES/`](LICENSES).

| Material | Where | License | Source |
|---|---|---|---|
| Apache License 2.0 text | `LICENSE` | Apache-2.0 | <https://www.apache.org/licenses/LICENSE-2.0> |
| Contributor Covenant 2.1 | `CODE_OF_CONDUCT.md` | CC-BY-4.0 (attribution kept in the file) | <https://www.contributor-covenant.org> |
| Icon paths adapted from Lucide (heart-pulse, activity, flask-conical, box, rocket, sparkles) | `templates/web-nextjs/app/_components/icons.tsx`, therefore also in every generated web app | ISC, Copyright (c) 2026 Lucide Icons and Contributors (the notice is kept in the file's header) | <https://lucide.dev> |
| Inter and JetBrains Mono typefaces | served by the documentation site (`site/`, installed from npm as `@fontsource-variable/*`, not stored in this repository) | OFL-1.1, Copyright the Inter and the JetBrains Mono project authors | <https://rsms.me/inter>, <https://www.jetbrains.com/lp/mono/> |

## Software that is installed, not bundled

Templates and scripts reference open-source software that is **downloaded when you use it**, not distributed in this repository: for example Next.js, Spring Boot, chi, FastAPI, Playwright, Vitest, Copier, devbox, ArgoCD, Traefik, External Secrets Operator, CloudNativePG, the OpenTelemetry Collector, Grafana's `otel-lgtm` image, Kyverno, Trivy, Docker base images. Each is governed by its own license, and repositories generated from the templates produce an SBOM (CycloneDX, in CI) that lists what they ship. Check those licenses before you distribute an image built from a generated repository.

## Trademarks

Claude and Claude Code are trademarks of Anthropic, PBC. Kubernetes, Docker, GitHub, Next.js, Spring, Argo, Grafana, Prometheus, OpenTelemetry, Kyverno and other product names are trademarks of their respective owners and are used only to describe compatibility. sdlc-foundry is an independent project and is **not affiliated with, sponsored by or endorsed by** Anthropic or any of these owners.
