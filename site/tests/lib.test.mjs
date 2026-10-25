import assert from 'node:assert/strict';
import test from 'node:test';
import { convertWikiLinks, firstHeading, rewriteLinks, splitDescription, stripFirstHeading, withFrontMatter } from '../scripts/lib.mjs';

const BASE = '/sdlc-foundry';
const ctx = (pages = {}, files = {}) => ({ pageFor: (p) => pages[p], exists: (p) => files[p] ?? null, base: BASE });

test('links to synced pages become site paths and keep their anchor', () => {
  const { text, unresolved } = rewriteLinks('See [adopting](ADOPTING.md#troubleshooting).', 'docs/USER-JOURNEY.md', ctx({ 'docs/ADOPTING.md': 'guides/adopting' }));
  assert.equal(text, 'See [adopting](/sdlc-foundry/guides/adopting/#troubleshooting).');
  assert.deepEqual(unresolved, []);
});

test('links outside docs resolve relative to the source file and point at GitHub', () => {
  const { text } = rewriteLinks('[readme](../README.md) and [templates](../templates/web-nextjs/)', 'docs/HOW-IT-WORKS.md', ctx({}, { 'README.md': 'file', 'templates/web-nextjs': 'dir' }));
  assert.match(text, /\(https:\/\/github\.com\/ika100\/sdlc-foundry\/blob\/main\/README\.md\)/);
  assert.match(text, /\(https:\/\/github\.com\/ika100\/sdlc-foundry\/tree\/main\/templates\/web-nextjs\)/);
});

test('external, mailto, anchor and already-final site links are untouched', () => {
  const src = '[a](https://example.com) [b](mailto:x@y.z) [c](#here) [d](/sdlc-foundry/guides/x/)';
  assert.equal(rewriteLinks(src, 'docs/a.md', ctx()).text, src);
});

test('code fences and inline code are never rewritten', () => {
  const src = 'Use `[x](missing.md)` here.\n\n```md\n[y](also-missing.md)\n```\n';
  const { text, unresolved } = rewriteLinks(src, 'docs/a.md', ctx());
  assert.equal(text, src);
  assert.deepEqual(unresolved, []);
});

test('a link to nothing is reported, not silently kept', () => {
  const { unresolved } = rewriteLinks('[x](nope.md)', 'docs/a.md', ctx());
  assert.deepEqual(unresolved, ['docs/a.md: nope.md']);
});

test('images and links to files copied into the site get site paths', () => {
  const opts = { ...ctx({}, { 'docs/img/map.svg': 'file' }), assetFor: (p) => (p === 'docs/img/map.svg' ? 'img/map.svg' : null) };
  const { text, unresolved } = rewriteLinks('![map](img/map.svg) and [source](img/map.svg)', 'docs/HOW-IT-WORKS.md', opts);
  assert.equal(text, '![map](/sdlc-foundry/img/map.svg) and [source](/sdlc-foundry/img/map.svg)');
  assert.deepEqual(unresolved, []);
});

test('wiki links link to known pages and fall back to plain text', () => {
  const out = convertWikiLinks('See [[ARCHITECTURE]] and [[Unknown]].', (n) => (n === 'ARCHITECTURE' ? '/sdlc-foundry/guides/architecture/' : null));
  assert.equal(out, 'See [ARCHITECTURE](/sdlc-foundry/guides/architecture/) and Unknown.');
});

test('front matter quotes titles safely and the first heading is stripped', () => {
  assert.equal(firstHeading('intro\n# ADR-1: "Quoted": title\n'), 'ADR-1: "Quoted": title');
  assert.equal(stripFirstHeading('# Title\n\nBody'), 'Body');
  const fm = withFrontMatter('Body', { title: 'A: "b"', description: 'd', order: 3, editUrl: false });
  assert.match(fm, /^---\ntitle: "A: \\"b\\""\ndescription: "d"\nsidebar:\n {2}order: 3\neditUrl: false\n---\nBody$/);
});

test('command descriptions split into summary and usage', () => {
  assert.deepEqual(splitDescription('Does a thing. Usage: /x:y <a>'), { summary: 'Does a thing.', usage: '/x:y <a>' });
  assert.deepEqual(splitDescription('No usage here'), { summary: 'No usage here', usage: '' });
});
