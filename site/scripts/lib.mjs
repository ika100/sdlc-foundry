// Pure helpers for the docs sync (unit-tested in tests/). No file-system access here.
import path from 'node:path';

export const REPO_URL = 'https://github.com/ika100/sdlc-foundry';

/** Split text into fenced code blocks and prose so link rewriting never touches code. */
function mapProse(markdown, fn) {
  const parts = markdown.split(/(^```[\s\S]*?^```[^\n]*$)/m);
  return parts
    .map((part, i) => (i % 2 === 1 ? part : part.split(/(`[^`\n]*`)/).map((seg, j) => (j % 2 === 1 ? seg : fn(seg))).join('')))
    .join('');
}

export function firstHeading(markdown) {
  const m = markdown.match(/^#{1,3}\s+(.+?)\s*$/m);
  return m ? m[1].replace(/[`*_]/g, '') : null;
}

export function stripFirstHeading(markdown) {
  return markdown.replace(/^#{1,3}\s+.+\n+/, '');
}

/** Front matter with a safely quoted title/description. */
export function withFrontMatter(markdown, meta) {
  const q = (s) => JSON.stringify(String(s));
  const lines = ['---', `title: ${q(meta.title)}`];
  if (meta.description) lines.push(`description: ${q(meta.description)}`);
  if (meta.order !== undefined) lines.push('sidebar:', `  order: ${meta.order}`);
  if (meta.editUrl === false) lines.push('editUrl: false');
  lines.push('---', '');
  return lines.join('\n') + markdown;
}

/** [[NAME]] wiki links (used in the vision PRD): link to a known page, else plain text. */
export function convertWikiLinks(markdown, resolveName) {
  return mapProse(markdown, (seg) => seg.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, name, label) => {
    const href = resolveName(name.trim());
    return href ? `[${label || name.trim()}](${href})` : label || name.trim();
  }));
}

/**
 * Rewrite relative Markdown links of a repository file.
 * - links to files that become site pages -> site paths (with the base path)
 * - images that are copied into the site (`assetFor`) -> site paths
 * - other repository files/directories -> GitHub URLs
 * - external, mailto and #anchor links are left alone
 * `exists(repoPath)` returns 'file' | 'dir' | null. Unresolvable links are reported in `unresolved`.
 */
export function rewriteLinks(markdown, sourceRepoPath, { pageFor, exists, base, assetFor = () => null }) {
  const unresolved = [];
  const dir = path.posix.dirname(sourceRepoPath);
  const text = mapProse(markdown, (seg) =>
    seg.replace(/(!?\[[^\]]*\])\(([^)\s]+)((?:\s+"[^"]*")?)\)/g, (whole, label, target, title) => {
      if (/^([a-z][a-z0-9+.-]*:|#|\/\/)/i.test(target)) return whole;
      if (target.startsWith(`${base}/`)) return whole; // already a final site URL (e.g. from a wiki link)
      const [rawPath, fragment = ''] = target.split('#');
      if (!rawPath) return whole;
      const repoPath = path.posix.normalize(rawPath.startsWith('/') ? rawPath.slice(1) : path.posix.join(dir, rawPath)).replace(/\/$/, '');
      const hash = fragment ? `#${fragment}` : '';
      const page = pageFor(repoPath);
      if (page) return `${label}(${base}/${page}/${hash})`;
      const asset = label.startsWith('!') ? assetFor(repoPath) : null;
      if (asset) return `${label}(${base}/${asset}${title})`;
      const kind = exists(repoPath);
      if (!kind) {
        unresolved.push(`${sourceRepoPath}: ${target}`);
        return whole;
      }
      return `${label}(${REPO_URL}/${kind === 'dir' ? 'tree' : 'blob'}/main/${repoPath}${hash}${title})`;
    }),
  );
  return { text, unresolved };
}

/** Pull "Usage: ..." out of a command description; returns { summary, usage }. */
export function splitDescription(description) {
  const i = description.indexOf('Usage:');
  if (i === -1) return { summary: description.trim(), usage: '' };
  return { summary: description.slice(0, i).trim().replace(/[ .]+$/, '.'), usage: description.slice(i + 6).trim() };
}

export function mdTableCell(s) {
  return String(s ?? '').replace(/\|/g, '\\|').replace(/\n/g, ' ');
}
