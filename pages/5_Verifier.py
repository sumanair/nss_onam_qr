import streamlit as st
import sqlite3
from pathlib import Path

# Show logo in sidebar
logo_path = Path("NSS-Logo-Transparent-2-300x300.png")

with st.sidebar:
    st.image("NSS-Logo-Transparent-2-300x300.png", use_container_width=True)



st.title("🛂 Attendance Check-In")

if 'authenticated' not in st.session_state or not st.session_state.authenticated:
    st.error("Please log in to access this page.")
    st.stop()

txn = st.text_input("🔍 Scan or enter QR Code Transaction ID")
if txn:
    conn = sqlite3.connect("event.db")
    row = conn.execute("SELECT number_of_attendees, number_checked_in FROM event_payment WHERE transaction_id = ?", (txn,)).fetchone()

    if row:
        total, checked = row
        new_checked = st.number_input("👥 Number checked in now:", min_value=0, max_value=total - checked, value=1)

        if st.button("✅ Update Attendance"):
            conn.execute("UPDATE event_payment SET number_checked_in = number_checked_in + ? WHERE transaction_id = ?", (new_checked, txn))
            conn.commit()
            st.success(f"{new_checked} attendee(s) checked in!")
    else:
        st.error("Transaction not found.")
