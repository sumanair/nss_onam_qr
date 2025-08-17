# Admin.py  — Pending -> Generate QRs (Early Bird + Pagination + no index + wider table)

import re
import math
import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import text

# ── Page config FIRST ─────────────────────────────────────────
st.set_page_config(page_title="Admin Panel", layout="wide")
st.markdown("<div style='margin-bottom: 1.5rem;'></div>", unsafe_allow_html=True)


# ── Shared styling/auth/services ──────────────────────────────
from utils.styling import inject_global_styles, inject_sidebar_styles
from utils.auth_sidebar import render_auth_in_sidebar, require_auth
from utils.db import get_engine
from utils.json_utils import to_jsonable

# Config + services (centralized)
from config import EVENT_NAME
from services.qr_service import regenerate_and_upload  # returns (s3_url, filename, qr_bytes, old_key)
from services.upload_service import ingest_excel

inject_global_styles()
inject_sidebar_styles()
render_auth_in_sidebar()   # shows login/logout in sidebar
require_auth()             # blocks page if not logged in

engine = get_engine()

# ── Make the main area & table wider ─────────────────────────
st.markdown("""
<style>
[data-testid="stAppViewContainer"] .main .block-container { 
  max-width: 95vw;
  padding-left: 1rem;
  padding-right: 1rem;
}
.block-container { max_width: 95vw; }
/* Data editor full width */
#editable-grid [data-testid="stDataFrame"], 
#editable-grid [data-testid="stDataFrame"] > div { width: 100% !important; }
/* Give the grid breathing room */
#editable-grid [data-testid="stDataFrame"] [role="table"],
#editable-grid [data-testid="stDataFrame"] table { min-width: 1400px; }
</style>
""", unsafe_allow_html=True)

# ── Title ─────────────────────────────────────────────────────
st.title(f"🔐 Admin Panel — {EVENT_NAME}")

# --- Upload Excel (collapsible, no preview, safe reset with versioned key) ---
if "uploader_nonce" not in st.session_state:
    st.session_state.uploader_nonce = 0

st.markdown("""
<style>
div.streamlit-expanderHeader p { font-weight: 700; }
div[data-testid="stExpander"] > details > summary {
  background: #80000010;
  border: 1px solid #FFD90055;
  border-radius: 10px;
  padding: .6rem .9rem;
}
</style>
""", unsafe_allow_html=True)

with st.expander("📄 Upload Attendee Excel (.xlsx)", expanded=False):
    st.caption("Headers are flexible—attendee count aliases like *num_attendees*, *attendees*, etc., are auto-mapped.")

    uploader_key = f"admin_excel_uploader_{st.session_state.uploader_nonce}"
    uploaded_file = st.file_uploader("Choose .xlsx file", type=["xlsx"], key=uploader_key)

    # Optional: template download (CSV)
    sample_df = pd.DataFrame([{
        "transaction_id": "ABC123",
        "username": "First Last",
        "email": "user@example.com",
        "phone": "123-456-7890",
        "address": "Address line",
        "membership_paid": True,
        "early_bird_applied": False,
        "payment_date": datetime.date.today(),
        "amount": 100.00,
        "paid_for": "Family of 2",
        "remarks": "",
        "number_of_attendees": 2
    }])
    st.download_button(
        "Download sample template",
        data=sample_df.to_csv(index=False).encode("utf-8"),
        file_name="event_payment_template.csv",
        mime="text/csv",
        help="CSV is fine; uploader also accepts .xlsx",
        use_container_width=False,
    )

    if uploaded_file is not None:
        summary = ingest_excel(engine, uploaded_file, table="event_payment")

        msgs = []
        if summary.get("inserted"):
            msgs.append(f"✅ **{summary['inserted']}** new row(s) saved.")
        if summary.get("skipped_existing"):
            msgs.append(f"ℹ️ **{summary['skipped_existing']}** duplicate row(s) skipped.")
        if msgs:
            st.success("  \n".join(msgs))
        if summary.get("errors"):
            with st.expander("⚠️ Issues found"):
                for e in summary["errors"]:
                    st.write("• " + e)

        # Reset the uploader cleanly by bumping the nonce, then rerun
        if summary.get("inserted") or summary.get("skipped_existing") or summary.get("errors"):
            st.session_state.uploader_nonce += 1
            st.rerun()

