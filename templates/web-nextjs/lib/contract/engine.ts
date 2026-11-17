// Consumer contract check (spec 110; platform-owned: /platform:update refreshes it).
//
// Every rule of contract/<plan_id>.json with role "consumer" becomes cases: the boundary values of the rule go
// through the front end's own validation, and the contract's error response (and one the contract does not list)
// goes through the form. The copy is written by `/component:spec --from-plan`; never edit it by hand. Wire the
// form in tests/contract/adapter.ts. Plain, erasable TypeScript with no dependency but node:fs (node runs it directly).
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

export type FieldErrors = Record<string, string>; // field -> message shown; {} = valid

export interface ContractAdapter {
  /** A valid request body for the endpoint. */
  base(endpoint: string): Record<string, unknown>;
  /** The front end's own validation of the body. */
  validate(endpoint: string, body: Record<string, unknown>): FieldErrors | Promise<FieldErrors>;
  /** Render the form, answer the submit with this response, read what is shown. */
  showResponse(
    endpoint: string,
    response: { status: number; body: unknown },
  ): Promise<{ fields: FieldErrors; form?: string }>;
}

export interface ContractCase {
  name: string;
  /** null = pass, else the failure message. */
  run(adapter: ContractAdapter): Promise<string | null>;
}

interface Rule {
  id: string;
  endpoint: string;
  field: string;
  kind: string;
  value?: unknown;
  step?: number;
  status?: number;
  role?: string;
}

interface Errors {
  status?: number;
  body?: { list?: string; field?: string; rule?: string; message?: string };
  unlisted?: { message?: string };
}

interface Doc {
  plan_id: string;
  rules?: Rule[];
  errors?: Errors;
}

const UNSET = Symbol("unset");

function isNumber(value: unknown): value is number {
  return typeof value === "number";
}

function decimals(n: number): number {
  const text = String(n);
  return text.includes(".") && !text.includes("e") ? text.split(".")[1].length : 0;
}

function stepped(value: number, step: number, sign: number): number {
  return Number((value + sign * step).toFixed(Math.max(decimals(step), decimals(value))));
}

function derivedValue(rule: Rule, rules: Rule[]): unknown {
  const same = rules.filter((r) => r.endpoint === rule.endpoint && r.field === rule.field);
  const allowed = same.find((r) => r.kind === "allowed");
  if (allowed) return (allowed.value as unknown[])[0];
  const minLength = same.find((r) => r.kind === "min_length");
  if (minLength) return "x".repeat(Math.max(minLength.value as number, 1));
  const minValue = same.find((r) => r.kind === "min_value");
  if (minValue) return minValue.value;
  return "x";
}

function notAllowed(values: unknown[]): unknown {
  if (values.every(isNumber)) return Math.max(...values) + 1;
  let out = `${String(values[0])}-not-allowed`;
  while (values.includes(out)) out += "-not-allowed";
  return out;
}

function getPath(body: Record<string, unknown>, dotted: string): unknown {
  let node: unknown = body;
  for (const key of dotted.split(".")) {
    if (typeof node !== "object" || node === null || !(key in node)) return UNSET;
    node = (node as Record<string, unknown>)[key];
  }
  return node;
}

function setPath(body: Record<string, unknown>, dotted: string, value: unknown, remove = false): void {
  const parts = dotted.split(".");
  const last = parts.pop() as string;
  let node = body;
  for (const key of parts) {
    let child = node[key];
    if (typeof child !== "object" || child === null) {
      if (remove) return;
      child = node[key] = {};
    }
    node = child as Record<string, unknown>;
  }
  if (remove) delete node[last];
  else node[last] = value;
}

function shown(value: unknown, removed: boolean): string {
  if (removed) return "field removed";
  if (typeof value === "string" && value.length > 40) return `${value.length} characters`;
  return String(value);
}

interface Spec {
  name: string;
  accept: boolean;
  value?: unknown;
  removed?: boolean;
  derived?: boolean;
}

