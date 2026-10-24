"""Tests for accounts and saved programs (backend/accounts.py and the
/auth and /programs endpoints), on a fresh database in a temporary folder.

Run from the kaaran folder:   python -m pytest tests -v
Skipped if FastAPI isn't installed (pip install -r backend/requirements.txt).
"""
import os
import re
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import accounts  # noqa: E402
import app as backend  # noqa: E402
import mailer  # noqa: E402

ASHA = {"name": "Asha Rawat", "email": "Asha@Example.com", "password": "correct horse"}
PROGRAM = {"title": "Average", "language": "python", "code": "print(1)\n", "input": ""}


@pytest.fixture(autouse=True)
def fast_hashes(monkeypatch):
    # The real settings take about 0.3 s a hash, on purpose; tests use cheap ones
    monkeypatch.setattr(accounts, "SCRYPT", {"n": 2 ** 10, "r": 8, "p": 1})
    monkeypatch.setattr(accounts, "_NOBODY", accounts.hash_password("nobody"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "DB_PATH", str(tmp_path / "kaaran.db"))
    backend.auth_limiter.seen.clear()
    backend.feedback_limiter.seen.clear()
    test_client = TestClient(backend.app)
    # Emails land here instead of being sent
    test_client.mailbox = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, text: test_client.mailbox.append(
        {"to": to, "subject": subject, "text": text}))
    return test_client


def code_in(mail):
    return re.search(r"\b(\d{6})\b", mail["text"]).group(1)


def signup(client, **changes):
    """Sign up and confirm the email with the code it was sent: the session."""
    fields = {**ASHA, **changes}
    response = client.post("/auth/signup", json=fields)
    assert response.status_code == 201, response.text
    assert response.json()["verify"] is True and "token" not in response.json()
    confirmed = client.post("/auth/verify", json={"email": fields["email"], "code": code_in(client.mailbox[-1]),
                                                  "password": fields["password"]})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- Accounts ----------

def test_signup_then_the_emailed_code_logs_in_and_normalises_the_email(client):
    body = signup(client)
    assert body["user"] == {"id": 1, "name": "Asha Rawat", "email": "asha@example.com"}
    assert client.get("/auth/me", headers=auth(body["token"])).json()["email"] == "asha@example.com"


def test_password_and_token_are_not_stored(client):
    token = signup(client)["token"]
    db = sqlite3.connect(accounts.DB_PATH)
    (stored,) = db.execute("SELECT password FROM users").fetchone()
    (token_hash,) = db.execute("SELECT token_hash FROM sessions").fetchone()
    db.close()
    assert stored.startswith("scrypt$") and ASHA["password"] not in stored
    assert token_hash != token and token not in token_hash


def test_same_password_gets_a_different_hash():
    assert accounts.hash_password("same password") != accounts.hash_password("same password")
    assert accounts.check_password("same password", accounts.hash_password("same password"))
    assert not accounts.check_password("other password", accounts.hash_password("same password"))
    assert not accounts.check_password("anything", "not a hash")


@pytest.mark.parametrize("changes, message", [
    ({"name": "  "}, "Enter your name"),
    ({"email": "asha"}, "email address"),
    ({"password": "short"}, "at least 8"),
])
def test_signup_checks_its_fields(client, changes, message):
    response = client.post("/auth/signup", json={**ASHA, **changes})
    assert response.status_code == 400 and message in response.json()["detail"]


# ---------- Confirming the email with a code ----------

def start_signup(client, **changes):
    response = client.post("/auth/signup", json={**ASHA, **changes})
    assert response.status_code == 201, response.text
    return response.json()


def confirm(client, code, email=ASHA["email"], password=ASHA["password"]):
    return client.post("/auth/verify", json={"email": email, "code": code, "password": password})


def test_signup_emails_a_code_and_gives_no_session_yet(client):
    body = start_signup(client)
    assert body == {"verify": True, "email": "asha@example.com", "wait": accounts.RESEND_SECONDS}
    [mail] = client.mailbox
    assert mail["to"] == "asha@example.com" and code_in(mail) in mail["subject"]
    assert "Hello Asha" in mail["text"]


