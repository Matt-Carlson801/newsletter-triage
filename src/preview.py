"""Fake sample data for `--preview`, so you can see the digest design without
touching your inbox, Gemini, or SMTP. Every sender, story and link is invented
(example.com is a domain reserved for examples).
"""

from datetime import datetime
from pathlib import Path

from digest import build_digest
from fetch import Newsletter
from summarize import NewsletterSummary, Story


def _email(sender: str, subject: str, when: datetime) -> Newsletter:
    """A fake email. Only sender, subject and date matter to the digest."""
    return Newsletter(sender=sender, subject=subject, date=when, body="", links=[], unsubscribe=None)


def sample_data(when: datetime) -> tuple[list[Newsletter], list[NewsletterSummary | str]]:
    """Return (fake newsletters, fake results), including the tricky cases:
    two emails from one sender, skipped emails, a story with no link, and a failure."""
    emails = [
        _email("Fake Daily <hello@fakedaily.example.com>", "Monday edition", when),
        _email("Fake Daily <hello@fakedaily.example.com>", "Special edition", when),
        _email("Startup Notes <notes@startupnotes.example.com>", "Seed rounds cooled", when),
        _email("Growth Weekly <team@growthweekly.example.com>", "Cold email in 2026", when),
        _email("Example Store <orders@store.example.com>", "Your order has shipped", when),
        _email("Example App <no-reply@app.example.com>", "Your verification code", when),
        _email("Broken Digest <hi@broken.example.com>", "Issue 88", when),
    ]
    results: list[NewsletterSummary | str] = [
        NewsletterSummary("AI & Tech", [
            Story("A small lab released an open model that runs on a laptop.", "https://example.com/open-model"),
            Story("Chip makers expect demand for inference hardware to double next year.", "https://example.com/chips"),
            Story("Regulators asked three companies to explain how their assistants store chat history.", "https://example.com/regulators"),
        ]),
        NewsletterSummary("AI & Tech", [
            Story("A fourth story from the same sender is dropped by the three-story cap.", "https://example.com/extra"),
        ]),
        NewsletterSummary("Startups & Product", [
            Story("Seed funding fell for the second quarter in a row, led by a pullback in consumer apps.", "https://example.com/seed"),
            Story("One founder explains why they replaced onboarding emails with a short video.", None),  # no link
        ]),
        NewsletterSummary("Marketing & Sales", [
            Story("Short plain-text cold emails beat designed templates in a 10,000-message test.", "https://example.com/cold-email"),
        ]),
        NewsletterSummary("Skip", []),
        NewsletterSummary("Skip", []),
        "(summary unavailable: Gemini rate limit reached (free tier); gave up after 3 retries.)",
    ]
    return emails, results


def write_preview(path: Path, when: datetime) -> Path:
    """Build the digest from sample data and write its HTML to `path`."""
    emails, results = sample_data(when)
    path.write_text(build_digest(emails, results, when).html, encoding="utf-8")
    return path
