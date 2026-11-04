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
  if (meta.order !== undefined || meta.label) lines.push('sidebar:');
  if (meta.label) lines.push(`  label: ${q(meta.label)}`);
  if (meta.order !== undefined) lines.push(`  order: ${meta.order}`);
  if (meta.editUrl === false) lines.push('editUrl: false');
  lines.push('---', '');
  return lines.join('\n') + markdown;
}

/** [[NAME]] wiki links (used in the vision PRD): link to a known page (read as its title), else plain text. */
export function convertWikiLinks(markdown, resolveName, titleOf = () => null) {
  return mapProse(markdown, (seg) => seg.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, name, label) => {
    const href = resolveName(name.trim());
    return href ? `[${label || titleOf(name.trim()) || name.trim()}](${href})` : label || name.trim();
  }));
}

/**
 * Rewrite relative Markdown links of a repository file.
 * - links to files that become site pages -> site paths (with the base path)
 * - files that are copied into the site (`assetFor`, e.g. images) -> site paths
 * - other repository files/directories -> GitHub URLs
 * - external, mailto and #anchor links are left alone
 * - a link to a page whose text is just a file name ([UPGRADES.md], [USER-JOURNEY]) reads as the page's title (`titleFor`)
 * `exists(repoPath)` returns 'file' | 'dir' | null. Unresolvable links are reported in `unresolved`.
 */
export function rewriteLinks(markdown, sourceRepoPath, { pageFor, exists, base, assetFor = () => null, titleFor = () => null }) {
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
      if (page) {
        const named = /^\[[A-Z0-9_-]+(\.md)?\]$/.test(label) && titleFor(repoPath);
        return `${named ? `[${named}]` : label}(${base}/${page}/${hash})`;
      }
      const asset = assetFor(repoPath);
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

/** Slash commands named in prose (/system:new) are set as code, as everywhere else in the docs. */
export function codeCommands(text) {
  return mapProse(text, (seg) => seg.replace(/(^|[\s(])(\/[a-z]+:[a-z-]+)(?=[\s,.;:)]|$)/g, '$1`$2`'));
}

/** Pull "Usage: ..." out of a command description; returns { summary, usage }. */
export function splitDescription(description) {
  const i = description.indexOf('Usage:');
  if (i === -1) return { summary: description.trim(), usage: '' };
  return { summary: description.slice(0, i).trim().replace(/[ .]+$/, '.'), usage: description.slice(i + 6).trim() };
}

/**
 * A usage line as an inline-code table cell whose option groups ([--env K=V], <spec-id>) never break inside: the line
 * wraps between options only. Raw HTML, so the text is escaped here; pipes become &#124; to stay inside the cell,
 * hyphens &#45; so that typographic quotes do not turn --flag into an en dash.
 */
export function usageCell(usage) {
  const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\|/g, '&#124;').replace(/\n/g, ' ').replace(/-/g, '&#45;');
  let out = '';
  let group = '';
  let depth = 0;
  for (const ch of usage) {
    if (ch === '[' || ch === '<') depth += 1;
    if (depth > 0) group += ch;
    else out += esc(ch);
    if ((ch === ']' || ch === '>') && depth > 0) {
      depth -= 1;
      if (depth === 0) {
        out += `<span class="nw">${esc(group)}</span>`;
        group = '';
      }
    }
  }
  return `<code>${out}${esc(group)}</code>`;
}

export function mdTableCell(s) {
  return String(s ?? '').replace(/\|/g, '\\|').replace(/\n/g, ' ');
}
