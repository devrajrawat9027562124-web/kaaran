"""Student accounts: sign up, log in, and the programs they save.

Everything is in one SQLite file (KAARAN_DB, by default backend/kaaran.db).

- Passwords are never stored: only a scrypt hash with a random salt
  (N=2^14, r=8, p=5, one of OWASP's recommended scrypt settings).
- Logging in gives a random session token. Only its SHA-256 hash is stored,
  so a copy of the database can't be used to log in. Sessions expire after
  KAARAN_SESSION_DAYS days, and logging out deletes them.
- A wrong email and a wrong password get the same answer, and take about the
  same time, so the login form doesn't reveal who has an account.

Not here (known gaps for a classroom tool): email verification and password
reset.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager

# A relative path is inside the backend folder, wherever the server was started from
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.environ.get("KAARAN_DB") or "kaaran.db")
SESSION_DAYS = float(os.environ.get("KAARAN_SESSION_DAYS", "14"))
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 5}
MAX_PROGRAMS = 200
LANGUAGES = ("python", "c", "cpp")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id       INTEGER PRIMARY KEY,
    email    TEXT NOT NULL UNIQUE,
    name     TEXT NOT NULL,
    password TEXT NOT NULL,          -- scrypt$N$r$p$salt$hash
    created  REAL NOT NULL
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
"""


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
    """Create an account and log it in: (token, user)."""
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
        if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise AccountError(409, "There's already an account with this email. Log in instead.")
        try:
            cursor = db.execute("INSERT INTO users (email, name, password, created) VALUES (?, ?, ?, ?)",
                                (email, name, hash_password(password), time.time()))
        except sqlite3.IntegrityError:  # the same email signed up a moment ago
            raise AccountError(409, "There's already an account with this email. Log in instead.") from None
        token = _new_session(db, cursor.lastrowid)
        return token, {"id": cursor.lastrowid, "name": name, "email": email}


def login(email, password):
    """(token, user) for a matching email and password."""
    with _db() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        ok = check_password(password, row["password"] if row else _NOBODY)
        if not row or not ok:
            raise AccountError(401, "That email and password don't match an account.")
        return _new_session(db, row["id"]), _user(row)


def user_for(token):
    """The logged-in user for a session token, or None if it's unknown or expired."""
    if not token:
        return None
    with _db() as db:
        row = db.execute("SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id "
                         "WHERE token_hash = ? AND expires > ?", (_token_hash(token), time.time())).fetchone()
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
