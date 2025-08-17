# pages/2_Issuance.py
from utils.screens.issue_screen import render_issue_like_page

render_issue_like_page(
    page_title="📤 QR Issuance",
    header_title="🧾 Ready to Issue (Generated but not Sent)",
    select_sql="""
        SELECT transaction_id, username, email, qr_code_filename, qr_s3_url,
               paid_for, remarks, address, phone,
               membership_paid, early_bird_applied, amount, payment_date,
               number_of_attendees, last_updated_at, qr_generated_at
        FROM event_payment
        WHERE COALESCE(qr_generated, FALSE) = TRUE
          AND COALESCE(qr_sent, FALSE) = FALSE
          AND COALESCE(qr_s3_url, '') <> ''      -- ensure there's actually a QR to send
        ORDER BY last_updated_at DESC NULLS LAST, qr_generated_at DESC NULLS LAST
    """,
    after_send_update_sql="""
        UPDATE event_payment
        SET qr_sent         = TRUE,
            qr_sent_at      = :now,
            last_updated_at = :now
        WHERE transaction_id = :txn
    """,
    send_button_label="📩 Send QR",
    is_reissue=False,   # explicit for readability
)
