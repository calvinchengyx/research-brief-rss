"""Email delivery: Brevo API (default) or plain SMTP."""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

import requests

log = logging.getLogger(__name__)


def send(recipients: list[str], subject: str, html: str, text: str, settings: dict) -> None:
    email = settings.get("email") or {}
    provider = email.get("provider", "brevo")
    sender = os.environ.get("SENDER_EMAIL") or os.environ.get("SMTP_USER")
    if not sender:
        raise RuntimeError("SENDER_EMAIL secret is not set")
    name = email.get("sender_name", "Research Brief")
    for to in recipients:  # one message each, so recipients don't see each other
        if provider == "brevo":
            _brevo(sender, name, to, subject, html, text)
        else:
            _smtp(sender, name, to, subject, html, text)
        log.info("Sent to %s", to)


def _brevo(sender: str, name: str, to: str, subject: str, html: str, text: str) -> None:
    key = os.environ.get("BREVO_API_KEY")
    if not key:
        raise RuntimeError("BREVO_API_KEY secret is not set")
    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": key, "accept": "application/json", "content-type": "application/json"},
        json={"sender": {"name": name, "email": sender}, "to": [{"email": to}],
              "subject": subject, "htmlContent": html, "textContent": text},
        timeout=60,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Brevo rejected the email ({resp.status_code}): {resp.text[:500]}")


def _smtp(sender: str, name: str, to: str, subject: str, html: str, text: str) -> None:
    msg = EmailMessage()
    msg["From"] = f"{name} <{sender}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT", "465"))) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)
