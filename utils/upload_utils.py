# utils/upload_utils.py
from __future__ import annotations

import re
import datetime as dt
from typing import List, Tuple, Dict, Optional
from zoneinfo import ZoneInfo

import pandas as pd

# Pull everything from central config (no env reads here)
try:
    from config import (
        UPLOAD_COLUMN_ALIASES,
        UPLOAD_REQUIRED_COLS,
        UPLOAD_ALLOWED_COLS,
        UPLOAD_DEFAULTS,
        UPLOAD_EMAIL_REGEX,
        APP_TZ,
    )
except Exception:
    # Safe fallbacks so this module is importable during early refactors
    UPLOAD_COLUMN_ALIASES: Dict[str, str] = {
        "number_of_attendees": "number_of_attendees",
        "no_of_attendees": "number_of_attendees",
        "number_attendees": "number_of_attendees",
        "attendees": "number_of_attendees",
        "num_attendees": "number_of_attendees",
        "num_of_attendees": "number_of_attendees",
        "attendee_count": "number_of_attendees",
    }
    # phone removed from required
    UPLOAD_REQUIRED_COLS: List[str] = [
        "transaction_id", "username", "email", "amount", "paid_for"
    ]
    UPLOAD_ALLOWED_COLS: List[str] = [
        "transaction_id", "username", "email", "phone", "address",
        "membership_paid", "early_bird_applied", "payment_date", "amount", "paid_for", "remarks",
        "qr_generated", "qr_sent", "number_checked_in", "qr_reissued_yn",
        "qr_code_filename", "qr_generated_at", "qr_sent_at",
        "number_of_attendees", "created_at", "last_updated_at",
    ]
    UPLOAD_DEFAULTS: Dict[str, object] = {
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
        # changed default attendees to 0
        "number_of_attendees": 0,
        "remarks": "",
    }
    UPLOAD_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    APP_TZ = "UTC"

TZ = ZoneInfo(APP_TZ)


def _now_tz() -> dt.datetime:
    return dt.datetime.now(tz=TZ)


def _canon_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    for c in list(df.columns):
        if c in UPLOAD_COLUMN_ALIASES and UPLOAD_COLUMN_ALIASES[c] not in df.columns:
            df = df.rename(columns={c: UPLOAD_COLUMN_ALIASES[c]})
    return df


def normalize_upload_df(df_raw: pd.DataFrame) -> pd.DataFrame:
    df = _canon_cols(df_raw)

    # Text columns
    text_cols = ["transaction_id", "username", "email", "phone", "address", "paid_for", "remarks"]
    for c in text_cols:
        if c not in df.columns:
            df[c] = UPLOAD_DEFAULTS.get(c, "")
        df[c] = df[c].astype(str).fillna("").str.strip()

    # Booleans
    for c in ["membership_paid", "early_bird_applied", "qr_generated", "qr_sent", "qr_reissued_yn"]:
        if c not in df.columns:
            df[c] = bool(UPLOAD_DEFAULTS.get(c, False))
        else:
            df[c] = df[c].astype(bool)

    # Numerics
    if "amount" not in df.columns:
        df["amount"] = UPLOAD_DEFAULTS.get("amount", 0.0)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

    # Dates
    if "payment_date" not in df.columns:
        df["payment_date"] = pd.NaT
    else:
        df["payment_date"] = pd.to_datetime(df["payment_date"], errors="coerce", utc=False)

    # Attendees
    if "number_of_attendees" not in df.columns:
        df["number_of_attendees"] = UPLOAD_DEFAULTS.get("number_of_attendees", 0)
    df["number_of_attendees"] = (
        pd.to_numeric(df["number_of_attendees"], errors="coerce")
        .fillna(UPLOAD_DEFAULTS.get("number_of_attendees", 1))
        .clip(lower=0)
        .astype(int)
    )

    # Meta timestamps
    now = _now_tz()
    if "created_at" not in df.columns:
        df["created_at"] = now
    if "last_updated_at" not in df.columns:
        df["last_updated_at"] = now

    for c, v in {
        "number_checked_in": UPLOAD_DEFAULTS.get("number_checked_in", 0),
        "qr_code_filename": UPLOAD_DEFAULTS.get("qr_code_filename", ""),
        "qr_generated_at": UPLOAD_DEFAULTS.get("qr_generated_at", None),
        "qr_sent_at": UPLOAD_DEFAULTS.get("qr_sent_at", None),
    }.items():
        if c not in df.columns:
            df[c] = v

    df["transaction_id"] = df["transaction_id"].astype(str).str.strip()
    return df


def validate_rows(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    errors: List[str] = []
    missing_required = [c for c in UPLOAD_REQUIRED_COLS if c not in df.columns]
    if missing_required:
        errors.append(f"Missing required column(s): {', '.join(missing_required)}")
        return df.iloc[0:0].copy(), errors

    valid_mask = pd.Series(True, index=df.index)

    # transaction_id required
    empty_txn = df["transaction_id"].astype(str).str.strip() == ""
    if empty_txn.any():
        errors.append(f"{empty_txn.sum()} row(s) missing transaction_id")
        valid_mask &= ~empty_txn

    # username required
    empty_name = df["username"].astype(str).str.strip() == ""
    if empty_name.any():
        errors.append(f"{empty_name.sum()} row(s) missing username")
        valid_mask &= ~empty_name

    # amount non-negative
    bad_amount = pd.to_numeric(df["amount"], errors="coerce").fillna(-1) < 0
    if bad_amount.any():
        errors.append(f"{bad_amount.sum()} row(s) negative amount")
        valid_mask &= ~bad_amount

    # email required + format
    empty_email = df["email"].astype(str).str.strip() == ""
    if empty_email.any():
        errors.append(f"{empty_email.sum()} row(s) missing email")
        valid_mask &= ~empty_email
    invalid_email_mask = ~df["email"].astype(str).str.match(UPLOAD_EMAIL_REGEX, na=False)
    invalid_email_mask &= ~empty_email
    if invalid_email_mask.any():
        errors.append(f"{invalid_email_mask.sum()} row(s) have invalid email format")
        valid_mask &= ~invalid_email_mask

    # phone optional — no validation

    # paid_for required
    empty_paid_for = df["paid_for"].astype(str).str.strip() == ""
    if empty_paid_for.any():
        errors.append(f"{empty_paid_for.sum()} row(s) missing paid_for")
        valid_mask &= ~empty_paid_for

    # attendees non-negative
    bad_att = pd.to_numeric(df["number_of_attendees"], errors="coerce").fillna(-1) < 0
    if bad_att.any():
        errors.append(f"{bad_att.sum()} row(s) negative attendee count")
        valid_mask &= ~bad_att

    return df.loc[valid_mask].copy(), errors


def coerce_schema(df: pd.DataFrame, allowed_cols: Optional[List[str]] = None) -> pd.DataFrame:
    df = df.copy()
    allowed = allowed_cols or UPLOAD_ALLOWED_COLS
    keep = [c for c in df.columns if c in allowed]
    df = df[keep]

    for c in allowed:
        if c not in df.columns:
            if c in {"created_at", "last_updated_at"}:
                df[c] = _now_tz()
            else:
                df[c] = UPLOAD_DEFAULTS.get(c, None)

    return df
