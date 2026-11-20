// Spec 110 test runner: loads the web-nextjs contract engine and runs every case against a small fake form.
// Usage: node contract_runner_110.mjs <engine.ts> <contract dir> '<options json>'; prints [{name, result}] as JSON.
import { pathToFileURL } from "node:url";

const [engine, dir, optionsJson] = process.argv.slice(2);
const o = {
  titleMax: 200,
  titleRequired: true,
  statuses: ["open", "done"],
  showAtField: true,
  unlisted: "Something went wrong. Please try again.",
  ...JSON.parse(optionsJson || "{}"),
};

const mod = await import(pathToFileURL(engine).href);

const adapter = {
  base: () => ({ title: "x", status: "open" }),
  validate: (endpoint, body) => {
    const errors = {};
    if (typeof body.title === "string" && body.title.length > o.titleMax) errors.title = "Title too long";
    if (o.titleRequired && (body.title === undefined || body.title === "")) errors.title = "Title is required";
    if (body.status !== undefined && !o.statuses.includes(body.status)) errors.status = "Unknown status";
    return errors;
  },
  showResponse: async (endpoint, response) => {
    const body = response.body;
    if (response.status === 422 && body && Array.isArray(body.errors) && body.errors.length > 0) {
      const e = body.errors[0];
      return o.showAtField ? { fields: { [e.field]: e.message } } : { fields: {}, form: e.message };
    }
    return { fields: {}, form: o.unlisted };
  },
};

const out = [];
for (const c of mod.contractCases(dir)) {
  out.push({ name: c.name, result: await c.run(adapter) });
}
console.log(JSON.stringify(out));
