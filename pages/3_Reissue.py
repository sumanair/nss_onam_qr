# pages/3_Reissuance.py
import os
import re
import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import text
from utils.email_utils import send_email_with_qr_url  # URL-only email sender

import boto3  # for deleting old S3 object

from utils.db import get_engine
from utils.styling import inject_global_styles
from utils.json_utils import to_jsonable
from utils.qr_s3_utils import (
    build_qr_payload, encode_qr_url, generate_qr_image, upload_to_s3
)

import unicodedata, html

# ---- helpers ----------------------------------------------------------------
def _clean(s: str) -> str:
    if s is None:
        return ""
    s = str(s).replace("\xa0", " ")  # kill NBSP
    return unicodedata.normalize("NFC", s)

def _clean_email(e: str) -> str:
    e = _clean(e)
    e = re.sub(r"\s+", "", e)  # remove ALL spaces incl. NBSP
    return e

def _truncate_middle(s: str, max_len: int = 36) -> str:
    s = str(s or "")
    if len(s) <= max_len:
        return s
    keep = max_len - 3
    left = keep // 2
    right = keep - left
    return f"{s[:left]}...{s[-right:]}"

def _time_ago(dt) -> str:
    if not dt:
        return ""
    try:
        dt = pd.to_datetime(dt)
    except Exception:
        return ""
    now = pd.Timestamp.now(tz=getattr(dt, "tz", None))
    delta = now - pd.Timestamp(dt)
    secs = int(delta.total_seconds())
    if secs < 60: return f"{secs}s ago"
    mins = secs // 60
    if mins < 60: return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24: return f"{hrs}h ago"
    days = hrs // 24
    return f"{days}d ago"

def _coerce_attendees(v, default=1) -> int:
    n = int(pd.to_numeric(v, errors="coerce") or default)
    return max(0, n)

# ── Config ────────────────────────────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

st.set_page_config(page_title="QR Re‑issuance", layout="wide")
inject_global_styles()

engine = get_engine()
EVENT_NAME = "Onam Ponnonam"              # TODO: make configurable
S3_BUCKET  = os.getenv("BUCKET_NAME", "")  # used for delete (regen)
S3_PREFIX  = "qrcodes/"                    # keep in sync with upload_to_s3

# ── Auth guard ────────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state or not st.session_state.authenticated:
    st.error("Please log in to access this page.")
    st.stop()

st.title("♻️ QR Re‑issuance")

# ── Section header ────────────────────────────────────────────────────────────
st.markdown("""
<div style="background:#004b6b; padding:0.75rem 1rem; border-radius:8px; margin: 0 0 1rem 0;">
  <h3 style="color:#ECF7FF; margin:0;">🔁 Sent But Not Re‑issued</h3>
  <p style="color:#CFEAF7; margin:0.25rem 0 0 0;">
    Records where an email was already sent but need a re‑issue (e.g., attendee disputes).<br/>
    Criterion: <code>qr_sent = TRUE</code> and <code>qr_reissued_yn = FALSE</code>.
  </p>
</div>
""", unsafe_allow_html=True)

# ── Fetch re-issuance candidates ──────────────────────────────────────────────
with engine.connect() as conn:
    df_list = pd.read_sql(
        text("""
            SELECT
                transaction_id, username, email, qr_code_filename, qr_s3_url,
                paid_for, remarks, address, phone,
                membership_paid, early_bird_applied, amount, payment_date,
                number_of_attendees, number_checked_in,
                qr_sent, qr_reissued_yn,
                last_updated_at, qr_generated_at, qr_sent_at
            FROM event_payment
            WHERE qr_sent = TRUE
              AND COALESCE(qr_reissued_yn, FALSE) = FALSE
            ORDER BY last_updated_at DESC NULLS LAST, qr_sent_at DESC NULLS LAST
        """),
        conn
    )

if df_list.empty:
    st.success("✅ No records pending re‑issuance.")
    st.stop()

# ── Selector controls (search / sort / pagination) ────────────────────────────
st.markdown("### Select a record to review & re‑issue")

col_a, col_b, col_c = st.columns([2, 1, 1])
with col_a:
    search = st.text_input("🔎 Search (name/email/file)", "").strip().lower()
