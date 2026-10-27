---
spec_id: 119-a-message-broker-resource-behind-events
title: A message broker resource behind events APIs
status: building
priority: P1
---

# 119 — A message broker resource behind events APIs

## Problem

Since 5.0 (spec 114) a system can declare an API of `type: events`, with one component that provides it and others that consume it. Nothing carries those events, though. Teams who want asynchronous work (order placed → send mail, file uploaded → make thumbnail) have to run a broker themselves and wire its address, credentials, streams and consumer names into every component by hand, in every environment. Spec 115 makes resources named, typed and optionally external. This spec adds the type that backs events APIs: a broker resource running NATS with JetStream (one small server that also runs on a laptop). The platform creates one stream per events API and one durable consumer per consuming component, and hands each component the connection and the names through environment variables. Spec 120 (scaling) needs those stream and consumer names to scale consumers on their backlog.

This is an additive 5.x extension of spec 114, which stays as approved and is not amended. It extends two of 114's closed lists: it adds the resource type `broker` to the resource types of AC-114.19 (opened up by spec 115), and it adds the key `broker` to an API entry of AC-114.16, for `type: events` only.

## Stories

- As a product owner, I want to declare a broker in `system.yaml` and say which events APIs it carries, so that events flow between my components in every environment without hand-written broker setup.
- As a developer of a component that provides an events API, I want the broker address, my credentials and my API's subject prefix in my environment, so that I can publish without knowing how the broker runs.
- As a developer of a consuming component, I want a durable consumer that is mine, so that I get every event once, including those published while my component was down.
- As an operator, I want a broker that cannot be removed while an events API still depends on it, and whose streams survive configuration changes, so that no event data is lost by a render.
- As the author of spec 120 (scaling), I want the stream and consumer names and the broker's monitoring endpoint in the model, so that consumers can be scaled on their pending messages.
- As a team that already runs NATS elsewhere (for example Synadia Cloud), I want to point the broker at it as an external resource (spec 115), so that my components see the same environment contract.

## Acceptance criteria

### Declaring a broker

- **AC-119.1** Given `resources:` with an entry of `type: broker` (keys `version`, `replicas`, `storage`, `resources`, and `instances.<env>` overriding `replicas`, `storage` and `resources`, as spec 115 defines for every resource type), when it is rendered, then each environment where a running component uses the broker (AC-119.7) gets one NATS server with JetStream enabled, with the given replica count and storage per replica; any other key fails naming the key and the allowed keys.
- **AC-119.2** Given a broker's `replicas`, when it is rendered, then `1` and `3` are accepted (default `1`), and any other value fails saying a broker runs with 1 or 3 replicas; with `3`, each stream is kept on 3 replicas, so that stopping one broker pod loses no acknowledged message and publishing keeps working.
- **AC-119.3** Given a broker without `version`, `storage` or `resources`, when it is rendered, then it uses the platform's pinned NATS server version, 1Gi of storage per replica and the platform's default requests and limits; a `version` the platform does not support fails listing the supported versions.
- **AC-119.4** Given `/resource:add <name> --type broker [--version V] [--replicas N]` in a gitops-app repo, when it runs, then it adds the broker to `resources:` and renders in one PR as spec 115 defines for `/resource:add`; `/resource:remove <name>` on a broker that an events API is bound to (AC-119.5) changes nothing and fails naming the bound APIs.

### Binding events APIs to a broker

- **AC-119.5** Given an API of `type: events` with `broker: <name>`, when it is rendered, then `<name>` must be a resource of `type: broker` in the same system; a name that is not a resource, or a resource of another type, fails naming the API and the system's brokers.
- **AC-119.6** Given an events API without `broker:`, when it is rendered, then it is bound to the system's only broker; with no broker the API stays unbound and the render prints a note naming the API and `/resource:add <name> --type broker` (not a failure: a 5.0 `system.yaml` with an events API and no broker must render byte-identically, AC-119.24), and with two or more brokers it fails naming the API and listing the brokers to choose from with `broker:`.
- **AC-119.7** Given a component that provides or consumes an events API, when it is rendered, then it uses that API's broker without listing it in `uses`; listing a broker in `uses` is accepted and changes nothing for such a component, and a component that lists a broker in `uses` but neither provides nor consumes an events API bound to it fails naming the component and saying a component reaches a broker through an events API.
- **AC-119.8** Given `broker:` on an API whose type is not `events`, when it is rendered, then the render fails naming the API and saying only events APIs are carried by a broker.

