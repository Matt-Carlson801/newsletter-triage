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
from links import Link, extract_links  # noqa: E402
from main import append_to_log  # noqa: E402

FAKE_EMAIL = b"""From: Example Weekly <hello@example.com>
Subject: Issue 42: Fake News
Date: Mon, 09 Nov 2026 12:00:00 +0000
List-Unsubscribe: <https://example.com/unsub>
Content-Type: text/plain; charset=utf-8

Read the full story at https://example.com/story.
Also see https://example.com/other, and https://example.com/story.
"""


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
