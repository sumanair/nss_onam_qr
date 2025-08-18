# ui/utils/qr_s3_utils.py
from __future__ import annotations

import os
import json
import base64
from pathlib import Path
from typing import Dict, Any
from urllib.parse import quote

import qrcode
from qrcode.constants import ERROR_CORRECT_L

from services.aws_session import get_session

# All knobs come from config (no env reads, no magic strings)
from config import (
    S3_BUCKET,
    S3_PREFIX,
    QR_ROOT_PATH,
    S3_QR_LOCAL_DIR,
    S3_QR_ACL,
    S3_QR_EXTRA_ARGS,
    S3_USE_PRESIGNED,
    S3_PRESIGN_EXPIRES,
    QR_IMAGE_OPTS,
)

# ──────────────────────────────────────────────────────────────
# Lazy S3 client (avoid side effects at import time)
# ──────────────────────────────────────────────────────────────
_s3_client = None
def _s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = get_session().client("s3")
    return _s3_client


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def _to_jsonable(val: Any) -> Any:
    """Safely convert common non-JSON values (e.g., pandas.Timestamp) to strings."""
    try:
        # pandas.Timestamp or datetime: ISO string
        if hasattr(val, "isoformat"):
            return val.isoformat()
        # numpy scalar
        if hasattr(val, "item"):
            return val.item()
        return val
    except Exception:
        return str(val)


def _default_qr_filename(transaction_id: str) -> str:
    return f"{transaction_id}.png"


def _qr_image(url: str, path: Path) -> None:
    """Generate a QR image with config-driven options."""
    opts = {
        "version": QR_IMAGE_OPTS.get("version", None),
        "error_correction": QR_IMAGE_OPTS.get("error_correction", ERROR_CORRECT_L),
        "box_size": QR_IMAGE_OPTS.get("box_size", 10),
        "border": QR_IMAGE_OPTS.get("border", 4),
    }
    qr = qrcode.QRCode(
        version=opts["version"],
        error_correction=opts["error_correction"],
        box_size=opts["box_size"],
        border=opts["border"],
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image()
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))


def _public_https_url(bucket: str, key: str) -> str:
    # If you use a custom domain/CloudFront, expose a different formatter via config later.
    return f"https://{bucket}.s3.amazonaws.com/{key}"


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────
def build_qr_payload(row: Dict[str, Any], event_name: str) -> Dict[str, Any]:
    """Config-safe payload builder (no direct serialization here)."""
    return {
        "data": {
            "name": row.get("username"),
            "email": row.get("email"),
            "phone": row.get("phone"),
            "paid_for": row.get("paid_for"),
            "amount": row.get("amount"),
            "payment_date": _to_jsonable(row.get("payment_date")),
            "membership_paid": bool(row.get("membership_paid", False)),
            "early_bird_applied": bool(row.get("early_bird_applied", False)),
            "event": event_name,
            "transaction_id": row.get("transaction_id"),
        }
    }


def encode_qr_url(payload: Dict[str, Any]) -> str:
    """URL to your public viewer with base64url payload."""
    json_str = json.dumps(payload, default=_to_jsonable, separators=(",", ":"))
    b64 = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")
    #return f"{QR_ROOT_PATH}?data={quote(b64)}" #- for local run
    return f"{QR_ROOT_PATH}&data={quote(b64)}" # - when running on server


def generate_qr_image(url: str, filename: str, local_folder: str | Path | None = None) -> str:
    folder = Path(local_folder or S3_QR_LOCAL_DIR)
    out_path = folder / filename
    _qr_image(url, out_path)
    return str(out_path)


def upload_to_s3(filepath: str, s3_key: str, delete_local: bool = True) -> str:
    """Uploads with config-driven headers/ACL; returns public or presigned URL per config."""
    extra_args = {
        "ContentType": "image/png",
        # caller-supplied defaults (CacheControl, ContentDisposition, etc.)
        **(S3_QR_EXTRA_ARGS or {}),
    }
    if S3_QR_ACL:
        extra_args["ACL"] = S3_QR_ACL

    _s3().upload_file(filepath, S3_BUCKET, s3_key, ExtraArgs=extra_args)

    if delete_local:
        try:
            os.remove(filepath)
        except OSError as e:
            print(f"⚠️ Could not delete {filepath}: {e}")

    if S3_USE_PRESIGNED:
        return _s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": s3_key},
            ExpiresIn=S3_PRESIGN_EXPIRES,
        )
    else:
        return _public_https_url(S3_BUCKET, s3_key)


def generate_qr_key(transaction_id: str, event_slug: str | None = None) -> str:
    """
    Deterministic S3 key; event_slug lets you group per event like:
    f"{S3_PREFIX}{event_slug}/{txn}.png"
    """
    fname = _default_qr_filename(transaction_id)
    prefix = S3_PREFIX.rstrip("/")
    if event_slug:
        return f"{prefix}/{event_slug}/{fname}"
    return f"{prefix}/{fname}"


def generate_and_upload_qr(row: Dict[str, Any], event_name: str, event_slug: str | None = None) -> str:
    """
    Full pipeline: build payload → encode url → render PNG → upload.
    Returns a URL (public or presigned) per config.
    """
    payload = build_qr_payload(row, event_name)
    url = encode_qr_url(payload)
    filename = _default_qr_filename(str(row["transaction_id"]))
    local_path = generate_qr_image(url, filename, local_folder=S3_QR_LOCAL_DIR)
    s3_key = generate_qr_key(str(row["transaction_id"]), event_slug=event_slug)
    return upload_to_s3(local_path, s3_key)
