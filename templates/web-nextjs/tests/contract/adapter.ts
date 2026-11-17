// Project-owned: wire this to your form so the contract check (tests/contract.test.ts) can drive it (spec 110).
import type { ContractAdapter } from "@/lib/contract/engine";

const NOT_WIRED = "wire tests/contract/adapter.ts to your form (spec 110)";

export const adapter: ContractAdapter = {
  // A valid request body per endpoint; add the fields your form always sends.
  base: () => ({}),
  // Call your front end's own validation and return its messages by field.
  validate: () => {
    throw new Error(NOT_WIRED);
  },
  // Render the form (Testing Library), answer its submit with `response`, return what is shown.
  showResponse: () => {
    throw new Error(NOT_WIRED);
  },
};
