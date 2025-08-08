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


st.title("📤 QR Issuance")

if 'authenticated' not in st.session_state or not st.session_state.authenticated:
    st.error("Please log in to access this page.")
    st.stop()

conn = sqlite3.connect("event.db")
cur = conn.cursor()

row = cur.execute("SELECT * FROM event_payment WHERE qr_generated = 0 LIMIT 1").fetchone()

if not row:
    st.success("All QR codes have been issued!")
    st.stop()

# Show details
transaction_id, username, email, *_ = row
st.write(f"**User**: {username}")
st.write(f"**Email**: {email}")

# Generate QR
qr_data = f"https://yourdomain.com/view?txn={transaction_id}"
img = qrcode.make(qr_data)

buffer = io.BytesIO()
img.save(buffer)
st.image(buffer.getvalue(), caption="Scan QR", use_column_width=True)

if st.button("📧 Send QR via Email"):
    # Implement send_email(email, qr_data)
    cur.execute("UPDATE event_payment SET qr_generated = 1, qr_sent = 1 WHERE transaction_id = ?", (transaction_id,))
    conn.commit()
    st.success("QR generated and email sent!")