# ===========================================
# FETCH PENDING -> TABLE + GENERATE QRs
# ===========================================
st.markdown("""
<div style="background-color:#800000; padding:0.75rem 1rem; border-radius:8px; margin: 1rem 0;">
  <h3 style="color:#FFFBEA; margin:0;">🧾 Pending Records (QR not yet generated)</h3>
</div>
""", unsafe_allow_html=True)

# fetch pending records
with engine.connect() as conn:
    df = pd.read_sql(
        "SELECT * FROM event_payment WHERE COALESCE(qr_generated, FALSE) = FALSE ORDER BY payment_date DESC NULLS LAST",
        conn,
    )

# coerce types for editor
if not df.empty and "number_of_attendees" in df.columns:
    df["number_of_attendees"] = (
        pd.to_numeric(df["number_of_attendees"], errors="coerce")
        .fillna(1).clip(lower=0).astype(int)
    )

for bcol in ["membership_paid", "early_bird_applied"]:
    if bcol in df.columns:
        df[bcol] = df[bcol].fillna(False).astype(bool)
    else:
        df[bcol] = False  # safety default if column missing

# --- Search (styled) ---------------------------------------------------------
st.markdown("""
<style>
div[data-testid="stTextInput"] label p { font-weight: 600; font-size: 1rem; }
div[data-testid="stTextInput"] input {
  background: #ffffff !important; border: 2px solid #F4D06F !important;
  border-radius: 10px !important; padding: 10px 14px !important;
  font-size: 1rem !important; color: #333 !important;
}
div[data-testid="stTextInput"] input:focus {
  outline: none !important; border-color: #F0B429 !important;
  box-shadow: 0 0 0 3px rgba(244,208,111,0.35) !important;
}
</style>
""", unsafe_allow_html=True)

search_term = st.text_input("🔎 Search by Name or Email", "", placeholder="Type a name or email…").strip().lower()

# Initialize pagination state
if "admin_page_size" not in st.session_state:
    st.session_state.admin_page_size = 25
if "admin_page" not in st.session_state:
    st.session_state.admin_page = 1
if "admin_last_search" not in st.session_state:
    st.session_state.admin_last_search = ""

# Reset page when search changes
if search_term != st.session_state.admin_last_search:
    st.session_state.admin_page = 1
    st.session_state.admin_last_search = search_term

# Apply search filter
if search_term and not df.empty:
    name_match = df["username"].fillna("").str.lower().str.contains(search_term)
    email_match = df["email"].fillna("").str.lower().str.contains(search_term)
    df = df[name_match | email_match]

if df.empty:
    st.success("✅ No pending records to generate QR codes.")
    st.stop()

# --- Pagination controls ------------------------------------------------------
top_l, top_c, top_r = st.columns([1, 2, 1], vertical_alignment="center")
with top_l:
    page_size = st.selectbox("Rows per page", [10, 25, 50, 100],
                             index=[10, 25, 50, 100].index(st.session_state.admin_page_size))
    if page_size != st.session_state.admin_page_size:
        st.session_state.admin_page_size = page_size
        st.session_state.admin_page = 1

total_rows = len(df)
total_pages = max(1, math.ceil(total_rows / st.session_state.admin_page_size))
current_page = min(max(1, st.session_state.admin_page), total_pages)

with top_c:
    st.markdown(
        f"<div style='text-align:center; font-weight:600;'>Page {current_page} / {total_pages} &nbsp;•&nbsp; {total_rows} rows</div>",
        unsafe_allow_html=True,
    )

with top_r:
    c1, c2 = st.columns(2)
    prev_clicked = c1.button("◀ Prev", disabled=(current_page <= 1))
    next_clicked = c2.button("Next ▶", disabled=(current_page >= total_pages))
    if prev_clicked:
        st.session_state.admin_page = max(1, current_page - 1); st.rerun()
    if next_clicked:
        st.session_state.admin_page = min(total_pages, current_page + 1); st.rerun()

# Slice the page
start = (current_page - 1) * st.session_state.admin_page_size
end = start + st.session_state.admin_page_size
page_index = df.index[start:end]
df_page = df.loc[page_index].copy()

