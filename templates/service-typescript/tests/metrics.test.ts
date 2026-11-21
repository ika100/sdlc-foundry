import { describe, expect, it } from "vitest";

import { buildApp } from "../src/app.js";

describe("metrics", () => {
  it("GET /metrics exposes Prometheus text with default and request metrics by route", async () => {
    const app = buildApp();
    await app.inject({ method: "GET", url: "/health" });
    const res = await app.inject({ method: "GET", url: "/metrics" });
    await app.close();
    expect(res.statusCode).toBe(200);
    expect(res.headers["content-type"]).toContain("text/plain");
    expect(res.body).toContain("process_cpu_user_seconds_total");
    expect(res.body).toMatch(/http_requests_total\{method="GET",route="\/health",status="200"\} 1/);
    expect(res.body).toContain("http_request_duration_seconds_bucket");
  });
});
