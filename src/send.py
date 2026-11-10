"""Send the digest through Gmail's outgoing mail server (SMTP).

SMTP is the standard protocol for sending email, the counterpart of IMAP
(which reads it). Python's smtplib handles it, so no extra package is needed.
"""

import smtplib
from email.message import EmailMessage

from config import SMTP_HOST, SMTP_PORT, Credentials
from digest import Digest


class SendError(Exception):
    """Raised for expected problems (bad login, no network, rejected recipient)."""


def build_message(digest: Digest, sender: str, recipient: str) -> EmailMessage:
    """Wrap the digest in an email message with plain-text and HTML versions.

    set_content() sets the plain-text part; add_alternative() attaches the HTML
    part. A mail app shows the HTML if it can and falls back to the text.
    """
    message = EmailMessage()
    message["Subject"] = digest.subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(digest.text)
    message.add_alternative(digest.html, subtype="html")
    return message


def send_digest(digest: Digest, creds: Credentials, recipient: str) -> None:
    """Send the digest from creds.address to recipient. Raises SendError on failure.

    We never print the password or the message body.
    """
    message = build_message(digest, creds.address, recipient)
    try:
        # SMTP_SSL = encrypted from the start. "with" closes the connection for us.
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.login(creds.address, creds.app_password)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise SendError("Gmail rejected the login. Check GMAIL_APP_PASSWORD.") from None
    except smtplib.SMTPRecipientsRefused:
        raise SendError("Gmail refused the recipient address. Check DIGEST_TO.") from None
    except smtplib.SMTPException as problem:
        raise SendError(f"Could not send the digest ({type(problem).__name__}).") from None
    except OSError as problem:  # no internet, timeout, etc.
        raise SendError(f"Could not reach Gmail to send ({problem}).") from None
