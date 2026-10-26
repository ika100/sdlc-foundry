---
spec_id: 119-a-message-broker-resource-behind-events
title: A message broker resource behind events APIs
status: draft
priority: P1
---

# 119 — A message broker resource behind events APIs

## Problem

Since 5.0 (spec 114) a system can declare an API of `type: events`, with one component that provides it and others that consume it. Nothing carries those events, though. Teams who want asynchronous work (order placed → send mail, file uploaded → make thumbnail) have to run a broker themselves and wire its address, credentials, streams and consumer names into every component by hand, in every environment. Spec 115 makes resources named, typed and optionally external. This spec adds the type that backs events APIs: a broker resource running NATS with JetStream (one small server that also runs on a laptop). The platform creates one stream per events API and one durable consumer per consuming component, and hands each component the connection and the names through environment variables. Spec 120 (scaling) needs those stream and consumer names to scale consumers on their backlog.

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
- **AC-119.20** Given a rendered broker, when its manifests are inspected, then the NATS server image and the version of every chart or controller the broker needs are pinned exactly by the platform release (a full version, no floating or `latest` tag); a change of `version`, or of those pins with a platform update, follows spec 121 (upgrades roll through the environments in order and downgrades are refused) and this spec defines no upgrade procedure of its own.
- **AC-119.4** Given `/resource:add <name> --type broker [--version V] [--replicas N]` in a gitops-app repo, when it runs, then it adds the broker to `resources:` and renders in one PR as spec 115 defines for `/resource:add`; `/resource:remove <name>` on a broker that an events API is bound to (AC-119.5) changes nothing and fails naming the bound APIs.

### Binding events APIs to a broker

- **AC-119.5** Given an API of `type: events` with `broker: <name>`, when it is rendered, then `<name>` must be a resource of `type: broker` in the same system; a name that is not a resource, or a resource of another type, fails naming the API and the system's brokers.
- **AC-119.6** Given an events API without `broker:`, when it is rendered, then it is bound to the system's only broker; with no broker the render fails naming the API and `/resource:add <name> --type broker`, and with two or more brokers it fails naming the API and listing the brokers to choose from with `broker:`.
- **AC-119.7** Given a component that provides or consumes an events API, when it is rendered, then it uses that API's broker without listing it in `uses`; listing a broker in `uses` is accepted and changes nothing for such a component, and a component that lists a broker in `uses` but neither provides nor consumes an events API bound to it fails naming the component and saying a component reaches a broker through an events API.
- **AC-119.8** Given `broker:` on an API whose type is not `events`, when it is rendered, then the render fails naming the API and saying only events APIs are carried by a broker.

### Streams, consumers and the environment contract