function specsOf(rule: Rule, rules: Rule[]): Spec[] {
  const value = rule.value;
  if (rule.kind === "required") {
    return [
      { name: "present", accept: true, derived: true, value: derivedValue(rule, rules) },
      { name: "missing", accept: false, removed: true },
    ];
  }
  if (rule.kind === "min_length" || rule.kind === "max_length") {
    const n = value as number;
    const past = rule.kind === "min_length" ? n - 1 : n + 1;
    const out: Spec[] = [{ name: "at-limit", accept: true, value: "x".repeat(n) }];
    if (past >= 0 && !(rule.kind === "min_length" && n === 0)) {
      out.push({ name: "past-limit", accept: false, value: "x".repeat(past) });
    }
    return out;
  }
  if (rule.kind === "min_value" || rule.kind === "max_value") {
    const v = value as number;
    const past = stepped(v, rule.step ?? 1, rule.kind === "min_value" ? -1 : 1);
    return [
      { name: "at-limit", accept: true, value: v },
      { name: "past-limit", accept: false, value: past },
    ];
  }
  if (rule.kind === "allowed") {
    const values = value as unknown[];
    return [
      ...values.map((v): Spec => ({ name: `allowed=${String(v)}`, accept: true, value: v })),
      { name: "not-allowed", accept: false, value: notAllowed(values) },
    ];
  }
  return [];
}

function validationCase(planId: string, rule: Rule, rules: Rule[], spec: Spec): ContractCase {
  return {
    name: `${planId}:${rule.id}:${spec.name}`,
    async run(adapter) {
      const body = structuredClone(adapter.base(rule.endpoint));
      let value = spec.value;
      if (spec.derived) {
        const existing = getPath(body, rule.field);
        value = existing === UNSET ? spec.value : existing;
      }
      if (spec.removed) setPath(body, rule.field, undefined, true);
      else setPath(body, rule.field, value);
      const errors = await adapter.validate(rule.endpoint, body);
      const message = errors[rule.field];
      const invalid = message !== undefined;
      if (invalid !== !spec.accept) {
        const got = invalid ? `error at ${rule.field}: ${JSON.stringify(message)}` : "valid";
        const expected = spec.accept ? "valid" : `error at ${rule.field}`;
        return (
          `contract ${planId} rule ${rule.id} field ${rule.field}: ${spec.name} (${shown(value, !!spec.removed)}) ` +
          `on ${rule.endpoint}: expected ${expected}, got ${got}`
        );
      }
      return null;
    },
  };
}

function responseCase(planId: string, rule: Rule, errors: Errors): ContractCase {
  const keys = errors.body ?? {};
  const status = rule.status ?? errors.status ?? 422;
  const message = `${rule.id} violated (contract check)`;
  return {
    name: `${planId}:${rule.id}:response`,
    async run(adapter) {
      const item = {
        [keys.field ?? "field"]: rule.field,
        [keys.rule ?? "rule"]: rule.id,
        [keys.message ?? "message"]: message,
      };
      const body = keys.list ? { [keys.list]: [item] } : item;
      const shownNow = await adapter.showResponse(rule.endpoint, { status, body });
      if (shownNow.fields?.[rule.field] === message) return null;
      return (
        `contract ${planId} rule ${rule.id} field ${rule.field}: response ${status}: expected message ` +
        `${JSON.stringify(message)} at ${rule.field}, got ${JSON.stringify(shownNow)}`
      );
    },
  };
}

function unlistedCase(planId: string, endpoint: string, status: number, message: string): ContractCase {
  return {
    name: `${planId}:${endpoint}:unlisted`,
    async run(adapter) {
      const shownNow = await adapter.showResponse(endpoint, { status, body: {} });
      if (shownNow.form === message && Object.keys(shownNow.fields ?? {}).length === 0) return null;
      return (
        `contract ${planId} ${endpoint}: unlisted response ${status}: expected form message ` +
        `${JSON.stringify(message)}, got ${JSON.stringify(shownNow)}`
      );
    },
  };
}

/** Every consumer rule of every `<dir>/contract/*.json` (the repo root by default), plus the response cases. */
export function contractCases(dir = "."): ContractCase[] {
  const base = join(dir, "contract");
  if (!existsSync(base)) return [];
  const cases: ContractCase[] = [];
  for (const file of readdirSync(base).filter((f) => f.endsWith(".json")).sort()) {
    const doc = JSON.parse(readFileSync(join(base, file), "utf8")) as Doc;
    const errors = doc.errors ?? {};
    const rules = doc.rules ?? [];
    const mine = rules.filter((r) => r.role === "consumer");
    for (const rule of mine) {
      for (const spec of specsOf(rule, rules)) cases.push(validationCase(doc.plan_id, rule, rules, spec));
    }
    for (const rule of mine) cases.push(responseCase(doc.plan_id, rule, errors));
    const used = new Set<number>([errors.status, ...rules.map((r) => r.status)].filter(isNumber));
    const status = [500, 503, 502].find((s) => !used.has(s)) ?? 500;
    const message = errors.unlisted?.message ?? "";
    for (const endpoint of [...new Set(mine.map((r) => r.endpoint))]) {
      cases.push(unlistedCase(doc.plan_id, endpoint, status, message));
    }
  }
  return cases;
}
