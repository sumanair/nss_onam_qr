# config.py
from __future__ import annotations
import os, re
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Load .env once, globally
load_dotenv(find_dotenv() or (Path(__file__).parent / ".env"))

def _clean(val: Optional[str], default: Optional[str] = None) -> Optional[str]:
    if val is None:
        return default
    v = val.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1].strip()
    return v

def _must(name: str) -> str:
    v = _clean(os.getenv(name))
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v

def _maybe_int(name: str, default: Optional[int] = None) -> Optional[int]:
    v = _clean(os.getenv(name))
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default

# App timezone (used for created_at/last_updated_at)
APP_TZ = "America/Chicago"

# ----- Admin / Verifier credentials -----
ADMIN_USERNAME   = _must("ADMIN_USERNAME")
ADMIN_NAME       = _must("ADMIN_NAME")
ADMIN_PASSWORD   = _must("ADMIN_PASSWORD")

VERIFIER_USERNAME = _must("VERIFIER_USERNAME")
VERIFIER_NAME     = _must("VERIFIER_NAME")
VERIFIER_PASSWORD = _must("VERIFIER_PASSWORD")

# ----- AWS / S3 -----
AWS_ACCESS_KEY_ID     = _must("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = _must("AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION    = _must("AWS_DEFAULT_REGION")

S3_BUCKET = _must("S3_BUCKET")
S3_PREFIX   = _clean(os.getenv("S3_PREFIX"), "qrcodes/")  # folder prefix for QR images
S3_QR_LOCAL_DIR = _must("S3_QR_LOCAL_DIR") 
# ----- QR Preview root (URL the QR points to) -----
QR_ROOT_PATH = _must("QR_ROOT_PATH")

# Optional ACL (None to omit). If you need public access via HTTPS URL, use "public-read".
S3_QR_ACL = None  # or "public-read"
# ExtraArgs passed to S3 upload (headers, etc.)
S3_QR_EXTRA_ARGS = {
    "ContentDisposition": "inline",
    "CacheControl": "no-store, no-cache, must-revalidate, max-age=0",
    # "Expires": "0",  # usually unnecessary if CacheControl is set
}

# If True, return a presigned GET URL after upload; else return the public HTTPS URL.
S3_USE_PRESIGNED = False
S3_PRESIGN_EXPIRES = 900  # seconds


# The root viewer page that decodes ?data=<base64url> (your hosted QR viewer)
#QR_ROOT_PATH = "https://sumanair.github.io/scanner/l1.html"
QR_ROOT_PATH = _must("QR_ROOT_PATH")

# QR image rendering options
from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
QR_IMAGE_OPTS = {
    "version": None,                 # let qrcode fit automatically
    "error_correction": ERROR_CORRECT_M,
    "box_size": 10,
    "border": 4,
}

# ----- Gmail / SMTP -----

# ── SMTP / Email config ───────────────────────────────────────
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_SECURITY = "ssl"  # "ssl" | "starttls" | "none"

# Auth (app password recommended for Gmail)
SMTP_USERNAME = _must("GMAIL_ADDRESS")
SMTP_PASSWORD = _must("GMAIL_PASSWORD")

SENDER_EMAIL  = _must("GMAIL_ADDRESS")
DEFAULT_BCC    = _clean(os.getenv("DEFAULT_BCC"), "eventsnssnt@gmail.com")
SENDER_NAME    = _clean(os.getenv("SENDER_NAME"), "NSS North Texas Team")
REPLY_TO       = _clean(os.getenv("REPLY_TO"))  # optional
EMAIL_SUBJECT_PREFIX = _clean(os.getenv("EMAIL_SUBJECT_PREFIX"))
EMAIL_DRY_RUN = False                 # True → log instead of sending
EMAIL_ALLOWLIST_REGEX = None          # e.g. r"@example\.com$" to restrict recipients

# Optional org header (helps mail clients surface unsubscribe)
ORG_LIST_UNSUBSCRIBE = None           # e.g. "<mailto:unsubscribe@example.com>, <https://example.com/unsub>" 
# ----- Database -----
DB_HOST = _must("DB_HOST")
DB_PORT = _maybe_int("DB_PORT", 5432) or 5432
DB_NAME = _must("DB_NAME")
DB_USER = _must("DB_USER")
DB_PASSWORD = _must("DB_PASSWORD")

SQLALCHEMY_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ----- App Defaults -----
EVENT_NAME = _clean(os.getenv("EVENT_NAME"), "Chinga Pulari 2025 (ചിങ്ങ പുലരി 2025)")


# Upload schema controls
UPLOAD_COLUMN_ALIASES = {
    "number_of_attendees": "number_of_attendees",
    "no_of_attendees": "number_of_attendees",
    "number_attendees": "number_of_attendees",
    "attendees": "number_of_attendees",
    "num_attendees": "number_of_attendees",
    "num_of_attendees": "number_of_attendees",
    "attendee_count": "number_of_attendees",
}

UPLOAD_REQUIRED_COLS = ["transaction_id", "username", "email",  "amount", "paid_for"]

UPLOAD_ALLOWED_COLS = [
    "transaction_id", "username", "email", "phone", "address",
    "membership_paid", "early_bird_applied", "payment_date", "amount", "paid_for", "remarks",
    "qr_generated", "qr_sent", "number_checked_in", "qr_reissued_yn",
    "qr_code_filename", "qr_generated_at", "qr_sent_at",
    "number_of_attendees", "created_at", "last_updated_at",
]

UPLOAD_DEFAULTS = {
    "address": "",
    "membership_paid": False,
    "early_bird_applied": False,
    "qr_generated": False,
    "qr_sent": False,
    "number_checked_in": 0,
    "qr_reissued_yn": False,
    "qr_code_filename": "",
    "qr_generated_at": None,
    "qr_sent_at": None,
    "number_of_attendees": 1,
    "remarks": "",
    "amount": 0.0,
}

UPLOAD_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def validate_config() -> None:
    if not QR_ROOT_PATH.lower().startswith(("http://", "https://")):
        raise RuntimeError("QR_ROOT_PATH must be an absolute http(s) URL")
    if not S3_PREFIX.endswith("/"):
        raise RuntimeError("S3_PREFIX should end with '/' for clean key joins")
