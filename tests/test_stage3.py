"""Offline checks for Stage 3. Everything here is made up, and smtplib is
replaced with a fake, so no email is sent and the network is never used.

Run from the project root with:  python -m unittest discover tests
"""

import smtplib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import main  # noqa: E402
from config import (  # noqa: E402
    CATEGORIES, MAX_STORIES, MAX_WORDS, SKIP_CATEGORY, ConfigError, Credentials, load_recipient,
)
from digest import build_digest  # noqa: E402
from fetch import Newsletter  # noqa: E402
from preview import sample_data, write_preview  # noqa: E402
from send import SendError, build_message, send_digest  # noqa: E402
from summarize import (  # noqa: E402
    RESPONSE_SCHEMA, SYSTEM_PROMPT, NewsletterSummary, Story, parse_reply,
)

WHEN = datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)
CREDS = Credentials(address="sender@example.com", app_password="fakepassword")


def make_newsletter(sender: str = "Fake Weekly <news@example.com>", subject: str = "Issue 1") -> Newsletter:
    """A fake email. Pass different senders when a test needs separate cards."""
    return Newsletter(sender=sender, subject=subject, date=WHEN, body="x", links=[], unsubscribe=None)


def make_summary(category: str = "AI & Tech", url: str | None = "https://example.com/a") -> NewsletterSummary:
    return NewsletterSummary(category=category, stories=[Story(summary="Something happened.", url=url)])


def sender(n: int) -> str:
    """A distinct fake sender, so emails do not merge."""
    return f"Sender {n} <s{n}@example.com>"


