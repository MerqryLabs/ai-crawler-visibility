import importlib.util
import io
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_visibility.py"
SPEC = importlib.util.spec_from_file_location("check_visibility", MODULE_PATH)
check_visibility = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_visibility)


def public_dns_result(host="93.184.216.34"):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, 0))]


class URLValidationTests(unittest.TestCase):
    def test_rejects_non_http_and_private_hosts(self):
        with self.assertRaisesRegex(ValueError, "http:// and https://"):
            check_visibility.validate_http_url("file:///etc/passwd")

        with self.assertRaisesRegex(ValueError, "public address"):
            check_visibility.validate_http_url("http://127.0.0.1/admin")

        with self.assertRaisesRegex(ValueError, "public address"):
            check_visibility.validate_http_url("http://localhost/admin")

        with patch.object(check_visibility.socket, "getaddrinfo", return_value=public_dns_result("10.0.0.5")):
            with self.assertRaisesRegex(ValueError, "public addresses"):
                check_visibility.validate_http_url("https://example.com/")

    def test_accepts_public_hosts_and_enforces_sitemap_same_origin(self):
        with patch.object(check_visibility.socket, "getaddrinfo", return_value=public_dns_result()):
            url = check_visibility.validate_http_url(
                "https://example.com/page",
                same_origin_as="https://example.com/sitemap.xml",
            )
        self.assertEqual(url, "https://example.com/page")

        with self.assertRaisesRegex(ValueError, "same origin"):
            check_visibility.validate_http_url(
                "https://evil.example/page",
                same_origin_as="https://example.com/sitemap.xml",
            )

    def test_redirects_are_revalidated(self):
        req = check_visibility.urllib.request.Request("https://example.com/sitemap.xml")
        handler = check_visibility.SafeRedirectHandler(same_origin_as="https://example.com/sitemap.xml")

        with self.assertRaisesRegex(ValueError, "same origin"):
            handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/page")

        public_handler = check_visibility.SafeRedirectHandler()
        with self.assertRaisesRegex(ValueError, "public address"):
            public_handler.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1/admin")


class BoundedParsingTests(unittest.TestCase):
    def test_read_limited_rejects_oversized_responses(self):
        resp = io.BytesIO(b"abcdef")
        with self.assertRaisesRegex(ValueError, "exceeded 5 bytes"):
            check_visibility._read_limited(resp, 5)

    def test_jsonld_blocks_are_capped(self):
        parser = check_visibility.PageParser(max_jsonld_chars=8)
        parser.feed('<script type="application/ld+json">{"x":"' + ("a" * 100) + '"}</script>')

        self.assertEqual(parser.jsonld_oversized, 1)
        self.assertEqual(parser.jsonld_blocks, [])


class SitemapTests(unittest.TestCase):
    def test_sitemap_urls_are_validated_and_limited(self):
        xml = """
        <urlset>
          <url><loc>https://example.com/a</loc></url>
          <url><loc>https://evil.example/b</loc></url>
          <url><loc>https://example.com/c</loc></url>
        </urlset>
        """

        with patch.object(check_visibility, "fetch", return_value=(xml, 200)):
            with patch.object(check_visibility.socket, "getaddrinfo", return_value=public_dns_result()):
                with patch.object(sys, "stderr", new=io.StringIO()) as stderr:
                    urls = check_visibility.urls_from_sitemap(
                        "https://example.com/sitemap.xml",
                        limit=2,
                    )

        self.assertEqual(urls, ["https://example.com/a", "https://example.com/c"])
        self.assertIn("Skipping unsafe sitemap URL", stderr.getvalue())


class AnalyzeTests(unittest.TestCase):
    def test_sitemap_origin_is_reused_for_page_fetches(self):
        html = """
        <html>
          <head>
            <title>Visible</title>
            <meta name="description" content="desc">
            <link rel="canonical" href="https://example.com/a">
            <script type="application/ld+json">{{"@context":"https://schema.org"}}</script>
          </head>
          <body>
            <a href="/one">one</a><a href="/two">two</a><a href="/three">three</a>
            {body}
          </body>
        </html>
        """.format(body="word " * 130)

        with patch.object(check_visibility, "fetch", side_effect=[(html, 200), (html, 200)]) as fetch:
            check_visibility.analyze(
                "https://example.com/a",
                same_origin_as="https://example.com/sitemap.xml",
            )

        self.assertEqual(
            fetch.call_args_list[0].kwargs["same_origin_as"],
            "https://example.com/sitemap.xml",
        )
        self.assertEqual(
            fetch.call_args_list[1].kwargs["same_origin_as"],
            "https://example.com/sitemap.xml",
        )


class OutputEscapingTests(unittest.TestCase):
    def test_terminal_controls_are_escaped(self):
        text = check_visibility.safe_terminal_text("https://example.com/\x1b[31m\nnext")
        self.assertEqual(text, "https://example.com/\\x1b[31m\\nnext")


if __name__ == "__main__":
    unittest.main()
