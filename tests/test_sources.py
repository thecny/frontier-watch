"""Offline contract tests for the public-source collectors."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from frontier_watch.sources import _parse_feed, fetch_all


NOW = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)

RSS_2 = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>CNX Software</title>
<item><guid>cnx-1</guid><title>New FPGA board</title>
<link>https://example.org/cnx/fpga-board</link>
<pubDate>Wed, 23 Sep 2026 10:00:00 GMT</pubDate>
<description>&lt;p&gt;A &lt;b&gt;reconfigurable&lt;/b&gt; board.&lt;/p&gt;</description>
</item></channel></rss>"""

HACKADAY_RSS_2 = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Hackaday</title>
<item><title>Audio Spectrum Analyzer on an ESP32 Display Board</title>
<link>https://hackaday.com/2026/09/23/audio-spectrum-analyzer-on-an-esp32-display-board/</link>
<pubDate>Thu, 24 Sep 2026 05:00:19 +0000</pubDate>
<description>ESP32 audio spectrum analyzer.</description>
</item></channel></rss>"""

RSS_1 = b"""<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel rdf:about="https://example.org/hackaday"><title>Hackaday</title></channel>
<item rdf:about="https://example.org/hackaday/adc">
<title>Fast ADC project</title><link>https://example.org/hackaday/adc</link>
<dc:date>2026-09-23T11:30:00Z</dc:date>
<description>ADC &amp; signal processing</description>
</item></rdf:RDF>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>arXiv</title><entry><id>http://arxiv.org/abs/2609.12345</id>
<title>  FPGA   acceleration of  DSP </title>
<link rel="alternate" href="https://arxiv.org/abs/2609.12345" />
<published>2026-09-22T17:00:00Z</published>
<summary>  A new accelerator.  </summary></entry></feed>"""

GITHUB = json.dumps({
    "total_count": 1,
    "incomplete_results": False,
    "items": [{
        "id": 12345,
        "full_name": "engineer/open-fpga",
        "html_url": "https://github.com/engineer/open-fpga",
        "description": "Open FPGA signal processing cores",
        "created_at": "2026-09-23T06:00:00Z",
        "stargazers_count": 42,
    }],
}).encode()


class SourceTests(unittest.TestCase):
    def test_collects_atom_and_news_rss_and_github_repositories(self):
        def http_get(url, headers):
            if "rss.arxiv.org" in url:
                return ATOM
            if "cnx-software.com" in url:
                return RSS_2
            if "hackaday.com" in url:
                return HACKADAY_RSS_2
            if "api.github.com/search/repositories" in url:
                return GITHUB
            raise AssertionError(f"unexpected source: {url}")

        entries, errors = fetch_all(NOW, http_get, github_token="test-token")

        self.assertEqual(errors, [])
        self.assertEqual(len(entries), 6)
        self.assertEqual({entry.kind for entry in entries}, {"paper", "news", "project"})
        self.assertIn("Hackaday", {entry.source for entry in entries})
        paper = next(entry for entry in entries if entry.kind == "paper")
        self.assertEqual(paper.title, "FPGA acceleration of DSP")
        self.assertEqual(paper.url, "https://arxiv.org/abs/2609.12345")
        self.assertEqual(paper.published, datetime(2026, 9, 22, 17, tzinfo=timezone.utc))
        news = next(entry for entry in entries if entry.url.endswith("/fpga-board"))
        self.assertEqual(news.summary, "A reconfigurable board.")
        repo = next(entry for entry in entries if entry.kind == "project")
        self.assertEqual(repo.title, "engineer/open-fpga")
        self.assertEqual(repo.summary, "Open FPGA signal processing cores")

    def test_parses_rss_one_with_dublin_core_date(self):
        entries = _parse_feed(RSS_1, "Example", "news")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].title, "Fast ADC project")
        self.assertEqual(entries[0].published, datetime(2026, 9, 23, 11, 30, tzinfo=timezone.utc))

    def test_one_failed_source_does_not_hide_other_results_or_leak_token(self):
        def http_get(url, headers):
            if "api.github.com" in url:
                raise RuntimeError("test-token is secret")
            return RSS_2

        entries, errors = fetch_all(NOW, http_get, github_token="test-token")

        self.assertEqual(len(entries), 3)
        self.assertEqual(len(errors), 3)
        self.assertTrue(all("GitHub" in error for error in errors))
        self.assertNotIn("test-token", " ".join(errors))

    def test_missing_or_invalid_dates_are_not_treated_as_new(self):
        undated = b"""<rss><channel><item><title>Undated FPGA</title>
        <link>https://example.org/no-date</link></item>
        <item><title>Invalid FPGA date</title>
        <link>https://example.org/invalid-date</link>
        <pubDate>not a date</pubDate></item></channel></rss>"""

        def http_get(url, headers):
            if "api.github.com" in url:
                return b'{"total_count":0,"incomplete_results":false,"items":[]}'
            return undated

        entries, errors = fetch_all(NOW, http_get)

        self.assertEqual(errors, [])
        self.assertEqual(entries, [])

    def test_oversized_or_malformed_source_isolated_from_other_sources(self):
        def http_get(url, headers):
            if "rss.arxiv.org" in url:
                return b"x" * 2_000_001
            if "cnx-software.com" in url:
                return b"<rss>"
            if "api.github.com" in url:
                return b'{"total_count":0,"incomplete_results":false,"items":[]}'
            return RSS_2

        entries, errors = fetch_all(NOW, http_get)

        self.assertEqual(len(entries), 1)
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("arXiv" in error for error in errors))
        self.assertTrue(any("CNX" in error for error in errors))

    def test_github_queries_are_recent_and_authentication_stays_in_headers(self):
        seen = []

        def http_get(url, headers):
            seen.append((url, headers))
            if "api.github.com" in url:
                return b'{"total_count":0,"incomplete_results":false,"items":[]}'
            return RSS_2

        fetch_all(NOW, http_get, github_token="test-token")

        github_requests = [(url, headers) for url, headers in seen if "api.github.com" in url]
        self.assertEqual(len(github_requests), 3)
        self.assertTrue(all("created%3A%3E%3D" in url for url, _ in github_requests))
        self.assertTrue(all("test-token" not in url for url, _ in github_requests))
        self.assertTrue(all(headers.get("Authorization") == "Bearer test-token" for _, headers in github_requests))

    def test_skips_github_repositories_without_descriptions_but_keeps_rss_items(self):
        rss_without_description = b"""<rss><channel><item>
        <title>New FPGA toolchain</title>
        <link>https://example.org/toolchain</link>
        <pubDate>Wed, 23 Sep 2026 10:00:00 GMT</pubDate>
        </item></channel></rss>"""
        github_response = json.dumps({
            "total_count": 3,
            "incomplete_results": False,
            "items": [
                {
                    "id": 1, "full_name": "example/no-description",
                    "html_url": "https://github.com/example/no-description",
                    "description": None, "created_at": "2026-09-23T06:00:00Z",
                    "stargazers_count": 1,
                },
                {
                    "id": 2, "full_name": "example/blank-description",
                    "html_url": "https://github.com/example/blank-description",
                    "description": "  \n  ", "created_at": "2026-09-23T06:00:00Z",
                    "stargazers_count": 2,
                },
                {
                    "id": 3, "full_name": "example/useful-fpga",
                    "html_url": "https://github.com/example/useful-fpga",
                    "description": "Open-source FPGA timing analysis",
                    "created_at": "2026-09-23T06:00:00Z",
                    "stargazers_count": 3,
                },
            ],
        }).encode()

        def http_get(url, headers):
            return github_response if "api.github.com" in url else rss_without_description

        entries, errors = fetch_all(NOW, http_get)

        self.assertEqual(errors, [])
        self.assertEqual([entry.title for entry in entries if entry.kind == "project"], ["example/useful-fpga"] * 3)
        self.assertEqual(len([entry for entry in entries if entry.kind != "project" and not entry.summary]), 3)


if __name__ == "__main__":
    unittest.main()
