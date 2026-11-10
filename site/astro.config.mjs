import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import starlightLinksValidator from 'starlight-links-validator';

const description =
  'An agentic SDLC platform: Claude Code agents, slash commands and Copier templates that take a product from idea to Kubernetes via GitOps: secrets, Postgres, OpenTelemetry and Kyverno guard rails are one declaration each.';

export default defineConfig({
  site: 'https://ika100.github.io',
  base: '/sdlc-foundry',
  trailingSlash: 'always',
  integrations: [
    starlight({
      title: 'sdlc-foundry',
      description,
      logo: { src: './src/assets/logo.svg' },
      favicon: '/favicon.svg',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/ika100/sdlc-foundry' }],
      // fonts are bundled with the site (no font CDN), like mermaid
      customCss: ['@fontsource-variable/inter', '@fontsource-variable/jetbrains-mono', './src/styles/custom.css'],
      expressiveCode: {
        themes: ['github-dark-default', 'github-light'],
        styleOverrides: { borderRadius: '0.75rem', codeFontFamily: 'var(--sl-font-mono)', uiFontFamily: 'var(--sl-font)' },
      },
      // pages written for the site link to their source; pages copied from docs/ set editUrl: false
      editLink: { baseUrl: 'https://github.com/ika100/sdlc-foundry/edit/main/site/' },
      components: { Footer: './src/components/Footer.astro' },
      lastUpdated: false,
      pagination: true,
      head: [
        { tag: 'meta', attrs: { name: 'theme-color', content: '#4f46e5' } },
        { tag: 'meta', attrs: { property: 'og:type', content: 'website' } },
        // a picture of the docs opens full size in a new tab (they fit the column instead of scrolling sideways)
        {
          tag: 'script',
          content:
            "document.addEventListener('click',e=>{const i=e.target.closest('.sl-markdown-content img[src*=\"/img/\"], .map img');"
            + "if(i&&!i.closest('a')){window.open(i.currentSrc||i.src,'_blank','noopener');}});",
        },
        { tag: 'meta', attrs: { name: 'keywords', content: 'claude code, gitops, kubernetes, argocd, copier, devbox, platform engineering, opentelemetry, kyverno' } },
      ],
      plugins: [starlightLinksValidator({ errorOnRelativeLinks: false, errorOnInvalidHashes: false })],
      sidebar: [
        {
          label: 'Why sdlc-foundry',
          items: [
            { label: 'Vision', slug: 'vision' },
            { label: 'The problem', slug: 'problem' },
            { label: 'Client value', slug: 'value' },
            { label: 'Usage scenarios', slug: 'scenarios' },
            { label: 'Compared with others', slug: 'compare' },
          ],
        },
        { label: 'Get started', items: [{ label: 'Quickstart', slug: 'get-started' }, { label: 'Run it on your laptop', slug: 'get-started/local-cluster' }, { label: 'Watch a real run', slug: 'get-started/watch-a-run' }] },
        { label: 'Concepts', items: [{ autogenerate: { directory: 'concepts' } }] },
        { label: 'Guides', items: [{ autogenerate: { directory: 'guides' } }] },
        {
          label: 'Reference',
          items: [
            { label: 'Slash commands', slug: 'reference/commands' },
            { label: 'Shapes', slug: 'reference/shapes' },
            { label: 'Configuration', slug: 'reference/configuration' },
            { label: 'The cplat CLI', slug: 'reference/cplat' },
            { label: 'Performance measurements', slug: 'reference/performance' },
            { label: 'Measured baselines', slug: 'reference/baselines' },
            { label: 'Architecture decisions', collapsed: true, items: [{ autogenerate: { directory: 'reference/adr' } }] },
            { label: 'Changelog', slug: 'reference/changelog' },
          ],
        },
        { label: 'Community', items: [{ autogenerate: { directory: 'community' } }] },
      ],
    }),
  ],
});
