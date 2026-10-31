# ADR-074: A gate that checked nothing fails

**Status:** Accepted (2026-10-31, spec 130)

## Context

CI, `/component:build`, `/component:ship` and the reviewer read a green gate as "verified". A gate can be green while it checked
nothing: a test runner that collected or ran 0 tests (or only skipped ones), kubeconform over an empty build (#260, #266, fixed for
cluster-gitops `validate` only in #278), a render check that compared no files, a secrets scan handed an empty file list. Every generated
repo inherits these holes, and a recipe edited later can bring one back.

## Decision

1. **Every covered gate counts what it checked and fails on 0.** Covered gates: `test`, `test-fast`, `validate`, `render-check`,
   `secrets-scan` in every template. The count comes from what the tool itself reports (JUnit XML for pytest and Maven, `go test -v`
   result lines, the Vitest JSON report, kubeconform's summary and the rendered documents, the rendered file set, `git ls-files`), never
   from a guess about the inputs. Skipped tests do not count.
2. **One message format, one helper.** The failure is one stderr line
   `<gate>: checked nothing: <what was empty> - <how to fix>`, with `<what was empty>` one of `0 tests ran`, `0 resources`,
   `0 files compared`, `0 files to scan`. Shell recipes produce it through `scripts/gate.sh` (one byte-identical file in every template,
   kept equal by `scripts/sync-template-copies.py`); the two Python renderers print the same format themselves.
3. **The check lives in platform-owned files.** Recipes in `devbox.json`, `scripts/gate.sh`, `scripts/render.py` and
   `vitest.config.mts` are re-applied by `/platform:update`; project-owned files (`pyproject.toml`, `pom.xml`, `package.json`, tests)
   are not touched, so the rule reaches existing repos without a merge of their manifests.
4. **No opt-out.** No setting, environment variable or recipe argument makes an empty gate pass. A repo without tests adds one.
5. **A platform test keeps it closed.** `tests/cplat/test_130_empty_gates.py` renders every template of `shapes.yml`, runs each covered
   gate against empty input with stub tools and asserts the exit and the line; a template without an entry fails the suite.

## Consequences

- A repo with 0 tests (or an empty build or file list) turns red after `/platform:update`; the changelog names the symptom and the fix.
  This is a behaviour change, released as a minor.
- A runner that broke (compile error, missing tool) keeps its own exit and message; the "checked nothing" line is printed only when the
  runner itself finished and reported nothing, so a broken build is never told to "add a test".
- `go test` runs with `-v` in the recipes (its result lines are the count), so the Go `test` output is longer.
- New templates and new gate recipes must follow the rule; the contributing guide and the template authoring guide say so and point
  to the platform test.
