import { afterEach, describe, expect, it } from "vitest";

import { buildApp } from "../src/app.js";

describe("probes", () => {
  let app = buildApp();
  afterEach(async () => {
    await app.close();
  });

  it("GET /health answers ok", async () => {
    app = buildApp();
    const res = await app.inject({ method: "GET", url: "/health" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ status: "ok" });
  });

  it("GET /ready answers ready while every dependency answers", async () => {
    app = buildApp({ ready: () => Promise.resolve(true) });
    const res = await app.inject({ method: "GET", url: "/ready" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ status: "ready" });
  });

  it("GET /ready answers 503 while a dependency does not", async () => {
    app = buildApp({ ready: () => Promise.resolve(false) });
    const res = await app.inject({ method: "GET", url: "/ready" });
    expect(res.statusCode).toBe(503);
    expect(res.json()).toEqual({ status: "unavailable" });
  });
});
