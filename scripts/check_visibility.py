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
import ipaddress
import json
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

# Real AI-crawler User-Agent strings (as observed mid-2026). The User-Agent is
# NOT what makes a page invisible — not executing JS is. But sending a known bot
# UA reveals whether a server is selectively prerendering for bots.
AI_BOT_UA = "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)"
HUMAN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

MOUNT_NODE_IDS = {"root", "app", "__next", "__nuxt", "svelte"}
SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "head"}
ALLOWED_URL_SCHEMES = {"http", "https"}
DEFAULT_TIMEOUT = 20
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_SITEMAP_BYTES = 2 * 1024 * 1024
MAX_JSONLD_CHARS = 1 * 1024 * 1024


class PageParser(HTMLParser):
    """Pulls out everything an AI crawler would (or wouldn't) find in raw HTML."""

    def __init__(self, max_jsonld_chars=MAX_JSONLD_CHARS):
        super().__init__(convert_charrefs=True)
        self._max_jsonld_chars = max_jsonld_chars
        self.title_parts = []
        self._in_title = False
        self.meta_description = None
        self.canonical = None
        self.og_tags = {}
        self.twitter_tags = {}
        self.jsonld_blocks = []
        self._in_jsonld = False
        self._jsonld_buf = []
        self._jsonld_chars = 0
        self._jsonld_too_large = False
        self.jsonld_oversized = 0
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
                self._jsonld_chars = 0
                self._jsonld_too_large = False
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
            if self._jsonld_too_large:
                self.jsonld_oversized += 1
            else:
                block = "".join(self._jsonld_buf).strip()
                if block:
                    self.jsonld_blocks.append(block)
            self._jsonld_buf = []
            self._jsonld_chars = 0
            self._jsonld_too_large = False
        # Close the most recent mount node and check if it gained any text.
        if tag == "div" and self._mount_stack:
            node_id, text_at_open = self._mount_stack.pop()
            if self._text_len - text_at_open < 10:
                self.empty_mount_nodes.append(node_id)

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        if self._in_jsonld:
            if self._jsonld_chars < self._max_jsonld_chars:
                remaining = self._max_jsonld_chars - self._jsonld_chars
                self._jsonld_buf.append(data[:remaining])
            self._jsonld_chars += len(data)
            if self._jsonld_chars > self._max_jsonld_chars:
                self._jsonld_too_large = True
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


def _default_port(scheme):
    return 443 if scheme == "https" else 80


def _origin(parsed):
    return (
        parsed.scheme.lower(),
        (parsed.hostname or "").lower().rstrip("."),
        parsed.port or _default_port(parsed.scheme.lower()),
    )


def _is_public_ip(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_global and not ip.is_multicast


def _parse_ip(address):
    try:
        return ipaddress.ip_address(address)
    except ValueError:
        return None


def _ensure_public_hostname(hostname):
    host = (hostname or "").strip().rstrip(".").lower()
    if not host:
        raise ValueError("URL must include a host")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("URL host must resolve to a public address")

    ip = _parse_ip(host)
    if ip is not None:
        if _is_public_ip(host):
            return
        raise ValueError("URL host must resolve to a public address")

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve URL host: {host}") from e
    if not infos:
        raise ValueError(f"Could not resolve URL host: {host}")

    for info in infos:
        if not _is_public_ip(info[4][0]):
            raise ValueError("URL host must resolve only to public addresses")


def validate_http_url(url, same_origin_as=None):
    value = (url or "").strip()
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
        raise ValueError("Only http:// and https:// URLs are supported")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("URL must include a host")
    if parsed.username or parsed.password:
        raise ValueError("URLs with credentials are not supported")

    try:
        current_origin = _origin(parsed)
    except ValueError as e:
        raise ValueError("URL has an invalid port") from e

    if same_origin_as:
        base = urllib.parse.urlparse(same_origin_as)
        try:
            base_origin = _origin(base)
        except ValueError as e:
            raise ValueError("Base URL has an invalid port") from e
        if current_origin != base_origin:
            raise ValueError("Sitemap URL must stay on the same origin")

    _ensure_public_hostname(parsed.hostname)
    return value


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, same_origin_as=None):
        self.same_origin_as = same_origin_as

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        validate_http_url(target, same_origin_as=self.same_origin_as)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _read_limited(resp, max_bytes):
    raw = resp.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"Response exceeded {max_bytes} bytes")
    return raw


