"""Offline checks for Stage 3. Everything here is made up, and smtplib is
replaced with a fake, so no email is sent and the network is never used.

Run from the project root with:  python -m unittest discover tests
"""

import smtplib
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import main  # noqa: E402
from config import ConfigError, Credentials, load_recipient  # noqa: E402
from digest import build_digest  # noqa: E402
from fetch import Newsletter  # noqa: E402
from send import SendError, build_message, send_digest  # noqa: E402
from summarize import NewsletterSummary, Story  # noqa: E402

WHEN = datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)
CREDS = Credentials(address="sender@example.com", app_password="fakepassword")


def make_newsletter(sender: str = "Fake Weekly <news@example.com>", subject: str = "Issue 1") -> Newsletter:
    return Newsletter(sender=sender, subject=subject, date=WHEN, body="x", links=[], unsubscribe=None)


def make_summary(category: str = "AI & Tech", url: str | None = "https://example.com/a") -> NewsletterSummary:
    return NewsletterSummary(category=category, stories=[Story(summary="Something happened.", url=url)])


class DigestTests(unittest.TestCase):
    def test_subject_counts_and_pluralizes(self) -> None:
        one = build_digest([make_newsletter()], [make_summary()], WHEN)
        two = build_digest([make_newsletter()] * 2, [make_summary()] * 2, WHEN)
        self.assertEqual(one.subject, "Newsletter digest: Tue Nov 10 (1 newsletter)")
        self.assertIn("(2 newsletters)", two.subject)

    def test_contains_summary_link_and_sender_name_only(self) -> None:
        digest = build_digest([make_newsletter()], [make_summary()], WHEN)
        for version in (digest.text, digest.html):
            self.assertIn("Something happened.", version)
            self.assertIn("https://example.com/a", version)
            self.assertIn("Fake Weekly", version)
            self.assertNotIn("news@example.com", version)  # address is not shown

    def test_groups_by_category_in_config_order(self) -> None:
        items = [make_newsletter(subject="B"), make_newsletter(subject="A")]
        results = [make_summary("Culture & Lifestyle"), make_summary("AI & Tech")]
        text = build_digest(items, results, WHEN).text
        self.assertLess(text.index("AI & TECH"), text.index("CULTURE & LIFESTYLE"))

    def test_failure_note_is_listed(self) -> None:
        digest = build_digest([make_newsletter()], ["(summary unavailable: rate limit)"], WHEN)
        self.assertIn("COULD NOT SUMMARIZE", digest.text)
        self.assertIn("rate limit", digest.html)

    def test_html_is_escaped_and_bad_links_dropped(self) -> None:
        evil_item = make_newsletter(subject="<script>alert(1)</script>")
        evil = NewsletterSummary("AI & Tech", [Story("<b>bold</b> & more", "javascript:alert(1)")])
        digest = build_digest([evil_item], [evil], WHEN)
        self.assertNotIn("<script>", digest.html)
        self.assertNotIn("<b>bold</b>", digest.html)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt; &amp; more", digest.html)
        self.assertNotIn("javascript:", digest.html)

    def test_quote_in_url_cannot_break_out_of_href(self) -> None:
        tricky = make_summary(url='https://example.com/"onmouseover="x')
        digest = build_digest([make_newsletter()], [tricky], WHEN)
        self.assertNotIn('"onmouseover=', digest.html)


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
