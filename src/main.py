"""Entry point. Run with:  python src/main.py

Stage 1: read the last 24 hours of newsletters, print a summary of each
(never the full body), and log sender + date to a CSV.
"""

import csv
import sys
from pathlib import Path

from config import LOG_PATH, ConfigError, load_credentials
from fetch import FetchError, Newsletter, connect, fetch_newsletters


def print_newsletters(newsletters: list[Newsletter]) -> None:
    """Show each newsletter's details. The body is deliberately not printed."""
    for number, item in enumerate(newsletters, start=1):
        print(f"\n[{number}] {item.subject}")
        print(f"    From: {item.sender}")
        print(f"    Date: {item.date:%Y-%m-%d %H:%M %Z}")
        print(f"    Unsubscribe: {item.unsubscribe or 'not provided'}")
        print(f"    Links ({len(item.links)}):")
        for link in item.links:
            print(f"      {link}")


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


def main() -> int:
    """Run Stage 1. Returns 0 on success, 1 on an expected problem."""
    try:
        creds = load_credentials()
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
    print_newsletters(newsletters)

    added = append_to_log(newsletters, LOG_PATH)
    print(f"\nLogged {added} new row(s) to {LOG_PATH.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
