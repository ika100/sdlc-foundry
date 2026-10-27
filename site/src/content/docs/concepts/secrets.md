---
title: "Secrets"
description: "Secrets are created or read in the cluster by External Secrets Operator; values never enter git."
sidebar:
  order: 6
---

Git holds **references**, never values. A component declares `secrets:` in `system.yaml`; `render.py` emits an `ExternalSecret` for each and exposes the resulting Secret to the pod through `envFrom`.

| Mode | Declare | What happens |
|---|---|---|
| `generate` | `generate: [DB_PASSWORD, JWT_KEY]` | External Secrets Operator creates random values in the cluster, once per environment, and keeps them (no implicit rotation). For secrets the system owns |
| `remote` | `remote: {keys: [STRIPE_KEY]}` | The value is read from your secret store (Vault, AWS Secrets Manager, GCP; locally the `secrets-store` namespace, set with `/instance:secret set`). For credentials someone else issues |

A secret-looking key with a value in `env:` is rejected at render time. Deleting an `ExternalSecret` regenerates (rotates) its generated values. Design and trade-offs: [ADR-018](/sdlc-foundry/reference/adr/018/).
