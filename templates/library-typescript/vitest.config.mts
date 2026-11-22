import { defineConfig } from "vitest/config";

// scripts/gate.sh sets VITEST_GATE_REPORT to count the tests that ran (spec 130).
const gateReport = process.env.VITEST_GATE_REPORT;

export default defineConfig({
  test: {
    ...(gateReport ? { reporters: ["default", "json"], outputFile: { json: gateReport } } : {}),
    environment: "node",
    include: ["tests/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts"],
      reporter: ["text", "lcov"],
      thresholds: { lines: 80, functions: 80, statements: 80 },
    },
  },
});
