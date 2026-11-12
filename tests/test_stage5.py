"""Offline checks for duplicate merging. A fake Gemini client replaces the real
one, so no API key, network or real email is used. Everything is made up.

Run from the project root with:  python -m unittest discover tests
"""

import json
import logging
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from google.genai import errors  # noqa: E402

import main  # noqa: E402
from digest import build_digest, merge_items, story_headlines  # noqa: E402
from fetch import Newsletter  # noqa: E402
from summarize import (  # noqa: E402
    NewsletterSummary, Story, SummarizeError, find_duplicate_groups, parse_duplicate_groups,
)
from test_stage2 import FakeClient  # noqa: E402
from test_stage4 import CI, SECRET_ERROR, run_main  # noqa: E402

WHEN = datetime(2026, 11, 10, 11, 30, tzinfo=timezone.utc)
ADDRESS = "reader@gmail.com"


def groups_reply(groups) -> str:
    return json.dumps({"groups": groups})


def newsletter(name: str, thread: str) -> Newsletter:
    return Newsletter(sender=f"{name} <hi@{name.lower()}.example.com>", subject="s", date=WHEN,
                      body="x", links=[], unsubscribe=None, thread_id=thread)


def story(title: str, url: str | None = None, category: str = "AI & Tech") -> Story:
    return Story(title, f"{title} sentence.", url, category)


# Flat story order (this is what the groups point at):
#   0 Alpha:  "Chip news"   1 Alpha: "Alpha only"
#   2 Beta:   "Chips again" 3 Beta:  "Rates"
#   4 Gamma:  "Chip story 3" 5 Gamma: "Rates too"   6 Gamma: "Gamma only"
NEWSLETTERS = [newsletter("Alpha", "a1"), newsletter("Beta", "b2"), newsletter("Gamma", "c3")]
RESULTS = [
    NewsletterSummary([story("Chip news", "https://example.com/chip-a"), story("Alpha only")]),
    NewsletterSummary([story("Chips again", "https://example.com/chip-b"),
                       story("Rates", category="Business & GTM")]),
    NewsletterSummary([story("Chip story 3"), story("Rates too", category="Business & GTM"),
                       story("Gamma only", category="Personal Growth")]),
]


class ParseGroupsTests(unittest.TestCase):
    def test_valid_groups_become_zero_based_sorted(self) -> None:
        self.assertEqual(parse_duplicate_groups(groups_reply([[3, 1], [5, 6]]), 6), [[0, 2], [4, 5]])

    def test_out_of_range_numbers_are_ignored(self) -> None:
        self.assertEqual(parse_duplicate_groups(groups_reply([[1, 2, 99, 0, -4]]), 3), [[0, 1]])

    def test_group_left_with_one_number_is_dropped(self) -> None:
        self.assertEqual(parse_duplicate_groups(groups_reply([[1, 99], [2]]), 3), [])

    def test_a_number_is_used_in_at_most_one_group(self) -> None:
        # 2 is already taken by the first group, so the second group has only 3 left and is dropped.
        self.assertEqual(parse_duplicate_groups(groups_reply([[1, 2], [2, 3]]), 3), [[0, 1]])
        # Repeats inside one group count once.
        self.assertEqual(parse_duplicate_groups(groups_reply([[1, 1]]), 3), [])

    def test_non_integers_are_ignored(self) -> None:
        self.assertEqual(parse_duplicate_groups(groups_reply([[1, "2", 2.5, True, None, 3]]), 3), [[0, 2]])

    def test_wrong_shapes_inside_groups_are_skipped(self) -> None:
        self.assertEqual(parse_duplicate_groups(groups_reply(["text", 5, [1, 2]]), 3), [[0, 1]])

    def test_bad_replies_raise(self) -> None:
        for bad in ("not json", "[]", "{}", json.dumps({"groups": "x"}), json.dumps({"groups": None})):
            with self.assertRaises(SummarizeError, msg=bad):
                parse_duplicate_groups(bad, 3)


