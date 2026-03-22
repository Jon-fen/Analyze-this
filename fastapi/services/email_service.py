"""
Email sending via SMTP (standard library only, no new deps).
Configured via env vars: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
"""
import smtplib
import io
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from typing import Optional, Tuple
from config import get_settings


def _smtp_configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_user and s.smtp_pass)


def send_pdf_email(
    to_email: str,
    subject: str,
    body_html: str,
    pdf_buffer: io.BytesIO,
    filename: str,
) -> Tuple[bool, str]:
    """Send an email with a PDF attachment. Returns (ok, error_message)."""
    s = get_settings()
    if not _smtp_configured():
        return False, "Email no configurado. Configura SMTP_HOST, SMTP_USER y SMTP_PASS."

    try:
        msg = MIMEMultipart()
        msg["From"] = s.smtp_from or s.smtp_user
        msg["To"] = to_email
        msg["Subject"] = subject

        msg.attach(MIMEText(body_html, "html", "utf-8"))

        part = MIMEBase("application", "pdf")
        pdf_buffer.seek(0)
        part.set_payload(pdf_buffer.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

        port = int(s.smtp_port or 587)
        with smtplib.SMTP(s.smtp_host, port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(s.smtp_user, s.smtp_pass)
            server.sendmail(msg["From"], [to_email], msg.as_bytes())
        return True, ""
    except Exception as e:
        return False, str(e)


def send_notification_email(to_email: str, subject: str, body_html: str) -> Tuple[bool, str]:
    """Send a plain notification email (no attachment). Returns (ok, error_message)."""
    s = get_settings()
    if not _smtp_configured():
        return False, "Email no configurado."
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = s.smtp_from or s.smtp_user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        port = int(s.smtp_port or 587)
        with smtplib.SMTP(s.smtp_host, port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(s.smtp_user, s.smtp_pass)
            server.sendmail(msg["From"], [to_email], msg.as_bytes())
        return True, ""
    except Exception as e:
        return False, str(e)
