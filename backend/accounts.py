"""Student accounts: sign up, log in, the programs they save, and the
feedback they send (problems with Kaaran or with their program).

Everything is in one SQLite file (KAARAN_DB, by default backend/kaaran.db).

- Passwords are never stored: only a scrypt hash with a random salt
  (N=2^14, r=8, p=5, one of OWASP's recommended scrypt settings).
- Logging in gives a random session token. Only its SHA-256 hash is stored,
  so a copy of the database can't be used to log in. Sessions expire after
  KAARAN_SESSION_DAYS days, and logging out deletes them.
- A wrong email and a wrong password get the same answer, and take about the
  same time, so the login form doesn't reveal who has an account.
- A new account must confirm its email: a 6-digit code is emailed (mailer.py)
  and works for 10 minutes and 5 tries. Only its hash is stored. Confirming
  also needs the account's password, so someone who signs up with another
  person's email can't take the account over when that person types the code.
  Emails to one account: one a minute, five an hour.

Not here (a known gap for a classroom tool): password reset.
"""
import base64
import hashlib
import hmac
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager

import mailer

# A relative path is inside the backend folder, wherever the server was started from
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.environ.get("KAARAN_DB") or "kaaran.db")
SESSION_DAYS = float(os.environ.get("KAARAN_SESSION_DAYS", "14"))
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 5}
MAX_PROGRAMS = 200
CODE_MINUTES = 10        # an emailed code works this long
RESEND_SECONDS = 60      # between two emails to one account
MAX_SENDS_PER_HOUR = 5   # emails to one account in an hour
MAX_ATTEMPTS = 5         # wrong codes before a code stops working
LANGUAGES = ("python", "c", "cpp")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id       INTEGER PRIMARY KEY,
    email    TEXT NOT NULL UNIQUE,
    name     TEXT NOT NULL,
    password TEXT NOT NULL,          -- scrypt$N$r$p$salt$hash
    created  REAL NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0  -- 1 once the emailed code was entered
);
CREATE TABLE IF NOT EXISTS email_codes (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    code_hash    TEXT NOT NULL,      -- SHA-256, never the code itself
    expires      REAL NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    sent         REAL NOT NULL,      -- when the last email went out
    window_start REAL NOT NULL,      -- the hour that `sends` counts in
    sends        INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,     -- SHA-256 of the token the browser holds
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS programs (
    id       INTEGER PRIMARY KEY,
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title    TEXT NOT NULL,
    language TEXT NOT NULL,
    code     TEXT NOT NULL,
    input    TEXT NOT NULL DEFAULT '',
    updated  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS programs_by_user ON programs (user_id, updated);
CREATE TABLE IF NOT EXISTS feedback (
    id       INTEGER PRIMARY KEY,
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,          -- one of FEEDBACK_CATEGORIES
    message  TEXT NOT NULL,
    language TEXT,                   -- the program in the editor, if the student attached it
    code     TEXT,
    input    TEXT,
    step     INTEGER,                -- the step they were looking at
    status   TEXT NOT NULL DEFAULT 'open',  -- open | resolved
    reply    TEXT,                   -- an answer from whoever runs Kaaran (show_feedback.py)
    created  REAL NOT NULL
);
"""
FEEDBACK_CATEGORIES = ("bug", "wrong-answer", "my-program", "idea", "other")


class AccountError(Exception):
    """A request that can't be done, with the HTTP status and a message for the student."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


_ready = set()
_ready_lock = threading.Lock()


def connect():
    """A connection to the database, creating the tables the first time."""
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    with _ready_lock:
        if DB_PATH not in _ready:
            db.executescript(SCHEMA)
            if "verified" not in {row[1] for row in db.execute("PRAGMA table_info(users)")}:
                # A database from before email codes: those accounts confirm at their next login
                db.execute("ALTER TABLE users ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
                db.commit()
            _ready.add(DB_PATH)
    return db


@contextmanager
def _db():
    """One transaction: committed if the block succeeds, then the connection is closed."""
    db = connect()
    try:
        with db:
            yield db
    finally:
        db.close()


# ---------- Passwords and sessions ----------

def _b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    n, r, p = SCRYPT["n"], SCRYPT["r"], SCRYPT["p"]
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt${n}${r}${p}${_b64(salt)}${_b64(digest)}"


def check_password(password, stored):
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        expected = _unb64(digest)
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p),
                                maxmem=64 * 1024 * 1024, dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return kind == "scrypt" and hmac.compare_digest(actual, expected)


# Checked against when the email has no account, so both answers take as long
_NOBODY = hash_password(secrets.token_urlsafe(16))


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _new_session(db, user_id):
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
    db.execute("INSERT INTO sessions (token_hash, user_id, expires) VALUES (?, ?, ?)",
               (_token_hash(token), user_id, now + SESSION_DAYS * 86400))
    return token


def _user(row):
    return {"id": row["id"], "name": row["name"], "email": row["email"]}


# ---------- Accounts ----------

def signup(name, email, password):
    """Create an account and email it a code: {"verify": True, "email", "wait"}.

    An email that signed up before but was never confirmed can sign up again
    (a typo in the password, a lost code): that replaces the name and password.
    """
    name, email = " ".join(name.split()), email.strip().lower()
    if not name:
        raise AccountError(400, "Enter your name.")
    if len(name) > 60:
        raise AccountError(400, "Use a name of at most 60 characters.")
    if not EMAIL.match(email) or len(email) > 254:
        raise AccountError(400, "Enter an email address like name@example.com.")
    if len(password) < 8:
        raise AccountError(400, "Use a password of at least 8 characters.")
    if len(password) > 128:
        raise AccountError(400, "Use a password of at most 128 characters.")
    with _db() as db:
        row = db.execute("SELECT id, verified FROM users WHERE email = ?", (email,)).fetchone()
        if row and row["verified"]:
            raise AccountError(409, "There's already an account with this email. Log in instead.")
        if row:
            db.execute("UPDATE users SET name = ?, password = ? WHERE id = ?",
                       (name, hash_password(password), row["id"]))
            user_id = row["id"]
        else:
            try:
                cursor = db.execute("INSERT INTO users (email, name, password, created) VALUES (?, ?, ?, ?)",
                                    (email, name, hash_password(password), time.time()))
            except sqlite3.IntegrityError:  # the same email signed up a moment ago
                raise AccountError(409, "There's already an account with this email. Log in instead.") from None
            user_id = cursor.lastrowid
    return {"verify": True, "email": email, "wait": _send_code(user_id, email, name)}


def login(email, password):
    """{"token", "user"} for a matching email and password. For an account whose
    email isn't confirmed yet, a code is emailed instead: {"verify": True, "email", "wait"}."""
    with _db() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        ok = check_password(password, row["password"] if row else _NOBODY)
        if not row or not ok:
            raise AccountError(401, "That email and password don't match an account.")
        if row["verified"]:
            return {"token": _new_session(db, row["id"]), "user": _user(row)}
    return {"verify": True, "email": row["email"], "wait": _send_code(row["id"], row["email"], row["name"])}


# ---------- Confirming the email with a code ----------

CODE_EMAIL = """Hello {name},

Your Kaaran code is {code}

Type it on the Kaaran page to confirm this is your email. It works for {minutes} minutes.

If you didn't sign up for Kaaran, you can ignore this email: nobody can use
the account without this code.
"""


def _code_hash(user_id, code):
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()


def _send_code(user_id, email, name):
    """Email a new code, unless one went out less than a minute ago.
    Returns the seconds until another may be sent."""
    now = time.time()
    with _db() as db:
        row = db.execute("SELECT * FROM email_codes WHERE user_id = ?", (user_id,)).fetchone()
        if row and now - row["sent"] < RESEND_SECONDS:
            return math.ceil(RESEND_SECONDS - (now - row["sent"]))
        recent = row and now - row["window_start"] < 3600
        window_start, sends = (row["window_start"], row["sends"]) if recent else (now, 0)
        if sends >= MAX_SENDS_PER_HOUR:
            raise AccountError(429, "Several codes have already been sent to this email in the last hour. "
                                    "Use the newest one, or try again later.")
        code = f"{secrets.randbelow(10 ** 6):06d}"
        db.execute("INSERT OR REPLACE INTO email_codes "
                   "(user_id, code_hash, expires, attempts, sent, window_start, sends) VALUES (?, ?, ?, 0, ?, ?, ?)",
                   (user_id, _code_hash(user_id, code), now + CODE_MINUTES * 60, now, window_start, sends + 1))
    try:
        mailer.send(email, f"Your Kaaran code: {code}",
                    CODE_EMAIL.format(name=name.split(" ")[0], code=code, minutes=CODE_MINUTES))
    except mailer.MailError as e:
        with _db() as db:  # nothing went out, so asking again needn't wait
            db.execute("UPDATE email_codes SET sent = 0 WHERE user_id = ?", (user_id,))
        raise AccountError(502, str(e)) from None
    return RESEND_SECONDS


def verify(email, code, password):
    """Confirm the email with its code (and the account's password), and log in: {"token", "user"}."""
    email, code = email.strip().lower(), re.sub(r"\D", "", code)  # "123 456" is fine
    error, token = None, None
    with _db() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and user["verified"]:
            raise AccountError(400, "This email is already confirmed. Log in.")
        pending = user and db.execute("SELECT * FROM email_codes WHERE user_id = ?", (user["id"],)).fetchone()
        if not pending or pending["expires"] < time.time():
            raise AccountError(400, "That code has expired. Ask for a new one.")
        right = hmac.compare_digest(pending["code_hash"], _code_hash(user["id"], code))
        if right and check_password(password, user["password"]):
            db.execute("UPDATE users SET verified = 1 WHERE id = ?", (user["id"],))
            db.execute("DELETE FROM email_codes WHERE user_id = ?", (user["id"],))
            token = _new_session(db, user["id"])
        else:
            # Counted here, then answered after the block: an error inside it would undo the count
            attempts = pending["attempts"] + 1
            if attempts >= MAX_ATTEMPTS:
                db.execute("UPDATE email_codes SET expires = 0 WHERE user_id = ?", (user["id"],))
                error = AccountError(429, "Too many wrong codes. Ask for a new one.")
            else:
                db.execute("UPDATE email_codes SET attempts = ? WHERE user_id = ?", (attempts, user["id"]))
                left = MAX_ATTEMPTS - attempts
                error = AccountError(400, f"That code isn't right. {left} {'try' if left == 1 else 'tries'} left.")
    if error:
        raise error
    return {"token": token, "user": _user(user)}


def resend(email, password):
    """Email a new code to an account that isn't confirmed yet: {"wait"}."""
    with _db() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    if not row or not check_password(password, row["password"]):
        raise AccountError(401, "That email and password don't match an account.")
    if row["verified"]:
        raise AccountError(400, "This email is already confirmed. Log in.")
    return {"wait": _send_code(row["id"], row["email"], row["name"])}


def user_for(token):
    """The logged-in user for a session token, or None if it's unknown or expired."""
    if not token:
        return None
    with _db() as db:
        row = db.execute("SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id "
                         "WHERE token_hash = ? AND expires > ? AND users.verified = 1",
                         (_token_hash(token), time.time())).fetchone()
        return _user(row) if row else None


def logout(token):
    with _db() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


# ---------- Saved programs (always looked up together with the user, so one
# student can never read or change another's) ----------

def _program(row, full=True):
    program = {"id": row["id"], "title": row["title"], "language": row["language"], "updated": row["updated"]}
    if full:
        program.update(code=row["code"], input=row["input"])
    return program


def _check(title, language):
    title = " ".join(title.split())
    if not title:
        raise AccountError(400, "Give the program a name.")
    if language not in LANGUAGES:
        raise AccountError(400, "The language must be Python, C or C++.")
    return title[:80]


def list_programs(user_id):
    with _db() as db:
        rows = db.execute("SELECT id, title, language, updated FROM programs WHERE user_id = ? "
                          "ORDER BY updated DESC", (user_id,)).fetchall()
        return [_program(row, full=False) for row in rows]


def get_program(user_id, program_id):
    with _db() as db:
        row = db.execute("SELECT * FROM programs WHERE id = ? AND user_id = ?", (program_id, user_id)).fetchone()
        if not row:
            raise AccountError(404, "That program isn't in your saved programs.")
        return _program(row)


def create_program(user_id, title, language, code, input=""):
    title = _check(title, language)
    with _db() as db:
        (count,) = db.execute("SELECT COUNT(*) FROM programs WHERE user_id = ?", (user_id,)).fetchone()
        if count >= MAX_PROGRAMS:
            raise AccountError(409, f"You have {MAX_PROGRAMS} saved programs. Delete some to save more.")
        cursor = db.execute("INSERT INTO programs (user_id, title, language, code, input, updated) "
                            "VALUES (?, ?, ?, ?, ?, ?)", (user_id, title, language, code, input, time.time()))
        program_id = cursor.lastrowid
    return get_program(user_id, program_id)


def update_program(user_id, program_id, title, language, code, input=""):
    title = _check(title, language)
    with _db() as db:
        cursor = db.execute("UPDATE programs SET title = ?, language = ?, code = ?, input = ?, updated = ? "
                            "WHERE id = ? AND user_id = ?",
                            (title, language, code, input, time.time(), program_id, user_id))
        if cursor.rowcount == 0:
            raise AccountError(404, "That program isn't in your saved programs.")
    return get_program(user_id, program_id)


def delete_program(user_id, program_id):
    with _db() as db:
        cursor = db.execute("DELETE FROM programs WHERE id = ? AND user_id = ?", (program_id, user_id))
        if cursor.rowcount == 0:
            raise AccountError(404, "That program isn't in your saved programs.")


# ---------- Feedback: problems and ideas, sent from the profile menu ----------

def _feedback(row):
    return {"id": row["id"], "category": row["category"], "message": row["message"], "step": row["step"],
            "attached": row["code"] is not None, "status": row["status"], "reply": row["reply"],
            "created": row["created"]}


def send_feedback(user_id, category, message, language=None, code=None, input=None, step=None):
    message = message.strip()
    if category not in FEEDBACK_CATEGORIES:
        raise AccountError(400, "Choose what the feedback is about.")
    if len(message) < 10:
        raise AccountError(400, "Tell us a little more (at least 10 characters).")
    if len(message) > 4000:
        raise AccountError(400, "Keep it to 4,000 characters.")
    if code is not None and language not in LANGUAGES:
        raise AccountError(400, "The language must be Python, C or C++.")
    with _db() as db:
        cursor = db.execute("INSERT INTO feedback (user_id, category, message, language, code, input, step, created) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (user_id, category, message, language if code is not None else None, code,
                             input if code is not None else None, step, time.time()))
        row = db.execute("SELECT * FROM feedback WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _feedback(row)


def list_feedback(user_id):
    """The student's own reports, newest first, with any reply."""
    with _db() as db:
        rows = db.execute("SELECT * FROM feedback WHERE user_id = ? ORDER BY created DESC", (user_id,)).fetchall()
        return [_feedback(row) for row in rows]