class FindGroupsTests(unittest.TestCase):
    def test_sends_numbered_headlines_only_and_returns_groups(self) -> None:
        client = FakeClient(groups_reply([[1, 3]]))
        headlines = story_headlines(RESULTS)
        self.assertEqual(find_duplicate_groups(headlines, client), [[0, 2]])
        self.assertIn("1. Chip news: Chip news sentence.", client.sent)
        self.assertIn("7. Gamma only: Gamma only sentence.", client.sent)
        for private in ("http", "example.com", "Alpha <", "@"):
            self.assertNotIn(private, client.sent)

    def test_fewer_than_two_headlines_makes_no_call(self) -> None:
        client = FakeClient(groups_reply([]))
        self.assertEqual(find_duplicate_groups(["only one"], client), [])
        self.assertEqual(client.calls, 0)

    def test_reuses_retry_logic(self) -> None:
        busy = errors.APIError(503, {"error": {"message": "busy"}})
        client = FakeClient(groups_reply([[1, 2]]), error=busy, fail_first=2)
        with mock.patch("summarize.time.sleep") as sleep:
            self.assertEqual(find_duplicate_groups(["a", "b"], client), [[0, 1]])
        self.assertEqual(client.calls, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4])

    def test_empty_reply_raises(self) -> None:
        with self.assertRaises(SummarizeError):
            find_duplicate_groups(["a", "b"], FakeClient(""))


