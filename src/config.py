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
