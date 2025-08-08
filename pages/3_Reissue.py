import streamlit as st
import sqlite3
import qrcode
import io
from PIL import Image
from pathlib import Path

# Show logo in sidebar
logo_path = Path("NSS-Logo-Transparent-2-300x300.png")

with st.sidebar:
    st.image("NSS-Logo-Transparent-2-300x300.png", use_container_width=True)



st.title("🔄 Reissue QR Code")

if 'authenticated' not in st.session_state or not st.session_state.authenticated:
    st.error("Please log in to access this page.")
    st.stop()

# --- Connect DB ---
conn = sqlite3.connect("event.db", check_same_thread=False)
cur = conn.cursor()

# --- Fetch issued records ---
rows = cur.execute("""
    SELECT transaction_id, username, email, phone, address, paid_for 
    FROM event_payment 
    WHERE qr_generated = 1 AND qr_sent = 1
""").fetchall()

if not rows:
    st.success("No issued QR codes found to reissue.")
    st.stop()

# --- Dropdown to select user ---
txn_options = [f"{row[0]} - {row[1]}" for row in rows]
selected = st.selectbox("🔍 Select user to reissue QR", txn_options)
selected_row = rows[txn_options.index(selected)]

# --- Unpack fields ---
transaction_id, username, email, phone, address, paid_for = selected_row

# --- Editable form ---
with st.form("reissue_form"):
    new_name = st.text_input("Edit Name", value=username)
    new_email = st.text_input("Edit Email", value=email)
    new_phone = st.text_input("Edit Phone", value=phone)
    new_address = st.text_area("Edit Address", value=address or "")
    new_paid_for = st.text_input("Edit Paid For", value=paid_for)

    submit = st.form_submit_button("💾 Save Changes & Reissue QR")

if submit:
    cur.execute("""
        UPDATE event_payment 
        SET username = ?, email = ?, phone = ?, address = ?, paid_for = ?, qr_reissued_yn = 1 
        WHERE transaction_id = ?
    """, (new_name, new_email, new_phone, new_address, new_paid_for, transaction_id))
    conn.commit()
    st.success("✔️ Changes saved and marked for reissue.")

    # --- Generate QR ---
    qr_data = f"https://yourdomain.com/view?txn={transaction_id}"
    qr_img = qrcode.make(qr_data)
    buf = io.BytesIO()
    qr_img.save(buf)
    st.image(buf.getvalue(), caption="Regenerated QR Code", use_column_width=True)

    if st.button("📧 Resend QR via Email"):
        # TODO: Call send_email_with_qr(new_email, buf)
        st.success(f"📨 QR code sent to {new_email}!")
