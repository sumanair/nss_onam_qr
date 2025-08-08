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

# === Load .env ===
load_dotenv()
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# === Page Setup ===
st.set_page_config(page_title="Admin Panel", page_icon="🛠️")
logo_path = Path("NSS-Logo-Transparent-2-300x300.png")
with st.sidebar:
    st.image(logo_path, use_container_width=True)
st.title("🔐 Admin Panel")

if 'authenticated' not in st.session_state or not st.session_state.authenticated:
    st.error("Please log in to access this page.")
    st.stop()

# === Upload Excel ===
uploaded_file = st.file_uploader("📄 Upload Attendee Excel", type=["xlsx"])

if uploaded_file:
    df_upload = pd.read_excel(uploaded_file)
    df_upload.columns = [col.strip().lower().replace(" ", "_") for col in df_upload.columns]

    default_fields = {
        "qr_generated": False,
        "qr_sent": False,
        "number_of_attendees": 1,
        "number_checked_in": 0,
        "qr_reissued_yn": False,
        "qr_code_filename": "",
        "qr_generated_at": None,
        "qr_sent_at": None,
        "last_updated_at": datetime.datetime.now(),
        "created_at": datetime.datetime.now(),
    }
    for field, default in default_fields.items():
        if field not in df_upload.columns:
            df_upload[field] = default

    df_upload['amount'] = pd.to_numeric(df_upload['amount'], errors='coerce')
    df_upload['payment_date'] = pd.to_datetime(df_upload['payment_date'], errors='coerce')

    # Save new records to DB (skip duplicates)
    conn = sqlite3.connect("event.db")
    existing_txns = pd.read_sql_query("SELECT transaction_id FROM event_payment", conn)['transaction_id'].tolist()
    df_new = df_upload[~df_upload['transaction_id'].isin(existing_txns)]
    if not df_new.empty:
        df_new.to_sql("event_payment", conn, if_exists="append", index=False)
        st.success(f"✅ {len(df_new)} new records saved.")
    else:
        st.info("ℹ️ All records already exist in the database.")
    conn.close()

# === Fetch All Pending Records from DB ===
conn = sqlite3.connect("event.db")
df = pd.read_sql_query("SELECT * FROM event_payment WHERE qr_generated = 0", conn)
conn.close()

# === Filter by Name ===
search_term = st.text_input("🔍 Search by Name", "").strip().lower()
if search_term:
    df = df[df["username"].str.lower().str.contains(search_term)]

if df.empty:
    st.success("✅ No pending records to generate QR codes.")
else:
    st.subheader("🧾 Pending Records (QR not yet generated)")

    # Initialize checkbox state
    if 'selected_rows' not in st.session_state or len(st.session_state.selected_rows) != len(df):
        st.session_state.selected_rows = [False] * len(df)

    # === Pagination ===
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

    # Navigation (Top)
    col_top1, col_top2, col_top3 = st.columns([1, 1, 3])
    with col_top1:
        if st.button("⬅️ Previous"):
            go_prev()
    with col_top2:
        if st.button("➡️ Next"):
            go_next()
    with col_top3:
        if st.button("☑️ Select All on Page"):
            select_all_on_page()

    # Display records for current page
    start_idx = st.session_state.page * ROWS_PER_PAGE
    end_idx = min((st.session_state.page + 1) * ROWS_PER_PAGE, len(df))
    for idx in range(start_idx, end_idx):
        row = df.iloc[idx]
        col1, col2 = st.columns([0.05, 0.85])
        with col1:
            st.session_state.selected_rows[idx] = st.checkbox("", key=f"chk_{idx}", value=st.session_state.selected_rows[idx])
        with col2:
            st.markdown(f"""
                **Name:** {row['username']} ({row['address']})  
                **Txn ID:** {row['transaction_id']}  
                **Email:** {row['email']} | 📞 {row['phone']}  
                **Amount:** ${row['amount']} on {row['payment_date']}  
                **Paid For:** {row['paid_for']}  
                🪪 **Membership:** {'Yes' if row['membership_paid'] else 'No'} | 🐦 **Early Bird:** {'Yes' if row['early_bird_applied'] else 'No'}  
                ✏️ **[Edit Record](#)** 🔧
            """)

    st.markdown("---")

    # === Generate QR Button ===
    if st.button("🎯 Generate QR Codes for Selected"):
        s3 = boto3.client(
            "s3",
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_DEFAULT_REGION
        )
        conn = sqlite3.connect("event.db")
        cur = conn.cursor()
        count = 0

        for idx, selected in enumerate(st.session_state.selected_rows):
            if selected:
                record = df.iloc[idx]
                txn_id = str(record['transaction_id'])
                name = str(record['username']).replace(" ", "")
                filename = f"{txn_id}_{name}.png"

                # QR Payload
                payload = {
                    "transaction_id": txn_id,
                    "name": record['username'],
                    "email": record['email'],
                    "amount": record['amount']
                }

                # Generate QR
                img = qrcode.make(str(payload))
                buffer = BytesIO()
                img.save(buffer, format="PNG")
                buffer.seek(0)

                # Upload to S3
                s3.upload_fileobj(buffer, BUCKET_NAME, f"qrcodes/{filename}")

                # Update DB
                cur.execute("""
                    UPDATE event_payment
                    SET qr_generated = 1,
                        qr_generated_at = ?,
                        qr_code_filename = ?,
                        last_updated_at = ?
                    WHERE transaction_id = ?
                """, (datetime.datetime.now(), filename, datetime.datetime.now(), txn_id))

                count += 1

        conn.commit()
        conn.close()

        if count > 0:
            st.success(f"✅ {count} QR codes generated and uploaded to S3.")
        else:
            st.warning("⚠️ No rows selected.")
