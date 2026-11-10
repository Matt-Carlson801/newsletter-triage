"""Build the daily digest email (subject, plain-text body, HTML body).

This file only builds text. It never touches the network, so it is easy to
test with fake data. send.py is the file that actually sends the result.

Layout: a header line, then one section per topic (for example "AI & Tech (7)"),
then a "could not summarize" section if any summary failed, then a one-line
footer. Stories from every newsletter are grouped by topic. A story is a bold
headline (the link), the newsletter name in gray parentheses, and on the next
line one sentence of context. Topics with no stories are left out.
"""

import html
import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
from urllib.parse import quote

from config import CATEGORIES
from fetch import Newsletter
from summarize import NewsletterSummary, Story


@dataclass(frozen=True)
class Digest:
    """The finished email, ready to send."""

    subject: str
    text: str   # plain-text version (for mail apps that do not show HTML)
    html: str   # the nicer version most people will see


@dataclass(frozen=True)
class Item:
    """One line in the digest: a story plus the newsletter it came from."""

    story: Story
    newsletter: str   # display name of the sender, e.g. "Morning Brew"
    source_url: str | None = None   # where the newsletter name links: the email in Gmail


def _sender_name(sender: str) -> str:
    """Return the display name from a From header.

    'Morning Brew <crew@morningbrew.com>' -> 'Morning Brew'.
    parseaddr() splits a header into (display name, address). If there is no
    display name we fall back to the address, and then to the raw header.
    """
    name, address = parseaddr(sender)
    return name or address or sender


def _safe_url(url: str | None) -> str | None:
    """Only allow web links. Anything else (javascript:, data:...) is dropped.

    Link addresses come from emails we do not control, so we check them
    before putting them in an HTML href.
    """
    if url and url.lower().startswith(("http://", "https://")):
        return url
    return None


def gmail_fallback_url(address: str | None, message_id: str | None) -> str | None:
    """Build a Gmail search link that opens one email by its Message-ID header.

    Gmail's search understands rfc822msgid:<id>. The id is URL-encoded so
    characters like < > + = & # cannot break the link. Returns None if either
    piece is missing.
    """
    message_id = (message_id or "").strip().strip("<>").strip()
    if not address or not message_id:
        return None
    return (
        f"https://mail.google.com/mail/?authuser={quote(address.strip(), safe='@')}"
        f"#search/rfc822msgid%3A{quote(message_id, safe='')}"
    )


def gmail_thread_url(address: str | None, thread_id: str | None) -> str | None:
    """Build a link that opens the email's conversation directly in Gmail.

    `thread_id` is the hex form of Gmail's X-GM-THRID. Returns None if either
    piece is missing or the id is not plain hex.
    """
    thread_id = (thread_id or "").strip().lower()
    if not address or not re.fullmatch(r"[0-9a-f]+", thread_id):
        return None
    return f"https://mail.google.com/mail/?authuser={quote(address.strip(), safe='@')}#all/{thread_id}"


def _source_url(item: Newsletter, gmail_address: str | None) -> str | None:
    """The link for the newsletter name: the Gmail thread, else a Message-ID search.

    (item.web_url is still collected by fetch.py but no longer used here.)
    """
    return _safe_url(
        gmail_thread_url(gmail_address, item.thread_id)
        or gmail_fallback_url(gmail_address, item.message_id)
    )


def _organize(
    newsletters: list[Newsletter], results: list[NewsletterSummary | str],
    gmail_address: str | None = None,
) -> tuple[dict[str, list[Item]], list[tuple[str, str]], int, int]:
    """Turn raw results into (topics, failures, skipped_count, newsletter_count).

    - topics maps each category to its stories, in the order of CATEGORIES in
      config.py. Categories with no stories are left out. Within a topic,
      stories keep inbox order (first email first).
    - Emails flagged skip are only counted, never shown.
    - Failures (a string note instead of a summary) are returned as
      (sender name, note) pairs.
    - newsletter_count is how many different senders contributed stories.
    """
    grouped: dict[str, list[Item]] = {name: [] for name in CATEGORIES}
    failures: list[tuple[str, str]] = []
    contributors: set[str] = set()
    skipped = 0

    for item, result in zip(newsletters, results):
        name = _sender_name(item.sender)
        if isinstance(result, str):
            failures.append((name, result))
        elif result.skip:
            skipped += 1
        else:
            source_url = _source_url(item, gmail_address)
            for story in result.stories:
                grouped[story.category].append(Item(story, name, source_url))
            if result.stories:
                contributors.add(parseaddr(item.sender)[1].lower() or item.sender)

    topics = {category: items for category, items in grouped.items() if items}
    return topics, failures, skipped, len(contributors)


def _plural(count: int, noun: str) -> str:
    """plural(2, 'newsletter') -> '2 newsletters'."""
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _header_line(newsletter_count: int, story_count: int) -> str:
    """e.g. '3 newsletters · 12 stories'."""
    stories = f"{story_count} " + ("story" if story_count == 1 else "stories")
    return f"{_plural(newsletter_count, 'newsletter')} · {stories}"


