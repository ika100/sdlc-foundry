---
spec_id: 078-one-image-tag-format
title: 'One image tag format: the full commit sha'
status: done
priority: P1
tracks: [116]
---

# 078 — One image tag format: the full commit sha

## Problem

The template CI pushes `sha-<7>`, and pin-dev and `pin.py` accept only `sha-<7>`. ai-ops reads `sha-{commit}` as the full sha, so it cannot pin stock-manager. A 7-character prefix can also collide. Decided 2026-10-22: the full sha is the one format.

## Stories

As a tool reading or writing pins, I want one unambiguous image tag, so that every consumer pins the same thing.

## Acceptance criteria

- **AC-078.1** Given a merge to main, when the template CI publishes the image, then it pushes `sha-<40>` (and still `sha-<7>` for one release), and the pin-dev dispatch sends `sha-<40>`.
- **AC-078.2** Given `pin-dev.yml` and `pin.py`, when a tag arrives, then both `sha-<40>` and `sha-<7>` are accepted, the pin branch stays `pin/dev-<service>-<7>`, and `/gitops:promote --sha` pins `sha-<40>` (falling back to `sha-<7>` for images built before).
- **AC-078.3** Given ADR-030 and the docs, when someone reads how images are tagged, then they say `sha-<40>` everywhere `sha-<7>` was the pin format.

## Non-goals

- Retagging existing images.

## Open questions

None.

## Changelog

- 2026-10-22 created from #116
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done
