# Fix Recipes — Making Content Visible to AI Crawlers

Load this when a page comes back PARTIAL or INVISIBLE. Pick the recipe matching the user's stack. The goal is always the same: get real content + meta tags + JSON-LD into the **raw HTML** the server returns, before any JavaScript runs.

## Table of contents
1. Decide the right strategy
2. React + Vite SPA (most common vibe-coded case)
3. Plain React (Create React App / custom SPA)
4. Vue / Nuxt SPA
5. Svelte / SvelteKit
6. Already on Next.js / Remix / Astro
7. Meta tags & JSON-LD specifically
8. Crawlable links & client-side routing
9. Hosting-level prerendering (Netlify / Vercel / Cloudflare)
10. How to verify any fix

---

## 1. Decide the right strategy

Three ways to put content in raw HTML, roughly easiest to most involved:

- **Prerendering (SSG snapshots):** a build step crawls your app with a headless browser and saves a static HTML file per route. Best when content is mostly static (marketing pages, docs, blog). No framework migration.
- **Server-side rendering (SSR):** the server renders HTML per request. Best when content is dynamic/personalized.
- **Static site generation (SSG) via a framework:** the framework builds HTML at deploy time. Best for content-driven sites.

For a typical vibe-coded SPA with marketing + a few content pages, **prerendering is usually the fastest win.** Dynamic rendering (serving bots a different prerendered response) is a workaround Google deprecated as a long-term strategy — use real prerendering/SSR instead where you can.

---

## 2. React + Vite SPA

Option A — `vite-react-ssg` (recommended for content sites):
- Install `vite-react-ssg`, switch the entry to its router, and pages get pre-rendered to static HTML at build time.
- Move per-route `<title>`, meta, and JSON-LD into a head component so each route ships them in raw HTML.

Option B — `vite-plugin-prerender` / `puppeteer`-based snapshotting:
- Add a prerender step to the build that snapshots listed routes to static HTML.
- Good when you don't want to restructure routing.

Option C — graduate to a meta-framework:
- If SEO/AEO is core to the business, moving to Next.js or Remix (which render on the server by default) removes the whole class of problem. Bigger lift.

Verify: build, then open the built `dist/<route>/index.html` and confirm your headline text and JSON-LD are in the file.

---

## 3. Plain React (CRA / custom SPA)

- `react-snap`: add it as a `postbuild` step. It crawls the built app with headless Chromium and writes static HTML per route. Minimal code change.
- Ensure `react-snap` is configured to hydrate (not replace) so interactivity still works.
- For meta/JSON-LD per route, use a head manager (e.g. `react-helmet-async`) AND confirm the snapshot captures it.

Verify: after `npm run build`, inspect the generated HTML files for real content.

---

## 4. Vue / Nuxt SPA

- If on plain Vue SPA: adopt **Nuxt** in SSR or SSG mode — it's the standard path and renders content server-side.
- If you can't migrate: use a prerender plugin (e.g. `vite-ssg` for Vue) to snapshot routes.
- Set head tags with `useHead` / `@unhead` so they land in raw HTML.

Verify: View Page Source on a deployed route; content and tags should be present.

---

## 5. Svelte / SvelteKit

- **SvelteKit** prerenders by default for static routes — set `export const prerender = true` on content routes, or use `adapter-static` for a fully static build.
- Put SEO tags in `<svelte:head>` so they're server-emitted.

Verify: built output contains the route HTML with content.

---

## 6. Already on Next.js / Remix / Astro

These render HTML server-side or at build time, so content should already be visible. If a page is still PARTIAL/INVISIBLE, the usual culprits:
- The page is a client component fetching data in `useEffect` instead of on the server. Move data fetching to a server component / `getServerSideProps` / loader.
- `generateStaticParams` is missing locales/params, so pages fall back to client rendering (and can throw 500s). Include every param.
- Meta/JSON-LD set client-side. Use the framework's metadata API so it's server-emitted.

---

## 7. Meta tags & JSON-LD specifically

- Put `<title>`, meta description, canonical, and Open Graph tags in the server/build-time HTML, not written by JS after load.
- **JSON-LD must be in raw HTML.** If it's injected via a `useEffect` or a client script, non-rendering crawlers never see it. Emit it server-side or hardcode it into the page template / `index.html` for static pages.
- Validate the JSON-LD is well-formed JSON (the analyzer flags invalid blocks).

---

## 8. Crawlable links & client-side routing

- Use real anchor tags with `href` (framework `<Link>` components output real `<a href>`). Crawlers do not follow `onClick` + `router.push()` navigation with no href.
- Avoid content that only appears after scroll or interaction for anything you want indexed.
- For client-routed 404s, return a real non-200 status for missing pages (or a server 404 route) to avoid soft-404s.

---

## 9. Hosting-level prerendering

- **Netlify:** use a prerendering build plugin or an edge function to serve prerendered HTML to bot user-agents; prefer build-time prerendering over per-request hacks. Ensure `_redirects`/SPA fallback isn't masking real status codes.
- **Vercel:** prefer a framework that SSRs/SSGs (Next.js) over a pure SPA; Vercel will serve the prerendered output.
- **Cloudflare:** Pages + a static/SSR framework, or an edge worker that serves prerendered HTML to crawlers.

Note: serving bots a prerendered version while users get the SPA is "dynamic rendering" — acceptable as a bridge, but real SSR/SSG is the durable fix.

---

## 10. How to verify any fix

1. Re-run this skill against the deployed URL — the verdict should flip to VISIBLE.
2. Manual check: in Chrome, right-click → **View Page Source** (NOT Inspect). The raw HTML should contain your headline text and your JSON-LD `<script type="application/ld+json">`. If it's there in View Source, the crawler sees it.
3. Optional: fetch with a bot UA and confirm content is present, e.g. `curl -A "ClaudeBot" https://thesite.com | grep -i "<your headline>"`.
