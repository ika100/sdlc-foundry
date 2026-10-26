---
title: "The problem"
description: "Why running a system on Kubernetes costs a small team so much glue work, and why AI agents alone make it worse."
---

<p class="lead">Writing the system is the smaller half of shipping it. The other half is the glue, and the glue is where small teams lose months.</p>

## The glue

For every service you ship, someone has to produce and keep consistent:

- a CI pipeline that builds, tests, scans and publishes an image for the right architectures;
- a Dockerfile that runs as a non-root user with a read-only filesystem;
- Kubernetes manifests: Deployment, Service, routes, probes, resources, per environment;
- secrets that never touch git, and credentials for the cluster to pull images;
- a database, telemetry, policies, and a safe way to move a version from dev to production.

Each piece is well understood. The cost is that they are *many*, they must agree with each other, and they are re-created for every repository with slightly different mistakes.

## What goes wrong in practice

These are not hypotheticals. They are some of the twelve defects the platform's own end-to-end test found when it generated a real three-repository application (a Java API, a Next.js UI and a GitOps repository) and deployed it to a local cluster:

| What happened | Why it hurts |
|---|---|
| Every template stamped `team: "@owner"` into a Kubernetes label, which is not a valid value | No generated service could ever be applied (since v1.0) |
| Images ran as a *named* non-root user | Kubernetes cannot verify a name, so pods sat in `CreateContainerConfigError` |
| The Java image's agent jar was unreadable for the non-root runtime user | The image never started |
| Images were published for one CPU architecture only | Apple-silicon nodes failed with "no match for platform in manifest" |
| The generated CI workflow did not run on pushes to `main` | Merged code was never built, so there was no image to deploy |
| Promotion pinned references and tags that do not exist (`?ref=sha-...`, `vX.Y.Z`) | Promoting a version could not work |
| A skeleton update silently reverted edits to the deployment manifest | Teams stopped updating |
| CI needed a token to read other private repositories just to build manifests | Credential sprawl |

None of these is hard to fix once seen. The point is that they were invisible until the whole chain ran, and that each would recur in every project that rebuilds the glue by hand.

## Why AI agents alone make it worse

A coding agent will happily write a Dockerfile, a Deployment and a workflow. Without constraints it writes a *different* one each time, forgets the security context on Tuesday and pins nothing on Wednesday. Prompts are expensive to run, hard to test and easy to drift. The failure mode is not that agents are bad at YAML; it is that nothing makes their output consistent, checked and reviewable.

## What a solution has to do

1. **Make the right thing the default** (secure, pinned, reproducible) so nobody has to remember it.
2. **Derive instead of duplicate:** one declaration per fact, everything else generated.
3. **Be testable:** deterministic work in scripts with tests, an end-to-end test of the whole chain, and a guard for every defect found.
4. **Keep humans in charge of outward actions:** previews, pull requests, explicit approval.
5. **Stay open:** plain Kubernetes, standard telemetry, vendor-neutral contracts, so you can leave.

That is what sdlc-foundry is. See the [vision](/sdlc-foundry/vision/) and the [client value](/sdlc-foundry/value/).
