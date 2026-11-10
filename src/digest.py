"""Build the daily digest email (subject, plain-text body, HTML body).

This file only builds text. It never touches the network, so it is easy to
test with fake data. send.py is the file that actually sends the result.

Layout: a header line, then one "card" per newsletter (emails from the same
sender are merged into one card), then a one-line footer.
"""

import html
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr

from config import CATEGORIES, MAX_STORIES, SKIP_CATEGORY
from fetch import Newsletter
from summarize import NewsletterSummary, Story


@dataclass(frozen=True)
class Digest:
    """The finished email, ready to send."""

    subject: str
    text: str   # plain-text version (for mail apps that do not show HTML)
    html: str   # the nicer version most people will see


@dataclass
class Block:
    """One card in the digest: everything from one sender, merged."""

    name: str              # display name of the sender
    category: str
    emails: int            # how many emails were merged into this card
    stories: list[Story]


def _sender_key(sender: str) -> tuple[str, str]:
    """Return (merge key, display name) for a From header.

    'Morning Brew <crew@morningbrew.com>' -> ('crew@morningbrew.com', 'Morning Brew').
    parseaddr() splits a header into (display name, address). Two emails with
    the same address are treated as the same sender.
    """
    name, address = parseaddr(sender)
    key = address.lower() or sender
    return key, name or address or sender


def _safe_url(url: str | None) -> str | None:
    """Only allow web links. Anything else (javascript:, data:...) is dropped.

    Link addresses come from emails we do not control, so we check them
    before putting them in an HTML href.
    """
    if url and url.lower().startswith(("http://", "https://")):
        return url
    return None


def _organize(
    newsletters: list[Newsletter], results: list[NewsletterSummary | str]
) -> tuple[list[Block], list[tuple[str, str]], int]:
    """Turn raw results into (cards, failures, skipped_count).

    - Emails in the "Skip" category are only counted, never shown.
    - Emails from the same sender merge into one card, keeping the category
      of that sender's first email. The card keeps at most MAX_STORIES stories.
    - Cards are ordered by the CATEGORIES list in config.py, so the layout is
      predictable. sorted() is stable: same-category cards keep inbox order.
    - Failures (a string note instead of a summary) are returned as
      (sender name, note) pairs.
    """
    blocks: dict[str, Block] = {}
    failures: list[tuple[str, str]] = []
    skipped = 0

    for item, result in zip(newsletters, results):
        key, name = _sender_key(item.sender)
        if isinstance(result, str):
            failures.append((name, result))
        elif result.category == SKIP_CATEGORY:
            skipped += 1
        elif key in blocks:
            blocks[key].emails += 1
            blocks[key].stories.extend(result.stories)
        else:
            blocks[key] = Block(name, result.category, 1, list(result.stories))

    for block in blocks.values():
        del block.stories[MAX_STORIES:]  # keep only the first MAX_STORIES

    ordered = sorted(blocks.values(), key=lambda b: CATEGORIES.index(b.category))
    return ordered, failures, skipped


def _plural(count: int, noun: str) -> str:
    """plural(2, 'newsletter') -> '2 newsletters'."""
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _header_line(blocks: list[Block]) -> str:
    """e.g. '3 newsletters · AI & Tech, Marketing & Sales'."""
    categories = list(dict.fromkeys(b.category for b in blocks))  # unique, in order
    line = _plural(len(blocks), "newsletter")
    return line + (" · " + ", ".join(categories) if categories else "")


def _footer_line(skipped: int) -> str | None:
    """e.g. '2 non-newsletter emails skipped.' (None when nothing was skipped)."""
    if not skipped:
        return None
    return f"{_plural(skipped, 'non-newsletter email')} skipped."


def build_digest(
    newsletters: list[Newsletter],
    results: list[NewsletterSummary | str],
    when: datetime,
) -> Digest:
    """Assemble the digest from newsletters and their summaries.

    `when` is passed in (instead of calling datetime.now() in here) so tests
    get the same output every time. All styles are inline (written on each
    tag) because many mail apps ignore <style> blocks.
    """
    blocks, failures, skipped = _organize(newsletters, results)
    subject = f"Newsletter digest: {when:%a %b} {when.day} ({_plural(len(blocks), 'newsletter')})"
    header = _header_line(blocks)
    footer = _footer_line(skipped)

    text: list[str] = [subject, header, ""]
    cards: list[str] = []

    for block in blocks:
        label = block.name + (f" ({block.emails} emails)" if block.emails > 1 else "")
        text.append(f"{label.upper()} · {block.category}")
        story_html = []
        for story in block.stories:
            url = _safe_url(story.url)
            # html.escape turns < > & " into harmless codes, so text from an
            # email can never inject markup into our digest.
            sentence = html.escape(story.summary)
            if url:  # the sentence itself is the link
                sentence = f'<a href="{html.escape(url, quote=True)}" style="{_LINK}">{sentence}</a>'
                text.append(f"- {story.summary}\n  {url}")
            else:
                text.append(f"- {story.summary}")
            story_html.append(f'<p style="{_STORY}">{sentence}</p>')
        text.append("")
        cards.append(
            f'<div style="{_CARD}">'
            f'<p style="{_LABEL}">{html.escape(label)} &middot; {html.escape(block.category)}</p>'
            + "".join(story_html)
            + "</div>"
        )

    if failures:
        text.append("COULD NOT SUMMARIZE")
        items = []
        for name, note in failures:
            text.append(f"- {name} {note}")
            items.append(f"<p style=\"{_STORY}\">{html.escape(name)} <i>{html.escape(note)}</i></p>")
        text.append("")
        cards.append(
            f'<div style="{_CARD}"><p style="{_LABEL}">Could not summarize</p>' + "".join(items) + "</div>"
        )

    if footer:
        text.append(footer)

    page = (
        f'<div style="{_PAGE}"><div style="{_WRAP}">'
        f'<p style="{_HEADER}">{html.escape(header)}</p>'
        + "".join(cards)
        + (f'<p style="{_FOOTER}">{html.escape(footer)}</p>' if footer else "")
        + "</div></div>"
    )
    return Digest(subject=subject, text="\n".join(text).rstrip() + "\n", html=page)


# --- Inline styles, kept in one place so the design is easy to tweak ---
_FONT = "font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;"
_PAGE = f"{_FONT}background:#f3f4f6;padding:24px 12px;"
_WRAP = "max-width:600px;margin:0 auto;"
_HEADER = "font-size:15px;font-weight:600;color:#111827;margin:0 0 20px 4px;"
_CARD = (
    "background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;"
    "padding:24px 26px 10px;margin:0 0 20px;"
)
_LABEL = "font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin:0 0 16px;"
_STORY = "font-size:16px;line-height:1.5;color:#111827;margin:0 0 16px;"
_LINK = "color:#1a56db;text-decoration:none;"
_FOOTER = "font-size:12px;color:#6b7280;margin:4px 0 0 4px;"