with col_b:
    sort_by = st.selectbox("Sort by", ["Last updated", "Name A→Z", "Email A→Z"])
with col_c:
    per_page = st.selectbox("Per page", [10, 25, 50], index=0)

dfx = df_list.copy()
dfx["display_name"]  = dfx["username"].fillna("(no name)")
dfx["display_email"] = dfx["email"].fillna("(no email)")
dfx["display_file"]  = dfx["qr_code_filename"].fillna("(no file)").map(_truncate_middle)
dfx["age"] = [
    _time_ago(r["last_updated_at"] or r["qr_sent_at"] or r["qr_generated_at"])
    for _, r in dfx.iterrows()
]

if search:
    mask = (
        dfx["display_name"].str.lower().str.contains(search) |
        dfx["display_email"].str.lower().str.contains(search) |
        dfx["qr_code_filename"].fillna("").str.lower().str_contains(search)
        if hasattr(pd.Series.str, "contains") else
        dfx["qr_code_filename"].fillna("").str.lower().str.contains(search)
    )
    dfx = dfx[mask]

if sort_by == "Last updated":
    dfx = dfx.sort_values(
        by=["last_updated_at", "qr_sent_at", "qr_generated_at"],
        ascending=[False, False, False],
        na_position="last"
    )
elif sort_by == "Name A→Z":
    dfx = dfx.sort_values(by=["display_name", "display_email"], ascending=[True, True])
else:  # Email A→Z
    dfx = dfx.sort_values(by=["display_email", "display_name"], ascending=[True, True])