def _footer_line(skipped: int) -> str | None:
    """e.g. '2 non-newsletter emails skipped.' (None when nothing was skipped)."""
    if not skipped:
        return None
    return f"{_plural(skipped, 'non-newsletter email')} skipped."


def _story_html(item: Item) -> str:
    """One story: bold headline (a link when we have a URL), the newsletter
    name in gray parentheses (a link to the original email in Gmail when
    we have one), then the sentence on the next line.

    html.escape turns < > & " into harmless codes, so text from an email can
    never inject markup into our digest.
    """
    title = html.escape(item.story.title)
    url = _safe_url(item.story.url)
    if url:
        title = f'<a href="{html.escape(url, quote=True)}" style="{_TITLE_LINK}">{title}</a>'
    else:
        title = f'<span style="{_TITLE_PLAIN}">{title}</span>'
    name = html.escape(item.newsletter)
    source_url = _safe_url(item.source_url)
    if source_url:
        source = (f'<span style="{_SOURCE}">(<a href="{html.escape(source_url, quote=True)}" '
                  f'style="{_SOURCE_LINK}">{name}</a>)</span>')
    else:
        source = f'<span style="{_SOURCE}">({name})</span>'
    return f'<p style="{_STORY}">{title} {source}<br>{html.escape(item.story.summary)}</p>'


def _story_text(item: Item) -> str:
    """Plain-text version of a story: 'Title (Newsletter): sentence' plus the link on its own line."""
    line = f"- {item.story.title} ({item.newsletter}): {item.story.summary}"
    url = _safe_url(item.story.url)
    source_url = _safe_url(item.source_url)
    return line + (f"\n  {url}" if url else "") + (f"\n  Newsletter: {source_url}" if source_url else "")


def build_digest(
    newsletters: list[Newsletter],
    results: list[NewsletterSummary | str],
    when: datetime,
    gmail_address: str | None = None,
) -> Digest:
    """Assemble the digest from newsletters and their summaries.

    `when` is passed in (instead of calling datetime.now() in here) so tests
    get the same output every time. `gmail_address` is used only to build the
    Gmail links on the newsletter names. All styles are inline (written on each
    tag) because many mail apps ignore <style> blocks.
    """
    topics, failures, skipped, newsletter_count = _organize(newsletters, results, gmail_address)
    story_count = sum(len(items) for items in topics.values())
    subject = f"Newsletter digest: {when:%a %b} {when.day} ({_plural(newsletter_count, 'newsletter')})"
    header = _header_line(newsletter_count, story_count)
    footer = _footer_line(skipped)

    text: list[str] = [subject, header, ""]
    sections: list[str] = []

    for category, items in topics.items():
        heading = f"{category} ({len(items)})"
        text.append(heading.upper())
        text.extend(_story_text(item) for item in items)
        text.append("")
        sections.append(
            f'<h2 style="{_HEADING}">{html.escape(heading)}</h2>' + "".join(_story_html(item) for item in items)
        )

    if failures:
        text.append("COULD NOT SUMMARIZE")
        rows = []
        for name, note in failures:
            text.append(f"- {name} {note}")
            rows.append(f'<p style="{_STORY}">{html.escape(name)} <i>{html.escape(note)}</i></p>')
        text.append("")
        sections.append(f'<h2 style="{_HEADING}">Could not summarize</h2>' + "".join(rows))

    if footer:
        text.append(footer)

    page = (
        f'<div style="{_PAGE}"><div style="{_WRAP}">'
        f'<p style="{_HEADER}">{html.escape(header)}</p>'
        + "".join(sections)
        + (f'<p style="{_FOOTER}">{html.escape(footer)}</p>' if footer else "")
        + "</div></div>"
    )
    return Digest(subject=subject, text="\n".join(text).rstrip() + "\n", html=page)


# --- Inline styles, kept in one place so the design is easy to tweak ---
_FONT = "font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;"
_PAGE = f"{_FONT}background:#ffffff;padding:24px 12px;"
_WRAP = "max-width:600px;margin:0 auto;"
_HEADER = "font-size:14px;font-weight:600;color:#374151;margin:0 0 8px;"
_HEADING = (
    "font-size:19px;line-height:1.3;font-weight:700;color:#111827;"
    "margin:32px 0 16px;padding:0 0 8px;border-bottom:2px solid #e5e7eb;"
)
_STORY = "font-size:15px;line-height:1.5;color:#374151;margin:0 0 16px;"
_TITLE_LINK = "font-size:16px;font-weight:700;color:#1a56db;text-decoration:none;"
_TITLE_PLAIN = "font-size:16px;font-weight:700;color:#111827;"
_SOURCE = "font-size:13px;color:#9ca3af;"
_SOURCE_LINK = "font-size:13px;color:#6b7280;text-decoration:underline;"
_FOOTER = "font-size:12px;color:#6b7280;margin:32px 0 0;"