def test_the_code_is_not_stored(client):
    start_signup(client)
    db = sqlite3.connect(accounts.DB_PATH)
    (stored,) = db.execute("SELECT code_hash FROM email_codes").fetchone()
    db.close()
    assert code_in(client.mailbox[-1]) not in stored


def test_an_unconfirmed_account_cant_log_in_until_it_enters_a_code(client):
    start_signup(client)
    client.mailbox.clear()
    accounts.RESEND_SECONDS, saved = 0, accounts.RESEND_SECONDS  # let login send a fresh code at once
    try:
        response = client.post("/auth/login", json={"email": ASHA["email"], "password": ASHA["password"]})
    finally:
        accounts.RESEND_SECONDS = saved
    assert response.status_code == 200 and response.json()["verify"] is True and "token" not in response.json()
    assert len(client.mailbox) == 1
    assert confirm(client, code_in(client.mailbox[-1])).status_code == 200


def test_a_wrong_password_sends_no_code(client):
    start_signup(client)
    client.mailbox.clear()
    response = client.post("/auth/login", json={"email": ASHA["email"], "password": "wrong password"})
    assert response.status_code == 401 and client.mailbox == []


def test_wrong_codes_count_down_then_stop_working(client):
    start_signup(client)
    right = code_in(client.mailbox[-1])
    wrong = "000000" if right != "000000" else "111111"
    answers = [confirm(client, wrong) for _ in range(accounts.MAX_ATTEMPTS)]
    assert [a.status_code for a in answers] == [400] * (accounts.MAX_ATTEMPTS - 1) + [429]
    assert "4 tries left" in answers[0].json()["detail"] and "1 try left" in answers[3].json()["detail"]
    assert confirm(client, right).status_code == 400  # the right code no longer works either


def test_an_expired_code_doesnt_work(client, monkeypatch):
    monkeypatch.setattr(accounts, "CODE_MINUTES", -1)
    start_signup(client)
    response = confirm(client, code_in(client.mailbox[-1]))
    assert response.status_code == 400 and "expired" in response.json()["detail"]


def test_the_code_also_needs_the_accounts_password(client):
    # Someone signing up with another person's email can't take over the account when
    # that person types the code: confirming needs the password too
    start_signup(client)
    response = confirm(client, code_in(client.mailbox[-1]), password="someone else's password")
    assert response.status_code == 400


def test_resend_waits_a_minute_then_sends_a_new_code(client, monkeypatch):
    start_signup(client)
    first = code_in(client.mailbox[-1])
    again = client.post("/auth/resend", json={"email": ASHA["email"], "password": ASHA["password"]})
    assert again.status_code == 200 and 0 < again.json()["wait"] <= 60 and len(client.mailbox) == 1
    monkeypatch.setattr(accounts, "RESEND_SECONDS", 0)
    client.post("/auth/resend", json={"email": ASHA["email"], "password": ASHA["password"]})
    assert len(client.mailbox) == 2
    second = code_in(client.mailbox[-1])
    if second != first:
        assert confirm(client, first).status_code == 400  # only the newest code works
    assert confirm(client, second).status_code == 200


def test_at_most_five_emails_an_hour(client, monkeypatch):
    monkeypatch.setattr(accounts, "RESEND_SECONDS", 0)
    start_signup(client)
    answers = [client.post("/auth/resend", json={"email": ASHA["email"], "password": ASHA["password"]})
               for _ in range(5)]
    assert [a.status_code for a in answers] == [200] * 4 + [429]
    assert len(client.mailbox) == accounts.MAX_SENDS_PER_HOUR


def test_an_unconfirmed_email_can_sign_up_again(client, monkeypatch):
    # A typo in the password, or a lost code: signing up again starts over
    monkeypatch.setattr(accounts, "RESEND_SECONDS", 0)
    start_signup(client)
    start_signup(client, password="a new password")
    assert confirm(client, code_in(client.mailbox[-1]), password="a new password").status_code == 200