total = len(dfx)
pages = max(1, (total + per_page - 1) // per_page)
page = st.number_input("Page", min_value=1, max_value=pages, value=1, step=1)
start = (page - 1) * per_page
end = start + per_page
dfp = dfx.iloc[start:end]

st.caption(f"Showing {len(dfp)}/{total} pending · Page {page}/{pages}")

def _label(row) -> str:
    line1 = f"**{row['display_name']}** · {row['display_email']}"
    line2 = f"{row['display_file']}  ·  _{row['age']}_"
    return f"{line1}\n{line2}"

options = dfp.index.tolist()
labels = [_label(row) for _, row in dfp.iterrows()]

if not options:
    st.info("No results on this page with the current filters.")
    st.stop()

selected_idx = st.radio(
    label="Select a record to review & re‑issue",
    options=options,
    format_func=lambda i: labels[options.index(i)],
    index=0,
    key="reissuance_selected_idx",
    label_visibility="collapsed",
)

# Use the original df_list to resolve the chosen transaction_id
selected_txn = str(df_list.loc[selected_idx, "transaction_id"])

# ── Re-load selected row from DB (fresh) ─────────────────────────────────────
with engine.connect() as conn:
    selected = conn.execute(
        text("SELECT * FROM event_payment WHERE transaction_id = :txn LIMIT 1"),
        {"txn": selected_txn}
    ).mappings().first()

if not selected:
    st.error("Could not re-load selected record from DB.")
    st.stop()

# ── Prefills ─────────────────────────────────────────────────────────────────
name_val   = str(selected.get("username") or "")
email_val  = str(selected.get("email") or "")
phone      = str(selected.get("phone") or "")
address    = str(selected.get("address") or "")
paid_for   = str(selected.get("paid_for") or "")
remarks    = str(selected.get("remarks") or "")
amount     = float(selected.get("amount") or 0.0)
membership = bool(selected.get("membership_paid") or False)
earlybird  = bool(selected.get("early_bird_applied") or False)
pay_date   = selected.get("payment_date")
if isinstance(pay_date, datetime.datetime):
    pay_date = pay_date.date()
num_attendees = _coerce_attendees(selected.get("number_of_attendees"), default=1)
num_checked_in = _coerce_attendees(selected.get("number_checked_in"), default=0)

# ── Layout: form (left) + QR preview (right) ─────────────────────────────────
left, right = st.columns([1, 1])

with left:
    st.markdown("#### Review / update details & Re‑issue")

    with st.form("reissue_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Name", value=name_val, disabled=True)
            email_in = st.text_input("Email", value=email_val)
            phone_in = st.text_input("Phone", value=phone)
        with c2:
            membership_in = st.checkbox("Membership Paid", value=membership)
            earlybird_in  = st.checkbox("Early Bird Applied", value=earlybird)
            st.date_input("Payment Date", value=pay_date or datetime.date.today(), disabled=True)
            st.number_input("Amount ($)", value=amount, step=0.01, min_value=0.0, disabled=True)

        address_in = st.text_input("Address", value=address)

        # Attendee counts row (editable attendees, read-only checked-in)
        a1, a2 = st.columns(2)
        with a1:
            number_of_attendees_in = st.number_input(
                "Number of Attendees",
                min_value=0, step=1, value=num_attendees
            )
        with a2:
            st.number_input(
                "Checked In (read-only)",
                min_value=0, step=1, value=num_checked_in, disabled=True
            )

        p1, p2 = st.columns([1, 2])
        with p1:
            paid_for_in = st.text_input("Paid For", value=paid_for)
        with p2:
            remarks_in = st.text_area("Remarks", value=remarks, height=80)

        save_btn = st.form_submit_button("💾 Save changes")

    if save_btn:
        if email_in and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_in):
            st.error("Invalid email.")
            st.stop()

        # coerce attendees to int, keep >= checked-in
        new_attendees = _coerce_attendees(number_of_attendees_in, default=num_attendees)
        if new_attendees < num_checked_in:
            st.warning("Number of Attendees cannot be less than already checked-in count. Keeping previous value.")
            new_attendees = num_attendees

        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE event_payment
                    SET email = :email,
                        paid_for = :paid_for,
                        remarks = :remarks,
                        phone = :phone,
                        address = :address,
                        membership_paid = :membership_paid,
                        early_bird_applied = :early_bird_applied,
                        number_of_attendees = :number_of_attendees,
                        last_updated_at = :now
                    WHERE transaction_id = :txn
                """),
                {
                    "email": email_in.strip(),
                    "paid_for": paid_for_in.strip(),
                    "remarks": remarks_in.strip(),
                    "phone": phone_in.strip(),
                    "address": address_in.strip(),
                    "membership_paid": bool(membership_in),
                    "early_bird_applied": bool(earlybird_in),
                    "number_of_attendees": int(new_attendees),
                    "now": datetime.datetime.now(),
                    "txn": selected_txn
                }
            )
        st.success("✅ Saved changes.")
        st.button("🔄 Refresh", on_click=lambda: st.rerun())

with right:
    st.markdown("#### Current QR")
    qr_url_from_db = selected.get("qr_s3_url")
    qr_filename    = selected.get("qr_code_filename") or ""
    attendees_display = _coerce_attendees(selected.get("number_of_attendees"), 1)

    if qr_url_from_db:
        st.caption(f"File: {qr_filename} · Attendees: {attendees_display}")
        st.image(qr_url_from_db, use_container_width=False)
    else:
        # Fallback preview without DB image; ensure attendees in payload
        row_clean = {k: to_jsonable(v) for k, v in dict(selected).items()}
        row_clean["number_of_attendees"] = attendees_display  # ✅ guarantee field
        payload = build_qr_payload(row_clean, event_name=EVENT_NAME)
        preview_url = encode_qr_url(payload)
        tmp_name = f"preview_{selected_txn}.png"
        local_path = generate_qr_image(preview_url, tmp_name, local_folder="qr_preview")
        st.warning("No S3 URL found; showing a temporary preview.")
        st.image(local_path, use_container_width=False)

# ── Actions: Regenerate (optional) & Re‑issue ────────────────────────────────
a1, a2, a3 = st.columns([1, 1, 2])

with a1:
    if st.button("♻️ Regenerate QR (optional)"):
        try:
            with engine.connect() as conn:
                fresh = conn.execute(
                    text("SELECT * FROM event_payment WHERE transaction_id = :txn"),
                    {"txn": selected_txn}
                ).mappings().first()

            if not fresh:
                st.error("Record vanished during regen.")
                st.stop()

            old_filename = (fresh.get("qr_code_filename") or "").strip()
            old_key = f"{S3_PREFIX}{old_filename}" if old_filename else None

            # Build new payload & QR (force canonical attendees)
            row_clean = {k: to_jsonable(v) for k, v in dict(fresh).items()}
            row_clean["number_of_attendees"] = _coerce_attendees(
                fresh.get("number_of_attendees"), 1
            )  # ✅ guarantee field
            payload = build_qr_payload(row_clean, event_name=EVENT_NAME)
            url = encode_qr_url(payload)

            safe_name = re.sub(r"[^A-Za-z0-9]+", "", str(fresh.get("username") or "unknown"))
            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            new_filename = f"{fresh.get('transaction_id')}_{safe_name}_{ts}.png"

            local_path = generate_qr_image(url, new_filename, local_folder="qr")
            new_key = f"{S3_PREFIX}{new_filename}"
            new_s3_url = upload_to_s3(local_path, new_key)

            now = datetime.datetime.now()
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE event_payment
                        SET qr_generated = TRUE,
                            qr_generated_at = :now,
                            qr_code_filename = :fname,
                            qr_s3_url = :s3,
                            last_updated_at = :now,
                            qr_sent = FALSE,          -- reset; you will re‑issue email next
                            qr_sent_at = NULL
                        WHERE transaction_id = :txn
                    """),
                    {"now": now, "fname": new_filename, "s3": new_s3_url, "txn": selected_txn}
                )

            # Best-effort delete of old S3 object (if different)
            try:
                if S3_BUCKET and old_key and old_key != new_key:
                    s3 = boto3.client("s3")
                    s3.delete_object(Bucket=S3_BUCKET, Key=old_key)
            except Exception as del_err:
                st.info(f"ℹ️ Old QR not deleted (will be cleaned later): {del_err}")

            st.success("✅ QR regenerated & DB updated. You can now Re‑issue the email.")
            st.button("🔄 Refresh", on_click=lambda: st.rerun())
        except Exception as e:
            st.error(f"Regen failed: {e}")

