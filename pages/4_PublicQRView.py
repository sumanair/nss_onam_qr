import streamlit as st
import sqlite3
import urllib.parse
from pathlib import Path

# Show logo in sidebar
logo_path = Path("NSS-Logo-Transparent-2-300x300.png")

with st.sidebar:
    st.image("NSS-Logo-Transparent-2-300x300.png", use_container_width=True)



txn = st.query_params.get("txn")
st.title("🎫 Event QR Viewer")

if txn:
    conn = sqlite3.connect("event.db")
    row = conn.execute("SELECT * FROM event_payment WHERE transaction_id = ?", (txn,)).fetchone()
    if row:
        st.write(f"Name: {row[2]}")
        st.write(f"Email: {row[3]}")
        st.write(f"Paid for: {row[10]}")
        st.write(f"Attendees: {row[13]}")
    else:
        st.error("Invalid transaction ID.")
else:
    st.warning("No transaction ID found in URL.")
