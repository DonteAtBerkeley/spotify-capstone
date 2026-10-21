#!/usr/bin/env python3
"""Hand-label the golden-50 sample, one review at a time.

Reads data/golden_50_to_label.csv (never modified) and writes
data/golden_50_labeled.csv after every review, so you can quit and resume.

Only review_text is shown; stars/likes/app_version are hidden so they
can't influence the labels. No answer is ever suggested or pre-filled.

Usage:  python3 tools/label_golden.py
At any prompt:  q = save and quit,  b = go back to the previous review.
"""
import csv
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "golden_50_to_label.csv")
OUT = os.path.join(ROOT, "data", "golden_50_labeled.csv")

# Order and wording follow data/GRADING_CONTRACT.md.
TOPICS = [
    ("access", "Login, signup, password or account access"),
    ("usability", "Navigation, controls, layout, queue/playlist management, ad interruptions"),
    ("playback", "Playback failure, crashes, lag, connection failures, audio quality, resource use"),
    ("downloads", "Downloading, saved music, offline listening, disappearing downloads"),
    ("catalog", "Missing songs/artists, search/discovery, recommendations, lyrics availability"),
    ("billing", "Price, charges, subscriptions, paywalls, premium entitlement"),
    ("support", "Contacting support and the support response"),
    ("other", "General praise/criticism, unrelated content, or no supported specific topic"),
]
INTENTS = [
    ("cancellation", "Explicitly leaving, uninstalling, cancelling, or threatening to"),
    ("complaint", "Negative experience, including mixed praise/criticism"),
    ("request", "Desired change without a reported failure"),
    ("praise", "Positive"),
    ("unclear", "Bare boycott slogans, unrelated or meaningless text"),
]
SEVERITIES = [
    ("1", "No reported problem: praise, neutral/unclear, or pure feature request"),
    ("2", "Dislike, generic criticism, minor annoyance, cosmetic; no functional loss"),
    ("3", "Degraded or restricted function; some use or workaround remains"),
    ("4", "Clearly blocked core task (e.g. can't log in or play music)"),
    ("5", "Explicit serious financial, privacy, or data harm"),
]
LABEL_FIELDS = ("topic", "intent", "severity")


class Quit(Exception):
    pass


class Back(Exception):
    pass


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def save(fieldnames, rows):
    """Write atomically so a crash mid-write can't corrupt saved labels."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, OUT)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load_rows():
    fieldnames, src_rows = read_csv(SRC)
    if not os.path.exists(OUT):
        return fieldnames, src_rows
    out_fields, out_rows = read_csv(OUT)
    if out_fields != fieldnames or [r["review_id"] for r in out_rows] != [
        r["review_id"] for r in src_rows
    ]:
        sys.exit(
            f"{OUT} doesn't match {SRC} (columns or review_ids differ).\n"
            "Move it aside before running, so no saved labels are lost."
        )
    return fieldnames, out_rows


def is_done(row):
    return all(row.get(k, "").strip() for k in LABEL_FIELDS)


def ask(title, options):
    print(f"\n{title}")
    for i, (name, desc) in enumerate(options, 1):
        label = desc if name == str(i) else f"{name:<13} {desc}"
        print(f"  {i}. {label}")
    while True:
        ans = input(f"Enter 1-{len(options)} (q quit, b back): ").strip().lower()
        if ans == "q":
            raise Quit
        if ans == "b":
            raise Back
        if ans.isdigit() and 1 <= int(ans) <= len(options):
            return options[int(ans) - 1][0]
        print("  Not a valid choice, try again.")


def main():
    fieldnames, rows = load_rows()
    total = len(rows)
    i = next((n for n, r in enumerate(rows) if not is_done(r)), total)
    if i == total:
        print(f"All {total} reviews are already labeled in {OUT}.")
        return

    try:
        while i < total:
            row = rows[i]
            done = sum(is_done(r) for r in rows)
            print("\n" + "=" * 72)
            print(f"Review {i + 1} of {total}   ({done} labeled)   id {row['review_id']}")
            if is_done(row):
                print("(already labeled; answering again will replace it)")
            print("-" * 72)
            print(row["review_text"])
            print("-" * 72)
            try:
                topic = ask("TOPIC", TOPICS)
                intent = ask("INTENT", INTENTS)
                severity = ask("SEVERITY", SEVERITIES)
            except Back:
                if i == 0:
                    print("  Already at the first review.")
                else:
                    i -= 1
                continue
            row.update(topic=topic, intent=intent, severity=severity)
            save(fieldnames, rows)
            print(f"  Saved: {topic} / {intent} / {severity}")
            # Next unlabeled review (handles coming back after a 'b').
            i = next((n for n in range(i + 1, total) if not is_done(rows[n])), total)
    except (Quit, KeyboardInterrupt, EOFError):
        print(f"\nStopped. Progress is saved in {OUT}; rerun to resume.")
        return

    print(f"\nDone: all {total} reviews labeled. Saved to {OUT}.")


if __name__ == "__main__":
    main()