# add selection column for editor (only on the page slice)
if "Select" not in df_page.columns:
    df_page.insert(0, "Select", False)

# --- External 'Select all (this page)' ---------------------------------------
select_all = st.checkbox(" Select all (this page)", value=False)
if select_all:
    df.loc[page_index, "Select"] = True
    df_page["Select"] = True

# --- Column order (Early Bird included) --------------------------------------
# --- Column order (Early Bird included) --------------------------------------
from pandas.api.types import is_bool_dtype, is_numeric_dtype, is_datetime64_any_dtype
import pandas as pd

COLS = [
    "Select", "username", "email", "phone",
    "paid_for", "membership_paid", "early_bird_applied",
    "number_of_attendees", "amount", "payment_date", "transaction_id"
]

missing_cols = [c for c in COLS if c not in df_page.columns]
if missing_cols:
    st.error(f"Missing expected columns: {missing_cols}")
    st.stop()

# 1) Convert common literal placeholders to NA (so we can blank them cleanly)
df_page = df_page.replace(r"^\s*(nan|NaN|None|null)\s*$", pd.NA, regex=True)

# 2) Column-wise normalization:
for col in COLS:
    if col not in df_page.columns:
        continue

    s = df_page[col]

    if is_bool_dtype(s):
        # Booleans: default to False
        df_page[col] = s.fillna(False).astype(bool)

    elif is_numeric_dtype(s) or is_datetime64_any_dtype(s):
        # Numbers/dates: keep dtype; NaN/NaT will render as blank in st.data_editor
        df_page[col] = s

    else:
        # Text-like: ensure string dtype and blank out missing
        df_page[col] = s.astype("string").fillna("")

# (optional) phone column is often mis-typed; force text
if "phone" in df_page.columns:
    df_page["phone"] = df_page["phone"].astype("string").fillna("")

# --- Legend ------------------------------------------------------------------
st.markdown("""
<div style="display:flex; gap:12px; align-items:center; margin:6px 0 2px 0;">
  <div style="width:14px; height:14px; background:#FFF5E5; border:1px solid #FFD8A8; border-radius:3px;"></div>
  <div style="font-size:0.9rem;">Editable fields <span style="opacity:0.7;">(✏️)</span></div>
</div>
""", unsafe_allow_html=True)

# --- Wrapper for CSS scope ---------------------------------------------------
st.markdown('<div id="editable-grid">', unsafe_allow_html=True)

# --- Table CSS: lock menus on editable fields + highlighting -----------------
st.markdown("""
<style>
/* Hide built-in header Select-all (we use external one) */
#editable-grid [data-testid="stDataFrame"] thead input[type="checkbox"] { display: none !important; }

/* Disable the column header menu on EDITABLE fields only */
#editable-grid [data-testid="stDataFrame"] thead tr th:nth-child(1) button,
#editable-grid [data-testid="stDataFrame"] thead tr th:nth-child(3) button,
#editable-grid [data-testid="stDataFrame"] thead tr th:nth-child(5) button,
#editable-grid [data-testid="stDataFrame"] thead tr th:nth-child(6) button,
#editable-grid [data-testid="stDataFrame"] thead tr th:nth-child(7) button,
#editable-grid [data-testid="stDataFrame"] thead tr th:nth-child(8) button {
  display: none !important;
}

/* Editable cells tint + stronger borders for readability */
#editable-grid [data-testid="stDataFrame"] tbody td:nth-child(1),
#editable-grid [data-testid="stDataFrame"] tbody td:nth-child(3),
#editable-grid [data-testid="stDataFrame"] tbody td:nth-child(5),
#editable-grid [data-testid="stDataFrame"] tbody td:nth-child(6),
#editable-grid [data-testid="stDataFrame"] tbody td:nth-child(7),
#editable-grid [data-testid="stDataFrame"] tbody td:nth-child(8) {
  background: #FFF5E5;
  border-bottom: 1px solid #e2e8f0 !important;
  border-top: 1px solid #e2e8f0 !important;
}

/* Zebra striping */
#editable-grid [data-testid="stDataFrame"] tbody tr:nth-child(even) td { background-color: #FFFDF7; }
#editable-grid [data-testid="stDataFrame"] tbody tr:nth-child(odd)  td { background-color: #FFFBF0; }
</style>
""", unsafe_allow_html=True)

