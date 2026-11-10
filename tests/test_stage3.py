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
    CATEGORIES, MAX_STORIES, MAX_TITLE_WORDS, MAX_WORDS, ConfigError, Credentials, load_recipient,
)
from digest import _organize, build_digest, gmail_fallback_url  # noqa: E402
from fetch import Newsletter  # noqa: E402
from preview import PREVIEW_GMAIL_ADDRESS, sample_data, write_preview  # noqa: E402
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
    return NewsletterSummary(stories=[Story("Big news", "Something happened.", url, category)])


SKIPPED = NewsletterSummary(stories=[], skip=True)


def sender(n: int) -> str:
    """A distinct fake sender, so emails do not merge."""
    return f"Sender {n} <s{n}@example.com>"


class DigestTests(unittest.TestCase):
    def test_subject_counts_and_pluralizes(self) -> None:
        one = build_digest([make_newsletter()], [make_summary()], WHEN)
        two = build_digest([make_newsletter(sender(1)), make_newsletter(sender(2))], [make_summary()] * 2, WHEN)
        self.assertEqual(one.subject, "Newsletter digest: Tue Nov 10 (1 newsletter)")
        self.assertIn("(2 newsletters)", two.subject)

    def test_story_is_bold_link_then_gray_newsletter_name_then_sentence(self) -> None:
        digest = build_digest([make_newsletter()], [make_summary()], WHEN)
        story = ('<a href="https://example.com/a" style="font-size:16px;font-weight:700;'
                 'color:#1a56db;text-decoration:none;">Big news</a> '
                 '<span style="font-size:13px;color:#9ca3af;">(Fake Weekly)</span><br>Something happened.')
        self.assertIn(story, digest.html)
        self.assertEqual(digest.html.count("<a "), 1)  # only the headline is a link; the name is not
        self.assertIn("- Big news (Fake Weekly): Something happened.\n  https://example.com/a", digest.text)

    def test_no_cards_and_no_subject_lines(self) -> None:
        digest = build_digest([make_newsletter(subject="The subject line")], [make_summary()], WHEN)
        self.assertNotIn("border-radius", digest.html)
        for version in (digest.text, digest.html):
            self.assertNotIn("The subject line", version)

    def test_heading_per_category_with_count_and_empty_ones_skipped(self) -> None:
        items = [make_newsletter(sender(n)) for n in range(1, 4)]
        results = [make_summary("AI & Tech"), make_summary("AI & Tech"), make_summary("Personal Growth")]
        digest = build_digest(items, results, WHEN)
        self.assertIn(">AI &amp; Tech (2)</h2>", digest.html)
        self.assertIn(">Personal Growth (1)</h2>", digest.html)
        self.assertIn("AI & TECH (2)", digest.text)
        for empty in ("Stoicism", "Health", "News &amp; Politics", "Other (", "Business"):
            self.assertNotIn(empty, digest.html)

    def test_headings_follow_config_category_order(self) -> None:
        items = [make_newsletter(sender(1)), make_newsletter(sender(2))]
        results = [make_summary("Other"), make_summary("AI & Tech")]
        text = build_digest(items, results, WHEN).text
        self.assertLess(text.index("AI & TECH (1)"), text.index("OTHER (1)"))

    def test_one_newsletter_can_appear_under_several_topics(self) -> None:
        both = NewsletterSummary([Story("A", "One.", None, "Personal Growth"), Story("B", "Two.", None, "AI & Tech")])
        digest = build_digest([make_newsletter()], [both], WHEN)
        self.assertEqual(digest.html.count("(Fake Weekly)"), 2)
        self.assertIn("1 newsletter ·", digest.text)
        self.assertIn("2 stories", digest.text)

    def test_two_newsletters_share_a_topic_heading(self) -> None:
        items = [make_newsletter(sender(1)), make_newsletter(sender(2))]
        digest = build_digest(items, [make_summary(), make_summary()], WHEN)
        self.assertEqual(digest.html.count("<h2"), 1)
        self.assertIn("AI &amp; Tech (2)", digest.html)
        self.assertIn("(Sender 1)", digest.html)
        self.assertIn("(Sender 2)", digest.html)

    def test_same_sender_twice_counts_as_one_newsletter(self) -> None:
        same = "Fake Weekly <News@Example.com>"  # different capitalization, still the same sender
        items = [make_newsletter(), make_newsletter(same, "Thursday issue")]
        digest = build_digest(items, [make_summary(), make_summary()], WHEN)
        self.assertIn("1 newsletter", digest.subject)
        self.assertIn("1 newsletter · 2 stories", digest.text)

    def test_shows_sender_name_but_not_address(self) -> None:
        digest = build_digest([make_newsletter()], [make_summary()], WHEN)
        for version in (digest.text, digest.html):
            self.assertIn("Fake Weekly", version)
            self.assertNotIn("news@example.com", version.lower())

    def test_story_without_link_is_plain_bold_text(self) -> None:
        digest = build_digest([make_newsletter()], [make_summary(url=None)], WHEN)
        self.assertIn("Big news</span> <span", digest.html)  # title still bold, just not a link
        self.assertNotIn("<a ", digest.html)

    def test_skipped_emails_hidden_and_counted_in_footer(self) -> None:
        items = [make_newsletter(sender(1)), make_newsletter(sender(2), "Your code is 123456"), make_newsletter(sender(3))]
        digest = build_digest(items, [make_summary(), SKIPPED, SKIPPED], WHEN)
        self.assertIn("1 newsletter", digest.subject)
        self.assertNotIn("Sender 2", digest.html)
        self.assertNotIn("Skip", digest.html.replace("skipped", ""))  # not shown as a topic
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
        self.assertIn("Could not summarize</h2>", digest.html)
        self.assertIn("rate limit", digest.html)

    def test_html_is_escaped_and_bad_links_dropped(self) -> None:
        evil = NewsletterSummary([Story("<i>Title</i>", "<b>bold</b> & more", "javascript:alert(1)", "AI & Tech")])
        digest = build_digest([make_newsletter("<script>alert(1)</script>")], [evil], WHEN)
        self.assertNotIn("<script>", digest.html)
        self.assertNotIn("<b>bold</b>", digest.html)
        self.assertNotIn("<i>Title</i>", digest.html)
        self.assertIn("&lt;i&gt;Title&lt;/i&gt;", digest.html)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt; &amp; more", digest.html)
        self.assertNotIn("javascript:", digest.html)

    def test_quote_in_url_cannot_break_out_of_href(self) -> None:
        tricky = make_summary(url='https://example.com/"onmouseover="x')
        digest = build_digest([make_newsletter()], [tricky], WHEN)
        self.assertNotIn('"onmouseover=', digest.html)


