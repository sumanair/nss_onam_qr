import datetime
import pandas as pd
from sqlalchemy import text
from utils.db import get_engine

engine = get_engine()

def _coerce_int(v, default=0) -> int:
    try:
        n = int(pd.to_numeric(v, errors="coerce") or default)
        return max(0, n)
    except Exception:
        return default

def fetch_attendance_row_by_txn(txn_id: str):
    with engine.connect() as conn:
        row = conn.execute(
            text("""SELECT transaction_id, username, email,
                           number_of_attendees,
                           COALESCE(number_checked_in,0) as number_checked_in
                    FROM event_payment
                    WHERE transaction_id = :txn
                    LIMIT 1"""),
            {"txn": txn_id}
        ).mappings().first()
        return dict(row) if row else None

def fetch_attendance_by_name_or_email(q: str):
    q_like = f"%{q.strip().lower()}%"
    with engine.connect() as conn:
        rows = conn.execute(
            text("""SELECT transaction_id, username, email,
                           number_of_attendees,
                           COALESCE(number_checked_in,0) as number_checked_in
                    FROM event_payment
                    WHERE LOWER(username) LIKE :q OR LOWER(email) LIKE :q
                    ORDER BY username ASC LIMIT 25"""),
            {"q": q_like}
        ).mappings().all()
        return pd.DataFrame(rows) if rows else pd.DataFrame()

def update_checkins(txn_id: str, delta: int):
    with engine.begin() as conn:
        cur = conn.execute(
            text("""SELECT number_of_attendees, COALESCE(number_checked_in,0) as checked
                    FROM event_payment
                    WHERE transaction_id = :txn
                    FOR UPDATE"""),
            {"txn": txn_id}
        ).mappings().first()
        if not cur: return False, "Transaction not found."

        total, checked = _coerce_int(cur["number_of_attendees"]), _coerce_int(cur["checked"])
        new_val = checked + delta
        if new_val < 0: return False, "Cannot reduce below 0."
        if new_val > total: return False, f"Only {total-checked} remaining."

        conn.execute(
            text("""UPDATE event_payment
                    SET number_checked_in=:val, last_updated_at=:now
                    WHERE transaction_id=:txn"""),
            {"val": new_val, "txn": txn_id, "now": datetime.datetime.now()}
        )
    return True, f"Updated check-ins: {new_val}/{total}"
