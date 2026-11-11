"""
email_service.py - Send email with SMTP.

Passwords come from the .env file only. For Gmail you must create an
"App Password" (Google Account > Security > 2-Step Verification > App passwords).
The assistant (assistant.py) always asks you to confirm BEFORE calling send_email().
"""

import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

CONTACTS_FILE = Path(__file__).resolve().parent / "config" / "contacts.json"
EMAIL_PATTERN = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


class EmailError(Exception):
    """Raised with a friendly message that can be spoken to the user."""


def _credentials():
    address = os.getenv("EMAIL_ADDRESS", "").strip()
    password = os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    return address, password


def is_configured():
    address, password = _credentials()
    return bool(address and password) and not address.startswith("your_") \
        and not password.startswith("your_")


def load_contacts(path=CONTACTS_FILE):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {k.lower(): v for k, v in data.items()}
    except (OSError, json.JSONDecodeError):
        return {}


def is_valid_email(address):
    return bool(EMAIL_PATTERN.match(address or ""))


def resolve_recipient(spoken, contacts=None):
    """
    Turn what the user said/typed into an email address.
    Accepts a contact name from config/contacts.json, or a spoken address like
    "john dot smith at gmail dot com". Returns None if it is not understood.
    """
    contacts = load_contacts() if contacts is None else contacts
    text = (spoken or "").strip().lower()
    if text in contacts and is_valid_email(contacts[text]):
        return contacts[text]

    text = re.sub(r"\s+at the rate( of)?\s+|\s+at\s+", "@", text)
    text = re.sub(r"\s+dot\s+", ".", text)
    text = re.sub(r"\s+underscore\s+", "_", text)
    text = re.sub(r"\s+(dash|hyphen)\s+", "-", text)
    text = text.replace(" ", "")
    return text if is_valid_email(text) else None


def send_email(to_address, subject, body):
    """Send one email. Raises EmailError when something goes wrong."""
    if not is_configured():
        raise EmailError("Email is not set up. Add EMAIL_ADDRESS and EMAIL_APP_PASSWORD to the .env file.")
    if not is_valid_email(to_address):
        raise EmailError("That email address does not look valid.")

    sender, password = _credentials()
    server = os.getenv("SMTP_SERVER", "smtp.gmail.com").strip()
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        raise EmailError("SMTP_PORT in the .env file must be a number such as 587.")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)

    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(server, port, timeout=20, context=context) as smtp:
                smtp.login(sender, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(server, port, timeout=20) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(sender, password)
                smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise EmailError(
            "Email login failed. For Gmail, use an App Password instead of your normal password."
        )
    except smtplib.SMTPRecipientsRefused:
        raise EmailError("The mail server refused that recipient address.")
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"I could not send the email: {exc}")
