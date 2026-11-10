"""Read newsletters from Gmail over IMAP and turn them into simple objects.

IMAP is the standard protocol mail programs use to read a mailbox. Python
ships with a client for it (imaplib), and a parser for email messages
(email), so this file needs no extra packages.
"""

import email
import imaplib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from config import IMAP_HOST, LOOKBACK_HOURS, NEWSLETTER_LABEL, Credentials
from links import Link, extract_links, find_web_version

# IMAP wants dates like 09-Nov-2026 with English month names. We spell them
# out ourselves because strftime("%b") changes with the computer's language.
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class FetchError(Exception):
    """Raised for expected problems (bad login, missing label, no network)."""


@dataclass
class Newsletter:
    """One newsletter email, reduced to the fields we care about."""

    sender: str
    subject: str
    date: datetime
    body: str                    # plain text; used by the summarizer
    links: list[Link]            # every link with its text (filtered later, before Gemini)
    unsubscribe: str | None      # the List-Unsubscribe header, if present
    web_url: str | None = None   # the email's "view in browser" page, if it has one
    message_id: str | None = None  # the Message-ID header; lets us build a Gmail search link
    thread_id: str | None = None   # Gmail's thread id as hex (from X-GM-THRID); opens the email directly


class _TextExtractor(HTMLParser):
    """Collects the visible text from an HTML email (drops the tags)."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        # Called by the parser each time it finds text between tags.
        self.parts.append(data)


def html_to_text(html: str) -> str:
    """Strip the tags from HTML and return just the text."""
    extractor = _TextExtractor()
    extractor.feed(html)
    return " ".join(" ".join(extractor.parts).split())


def parse_message(raw: bytes) -> Newsletter:
    """Turn the raw bytes of one email into a Newsletter."""
    # policy.default gives us the modern API that decodes headers for us.
    msg: EmailMessage = email.message_from_bytes(raw, policy=policy.default)  # type: ignore[assignment]

    # An email can have a plain-text part, an HTML part, or both.
    plain_part = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    plain = plain_part.get_content() if plain_part else ""
    html = html_part.get_content() if html_part else ""

    # Prefer the plain text; fall back to text pulled out of the HTML.
    body = plain.strip() or html_to_text(html)

    try:
        date = parsedate_to_datetime(str(msg["Date"]))
        if date.tzinfo is None:  # some emails omit the timezone; assume UTC
            date = date.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        date = datetime.now(timezone.utc)  # missing or broken Date header

    unsubscribe = msg["List-Unsubscribe"]
    message_id = str(msg["Message-ID"] or "").strip()
    links = extract_links(plain, html)
    return Newsletter(
        sender=str(msg["From"] or "(unknown sender)"),
        subject=str(msg["Subject"] or "(no subject)"),
        date=date,
        body=body,
        links=links,
        unsubscribe=str(unsubscribe) if unsubscribe else None,
        web_url=find_web_version(links),
        message_id=message_id or None,
    )


# Gmail adds a custom IMAP field, X-GM-THRID: a big decimal number that
# identifies the conversation. The reply looks like: 1 (X-GM-THRID 1783... ...)
THREAD_ID_PATTERN = re.compile(rb"X-GM-THRID\s+(\d+)")


def parse_thread_id(parts: list) -> str | None:
    """Pull Gmail's thread id out of an IMAP FETCH reply and return it as hex.

    imaplib hands back a list. The first item is usually a tuple
    (the response line, the raw email), and Gmail may put X-GM-THRID in that
    line or in a short trailing item after the email, so we look at both.
    Gmail's web address uses the hex form of the number (e.g. 1783... -> 18ab...).
    Returns None if the field is missing.
    """
    for part in parts:
        line = part[0] if isinstance(part, tuple) else part
        if isinstance(line, bytes):
            found = THREAD_ID_PATTERN.search(line)
            if found:
                return format(int(found.group(1)), "x")
    return None


def connect(creds: Credentials) -> imaplib.IMAP4_SSL:
    """Open a secure connection to Gmail and log in."""
    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST)  # SSL = encrypted connection
        conn.login(creds.address, creds.app_password)
    except imaplib.IMAP4.error:
        raise FetchError(
            "Gmail rejected the login. Check GMAIL_ADDRESS and that "
            "GMAIL_APP_PASSWORD is an App Password (not your normal password)."
        ) from None
    except OSError as problem:  # no internet, DNS failure, timeout, etc.
        raise FetchError(f"Could not reach Gmail ({problem}). Check your internet connection.") from None
    return conn


def _imap_date(moment: datetime) -> str:
    """Format a date the way IMAP expects, e.g. 09-Nov-2026."""
    return f"{moment.day:02d}-{MONTHS[moment.month - 1]}-{moment.year}"


def fetch_newsletters(conn: imaplib.IMAP4_SSL) -> list[Newsletter]:
    """Return newsletters in the Newsletters label from the last 24 hours."""
    # readonly=True: we only look, so nothing gets marked as read or changed.
    status, _ = conn.select(f'"{NEWSLETTER_LABEL}"', readonly=True)
    if status != "OK":
        raise FetchError(
            f"Could not open the '{NEWSLETTER_LABEL}' label in Gmail. "
            "Check that the label exists and the spelling matches."
        )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    # IMAP can only search by whole days, so we ask for "since that date"
    # (a little too much) and then filter precisely to 24 hours below.
    status, data = conn.search(None, "SINCE", _imap_date(cutoff))
    if status != "OK":
        raise FetchError("Gmail could not run the search.")

    newsletters = []
    for message_id in data[0].split():
        # BODY.PEEK[] downloads the whole message without marking it read.
        # X-GM-THRID also asks Gmail for the conversation id (for the link).
        status, parts = conn.fetch(message_id, "(X-GM-THRID BODY.PEEK[])")
        if status != "OK" or not parts or not isinstance(parts[0], tuple):
            continue  # skip a message we could not download
        newsletter = parse_message(parts[0][1])
        newsletter.thread_id = parse_thread_id(parts)
        if newsletter.date >= cutoff:
            newsletters.append(newsletter)
    return newsletters
