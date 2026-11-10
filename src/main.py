"""Entry point. Run with:  python src/main.py

Stage 1: read the last 24 hours of newsletters and log sender + date to a CSV.
Stage 2: one Gemini call per newsletter gives up to five one-sentence
stories, each with its own topic category and best link.
Stage 3: build one digest email and send it to DIGEST_TO.
The full body is never printed.

Add --no-send to do everything except send the email.
Add --preview to build the digest from fake sample data and write preview.html
(no inbox, no Gemini, no sending).
"""

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

from config import LOG_PATH, PAUSE_BETWEEN_NEWSLETTERS, PREVIEW_PATH, ConfigError, load_credentials, load_recipient
from digest import build_digest
from fetch import FetchError, Newsletter, connect, fetch_newsletters
from preview import write_preview
from send import SendError, send_digest
from summarize import NewsletterSummary, SummarizeError, summarize


def summarize_all(newsletters: list[Newsletter]) -> list[NewsletterSummary | str]:
    """Summarize every newsletter, in order. Never raises for expected problems.

    If one newsletter fails (rate limit, blocked reply...), its slot holds a
    short "unavailable" note (a string) instead, so one failure cannot sink
    the rest. Pauses 1 second between newsletters to stay under rate limits.
    """
    results: list[NewsletterSummary | str] = []
    for number, item in enumerate(newsletters):
        if number > 0:  # pause between newsletters, not before the first
            time.sleep(PAUSE_BETWEEN_NEWSLETTERS)
        try:
            results.append(summarize(item.body, item.links, item.unsubscribe))
        except SummarizeError as problem:
            results.append(f"(summary unavailable: {problem})")
    return results


def print_newsletters(newsletters: list[Newsletter], results: list[NewsletterSummary | str]) -> None:
    """Show each newsletter's details and stories (each with its category). The body is deliberately not printed."""
    # zip() walks the two lists side by side: first newsletter with first result, etc.
    for number, (item, result) in enumerate(zip(newsletters, results), start=1):
        print(f"\n[{number}] {item.subject}")
        print(f"    From: {item.sender}")
        print(f"    Date: {item.date:%Y-%m-%d %H:%M %Z}")
        print(f"    Unsubscribe: {item.unsubscribe or 'not provided'}")
        if isinstance(result, str):  # a failure note
            print(f"    {result}")
            continue
        if result.skip:
            print("    Skipped: not a newsletter.")
        for story in result.stories:
            print(f"      - [{story.category}] {story.title}: {story.summary}")
            print(f"        {story.url or '(no link)'}")


def append_to_log(newsletters: list[Newsletter], log_path: Path) -> int:
    """Append sender + date rows to the CSV log. Returns how many were added.

    Rows already in the file are skipped, so running the script twice
    does not double-count the same newsletter in the future audit.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)  # create data/ if needed
    is_new_file = not log_path.exists()

    # Read what is already logged so we can skip duplicates.
    existing: set[tuple[str, str]] = set()
    if not is_new_file:
        with open(log_path, newline="", encoding="utf-8") as file:
            existing = {(row["sender"], row["date"]) for row in csv.DictReader(file)}

    added = 0
    # "a" = append: add to the end instead of overwriting the file.
    with open(log_path, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if is_new_file:
            writer.writerow(["sender", "date"])  # header row
        for item in newsletters:
            row = (item.sender, item.date.isoformat())
            if row not in existing:
                writer.writerow(row)
                added += 1
    return added


def main(argv: list[str] | None = None) -> int:
    """Run Stages 1 to 3 (or just the preview). Returns 0 on success, 1 on an expected problem."""
    # argparse reads command-line options. Here there is just one: --no-send.
    parser = argparse.ArgumentParser(description="Summarize today's newsletters and email a digest.")
    parser.add_argument("--no-send", action="store_true", help="do everything except send the email")
    parser.add_argument("--preview", action="store_true",
                        help="write preview.html from fake sample data (no inbox, Gemini or sending)")
    args = parser.parse_args(argv)

    if args.preview:  # handled first: needs no credentials and no network
        path = write_preview(PREVIEW_PATH, datetime.now().astimezone())
        print(f"Preview written to {path}")
        return 0

    try:
        creds = load_credentials()
        recipient = None if args.no_send else load_recipient()  # fail early, before any Gemini calls
        conn = connect(creds)
        try:
            newsletters = fetch_newsletters(conn)
        finally:
            conn.logout()  # always close the connection, even after an error
    except (ConfigError, FetchError) as problem:
        print(f"Error: {problem}")
        return 1

    if not newsletters:
        print("No newsletters found in the last 24 hours.")
        return 0

    print(f"Found {len(newsletters)} newsletter(s) in the last 24 hours.")
    print("Summarizing with Gemini...")
    results = summarize_all(newsletters)
    print_newsletters(newsletters, results)

    added = append_to_log(newsletters, LOG_PATH)
    print(f"\nLogged {added} new row(s) to {LOG_PATH.name}.")

    if recipient is None:
        print("--no-send given: digest not sent.")
        return 0

    digest = build_digest(newsletters, results, datetime.now().astimezone(), creds.address)
    try:
        send_digest(digest, creds, recipient)
    except SendError as problem:
        print(f"Error: {problem}")
        return 1
    print("Digest sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
