"""Tests for backend/mailer.py with a stand-in for the SMTP server (no email is sent).

Run from the kaaran folder:   python -m pytest tests -v
"""
import os
import smtplib
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import mailer  # noqa: E402


class FakeSMTP:
    """Records what mailer does with the server."""
    made = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.calls = host, port, []
        FakeSMTP.made.append(self)

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, message):
        self.calls.append(("send", message["From"], message["To"], message["Subject"], message.get_content()))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def gmail(monkeypatch):
    FakeSMTP.made = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    for key, value in {"SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_USER": "kaaran@gmail.com",
                       "SMTP_PASSWORD": "app password", "MAIL_FROM": "Kaaran <kaaran@gmail.com>"}.items():
        monkeypatch.setenv(key, value)


def test_without_smtp_host_the_email_is_printed(monkeypatch, capsys):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert mailer.mode() == "console"
    mailer.send("asha@example.com", "Your Kaaran code: 123456", "Your Kaaran code is 123456")
    assert "Your Kaaran code is 123456" in capsys.readouterr().out


def test_port_587_uses_starttls_then_logs_in_and_sends(gmail):
    assert mailer.mode() == "smtp"
    mailer.send("asha@example.com", "Your Kaaran code: 123456", "Your Kaaran code is 123456")
    [server] = FakeSMTP.made
    assert (server.host, server.port) == ("smtp.gmail.com", 587)
    assert server.calls[0] == "starttls"  # encrypted before the password is sent
    assert server.calls[1] == ("login", "kaaran@gmail.com", "app password")
    sent = server.calls[2]
    assert sent[1:4] == ("Kaaran <kaaran@gmail.com>", "asha@example.com", "Your Kaaran code: 123456")
    assert "123456" in sent[4]


def test_port_465_uses_ssl_from_the_start(gmail, monkeypatch):
    monkeypatch.setenv("SMTP_PORT", "465")
    mailer.send("asha@example.com", "Subject", "Text")
    [server] = FakeSMTP.made
    assert server.port == 465 and "starttls" not in server.calls


def test_a_server_problem_becomes_a_plain_message(gmail, monkeypatch):
    class Refused(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
    monkeypatch.setattr(smtplib, "SMTP", Refused)
    with pytest.raises(mailer.MailError, match="couldn't be sent"):
        mailer.send("asha@example.com", "Subject", "Text")
