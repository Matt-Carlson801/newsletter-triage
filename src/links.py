"""Find the links in a newsletter and throw away the ones that are not stories.

Two jobs live here:
  1. extract_links(): pull out every link WITH its clickable text.
  2. filter_links(): drop images, fonts, tracking pixels, social buttons,
     unsubscribe/preference links and sponsor links.

Only links that survive filter_links() are ever sent to Gemini.
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

# A very simple pattern for "something that looks like a web link".
LINK_PATTERN = re.compile(r"https?://[^\s<>\"')\]]+")

# --- What counts as "not a story link" (edit these lists to tune the filter) ---
FILE_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp",  # images
    ".woff", ".woff2", ".ttf", ".otf", ".eot",                         # fonts
    ".css", ".js",                                                     # page assets
)
SOCIAL_DOMAINS = (
    "twitter.com", "x.com", "facebook.com", "instagram.com", "linkedin.com",
    "tiktok.com", "pinterest.com", "threads.net", "bsky.app", "t.me", "wa.me",
)
# Words that mean "this link is about managing the subscription".
UNSUBSCRIBE_WORDS = (
    "unsubscribe", "opt-out", "optout", "manage preferences", "manage-preferences",
    "email preferences", "email-preferences", "update your preferences",
    "update profile", "manage subscription",
)
SPONSOR_WORDS = ("sponsor", "advertis", "promoted", "paid partner")
SPONSOR_UTM_MEDIUMS = {"ad", "ads", "paid", "sponsor", "sponsored", "advertising"}
TRACKING_WORDS = ("pixel", "beacon", "track/open", "open.gif", "/wf/open")


@dataclass(frozen=True)
class Link:
    """One link: the words the reader clicks, and where it goes."""

    text: str  # may be empty (plain-text emails often have bare URLs)
    url: str


class _AnchorExtractor(HTMLParser):
    """Collects <a href="...">text</a> pairs from an HTML email."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[Link] = []
        self._href: str | None = None  # the link we are currently inside, if any
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = " ".join(" ".join(self._text).split())
            self.links.append(Link(text=text, url=self._href.strip()))
            self._href = None


def extract_links(plain: str, html: str) -> list[Link]:
    """Return every http(s) link, with its text, without duplicate URLs.

    HTML links come first because they carry text. Bare URLs found in the
    plain-text version are added only if the HTML did not already have them.
    <img> tags are ignored, so image and pixel sources never get in.
    """
    parser = _AnchorExtractor()
    parser.feed(html)
    found = parser.links + [Link("", url) for url in LINK_PATTERN.findall(plain)]

    unique: dict[str, Link] = {}  # URL -> Link; a dict keeps first-seen order
    for link in found:
        url = link.url.rstrip(".,;")
        if not url.lower().startswith(("http://", "https://")):
            continue  # skips mailto:, tel:, and in-page #anchors
        if url not in unique or (link.text and not unique[url].text):
            unique[url] = Link(link.text, url)  # prefer the copy that has text
    return list(unique.values())


def header_urls(unsubscribe_header: str | None) -> set[str]:
    """Pull the web URLs out of a List-Unsubscribe header like '<https://x>, <mailto:y>'."""
    return set(LINK_PATTERN.findall(unsubscribe_header or ""))


def _reason_to_drop(link: Link, unsubscribe_urls: set[str]) -> str | None:
    """Return why a link should be dropped, or None if it should be kept."""
    parts = urlparse(link.url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    text = link.text.lower()
    url = link.url.lower()

    if link.url in unsubscribe_urls:
        return "unsubscribe"
    if parts.path.lower().endswith(FILE_EXTENSIONS):
        return "file"
    if any(host == d or host.endswith("." + d) for d in SOCIAL_DOMAINS):
        return "social"
    if any(word in text or word in url for word in UNSUBSCRIBE_WORDS):
        return "unsubscribe"
    if any(word in url for word in TRACKING_WORDS):
        return "tracking"
    medium = parse_qs(parts.query).get("utm_medium", [""])[0].lower()
    if medium in SPONSOR_UTM_MEDIUMS or any(w in text or w in url for w in SPONSOR_WORDS):
        return "sponsor"
    return None


def filter_links(links: list[Link], unsubscribe_header: str | None = None) -> list[Link]:
    """Keep only links that could plausibly be a story."""
    blocked = header_urls(unsubscribe_header)
    return [link for link in links if _reason_to_drop(link, blocked) is None]
