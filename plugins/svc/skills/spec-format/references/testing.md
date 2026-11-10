# Acceptance tests

Acceptance tests turn the criteria into executable checks. They are written **from the approved spec, before the code**, and they are the coders' definition of done.

## Naming the criterion

Every acceptance test names the criterion it proves, in its name or a comment on the test. `cplat spec trace` searches the shape's `test_globs` (from `shapes.yml`) for the id; `AC-007.1` never matches `AC-007.10`.

| Shape | Idiom |
|---|---|
| service-python, library-python | `def test_alert_email_on_cross():  # AC-007.1` |
| web-nextjs | `it("AC-007.1 sends an email when the price crosses", …)` |
| service-java | `@DisplayName("AC-007.1 sends an email when the price crosses")` |
| service-go | `t.Run("AC-007.1 sends an email when the price crosses", …)` or `// AC-007.1` above the test |

One test may name several criteria; one criterion may need several tests (happy path and errors).

## Red first

- Write the tests against the **contract** (`design.md`) and the public surface the criteria describe, not against internals, because the coders write those later.
- Run `devbox run test-fast`. Every new acceptance test must **fail because the behaviour is missing**: an assertion failure, a 404 for the missing route, or an import of the missing module. A test that fails for another reason (syntax error, broken fixture) is a broken test; fix it.
- A test that already passes proves nothing about the new feature: tighten it or report the criterion as met.
- Run `devbox run lint-fix` first, then commit them as one commit: `test(<slug>): acceptance tests for AC-007.1–AC-007.4`. Tests a later `lint-fix` would rewrite fail `cplat spec test-diff`.

## Smoke tests for `(smoke)` criteria

A criterion that ends with `(smoke)` gets a second test, a smoke test, which `devbox run smoke` runs against a deployed environment (`SMOKE_BASE_URL`, no trailing slash). Put it in a file naming the criterion id and carrying the shape's tag, because `cplat spec trace` counts the criterion only then.

| Shape | Tag and base URL | Skips itself when `SMOKE_BASE_URL` is empty |
|---|---|---|
| service-python | `@pytest.mark.smoke` + fixture `smoke_base_url` | the fixture |
| service-java | `@Tag("smoke")`, `java.net.http.HttpClient` | `@EnabledIfEnvironmentVariable(named = "SMOKE_BASE_URL", matches = ".+")` |
| service-go | top-level `func TestSmoke<Name>(t *testing.T)` | `if os.Getenv("SMOKE_BASE_URL") == "" { t.Skip("SMOKE_BASE_URL not set") }` |
| web-nextjs | Playwright test in `e2e/` with `@smoke` in the title | `test.skip(!process.env.SMOKE_BASE_URL, "SMOKE_BASE_URL not set")` |

Rules: reach the service only through the base URL; create your own data with unique names (`smoke-<uuid>`); never change or delete data you did not create, so that the test is repeatable against a shared environment; one smoke test per criterion, clearly named.

Writing data: smoke runs in dev, staging and prod (`SMOKE_ENV`); outside dev the platform sets `SMOKE_READ_ONLY=1` and the harness leaves out every smoke test marked as writing, so that dev alone gets smoke data. Mark a smoke test that creates, changes or deletes data: `@pytest.mark.writes` (python), `@Tag("writes")` (java), the name `TestSmokeWrites<Name>` (go), `@writes` in the title (web). Keep read-only smoke checks too, because outside dev a run where no smoke test passed is reported as not run, never as passed.

## After that

- Assert on parsed values, never on serialized text, because the order of keys in a JSON object is never part of a contract and a map does not keep it: decode a JSON body into a typed value (or compare decoded values) and check the fields and the order of lists the criterion names.
- **Hard rule:** Coders make these tests pass and never edit, skip or weaken them, because a test that bends to the code proves nothing. Formatting through `devbox run lint-fix` is fine, and so is a line-level linter suppression that names its rule for a false positive (`//nolint:<rule>`, `# noqa: <code>`, `# type: ignore[<code>]`, `// eslint-disable-next-line <rule>`, `@SuppressWarnings("<name>")` on a method; spec 160): the build checks every change with `cplat spec test-diff <red commit>` (same parsed code for Python, same text without whitespace for other languages, same criterion ids, the suppressions aside) and stops on anything else, a file-wide or rule-less suppression included. If a test contradicts the spec or the contract, the coder stops and reports it; the orchestrator decides (and records the change in the spec's Changelog if the spec was wrong).
- Unit and integration tests for internals come later as usual; they need no criterion ids, because they test internals, not criteria.
