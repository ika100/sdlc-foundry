// Platform-owned (spec 095): set `overrides: { <package>: '<version>' }` in pnpm-workspace.yaml.
// Usage: node scripts/deps-override.mjs <package> <version>
// A text edit: existing keys (allowBuilds, comments, ...) are kept. Node standard library only.
import { readFileSync, writeFileSync, existsSync } from "node:fs";

const [pkg, ver] = process.argv.slice(2);
if (!pkg || !ver) {
  console.error("usage: node scripts/deps-override.mjs <package> <version>");
  process.exit(2);
}

const file = "pnpm-workspace.yaml";
const text = existsSync(file) ? readFileSync(file, "utf8") : "";
const key = /^[A-Za-z0-9_.-]+$/.test(pkg) ? pkg : `'${pkg.replace(/'/g, "''")}'`;
const entry = `  ${key}: '${ver}'`;
const lines = text.split("\n");
const head = lines.findIndex((l) => /^overrides:\s*(#.*)?$/.test(l) || /^overrides:\s*\{\s*\}\s*(#.*)?$/.test(l));

let out;
if (head === -1) {
  const body = text === "" || text.endsWith("\n") ? text : `${text}\n`;
  out = `${body}${body === "" ? "" : "\n"}overrides:\n${entry}\n`;
} else {
  lines[head] = "overrides:";
  let end = head + 1;
  while (end < lines.length && (/^\s+\S/.test(lines[end]) || /^\s*$/.test(lines[end]) && end + 1 < lines.length && /^\s+\S/.test(lines[end + 1]))) end++;
  const own = (l) => {
    const m = l.match(/^\s+(?:'((?:[^']|'')*)'|"([^"]*)"|([^\s:'"][^:]*?))\s*:/);
    return m ? (m[1] ?? m[2] ?? m[3]).replace(/''/g, "'") : null;
  };
  const at = lines.slice(head + 1, end).findIndex((l) => own(l) === pkg);
  if (at === -1) lines.splice(head + 1, 0, entry);
  else lines[head + 1 + at] = entry;
  out = lines.join("\n");
}
writeFileSync(file, out);
