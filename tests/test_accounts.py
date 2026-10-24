"""Tests for accounts and saved programs (backend/accounts.py and the
/auth and /programs endpoints), on a fresh database in a temporary folder.

Run from the kaaran folder:   python -m pytest tests -v
Skipped if FastAPI isn't installed (pip install -r backend/requirements.txt).
"""
import os
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
    return TestClient(backend.app)


def signup(client, **changes):
    response = client.post("/auth/signup", json={**ASHA, **changes})
    assert response.status_code == 201, response.text
    return response.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- Accounts ----------

def test_signup_logs_in_and_normalises_the_email(client):
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