class NewsletterLinkTests(unittest.TestCase):
    ADDRESS = "me@example.com"

    def digest_for(self, web_url: str | None, message_id: str | None, address: str | None = ADDRESS):
        item = make_newsletter()
        item.web_url, item.message_id = web_url, message_id
        return build_digest([item], [make_summary()], WHEN, address)

    def test_name_links_to_web_version_when_found(self) -> None:
        digest = self.digest_for("https://example.com/web", "<abc@mail.example.com>")
        self.assertIn('(<a href="https://example.com/web" style="font-size:13px;color:#9ca3af;'
                      'text-decoration:none;">Fake Weekly</a>)', digest.html)
        self.assertNotIn("mail.google.com", digest.html)  # web version wins over the fallback
        self.assertIn("Newsletter: https://example.com/web", digest.text)

    def test_name_falls_back_to_gmail_link(self) -> None:
        digest = self.digest_for(None, "<abc+1=2@mail.example.com>")
        self.assertIn("https://mail.google.com/mail/u/me@example.com/#search/rfc822msgid%3A"
                      "abc%2B1%3D2%40mail.example.com", digest.html)
        self.assertEqual(digest.html.count("<a "), 2)  # headline + newsletter name

    def test_headline_still_links_to_the_article(self) -> None:
        digest = self.digest_for("https://example.com/web", None)
        self.assertIn('<a href="https://example.com/a" style="font-size:16px', digest.html)

    def test_no_link_when_nothing_is_available(self) -> None:
        for digest in (self.digest_for(None, None), self.digest_for(None, "<a@b>", address=None)):
            self.assertIn("(Fake Weekly)</span>", digest.html)
            self.assertEqual(digest.html.count("<a "), 1)

    def test_only_http_links_allowed_for_web_version(self) -> None:
        digest = self.digest_for("javascript:alert(1)", None)
        self.assertNotIn("javascript:", digest.html)
        self.assertEqual(digest.html.count("<a "), 1)

    def test_everything_is_escaped(self) -> None:
        digest = self.digest_for('https://example.com/"onmouseover="x', None)
        self.assertNotIn('"onmouseover=', digest.html)
        url = gmail_fallback_url('a"b@example.com', '<x"y>')
        self.assertNotIn('"', url)
        self.assertNotIn("<", url)

    def test_fallback_url_format(self) -> None:
        self.assertEqual(
            gmail_fallback_url("me@example.com", "<id@host>"),
            "https://mail.google.com/mail/u/me@example.com/#search/rfc822msgid%3Aid%40host",
        )
        self.assertIsNone(gmail_fallback_url("me@example.com", None))
        self.assertIsNone(gmail_fallback_url(None, "<id@host>"))

    def test_preview_mixes_web_links_and_gmail_fallbacks(self) -> None:
        emails, _ = sample_data(WHEN)
        self.assertTrue(any(item.web_url for item in emails))
        self.assertTrue(any(not item.web_url for item in emails))
        with tempfile.TemporaryDirectory() as folder:
            page = write_preview(Path(folder) / "preview.html", WHEN).read_text(encoding="utf-8")
        self.assertIn("/web-version/latest", page)
        self.assertIn(f"mail.google.com/mail/u/{PREVIEW_GMAIL_ADDRESS}/#search/rfc822msgid%3A", page)

    def test_main_passes_gmail_address_to_digest(self) -> None:
        with mock.patch("main.build_digest", wraps=build_digest) as builder, \
             mock.patch("main.load_credentials", return_value=mock.Mock(address="me@example.com")), \
             mock.patch("main.load_recipient", return_value="to@example.com"), \
             mock.patch("main.connect"), \
             mock.patch("main.fetch_newsletters", return_value=[make_newsletter()]), \
             mock.patch("main.summarize_all", return_value=[make_summary()]), \
             mock.patch("main.append_to_log", return_value=0), \
             mock.patch("main.send_digest"):
            self.assertEqual(main.main([]), 0)
        self.assertEqual(builder.call_args.args[3], "me@example.com")