def fetch(url, user_agent, timeout=DEFAULT_TIMEOUT, max_bytes=MAX_RESPONSE_BYTES, same_origin_as=None):
    safe_url = validate_http_url(url, same_origin_as=same_origin_as)
    req = urllib.request.Request(safe_url, headers={"User-Agent": user_agent})
    opener = urllib.request.build_opener(SafeRedirectHandler(same_origin_as=same_origin_as))
    with opener.open(req, timeout=timeout) as resp:
        raw = _read_limited(resp, max_bytes)
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace"), getattr(resp, "status", resp.getcode())


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


def analyze(url, same_origin_as=None):
    result = {"url": url, "error": None}
    try:
        human_html, status = fetch(url, HUMAN_UA, same_origin_as=same_origin_as)
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
        bot_html, _ = fetch(url, AI_BOT_UA, same_origin_as=same_origin_as)
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
        "jsonld_oversized": p.jsonld_oversized,
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
    if r.get("jsonld_oversized", 0) > 0:
        out.append(f"{r['jsonld_oversized']} JSON-LD block(s) exceed the parser size cap")
    if r.get("crawlable_links", 0) < 3:
        out.append("Few/no real <a href> links — JS-router links aren't followed by crawlers")
    return out


def safe_terminal_text(value):
    out = []
    for ch in str(value):
        code = ord(ch)
        if ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif code < 32 or code == 127 or 0x80 <= code <= 0x9F:
            out.append(f"\\x{code:02x}" if code <= 0xFF else f"\\u{code:04x}")
        else:
            out.append(ch)
    return "".join(out)


def print_report(results):
    icon = {"VISIBLE": "[OK]", "PARTIAL": "[WARN]", "INVISIBLE": "[FAIL]", None: "[ERR]"}
    for r in results:
        print("=" * 64)
        print(f"URL: {safe_terminal_text(r['url'])}")
        if r.get("error"):
            print(f"  {icon[None]} {safe_terminal_text(r['error'])}")
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
                print(f"    - {safe_terminal_text(m)}")
        else:
            print("  All key signals (title, description, canonical, OG, JSON-LD) present.")
    print("=" * 64)
    bad = [r for r in results if r.get("verdict") in ("INVISIBLE", "PARTIAL")]
    if bad:
        print(f"{len(bad)} of {len(results)} page(s) are not fully visible to AI crawlers.")
        print("See references/fix-recipes.md for framework-specific fixes.")
    else:
        print("All checked pages are visible to AI crawlers.")


def urls_from_sitemap(sitemap_url, limit=None):
    safe_sitemap_url = validate_http_url(sitemap_url)
    xml, _ = fetch(safe_sitemap_url, HUMAN_UA, max_bytes=MAX_SITEMAP_BYTES)
    urls = []
    for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml):
        if limit is not None and len(urls) >= limit:
            break
        try:
            urls.append(validate_http_url(loc, same_origin_as=safe_sitemap_url))
        except ValueError as e:
            print(
                f"Skipping unsafe sitemap URL: {safe_terminal_text(loc)} ({safe_terminal_text(e)})",
                file=sys.stderr,
            )
    return urls


def main():
    ap = argparse.ArgumentParser(description="See your site the way an AI crawler sees it.")
    ap.add_argument("urls", nargs="*", help="One or more page URLs to check.")
    ap.add_argument("--sitemap", help="Pull URLs from this sitemap.xml.")
    ap.add_argument("--limit", type=int, default=10, help="Max URLs to check from a sitemap.")
    ap.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    args = ap.parse_args()

    url_jobs = [(url, None) for url in args.urls]
    if args.limit < 1:
        ap.error("--limit must be at least 1")
    if args.sitemap:
        try:
            safe_sitemap_url = validate_http_url(args.sitemap)
            url_jobs += [
                (url, safe_sitemap_url)
                for url in urls_from_sitemap(safe_sitemap_url, limit=args.limit)
            ]
        except Exception as e:
            print(f"Could not read sitemap: {safe_terminal_text(e)}", file=sys.stderr)
    if not url_jobs:
        ap.error("Provide at least one URL or a --sitemap.")

    results = [analyze(url, same_origin_as=same_origin_as) for url, same_origin_as in url_jobs]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_report(results)

    # Non-zero exit if anything is not fully visible (useful in CI).
    if any(r.get("verdict") in ("INVISIBLE", "PARTIAL") or r.get("error") for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
