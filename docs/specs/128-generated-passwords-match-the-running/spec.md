---
spec_id: 128-generated-passwords-match-the-running
title: Generated passwords match the running server
status: building
priority: P1
shape: platform
tracks: [316]
---

# 128 — Generated passwords match the running server

## Problem

An in-cluster cache can run with a different password than its Secret `<system>-<name>-app` holds (#316). In three upgrade e2e runs the Secret and its `url` held one password and the running Valkey server another; the Secret was created and the pod started in the same second, with no restart, one External Secrets controller (2.12.0), and applying the `Password` generator first did not help. The likely cause is that External Secrets writes the Secret a second time with a newly generated password even though the ExternalSecret says `refreshPolicy: CreatedOnce`. Whoever reads the Secret first keeps the first value. Every component that uses the cache then gets `WRONGPASS` until someone restarts the server, so a freshly created environment can be broken without any error in Argo CD. ADR-064 promises that the password is generated once and never changes, and spec 118 (AC-118.19) relies on that promise, so this is a defect in a released contract. The broker (spec 119: the `_nack` user and one generated user per component, which the NATS server reads at start) and the bucket (spec 117 / ADR-059: generated S3 keys) use the same pattern of "generator plus ExternalSecret, read by a long-running process" and may fail the same way. The upgrade e2e hides the defect today with the workaround `settle_cache`, which waits for the Secret to stop changing and then restarts the server. The fix belongs in what the platform renders, so that no system, and no test, needs a workaround.

## Stories

- As a component developer, I want my component to connect to the cache and the broker with the variables it gets, every time an environment is created, so that I never see `WRONGPASS` or an authorization error that only a restart fixes.
- As a system owner, I want `/platform:update` to apply the fix without changing the passwords my running components use, so that the update causes no outage.
- As the platform maintainer, I want the e2e tests to pass without restarting servers by hand, so that they test what users get and catch this defect if it comes back.

## Acceptance criteria

"Ready" below means the server's pod reports ready. "Settled" means 60 seconds after ready. The checks compare the value a server accepts with the value in the Secret. They never print either value.

### Cache

- **AC-128.1** Given a cache instance that is created in an environment (a new system, a new environment or a cache added to an existing system), when its server is settled, then the server accepts the password in `<system>-<name>-app` (key `password`, and the password inside `url`) and refuses any other. This stays true for as long as the instance lives, and no person, script or test has to restart the server for it.
- **AC-128.2** Given a component that uses the cache and has a running instance in the same environment, whether it started before, with or after the cache, when the cache is settled, then every new connection the component opens with its own `REDIS_URL`, and also with `REDIS_HOST`, `REDIS_PORT` and `REDIS_PASSWORD`, gets `PONG` to `PING`. From that point on no component instance gets `WRONGPASS`.
- **AC-128.3** Given a cache whose Secret already exists, when whatever writes that Secret runs again (the External Secrets controller restarts, Argo CD re-syncs or re-applies the cache's objects, or a forced refresh is requested), then the password in the Secret and the password the server accepts both stay the same.

### Broker

- **AC-128.4** Given a broker instance that is created in an environment, when its NATS server is settled, then the user `_nack` authenticates with the password in `<system>-<name>-nack` and the broker's NACK Account becomes ready. Each component user authenticates with the password in its `<system>-<name>-<component>-app`, and no server restart is needed for either.
- **AC-128.5** Given a broker that is already running, when a component that uses it is added (a new user and a new Secret), then within 60 seconds after the broker's server is ready again, the new component connects with its `NATS_URL`, `NATS_USER` and `NATS_PASSWORD`, and so do the components that were already there. None of them gets an authorization error.
- **AC-128.6** Given a broker whose Secrets already exist, when whatever writes them runs again (the same triggers as AC-128.3), then no password in them changes and every user still authenticates.

### Bucket and component-generated secrets

- **AC-128.7** Given an in-cluster bucket instance, when its credentials Secret `<system>-<name>-app` has existed for 60 seconds, then the bucket's S3 endpoint accepts `accessKeyId` and `secretAccessKey` from it, and a component that uses the bucket can put an object and read it back. The Secret is written exactly once, like the Secrets of the cache and the broker. Its keys stay the same when whatever writes it runs again (the triggers of AC-128.3, including a forced refresh).
- **AC-128.8** Given a component with a `secrets:` entry using `generate:` and two or more running replicas, when the generated Secret has existed for 60 seconds, then every replica, including those started before that point, sees the same value for each generated key, and that value equals the one in the Secret. The value stays the same when whatever writes it runs again.

### Existing systems

- **AC-128.9** Given a system rendered by 5.4.x with running caches, brokers, buckets and generated component secrets whose passwords match their servers, when `/platform:update` re-renders it and Argo CD syncs, then every existing Secret keeps its values and no server or component sees an authentication failure during or after the sync. No step by hand is needed. The change list names, per resource type, what changed in the rendered objects, and says that existing passwords and keys are kept.
- **AC-128.10** Given an existing cache or broker that is already in the #316 state (its server accepts a different password than its Secret holds), when the updated platform is synced, then within 60 seconds the server accepts the Secret's password and the components connect. No component configuration changes.

### Tests, records and release notes

- **AC-128.11** Given `tests/e2e/upgrade.sh`, then the function `settle_cache` and its call are removed, and no e2e script restarts a cache or broker server to make passwords match, or waits for a Secret to stop changing (a workaround like `settle_cache`). Restarts that other specs test on purpose (AC-118.7, AC-116.8, and spec 120's chart change) stay, and they run after the AC-128 checks. The upgrade e2e and the e2e cluster test check AC-128.1, AC-128.2 and AC-128.4 in every environment they create. They also check AC-128.3 by forcing one more write of a cache's Secret after it was created. Both pass on CI in 3 runs in a row.
- **AC-128.12** Given the cplat test suite, then for the cache, the broker, the bucket and generated component secrets there is a test that checks the rendered objects: each generated credential is written exactly once, by a path that cannot write it twice (create if absent, otherwise keep what exists), and no generator-backed templated ExternalSecret writes it. The test fails on the 5.4 form, where a server reads at start a password from a Secret that a generator-backed ExternalSecret may write again.
- **AC-128.13** Given the platform's decision records, then one ADR records the cause found for #316 (with the External Secrets version that was examined and any upstream issue or fixed version) and the chosen mechanism: a credential is written exactly once, by a path that cannot write it twice. The ADR records this as an exception to ADR-018 ("every Secret comes from External Secrets"), with the rights the creator needs in the namespace. It amends ADR-064 (point 3), ADR-065 and ADR-059 where they say a password is "written once".
- **AC-128.14** Given `docs/CHANGELOG.md`, then the `[Unreleased]` section has a `Fixed` entry that names #316, the symptom (`WRONGPASS` or an authorization error until the server restarts), the affected resource types and releases, the fix, and what an existing system must do (nothing, per AC-128.9 and AC-128.10).

## Non-goals

- Password rotation: changing a password on purpose, by a person or on a schedule (ADR-064 and spec 118 exclude it).
- Databases: CloudNativePG generates and owns their credentials; External Secrets is not involved.
- External caches, brokers and buckets, and component secrets read from the secret store (`remote:`): their values come from the store, and following the store's changes is existing behaviour.
- Changing Secret names, keys, variable names or the `url` form (specs 118, 119 and 127).
- Upgrading, pinning or replacing External Secrets Operator. The fix does not depend on its behaviour for generated credentials.
- Having servers or components follow a Secret that changes at runtime (beyond the one-time repair of AC-128.10).

## Open questions

1. ~~What mechanism stops the server and the Secret from drifting apart?~~ Answered (user, 2026-10-30): B. Each credential is written exactly once, by a path that cannot write it twice (create if absent), not by a generator-backed templated ExternalSecret. This is recorded as an exception to ADR-018. See AC-128.12, AC-128.13 and Non-goals.
2. ~~Confirm: the fix covers generated component secrets (`secrets: generate:`).~~ Answered (user, 2026-10-30): yes. See AC-128.8.
3. ~~Confirm: the bucket is in scope even if its operator already follows Secret changes.~~ Answered (user, 2026-10-30): yes. First answered as "a check only"; during planning the user moved the bucket to the same write-once mechanism as the cache and the broker. See AC-128.7 and AC-128.12.
4. ~~Should the update repair an instance already in the #316 state on its own?~~ Answered (user, 2026-10-30): yes, automatically, within 60 s and without a manual step. See AC-128.10.
5. ~~Confirm: 60 seconds after ready, and 3 green CI runs in a row.~~ Answered (user, 2026-10-30): yes. See AC-128.1, AC-128.2, AC-128.4, AC-128.5, AC-128.7, AC-128.8, AC-128.10 and AC-128.11.

## Changelog

- 2026-10-30 created
- 2026-10-30 open questions answered: the mechanism is a credential written exactly once by a create-if-absent path (exception to ADR-018, AC-128.12 and AC-128.13 clarified); component secrets and the bucket check stay in scope (AC-128.7 clarified); repair is automatic; thresholds confirmed
- 2026-10-30 amended: the bucket's credentials Secret is written exactly once, like the cache's and the broker's (AC-128.7 and AC-128.12; the branch "render unchanged if the operator follows" is removed). AC-128.11 clarified: only restarts done to make passwords match are removed, and the deliberate restarts of AC-118.7, AC-116.8 and spec 120 stay and run after the AC-128 checks
- 2026-10-30 approved
- 2026-10-30 draft: amend: bucket moves to write-once (AC-128.7); AC-128.11 bans only workaround restarts
- 2026-10-30 approved
- 2026-10-30 building
