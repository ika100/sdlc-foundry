## What and why

<!-- What does this change, and why? Link the issue (Closes #123) if there is one. -->

## Checklist

- [ ] PR title follows Conventional Commits (`feat(scope): ...`) and every commit is signed off (`git commit -s`)
- [ ] Tests added or updated (`tests/cplat`, or the template's own tests)
- [ ] `uv run scripts/shapes.py check`, `python3 scripts/pin-actions.py --check` and `pytest tests/cplat` pass locally
- [ ] Plugin changed? Version bumped in `plugin.json` **and** `.claude-plugin/marketplace.json`
- [ ] User-visible change? One changelog fragment `docs/changelog.d/<id>-<slug>.<added|changed|fixed>.md` (not an edit of `docs/CHANGELOG.md`)
- [ ] ADR added or updated if this changes how the platform works
- [ ] No secrets or personal data in code, tests, fixtures or screenshots

## How I verified it

<!-- Commands you ran, template you rendered, screenshots for UI changes. -->
