# Design — 106 Prod runs the exact image staging tested

## Decisions

- **Digests come from `registry.py` (spec 105).** 106 extends it: `registry.digests(image, tags) -> {tag: digest|None}`
  pages through every version (`?per_page=100&page=N` until a short page, at most 20 pages) in one pass, and
  `registry.digest` uses it. A lookup that fails raises `RegistryError` (message names the call, hint the fix such as
  `gh auth refresh -s read:packages`); `promote` turns that into a refusal, never a warning (AC-106.5).
- **The check runs in `promote.py` before anything is written** (AC-106.1, AC-106.2, AC-106.11). For a `staging →
  prod` promotion the plan step reads, per service, the tag `staging` pins (`_staging_tag`, the local overlay) and the
  release tag `X.Y.Z` from `pick_tag`. Then:
  - the staging tag must be an immutable build tag `sha-<40 hex>` (`latest`, a short sha or a semver tag →
    refusal "the staging image cannot be identified: <tag>", AC-106.8);
  - both tags must exist (`registry.digests`; a missing one is named, AC-106.4; the existing "image does not exist"
    refusal for the release tag stays);
  - equal digests → proceed; different → refusal naming the service, both tags and both digests, "prod would not run
    what staging tested", and the next step (re-publish the release from the tested image with the release job, or
    promote the release whose image is the staging one).
  All services are checked first; any failure → exit 1, no PR, nothing changed, every failing service listed.
- **Dry run** (AC-106.3): `--dry-run` (and `--json`) prints per service `staging: <tag> <digest>`,
  `prod: <tag> <digest>`, `match`/`mismatch`; a mismatch exits 1 and writes nothing. JSON: `data.digests[<svc>] =
  {staging_tag, staging_digest, release_tag, release_digest, result}`.
- **Override** (AC-106.7): `--accept-digest-mismatch "<reason>"`. The reason must be at least one sentence: 3 or more
  words and ending in `.`, `!` or `?`; otherwise the flag is refused. With it the promotion proceeds, and the output
  and the PR body say `digest mismatch accepted: <reason>` with both digests. It applies only to the digest
  comparison; missing tags, a failed lookup and an unidentifiable staging tag still refuse.
- **`--no-verify`** (AC-106.6) skips the digest check for prod as well and prints one line
  `image identity not verified (--no-verify)`. A promotion to `staging` has no digest check, as before.
- **Evidence and PR body** (AC-106.9): on a match, `evidence.summary` and the PR body get
  `image digest: <digest> (same in staging and prod)`.
- **Release job re-tags, never rebuilds** (AC-106.10). In the four image-publishing templates (`service-python`,
  `service-java`, `service-go`, `web-nextjs`), a `v*.*.*` tag push no longer runs the image build. A new
  `release-image` job resolves `sha-${GITHUB_SHA}` with `docker buildx imagetools inspect`. If that image is missing,
  it fails with "no published sha-<40> image for <sha>: merge to main and wait for its CI before tagging". Otherwise
  it runs `docker buildx imagetools create` with the `X.Y.Z`, `X.Y` and `X` tags pointing at that manifest list, so
  the digest is identical. The release Trivy gate scans that image by digest instead of a fresh build. Jinja escaping
  follows the existing `${{ '{{' }} … {{ '}}' }}` pattern.
- **Docs** (AC-106.12): `plugins/gitops/commands/promote.md` and `docs/unattended-delivery.md` state the digest rule,
  the dry-run output and the override.

## Contract

```
registry.digests(image: str, tags: list[str]) -> dict[str, str | None]      raises RegistryError
cplat promote <svc...> staging prod [--dry-run [--json]] [--no-verify] [--accept-digest-mismatch "<reason>"]
template CI: job release-image (on v*.*.* tags): imagetools inspect sha-<40> → imagetools create X.Y.Z, X.Y, X
```