with a2:
    if st.button("📩 Re‑issue Email (mark as re‑issued)"):
        try:
            with engine.connect() as conn:
                rec = conn.execute(
                    text("""
                        SELECT username, email, qr_s3_url, number_of_attendees
                        FROM event_payment
                        WHERE transaction_id = :txn
                        LIMIT 1
                    """),
                    {"txn": selected_txn}
                ).mappings().first()

            if not rec:
                st.error("Record not found.")
                st.stop()

            recipient = _clean_email(rec.get("email") or "")
            username  = _clean(rec.get("username") or "Attendee")
            s3_url    = (rec.get("qr_s3_url") or "").strip()

            if not recipient or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", recipient):
                st.error(f"Invalid or missing email: {recipient or '(empty)'}")
                st.stop()
            if not s3_url.startswith(("http://", "https://")):
                st.error("No valid QR URL found for this record. Please regenerate first.")
                st.stop()

            subject = _clean(f"Your QR Code - {EVENT_NAME}")  # ASCII hyphen
            body = f"""
                <p>Hi {html.escape(username)},</p>
                <p>As requested, here is your QR code for <b>{html.escape(EVENT_NAME)}</b>.</p>
                <p><a href="{html.escape(s3_url)}" target="_blank" rel="noopener">View QR Code</a></p>
                <p>If anything still looks off, reply to this email.</p>
                <p>Thanks!<br/>NSSNT Team</p>
            """
            send_email_with_qr_url(
                recipient=recipient,
                subject=subject,
                body_html=_clean(body),
            )

            now = datetime.datetime.now()
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE event_payment
                        SET
                            qr_sent = TRUE,                -- sent again
                            qr_sent_at = :now,
                            qr_reissued_yn = TRUE,         -- ✅ mark as re‑issued
                            last_updated_at = :now
                        WHERE transaction_id = :txn
                    """),
                    {"now": now, "txn": selected_txn}
                )

            st.success(f"✅ Re‑issued to {recipient} and marked as re‑issued.")
            st.rerun()

        except Exception as e:
            st.error(f"Re‑issue failed: {e}")

with a3:
    st.info("Pick a record, review/edit, optionally regenerate, then Re‑issue. The number of attendees is now saved to DB and embedded in regenerated QR.")
