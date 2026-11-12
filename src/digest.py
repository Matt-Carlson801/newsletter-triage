"""Build the daily digest email (subject, plain-text body, HTML body).

This file only builds text. It never touches the network, so it is easy to
test with fake data. send.py is the file that actually sends the result.

Layout: a header line, then (if any story was reported by two or more
newsletters) an "In multiple newsletters today" section, then one section per topic (for example "AI & Tech (7)"),
then a "could not summarize" section if any summary failed, then a one-line
footer. Stories from every newsletter are grouped by topic. A story is a bold
headline (the link), the newsletter name in gray parentheses, and on the next
line one sentence of context. Topics with no stories are left out.

Duplicate merging: build_digest can take groups of story positions that
describe the same story. A group becomes ONE story (the first one's headline,
link and sentence) followed by every source newsletter in the parentheses.
"""

import html
import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
from urllib.parse import quote

from config import CATEGORIES, REDIRECT_BASE
from fetch import Newsletter
from summarize import NewsletterSummary, Story


@dataclass(frozen=True)
class Digest:
    """The finished email, ready to send."""

    subject: str
    text: str   # plain-text version (for mail apps that do not show HTML)
    html: str   # the nicer version most people will see


@dataclass(frozen=True)
class Source:
    """One newsletter a story appeared in, with the link to its email."""

    name: str              # display name, e.g. "Morning Brew"
    url: str | None        # link to the email through the redirect page
    key: str               # lowercase sender address; tells newsletters apart


@dataclass(frozen=True)
class Item:
    """One line in the digest: a story plus the newsletter it came from.

    A merged story also lists the other newsletters that ran it in `also_in`.
    """

    story: Story
    newsletter: str   # display name of the sender, e.g. "Morning Brew"
    source_url: str | None = None   # where the newsletter name links: the email in Gmail
    sender_key: str = ""            # lowercase sender address (tells newsletters apart)
    also_in: tuple[Source, ...] = ()   # other newsletters, only set on merged stories

    @property
    def sources(self) -> list[Source]:
        """Every newsletter this story came from, the first story's newsletter first."""
        return [Source(self.newsletter, self.source_url, self.sender_key), *self.also_in]


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


# A Gmail thread id: 1 to 32 lowercase hex characters.
_THREAD_ID_RE = re.compile(r"[0-9a-f]{1,32}")
# A plain gmail.com address: no spaces, quotes or angle brackets.
_GMAIL_ADDRESS_RE = re.compile(r"[a-z0-9][a-z0-9._+-]{0,63}@gmail\.com", re.IGNORECASE)
_MAX_MESSAGE_ID = 512


def _clean_address(address: str | None) -> str | None:
    """Return the address if it is a plain gmail.com address, otherwise None."""
    address = (address or "").strip()
    return address if _GMAIL_ADDRESS_RE.fullmatch(address) else None


def _address_part(address: str) -> str:
    """URL-encode the address for the fragment. '+' becomes %2B so it survives."""
    return quote(address, safe="@")


def redirect_message_url(address: str | None, message_id: str | None) -> str | None:
    """Build a redirect-page link that finds one email by its Message-ID header.

    The redirect page (docs/open.html) turns this into a Gmail search for
    rfc822msgid:<id>. The id is URL-encoded so characters like < > + = & #
    cannot break the link. Returns None if the address is not a plain
    gmail.com address, or the id is missing, too long, or contains whitespace.
    """
    address = _clean_address(address)
    message_id = (message_id or "").strip().strip("<>").strip()
    if not address or not message_id or len(message_id) > _MAX_MESSAGE_ID:
        return None
    if re.search(r"[\s\x00-\x1f\x7f]", message_id):
        return None
    return f"{REDIRECT_BASE}#m={quote(message_id, safe='')}&a={_address_part(address)}"


def redirect_thread_url(address: str | None, thread_id: str | None) -> str | None:
    """Build a redirect-page link that opens the email's conversation in Gmail.

    `thread_id` is the hex form of Gmail's X-GM-THRID. Returns None if the
    address is not a plain gmail.com address or the id is not 1 to 32 hex
    characters.
    """
    address = _clean_address(address)
    thread_id = (thread_id or "").strip().lower()
    if not address or not _THREAD_ID_RE.fullmatch(thread_id):
        return None
    return f"{REDIRECT_BASE}#t={thread_id}&a={_address_part(address)}"


def _source_url(item: Newsletter, gmail_address: str | None) -> str | None:
    """The link for the newsletter name: the redirect page with a thread id, else a Message-ID.

    (item.web_url is still collected by fetch.py but no longer used here.)
    """
    return _safe_url(
        redirect_thread_url(gmail_address, item.thread_id)
        or redirect_message_url(gmail_address, item.message_id)
    )


def _collect(
    newsletters: list[Newsletter], results: list[NewsletterSummary | str],
    gmail_address: str | None = None,
) -> tuple[list[Item], list[tuple[str, str]], int, int]:
    """Walk the results once and return (items, failures, skipped, newsletter_count).

    `items` holds every story in "flat order": first newsletter's stories, then
    the second's, and so on. Merge groups are positions in this list, and
    story_headlines() uses the same order, so the two always line up.
    """
    items: list[Item] = []
    failures: list[tuple[str, str]] = []
    contributors: set[str] = set()
    skipped = 0

    for newsletter, result in zip(newsletters, results):
        name = _sender_name(newsletter.sender)
        if isinstance(result, str):
            failures.append((name, result))
        elif result.skip:
            skipped += 1
        else:
            key = parseaddr(newsletter.sender)[1].lower() or newsletter.sender
            source_url = _source_url(newsletter, gmail_address)
            items.extend(Item(story, name, source_url, key) for story in result.stories)
            if result.stories:
                contributors.add(key)
    return items, failures, skipped, len(contributors)