- **AC-119.9** Given an events API `<api>` in system `<system>` bound to a broker, when the broker instance of an environment is running, then it has one stream named `<system>-<api>` that captures exactly the subjects `<system>.<api>.>`, keeping messages for 7 days.
- **AC-119.10** Given a component with an instance in an environment that consumes an events API, when the broker instance of that environment is running, then the API's stream has one durable consumer named after the component, with explicit acknowledgement; a message not acknowledged within 30 seconds is delivered again. A consuming component without an instance in that environment has no consumer there.
- **AC-119.11** Given a component that uses a broker, when its instance starts, then it has the environment variables `NATS_URL` (the broker instance's address) and `NATS_USER` and `NATS_PASSWORD` (read from a Secret, never in git), and for every events API it provides or consumes `EVENTS_<API>_STREAM` and `EVENTS_<API>_SUBJECT_PREFIX` (`<system>.<api>`), plus `EVENTS_<API>_CONSUMER` for an API it consumes, where `<API>` is the API name in upper case with `-` replaced by `_`.
- **AC-119.12** Given the credentials of AC-119.11, when a component connects, then each component has its own user per environment: the provider of an API may publish on `<system>.<api>.>`, a consumer may read only through its own durable consumer and is refused when it publishes on a subject of an API it only consumes, and a component that is not part of an API is refused when it subscribes to that API's subjects.
- **AC-119.13** Given a system whose events API has a provider and a consumer with instances in the same environment, when the provider publishes one message on `<system>.<api>.created`, then the consumer receives it through its durable consumer within 30 seconds; a message published while the consumer was stopped is delivered after it starts again, and an acknowledged message is not delivered again after a restart.
- **AC-119.14** Given a removed consumer (the component no longer consumes the API or loses its instance) or a removed events API, when it is rendered, then the durable consumer, the stream and their messages stay on the broker until a human deletes them, as for the database of ADR-020; the render prints which consumers and streams are no longer declared.

### Model, external brokers and checks

- **AC-119.15** Given a system with a broker, when `cplat model show --json` runs, then each broker resource instance lists its environment, its address inside the cluster, its monitoring endpoint, and for each bound events API the stream name, the subject prefix and the durable consumer names with their components; `/api:list` shows the broker of each events API.
- **AC-119.16** Given a running broker instance, when its monitoring endpoint is queried, then it reports for each stream the stored message count and for each durable consumer the number of pending (not yet delivered) and unacknowledged messages, so that spec 120 can scale a consumer on that number.
- **AC-119.17** Given a broker marked external per spec 115 (for example a NATS service such as Synadia Cloud), when it is rendered, then no NATS server is rendered for it, the components get the same variables as in AC-119.11 with `NATS_URL`, `NATS_USER` and `NATS_PASSWORD` read from the secret store per spec 115, and the stream and consumer names of AC-119.9 and AC-119.10 are listed in the model and printed by the render as names the external broker must provide; the platform creates no streams or consumers on it.
- **AC-119.18** Given a system with a broker that is not external, when `/platform:doctor` runs against a cluster that lacks what the broker needs to run, then it warns naming what is missing and how to install it; `cluster-up` installs it on a local cluster when the system declares a broker.
- **AC-119.19** Given the end-to-end cluster test, when it runs, then it declares a broker and one events API with a provider and a consumer component in dev, and checks AC-119.13 on a laptop-sized local cluster with a broker of 1 replica.

## Non-goals

- Kafka, RabbitMQ or any broker other than NATS, in the cluster or external; an external broker is NATS only.
- Event schemas and checking them between provider and consumers: a pointer to spec 110 (contract check), not part of this spec.
- Request/reply, plain (non-JetStream) subjects, key-value and object stores of NATS; publishing outside the subjects of a declared events API.
- More than one provider per events API (spec 114 keeps exactly one), and per-API retention, limits or delivery settings beyond the defaults of AC-119.9 and AC-119.10.
- Backups of broker data: spec 117 decides whether broker volumes are backed up.
- Scaling consumers on their backlog: spec 120; this spec only exposes the names and the monitoring endpoint.
- The upgrade procedure for the broker and what it needs to run: spec 121.
- Sharing one broker between systems; NATS accounts, leaf nodes and clusters across regions.
- Off-the-shelf components (running third-party applications as components).

## Open questions

- How does the broker run in the cluster? (suggested: the official NATS Helm chart for the server, plus the NATS JetStream controller (NACK) so streams and consumers are declared objects in git that Argo shows and syncs; alternatives: Helm chart only, with streams and consumers created by a platform job at deploy; or a platform-rendered StatefulSet with the same job; affects AC-119.1, AC-119.9, AC-119.10, AC-119.14, AC-119.18)
- How do components authenticate? (suggested: one generated user and password per component and environment, with publish and subscribe rights limited per API as in AC-119.12; alternatives: one shared token per broker instance with no per-API rights, which drops AC-119.12; or NATS decentralized JWT/NKey accounts with a creds file; affects AC-119.11, AC-119.12, AC-119.17)
- Do components use the broker implicitly through their events APIs, or must they list it in `uses`? (suggested: implicit, `uses` optional and only accepted for a component on an events API of that broker; alternatives: required in `uses`, render fails without it; or `uses` alone grants a free subject prefix `<system>.<component>.>`; affects AC-119.7)
- Confirm: stream name `<system>-<api>`, subjects `<system>.<api>.>`, durable consumer named after the consuming component, 7 days retention, 30 seconds acknowledgement wait. (suggested: yes; alternatives: retention by size (80% of storage) instead of age; a per-API `retention` key; affects AC-119.9, AC-119.10, AC-119.11)
- Confirm: broker replicas only 1 or 3, default 1; default storage 1Gi per replica. (suggested: yes; alternatives: allow 5; default 5Gi; affects AC-119.2, AC-119.3)
- Confirm: removing a consumer or an events API never deletes the stream or its messages. (suggested: yes, as for the database in ADR-020; alternatives: delete the durable consumer but keep the stream; delete both on removal; affects AC-119.14)
- On an external broker, who creates the streams and consumers? (suggested: the external broker's owner; the platform only lists the names, AC-119.17; alternatives: the platform creates them with an admin credential from the secret store; affects AC-119.17)
- Is an external Kafka (or RabbitMQ) broker in scope? (suggested: no, a non-goal; NATS only, in the cluster or external; alternatives: external Kafka with `KAFKA_BOOTSTRAP_SERVERS` as a second contract in a follow-up spec; affects Non-goals)
- Do the templates ship publisher or subscriber code? (suggested: no code in templates; the docs describe the environment contract with one short Python example; alternatives: a working publisher and subscriber example in service-python only; examples in every service template; affects a new criterion)

## Changelog

- 2026-10-26 created
