# [ ... all your existing imports ... ]
import streamlit as st
import pandas as pd
import sqlite3
from io import BytesIO
from pathlib import Path
import qrcode
import os
import datetime
import boto3
from dotenv import load_dotenv

# Load AWS credentials
load_dotenv()
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# Config
st.set_page_config(page_title="Admin Panel", page_icon="🛠️")
logo_path = Path("NSS-Logo-Transparent-2-300x300.png")
with st.sidebar:
    st.image(logo_path, use_container_width=True)
st.title("🔐 Admin Panel")

# Login check
if 'authenticated' not in st.session_state or not st.session_state.authenticated:
    st.error("Please log in to access this page.")
    st.stop()

uploaded_file = st.file_uploader("📄 Upload Attendee Excel", type=["xlsx"])

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    df.columns = [col.strip().lower().replace(" ", "_") for col in df.columns]

    default_fields = {
        "qr_generated": False,
        "qr_sent": False,
        "number_of_attendees": 1,
        "number_checked_in": 0,
        "qr_reissued_yn": False,
        "qr_code_filename": "",
        "qr_generated_at": None,
        "qr_sent_at": None,
        "updated_at": datetime.datetime.now(),
        "created_at": datetime.datetime.now(),
    }

    for field, default in default_fields.items():
        if field not in df.columns:
            df[field] = default

    if 'selected_rows' not in st.session_state or len(st.session_state.selected_rows) != len(df):
        st.session_state.selected_rows = [False] * len(df)

    ROWS_PER_PAGE = 5
    total_pages = (len(df) - 1) // ROWS_PER_PAGE + 1
    if 'page' not in st.session_state:
        st.session_state.page = 0

    def go_next():
        st.session_state.page = min(st.session_state.page + 1, total_pages - 1)

    def go_prev():
        st.session_state.page = max(st.session_state.page - 1, 0)

    def select_all_on_page():
        for i in range(st.session_state.page * ROWS_PER_PAGE, min((st.session_state.page + 1) * ROWS_PER_PAGE, len(df))):
            st.session_state.selected_rows[i] = True

    st.subheader("📋 Preview & Select Rows")

    # Top navigation
    col_top1, col_top2, col_top3 = st.columns([1, 1, 3])
    with col_top1:
        if st.button("⬅️ Previous"):
            go_prev()
    with col_top2:
        if st.button("➡️ Next"):
            go_next()
    with col_top3:
        if st.button("☑️ Select All on This Page"):
            select_all_on_page()

    # Page display
    start_idx = st.session_state.page * ROWS_PER_PAGE
    end_idx = min((st.session_state.page + 1) * ROWS_PER_PAGE, len(df))
    for idx in range(start_idx, end_idx):
        row = df.iloc[idx]
        col1, col2 = st.columns([0.1, 0.9])
        with col1:
            st.session_state.selected_rows[idx] = st.checkbox("", key=f"chk_{idx}", value=st.session_state.selected_rows[idx])
        with col2:
            st.markdown(f"""
                **Name:** {row.get('username', 'N/A')}  
                **Transaction ID:** {row.get('transaction_id', 'N/A')}  
                **Email:** {row.get('email', 'N/A')}  
                **Amount:** {row.get('amount', 'N/A')}
            """)

    st.markdown("---")

    # Save all to DB
    col_save, col_qr = st.columns([1, 2])
    with col_save:
        if st.button("✅ Save All to DB"):
            bool_cols = ['membership_paid', 'early_bird_applied', 'qr_generated', 'qr_sent', 'qr_reissued_yn']
            for col in bool_cols:
                df[col] = df[col].astype(bool)

            df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
            df['payment_date'] = pd.to_datetime(df['payment_date'], errors='coerce')

            now = datetime.datetime.now()
            df['created_at'] = now
            df['updated_at'] = now

            conn = sqlite3.connect("event.db")
            df.to_sql("event_payment", conn, if_exists="append", index=False)
            conn.close()

            st.success(f"✅ All {len(df)} rows saved to the database.")

    # Generate QR Codes and update DB
    with col_qr:
        if st.button("🎯 Generate QR Codes for Selected"):
            count = 0
            conn = sqlite3.connect("event.db")
            cursor = conn.cursor()
            s3 = boto3.client(
                "s3",
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_DEFAULT_REGION
            )

            for idx, selected in enumerate(st.session_state.selected_rows):
                if selected:
                    row = df.iloc[idx]
                    txn_id = str(row.get("transaction_id", "unknown"))
                    name = str(row.get("username", "unknown")).replace(" ", "")
                    filename = f"{txn_id}_{name}.png"

                    payload = {
                        "transaction_id": txn_id,
                        "name": row.get("username", ""),
                        "email": row.get("email", ""),
                        "amount": row.get("amount", "")
                    }

                    img = qrcode.make(str(payload))
                    buffer = BytesIO()
                    img.save(buffer, format="PNG")
                    buffer.seek(0)

                    s3.upload_fileobj(buffer, BUCKET_NAME, f"qrcodes/{filename}")
                    now = datetime.datetime.now()

                    try:
                        cursor.execute("""
                            UPDATE event_payment
                            SET 
                                qr_generated = 1,
                                qr_generated_at = ?,
                                qr_code_filename = ?,
                                last_updated_at = ?
                            WHERE transaction_id = ?
                        """, (now, filename, now, txn_id))
                        count += 1
                    except Exception as e:
                        st.error(f"❌ DB update failed for {txn_id}: {e}")

            conn.commit()
            conn.close()

            if count > 0:
                st.success(f"🎉 {count} QR code(s) generated and S3 + DB updated")
            else:
                st.warning("⚠️ No rows selected.")