# --- Data editor on current page (index hidden by reset_index) ---------------
edited_df = st.data_editor(
    df_page[COLS].reset_index(drop=True),  # <- hides the index column
    column_config={
        "Select": st.column_config.CheckboxColumn("✏️ Select"),
        "username": "Name",
        "email": st.column_config.TextColumn("✏️ Email"),
        "phone": "Phone",
        "paid_for": st.column_config.TextColumn("✏️ Paid For"),
        "membership_paid": st.column_config.CheckboxColumn("✏️ Membership"),
        "early_bird_applied": st.column_config.CheckboxColumn("✏️ Early Bird"),
        "number_of_attendees": st.column_config.NumberColumn("✏️ Attendee Count", min_value=0, step=1),
        "amount": st.column_config.NumberColumn("Amount ($)", format="$%.2f"),
        "payment_date": st.column_config.DateColumn("Payment Date"),
        "transaction_id": "Txn ID",
    },
    use_container_width=True,
    num_rows="dynamic",
    hide_index=True,   # keep positions stable
    disabled=["username", "transaction_id", "amount", "payment_date"],
)

st.markdown('</div>', unsafe_allow_html=True)  # end wrapper

# === Generate QR Codes Button ================================================
if st.button("🎯 Generate QR Codes for Selected"):
    selected = edited_df[edited_df["Select"] == True]
    if selected.empty:
        st.warning("⚠️ No rows selected.")
    else:
        successes, failures = 0, 0
        error_msgs = []

        with st.spinner("Generating and uploading QR codes..."):
            with engine.begin() as conn:
                for _, row in selected.iterrows():
                    try:
                        # normalize & validate transaction_id early
                        txn = str(row.get("transaction_id") or "").strip()
                        if not txn:
                            failures += 1
                            error_msgs.append("Missing transaction_id; row skipped.")
                            continue

                        # validate email (optional but nice)
                        email_val = str(row.get("email", "") or "").strip()
                        if email_val and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_val):
                            failures += 1
                            error_msgs.append(f"Txn {txn}: invalid email '{email_val}'")
                            continue

                        # normalize attendees & boolean fields
                        num_attendees = int(pd.to_numeric(row.get("number_of_attendees"), errors="coerce") or 0)
                        if num_attendees < 0:
                            num_attendees = 0

                        row_clean = {k: to_jsonable(v) for k, v in row.items()}
                        row_clean["transaction_id"] = txn
                        row_clean["email"] = email_val
                        row_clean["number_of_attendees"] = num_attendees
                        row_clean["early_bird_applied"] = bool(row.get("early_bird_applied", False))
                        row_clean["membership_paid"]    = bool(row.get("membership_paid", False))
                        row_clean.setdefault("qr_generated", False)
                        row_clean.setdefault("qr_sent", False)

                        # generate + upload via service
                        s3_url, filename, _qr_bytes, _old_key = regenerate_and_upload(
                            dict(row_clean), event_name=EVENT_NAME
                        )
                        if not s3_url:
                            failures += 1
                            error_msgs.append(f"Txn {txn}: S3 URL missing")
                            continue

                        now = datetime.datetime.now()
                        conn.execute(
                            text("""
                                UPDATE event_payment
                                SET
                                    email = :email,
                                    paid_for = :paid_for,
                                    early_bird_applied = :early_bird_applied,
                                    membership_paid = :membership_paid,
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
                                "early_bird_applied": bool(row.get("early_bird_applied", False)),
                                "membership_paid": bool(row.get("membership_paid", False)),
                                "number_of_attendees": num_attendees,
                                "now": now,
                                "filename": filename,
                                "s3_url": s3_url,
                                "txn": txn,
                            }
                        )

                        successes += 1
                    except Exception as e:
                        failures += 1
                        error_msgs.append(f"Txn {txn or '(no-txn)'}: {e}")

        if successes:
            st.success(f"✅ Generated & uploaded {successes} QR code(s).")
        if failures:
            st.warning(f"⚠️ {failures} record(s) failed.")
            with st.expander("Show errors"):
                for m in error_msgs:
                    st.write("• " + m)

        if st.button("🔄 Refresh Table"):
            st.rerun()
