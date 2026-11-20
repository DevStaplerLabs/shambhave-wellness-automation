"""Email via SMTP (e.g. Google Workspace with an app password). Settings come from environment secrets.
If SMTP is not configured, the email is written to data/outbox/ instead, so nothing is lost."""
import os
import smtplib
import ssl
from email.message import EmailMessage

from .store import write_text


def send_email(subject, html, text, tag):
    host, user, pwd = os.environ.get("SMTP_HOST"), os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    to = [a.strip() for a in os.environ.get("REPORT_TO", "").split(",") if a.strip()]
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
