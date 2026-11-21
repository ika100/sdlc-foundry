// Turns Vitest's JSON report into the smoke result lines (platform-owned, spec 091).
// Usage: SMOKE_PATTERN=<regex> node scripts/smoke-summary.mjs <report.json>
// Only the tests the pattern selects are listed: the ones it leaves out (@writes in a read-only run) are not results.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

const file = process.argv[2];
if (!file || !existsSync(file) || readFileSync(file, "utf8").trim() === "") {
  console.error("smoke-summary: no Vitest JSON report");
  process.exit(2);
}
const report = JSON.parse(readFileSync(file, "utf8"));
const pattern = new RegExp(process.env.SMOKE_PATTERN || "@smoke");
const lines = [];
const counts = { PASS: 0, FAIL: 0, SKIP: 0 };

for (const result of report.testResults ?? []) {
  const rel = path.relative(process.cwd(), result.name ?? "").split(path.sep).join("/");
  for (const t of result.assertionResults ?? []) {
    const name = t.title ?? "";
    if (!pattern.test(t.fullName ?? name)) continue;
    let verdict = "FAIL";
    if (t.status === "passed") verdict = "PASS";
    else if (t.status === "skipped" || t.status === "pending" || t.status === "todo") verdict = "SKIP";
    counts[verdict] += 1;
    lines.push(`${verdict}  ${rel}::${name}`);
  }
}

if (lines.length === 0) {
  console.log("0 smoke tests");
} else {
  console.log(lines.join("\n"));
  console.log(`smoke: ${counts.PASS} passed, ${counts.FAIL} failed, ${counts.SKIP} skipped`);
}
process.exit(counts.FAIL > 0 ? 1 : 0);
