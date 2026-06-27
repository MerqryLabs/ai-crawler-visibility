# AI Crawler Visibility

**A Claude Code skill that tells you whether your website is actually visible to AI search — and exactly how to fix it if it isn't.**

ChatGPT Search, Claude, and Perplexity are sending people to websites now. But the crawlers that feed them — **ClaudeBot, GPTBot, PerplexityBot, Bytespider, Meta-ExternalAgent** — *do not run JavaScript*. They read only the raw HTML your server returns.

Google's renderer has handled JavaScript for years, so a client-rendered site (React, Vite, Vue, Svelte, any SPA) can rank perfectly fine on Google and still be **completely invisible in AI answers**.

If you've ever thought *"we get Google traffic but nothing from AI"* — or you shipped a slick vibe-coded SPA and you're nowhere in ChatGPT — this is almost always why.

---

## What it does

This skill fetches your page(s) the same way a non-JS crawler does — raw HTML, no browser — and reports, per page, whether your real content and key signals (`title`, meta description, canonical, Open Graph, JSON-LD, crawlable links) are actually present.

Then it prescribes a **concrete, framework-specific fix**. Not "consider SSR" — the exact tool, config change, and one-line way to verify it worked.

Every page gets one of three verdicts:

| Verdict | What it means |
|---|---|
| ✅ **VISIBLE** | Real content is in the raw HTML. The crawler can read you. |
| ⚠️ **PARTIAL** | Only a fraction is in raw HTML; the main body is JS-rendered. |
| ❌ **INVISIBLE** | The crawler gets an empty shell (`<div id="root"></div>`). Nothing useful is there. |

It **diagnoses and prescribes**. It does not write marketing copy, do keyword research, or chase backlinks.

---

## Install

This is a [Claude Code Agent Skill](https://docs.claude.com/en/docs/claude-code/overview). Drop the folder into your skills directory and Claude Code picks it up automatically.

**Personal (available in every project):**
```bash
git clone https://github.com/MerqryLabs/ai-crawler-visibility.git \
  ~/.claude/skills/ai-crawler-visibility
```

**Project-scoped (just this repo):**
```bash
git clone https://github.com/MerqryLabs/ai-crawler-visibility.git \
  ./.claude/skills/ai-crawler-visibility
```

That's it. No npm install, no API keys, no third-party packages — the analyzer runs on plain Python 3.

> Check the official [Agent Skills docs](https://docs.claude.com/en/docs/claude-code/overview) for the canonical skills path if your setup differs.

---

## Use it

Just talk to Claude Code in natural language. The skill triggers on its own when you ask the kind of question it's built for:

- *"Why isn't my site showing up in ChatGPT?"*
- *"Is my new site visible to AI search engines?"*
- *"I added JSON-LD but rich results still aren't showing."*

You can also run the bundled analyzer directly:

```bash
# Single page
python3 scripts/check_visibility.py https://thesite.com

# Several specific pages
python3 scripts/check_visibility.py https://thesite.com https://thesite.com/pricing

# Sample from a sitemap (checks up to --limit pages)
python3 scripts/check_visibility.py --sitemap https://thesite.com/sitemap.xml --limit 10
```

Add `--json` to process results programmatically.

> ⚠️ Always check your **production** URL, not `localhost` — local dev servers don't reflect how the deployed site is served to crawlers.

---

## What the report looks like

```
# AI Crawler Visibility Report

## Verdict
https://thesite.com         — INVISIBLE
https://thesite.com/pricing — INVISIBLE

## What the crawler actually sees
/ : 0 visible words. Missing from raw HTML: meta description,
    canonical, Open Graph, JSON-LD, crawlable links.

## Fixes (highest impact first)
[Concrete, framework-specific steps — each with how to verify]

## How to confirm the fix
View Page Source (not Inspect) and confirm your headline text
and JSON-LD appear in the raw HTML.
```

---

## Got an INVISIBLE or PARTIAL verdict? Here's the fast lane.

This skill tells you *what's broken* and *what the fix is*. If you'd rather not hand-implement prerendering and static JSON-LD injection yourself, the companion **AI Crawler Fixer** pack does it for you:

- Injects static SEO + JSON-LD straight into `index.html`
- Sets up post-build prerendering so real content lands in the raw HTML
- Works through approval gates so nothing touches your codebase without your sign-off
- Re-runs the diagnosis after to prove the fix landed

👉 **[Get the AI Crawler Fixer pack →] https://novae8.gumroad.com/l/AICrawlerFixer

*Diagnosis is free and always will be. The Fixer is for when you want the problem gone today.*

---

## How it works (the short version)

- **The User-Agent isn't what makes a page invisible — not executing JavaScript is.** (The script still sends a real bot UA as a second request to detect server-side prerendering.)
- **JSON-LD injected by JavaScript is invisible** to non-rendering crawlers. It has to be in the raw HTML.
- **Hydration is fine.** It attaches handlers to already-rendered HTML, so the content's already there. Pure client-side rendering (CSR) is the problem.
- **"View Page Source"** shows raw HTML (what the crawler sees). **"Inspect"** shows the rendered DOM (what it does *not* see). Always verify with View Page Source.

---

## License

MIT — use it, fork it, ship it.

---

Built by [Novae Systems](https://getnovaesystems.com) — websites, AI automation, and SEO for local businesses.

*Novae builds. Systems flow.*
