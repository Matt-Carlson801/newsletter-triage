"""Offline checks for Stage 2. A fake Gemini client stands in for the real
one, so these tests use no API key, no network, and no real email. Every
newsletter and link below is made up.

Run from the project root with:  python -m unittest discover tests
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from google.genai import errors  # noqa: E402

import main  # noqa: E402
from config import CATEGORIES, MAX_INPUT_CHARS, MAX_STORIES  # noqa: E402
from fetch import Newsletter  # noqa: E402
from links import Link, filter_links  # noqa: E402
from summarize import (  # noqa: E402
    RESPONSE_SCHEMA, SYSTEM_PROMPT, NewsletterSummary, Story, SummarizeError, parse_reply, summarize,
)

GOOD = Link("Read the launch post", "https://example.com/launch")
GOOD2 = Link("Funding round details", "https://example.com/funding")


def reply(category: str = "AI & Tech", stories: list | None = None) -> str:
    """Build a JSON reply like the one Gemini should send back."""
    if stories is None:
        stories = [{"summary": "A thing happened.", "link_id": 1}]
    return json.dumps({"category": category, "stories": stories})


class FakeClient:
    """Mimics client.models.generate_content(...) and records what it was sent."""

    def __init__(self, text: str = "", error: Exception | None = None, fail_first: int = 0) -> None:
        # error: raised on every call. fail_first: raise `error` only on the
        # first N calls, then succeed (use both to script "fails twice, then works").
        self.text, self.error, self.fail_first = text, error, fail_first
        self.sent: str | None = None
        self.calls = 0
        self.models = self  # so client.models.generate_content works

    def generate_content(self, model, contents, config):
        self.calls += 1
        if self.error and (not self.fail_first or self.calls <= self.fail_first):
            raise self.error
        self.sent = contents
        return mock.Mock(text=self.text)


class FilterLinksTests(unittest.TestCase):
    def dropped(self, link: Link, header: str | None = None) -> bool:
        return filter_links([link], header) == []

    def test_good_links_are_kept(self) -> None:
        self.assertEqual(filter_links([GOOD, GOOD2]), [GOOD, GOOD2])

    def test_images_and_fonts_are_dropped(self) -> None:
        for url in ("https://cdn.example.com/logo.PNG", "https://x.com/a.woff2",
                    "https://example.com/img/photo.jpg?w=600", "https://example.com/a.svg"):
            self.assertTrue(self.dropped(Link("", url)), url)

    def test_tracking_pixels_are_dropped(self) -> None:
        self.assertTrue(self.dropped(Link("", "https://mail.example.com/track/open?id=9")))
        self.assertTrue(self.dropped(Link("", "https://example.com/pixel?u=1")))

    def test_social_links_are_dropped_including_subdomains(self) -> None:
        for url in ("https://twitter.com/example", "https://www.linkedin.com/company/x",
                    "https://mobile.facebook.com/x", "https://x.com/example"):
            self.assertTrue(self.dropped(Link("Follow us", url)), url)

    def test_lookalike_domain_is_not_social(self) -> None:
        # "box.com" ends with the letters "x.com" but is a different site than x.com.
        self.assertFalse(self.dropped(Link("Story", "https://box.com/story")))
        self.assertFalse(self.dropped(Link("Story", "https://notlinkedin.com/story")))

    def test_unsubscribe_by_text_url_or_header(self) -> None:
        self.assertTrue(self.dropped(Link("Unsubscribe", "https://example.com/a")))
        self.assertTrue(self.dropped(Link("here", "https://example.com/unsubscribe?u=1")))
        self.assertTrue(self.dropped(Link("Manage preferences", "https://example.com/p")))
        self.assertTrue(self.dropped(Link("click", "https://example.com/zzz"), header="<https://example.com/zzz>"))

    def test_sponsor_links_are_dropped(self) -> None:
        self.assertTrue(self.dropped(Link("Our sponsor: Acme", "https://acme.com")))
        self.assertTrue(self.dropped(Link("Try it", "https://acme.com/?utm_medium=sponsor")))
        self.assertTrue(self.dropped(Link("Try it", "https://acme.com/?utm_medium=PAID")))
        self.assertTrue(self.dropped(Link("Advertisement", "https://acme.com")))


class ParseReplyTests(unittest.TestCase):
    def test_maps_link_id_to_real_url(self) -> None:
        result = parse_reply(reply(stories=[{"summary": "S.", "link_id": 2}]), [GOOD, GOOD2])
        self.assertEqual(result, NewsletterSummary("AI & Tech", [Story("S.", GOOD2.url)]))

    def test_bad_link_ids_become_none(self) -> None:
        stories = [{"summary": f"S{i}.", "link_id": i} for i in (0, 3, -1)]
        result = parse_reply(reply(stories=stories), [GOOD, GOOD2])
        self.assertEqual([s.url for s in result.stories], [None, None, None])

    def test_unknown_category_becomes_other(self) -> None:
        self.assertEqual(parse_reply(reply(category="Cooking"), [GOOD]).category, "Other")

    def test_stories_are_capped(self) -> None:
        stories = [{"summary": f"S{i}.", "link_id": 1} for i in range(9)]
        self.assertEqual(len(parse_reply(reply(stories=stories), [GOOD]).stories), MAX_STORIES)

    def test_blank_stories_are_skipped(self) -> None:
        stories = [{"summary": "  ", "link_id": 1}, {"summary": "Real.", "link_id": 1}]
        self.assertEqual(len(parse_reply(reply(stories=stories), [GOOD]).stories), 1)

    def test_garbage_is_an_error(self) -> None:
        for bad in ("not json", "[]", '{"category": "AI & Tech"}', reply(stories=[])):
            with self.assertRaises(SummarizeError, msg=bad):
                parse_reply(bad, [GOOD])


def api_error(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"message": "fake"}})


class SummarizeTests(unittest.TestCase):
    def setUp(self) -> None:
        # Replace time.sleep with a recorder so tests are instant and we can
        # check exactly how long the code *would* have waited.
        patcher = mock.patch("time.sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_category_and_stories(self) -> None:
        client = FakeClient(reply(stories=[{"summary": "Launch.", "link_id": 1}]))
        result = summarize("Hello world", [GOOD], client=client)
        self.assertEqual(result, NewsletterSummary("AI & Tech", [Story("Launch.", GOOD.url)]))

    def test_exactly_one_gemini_call(self) -> None:
        client = FakeClient(reply())
        summarize("Hello", [GOOD], client=client)
        self.assertEqual(client.calls, 1)

    def test_junk_links_never_reach_gemini(self) -> None:
        junk = [
            Link("", "https://cdn.example.com/logo.png"),
            Link("Follow us", "https://twitter.com/example"),
            Link("Unsubscribe", "https://example.com/unsubscribe"),
            Link("Sponsor: Acme", "https://acme.com"),
            Link("", "https://example.com/track/open?id=1"),
            Link("hidden", "https://example.com/zzz"),  # only in the header
        ]
        client = FakeClient(reply())
        summarize("Hello", junk + [GOOD], unsubscribe_header="<https://example.com/zzz>", client=client)
        self.assertIn(GOOD.url, client.sent)
        self.assertIn(GOOD.text, client.sent)  # link text is sent too
        for link in junk:
            self.assertNotIn(link.url, client.sent)

    def test_text_cutoff_is_30000(self) -> None:
        self.assertEqual(MAX_INPUT_CHARS, 30_000)
        client = FakeClient(reply())
        summarize("x" * 40_000 + "TAIL", [], client=client)
        self.assertNotIn("TAIL", client.sent)
        self.assertIn("x" * 30_000, client.sent)
        self.assertNotIn("x" * 30_001, client.sent)

    def test_text_just_under_cutoff_is_not_cut(self) -> None:
        client = FakeClient(reply())
        summarize("x" * 29_990 + " END", [], client=client)
        self.assertIn("END", client.sent)

    def test_prompt_and_schema_use_the_fixed_category_list(self) -> None:
        self.assertEqual(RESPONSE_SCHEMA["properties"]["category"]["enum"], CATEGORIES)
        for category in CATEGORIES:
            self.assertIn(category, SYSTEM_PROMPT)

    def test_empty_text_is_an_error(self) -> None:
        with self.assertRaises(SummarizeError):
            summarize("   ", [GOOD], client=FakeClient(reply()))

    def test_empty_reply_is_an_error(self) -> None:
        with self.assertRaises(SummarizeError):
            summarize("Hello", [GOOD], client=FakeClient(""))

    def test_rate_limit_becomes_friendly_error(self) -> None:
        with self.assertRaisesRegex(SummarizeError, "rate limit"):
            summarize("Hello", [GOOD], client=FakeClient(error=api_error(429)))

    def test_fails_twice_then_succeeds(self) -> None:
        for code in (503, 429):
            self.sleep.reset_mock()
            client = FakeClient(reply(), error=api_error(code), fail_first=2)
            result = summarize("Hello", [GOOD], client=client)
            self.assertEqual(result.category, "AI & Tech")
            self.assertEqual(client.calls, 3)  # 2 failures + 1 success
            self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [2, 4])

    def test_always_failing_retries_three_times_then_raises(self) -> None:
        for code, word in ((503, "overloaded"), (429, "rate limit")):
            self.sleep.reset_mock()
            client = FakeClient(error=api_error(code))
            with self.assertRaisesRegex(SummarizeError, word):
                summarize("Hello", [GOOD], client=client)
            self.assertEqual(client.calls, 4)  # 1 first try + 3 retries
            self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [2, 4, 8])

    def test_other_errors_are_not_retried(self) -> None:
        for code in (400, 403, 500):
            self.sleep.reset_mock()
            client = FakeClient(error=api_error(code))
            with self.assertRaises(SummarizeError):
                summarize("Hello", [GOOD], client=client)
            self.assertEqual(client.calls, 1)
            self.sleep.assert_not_called()

    def test_success_first_time_never_waits(self) -> None:
        summarize("Hello", [GOOD], client=FakeClient(reply()))
        self.sleep.assert_not_called()

    def test_missing_key_is_an_error(self) -> None:
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(SummarizeError, "GEMINI_API_KEY"):
                summarize("Hello", [GOOD])


class SummarizeAllTests(unittest.TestCase):
    def test_pauses_one_second_between_newsletters_only(self) -> None:
        items = [Newsletter("a", "s", None, "text", [], None) for _ in range(3)]
        fine = NewsletterSummary("Other", [Story("Fine.", None)])
        with mock.patch.object(main, "summarize", return_value=fine), \
                mock.patch("time.sleep") as sleep:
            main.summarize_all(items)
        # 3 newsletters = 2 gaps: none before the first, none after the last.
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 1])

    def test_no_pause_for_a_single_newsletter(self) -> None:
        item = Newsletter("a", "s", None, "text", [], None)
        with mock.patch.object(main, "summarize", side_effect=SummarizeError("x")), \
                mock.patch("time.sleep") as sleep:
            main.summarize_all([item])
        sleep.assert_not_called()

    def test_one_failure_does_not_stop_the_rest(self) -> None:
        items = [Newsletter("a", "s", None, body, [], None) for body in ("one", "two")]
        fine = NewsletterSummary("Other", [Story("Fine.", None)])
        with mock.patch.object(main, "summarize", side_effect=[SummarizeError("boom"), fine]), \
                mock.patch("time.sleep"):
            result = main.summarize_all(items)
        self.assertIn("unavailable", result[0])
        self.assertEqual(result[1], fine)


if __name__ == "__main__":
    unittest.main()
