"""List the student accounts in the database, for the person running the server.

    python show_users.py          (from the backend folder, with the venv active)

Read-only: it opens the database so that it can't change anything. Password
hashes are left out: there is never a reason to look at them.
"""
import datetime
import os
import sqlite3
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import accounts  # noqa: E402  (reads KAARAN_DB, loaded above)


def when(seconds):
    return datetime.datetime.fromtimestamp(seconds).strftime("%d %b %Y, %H:%M")


def main():
    if not os.path.exists(accounts.DB_PATH):
        print(f"No database yet at {accounts.DB_PATH}: nobody has signed up.")
        return
    db = sqlite3.connect(f"file:{accounts.DB_PATH}?mode=ro", uri=True)
    # A database from before email codes has no `verified` column until the server next starts
    verified = "users.verified" if "verified" in {row[1] for row in db.execute("PRAGMA table_info(users)")} else "0"
    rows = db.execute(f"""
        SELECT users.id, users.name, users.email, users.created, {verified},
               (SELECT COUNT(*) FROM programs WHERE programs.user_id = users.id),
               (SELECT COUNT(*) FROM sessions WHERE sessions.user_id = users.id AND expires > ?)
        FROM users ORDER BY users.id""", (datetime.datetime.now().timestamp(),)).fetchall()
    db.close()
    print(f"{len(rows)} account{'s' if len(rows) != 1 else ''} in {accounts.DB_PATH}\n")
    if not rows:
        return
    print(f"{'id':>3}  {'name':<22} {'email':<32} {'signed up':<19} {'confirmed':<9}  {'programs':>8}  logged in")
    for user_id, name, email, created, verified, programs, sessions in rows:
        print(f"{user_id:>3}  {name[:22]:<22} {email[:32]:<32} {when(created):<19} {'yes' if verified else 'not yet':<9}  "
              f"{programs:>8}  {'yes' if sessions and verified else 'no'}")  # only confirmed accounts get in


if __name__ == "__main__":
    sys.exit(main())
