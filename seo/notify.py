"""Email, two options (settings come from environment secrets):
1. Resend (RESEND_API_KEY): no Google settings needed. Without a verified domain, Resend's test sender
   onboarding@resend.dev can only send to the email address the Resend account was created with.
2. SMTP (e.g. Google Workspace with an app password).
If neither is configured, the email is written to data/outbox/ instead, so nothing is lost."""
import os
import smtplib
import ssl
from email.message import EmailMessage

import requests

from .store import write_text


def _send_resend(key, sender, to, subject, html, text):
    r = requests.post("https://api.resend.com/emails", timeout=60,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"from": sender, "to": to, "subject": subject, "html": html, "text": text})
    if r.status_code >= 300:
        raise RuntimeError(f"Resend error {r.status_code}: {r.text[:200]}")
    return f"Sent with Resend to {len(to)} recipient(s)"


def send_email(subject, html, text, tag):
    host, user, pwd = os.environ.get("SMTP_HOST"), os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    to = [a.strip() for a in os.environ.get("REPORT_TO", "").split(",") if a.strip()]
    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key and to:
        sender = os.environ.get("REPORT_FROM") or "Shambhave SEO Bot <onboarding@resend.dev>"
        return _send_resend(resend_key, sender, to, subject, html, text)
    sender = os.environ.get("REPORT_FROM") or user
    if not (host and user and pwd and to):
        p = write_text(f"outbox/{tag}.html", html)
        return f"SMTP not configured, saved to {p.relative_to(p.parents[2])}"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    port = int(os.environ.get("SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
            s.login(user, pwd)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls(context=ctx)
            s.login(user, pwd)
            s.send_message(msg)
    return f"Sent to {len(to)} recipient(s)"
