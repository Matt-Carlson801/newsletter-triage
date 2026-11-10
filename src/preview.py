"""Fake sample data for `--preview`, so you can see the digest design without
touching your inbox, Gemini, or SMTP.

Everything here is invented: the newsletter names, the stories and the links
(example.com is a domain reserved for examples). Nine senders send ten emails:
one sender mails twice, one email is a signup confirmation (skipped), and one
summary failed. Stories cover seven topics, and several topics (AI & Tech,
Work & Productivity, Business & GTM) are covered by more than one newsletter.
Five emails have a (fake) Gmail thread id; the rest use the Message-ID fallback link.
"Other" is left empty on purpose, to show that empty topics are not shown.
"""

import zlib
from datetime import datetime
from pathlib import Path

from digest import build_digest
from fetch import Newsletter
from summarize import NewsletterSummary, Story


PREVIEW_GMAIL_ADDRESS = "reader@example.com"  # fake; used for the Gmail links


def _email(name: str, domain: str, subject: str, when: datetime, thread: bool = False) -> Newsletter:
    """A fake email. Only the sender and the two source links matter to the digest.

    thread=True gives it a fake Gmail thread id (a direct link); otherwise the
    digest falls back to a Gmail search link built from the (fake) Message-ID.
    """
    return Newsletter(
        sender=f"{name} <hello@{domain}.example.com>", subject=subject, date=when,
        body="", links=[], unsubscribe=None,
        thread_id=f"{zlib.crc32(subject.encode()):x}0fa4e" if thread else None,  # fake hex id
        message_id=f"<{domain}-{subject.split()[0].lower()}@mail.{domain}.example.com>",
    )


def _story(category: str, title: str, summary: str, path: str | None) -> Story:
    """A fake story. path=None means 'no link', to show that case too."""
    return Story(title, summary, f"https://example.com/{path}" if path else None, category)


