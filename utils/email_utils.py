# utils/email_utils.py
from __future__ import annotations

import re
import smtplib
import unicodedata
from typing import Iterable, Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.header import Header
from email.utils import formataddr, make_msgid
from email import encoders
import html as html_lib

from config import (
    # Identity / auth
    SMTP_HOST,
    SMTP_PORT,
    SMTP_SECURITY,       # "ssl" | "starttls" | "none"
    SMTP_USERNAME,
    SMTP_PASSWORD,
    SENDER_EMAIL,        # replaces GMAIL_ADDRESS
    SENDER_NAME,
    REPLY_TO,

    # Policy
    DEFAULT_BCC,
    EMAIL_SUBJECT_PREFIX,  # e.g. "[NSS Onam] "
    EMAIL_DRY_RUN,         # True/False
    EMAIL_ALLOWLIST_REGEX, # regex string or None

    # Optional org headers
    ORG_LIST_UNSUBSCRIBE,  # mailto:... or <https://...>
)

# ---------- helpers ----------
def _clean(s: str) -> str:
    """Normalize unicode and strip weird spaces."""
    if s is None:
        return ""
    s = str(s).replace("\xa0", " ")
    return unicodedata.normalize("NFC", s)

def _clean_email(e: str) -> str:
    """Normalize and remove all whitespace inside email fields."""
    e = _clean(e)
    return re.sub(r"\s+", "", e)

