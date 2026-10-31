import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// scripts/gate.sh sets VITEST_GATE_REPORT to count the tests that ran (spec 130).
const gateReport = process.env.VITEST_GATE_REPORT;

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirror tsconfig "paths": { "@/*": ["./*"] }
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    ...(gateReport ? { reporters: ["default", "json"], outputFile: { json: gateReport } } : {}),
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["app/**/*.{ts,tsx}"],
      reporter: ["text", "lcov"],
      thresholds: { lines: 80, functions: 80, statements: 80 },
    },
  },
});
