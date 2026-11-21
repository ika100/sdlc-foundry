import type { FastifyInstance } from "fastify";
import { Counter, Histogram, Registry, collectDefaultMetrics } from "prom-client";

export interface Metrics {
  registry: Registry;
  requests: Counter<"method" | "route" | "status">;
  duration: Histogram<"method" | "route" | "status">;
}

/** A registry of its own per app, so that tests can build several apps in one process. */
export function createMetrics(): Metrics {
  const registry = new Registry();
  collectDefaultMetrics({ register: registry });
  const labelNames = ["method", "route", "status"] as const;
  return {
    registry,
    requests: new Counter({
      name: "http_requests_total",
      help: "HTTP requests by method, route and status.",
      labelNames,
      registers: [registry],
    }),
    duration: new Histogram({
      name: "http_request_duration_seconds",
      help: "HTTP request duration in seconds by method, route and status.",
      labelNames,
      registers: [registry],
    }),
  };
}

/** Counts and times every request by its route pattern (never the raw URL, which would explode the label set). */
export function registerMetrics(app: FastifyInstance, metrics: Metrics = createMetrics()): void {
  app.addHook("onResponse", async (request, reply) => {
    const labels = {
      method: request.method,
      route: request.routeOptions.url ?? "unmatched",
      status: String(reply.statusCode),
    };
    metrics.requests.inc(labels);
    metrics.duration.observe(labels, reply.elapsedTime / 1000);
  });
  app.get("/metrics", async (_request, reply) => {
    return reply.type(metrics.registry.contentType).send(await metrics.registry.metrics());
  });
}
