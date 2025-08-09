import streamlit as st
import pandas as pd
import datetime, re
from pathlib import Path
import os

from dotenv import load_dotenv

# --- Load env (from this page's folder) ---
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

import streamlit_authenticator as stauth
from sqlalchemy import text
from utils.styling import inject_global_styles
from utils.db import get_engine
from utils.json_utils import to_jsonable

from utils.qr_s3_utils import (
    build_qr_payload, encode_qr_url, generate_qr_image, upload_to_s3
)

engine = get_engine()

# --- Grab credentials ---
admin_username = os.getenv("ADMIN_USERNAME")
admin_name = os.getenv("ADMIN_NAME")
admin_password = os.getenv("ADMIN_PASSWORD")

verifier_username = os.getenv("VERIFIER_USERNAME")
verifier_name = os.getenv("VERIFIER_NAME")
verifier_password = os.getenv("VERIFIER_PASSWORD")

# --- Safety check for login credentials ---
required_vars = {
    "ADMIN_USERNAME": admin_username,
    "ADMIN_NAME": admin_name,
    "ADMIN_PASSWORD": admin_password,
    "VERIFIER_USERNAME": verifier_username,
    "VERIFIER_NAME": verifier_name,
    "VERIFIER_PASSWORD": verifier_password
}
missing = [k for k, v in required_vars.items() if not v]
if missing:
    st.error(f"❌ Missing the following .env values: {', '.join(missing)}")
    st.stop()

# --- Page config FIRST ---
st.set_page_config(page_title="Admin Panel", layout="wide")

# --- Global styles ---
inject_global_styles()

st.title("🔐 Admin Panel")

# --- Login guard  ---
if "authenticated" not in st.session_state or not st.session_state.authenticated:
    st.error("Please log in to access this page.")
    st.stop()

