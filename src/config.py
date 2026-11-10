"""Settings for the newsletter digest.

Secrets (your Gmail address and app password) come from environment
variables. Locally they are loaded from the .env file; in GitHub Actions
they will come from GitHub Secrets. Everything else is a plain constant.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# --- Plain settings (safe to commit, change them here in one place) ---
IMAP_HOST = "imap.gmail.com"      # Gmail's incoming-mail server
NEWSLETTER_LABEL = "Newsletters"  # the Gmail label your filter applies
LOOKBACK_HOURS = 24               # only look at emails newer than this

# Outgoing mail (Stage 3). Port 465 means the connection is encrypted from the first byte.
SMTP_HOST = "smtp.gmail.com"      # Gmail's outgoing-mail server
SMTP_PORT = 465

# Gemini settings. The model name lives here so swapping it is a one-line change.
GEMINI_MODEL = "gemini-3.5-flash-lite"  # free-tier "Flash-Lite" model (checked Nov 2026)
MAX_INPUT_CHARS = 30_000          # newsletters longer than this are cut before sending
MAX_STORIES = 5                   # most stories we keep per newsletter
MAX_LINKS_SENT = 120              # most candidate links sent to Gemini per newsletter

# Retry settings. On a temporary Gemini error we wait, then try again.
RETRY_DELAYS = (2, 4, 8)          # seconds to wait before retry 1, 2 and 3
RETRYABLE_CODES = (429, 503)      # 429 = rate limit, 503 = Gemini overloaded
PAUSE_BETWEEN_NEWSLETTERS = 1     # seconds; keeps us under the free tier's per-minute limit

# Gemini must pick exactly one of these for each newsletter.
CATEGORIES = [
    "AI & Tech",
    "Business & Finance",
    "Marketing & Sales",
    "Startups & Product",
    "Science & Health",
    "News & Politics",
    "Culture & Lifestyle",
    "Other",
]

# Path to the CSV log. __file__ is this file's location, so .parent.parent
# walks up from src/ to the project root regardless of where you run from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = PROJECT_ROOT / "data" / "newsletter_log.csv"


class ConfigError(Exception):
    """Raised when a required setting is missing."""


@dataclass(frozen=True)
class Credentials:
    """Holds the two secrets. frozen=True means they cannot be changed
    after creation, which avoids accidental edits."""

    address: str
    app_password: str


def load_credentials() -> Credentials:
    """Read the Gmail address and app password from the environment.

    Raises ConfigError with a friendly message if either is missing.
    """
    # Reads the .env file (if present) and adds its lines to os.environ.
    load_dotenv(PROJECT_ROOT / ".env")

    address = os.environ.get("GMAIL_ADDRESS", "").strip()
    # Google shows app passwords in groups of four with spaces; remove them.
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")

    missing = []
    if not address:
        missing.append("GMAIL_ADDRESS")
    if not app_password:
        missing.append("GMAIL_APP_PASSWORD")
    if missing:
        raise ConfigError(
            "Missing setting(s): " + ", ".join(missing)
            + ". Add them to your .env file (see .env.example)."
        )

    return Credentials(address=address, app_password=app_password)


def load_recipient() -> str:
    """Read DIGEST_TO: the address the daily digest is sent to.

    Kept separate from load_credentials() because only the sending step
    needs it. Raises ConfigError if it is missing.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    recipient = os.environ.get("DIGEST_TO", "").strip()
    if not recipient:
        raise ConfigError("Missing setting: DIGEST_TO. Add it to your .env file (see .env.example).")
    return recipient
