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

# IMAP wants dates like 09-Nov-2026 with English month names. We spell them
# out ourselves because strftime("%b") changes with the computer's language.
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# A very simple pattern for "something that looks like a web link".
LINK_PATTERN = re.compile(r"https?://[^\s<>\"')\]]+")


class FetchError(Exception):
    """Raised for expected problems (bad login, missing label, no network)."""


@dataclass
class Newsletter:
    """One newsletter email, reduced to the fields we care about."""

    sender: str
    subject: str
    date: datetime
    body: str                    # plain text; used by the summarizer in Stage 2
    links: list[str]
    unsubscribe: str | None      # the List-Unsubscribe header, if present


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


def extract_links(*texts: str) -> list[str]:
    """Find every http(s) link in the given texts, without duplicates.

    *texts means "accept any number of strings". We search both the plain
    and HTML versions of an email because newsletters often keep their links
    only in the HTML.
    """
    seen: dict[str, None] = {}  # a dict remembers insertion order; we use it as an ordered set
    for text in texts:
        for url in LINK_PATTERN.findall(text):
            seen[url.rstrip(".,;")] = None
    return list(seen)


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
    return Newsletter(
        sender=str(msg["From"] or "(unknown sender)"),
        subject=str(msg["Subject"] or "(no subject)"),
        date=date,
        body=body,
        links=extract_links(plain, html),
        unsubscribe=str(unsubscribe) if unsubscribe else None,
    )


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
        status, parts = conn.fetch(message_id, "(BODY.PEEK[])")
        if status != "OK" or not parts or not isinstance(parts[0], tuple):
            continue  # skip a message we could not download
        newsletter = parse_message(parts[0][1])
        if newsletter.date >= cutoff:
            newsletters.append(newsletter)
    return newsletters
