# pages/04_Attendance_Dashboard.py
import os
import time
from datetime import datetime
import pandas as pd
import streamlit as st
from sqlalchemy import text

# ── Page config FIRST ─────────────────────────────────────────
st.set_page_config(page_title="Attendance Dashboard", page_icon="📊", layout="wide")
st.markdown("<div style='margin-bottom: 1.5rem;'></div>", unsafe_allow_html=True)

# ── Shared styling/auth/services (same as your Admin.py) ─────
from utils.styling import inject_global_styles, inject_sidebar_styles
from utils.auth_sidebar import render_auth_in_sidebar, require_auth
from utils.db import get_engine
from config import EVENT_NAME  # used in title; remove if not needed

inject_global_styles()
inject_sidebar_styles()
render_auth_in_sidebar()
require_auth()  # blocks page until logged in

engine = get_engine()

# ── Optional brand accent bar ────────────────────────────────
st.markdown("""
<style>
.bar {background: linear-gradient(90deg,#7a0019 0 20%, #caa43a 20% 70%, #f59e0b 70% 100%);
      height:10px; border-radius:6px; margin:4px 0 12px;}
</style>
<div class="bar"></div>
""", unsafe_allow_html=True)

st.title(f"📊 Attendance Dashboard — {EVENT_NAME}")

# ── Sidebar controls ─────────────────────────────────────────
st.sidebar.header("Controls")
auto_refresh = st.sidebar.checkbox("Auto-refresh", value=True)
interval_s   = st.sidebar.slider("Refresh every (seconds)", 5, 60, 10)

LOCAL_TZ = os.getenv("DISPLAY_TZ", "America/Chicago")

# ── Data loaders (event_payment + event_checkin) ─────────────
def load_totals():
    sql = text("""
    WITH roll AS (
      SELECT
        ec.payment_id,
        COALESCE(SUM(CASE WHEN ec.revoked_yn = FALSE THEN ec.count_checked_in END), 0) AS checked_in
      FROM event_checkin ec
      GROUP BY ec.payment_id
    )
    SELECT
      COALESCE(SUM(ep.number_of_attendees), 0) AS total_attendees,
      COALESCE(SUM(roll.checked_in), 0)        AS checked_in,
      COUNT(*)                                  AS transactions_total,
      SUM(
        CASE WHEN COALESCE(roll.checked_in, 0) >= ep.number_of_attendees THEN 1 ELSE 0 END
      )                                         AS transactions_completed
    FROM event_payment ep
    LEFT JOIN roll ON roll.payment_id = ep.id;
    """)
    with engine.begin() as conn:
        r = conn.execute(sql).mappings().first()
    total = int(r["total_attendees"] or 0)
    checked = int(r["checked_in"] or 0)
    remaining = max(0, total - checked)
    tx_total = int(r["transactions_total"] or 0)
    tx_done  = int(r["transactions_completed"] or 0)
    return total, checked, remaining, tx_total, tx_done

def load_by_type():
    sql = text("""
    WITH roll AS (
      SELECT
        ec.payment_id,
        COALESCE(SUM(CASE WHEN ec.revoked_yn = FALSE THEN ec.count_checked_in END), 0) AS checked_in
      FROM event_checkin ec
      GROUP BY ec.payment_id
    )
    SELECT
      COALESCE(ep.paid_for, '(unknown)') AS ticket_type,
      SUM(ep.number_of_attendees)        AS total_attendees,
      COALESCE(SUM(roll.checked_in), 0)  AS checked_in,
      SUM(ep.number_of_attendees) - COALESCE(SUM(roll.checked_in), 0) AS remaining,
      COUNT(*) AS transactions,
      SUM(CASE WHEN COALESCE(roll.checked_in,0) >= ep.number_of_attendees THEN 1 ELSE 0 END)
        AS transactions_completed
    FROM event_payment ep
    LEFT JOIN roll ON roll.payment_id = ep.id
    GROUP BY 1
    ORDER BY total_attendees DESC NULLS LAST;
    """)
    with engine.begin() as conn:
        return pd.read_sql(sql, conn)

