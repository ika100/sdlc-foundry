import { defineConfig } from "vitest/config";

// `devbox run smoke` (scripts/smoke.sh): only the tests in tests/smoke/, against SMOKE_BASE_URL.
export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/smoke/**/*.test.ts"],
    testTimeout: 30_000,
  },
});
