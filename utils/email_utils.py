# utils/email_utils.py
import os
import re
import smtplib
import unicodedata
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.header import Header
from email.utils import formataddr
from email import encoders
from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")


# ---------- helpers ----------
def _clean(s: str) -> str:
    """Normalize unicode, replace NBSPs with spaces, return safe string."""
    if s is None:
        return ""
    s = str(s).replace("\xa0", " ")
    return unicodedata.normalize("NFC", s)

def _clean_email(e: str) -> str:
    """Normalize and remove all whitespace characters from an email."""
    e = _clean(e)
    # remove any whitespace (incl. NBSP) inside the address
    return re.sub(r"\s+", "", e)

def _assert_gmail():
    if not GMAIL_ADDRESS or not GMAIL_PASSWORD:
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_PASSWORD not configured (.env)")


# ---------- URL-only sender ----------
def send_email_with_qr_url(
    recipient: str,
    subject: str,
    body_html: str,
    sender_name: str = "NSS Team",
    reply_to: str | None = None,
):
    """
    Sends an HTML email that contains a link to the QR code (no attachment).

    Parameters
    ----------
    recipient : str
        Destination email address.
    subject : str
        Email subject (UTF-8 supported).
    body_html : str
        HTML body (include your <a href="...">View QR</a> link).
    sender_name : str
        Display name for the From header.
    reply_to : str | None
        Optional Reply-To address.
    """
    _assert_gmail()

    recipient  = _clean_email(recipient)
    subject    = _clean(subject)
    body_html  = _clean(body_html)
    sender_name = _clean(sender_name)
    reply_to   = _clean_email(reply_to) if reply_to else None

    msg = MIMEMultipart()
    msg["From"] = formataddr((str(Header(sender_name, "utf-8")), GMAIL_ADDRESS))
    msg["To"] = recipient
    msg["Subject"] = Header(subject, "utf-8")
    if reply_to:
        msg["Reply-To"] = reply_to

    msg.attach(MIMEText(body_html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(GMAIL_ADDRESS, GMAIL_PASSWORD)  # Use a Gmail App Password
        server.send_message(msg)


# ---------- Attachment sender ----------
def send_email_with_qr(
    recipient: str,
    subject: str,
    body_html: str,
    attachment_path: str,
    sender_name: str = "NSS Team",
    reply_to: str | None = None,
):
    """
    Sends an email with a QR attachment. Fully UTF‑8 safe (subject/body/filename).

    Parameters
    ----------
    recipient : str
        Destination email address.
    subject : str
        Email subject (UTF-8 supported).
    body_html : str
        HTML body.
    attachment_path : str
        Local file path to the QR image to attach.
    sender_name : str
        Display name for the From header.
    reply_to : str | None
        Optional Reply-To address.
    """
    _assert_gmail()

    recipient    = _clean_email(recipient)
    subject      = _clean(subject)
    body_html    = _clean(body_html)
    sender_name  = _clean(sender_name)
    reply_to     = _clean_email(reply_to) if reply_to else None
    filename_safe = _clean(os.path.basename(attachment_path))

    msg = MIMEMultipart()
    msg["From"] = formataddr((str(Header(sender_name, "utf-8")), GMAIL_ADDRESS))
    msg["To"] = recipient
    msg["Subject"] = Header(subject, "utf-8")
    if reply_to:
        msg["Reply-To"] = reply_to

    # UTF-8 HTML body
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    # Attachment (UTF-8 filename via RFC 2231)
    with open(attachment_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", filename_safe))
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(GMAIL_ADDRESS, GMAIL_PASSWORD)  # Use a Gmail App Password
        server.send_message(msg)
