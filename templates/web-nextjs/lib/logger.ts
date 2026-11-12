import { isSpanContextValid, trace } from "@opentelemetry/api";

type Level = "debug" | "info" | "warn" | "error";

/** One JSON line per call; inside an active span the line carries its trace_id and span_id. */
function write(level: Level, msg: string, fields?: Record<string, unknown>): void {
  const spanContext = trace.getActiveSpan()?.spanContext();
  const ids =
    spanContext && isSpanContextValid(spanContext)
      ? { trace_id: spanContext.traceId, span_id: spanContext.spanId }
      : {};
  const line = JSON.stringify({ time: new Date().toISOString(), level, msg, ...fields, ...ids });
  if (level === "error") {
    process.stderr.write(`${line}\n`);
  } else {
    process.stdout.write(`${line}\n`);
  }
}

export const logger = {
  debug: (msg: string, fields?: Record<string, unknown>) => write("debug", msg, fields),
  info: (msg: string, fields?: Record<string, unknown>) => write("info", msg, fields),
  warn: (msg: string, fields?: Record<string, unknown>) => write("warn", msg, fields),
  error: (msg: string, fields?: Record<string, unknown>) => write("error", msg, fields),
};
