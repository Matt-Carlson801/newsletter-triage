"""Offline checks for Stage 1. They use a made-up email, never your inbox.

Run from the project root with:  python -m unittest discover tests
"""

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Let the tests import the modules that live in src/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fetch import parse_message  # noqa: E402
from links import Link, extract_links, filter_links, find_web_version  # noqa: E402
from main import append_to_log  # noqa: E402

FAKE_EMAIL = b"""From: Example Weekly <hello@example.com>
Subject: Issue 42: Fake News
Date: Mon, 09 Nov 2026 12:00:00 +0000
List-Unsubscribe: <https://example.com/unsub>
Content-Type: text/plain; charset=utf-8

Read the full story at https://example.com/story.
Also see https://example.com/other, and https://example.com/story.
"""


WEB_EMAIL = b"""From: Example Weekly <hello@example.com>
Subject: Issue 43
Date: Mon, 09 Nov 2026 12:00:00 +0000
Message-ID: <abc123@mail.example.com>
Content-Type: text/html; charset=utf-8

<a href="https://example.com/unsub">Unsubscribe</a>
<a href="https://example.com/v/9">View in browser</a>
<a href="https://example.com/story">A story</a>
"""


class WebVersionTests(unittest.TestCase):
    def test_anchor_text_finds_web_version_and_message_id(self) -> None:
        item = parse_message(WEB_EMAIL)
        self.assertEqual(item.web_url, "https://example.com/v/9")
        self.assertEqual(item.message_id, "<abc123@mail.example.com>")

    def test_phrases_and_url_words(self) -> None:
        for text in ("View Online", "read online", "Web version", "View this email in your browser"):
            self.assertEqual(find_web_version([Link(text, "https://e.com/x")]), "https://e.com/x", text)
        self.assertEqual(find_web_version([Link("", "https://e.com/web-version/3")]), "https://e.com/web-version/3")

    def test_none_when_absent_or_not_http_or_unsubscribe(self) -> None:
        self.assertIsNone(find_web_version([Link("A story", "https://e.com/s")]))
        self.assertIsNone(find_web_version([Link("View online", "mailto:x@e.com")]))
        self.assertIsNone(find_web_version([Link("Unsubscribe", "https://e.com/unsubscribe/web-version")]))

    def test_web_version_link_is_not_offered_as_a_story(self) -> None:
        links = [Link("View in browser", "https://e.com/v"), Link("A story", "https://e.com/s")]
        self.assertEqual([l.url for l in filter_links(links)], ["https://e.com/s"])

    def test_missing_message_id_is_none(self) -> None:
        self.assertIsNone(parse_message(FAKE_EMAIL).message_id)
        self.assertIsNone(parse_message(FAKE_EMAIL).web_url)


class ParseMessageTests(unittest.TestCase):
    def test_fields_are_extracted(self) -> None:
        item = parse_message(FAKE_EMAIL)
        self.assertEqual(item.subject, "Issue 42: Fake News")
        self.assertIn("hello@example.com", item.sender)
        self.assertEqual(item.date, datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(item.unsubscribe, "<https://example.com/unsub>")

    def test_links_are_cleaned_and_deduplicated(self) -> None:
        item = parse_message(FAKE_EMAIL)
        self.assertEqual([link.url for link in item.links],
                         ["https://example.com/story", "https://example.com/other"])

    def test_missing_unsubscribe_header_is_none(self) -> None:
        raw = FAKE_EMAIL.replace(b"List-Unsubscribe: <https://example.com/unsub>\n", b"")
        self.assertIsNone(parse_message(raw).unsubscribe)

    def test_extract_links_searches_all_texts(self) -> None:
        links = extract_links("a https://a.com", '<a href="https://b.com">x</a>')
        self.assertEqual([link.url for link in links], ["https://b.com", "https://a.com"])

    def test_link_text_is_kept_and_images_are_ignored(self) -> None:
        html = ('<a href="https://a.com/p">Big  <b>news</b></a>'
                '<img src="https://a.com/pixel.gif"><a href="mailto:x@y.com">mail</a>')
        self.assertEqual(extract_links("", html), [Link("Big news", "https://a.com/p")])

    def test_text_is_preferred_when_url_appears_twice(self) -> None:
        links = extract_links("see https://a.com/p", '<a href="https://a.com/p">Story</a>')
        self.assertEqual(links, [Link("Story", "https://a.com/p")])


class LogTests(unittest.TestCase):
    def test_log_appends_once_and_skips_duplicates(self) -> None:
        item = parse_message(FAKE_EMAIL)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data" / "log.csv"
            self.assertEqual(append_to_log([item], path), 1)
            self.assertEqual(append_to_log([item], path), 0)  # same row again
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)  # header + one row


if __name__ == "__main__":
    unittest.main()