def load_today_10min_delta_and_cum():
    """
    Today-only (local time), 10-minute buckets.
    Deltas: +count for admits, -count for revokes.
    Cumulative: running sum of delta across the day.
    """
    sql = text("""
    SELECT
      to_timestamp(
        floor(
          extract(epoch from (COALESCE(ec.revoked_at, ec.created_at) AT TIME ZONE :tz)) / 600
        ) * 600
      ) AS ts_10m,
      SUM(CASE WHEN ec.revoked_yn = TRUE THEN -ec.count_checked_in ELSE ec.count_checked_in END) AS delta
    FROM event_checkin ec
    WHERE (COALESCE(ec.revoked_at, ec.created_at) AT TIME ZONE :tz)::date = (now() AT TIME ZONE :tz)::date
    GROUP BY 1
    ORDER BY 1;
    """)
    with engine.begin() as conn:
        df = pd.read_sql(sql, conn, params={"tz": LOCAL_TZ})

    # Create a full 10-min index from midnight local -> now for smooth chart
    start = pd.Timestamp(datetime.now()).tz_localize(None).normalize()
    end   = pd.Timestamp(datetime.now()).floor("10min")
    idx   = pd.date_range(start=start, end=end, freq="10min")
    if df.empty:
        out = pd.DataFrame({"ts_10m": idx, "delta": 0})
    else:
        out = (
            df.set_index("ts_10m")
              .reindex(idx, fill_value=0)
              .rename_axis("ts_10m")
              .reset_index()
        )
        out.columns = ["ts_10m", "delta"]
    out["cumulative"] = out["delta"].cumsum()
    return out

def load_recent(limit: int = 500):
    sql = text("""
    SELECT
      (COALESCE(ec.revoked_at, ec.created_at) AT TIME ZONE :tz) AS ts_local,
      ep.transaction_id,
      CASE WHEN ec.revoked_yn = TRUE THEN -ec.count_checked_in ELSE ec.count_checked_in END AS delta,
      COALESCE(ep.paid_for,'') AS ticket_type,
      COALESCE(ec.verifier_id,'') AS verifier_id,
      ec.revoked_yn
    FROM event_checkin ec
    JOIN event_payment ep ON ep.id = ec.payment_id
    ORDER BY COALESCE(ec.revoked_at, ec.created_at) DESC
    LIMIT :limit;
    """)
    with engine.begin() as conn:
        return pd.read_sql(sql, conn, params={"tz": LOCAL_TZ, "limit": limit})

# ── KPIs ─────────────────────────────────────────────────────
try:
    total, checked, remaining, tx_total, tx_done = load_totals()
except Exception as e:
    st.error(f"Error loading totals: {e}")
    st.stop()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Attendees", f"{total:,}")
k2.metric("Checked-in", f"{checked:,}")
k3.metric("Remaining", f"{remaining:,}")
k4.metric("Transactions", f"{tx_total:,}")
k5.metric("Completed Trans.", f"{tx_done:,}")

st.markdown("---")

# ── Chart (left) + Recent Check-ins (right) ──────────────────
left, right = st.columns([1, 1.4])

with left:
    st.subheader("Cumulative Checked-in — Today (10-min)")
    try:
        ts = load_today_10min_delta_and_cum()
        if ts.empty or ts["cumulative"].sum() == 0 and ts["delta"].sum() == 0:
            st.info("No activity yet today.")
        else:
            ts_chart = ts.set_index("ts_10m")[["cumulative"]]
            st.area_chart(ts_chart)  # smooth, always non-decreasing
            # Optional: tiny caption
            st.caption("Cumulative count; revokes reduce the total.")
    except Exception as e:
        st.error(f"Error loading chart: {e}")

with right:
    st.subheader("Recent Check-ins")
    try:
        recent = load_recent(500)
        if recent.empty:
            st.info("No recent events.")
        else:
            recent["ts_local"] = pd.to_datetime(recent["ts_local"]).dt.strftime("%Y-%m-%d %H:%M:%S")
            recent["Δ"] = recent["delta"]
            recent = recent.drop(columns=["delta"])
            st.dataframe(
                recent.rename(columns={
                    "ts_local": "When",
                    "transaction_id": "Transaction",
                    "ticket_type": "Type",
                    "verifier_id": "Verifier",
                    "revoked_yn": "Revoked?",
                }),
                use_container_width=True,
                hide_index=True,
                height=520,
            )
    except Exception as e:
        st.error(f"Error loading recent activity: {e}")

st.markdown("---")

# ── By Ticket Type (bottom, full width) ──────────────────────
st.subheader("By Ticket Type")
try:
    df_type = load_by_type()
    if df_type.empty:
        st.info("No ticket data yet.")
    else:
        df_show = df_type.copy()
        df_show["Completion %"] = (
            (df_show["checked_in"] / df_show["total_attendees"]).replace([pd.NA, 0], 0).fillna(0) * 100
        ).round(1)
        st.dataframe(
            df_show.rename(columns={
                "ticket_type": "Type",
                "total_attendees": "Total",
                "checked_in": "Checked-in",
                "remaining": "Remaining",
                "transactions": "Transactions",
                "transactions_completed": "Trans. Done",
            }),
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "⬇️ Download breakdown (CSV)",
            data=df_show.to_csv(index=False).encode("utf-8"),
            file_name=f"attendance_breakdown_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )
except Exception as e:
    st.error(f"Error loading breakdown: {e}")

# ── Auto-refresh ─────────────────────────────────────────────
if auto_refresh:
    time.sleep(int(interval_s))
    st.rerun()