class SkipAndPreviewTests(unittest.TestCase):
    def test_categories_are_the_agreed_topics(self) -> None:
        self.assertEqual(CATEGORIES, [
            "AI & Tech", "Work & Productivity", "Business & GTM", "Personal Growth",
            "Stoicism & Philosophy", "Health & Performance", "News & Politics", "Other",
        ])
        self.assertNotIn("Skip", CATEGORIES)

    def test_skip_is_a_newsletter_level_flag_in_schema_and_prompt(self) -> None:
        self.assertEqual(RESPONSE_SCHEMA["properties"]["skip"], {"type": "boolean"})
        self.assertIn("skip", RESPONSE_SCHEMA["required"])
        self.assertIn('"skip": true', SYSTEM_PROMPT)
        self.assertIn(f"fewer than {MAX_WORDS} words", " ".join(SYSTEM_PROMPT.split()))

    def test_parse_reply_accepts_skip_with_no_stories(self) -> None:
        result = parse_reply('{"skip": true, "stories": []}', [])
        self.assertTrue(result.skip)
        self.assertEqual(result.stories, [])

    def test_prompt_and_schema_ask_for_title_sentence_and_category(self) -> None:
        item = RESPONSE_SCHEMA["properties"]["stories"]["items"]
        self.assertEqual(item["required"], ["title", "summary", "link_id", "category"])
        self.assertEqual(RESPONSE_SCHEMA["properties"]["stories"]["maxItems"], 5)
        prompt = " ".join(SYSTEM_PROMPT.split())
        self.assertIn(f"fewer than {MAX_TITLE_WORDS} words", prompt)
        self.assertIn("up to 5 distinct stories", prompt)

    def test_sample_data_shape_matches_the_brief(self) -> None:
        emails, results = sample_data(WHEN)
        self.assertEqual(len(emails), len(results))
        self.assertEqual(len({item.sender for item in emails}), 9)       # 9 senders
        self.assertEqual(sum(isinstance(r, str) for r in results), 1)    # one failure
        self.assertEqual(sum(isinstance(r, NewsletterSummary) and r.skip for r in results), 1)
        senders = [item.sender for item in emails]
        self.assertEqual(len(senders) - len(set(senders)), 1)            # one sender mails twice
        topics, _, _, _ = _organize(emails, results)
        self.assertGreaterEqual(len(topics), 5)                          # at least 5 categories appear
        # Two different newsletters cover the same topic, in more than one topic.
        shared = [c for c, items in topics.items() if len({i.newsletter for i in items}) >= 2]
        self.assertGreaterEqual(len(shared), 1)
        for items in topics.values():
            for item in items:
                self.assertLess(len(item.story.title.split()), MAX_TITLE_WORDS, item.story.title)
                self.assertLess(len(item.story.summary.split()), MAX_WORDS, item.story.summary)
        for result in results:
            if isinstance(result, NewsletterSummary):
                self.assertLessEqual(len(result.stories), MAX_STORIES)

    def test_sample_data_uses_only_fake_example_addresses(self) -> None:
        emails, results = sample_data(WHEN)
        self.assertEqual(len(emails), len(results))
        for item in emails:
            self.assertIn(".example.com>", item.sender)

    def test_write_preview_creates_html_without_any_network_or_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = write_preview(Path(folder) / "preview.html", WHEN)
            page = path.read_text(encoding="utf-8")
        # 10 emails: 7 newsletters with stories, 1 confirmation skipped, 1 failure.
        self.assertIn("7 newsletters", page)
        self.assertIn("1 non-newsletter email skipped.", page)
        self.assertIn("Could not summarize", page)
        self.assertIn("Business &amp; GTM (7)", page)
        self.assertNotIn("Other (", page)  # empty topics are not shown
        self.assertEqual(page.count("<h2"), 8)  # 7 topics + the failure section

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
