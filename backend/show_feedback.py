"""Read the feedback students send, and answer it.

    python show_feedback.py                      open reports, newest first
    python show_feedback.py --all                resolved ones too
    python show_feedback.py --show 3             one report in full, with the program it attached
    python show_feedback.py --resolve 3 --reply "Fixed in today's update, thanks!"

A reply appears to the student under "Your earlier reports" in the feedback
form. Run from the backend folder, with the venv active.
"""
import argparse
import datetime
import os
import sqlite3
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import accounts  # noqa: E402  (reads KAARAN_DB, loaded above)

CATEGORY = {
    "bug": "Kaaran isn't working",
    "wrong-answer": "Wrong step or answer",
    "my-program": "About my program",
    "idea": "Idea",
    "other": "Other",
}


def when(seconds):
    return datetime.datetime.fromtimestamp(seconds).strftime("%d %b %Y, %H:%M")


def connect(write=False):
    mode = "rw" if write else "ro"
    db = sqlite3.connect(f"file:{accounts.DB_PATH}?mode={mode}", uri=True)
    db.row_factory = sqlite3.Row
    return db


def listing(db, everything):
    where = "" if everything else "WHERE status = 'open'"
    rows = db.execute("SELECT feedback.*, users.name, users.email FROM feedback "
                      f"JOIN users ON users.id = feedback.user_id {where} ORDER BY feedback.created DESC").fetchall()
    kind = "report" if everything else "open report"
    print(f"{len(rows)} {kind}{'s' if len(rows) != 1 else ''}\n")
    for row in rows:
        first_line = row["message"].strip().splitlines()[0]
        print(f"#{row['id']}  {when(row['created'])}  {row['name']} <{row['email']}>  [{CATEGORY.get(row['category'], row['category'])}]"
              f"{'  RESOLVED' if row['status'] == 'resolved' else ''}{'  +program' if row['code'] is not None else ''}")
        print(f"     {first_line[:100]}{'…' if len(first_line) > 100 else ''}\n")
    if rows:
        print("See one in full:  python show_feedback.py --show ID")


def show(db, report_id):
    row = db.execute("SELECT feedback.*, users.name, users.email FROM feedback JOIN users ON users.id = feedback.user_id "
                     "WHERE feedback.id = ?", (report_id,)).fetchone()
    if not row:
        print(f"There's no report #{report_id}.")
        return 1
    print(f"#{row['id']} from {row['name']} <{row['email']}>, {when(row['created'])}")
    print(f"About: {CATEGORY.get(row['category'], row['category'])}   Status: {row['status']}"
          + (f"   Looking at step {row['step']}" if row["step"] else ""))
    print(f"\n{row['message']}\n")
    if row["code"] is not None:
        print(f"--- their program ({row['language']}) ---\n{row['code']}")
        if row["input"]:
            print(f"--- its input ---\n{row['input']}")
    if row["reply"]:
        print(f"--- your reply ---\n{row['reply']}")
    return 0


def resolve(report_id, reply):
    db = connect(write=True)
    with db:
        cursor = db.execute("UPDATE feedback SET status = 'resolved', reply = COALESCE(?, reply) WHERE id = ?",
                            (reply, report_id))
    db.close()
    if cursor.rowcount == 0:
        print(f"There's no report #{report_id}.")
        return 1
    print(f"Report #{report_id} is resolved" + (" and the student will see your reply." if reply else "."))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Read and answer student feedback.")
    parser.add_argument("--all", action="store_true", help="include resolved reports")
    parser.add_argument("--show", type=int, metavar="ID", help="one report in full")
    parser.add_argument("--resolve", type=int, metavar="ID", help="mark a report resolved")
    parser.add_argument("--reply", metavar="TEXT", help="with --resolve: an answer the student will see")
    args = parser.parse_args()
    if args.reply and args.resolve is None:
        parser.error("--reply goes with --resolve ID")
    if not os.path.exists(accounts.DB_PATH):
        print(f"No database yet at {accounts.DB_PATH}: no feedback.")
        return 0
    if args.resolve is not None:
        return resolve(args.resolve, args.reply)
    db = connect()
    try:
        return show(db, args.show) if args.show is not None else listing(db, args.all)
    except sqlite3.OperationalError:
        print("No feedback yet (the server hasn't been started since feedback was added).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
