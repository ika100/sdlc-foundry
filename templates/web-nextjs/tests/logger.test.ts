import {
  type Context,
  type ContextManager,
  ROOT_CONTEXT,
  TraceFlags,
  context,
  trace,
} from "@opentelemetry/api";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { logger } from "@/lib/logger";

/** Minimal synchronous context manager, so the test needs no extra package. */
class StackContextManager implements ContextManager {
  private current: Context = ROOT_CONTEXT;
  active(): Context {
    return this.current;
  }
  with<A extends unknown[], F extends (...args: A) => ReturnType<F>>(
    ctx: Context,
    fn: F,
    thisArg?: ThisParameterType<F>,
    ...args: A
  ): ReturnType<F> {
    const previous = this.current;
    this.current = ctx;
    try {
      return fn.call(thisArg, ...args);
    } finally {
      this.current = previous;
    }
  }
  bind<T>(_ctx: Context, target: T): T {
    return target;
  }
  enable(): this {
    return this;
  }
  disable(): this {
    this.current = ROOT_CONTEXT;
    return this;
  }
}

const TRACE_ID = "0af7651916cd43dd8448eb211c80319c";
const SPAN_ID = "b7ad6b7169203331";

function capture(stream: "stdout" | "stderr", fn: () => void): Record<string, unknown> {
  const spy = vi.spyOn(process[stream], "write").mockImplementation(() => true);
  try {
    fn();
    return JSON.parse(String(spy.mock.calls[0][0]));
  } finally {
    spy.mockRestore();
  }
}

function inSpan(fn: () => void, traceId = TRACE_ID, spanId = SPAN_ID): void {
  const span = trace.wrapSpanContext({ traceId, spanId, traceFlags: TraceFlags.SAMPLED });
  context.with(trace.setSpan(ROOT_CONTEXT, span), fn);
}

describe("logger", () => {
  beforeAll(() => {
    context.setGlobalContextManager(new StackContextManager());
  });
  afterEach(() => vi.restoreAllMocks());

  it("carries the active span's trace_id and span_id", () => {
    let line: Record<string, unknown> = {};
    inSpan(() => {
      line = capture("stdout", () => logger.info("hello", { a: 1 }));
    });
    expect(line.trace_id).toBe(TRACE_ID);
    expect(line.span_id).toBe(SPAN_ID);
    expect(line).toMatchObject({ level: "info", msg: "hello", a: 1 });
    expect(typeof line.time).toBe("string");
  });

  it("omits both ids outside a span", () => {
    const line = capture("stdout", () => logger.warn("plain"));
    expect(line).not.toHaveProperty("trace_id");
    expect(line).not.toHaveProperty("span_id");
    expect(line.level).toBe("warn");
  });

  it("omits both ids for an invalid span context", () => {
    let line: Record<string, unknown> = {};
    inSpan(
      () => {
        line = capture("stdout", () => logger.debug("x"));
      },
      "0".repeat(32),
      "0".repeat(16),
    );
    expect(line).not.toHaveProperty("trace_id");
    expect(line).not.toHaveProperty("span_id");
  });

  it("writes errors to stderr", () => {
    const line = capture("stderr", () => logger.error("boom"));
    expect(line).toMatchObject({ level: "error", msg: "boom" });
  });
});
