# ADR-054: The 5.0 interface: system.yaml checked by the renderer, noun plugins with tombstones, and a migration that proves itself

**Status:** Accepted (2026-10-26)
**Builds on:** [ADR-053](053-domain-model.md) (the domain model and the two steps), [ADR-014](014-gitops-app-composition-spec.md) (composition), [ADR-017](017-gitops-owns-manifests.md) (the gitops-app owns manifests), [ADR-020](020-addons-contract.md) (addons), spec 096 (fleet updates)

## Context

ADR-053 decided that 5.0 replaces `app.yaml` and `services.yaml` with one `system.yaml`, groups the commands by noun and converts existing repos. Spec 114 is that release. Three choices in it outlive the release itself:

1. Two programs read `system.yaml`: the gitops-app's own `scripts/render.py`, which runs in the gitops repo's CI without the platform, and `cplat`'s model (spec 113). Both could validate the file, and their rules would drift.
2. Claude Code has no way to rename a slash command. A user who types `/svc:ship` after the update either gets "unknown command" or an alias, and [CLAUDE.md](../../CLAUDE.md) rules out aliases.
3. The fleet update (spec 096) never merges a major version by itself. 5.0 is a major version that touches every repo, so without an exception every repo waits for a person, although the migration can show that nothing in the cluster changes.

## Decision

1. **The renderer is the only validator of `system.yaml`.** `render.py` rejects every malformed file with a message naming the key, and it runs on every change (`devbox run render`, `render --check` in CI, every `cplat` command that edits the file). `cplat`'s model loads `system.yaml` leniently (it skips what it cannot read, as spec 113's loaders do) and never re-implements a schema rule. The few facts both need (the environment list, the valid `type`/`lang` pairs) are constants in both, and a platform test fails when they differ.
2. **Plugins are named after the nouns** (`system`, `component`, `api`, `resource`, `instance`, `issue`, `platform`); agents stay where the shapes route them (`svc`, `svc-java`, `svc-go`, `web`, `shared`). `shared` keeps the `cplat` launcher and the hooks, so every noun plugin needs it enabled.
3. **A renamed command leaves a tombstone, never an alias.** The last major of a plugin that loses a command keeps a command file of the old name that runs nothing and answers with one line naming the new command (and the migration, in an unmigrated repo). The tombstones are generated from one table in `scripts/tombstones.py`, which the CHANGELOG's old → new table and the tests read too. A plugin that holds only tombstones leaves the marketplace in the next major (`app` and `gitops` in 6.0). `cplat` subcommands do the same: a regrouped name exits 2 and names the new form.
4. **A migration proves itself, and only a proved migration merges by itself.** The platform keeps a frozen copy of the last 4.x renderer (`scripts/cplat/assets/render_v4.py`). `cplat platform update --migrate` renders the repo with it before converting and with the new renderer after, and refuses (nothing committed) unless every generated file is byte-identical. The fleet merges a major update on green CI only when that proof holds and the update overwrote nothing the repo added; otherwise the PR waits for review as before.

## Consequences

- One schema, one place: a rule added to `system.yaml` is a change to `render.py` and its tests; `cplat` only learns to read the new key.
- Users of 4.x names get a pointer instead of an error for one major version; the marketplace drops the empty plugins in 6.0.
- Future breaking changes to the gitops-app files can follow the same pattern: freeze the old renderer, convert, compare, merge only on proof.
- The frozen renderer is code the platform keeps without running it in production; it is removed together with the 4.x migration in 6.0.
