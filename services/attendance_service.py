import datetime
from typing import Optional, Dict, Any, List

import pandas as pd
from sqlalchemy import text
from utils.db import get_engine

engine = get_engine()

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _coerce_int(v, default=0) -> int:
    try:
        n = int(pd.to_numeric(v, errors="coerce") or default)
        return max(0, n)
    except Exception:
        return default

def _fetch_payment_by_txn(conn, txn_id: str) -> Optional[Dict[str, Any]]:
    """Lock parent row for updates when needed."""
    row = conn.execute(
        text("""
            SELECT id, transaction_id, username, email,
                   number_of_attendees
            FROM event_payment
            WHERE transaction_id = :txn
            FOR UPDATE
        """),
        {"txn": txn_id}
    ).mappings().first()
    return dict(row) if row else None

def _rollup_counts(conn, payment_id: int) -> Dict[str, int]:
    """Compute active (non-revoked) checked-in total from child table."""
    row = conn.execute(
        text("""
            SELECT
              COALESCE(SUM(CASE WHEN revoked_yn = FALSE THEN count_checked_in END), 0) AS checked_in
            FROM event_checkin
            WHERE payment_id = :pid
        """),
        {"pid": payment_id}
    ).mappings().first()
    checked = _coerce_int(row["checked_in"], 0) if row else 0
    return {"checked_in": checked}

def _remaining(conn, payment_id: int, planned: int) -> int:
    r = _rollup_counts(conn, payment_id)
    return max(0, planned - r["checked_in"])

# ─────────────────────────────────────────────────────────────
# Public API used by your app
# ─────────────────────────────────────────────────────────────

def fetch_attendance_row_by_txn(txn_id: str) -> Optional[Dict[str, Any]]:
    """Return parent + derived rollups (checked_in, remaining, all_done)."""
    with engine.connect() as conn:
        base = conn.execute(
            text("""
                SELECT id, transaction_id, username, email, number_of_attendees
                FROM event_payment
                WHERE transaction_id = :txn
                LIMIT 1
            """),
            {"txn": txn_id}
        ).mappings().first()
        if not base:
            return None
        base = dict(base)
        r = _rollup_counts(conn, base["id"])
        checked = r["checked_in"]
        total = _coerce_int(base["number_of_attendees"])
        return {
            "transaction_id": base["transaction_id"],
            "username": base["username"],
            "email": base["email"],
            "number_of_attendees": total,
            "number_checked_in": checked,
            "remaining": max(0, total - checked),
            "all_attendees_checked_in": (total > 0 and checked >= total),
        }

def fetch_attendance_by_name_or_email(q: str) -> pd.DataFrame:
    """Search by name/email and include derived counts."""
    q_like = f"%{q.strip().lower()}%"
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT ep.id, ep.transaction_id, ep.username, ep.email, ep.number_of_attendees,
                       COALESCE(SUM(CASE WHEN ec.revoked_yn = FALSE THEN ec.count_checked_in END), 0) AS number_checked_in
                FROM event_payment ep
                LEFT JOIN event_checkin ec ON ec.payment_id = ep.id
                WHERE LOWER(ep.username) LIKE :q OR LOWER(ep.email) LIKE :q
                GROUP BY ep.id
                ORDER BY ep.username ASC
                LIMIT 25
            """),
            {"q": q_like}
        ).mappings().all()

        data = []
        for r in rows or []:
            r = dict(r)
            total = _coerce_int(r["number_of_attendees"])
            checked = _coerce_int(r["number_checked_in"])
            data.append({
                "transaction_id": r["transaction_id"],
                "username": r["username"],
                "email": r["email"],
                "number_of_attendees": total,
                "number_checked_in": checked,
                "remaining": max(0, total - checked),
                "all_attendees_checked_in": (total > 0 and checked >= total),
            })
        return pd.DataFrame(data) if data else pd.DataFrame()

def update_checkins(txn_id: str, delta: int, verifier_id: Optional[str] = None, notes: Optional[str] = None):
    """
    Batch-aware update:
      - delta > 0  => insert one event_checkin row of 'delta'
      - delta < 0  => rewind most recent active batches totalling |delta| (revoke or reduce)
      - delta = 0  => no-op
    Uses triggers to stamp parent & keep cached columns in sync (if you kept them).
    """
    if delta == 0:
        return True, "No change."

    with engine.begin() as conn:  # BEGIN … COMMIT
        # Lock parent
        pay = _fetch_payment_by_txn(conn, txn_id)
        if not pay:
            return False, "Transaction not found."
        payment_id = pay["id"]
        total = _coerce_int(pay["number_of_attendees"])

        if delta > 0:
            # Pre-check remaining (guard also enforced by DB trigger)
            remaining = _remaining(conn, payment_id, total)
            if delta > remaining:
                return False, f"Only {remaining} remaining."

            conn.execute(
                text("""
                    INSERT INTO event_checkin (payment_id, count_checked_in, verifier_id, notes)
                    VALUES (:pid, :cnt, :vid, :nts)
                """),
                {"pid": payment_id, "cnt": delta, "vid": verifier_id, "nts": notes}
            )
            new_rollup = _rollup_counts(conn, payment_id)["checked_in"]
            return True, f"Checked in {delta}. Now {new_rollup}/{total}."

        # delta < 0: revoke / reduce most recent active batches
        to_rewind = abs(delta)

        # Fetch active batches newest-first
        batches: List[Dict[str, Any]] = conn.execute(
            text("""
                SELECT id, count_checked_in
                FROM event_checkin
                WHERE payment_id = :pid AND revoked_yn = FALSE
                ORDER BY created_at DESC, id DESC
                FOR UPDATE
            """),
            {"pid": payment_id}
        ).mappings().all()

        current_checked = _rollup_counts(conn, payment_id)["checked_in"]
        if to_rewind > current_checked:
            return False, f"Cannot rewind {to_rewind}; only {current_checked} already checked in."

        remaining_to_rewind = to_rewind
        for b in batches:
            if remaining_to_rewind <= 0:
                break
            bid = b["id"]
            cnt = _coerce_int(b["count_checked_in"])
            if cnt <= remaining_to_rewind:
                # Fully revoke this batch
                conn.execute(
                    text("""
                        UPDATE event_checkin
                           SET revoked_yn = TRUE,
                               revoked_at = CURRENT_TIMESTAMP,
                               revoked_by = COALESCE(:vid, revoked_by)
                         WHERE id = :bid
                    """),
                    {"bid": bid, "vid": verifier_id}
                )
                remaining_to_rewind -= cnt
            else:
                # Partially reduce this batch
                new_cnt = cnt - remaining_to_rewind
                conn.execute(
                    text("""
                        UPDATE event_checkin
                           SET count_checked_in = :new_cnt
                         WHERE id = :bid
                    """),
                    {"bid": bid, "new_cnt": new_cnt}
                )
                remaining_to_rewind = 0

        new_rollup = _rollup_counts(conn, payment_id)["checked_in"]
        return True, f"Rewound {to_rewind}. Now {new_rollup}/{total}."
