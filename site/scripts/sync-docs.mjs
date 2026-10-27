// Copies the user-facing Markdown of the repository into the site (src/content/docs), adding Starlight front matter and
// rewriting relative links. The repository stays the single source of truth; the copies are git-ignored.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { convertWikiLinks, firstHeading, rewriteLinks, stripFirstHeading, withFrontMatter } from './lib.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const OUT = path.join(ROOT, 'site', 'src', 'content', 'docs');
const BASE = '/sdlc-foundry';

/** repo file -> site page. `slug` is relative to the docs collection. */
const PAGES = [
  { src: 'docs/USER-JOURNEY.md', slug: 'guides/user-journey', title: 'User journey: from empty folder to a running system', order: 1 },
  { src: 'docs/HOW-IT-WORKS.md', slug: 'guides/how-it-works', title: 'How it works', order: 2 },
  { src: 'docs/console.md', slug: 'guides/console', title: 'The local console', order: 2 },
  { src: 'docs/DOMAIN-MODEL.md', slug: 'guides/domain-model', title: 'Domain model', order: 3 },
  { src: 'docs/BACKUP-AND-RESTORE.md', slug: 'guides/backup-and-restore', title: 'Backup and restore', order: 4 },
  { src: 'docs/CLUSTERS.md', slug: 'guides/clusters', title: 'Clusters shared by several systems', order: 4 },
  { src: 'docs/ADOPTING.md', slug: 'guides/adopting', title: 'Adopting the platform and troubleshooting', order: 3 },
  { src: 'docs/AGENTS.md', slug: 'guides/agents', title: 'The agent orchestration model', order: 4 },
  { src: 'docs/ARCHITECTURE.md', slug: 'guides/architecture', title: 'Architecture', order: 5 },
  { src: 'docs/templates.md', slug: 'guides/add-a-shape', title: 'Adding a new shape', order: 6 },
  { src: 'docs/unattended-delivery.md', slug: 'guides/unattended-delivery', title: 'Unattended delivery, run records and cost', order: 7 },
  { src: 'docs/requirements/platform-vision.md', slug: 'vision/design-history', title: 'Design history: the original vision PRD', order: 9 },
  { src: 'docs/requirements/end-to-end-scenario.md', slug: 'vision/end-to-end-scenario', title: 'Design history: the end-to-end scenario', order: 10 },
  { src: 'docs/BASELINES.md', slug: 'reference/baselines', title: 'Measured baselines', order: 20 },
  { src: 'docs/e2e/2026-10-08-todo-spec-driven.md', slug: 'reference/e2e-todo-2026-10-08', title: 'Field report: a todo product end to end (2026-10-08)', order: 21 },
  { src: 'docs/e2e/2026-10-09-todo-second-feature.md', slug: 'reference/e2e-todo-2026-10-09', title: 'Field report: a second feature with v4.0.0 (2026-10-09)', order: 22 },
  { src: 'docs/CHANGELOG.md', slug: 'reference/changelog', title: 'Changelog', order: 30 },
  { src: 'docs/adr/README.md', slug: 'reference/adr', title: 'Architecture decision records', order: 25 },
  { src: 'CONTRIBUTING.md', slug: 'community/contributing', title: 'Contributing', order: 1 },
  { src: 'CODE_OF_CONDUCT.md', slug: 'community/code-of-conduct', title: 'Code of conduct', order: 2 },
  { src: 'SECURITY.md', slug: 'community/security', title: 'Security policy', order: 3 },
  { src: 'SUPPORT.md', slug: 'community/support', title: 'Getting help', order: 4 },
  { src: 'THIRD_PARTY_NOTICES.md', slug: 'community/third-party-notices', title: 'Third-party notices', order: 5 },
];

for (const f of fs.readdirSync(path.join(ROOT, 'docs', 'adr')).sort()) {
  const m = f.match(/^(\d+)-.*\.md$/);
  if (!m) continue;
  const first = fs.readFileSync(path.join(ROOT, 'docs', 'adr', f), 'utf8').split('\n')[0].replace(/^#\s*/, '');
  PAGES.push({ src: `docs/adr/${f}`, slug: `reference/adr/${m[1]}`, title: first, order: Number(m[1]) });
}

const bySrc = new Map(PAGES.map((p) => [p.src, p.slug]));
const exists = (repoPath) => {
  const full = path.join(ROOT, repoPath);
  return fs.existsSync(full) ? (fs.statSync(full).isDirectory() ? 'dir' : 'file') : null;
};
const names = new Map(PAGES.map((p) => [path.basename(p.src, '.md').toLowerCase(), `${BASE}/${p.slug}/`]));

function description(markdown) {
  const para = markdown.replace(/^#.*\n+/, '').split(/\n\s*\n/).find((p) => p.trim() && !/^(\||```|>|-|\*|\d+\.|\*\*Status)/.test(p.trim()));
  return para ? para.replace(/\s+/g, ' ').replace(/[`*_[\]]|\([^)]*\)/g, '').trim().slice(0, 160) : undefined;
}

// images of the docs (docs/img/) are served by the site as /img/<name>
const IMG = path.join(ROOT, 'docs', 'img');
const PUBLIC_IMG = path.join(ROOT, 'site', 'public', 'img');
fs.rmSync(PUBLIC_IMG, { recursive: true, force: true });
if (fs.existsSync(IMG)) fs.cpSync(IMG, PUBLIC_IMG, { recursive: true });
const assetFor = (repoPath) => (repoPath.startsWith('docs/img/') && exists(repoPath) === 'file' ? `img/${repoPath.slice('docs/img/'.length)}` : null);

let problems = [];
for (const page of PAGES) {
  const src = fs.readFileSync(path.join(ROOT, page.src), 'utf8');
  let body = convertWikiLinks(stripFirstHeading(src), (n) => names.get(n.toLowerCase()));
  const { text, unresolved } = rewriteLinks(body, page.src, { pageFor: (p) => bySrc.get(p), exists, base: BASE, assetFor });
  problems = problems.concat(unresolved);
  const out = path.join(OUT, `${page.slug}.md`);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, withFrontMatter(text, { title: page.title, description: description(src), order: page.order, editUrl: false }));
}
// the ADR index is the landing page of its folder
fs.mkdirSync(path.join(OUT, 'reference', 'adr'), { recursive: true });
fs.renameSync(path.join(OUT, 'reference', 'adr.md'), path.join(OUT, 'reference', 'adr', 'index.md'));

if (problems.length) {
  console.error('ERROR: links that resolve to nothing:\n  ' + problems.join('\n  '));
  process.exit(1);
}
console.log(`synced ${PAGES.length} pages from the repository`);