def sample_data(when: datetime) -> tuple[list[Newsletter], list[NewsletterSummary | str]]:
    """Return (fake newsletters, fake results) for the preview."""
    emails = [
        _email("The Context Window", "contextwindow", "Small models, big laptops", when, thread=True),
        _email("Ledger & Lantern", "ledgerlantern", "Why rate cuts stalled again", when),
        _email("Pipeline Pulse", "pipelinepulse", "Cold email is not dead, lazy email is", when, thread=True),
        _email("The Context Window", "contextwindow", "Thursday deep dive: agents in production", when),
        _email("Seed Stage Weekly", "seedstage", "The quiet comeback of the $2M round", when, thread=True),
        _email("Bright Basket", "brightbasket", "Welcome! Please confirm your email address", when),
        _email("The Lab Notebook", "labnotebook", "Sleep, salt and a surprising protein", when, thread=True),
        _email("Harbor Politics Brief", "harborbrief", "Port funding vote moves to Tuesday", when),
        _email("The Weekend Reader", "weekendreader", "Issue 212: the long way home", when),
        _email("Daily Stoic Post", "stoicpost", "The obstacle is the way, again", when, thread=True),
    ]
    results: list[NewsletterSummary | str] = [
        # The Context Window, Monday
        NewsletterSummary([
            _story("AI & Tech", "Open model now runs on a laptop",
                   "A university lab released a 7B-parameter model that answers coding questions in under a second.", "open-model"),
            _story("AI & Tech", "Inference chips face a supply squeeze",
                   "Two fabs warned that advanced packaging capacity is sold out through next summer.", "chip-supply"),
            _story("AI & Tech", "Regulators ask how assistants store chats",
                   "Three consumer apps have thirty days to explain how long conversations are kept.", "chat-retention"),
        ]),
        # Ledger & Lantern
        NewsletterSummary([
            _story("Business & GTM", "Rate cuts stall for a second quarter",
                   "Sticky service prices kept central bankers from easing, despite cooling goods inflation.", "rate-cuts"),
            _story("Business & GTM", "Regional banks tighten office loans",
                   "Lenders are now asking for larger down payments on half-empty downtown towers.", "office-loans"),
            _story("News & Politics", "Shipping costs ease for the first time",
                   "Container rates fell nine percent as new vessels entered service on Asia routes.", "shipping"),
        ]),
        # Pipeline Pulse
        NewsletterSummary([
            _story("Business & GTM", "Plain-text cold email wins again",
                   "A 10,000-message test found short, unformatted emails drew nearly twice the replies of designed templates.", "plain-text"),
            _story("Business & GTM", "Follow up on day four",
                   "Reply rates peaked when the second touch landed after a weekend gap.", "follow-up-timing"),
            _story("Work & Productivity", "Teams cut tools to fix attribution",
                   "Three revenue teams dropped overlapping trackers and saw clearer pipeline numbers.", "attribution"),
            _story("AI & Tech", "AI email drafters flood sales inboxes",
                   "Buyers report more generic outreach, and reply rates are falling for the lazy templates.", "ai-drafters"),
        ]),
        # The Context Window, Thursday (same sender as the first email)
        NewsletterSummary([
            _story("Work & Productivity", "Agents need a boring retry policy",
                   "Most production failures came from unbounded retries, not from bad model answers.", "agent-retries"),
            _story("Work & Productivity", "Logs beat dashboards for debugging",
                   "Engineers traced odd behavior faster by replaying full request histories.", "replay-logs"),
        ]),
        # Seed Stage Weekly
        NewsletterSummary([
            _story("Business & GTM", "Two-million-dollar seed rounds return",
                   "Smaller first checks are back as investors favor lean teams over big hiring plans.", "small-seed"),
            _story("Business & GTM", "A founder swaps onboarding emails for video",
                   "Activation rose eleven percent after a ninety-second walkthrough replaced a five-email sequence.", "video-onboarding"),
            _story("Business & GTM", "Why one app removed its free trial",
                   "Switching to a money-back guarantee lowered sign-ups but doubled paid conversion.", "free-trial"),
            _story("Personal Growth", "Customer calls beat surveys",
                   "Five short interviews surfaced the churn reason that a 400-person survey missed.", None),
        ]),
        NewsletterSummary([], skip=True),  # the Bright Basket confirmation email
        # The Lab Notebook
        NewsletterSummary([
            _story("Health & Performance", "Late dinners linked to poorer sleep",
                   "A six-week study found eating within two hours of bedtime cut deep sleep by about twelve minutes.", "late-dinner"),
            _story("Health & Performance", "Salt cravings may start in the gut",
                   "Mouse experiments suggest gut bacteria influence how strongly the brain rewards salty food.", "salt-gut"),
            _story("Personal Growth", "A fixed wake time beats weekend lie-ins",
                   "Participants who kept the same alarm all week reported better focus on Monday.", "wake-time"),
        ]),
        # Harbor Politics Brief
        NewsletterSummary([
            _story("News & Politics", "Port funding vote moves to Tuesday",
                   "Council members delayed the budget decision after a dispute over dredging costs.", "port-vote"),
            _story("News & Politics", "Transit fares frozen through spring",
                   "The regional board voted to hold prices while it studies ridership recovery.", "transit-fares"),
            _story("News & Politics", "Mayor proposes a harbor cleanup fund",
                   "The plan would use a small fee on cruise ships, pending approval next month.", "harbor-cleanup"),
        ]),
        # The Weekend Reader: the summary failed
        "(summary unavailable: Gemini rate limit reached (free tier); gave up after 3 retries.)",
        # Daily Stoic Post
        NewsletterSummary([
            _story("Stoicism & Philosophy", "Marcus Aurelius on the morning mindset",
                   "A short reading on rehearsing obstacles before the day begins, so surprises land softer.", "morning-mindset"),
            _story("Stoicism & Philosophy", "What Seneca meant by borrowed time",
                   "A fresh translation argues his letters are about attention, not about rushing.", "seneca-time"),
            _story("Personal Growth", "A five-minute evening review habit",
                   "Writing down one win and one lesson each night kept readers consistent for a month.", "evening-review"),
        ]),
    ]
    return emails, results


def write_preview(path: Path, when: datetime) -> Path:
    """Build the digest from sample data and write its HTML to `path`."""
    emails, results = sample_data(when)
    path.write_text(build_digest(emails, results, when, PREVIEW_GMAIL_ADDRESS).html, encoding="utf-8")
    return path
