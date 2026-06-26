---
name: ai-crawler-visibility
description: Diagnose whether a website's content is visible to AI crawlers (ClaudeBot, GPTBot, PerplexityBot, Bytespider, Meta-ExternalAgent) that do NOT execute JavaScript, and prescribe framework-specific fixes. Use this skill whenever the user asks why their site isn't showing up in ChatGPT / Claude / Perplexity / AI search, mentions an AI crawler or AEO/GEO, suspects their single-page app (SPA), React/Vite/Vue/Svelte site, or "vibe-coded" site is invisible to AI, asks whether their content is in the raw HTML, or reports zero GPTBot/AI traffic — even if they don't use the exact words "AI crawler."
---

# AI Crawler Visibility

## Why this matters

AI assistants increasingly send people to websites — but the crawlers that feed them (ClaudeBot, GPTBot, PerplexityBot, Bytespider, Meta-ExternalAgent) **do not run JavaScript**. They read only the raw HTML the server returns. Google's renderer has handled JavaScript for years, so a client-rendered site can rank fine on Google yet be completely invisible in ChatGPT Search and Perplexity. The symptom is "we get Google traffic but nothing from AI," or for a brand-new vibe-coded SPA, "we're nowhere in AI answers."

The root cause is almost always the same: the content, meta tags, and JSON-LD structured data exist only after JavaScript runs, so they never reach the crawler. This skill detects that gap and tells the user exactly how to close it.

## What this skill does

It fetches the user's page(s) the same way a non-JS crawler does — raw HTML, no browser — and reports, per page, whether real content and key signals are present. Then it prescribes a concrete, framework-specific fix. It diagnoses and prescribes; it does not write marketing content, do keyword research, or chase backlinks.

## Workflow

Follow these steps in order.

### 1. Get the URL(s) to check

Ask the user for the live, deployed URL if you don't have it. Important: check the **production** URL, not `localhost` — local dev servers don't reflect how the deployed site is served. If the user has a sitemap, prefer it to sample several routes at once.

### 2. Run the analyzer

Run the bundled script. It needs no third-party packages.

Run the script using the `${CLAUDE_SKILL_DIR}` variable so the path resolves no matter which directory the session is working in.

Single page:
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/check_visibility.py" https://thesite.com
```

Several specific pages:
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/check_visibility.py" https://thesite.com https://thesite.com/pricing https://thesite.com/blog/post
```

Sample from a sitemap (checks up to --limit pages):
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/check_visibility.py" --sitemap https://thesite.com/sitemap.xml --limit 10
```

Add `--json` if you want to process the results programmatically.

### 3. Interpret the verdict

Each page returns one of:
- **VISIBLE** — real content is in the raw HTML. The crawler can read it.
- **PARTIAL** — only a fraction of the content is in raw HTML; the main body is JS-rendered.
- **INVISIBLE** — the crawler gets an empty shell (e.g. `<div id="root"></div>`). Nothing useful is there.

Also note: `dynamic_rendering_detected` means the server already serves bots a prerendered version — good, but confirm it covers all routes and isn't stale.

### 4. Prescribe the fix

For any PARTIAL or INVISIBLE page, read `${CLAUDE_SKILL_DIR}/references/fix-recipes.md` and give the user the recipe that matches their stack (React+Vite SPA, Vue, plain SPA, Next.js, etc.). Be specific: name the exact tool or config change and the one-line way to verify it worked. Do not give a generic "consider SSR" — give the concrete steps for their framework.

### 5. Report

ALWAYS structure the final answer with this template:

```
# AI Crawler Visibility Report

## Verdict
[One line per page: URL — VERDICT]

## What the crawler actually sees
[Per problem page: visible word count, and which of title / meta description / canonical / Open Graph / JSON-LD / crawlable links are missing from raw HTML]

## Fixes (highest impact first)
[Concrete, framework-specific steps from fix-recipes.md, each with how to verify]

## How to confirm the fix
[The exact check: re-run this skill, or "View Page Source (not Inspect) and confirm your headline text and JSON-LD appear in the raw HTML"]
```

## Examples

**Example 1**
User: "My React site ranks on Google but we get zero traffic from ChatGPT. Why?"
Action: Run the analyzer on their URL. If it returns INVISIBLE with an empty `#root`, explain that ClaudeBot/GPTBot don't run JS so they see an empty page, then give the React+Vite prerendering recipe.

**Example 2**
User: "Is my new site visible to AI search engines?"
Action: Run the analyzer (sitemap if available). Report verdict per page and fix anything PARTIAL/INVISIBLE.

**Example 3**
User: "I added JSON-LD but rich results still aren't showing."
Action: Run the analyzer. If `jsonld_blocks_in_raw_html` is 0, the JSON-LD is being injected by JS after load — crawlers that don't render never see it. Recipe: move JSON-LD into the server/build-time HTML.

## Key facts to keep straight

- The User-Agent is not what makes a page invisible — not executing JavaScript is. (The script still sends a real bot UA as a second request to detect server-side prerendering.)
- JSON-LD injected by JavaScript is invisible to non-rendering crawlers. It must be in the raw HTML.
- Hydration is fine: it attaches handlers to already-rendered HTML, so the content is already there. Pure client-side rendering (CSR) is the problem.
- "View Page Source" shows raw HTML (what the crawler sees). "Inspect" shows the rendered DOM (what it does NOT see). Always tell users to use View Page Source to verify.
