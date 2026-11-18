"""Email & WhatsApp delivery.

Playbook rules applied:
* Human-in-the-loop - messages are only *queued* by staff; nothing leaves the CRM
  until someone approves it in the Outbox.
* Dynamic credentials - SMTP / WhatsApp secrets are read from Config at send time.
* Per-run budgets - approvals are capped per batch and per day.
"""
from __future__ import annotations

import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import quote

import requests

TEMPLATES = {
    "payment_reminder": {
        "label": "Subscription payment reminder",
        "subject": "{org} - Annual subscription reminder",
        "body": (
            "Dear {name},\n\nGreetings from the {org_name}.\n\n"
            "This is a gentle reminder that your annual membership subscription of Rs. {fee} "
            "(Member ID: {member_id}) is pending. Kindly renew at the earliest to continue "
            "enjoying member benefits.\n\nWarm regards,\n{org}"
        ),
    },
    "payment_thanks": {
        "label": "Payment acknowledgement",
        "subject": "{org} - Subscription received",
        "body": (
            "Dear {name},\n\nThank you! We have received your subscription of Rs. {subscription} "
            "(Member ID: {member_id}).\n\nWarm regards,\n{org}"
        ),
    },
    "welcome": {
        "label": "Welcome new member",
        "subject": "Welcome to {org}",
        "body": (
            "Dear {name},\n\nWelcome to the {org_name}! "
            "Your Member ID is {member_id}. We look forward to your active participation in "
            "the {chapter} chapter.\n\nWarm regards,\n{org}"
        ),
    },
    "event": {
        "label": "Event / study circle invitation",
        "subject": "{org} - You are invited",
        "body": (
            "Dear {name},\n\nYou are cordially invited to our upcoming study circle meeting. "
            "Details: <date, time, venue>.\n\nWarm regards,\n{org}"
        ),
    },
    "custom": {"label": "Custom message", "subject": "", "body": "Dear {name},\n\n"},
}


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


ORG = {"org": "", "org_name": ""}  # filled in by the app from Config


def render(text: str, member: dict, fee: int) -> str:
    ctx = _SafeDict({**member, **ORG, "fee": fee})
    ctx["name"] = (member.get("name") or "Member").title()
    return text.format_map(ctx)


def normalize_phone(phone: str, country_code: str = "91") -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        return country_code + digits
    if len(digits) == 11 and digits.startswith("0"):
        return country_code + digits[1:]
    return digits if len(digits) >= 11 else ""


def valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""))


def whatsapp_link(phone: str, text: str, country_code: str = "91") -> str:
    num = normalize_phone(phone, country_code)
    return f"https://wa.me/{num}?text={quote(text)}" if num else ""


def mailto_link(email: str, subject: str, body: str) -> str:
    return f"mailto:{email}?subject={quote(subject)}&body={quote(body)}"


class Messenger:
    def __init__(self, cfg):
        self.cfg = cfg

    @property
    def email_ready(self) -> bool:
        c = self.cfg
        return bool(c.SMTP_HOST and c.SMTP_USER and c.SMTP_PASSWORD and c.SMTP_FROM)

    @property
    def whatsapp_ready(self) -> bool:
        return bool(self.cfg.WHATSAPP_TOKEN and self.cfg.WHATSAPP_PHONE_NUMBER_ID)

    def send(self, msg: dict) -> tuple[str, str]:
        """Return (status, error). status is Sent / Failed / Manual."""
        try:
            if msg["channel"] == "Email":
                if not self.email_ready:
                    return "Manual", "SMTP not configured - use the mail link to send manually."
                self._send_email(msg["recipient"], msg["subject"], msg["body"])
                return "Sent", ""
            if msg["channel"] == "WhatsApp":
                if not self.whatsapp_ready:
                    return "Manual", "WhatsApp API not configured - use the WhatsApp link."
                self._send_whatsapp(msg["recipient"], msg["body"])
                return "Sent", ""
            return "Failed", f"Unknown channel {msg['channel']}"
        except Exception as exc:  # noqa: BLE001 - surface any provider error to the user
            return "Failed", str(exc)[:300]

    def _send_email(self, to: str, subject: str, body: str):
        c = self.cfg
        em = EmailMessage()
        em["From"] = c.SMTP_FROM
        em["To"] = to
        em["Subject"] = subject
        em.set_content(body)
        with smtplib.SMTP(c.SMTP_HOST, c.SMTP_PORT, timeout=20) as s:
            if c.SMTP_USE_TLS:
                s.starttls(context=ssl.create_default_context())
            s.login(c.SMTP_USER, c.SMTP_PASSWORD)
            s.send_message(em)

    def _send_whatsapp(self, phone: str, body: str):
        c = self.cfg
        url = f"https://graph.facebook.com/{c.WHATSAPP_API_VERSION}/{c.WHATSAPP_PHONE_NUMBER_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": normalize_phone(phone, c.DEFAULT_COUNTRY_CODE),
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        r = requests.post(url, json=payload, timeout=20,
                          headers={"Authorization": f"Bearer {c.WHATSAPP_TOKEN}"})
        if r.status_code >= 300:
            raise RuntimeError(f"WhatsApp API {r.status_code}: {r.text[:200]}")


def sent_today(comms: list[dict]) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for c in comms if c["status"] == "Sent" and c["sent_on"].startswith(today))
