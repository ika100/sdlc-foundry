// Turns Playwright's JSON report into the smoke result lines (platform-owned, spec 091).
// Usage: node scripts/smoke-summary.mjs <report.json>
import { readFileSync } from "node:fs";
import path from "node:path";

const report = JSON.parse(readFileSync(process.argv[2], "utf8"));
const root = report.config?.rootDir ?? process.cwd();
const lines = [];
const counts = { PASS: 0, FAIL: 0, SKIP: 0 };

function walk(suite) {
  for (const spec of suite.specs ?? []) {
    const file = path.relative(process.cwd(), path.resolve(root, spec.file ?? suite.file ?? ""));
    for (const t of spec.tests ?? []) {
      const results = t.results ?? [];
      const last = results[results.length - 1];
      let verdict = "FAIL";
      if (t.status === "skipped" || (last && last.status === "skipped")) verdict = "SKIP";
      else if (t.status === "expected" || t.status === "flaky") verdict = "PASS";
      counts[verdict] += 1;
      lines.push(`${verdict}  ${file.split(path.sep).join("/")}::${spec.title}`);
    }
  }
  for (const child of suite.suites ?? []) walk(child);
}
for (const suite of report.suites ?? []) walk(suite);

if (lines.length === 0) {
  console.log("0 smoke tests");
} else {
  console.log(lines.join("\n"));
  console.log(`smoke: ${counts.PASS} passed, ${counts.FAIL} failed, ${counts.SKIP} skipped`);
}
process.exit(counts.FAIL > 0 ? 1 : 0);
