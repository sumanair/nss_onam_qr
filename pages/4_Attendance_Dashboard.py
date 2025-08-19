# pages/04_Attendance_Dashboard.py
import os
import time
from datetime import datetime
import pandas as pd
import streamlit as st
from sqlalchemy import text
from zoneinfo import ZoneInfo

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

# ── Helpers ──────────────────────────────────────────────────
def load_revokes_summary():
    """
    Totals across all time:
      - admitted_sum: sum of +count_checked_in
      - revoked_sum:  sum of revoked (positive magnitude)
    """
    sql = text("""
    SELECT
      COALESCE(SUM(CASE WHEN ec.revoked_yn = FALSE THEN ec.count_checked_in END), 0) AS admitted_sum,
      COALESCE(SUM(CASE WHEN ec.revoked_yn = TRUE  THEN ec.count_checked_in END), 0) AS revoked_sum
    FROM event_checkin ec;
    """)
    with engine.begin() as conn:
        r = conn.execute(sql).mappings().first()
    return int(r["admitted_sum"] or 0), int(r["revoked_sum"] or 0)

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
    Today-only in LOCAL_TZ, 10-minute buckets.
    Deltas: +count for admits, -count for revokes.
    Cumulative: running sum of delta across the local day.
    """
    sql = text("""
    SELECT
      to_timestamp(
        floor(
          extract(epoch from (COALESCE(ec.revoked_at, ec.created_at) AT TIME ZONE :tz)) / 600
        ) * 600
      ) AS ts_10m,
      SUM(
        CASE WHEN ec.revoked_yn = TRUE
             THEN -ec.count_checked_in
             ELSE  ec.count_checked_in
        END
      ) AS delta
    FROM event_checkin ec
    WHERE (COALESCE(ec.revoked_at, ec.created_at) AT TIME ZONE :tz)::date = (now() AT TIME ZONE :tz)::date
    GROUP BY 1
    ORDER BY 1;
    """)
    with engine.begin() as conn:
        df = pd.read_sql(sql, conn, params={"tz": LOCAL_TZ})

    # Build the 10-min timeline in the *local* timezone, then drop tz to match SQL output
    tz = ZoneInfo(LOCAL_TZ)
    now_local = pd.Timestamp.now(tz=tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = now_local.floor("10min")
    idx = pd.date_range(start=start_local, end=end_local, freq="10min").tz_localize(None)

    if df.empty:
        out = pd.DataFrame({"ts_10m": idx, "delta": 0})
    else:
        # SQL returns naive timestamps that represent local time already
        df["ts_10m"] = pd.to_datetime(df["ts_10m"])
        out = (
            df.set_index("ts_10m")
              .reindex(idx, fill_value=0)
              .rename_axis("ts_10m")
              .reset_index()
              .rename(columns={"index": "ts_10m"})
        )

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
    st.subheader("Attendance Progress (Overall)")

    try:
        # These already computed above
        total_attendees = total
        checked_in = checked
        remaining_total = max(0, total_attendees - checked_in)

        # Extra signal: revokes
        admitted_sum, revoked_sum = load_revokes_summary()
        revoke_rate = (revoked_sum / admitted_sum * 100) if admitted_sum > 0 else 0.0

        completion_pct = (checked_in / total_attendees * 100) if total_attendees > 0 else 0.0

        # Donut gauge (Altair). Falls back to Streamlit if Altair isn't present.
        data = pd.DataFrame({"label": ["Checked‑in", "Remaining"], "value": [checked_in, remaining_total]})

        try:
            import altair as alt
            chart = alt.Chart(data).mark_arc(innerRadius=70).encode(
                theta=alt.Theta("value:Q"),
                color=alt.Color("label:N", legend=alt.Legend(title=None)),
                tooltip=["label:N", "value:Q"]
            ).properties(height=260)

            center_text = alt.Chart(pd.DataFrame({"text": [f"{completion_pct:.1f}%"]})).mark_text(
                fontSize=28, fontWeight="bold"
            ).encode(text="text:N")

            st.altair_chart(chart + center_text, use_container_width=True)
        except Exception:
            # Fallback
            st.progress(min(1.0, completion_pct / 100.0))
            st.write(f"**{completion_pct:.1f}% complete**  •  {checked_in:,} / {total_attendees:,} checked‑in")

        
        cols = st.columns(3)
        with cols[0]:
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<div style='font-weight:600; color:#374151;'>Checked-in</div>"
                f"<div style='font-size:1.8rem; font-weight:700;'>{checked_in:,}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with cols[1]:
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<div style='font-weight:600; color:#374151;'>Remaining</div>"
                f"<div style='font-size:1.8rem; font-weight:700;'>{remaining_total:,}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with cols[2]:
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<div style='font-weight:600; color:#374151;'>Completion</div>"
                f"<div style='font-size:1.8rem; font-weight:700;'>{completion_pct:.1f}%</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


        # Footnote outside the card
        st.caption(
            f"Revoked entries: {revoked_sum:,} "
            f"({revoke_rate:.1f}% of all admits). Net checked-in = admits − revokes."
        )

    except Exception as e:
        st.error(f"Error rendering progress: {e}")

with right:
    st.subheader("Recent Check-ins")

    NUM_ROWS_VIEWPORT = 10
    ROW_PX = 34        # approx row height
    HEADER_PX = 38     # header height
    PADDING_PX = 16
    TABLE_HEIGHT = HEADER_PX + NUM_ROWS_VIEWPORT * ROW_PX + PADDING_PX  # ~10 visible rows

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
                    "revoked_yn": "Revoke",
                }),
                use_container_width=True,
                hide_index=True,
                height=TABLE_HEIGHT,
            )
            st.caption(f"Showing latest {len(recent)} events (scroll for more).")
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