class DigestTests(unittest.TestCase):
    def test_subject_counts_and_pluralizes(self) -> None:
        one = build_digest([make_newsletter()], [make_summary()], WHEN)
        two = build_digest([make_newsletter(sender(1)), make_newsletter(sender(2))], [make_summary()] * 2, WHEN)
        self.assertEqual(one.subject, "Newsletter digest: Tue Nov 10 (1 newsletter)")
        self.assertIn("(2 newsletters)", two.subject)

    def test_sentence_is_the_link_and_no_read_links(self) -> None:
        digest = build_digest([make_newsletter()], [make_summary()], WHEN)
        self.assertIn('<a href="https://example.com/a" style="color:#1a56db;text-decoration:none;">Something happened.</a>', digest.html)
        self.assertNotIn("Read", digest.html)
        self.assertIn("Something happened.", digest.text)
        self.assertIn("https://example.com/a", digest.text)

    def test_shows_sender_name_but_not_address(self) -> None:
        digest = build_digest([make_newsletter()], [make_summary()], WHEN)
        for version in (digest.text.lower(), digest.html.lower()):
            self.assertIn("fake weekly", version)  # plain text shows the label in capitals
            self.assertNotIn("news@example.com", version)

    def test_story_without_link_is_plain_text(self) -> None:
        digest = build_digest([make_newsletter()], [make_summary(url=None)], WHEN)
        self.assertIn("Something happened.", digest.html)
        self.assertNotIn("<a ", digest.html)

    def test_header_line_has_count_and_categories(self) -> None:
        items = [make_newsletter(sender(1)), make_newsletter(sender(2)), make_newsletter(sender(3))]
        results = [make_summary("Culture & Lifestyle"), make_summary("AI & Tech"), make_summary("AI & Tech")]
        digest = build_digest(items, results, WHEN)
        self.assertIn("3 newsletters · AI & Tech, Culture & Lifestyle", digest.text)  # config order, no repeats
        self.assertIn("3 newsletters · AI &amp; Tech, Culture &amp; Lifestyle", digest.html)

    def test_cards_follow_config_category_order(self) -> None:
        items = [make_newsletter(sender(1)), make_newsletter(sender(2))]
        results = [make_summary("Culture & Lifestyle"), make_summary("AI & Tech")]
        text = build_digest(items, results, WHEN).text
        self.assertLess(text.index("SENDER 2"), text.index("SENDER 1"))

    def test_same_sender_merges_into_one_card_and_caps_stories(self) -> None:
        same = "Fake Weekly <News@Example.com>"  # different capitalization, still the same sender
        items = [make_newsletter(), make_newsletter(same)]
        results = [make_summary(), NewsletterSummary("AI & Tech", [Story(f"Story {i}.", None) for i in range(4)])]
        digest = build_digest(items, results, WHEN)
        self.assertEqual(digest.html.count("border-radius:12px"), 1)       # one card
        self.assertIn("FAKE WEEKLY (2 EMAILS)", digest.text)
        self.assertIn("Fake Weekly (2 emails)", digest.html)
        self.assertEqual(digest.text.count("- "), MAX_STORIES)             # capped
        self.assertIn("1 newsletter", digest.subject)

    def test_skipped_emails_hidden_and_counted_in_footer(self) -> None:
        items = [make_newsletter(sender(1)), make_newsletter(sender(2), "Your code is 123456"), make_newsletter(sender(3))]
        results = [make_summary(), NewsletterSummary("Skip", []), NewsletterSummary("Skip", [])]
        digest = build_digest(items, results, WHEN)
        self.assertIn("1 newsletter", digest.subject)
        self.assertNotIn("Sender 2", digest.html)
        self.assertNotIn("Skip", digest.html.replace("skipped", ""))  # not shown as a category
        self.assertIn("2 non-newsletter emails skipped.", digest.text)
        self.assertIn("2 non-newsletter emails skipped.", digest.html)

    def test_no_footer_when_nothing_skipped(self) -> None:
        digest = build_digest([make_newsletter()], [make_summary()], WHEN)
        self.assertNotIn("skipped", digest.text)
        self.assertNotIn("skipped", digest.html)

    def test_only_inline_styles(self) -> None:
        digest = build_digest([make_newsletter()], [make_summary()], WHEN)
        self.assertNotIn("<style", digest.html)
        self.assertNotIn("class=", digest.html)

    def test_failure_note_is_listed(self) -> None:
        digest = build_digest([make_newsletter()], ["(summary unavailable: rate limit)"], WHEN)
        self.assertIn("COULD NOT SUMMARIZE", digest.text)
        self.assertIn("rate limit", digest.html)

    def test_html_is_escaped_and_bad_links_dropped(self) -> None:
        evil = NewsletterSummary("AI & Tech", [Story("<b>bold</b> & more", "javascript:alert(1)")])
        digest = build_digest([make_newsletter("<script>alert(1)</script>")], [evil], WHEN)
        self.assertNotIn("<script>", digest.html)
        self.assertNotIn("<b>bold</b>", digest.html)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt; &amp; more", digest.html)
        self.assertNotIn("javascript:", digest.html)

    def test_quote_in_url_cannot_break_out_of_href(self) -> None:
        tricky = make_summary(url='https://example.com/"onmouseover="x')
        digest = build_digest([make_newsletter()], [tricky], WHEN)
        self.assertNotIn('"onmouseover=', digest.html)


class SkipAndPreviewTests(unittest.TestCase):
    def test_skip_category_is_in_config_and_schema(self) -> None:
        self.assertIn(SKIP_CATEGORY, CATEGORIES)
        self.assertIn(SKIP_CATEGORY, RESPONSE_SCHEMA["properties"]["category"]["enum"])
        self.assertIn(SKIP_CATEGORY, SYSTEM_PROMPT)
        self.assertIn(f"fewer than {MAX_WORDS} words", " ".join(SYSTEM_PROMPT.split()))

    def test_parse_reply_accepts_skip_with_no_stories(self) -> None:
        result = parse_reply('{"category": "Skip", "stories": []}', [])
        self.assertEqual(result.category, SKIP_CATEGORY)
        self.assertEqual(result.stories, [])

    def test_max_stories_is_three(self) -> None:
        self.assertEqual(MAX_STORIES, 3)

    def test_sample_data_uses_only_fake_example_addresses(self) -> None:
        emails, results = sample_data(WHEN)
        self.assertEqual(len(emails), len(results))
        for item in emails:
            self.assertIn(".example.com>", item.sender)

    def test_write_preview_creates_html_without_any_network_or_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = write_preview(Path(folder) / "preview.html", WHEN)
            page = path.read_text(encoding="utf-8")
        # 4 sender emails became 3 cards because the two Fake Daily emails merge.
        self.assertIn("3 newsletters", page)
        self.assertIn("Fake Daily (2 emails)", page)
        self.assertIn("2 non-newsletter emails skipped.", page)

    def test_preview_flag_never_loads_credentials_or_sends(self) -> None:
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch("main.PREVIEW_PATH", Path(folder) / "preview.html"), \
             mock.patch("main.load_credentials") as creds, \
             mock.patch("main.connect") as connect, \
             mock.patch("main.summarize_all") as summarizer, \
             mock.patch("main.send_digest") as sender_mock:
            self.assertEqual(main.main(["--preview"]), 0)
            self.assertTrue((Path(folder) / "preview.html").exists())
        for fake in (creds, connect, summarizer, sender_mock):
            fake.assert_not_called()

    def test_preview_html_is_gitignored(self) -> None:
        ignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text()
        self.assertIn("preview.html", ignore.splitlines())


class SendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.digest = build_digest([make_newsletter()], [make_summary()], WHEN)

    def test_message_has_headers_and_both_parts(self) -> None:
        message = build_message(self.digest, "sender@example.com", "me@example.com")
        self.assertEqual(message["From"], "sender@example.com")
        self.assertEqual(message["To"], "me@example.com")
        self.assertEqual(message["Subject"], self.digest.subject)
        types = [part.get_content_type() for part in message.iter_parts()]
        self.assertEqual(types, ["text/plain", "text/html"])

    def test_send_logs_in_and_sends_once(self) -> None:
        with mock.patch("send.smtplib.SMTP_SSL") as smtp:
            server = smtp.return_value.__enter__.return_value
            send_digest(self.digest, CREDS, "me@example.com")
        server.login.assert_called_once_with("sender@example.com", "fakepassword")
        server.send_message.assert_called_once()

    def test_expected_failures_become_send_error(self) -> None:
        cases = [
            (smtplib.SMTPAuthenticationError(535, b"bad"), "GMAIL_APP_PASSWORD"),
            (smtplib.SMTPRecipientsRefused({}), "DIGEST_TO"),
            (smtplib.SMTPServerDisconnected("gone"), "Could not send"),
            (OSError("offline"), "offline"),
        ]
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                with mock.patch("send.smtplib.SMTP_SSL", side_effect=error):
                    with self.assertRaises(SendError) as caught:
                        send_digest(self.digest, CREDS, "me@example.com")
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn("fakepassword", str(caught.exception))


class ConfigAndMainTests(unittest.TestCase):
    def test_missing_recipient_raises(self) -> None:
        with mock.patch("config.load_dotenv"), mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ConfigError):
                load_recipient()

    def test_main_sends_digest_with_fake_everything(self) -> None:
        with mock.patch("main.load_credentials", return_value=CREDS), \
             mock.patch("main.load_recipient", return_value="me@example.com"), \
             mock.patch("main.connect"), \
             mock.patch("main.fetch_newsletters", return_value=[make_newsletter()]), \
             mock.patch("main.summarize_all", return_value=[make_summary()]), \
             mock.patch("main.append_to_log", return_value=0), \
             mock.patch("main.send_digest") as sender:
            self.assertEqual(main.main([]), 0)
        sender.assert_called_once()
        self.assertEqual(sender.call_args.args[2], "me@example.com")

    def test_no_send_flag_skips_sending(self) -> None:
        with mock.patch("main.load_credentials", return_value=CREDS), \
             mock.patch("main.connect"), \
             mock.patch("main.fetch_newsletters", return_value=[make_newsletter()]), \
             mock.patch("main.summarize_all", return_value=[make_summary()]), \
             mock.patch("main.append_to_log", return_value=0), \
             mock.patch("main.send_digest") as sender:
            self.assertEqual(main.main(["--no-send"]), 0)
        sender.assert_not_called()

    def test_send_failure_exits_cleanly(self) -> None:
        with mock.patch("main.load_credentials", return_value=CREDS), \
             mock.patch("main.load_recipient", return_value="me@example.com"), \
             mock.patch("main.connect"), \
             mock.patch("main.fetch_newsletters", return_value=[make_newsletter()]), \
             mock.patch("main.summarize_all", return_value=[make_summary()]), \
             mock.patch("main.append_to_log", return_value=0), \
             mock.patch("main.send_digest", side_effect=SendError("boom")):
            self.assertEqual(main.main([]), 1)


if __name__ == "__main__":
    unittest.main()