def test_if_the_email_cant_be_sent_asking_again_works_at_once(client, monkeypatch):
    def broken(to, subject, text):
        raise mailer.MailError("The email couldn't be sent. Try again in a minute.")
    monkeypatch.setattr(mailer, "send", broken)
    response = client.post("/auth/signup", json=ASHA)
    assert response.status_code == 502
    monkeypatch.setattr(mailer, "send", lambda to, subject, text: client.mailbox.append({"text": text, "subject": subject}))
    assert client.post("/auth/resend", json={"email": ASHA["email"], "password": ASHA["password"]}).status_code == 200
    assert len(client.mailbox) == 1


def test_accounts_from_before_email_codes_confirm_at_next_login(tmp_path, monkeypatch):
    # An old database has no `verified` column: it's added, and those accounts aren't confirmed yet
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, "
                "password TEXT NOT NULL, created REAL NOT NULL)")
    old.execute("INSERT INTO users (email, name, password, created) VALUES ('old@example.com', 'Old', 'x', 0)")
    old.commit()
    old.close()
    monkeypatch.setattr(accounts, "DB_PATH", str(path))
    db = accounts.connect()
    assert db.execute("SELECT verified FROM users").fetchone()[0] == 0
    db.close()


def test_one_account_per_email(client):
    signup(client)
    response = client.post("/auth/signup", json={**ASHA, "email": "asha@example.com"})
    assert response.status_code == 409


def test_login(client):
    signup(client)
    response = client.post("/auth/login", json={"email": " ASHA@example.com ", "password": ASHA["password"]})
    assert response.status_code == 200 and response.json()["user"]["name"] == "Asha Rawat"


def test_wrong_password_and_unknown_email_get_the_same_answer(client):
    signup(client)
    wrong = client.post("/auth/login", json={"email": ASHA["email"], "password": "wrong password"})
    nobody = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong password"})
    assert wrong.status_code == nobody.status_code == 401
    assert wrong.json() == nobody.json()


def test_logout_ends_the_session(client):
    token = signup(client)["token"]
    assert client.post("/auth/logout", headers=auth(token)).status_code == 204
    assert client.get("/auth/me", headers=auth(token)).status_code == 401


def test_expired_session_is_refused(client, monkeypatch):
    monkeypatch.setattr(accounts, "SESSION_DAYS", -1)
    token = signup(client)["token"]
    assert client.get("/auth/me", headers=auth(token)).status_code == 401


