# services/qr_service.py
import os
import re
import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from utils.qr_s3_utils import build_qr_payload, encode_qr_url, generate_qr_image
from services.s3_service import upload_png, delete_key  # kept for compatibility
from utils.session_cache import put_qr_bytes
from utils.json_utils import to_jsonable
from config import S3_PREFIX

__all__ = ["build_preview_url", "regenerate_and_upload"]

# ──────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────
def _add_query_params(url: str, extra: dict[str, str]) -> str:
    """Return url with extra query params appended (overwriting existing keys)."""
    parts = urlparse(url)
    q = parse_qs(parts.query)
    for k, v in extra.items():
        if v is None or v == "":
            continue
        q[k] = [str(v)]
    new_query = urlencode(q, doseq=True)
    return urlunparse(parts._replace(query=new_query))


def _safe_name(username: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", str(username or "unknown"))


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────
def build_preview_url(row: dict, event_name: str) -> str:
    """
    Build the human-facing preview URL that the QR code encodes.
    Adds ?tx=<transaction_id> so the Verifier can look up attendees, etc. from DB.
    """
    clean = {k: to_jsonable(v) for k, v in row.items()}

    # NOTE: attendees intentionally not in QR payload; keep if needed.
    payload = build_qr_payload(clean, event_name=event_name)
    base_url = encode_qr_url(payload)

    txid = (row.get("transaction_id") or "").strip()
    # Always carry tx=<transaction_id> for verifier DB lookup
    return _add_query_params(base_url, {"tx": txid})


def regenerate_and_upload(row: dict, *, event_name: str) -> tuple[str, str, bytes, str | None]:
    """
    Generate a QR image for this row, upload to S3, and cache bytes for immediate emailing.

    Returns:
        (s3_url, filename, bytes, old_key_if_any)
    """
    safe_name = _safe_name(row.get("username"))
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{row.get('transaction_id')}_{safe_name}_{ts}.png"
    key = f"{S3_PREFIX}{filename}"

    old_fname = (row.get("qr_code_filename") or "").strip()
    old_key = f"{S3_PREFIX}{old_fname}" if old_fname else None

    # Build encoded URL (now includes ?tx=transaction_id)
    url = build_preview_url(row, event_name)

    # Create local PNG
    local_path = generate_qr_image(url, filename, local_folder="qr")
    with open(local_path, "rb") as f:
        data = f.read()

    # Cache bytes in-session for immediate email send
    put_qr_bytes(row["transaction_id"], data)

    # Upload to S3
    s3_url = upload_png(local_path, key)

    # Best-effort local cleanup
    try:
        os.remove(local_path)
    except Exception:
        pass

    return s3_url, filename, data, old_key
