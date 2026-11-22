import { describe, expect, it } from "vitest";

import { greet } from "../src/index.js";

describe("greet", () => {
  it("greets a trimmed name", () => {
    expect(greet("  Ada ")).toEqual({ name: "Ada", text: "Hello, Ada!" });
  });

  it("refuses a blank name", () => {
    expect(() => greet("   ")).toThrow(RangeError);
  });
});
