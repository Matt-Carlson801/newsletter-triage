"""Build the daily digest email (subject, plain-text body, HTML body).

This file only builds text. It never touches the network, so it is easy to
test with fake data. send.py is the file that actually sends the result.
"""

import html
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr

from config import CATEGORIES
from fetch import Newsletter
from summarize import NewsletterSummary


@dataclass(frozen=True)
class Digest:
    """The finished email, ready to send."""

    subject: str
    text: str   # plain-text version (for mail apps that do not show HTML)
    html: str   # the nicer version most people will see


def _sender_name(sender: str) -> str:
    """'Morning Brew <crew@morningbrew.com>' -> 'Morning Brew'.

    parseaddr() splits a From header into (display name, address). We show the
    name if there is one, otherwise the address.
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


def _group_by_category(
    newsletters: list[Newsletter], results: list[NewsletterSummary | str]
) -> tuple[dict[str, list[tuple[Newsletter, NewsletterSummary]]], list[tuple[Newsletter, str]]]:
    """Split results into {category: [(newsletter, summary), ...]} plus a list of failures.

    Categories come out in the order of the CATEGORIES list in config.py,
    so the digest always has the same layout. Empty categories are left out.
    """
    by_category: dict[str, list[tuple[Newsletter, NewsletterSummary]]] = {}
    failures: list[tuple[Newsletter, str]] = []
    for item, result in zip(newsletters, results):
        if isinstance(result, str):  # a "(summary unavailable...)" note
            failures.append((item, result))
        else:
            by_category.setdefault(result.category, []).append((item, result))
    ordered = {name: by_category[name] for name in CATEGORIES if name in by_category}
    return ordered, failures


def _subject(count: int, when: datetime) -> str:
    """e.g. 'Newsletter digest: Mon Nov 10 (3 newsletters)'."""
    noun = "newsletter" if count == 1 else "newsletters"
    return f"Newsletter digest: {when:%a %b} {when.day} ({count} {noun})"


def build_digest(
    newsletters: list[Newsletter],
    results: list[NewsletterSummary | str],
    when: datetime,
) -> Digest:
    """Assemble the digest from newsletters and their summaries.

    `when` is passed in (instead of calling datetime.now() in here) so tests
    get the same output every time.
    """
    grouped, failures = _group_by_category(newsletters, results)
    subject = _subject(len(newsletters), when)

    # We build the plain-text and HTML versions side by side, as lists of lines.
    text: list[str] = [subject, ""]
    body: list[str] = []

    for category, entries in grouped.items():
        text.append(category.upper())
        body.append(f'<h2 style="{_H2}">{html.escape(category)}</h2>')
        for item, summary in entries:
            name = _sender_name(item.sender)
            text.append(f"{name}: {item.subject}")
            body.append(f'<p style="{_SOURCE}"><b>{html.escape(name)}</b> &middot; {html.escape(item.subject)}</p>')
            body.append('<ul style="margin:0 0 16px;padding-left:20px;">')
            for story in summary.stories:
                url = _safe_url(story.url)
                text.append(f"  - {story.summary}" + (f"\n    {url}" if url else ""))
                # html.escape turns < > & " into harmless codes, so text from an
                # email can never inject markup into our digest.
                line = html.escape(story.summary)
                if url:
                    line += f' <a href="{html.escape(url, quote=True)}" style="color:#1a56db;">Read &rarr;</a>'
                body.append(f'<li style="margin-bottom:6px;">{line}</li>')
            body.append("</ul>")
            text.append("")

    if failures:
        text.append("COULD NOT SUMMARIZE")
        body.append(f'<h2 style="{_H2}">Could not summarize</h2><ul style="margin:0 0 16px;padding-left:20px;">')
        for item, note in failures:
            name = _sender_name(item.sender)
            text.append(f"  - {name}: {item.subject} {note}")
            body.append(f"<li>{html.escape(name)}: {html.escape(item.subject)} <i>{html.escape(note)}</i></li>")
        body.append("</ul>")
        text.append("")

    page = (
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
        'max-width:640px;margin:0 auto;color:#222;line-height:1.45;">'
        f'<h1 style="font-size:20px;margin:0 0 4px;">{html.escape(subject)}</h1>'
        + "".join(body)
        + "</div>"
    )
    return Digest(subject=subject, text="\n".join(text).rstrip() + "\n", html=page)


# Inline styles: many mail apps ignore <style> blocks, so styles go on each tag.
_H2 = "font-size:15px;text-transform:uppercase;letter-spacing:.04em;color:#555;border-bottom:1px solid #ddd;padding-bottom:4px;margin:24px 0 8px;"
_SOURCE = "margin:8px 0 4px;"