def story_headlines(results: list[NewsletterSummary | str]) -> list[str]:
    """One "title: sentence" line per story, in flat order. Used for the duplicate check.

    Only the headline and sentence: no links, no sender names, no addresses.
    """
    return [
        f"{story.title}: {story.summary}"
        for result in results if not isinstance(result, str) and not result.skip
        for story in result.stories
    ]


def _group_by_category(items: list[Item]) -> dict[str, list[Item]]:
    """Group items by topic in the order of CATEGORIES; empty topics are left out."""
    grouped: dict[str, list[Item]] = {name: [] for name in CATEGORIES}
    for item in items:
        grouped[item.story.category].append(item)
    return {category: found for category, found in grouped.items() if found}


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
    items, failures, skipped, newsletter_count = _collect(newsletters, results, gmail_address)
    return _group_by_category(items), failures, skipped, newsletter_count


def merge_items(items: list[Item], groups: list[list[int]] | None) -> list[Item]:
    """Fold each group of duplicate stories into one Item.

    The merged story keeps the FIRST member's headline, sentence, link and
    category, and lists every distinct newsletter of the group (the same
    newsletter twice counts once). It sits where its first member was; the
    other members are removed. Bad groups are ignored again here (out of range,
    number reused, fewer than 2), so this function is safe on its own.
    """
    used: set[int] = set()
    merged_at: dict[int, Item] = {}
    for group in groups or []:
        members = sorted({n for n in group if isinstance(n, int) and 0 <= n < len(items) and n not in used})
        if len(members) < 2:
            continue
        used.update(members)
        first = items[members[0]]
        seen = {first.sender_key}
        extra: list[Source] = []
        for number in members[1:]:
            for source in items[number].sources:
                if source.key not in seen:
                    seen.add(source.key)
                    extra.append(source)
        merged_at[members[0]] = Item(first.story, first.newsletter, first.source_url, first.sender_key, tuple(extra))

    result: list[Item] = []
    for number, item in enumerate(items):
        if number in merged_at:
            result.append(merged_at[number])
        elif number not in used:
            result.append(item)
    return result


def _plural(count: int, noun: str) -> str:
    """plural(2, 'newsletter') -> '2 newsletters'."""
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _header_line(newsletter_count: int, story_count: int, multi_count: int = 0) -> str:
    """e.g. '3 newsletters · 12 stories' or '... · 2 in multiple newsletters'.

    story_count counts merged stories once.
    """
    stories = f"{story_count} " + ("story" if story_count == 1 else "stories")
    line = f"{_plural(newsletter_count, 'newsletter')} · {stories}"
    if multi_count:
        line += f" · {multi_count} in multiple newsletters"
    return line


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
    names = []
    for found in item.sources:
        name = html.escape(found.name)
        source_url = _safe_url(found.url)
        if source_url:
            name = f'<a href="{html.escape(source_url, quote=True)}" style="{_SOURCE_LINK}">{name}</a>'
        names.append(name)
    source = f'<span style="{_SOURCE}">({", ".join(names)})</span>'
    return f'<p style="{_STORY}">{title} {source}<br>{html.escape(item.story.summary)}</p>'


def _story_text(item: Item) -> str:
    """Plain-text version of a story: 'Title (Newsletter): sentence' plus the link on its own line."""
    names = ", ".join(found.name for found in item.sources)
    line = f"- {item.story.title} ({names}): {item.story.summary}"
    url = _safe_url(item.story.url)
    if url:
        line += f"\n  {url}"
    if len(item.sources) == 1:
        source_url = _safe_url(item.source_url)
        return line + (f"\n  Newsletter: {source_url}" if source_url else "")
    for found in item.sources:  # a merged story: one email link per newsletter
        source_url = _safe_url(found.url)
        if source_url:
            line += f"\n  {found.name}: {source_url}"
    return line


def build_digest(
    newsletters: list[Newsletter],
    results: list[NewsletterSummary | str],
    when: datetime,
    gmail_address: str | None = None,
    merge_groups: list[list[int]] | None = None,
) -> Digest:
    """Assemble the digest from newsletters and their summaries.

    `when` is passed in (instead of calling datetime.now() in here) so tests
    get the same output every time. `gmail_address` is used only to build the
    Gmail links on the newsletter names. All styles are inline (written on each
    tag) because many mail apps ignore <style> blocks.

    `merge_groups` (optional) are groups of story positions that are the same
    story; see merge_items(). Merged stories that came from two or more
    different newsletters go in a section at the top and are not repeated
    under their topic.
    """
    all_items, failures, skipped, newsletter_count = _collect(newsletters, results, gmail_address)
    items_after_merge = merge_items(all_items, merge_groups)
    # sorted() is stable, so equal source counts keep their original order.
    multi = sorted((i for i in items_after_merge if len(i.sources) > 1), key=lambda i: -len(i.sources))
    topics = _group_by_category([i for i in items_after_merge if len(i.sources) == 1])
    story_count = len(items_after_merge)
    subject = f"Newsletter digest: {when:%a %b} {when.day} ({_plural(newsletter_count, 'newsletter')})"
    header = _header_line(newsletter_count, story_count, len(multi))
    footer = _footer_line(skipped)

    text: list[str] = [subject, header, ""]
    sections: list[str] = []

    if multi:
        heading = f"In multiple newsletters today ({len(multi)})"
        text.append(heading.upper())
        text.extend(_story_text(item) for item in multi)
        text.append("")
        sections.append(
            f'<h2 style="{_HEADING}">{html.escape(heading)}</h2>' + "".join(_story_html(item) for item in multi)
        )

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
