// Consumer contract check (spec 110): one test per case of contract/*.json; wire tests/contract/adapter.ts.
import { describe, expect, it } from "vitest";

import { contractCases } from "@/lib/contract/engine";

import { adapter } from "./contract/adapter";

const cases = contractCases();

describe("contract", () => {
  if (cases.length === 0) {
    it("contract: no copy in contract/ (nothing to check)", () => {
      expect(cases).toHaveLength(0);
    });
  }
  for (const contractCase of cases) {
    it(contractCase.name, async () => {
      const failure = await contractCase.run(adapter);
      if (failure) throw new Error(failure);
    });
  }
});