def _strip_html_to_text(html: str) -> str:
    """Very light HTML→text fallback for multipart/alternative."""
    if not html:
        return ""
    # Unescape entities, remove tags, collapse whitespace.
    txt = html_lib.unescape(re.sub(r"<br\s*/?>", "\n", html, flags=re.I))
    txt = re.sub(r"<[/!]?[a-zA-Z][^>]*>", "", txt)  # strip tags
    txt = re.sub(r"[ \t]+\n", "\n", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()

def _compile_allowlist() -> Optional[re.Pattern]:
    if EMAIL_ALLOWLIST_REGEX:
        try:
            return re.compile(EMAIL_ALLOWLIST_REGEX, re.I)
        except re.error:
            raise RuntimeError(f"Bad EMAIL_ALLOWLIST_REGEX: {EMAIL_ALLOWLIST_REGEX}")
    return None

_ALLOWLIST_RE = _compile_allowlist()

def _allowed(addr: str) -> bool:
    """If allowlist is configured, only allow addresses that match."""
    if not _ALLOWLIST_RE:
        return True
    return bool(_ALLOWLIST_RE.search(addr))

def _assert_smtp() -> None:
    if not (SMTP_HOST and SMTP_PORT is not None and SENDER_EMAIL):
        raise RuntimeError("SMTP config incomplete (host/port/sender) in config.py")
    if SMTP_SECURITY not in {"ssl", "starttls", "none"}:
        raise RuntimeError("SMTP_SECURITY must be 'ssl', 'starttls', or 'none'")
    if (SMTP_USERNAME and not SMTP_PASSWORD) or (SMTP_PASSWORD and not SMTP_USERNAME):
        raise RuntimeError("SMTP_USERNAME/SMTP_PASSWORD must be provided together")

def _merge_bcc(user_bcc: str | None) -> str | None:
    """
    Always include DEFAULT_BCC and merge with any provided bcc.
    Returns a comma-separated string or None.
    """
    bccs: list[str] = []
    if user_bcc:
        bccs.extend([_clean_email(x) for x in user_bcc.split(",") if x])
    if DEFAULT_BCC:
        bccs.extend([_clean_email(x) for x in DEFAULT_BCC.split(",") if x])

    # dedupe while preserving order
    seen = set()
    merged = []
    for addr in bccs:
        if addr and addr not in seen:
            seen.add(addr)
            merged.append(addr)
    return ",".join(merged) if merged else None

def _prefix_subject(subject: str) -> str:
    subject = _clean(subject)
    if EMAIL_SUBJECT_PREFIX and not subject.startswith(EMAIL_SUBJECT_PREFIX):
        return f"{EMAIL_SUBJECT_PREFIX}{subject}"
    return subject

def _check_policy(recipients: Iterable[str], bcc: Optional[str]) -> None:
    recips = [r for r in recipients if r]
    if bcc:
        recips.extend([x.strip() for x in bcc.split(",") if x.strip()])

    bad = [r for r in recips if not _allowed(r)]
    if bad:
        raise RuntimeError(f"Email blocked by allowlist: {', '.join(bad)}")

def _open_smtp():
    if EMAIL_DRY_RUN:
        return None  # signal dry-run
    if SMTP_SECURITY == "ssl":
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        if SMTP_SECURITY == "starttls":
            server.starttls()
    if SMTP_USERNAME and SMTP_PASSWORD:
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
    return server

def _send_message(msg):
    if EMAIL_DRY_RUN:
        # In dry-run, just print a compact summary
        to = msg.get("To", "")
        bcc = msg.get("Bcc", "")
        subj = msg.get("Subject", "")
        print(f"[DRY-RUN] Would send email → TO={to} BCC={bcc} SUBJ={subj}")
        return
    server = _open_smtp()
    try:
        server.send_message(msg)
    finally:
        server.quit()

def _format_from(sender_name: str) -> str:
    sender_name = _clean(sender_name)
    return formataddr((str(Header(sender_name, "utf-8")), SENDER_EMAIL))

# ---------- URL-only sender ----------
def send_email_with_qr_url(
    recipient: str,
    subject: str,
    body_html: str,
    sender_name: str = SENDER_NAME,
    reply_to: str | None = REPLY_TO,
    bcc: str | None = DEFAULT_BCC,
) -> None:
    """
    Sends an HTML email (no inline image) with the provided body.
    Always merges in DEFAULT_BCC and enforces allowlist/dry-run policies.
    """
    _assert_smtp()

    recipient   = _clean_email(recipient)
    subject     = _prefix_subject(subject)
    body_html   = _clean(body_html)
    sender_name = _clean(sender_name)
    reply_to    = _clean_email(reply_to) if reply_to else None
    bcc         = _merge_bcc(bcc)

    _check_policy([recipient], bcc)

    msg = MIMEMultipart("alternative")
    msg["From"] = _format_from(sender_name)
    msg["To"] = recipient
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = Header(subject, "utf-8")
    if reply_to:
        msg["Reply-To"] = reply_to
    if ORG_LIST_UNSUBSCRIBE:
        msg["List-Unsubscribe"] = ORG_LIST_UNSUBSCRIBE

    # Attach both plain & HTML
    msg.attach(MIMEText(_strip_html_to_text(body_html), "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    _send_message(msg)

# ---------- Inline-image sender (CID) ----------
def send_email_with_inline_qr(
    recipient: str,
    subject: str,
    body_intro_html: str,
    *,
    qr_bytes: bytes,
    s3_url: str,
    preview_url: str,
    is_reissue: bool = False,
    sender_name: str = SENDER_NAME,
    reply_to: str | None = REPLY_TO,
    bcc: str | None = DEFAULT_BCC,
    attach_as_file: bool = False,
    attachment_filename: str = "qr.png",
) -> None:
    """
    Sends an HTML email that embeds the QR inline via Content-ID (CID),
    flags re-issues, merges DEFAULT_BCC, and includes preview/download links.
    Enforces allowlist and supports dry-run mode.
    """
    _assert_smtp()

    recipient       = _clean_email(recipient)
    subject         = _prefix_subject(subject)
    body_intro_html = _clean(body_intro_html)
    sender_name     = _clean(sender_name)
    reply_to        = _clean_email(reply_to) if reply_to else None
    bcc             = _merge_bcc(bcc)

    _check_policy([recipient], bcc)

    msg_root = MIMEMultipart("related")
    msg_root["From"] = _format_from(sender_name)
    msg_root["To"] = recipient
    if bcc:
        msg_root["Bcc"] = bcc
    msg_root["Subject"] = Header(subject, "utf-8")
    if reply_to:
        msg_root["Reply-To"] = reply_to
    if ORG_LIST_UNSUBSCRIBE:
        msg_root["List-Unsubscribe"] = ORG_LIST_UNSUBSCRIBE

    alt = MIMEMultipart("alternative")
    msg_root.attach(alt)

    reissue_note = ""
    if is_reissue:
        reissue_note = (
            "<p style='color:#b91c1c; font-weight:600;'>"
            "This is a <u>re-issue</u> of your QR code. "
            "Please use this NEW QR for entry."
            "</p>"
        )

    html = f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif; font-size:15px; line-height:1.5;">
      {body_intro_html}
      {reissue_note}
      <p>
        <a href="{preview_url}" target="_blank" rel="noopener">Open your QR Pass page</a>
        &nbsp;•&nbsp;
        <a href="{s3_url}" target="_blank" rel="noopener">Download the QR (PNG)</a>
      </p>
      <p style="margin:12px 0 6px; font-weight:600;">Your QR (inline):</p>
      <img src="cid:qrcode" alt="QR Code" style="max-width:340px; height:auto; border:1px solid #e5e7eb; border-radius:8px;" />
      <p style="color:#6b7280; font-size:12px; margin-top:10px;">
        If the image doesn't display, use the links above.
      </p>
    </div>
    """.strip()

    # multipart/alternative: text + html
    alt.attach(MIMEText(_strip_html_to_text(html), "plain", "utf-8"))
    alt.attach(MIMEText(html, "html", "utf-8"))

    # Inline QR image with stable CID
    cid = make_msgid(domain=None)  # random but unique
    cid_clean = "qrcode"  # Use fixed ref in HTML
    img = MIMEImage(qr_bytes, _subtype="png")
    img.add_header("Content-ID", f"<{cid_clean}>")
    img.add_header("Content-Disposition", "inline", filename=("utf-8", "", attachment_filename))
    msg_root.attach(img)

    # Optional separate attachment
    if attach_as_file:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(qr_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", attachment_filename))
        msg_root.attach(part)

    _send_message(msg_root)
