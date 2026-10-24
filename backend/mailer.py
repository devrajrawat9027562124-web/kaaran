"""Sends email (the sign-up codes) through an SMTP server, with Python's own smtplib.

Settings (backend/.env):
    SMTP_HOST, SMTP_PORT (587 = STARTTLS, 465 = SSL), SMTP_USER, SMTP_PASSWORD, MAIL_FROM

Gmail: SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, SMTP_USER=you@gmail.com,
SMTP_PASSWORD = an App Password (Google Account -> Security -> 2-Step
Verification -> App passwords; your normal password won't work), and
MAIL_FROM="Kaaran <you@gmail.com>".

With no SMTP_HOST, nothing is sent: the email is printed in the server's
terminal instead. That is for trying Kaaran on your own computer only.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage


class MailError(Exception):
    pass


def mode():
    return "smtp" if os.environ.get("SMTP_HOST") else "console"


def send(to, subject, text):
    if mode() == "console":
        print(f"\n----- Kaaran email (not sent: SMTP_HOST isn't set in backend/.env) -----\n"
              f"To: {to}\nSubject: {subject}\n\n{text}\n"
              f"-------------------------------------------------------------------------\n", flush=True)
        return

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    message = EmailMessage()
    message["From"] = os.environ.get("MAIL_FROM") or user
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    context = ssl.create_default_context()
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, context=context, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls(context=context)
        with server:
            if user:
                server.login(user, os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as e:
        # The detail goes to the server log; the student gets a plain message
        print(f"Kaaran: couldn't send email to {to}: {e!r}", flush=True)
        raise MailError("The email couldn't be sent. Try again in a minute.") from e
