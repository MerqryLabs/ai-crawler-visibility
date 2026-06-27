#!/usr/bin/env python3
"""
check_visibility.py — See your site the way an AI crawler sees it.

AI crawlers (ClaudeBot, GPTBot, PerplexityBot, Bytespider, Meta-ExternalAgent)
do NOT execute JavaScript. They read the RAW HTML your server returns and
nothing more. This script fetches that raw HTML — no browser, no JS execution,
exactly what the crawler gets — and reports whether your real content, meta
tags, and JSON-LD structured data are actually present.

It also fetches a second time using a real AI-crawler User-Agent. If the two
responses differ, the site is doing bot-specific prerendering (dynamic
rendering), which is worth knowing.

Usage:
    python check_visibility.py https://example.com
    python check_visibility.py https://example.com https://example.com/pricing
    python check_visibility.py --sitemap https://example.com/sitemap.xml
    python check_visibility.py https://example.com --json

No third-party dependencies — standard library only.
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from html.parser import HTMLParser

# Real AI-crawler User-Agent strings (as observed mid-2026). The User-Agent is
# NOT what makes a page invisible — not executing JS is. But sending a known bot
# UA reveals whether a server is selectively prerendering for bots.
AI_BOT_UA = "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)"
HUMAN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

MOUNT_NODE_IDS = {"root", "app", "__next", "__nuxt", "svelte"}
SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "head"}


class PageParser(HTMLParser):
    """Pulls out everything an AI crawler would (or wouldn't) find in raw HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts = []
        self._in_title = False
        self.meta_description = None
        self.canonical = None
        self.og_tags = {}
        self.twitter_tags = {}
        self.jsonld_blocks = []
        self._in_jsonld = False
        self._jsonld_buf = []
        self.script_srcs = []
        self.link_count = 0
        self.empty_mount_nodes = []
        self._mount_stack = []  # (id, text_len_at_open)
        self._skip_depth = 0
        self._text_len = 0
        self._visible_words = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in SKIP_TEXT_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or "").lower()
            prop = (a.get("property") or "").lower()
            content = a.get("content", "")
            if name == "description":
                self.meta_description = content
            if prop.startswith("og:"):
                self.og_tags[prop] = content
            if name.startswith("twitter:"):
                self.twitter_tags[name] = content
        elif tag == "link":
            if (a.get("rel") or "").lower() == "canonical":
                self.canonical = a.get("href")
        elif tag == "script":
            stype = (a.get("type") or "").lower()
            if stype == "application/ld+json":
                self._in_jsonld = True
                self._jsonld_buf = []
            if a.get("src"):
                self.script_srcs.append(a["src"])
        elif tag == "a":
            if a.get("href"):
                self.link_count += 1
        # Track mount nodes (#root, #app, #__next) to detect empty SPA shells.
        node_id = (a.get("id") or "").lower()
        if node_id in MOUNT_NODE_IDS:
            self._mount_stack.append((node_id, self._text_len))

    def handle_endtag(self, tag):
        if tag in SKIP_TEXT_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            block = "".join(self._jsonld_buf).strip()
            if block:
                self.jsonld_blocks.append(block)
        # Close the most recent mount node and check if it gained any text.
        if tag == "div" and self._mount_stack:
            node_id, text_at_open = self._mount_stack.pop()
            if self._text_len - text_at_open < 10:
                self.empty_mount_nodes.append(node_id)

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        if self._in_jsonld:
            self._jsonld_buf.append(data)
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._text_len += len(stripped)
                self._visible_words += len(stripped.split())

    @property
    def title(self):
        return "".join(self.title_parts).strip()

    @property
    def visible_words(self):
        return self._visible_words


