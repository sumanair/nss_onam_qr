from utils.qr_s3_utils import build_qr_payload, encode_qr_url, generate_qr_image, upload_to_s3
from utils.json_utils import to_jsonable  # your helper we created earlier
import re
import datetime, streamlit as st, streamlit_authenticator

# --- Editable fields except transaction_id ---
editable_fields = [
    "username", "email", "phone", "address",
    "membership_paid", "early_bird_applied",
    "payment_date", "amount", "paid_for", "remarks",
    "number_of_attendees", "number_checked_in", "qr_reissued_yn"
]

st.subheader("Edit details & regenerate")

# Pull fresh row dict for safety
row_db = df.loc[df["qr_code_filename"] == st.session_state.preview_qr_name].iloc[0].to_dict()

with st.form("edit_and_regen_form", clear_on_submit=False):
    # Build inputs dynamically from row_db if present
    # (fall back if some columns weren’t selected in df)
    def get(key, default=None): return row_db.get(key, default)

    c1, c2 = st.columns(2)
    with c1:
        username = st.text_input("Name", value=str(get("username", "")))
        email    = st.text_input("Email", value=str(get("email", "")))
        phone    = st.text_input("Phone", value=str(get("phone", "")))
        address  = st.text_input("Address", value=str(get("address", "")))
        paid_for = st.text_input("Paid For", value=str(get("paid_for", "")))
        remarks  = st.text_input("Remarks", value=str(get("remarks", "")))
    with c2:
        membership_paid    = st.checkbox("Membership Paid", value=bool(get("membership_paid", False)))
        early_bird_applied = st.checkbox("Early Bird Applied", value=bool(get("early_bird_applied", False)))
        payment_date       = st.date_input("Payment Date", value=(get("payment_date") or datetime.date.today()))
        amount             = st.number_input("Amount ($)", value=float(get("amount") or 0.0), step=0.01, min_value=0.0)
        number_of_attendees = st.number_input("Number of Attendees", value=int(get("number_of_attendees") or 1), step=1, min_value=0)
        number_checked_in   = st.number_input("Number Checked In", value=int(get("number_checked_in") or 0), step=1, min_value=0)
        qr_reissued_yn      = st.checkbox("QR Reissued", value=bool(get("qr_reissued_yn", False)))

    submitted = st.form_submit_button("♻️ Save changes & Regenerate QR")

    if submitted:
        # Basic validations
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            st.error("Invalid email address.")
            st.stop()

        txn_id = row.get("transaction_id") or row_db.get("transaction_id")
        if not txn_id:
            st.error("Missing transaction_id; cannot update.")
            st.stop()

        # Assemble updated row dict (JSON-safe for payload)
        updated = {
            "transaction_id": txn_id,
            "username": username,
            "email": email,
            "phone": phone,
            "address": address,
            "membership_paid": membership_paid,
            "early_bird_applied": early_bird_applied,
            "payment_date": payment_date,  # will be json-serialized via to_jsonable
            "amount": amount,
            "paid_for": paid_for,
            "remarks": remarks,
            "number_of_attendees": number_of_attendees,
            "number_checked_in": number_checked_in,
            "qr_reissued_yn": qr_reissued_yn,
        }

        # 1) Regenerate QR
        #    Clean to JSON-safe for payload
        row_clean = {k: to_jsonable(v) for k, v in updated.items()}
        payload = build_qr_payload(row_clean, event_name="Onam Ponnonam")  # or make this selectable
        url = encode_qr_url(payload)

        safe_name = re.sub(r"[^A-Za-z0-9]+", "", username or "unknown")
        # put a timestamp to avoid collisions
        ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        new_filename = f"{txn_id}_{safe_name}_{ts}.png"

        local_path = generate_qr_image(url, new_filename, local_folder="qr")
        s3_key = f"{S3_PREFIX}{new_filename}"
        try:
            new_s3_url = upload_to_s3(local_path, s3_key)  # returns public or just s3 path depending on your impl
        except Exception as e:
            st.error(f"Upload to S3 failed: {e}")
            st.stop()

        # 2) Persist edits + new QR pointers in DB (and reset qr_sent)
        now = datetime.datetime.now()
        set_parts = [
            "username = :username",
            "email = :email",
            "phone = :phone",
            "address = :address",
            "membership_paid = :membership_paid",
            "early_bird_applied = :early_bird_applied",
            "payment_date = :payment_date",
            "amount = :amount",
            "paid_for = :paid_for",
            "remarks = :remarks",
            "number_of_attendees = :number_of_attendees",
            "number_checked_in = :number_checked_in",
            "qr_reissued_yn = :qr_reissued_yn",
            # QR lifecycle fields:
            "qr_generated = TRUE",
            "qr_generated_at = :now",
            "qr_code_filename = :qr_code_filename",
            "qr_s3_url = :qr_s3_url",
            "qr_sent = FALSE",
            "qr_sent_at = NULL",
            "last_updated_at = :now"
        ]
        sql = f"UPDATE event_payment SET {', '.join(set_parts)} WHERE transaction_id = :txn"

        params = {
            **updated,
            "now": now,
            "qr_code_filename": new_filename,
            "qr_s3_url": new_s3_url,
            "txn": txn_id,
            # ensure types are serializable for psycopg
            "payment_date": datetime.datetime.combine(payment_date, datetime.time()) if isinstance(payment_date, datetime.date) and not isinstance(payment_date, datetime.datetime) else payment_date,
        }

        with engine.begin() as conn:
            conn.execute(text(sql), params)

        st.success("✅ Saved changes and regenerated QR.")
        if st.button("🔄 Refresh Table"):
            st.rerun()