### Streams, consumers and the environment contract

- **AC-119.9** Given an events API `<api>` in system `<system>` bound to a broker, when the broker instance of an environment is running, then it has one stream named `<system>-<api>` that captures exactly the subjects `<system>.<api>.>`, keeping messages for 7 days.
- **AC-119.10** Given a component with an instance in an environment that consumes an events API, when the broker instance of that environment is running, then the API's stream has one durable consumer named after the component, with explicit acknowledgement; a message not acknowledged within 30 seconds is delivered again. A consuming component without an instance in that environment has no consumer there.
- **AC-119.11** Given a component `<component>` that uses broker `<name>` in system `<system>`, when its instance starts, then it has the environment variables `NATS_URL` (the broker instance's address) and `NATS_USER` and `NATS_PASSWORD` (read from the Secret `<system>-<name>-<component>-app`, generated per environment, never in git), and for every events API it provides or consumes `EVENTS_<API>_STREAM` and `EVENTS_<API>_SUBJECT_PREFIX` (`<system>.<api>`), plus `EVENTS_<API>_CONSUMER` for an API it consumes, where `<API>` is the API name in upper case with `-` replaced by `_`. The Secret name never changes.
- **AC-119.12** Given the credentials of AC-119.11, when a component connects, then each component has its own user per environment: the provider of an API may publish on `<system>.<api>.>`, a consumer may read only through its own durable consumer and is refused when it publishes on a subject of an API it only consumes, and a component that is not part of an API is refused when it subscribes to that API's subjects.
- **AC-119.13** Given a system whose events API has a provider and a consumer with instances in the same environment, when the provider publishes one message on `<system>.<api>.created`, then the consumer receives it through its durable consumer within 30 seconds; a message published while the consumer was stopped is delivered after it starts again, and an acknowledged message is not delivered again after a restart.
- **AC-119.14** Given a removed consumer (the component no longer consumes the API or loses its instance) or a removed events API, when it is rendered, then the durable consumer, the stream and their messages stay on the broker until a human deletes them, as for the database of ADR-020; the render prints which consumers and streams are no longer declared.

### Model, external brokers and checks

- **AC-119.15** Given a system with a broker, when `cplat model show --json` runs, then each broker resource instance lists its environment, its address inside the cluster, its monitoring endpoint, and for each bound events API the stream name, the subject prefix and the durable consumer names with their components; `/api:list` shows the broker of each events API.
- **AC-119.16** Given a running broker instance, when its monitoring endpoint is queried, then it reports for each stream the stored message count and for each durable consumer the number of pending (not yet delivered) and unacknowledged messages, so that spec 120 can scale a consumer on that number.
- **AC-119.17** Given a broker marked external per spec 115 (for example a NATS service such as Synadia Cloud), when it is rendered, then no NATS server is rendered for it, the components get the same variables as in AC-119.11 with `NATS_URL`, `NATS_USER` and `NATS_PASSWORD` read from the secret store per spec 115, and the stream and consumer names of AC-119.9 and AC-119.10 are listed in the model and printed by the render as names the external broker's owner must create; the platform creates no streams or consumers on it.
- ~~**AC-119.18**~~ withdrawn 2026-10-26: the platform now installs what the broker needs on every cluster; replaced by AC-119.22 and AC-119.23.
- **AC-119.19** Given the end-to-end cluster test, when it runs, then it declares a broker and one events API with a provider and a consumer component in dev, and checks AC-119.13 on a laptop-sized local cluster with a broker of 1 replica.

### Running the broker, upgrades and docs

- **AC-119.20** Given a rendered broker, when its manifests are inspected, then the NATS server image and the version of every chart or controller the broker needs are pinned exactly by the platform release (a full version, no floating or `latest` tag); a change of `version`, or of those pins with a platform update, follows spec 121 (upgrades roll through the environments in order and downgrades are refused) and this spec defines no upgrade procedure of its own.
- **AC-119.21** Given a broker that is not external, when it is rendered, then the NATS server comes from the official NATS chart and every stream and durable consumer of AC-119.9 and AC-119.10 is a declared object in the environment's rendered tree, which Argo CD shows as synced once the broker has created it.
- **AC-119.22** Given a cluster where at least one environment has an in-cluster (not external) broker, when the system is rendered, then the platform installs the NATS JetStream controller (NACK) on that cluster as one Argo CD application per cluster, at the version pinned in spec 121's versions table; a cluster with only external brokers, or none, gets no such application.
- **AC-119.23** Given an environment with `operators: owner`, when the system is rendered, then the platform installs nothing of AC-119.22 for that environment's cluster, and `/platform:doctor` compares the installed NATS chart and controller versions with the expected ones of spec 121's versions table and warns naming each missing or differing one and its expected version.
- **AC-119.24** Given a 5.0 `system.yaml` without a broker and without `broker:` on any API, when it is rendered with this spec built, then the rendered tree is byte-identical to the 5.0 render.
- **AC-119.25** Given the platform docs, when this spec is built, then they describe the broker's environment contract (AC-119.11) with one short Python example that publishes on and consumes from an events API; no template ships publisher or subscriber code.

## Non-goals

- Kafka, RabbitMQ or any broker other than NATS, in the cluster or external; an external broker is NATS only.
- Publisher or subscriber code in the templates; the docs example of AC-119.25 is all.
- Event schemas and checking them between provider and consumers: a pointer to spec 110 (contract check), not part of this spec.
- Request/reply, plain (non-JetStream) subjects, key-value and object stores of NATS; publishing outside the subjects of a declared events API.
- More than one provider per events API (spec 114 keeps exactly one), and per-API retention, limits or delivery settings beyond the defaults of AC-119.9 and AC-119.10.
- Backups: spec 117 includes the broker volumes (JetStream data) in the Velero environment backup; this spec adds nothing to it.
- Scaling consumers on their backlog: spec 120; this spec only exposes the names and the monitoring endpoint.
- The upgrade procedure for the broker and what it needs to run: spec 121.
- Amending spec 114: it stays as approved; this spec only extends its lists as stated in Problem.
- Sharing one broker between systems; NATS accounts, leaf nodes and clusters across regions.
- Off-the-shelf components (running third-party applications as components).

## Open questions

- ~~How does the broker run in the cluster?~~ Answered: the official NATS chart plus the NACK controller, installed per cluster as a pinned Argo CD application unless the environment sets `operators: owner`. See AC-119.21, AC-119.22 and AC-119.23.
- ~~How do components authenticate?~~ Answered: one generated user and password per component and environment, rights per API, in the Secret `<system>-<name>-<component>-app`. See AC-119.11 and AC-119.12.
- ~~Do components use the broker implicitly, or must they list it in `uses`?~~ Answered: implicitly; `uses` is optional and only for a component on an events API of that broker. See AC-119.7.
- ~~Confirm: stream and consumer naming, 7 days retention, 30 seconds acknowledgement wait.~~ Answered: yes. See AC-119.9, AC-119.10 and AC-119.11.
- ~~Confirm: broker replicas only 1 or 3, default 1; default storage 1Gi per replica.~~ Answered: yes. See AC-119.2 and AC-119.3.
- ~~Confirm: removing a consumer or an events API never deletes the stream or its messages.~~ Answered: yes. See AC-119.14.
- ~~On an external broker, who creates the streams and consumers?~~ Answered: the external broker's owner; the platform lists the names. See AC-119.17.
- ~~Is an external Kafka (or RabbitMQ) broker in scope?~~ Answered: no. See Non-goals.
- ~~Do the templates ship publisher or subscriber code?~~ Answered: no; the docs carry one short Python example. See AC-119.25 and Non-goals.

## Changelog

- 2026-10-26 created
- 2026-10-26 open questions answered: per-component Secret named `<system>-<name>-<component>-app` (AC-119.11 clarified); AC-119.18 withdrawn for the platform-installed controller and the `operators: owner` opt-out (AC-119.22, AC-119.23); added AC-119.21 (chart and declared streams), AC-119.24 (additive to 5.0), AC-119.25 (docs example); AC-119.20 to AC-119.25 under "Running the broker, upgrades and docs" so ids read in order; backups by spec 117 noted.
- 2026-10-26 approved
- 2026-10-28 AC-119.6 clarified at plan time: with no broker an events API stays unbound and the render prints a note instead of failing, because failing contradicted AC-119.24 (5.0 systems may declare events APIs and must render byte-identically) and would have made the release breaking
- 2026-10-28 building
