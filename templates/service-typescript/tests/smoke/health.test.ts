import { describe, expect, it } from "vitest";

// Smoke tests run against a deployed instance: `SMOKE_BASE_URL=https://<host> devbox run smoke` (spec 091). Each test
// name carries @smoke; one that creates, changes or deletes data also carries @writes and then runs only in dev (#474).
// Without SMOKE_BASE_URL (devbox run test, ci) they are skipped.
const base = process.env.SMOKE_BASE_URL;

describe.skipIf(!base)("smoke", () => {
  it("the service answers /health at the base URL @smoke", async () => {
    const res = await fetch(new URL("/health", base));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "ok" });
  });
});