# ===========================================
# 1) UPLOAD EXCEL -> SAVE TO DB (dedup)
# ===========================================
st.markdown("""
<div style="background-color:#800000; padding:0.75rem 1rem; border-radius:8px; margin-bottom:1rem">
  <h3 style="color:#FFFBEA; margin:0;">📄 Upload Attendee Excel</h3>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Choose .xlsx file", type=["xlsx"])

if uploaded_file:
    df_upload = pd.read_excel(uploaded_file)
    # normalize column names
    df_upload.columns = [c.strip().lower().replace(" ", "_") for c in df_upload.columns]

    # --- Map header variants -> number_of_attendees (canonical) ---
    attendee_aliases = [
        "number_of_attendees", "no_of_attendees", "number_attendees",
        "attendees", "num_attendees", "num_of_attendees", "attendee_count"
    ]
    for alias in attendee_aliases:
        if alias in df_upload.columns and "number_of_attendees" not in df_upload.columns:
            df_upload.rename(columns={alias: "number_of_attendees"}, inplace=True)

    # --- Defaults for system columns ---
    defaults = {
        "qr_generated": False,
        "qr_sent": False,
        "number_of_attendees": 1 if "number_of_attendees" not in df_upload.columns else None,
        "number_checked_in": 0,
        "qr_reissued_yn": False,
        "qr_code_filename": "",
        "qr_generated_at": None,
        "qr_sent_at": None,
        "last_updated_at": datetime.datetime.now(),
        "created_at": datetime.datetime.now(),
    }
    for col, val in defaults.items():
        if val is None:
            continue
        if col not in df_upload.columns:
            df_upload[col] = val

    # --- Type coercions ---
    for c in ["membership_paid", "early_bird_applied", "qr_generated", "qr_sent", "qr_reissued_yn"]:
        if c in df_upload.columns:
            df_upload[c] = df_upload[c].astype(bool)

    if "amount" in df_upload.columns:
        df_upload["amount"] = pd.to_numeric(df_upload["amount"], errors="coerce")

    if "payment_date" in df_upload.columns:
        df_upload["payment_date"] = pd.to_datetime(df_upload["payment_date"], errors="coerce")

    if "number_of_attendees" in df_upload.columns:
        df_upload["number_of_attendees"] = (
            pd.to_numeric(df_upload["number_of_attendees"], errors="coerce")
            .fillna(1).clip(lower=0).astype(int)
        )

    # normalize a few text fields
    for c in ["transaction_id", "username", "email", "phone", "address", "paid_for", "remarks"]:
        if c in df_upload.columns:
            df_upload[c] = df_upload[c].astype(str)

    # --- Write only NEW rows (by transaction_id) ---
    with engine.connect() as conn:
        existing = pd.read_sql("SELECT transaction_id FROM event_payment", conn)
        existing_ids = set(existing["transaction_id"].astype(str).tolist()) if not existing.empty else set()

    df_upload["transaction_id"] = df_upload["transaction_id"].astype(str)
    df_new = df_upload[~df_upload["transaction_id"].isin(existing_ids)]

    if not df_new.empty:
        df_new.to_sql("event_payment", engine, if_exists="append", index=False, method="multi")
        st.success(f"✅ {len(df_new)} new row(s) saved to the database.")
    else:
        st.info("ℹ️ No new rows to save (all transaction_ids already exist).")

# ===========================================
# 2) FETCH PENDING -> TABLE + GENERATE QRs
# ===========================================
st.markdown("""
<div style="background-color:#800000; padding:0.75rem 1rem; border-radius:8px; margin: 1rem 0;">
  <h3 style="color:#FFFBEA; margin:0;">🧾 Pending Records (QR not yet generated)</h3>
</div>
""", unsafe_allow_html=True)

# fetch pending records
with engine.connect() as conn:
    df = pd.read_sql("SELECT * FROM event_payment WHERE qr_generated = FALSE", conn)

# coerce attendees column so the editor stepper works and we can edit
if "number_of_attendees" in df.columns:
    df["number_of_attendees"] = (
        pd.to_numeric(df["number_of_attendees"], errors="coerce")
        .fillna(1).clip(lower=0).astype(int)
    )

# search by name
search_term = st.text_input("🔍 Search by Name", "").strip().lower()
if search_term and not df.empty:
    df = df[df["username"].fillna("").str.lower().str.contains(search_term)]

if df.empty:
    st.success("✅ No pending records to generate QR codes.")
    st.stop()

# add selection column for editor
if "Select" not in df.columns:
    df.insert(0, "Select", False)

# --- TABLE: number_of_attendees is editable ---
edited_df = st.data_editor(
    df[[
        "Select",
        "username",
        "email",          # editable
        "phone",
        "transaction_id",
        "amount",
        "payment_date",
        "paid_for",       # editable
        "membership_paid",
        "early_bird_applied",
        "number_of_attendees"  # ✅ editable
    ]],
    column_config={
        "Select": st.column_config.CheckboxColumn("Select"),
        "username": "Name",
        "email": st.column_config.TextColumn("Email"),
        "phone": "Phone",
        "transaction_id": "Txn ID",
        "amount": st.column_config.NumberColumn("Amount ($)", format="$%.2f"),
        "payment_date": st.column_config.DateColumn("Payment Date"),
        "paid_for": st.column_config.TextColumn("Paid For"),
        "membership_paid": st.column_config.CheckboxColumn("Membership"),
        "early_bird_applied": st.column_config.CheckboxColumn("Early Bird"),
        "number_of_attendees": st.column_config.NumberColumn(
            "Number of Attendees",
            min_value=0, step=1
        ),
    },
    use_container_width=True,
    num_rows="dynamic",
    # Do NOT disable number_of_attendees so it's editable
    disabled=[
        "username", "phone", "transaction_id",
        "amount", "payment_date",
        "membership_paid", "early_bird_applied"
    ]
)

# === Generate QR Codes Button ===
if st.button("🎯 Generate QR Codes for Selected"):
    selected = edited_df[edited_df["Select"] == True]
    if selected.empty:
        st.warning("⚠️ No rows selected.")
    else:
        event_name = "Onam Ponnonam"  # TODO: make configurable if needed
        successes, failures = 0, 0

        with engine.begin() as conn:  # transaction
            for _, row in selected.iterrows():
                try:
                    # basic email validation (allow empty to pass)
                    email_val = str(row.get("email", "")).strip()
                    if email_val and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_val):
                        st.warning(f"⚠️ Skipping txn {row.get('transaction_id')}: invalid email '{email_val}'")
                        failures += 1
                        continue

                    # canonical attendees from edited table
                    num_attendees = int(pd.to_numeric(row.get("number_of_attendees"), errors="coerce") or 0)
                    if num_attendees < 0:
                        num_attendees = 0

                    # Build payload + URL (force canonical value in payload)
                    row_clean = {k: to_jsonable(v) for k, v in row.items()}
                    row_clean["number_of_attendees"] = num_attendees
                    payload = build_qr_payload(row_clean, event_name)  # includes number_of_attendees
                    url = encode_qr_url(payload)

                    txn_id = str(row["transaction_id"])
                    safe_name = re.sub(r"[^A-Za-z0-9]+", "", str(row["username"]))
                    filename = f"{txn_id}_{safe_name}.png"

                    local_path = generate_qr_image(url, filename, local_folder="qr")
                    s3_key = f"qrcodes/{filename}"
                    s3_url = upload_to_s3(local_path, s3_key)
                    if not s3_url:
                        st.warning(f"No S3 URL returned for {txn_id}; storing NULL")
                        s3_url = None

                    now = datetime.datetime.now()

                    # Persist edited email/paid_for/attendees into DB alongside QR metadata
                    conn.execute(
                        text("""
                            UPDATE event_payment
                            SET
                                email = :email,
                                paid_for = :paid_for,
                                number_of_attendees = :number_of_attendees,
                                qr_generated = TRUE,
                                qr_generated_at = :now,
                                qr_code_filename = :filename,
                                qr_s3_url = :s3_url,
                                last_updated_at = :now
                            WHERE transaction_id = :txn
                        """),
                        {
                            "email": email_val,
                            "paid_for": str(row.get("paid_for", "")).strip(),
                            "number_of_attendees": num_attendees,
                            "now": now,
                            "filename": filename,
                            "s3_url": s3_url,
                            "txn": txn_id,
                        }
                    )

                    successes += 1
                except Exception as e:
                    failures += 1
                    st.error(f"❌ Failed for txn {row.get('transaction_id')}: {e}")

        if successes:
            st.success(f"✅ Generated & uploaded {successes} QR code(s).")
        if st.button("🔄 Refresh Table"):
            st.rerun()
        if failures:
            st.warning(f"⚠️ {failures} record(s) failed. Check the errors above.)")