class FallbackTests(unittest.TestCase):
    """find_merge_groups must never raise; any failure means 'no groups'."""

    def run_it(self, client) -> list:
        with mock.patch("main.time.sleep"), mock.patch("summarize.time.sleep"):
            return main.find_merge_groups(RESULTS, client)

    def test_success(self) -> None:
        self.assertEqual(self.run_it(FakeClient(groups_reply([[1, 3, 5]]))), [[0, 2, 4]])

    def test_api_failure_gives_no_groups(self) -> None:
        self.assertEqual(self.run_it(FakeClient(error=errors.APIError(500, {"error": {"message": "x"}}))), [])

    def test_rate_limit_after_retries_gives_no_groups(self) -> None:
        self.assertEqual(self.run_it(FakeClient(error=errors.APIError(429, {"error": {"message": "x"}}))), [])

    def test_network_error_gives_no_groups(self) -> None:
        self.assertEqual(self.run_it(FakeClient(error=OSError("offline"))), [])

    def test_bad_data_gives_no_groups(self) -> None:
        self.assertEqual(self.run_it(FakeClient("this is not json")), [])

    def test_unexpected_exception_gives_no_groups(self) -> None:
        self.assertEqual(self.run_it(FakeClient(error=ValueError("weird"))), [])

    def test_missing_api_key_gives_no_groups(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(self.run_it(None), [])

    def test_digest_is_still_built_unmerged(self) -> None:
        groups = self.run_it(FakeClient("garbage"))
        digest = build_digest(NEWSLETTERS, RESULTS, WHEN, ADDRESS, groups)
        self.assertNotIn("In multiple newsletters", digest.html)
        self.assertIn("7 stories", digest.text)


class DigestMergeTests(unittest.TestCase):
    def build(self, groups):
        return build_digest(NEWSLETTERS, RESULTS, WHEN, ADDRESS, groups)

    def test_no_groups_means_no_section(self) -> None:
        digest = self.build(None)
        self.assertNotIn("In multiple newsletters", digest.html)
        self.assertIn("3 newsletters · 7 stories", digest.text)

    def test_merged_story_appears_once_with_first_headline_and_link(self) -> None:
        digest = self.build([[0, 2, 4]])
        self.assertEqual(digest.html.count("Chip news</a>"), 1)
        self.assertNotIn("Chips again", digest.html)
        self.assertNotIn("Chip story 3", digest.html)
        self.assertIn('href="https://example.com/chip-a"', digest.html)
        self.assertNotIn("chip-b", digest.html)
        self.assertIn("Chip news sentence.", digest.html)

    def test_every_source_is_linked_through_the_redirect_page(self) -> None:
        html_out = self.build([[0, 2, 4]]).html
        for name, thread in (("Alpha", "a1"), ("Beta", "b2"), ("Gamma", "c3")):
            self.assertRegex(html_out, rf'<a href="[^"]*#t={thread}&amp;a=reader@gmail\.com"[^>]*>{name}</a>')
        self.assertIn("(<a", html_out)  # sources sit in one pair of parentheses

    def test_section_at_top_with_count_and_no_repeat_under_categories(self) -> None:
        digest = self.build([[0, 2, 4], [3, 5]])
        html_out = digest.html
        self.assertIn("In multiple newsletters today (2)", html_out)
        self.assertLess(html_out.index("In multiple newsletters today"), html_out.index("AI &amp; Tech"))
        # The merged AI story left its category: only "Alpha only" remains under AI & Tech.
        self.assertIn("AI &amp; Tech (1)", html_out)
        self.assertNotIn("Business &amp; GTM", html_out)  # both Rates stories merged away
        self.assertEqual(html_out.count("Rates</"), 1)
        self.assertIn("Personal Growth (1)", html_out)
        self.assertIn("Gamma only", html_out)
        self.assertIn("Alpha only", html_out)

    def test_sorted_by_number_of_sources(self) -> None:
        digest = self.build([[3, 5], [0, 2, 4]])  # the 2-source group is listed first on purpose
        self.assertLess(digest.html.index("Chip news"), digest.html.index("Rates"))
        self.assertLess(digest.text.index("Chip news"), digest.text.index("Rates"))

    def test_header_counts_merged_story_once(self) -> None:
        digest = self.build([[0, 2, 4], [3, 5]])
        self.assertIn("3 newsletters · 4 stories · 2 in multiple newsletters", digest.text)
        self.assertIn("IN MULTIPLE NEWSLETTERS TODAY (2)", digest.text)

    def test_same_newsletter_group_is_merged_but_stays_under_its_category(self) -> None:
        digest = self.build([[0, 1]])  # both stories are from Alpha
        self.assertNotIn("In multiple newsletters", digest.html)
        self.assertIn("Chip news", digest.html)
        self.assertNotIn("Alpha only", digest.html)
        self.assertIn("AI &amp; Tech (3)", digest.html)

    def test_bad_groups_are_ignored_by_the_digest_too(self) -> None:
        items = merge_items([mock.Mock(), mock.Mock()], [[0, 5], [1], [-1, 0]])
        self.assertEqual(len(items), 2)

    def test_plain_text_lists_each_source_link(self) -> None:
        text = self.build([[0, 2]]).text
        self.assertIn("(Alpha, Beta)", text)
        self.assertRegex(text, r"Alpha: https://\S+#t=a1")
        self.assertRegex(text, r"Beta: https://\S+#t=b2")


class CiLogSafetyTests(unittest.TestCase):
    """In CI the new Gemini call may print only counts, never story text or error text."""

    TITLE = "SECRET-DUP-TITLE"
    SENTENCE = "SECRET-DUP-SENTENCE"

    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)

    def run_ci(self, client):
        results = [NewsletterSummary([Story(self.TITLE, self.SENTENCE, "https://secret.example.com/x", "AI & Tech")])] * 2
        other = [newsletter("Alpha", "a1"), newsletter("Beta", "b2")]
        with mock.patch("summarize._get_client", return_value=client), \
             mock.patch("main.time.sleep"), mock.patch("summarize.time.sleep"):
            return run_main([], CI, fetch_newsletters=mock.Mock(return_value=other),
                            summarize_all=mock.Mock(return_value=results), find_merge_groups=main.find_merge_groups)

    def assert_clean(self, output: str) -> None:
        for private in (self.TITLE, self.SENTENCE, SECRET_ERROR, "secret.example.com"):
            self.assertNotIn(private, output)

    def test_success_logs_only_a_count(self) -> None:
        code, output = self.run_ci(FakeClient(groups_reply([[1, 2]])))
        self.assertEqual(code, 0)
        self.assertIn("Merged 1 duplicate stories.", output)
        self.assert_clean(output)

    def test_failure_logs_no_error_text(self) -> None:
        for error in (ValueError(f"{self.TITLE} {SECRET_ERROR}"), OSError(f"{self.SENTENCE} {SECRET_ERROR}"),
                      errors.APIError(400, {"error": {"message": f"{self.TITLE} {SECRET_ERROR}"}})):
            code, output = self.run_ci(FakeClient(error=error))
            self.assertEqual(code, 0)
            self.assertIn("Duplicate check unavailable", output)
            self.assert_clean(output)

    def test_bad_reply_logs_no_reply_text(self) -> None:
        code, output = self.run_ci(FakeClient(f"{self.TITLE} not json {SECRET_ERROR}"))
        self.assertEqual(code, 0)
        self.assert_clean(output)

    def test_digest_is_sent_even_when_the_check_fails(self) -> None:
        self.run_ci(FakeClient(error=ValueError("x")))
        run_main.last_fakes["send_digest"].assert_called_once()


if __name__ == "__main__":
    unittest.main()
