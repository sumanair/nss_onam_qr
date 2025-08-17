# pages/3_Reissuance.py
import streamlit as st

# --- HOTFIX: make sure keys exist before auth.login() runs anywhere ---
for k, v in {
    "logout": False,
    "authentication_status": None,
    "username": "",
    "name": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v
# ----------------------------------------------------------------------

from utils.screens.issue_screen import render_issue_like_page

render_issue_like_page(
    page_title="♻️ QR Re-issuance",
    header_title="🔁 Sent but Requested Re-issue",
    select_sql="""
        SELECT transaction_id, username, email, qr_code_filename, qr_s3_url,
               paid_for, remarks, address, phone,
               membership_paid, early_bird_applied, amount, payment_date,
               number_of_attendees, last_updated_at, qr_sent_at
        FROM event_payment
        WHERE qr_sent = TRUE
          AND COALESCE(qr_reissued_yn, FALSE) = FALSE
        ORDER BY last_updated_at DESC NULLS LAST, qr_sent_at DESC NULLS LAST
    """,
    after_send_update_sql="""
        UPDATE event_payment
        SET qr_reissued_yn  = TRUE, 
            qr_reissued_at  = :now,
            last_updated_at = :now
        WHERE transaction_id = :txn
    """,
    send_button_label="📩 Re-send QR",
)