def test_requests_without_a_session_are_refused(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/programs", headers=auth("made-up-token")).status_code == 401
    assert client.post("/programs", json=PROGRAM).status_code == 401


def test_login_attempts_are_rate_limited(client):
    for _ in range(10):
        client.post("/auth/login", json={"email": "a@b.co", "password": "wrong password"})
    response = client.post("/auth/login", json={"email": "a@b.co", "password": "wrong password"})
    assert response.status_code == 429


# ---------- Saved programs ----------

def test_save_list_open_update_delete(client):
    headers = auth(signup(client)["token"])
    saved = client.post("/programs", json=PROGRAM, headers=headers)
    assert saved.status_code == 201
    program_id = saved.json()["id"]

    listed = client.get("/programs", headers=headers).json()
    assert [(p["id"], p["title"], p["language"]) for p in listed] == [(program_id, "Average", "python")]
    assert "code" not in listed[0]  # the list is light; opening one gets the code

    assert client.get(f"/programs/{program_id}", headers=headers).json()["code"] == "print(1)\n"

    changed = client.put(f"/programs/{program_id}", json={**PROGRAM, "code": "print(2)\n", "input": "5\n"},
                         headers=headers)
    assert changed.status_code == 200 and changed.json()["code"] == "print(2)\n"
    assert changed.json()["input"] == "5\n"

    assert client.delete(f"/programs/{program_id}", headers=headers).status_code == 204
    assert client.get("/programs", headers=headers).json() == []


def test_newest_program_comes_first(client):
    headers = auth(signup(client)["token"])
    first = client.post("/programs", json={**PROGRAM, "title": "First"}, headers=headers).json()["id"]
    client.post("/programs", json={**PROGRAM, "title": "Second"}, headers=headers)
    client.put(f"/programs/{first}", json={**PROGRAM, "title": "First"}, headers=headers)
    assert [p["title"] for p in client.get("/programs", headers=headers).json()] == ["First", "Second"]


def test_a_student_cannot_see_or_change_another_students_programs(client):
    asha = auth(signup(client)["token"])
    ravi = auth(signup(client, name="Ravi", email="ravi@example.com")["token"])
    program_id = client.post("/programs", json=PROGRAM, headers=asha).json()["id"]

    assert client.get("/programs", headers=ravi).json() == []
    assert client.get(f"/programs/{program_id}", headers=ravi).status_code == 404
    assert client.put(f"/programs/{program_id}", json=PROGRAM, headers=ravi).status_code == 404
    assert client.delete(f"/programs/{program_id}", headers=ravi).status_code == 404
    assert client.get(f"/programs/{program_id}", headers=asha).status_code == 200


@pytest.mark.parametrize("changes, status", [
    ({"title": "   "}, 400),
    ({"language": "java"}, 400),
    ({"code": "x" * 20_001}, 422),
])
def test_programs_are_checked(client, changes, status):
    headers = auth(signup(client)["token"])
    assert client.post("/programs", json={**PROGRAM, **changes}, headers=headers).status_code == status


# ---------- Feedback ----------

REPORT = {"category": "wrong-answer", "message": "The Why answer for total skips line 3.",
          "language": "python", "code": "total = 0\n", "input": "", "step": 7}


def test_feedback_is_stored_with_the_attached_program(client):
    headers = auth(signup(client)["token"])
    sent = client.post("/feedback", json=REPORT, headers=headers)
    assert sent.status_code == 201
    assert sent.json()["status"] == "open" and sent.json()["attached"] is True
    db = sqlite3.connect(accounts.DB_PATH)
    stored = db.execute("SELECT category, message, language, code, step FROM feedback").fetchone()
    db.close()
    assert stored == ("wrong-answer", REPORT["message"], "python", "total = 0\n", 7)


def test_feedback_without_the_program(client):
    headers = auth(signup(client)["token"])
    sent = client.post("/feedback", json={"category": "idea", "message": "A dark theme for the terminal, please."},
                       headers=headers)
    assert sent.status_code == 201 and sent.json()["attached"] is False


def test_feedback_needs_a_login(client):
    assert client.post("/feedback", json=REPORT).status_code == 401
    assert client.get("/feedback").status_code == 401


@pytest.mark.parametrize("changes, message", [
    ({"message": "  broken "}, "at least 10"),
    ({"category": "spam"}, "what the feedback is about"),
    ({"message": "x" * 4001}, "4,000"),
    ({"language": "java"}, "Python, C or C++"),
])
def test_feedback_is_checked(client, changes, message):
    headers = auth(signup(client)["token"])
    response = client.post("/feedback", json={**REPORT, **changes}, headers=headers)
    assert response.status_code == 400 and message in response.json()["detail"]


def test_students_see_only_their_own_feedback_and_its_reply(client):
    asha = auth(signup(client)["token"])
    ravi = auth(signup(client, name="Ravi", email="ravi@example.com")["token"])
    report_id = client.post("/feedback", json=REPORT, headers=asha).json()["id"]
    assert client.get("/feedback", headers=ravi).json() == []

    db = sqlite3.connect(accounts.DB_PATH)  # what show_feedback.py --resolve does
    with db:
        db.execute("UPDATE feedback SET status = 'resolved', reply = 'Fixed, thanks!' WHERE id = ?", (report_id,))
    db.close()
    [mine] = client.get("/feedback", headers=asha).json()
    assert (mine["status"], mine["reply"]) == ("resolved", "Fixed, thanks!")


def test_feedback_is_rate_limited(client):
    backend.feedback_limiter.seen.clear()
    headers = auth(signup(client)["token"])
    codes = [client.post("/feedback", json=REPORT, headers=headers).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]