def fetch(url, user_agent, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace"), resp.status


def jsonld_valid(blocks):
    """Return (count_valid, count_invalid) for JSON-LD blocks found in raw HTML."""
    valid = invalid = 0
    for b in blocks:
        try:
            json.loads(b)
            valid += 1
        except Exception:
            invalid += 1
    return valid, invalid


def analyze(url):
    result = {"url": url, "error": None}
    try:
        human_html, status = fetch(url, HUMAN_UA)
    except urllib.error.HTTPError as e:
        result["error"] = f"HTTP {e.code} {e.reason}"
        return result
    except Exception as e:
        result["error"] = f"Could not fetch: {e}"
        return result

    p = PageParser()
    p.feed(human_html)

    valid_ld, invalid_ld = jsonld_valid(p.jsonld_blocks)

    # Bot-UA fetch to detect dynamic rendering (server serving bots different HTML).
    dynamic_rendering = False
    try:
        bot_html, _ = fetch(url, AI_BOT_UA)
        # Compare visible word counts; a large gap means bot-specific prerendering.
        bp = PageParser()
        bp.feed(bot_html)
        if bp.visible_words - p.visible_words > 100:
            dynamic_rendering = True
            # Re-base the verdict on what the bot actually receives.
            p = bp
            valid_ld, invalid_ld = jsonld_valid(p.jsonld_blocks)
    except Exception:
        pass

    well_marked = bool(p.title) and bool(p.meta_description) and bool(p.jsonld_blocks)
    has_content = p.visible_words >= 120
    shell = bool(p.empty_mount_nodes) and p.visible_words < 50

    # Verdict logic, AI-crawler-first. A page is VISIBLE if it carries real
    # content in raw HTML, OR is fully marked up with a solid amount of text.
    if shell or (p.visible_words < 40 and not p.jsonld_blocks):
        verdict = "INVISIBLE"
        summary = "An AI crawler sees an empty shell. Your content is rendered by JavaScript and is not in the raw HTML."
    elif has_content or (well_marked and p.visible_words >= 60):
        verdict = "VISIBLE"
        summary = "Your main content is present in the raw HTML an AI crawler reads."
    else:
        verdict = "PARTIAL"
        summary = "An AI crawler sees only a fraction of your content. Important text is likely JS-rendered."

    result.update({
        "verdict": verdict,
        "summary": summary,
        "status": status,
        "visible_words": p.visible_words,
        "title": p.title or None,
        "has_title": bool(p.title),
        "has_meta_description": bool(p.meta_description),
        "has_canonical": bool(p.canonical),
        "og_tag_count": len(p.og_tags),
        "jsonld_blocks_in_raw_html": len(p.jsonld_blocks),
        "jsonld_valid": valid_ld,
        "jsonld_invalid": invalid_ld,
        "crawlable_links": p.link_count,
        "empty_mount_nodes": p.empty_mount_nodes,
        "external_scripts": len(p.script_srcs),
        "dynamic_rendering_detected": dynamic_rendering,
    })
    return result


def missing_signals(r):
    out = []
    if not r.get("has_title"):
        out.append("No <title> in raw HTML")
    if not r.get("has_meta_description"):
        out.append("No meta description in raw HTML")
    if not r.get("has_canonical"):
        out.append("No canonical link in raw HTML")
    if r.get("og_tag_count", 0) == 0:
        out.append("No Open Graph (og:) tags — weak link previews / AI cards")
    if r.get("jsonld_blocks_in_raw_html", 0) == 0:
        out.append("No JSON-LD structured data in raw HTML")
    if r.get("jsonld_invalid", 0) > 0:
        out.append(f"{r['jsonld_invalid']} JSON-LD block(s) are invalid JSON")
    if r.get("crawlable_links", 0) < 3:
        out.append("Few/no real <a href> links — JS-router links aren't followed by crawlers")
    return out


def print_report(results):
    icon = {"VISIBLE": "[OK]", "PARTIAL": "[WARN]", "INVISIBLE": "[FAIL]", None: "[ERR]"}
    for r in results:
        print("=" * 64)
        print(f"URL: {r['url']}")
        if r.get("error"):
            print(f"  {icon[None]} {r['error']}")
            continue
        v = r["verdict"]
        print(f"  {icon[v]} {v} — {r['summary']}")
        print(f"  Visible words in raw HTML: {r['visible_words']}")
        if r["dynamic_rendering_detected"]:
            print("  NOTE: server appears to prerender for bots (dynamic rendering detected).")
        miss = missing_signals(r)
        if miss:
            print("  Missing for AI crawlers:")
            for m in miss:
                print(f"    - {m}")
        else:
            print("  All key signals (title, description, canonical, OG, JSON-LD) present.")
    print("=" * 64)
    bad = [r for r in results if r.get("verdict") in ("INVISIBLE", "PARTIAL")]
    if bad:
        print(f"{len(bad)} of {len(results)} page(s) are not fully visible to AI crawlers.")
        print("See references/fix-recipes.md for framework-specific fixes.")
    else:
        print("All checked pages are visible to AI crawlers.")


def urls_from_sitemap(sitemap_url):
    xml, _ = fetch(sitemap_url, HUMAN_UA)
    return re.findall(r"<loc>\s*(.*?)\s*</loc>", xml)


def main():
    ap = argparse.ArgumentParser(description="See your site the way an AI crawler sees it.")
    ap.add_argument("urls", nargs="*", help="One or more page URLs to check.")
    ap.add_argument("--sitemap", help="Pull URLs from this sitemap.xml.")
    ap.add_argument("--limit", type=int, default=10, help="Max URLs to check from a sitemap.")
    ap.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.sitemap:
        try:
            urls += urls_from_sitemap(args.sitemap)[: args.limit]
        except Exception as e:
            print(f"Could not read sitemap: {e}", file=sys.stderr)
    if not urls:
        ap.error("Provide at least one URL or a --sitemap.")

    results = [analyze(u) for u in urls]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_report(results)

    # Non-zero exit if anything is not fully visible (useful in CI).
    if any(r.get("verdict") in ("INVISIBLE", "PARTIAL") or r.get("error") for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
