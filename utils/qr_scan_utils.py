# utils/qr_scan_utils.py
import base64
import json
import re
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs, unquote

# Keys that may carry the transaction id (case-insensitive)
HIDE_KEYS_LOWER = {"transaction_id", "txn", "txid", "transactionid"}

def _b64_try(s: str) -> Optional[str]:
    """Base64/URL-safe base64 decode; return None on failure."""
    s = (s or "").strip()
    if not s:
        return None
    s2 = s.replace("-", "+").replace("_", "/")
    pad = "=" * ((4 - len(s2) % 4) % 4)
    try:
        return base64.b64decode(s2 + pad).decode("utf-8", errors="ignore")
    except Exception:
        return None

def _find_txn_in_obj(obj: Any) -> Optional[str]:
    """Recursively search dict/list for a transaction id by key name."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).strip().lower() in HIDE_KEYS_LOWER and v:
                return str(v)
        # search nested values
        for v in obj.values():
            sub = _find_txn_in_obj(v)
            if sub:
                return sub
    elif isinstance(obj, list):
        for v in obj:
            sub = _find_txn_in_obj(v)
            if sub:
                return sub
    return None

def _extract_txn_from_url(url: str) -> Optional[str]:
    """Extract a transaction id from URL query (direct or base64-embedded JSON)."""
    try:
        u = urlparse(url)
    except Exception:
        return None

    q = parse_qs(u.query or "")

    # direct query param
    for k, vals in q.items():
        if k.lower() in HIDE_KEYS_LOWER and vals:
            return vals[0]

    # base64/json under common payload params
    for k in ("data", "payload", "qr", "p"):
        if k in q and q[k]:
            raw = unquote(q[k][0])
            decoded = _b64_try(raw) or raw  # try b64 first; else assume plain JSON/hex already
            try:
                return _find_txn_in_obj(json.loads(decoded))
            except Exception:
                continue

    # last path segment as base64/json (optional)
    last = (u.path or "").split("/")[-1]
    if last:
        decoded = _b64_try(last)
        if decoded:
            try:
                return _find_txn_in_obj(json.loads(decoded))
            except Exception:
                pass

    return None

def parse_scanned_text_to_txn(text: str) -> Optional[str]:
    """
    Accept raw QR text and try to extract a transaction id.
    - JSON (top-level or nested in 'data')
    - URL with ?data=/payload/qr/p params (possibly base64url)
    - raw base64-encoded JSON
    - plain alphanumeric token
    """
    if not text:
        return None
    s = text.strip()

    # JSON string
    if s.startswith("{") and s.endswith("}"):
        try:
            return _find_txn_in_obj(json.loads(s))
        except Exception:
            return None

    # URL form
    if s.startswith(("http://", "https://")):
        return _extract_txn_from_url(s)

    # raw base64-encoded JSON
    decoded = _b64_try(s)
    if decoded:
        try:
            return _find_txn_in_obj(json.loads(decoded))
        except Exception:
            pass

    # fallback: plain token
    if re.fullmatch(r"[A-Za-z0-9\-_=]{6,}", s):
        return s

    return None
