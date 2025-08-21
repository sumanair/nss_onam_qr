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

# ── Shared styling/services (no auth) ────────────────────────
from utils.styling import inject_global_styles, inject_sidebar_styles
from utils.db import get_engine
from config import EVENT_NAME

inject_global_styles()
inject_sidebar_styles()

engine = get_engine()
LOCAL_TZ = os.getenv("DISPLAY_TZ", "America/Chicago")

# ── Accent bar ───────────────────────────────────────────────
st.markdown("""
<style>
.bar {background: linear-gradient(90deg,#7a0019 0 20%, #caa43a 20% 70%, #f59e0b 70% 100%);
      height:10px; border-radius:6px; margin:4px 0 12px;}
</style>
<div class="bar"></div>
""", unsafe_allow_html=True)

# Center the title + subheader
_, mid, _ = st.columns([1, 2, 1])
with mid:
    st.title("📊 Attendance Dashboard")
    st.subheader(EVENT_NAME)

# ── Sidebar ──────────────────────────────────────────────────
st.sidebar.header("Controls")
auto_refresh = st.sidebar.checkbox("Auto-refresh", value=True)
interval_s   = st.sidebar.slider("Refresh every (seconds)", 5, 60, 10)

# ── Helpers ──────────────────────────────────────────────────
def load_revokes_summary():
    sql = text("""
    SELECT
      COALESCE(SUM(CASE WHEN ec.revoked_yn = FALSE THEN ec.count_checked_in END), 0) AS admitted_sum,
      COALESCE(SUM(CASE WHEN ec.revoked_yn = TRUE  THEN ec.count_checked_in END), 0) AS revoked_sum
    FROM event_checkin ec;
    """)
    with engine.begin() as conn:
        r = conn.execute(sql).mappings().first()
    return int(r["admitted_sum"] or 0), int(r["revoked_sum"] or 0)

def load_totals_and_status():
    """
    Compute NET check-ins per payment (undo-friendly):
      net_checked_in = sum(+count) - sum(revoked count)
    Clamp per payment: min(max(net, 0), ep.number_of_attendees)

    Returns:
      total_attendees, checked_in_attendees, remaining_attendees,
      tx_total, tx_full, tx_partial, tx_not_started,
      attendees_not_started, attendees_remaining_in_progress
    """
    sql = text("""
    WITH roll AS (
      SELECT
        ec.payment_id,
        COALESCE(SUM(CASE WHEN ec.revoked_yn IS TRUE
                          THEN -ec.count_checked_in
                          ELSE  ec.count_checked_in END), 0) AS net_checked_in
      FROM event_checkin ec
      GROUP BY ec.payment_id
    ),
    joined AS (
      SELECT
        ep.id,
        ep.number_of_attendees,
        GREATEST(0, COALESCE(roll.net_checked_in, 0)) AS net_raw
      FROM event_payment ep
      LEFT JOIN roll ON roll.payment_id = ep.id
    ),
    clamped AS (
      SELECT
        id,
        number_of_attendees,
        LEAST(net_raw, number_of_attendees) AS net_clamped
      FROM joined
    )
    SELECT
      COALESCE(SUM(number_of_attendees), 0) AS total_attendees,
      COALESCE(SUM(net_clamped), 0) AS checked_in_attendees,

      -- attendees in tx with 0 net
      COALESCE(SUM(CASE WHEN net_clamped = 0
                        THEN number_of_attendees ELSE 0 END), 0) AS attendees_not_started,

      -- attendees remaining only within partial tx
      COALESCE(SUM(CASE WHEN net_clamped > 0 AND net_clamped < number_of_attendees
                        THEN number_of_attendees - net_clamped ELSE 0 END), 0) AS attendees_remaining_in_progress,

      COUNT(*) AS tx_total,
      COALESCE(SUM(CASE WHEN net_clamped >= number_of_attendees THEN 1 ELSE 0 END), 0) AS tx_full,
      COALESCE(SUM(CASE WHEN net_clamped = 0 THEN 1 ELSE 0 END), 0) AS tx_not_started,
      COALESCE(SUM(CASE WHEN net_clamped > 0 AND net_clamped < number_of_attendees THEN 1 ELSE 0 END), 0) AS tx_partial
    FROM clamped;
    """)
    with engine.begin() as conn:
        r = conn.execute(sql).mappings().first()

    total_attendees = int(r["total_attendees"] or 0)
    checked_in_attendees = int(r["checked_in_attendees"] or 0)
    attendees_not_started = int(r["attendees_not_started"] or 0)
    attendees_remaining_in_progress = int(r["attendees_remaining_in_progress"] or 0)

    remaining_attendees = max(0, total_attendees - checked_in_attendees)

    tx_total = int(r["tx_total"] or 0)
    tx_full = int(r["tx_full"] or 0)
    tx_partial = int(r["tx_partial"] or 0)
    tx_not_started = int(r["tx_not_started"] or 0)

    return (total_attendees, checked_in_attendees, remaining_attendees,
            tx_total, tx_full, tx_partial, tx_not_started,
            attendees_not_started, attendees_remaining_in_progress)

def load_by_type():
    sql = text("""
    WITH roll AS (
      SELECT
        ec.payment_id,
        COALESCE(SUM(CASE WHEN ec.revoked_yn IS TRUE
                          THEN -ec.count_checked_in
                          ELSE  ec.count_checked_in END), 0) AS net_checked_in
      FROM event_checkin ec
      GROUP BY ec.payment_id
    )
    SELECT
      COALESCE(ep.paid_for, '(unknown)') AS ticket_type,
      SUM(ep.number_of_attendees)        AS total_attendees,
      COALESCE(SUM(LEAST(GREATEST(roll.net_checked_in,0), ep.number_of_attendees)), 0)  AS checked_in,
      SUM(ep.number_of_attendees) - COALESCE(SUM(LEAST(GREATEST(roll.net_checked_in,0), ep.number_of_attendees)), 0) AS remaining,
      COUNT(*) AS transactions,
      SUM(CASE WHEN COALESCE(roll.net_checked_in,0) >= ep.number_of_attendees THEN 1 ELSE 0 END)
        AS transactions_completed
    FROM event_payment ep
    LEFT JOIN roll ON roll.payment_id = ep.id
    GROUP BY 1
    ORDER BY total_attendees DESC NULLS LAST;
    """)
    with engine.begin() as conn:
        return pd.read_sql(sql, conn)

def load_recent(limit: int = 500):
    """
    Recent admissions/revokes with human-friendly identity and per-transaction status.
    Status is computed against *current* net totals per payment (net of revokes).
    """
    sql = text("""
    WITH roll AS (
      SELECT
        ec.payment_id,
        COALESCE(SUM(CASE WHEN ec.revoked_yn IS TRUE
                          THEN -ec.count_checked_in
                          ELSE  ec.count_checked_in END), 0) AS net_checked_in
      FROM event_checkin ec
      GROUP BY ec.payment_id
    )
    SELECT
      (COALESCE(ec.revoked_at, ec.created_at) AT TIME ZONE :tz) AS ts_local,
      COALESCE(ep.username, '') AS username,
      COALESCE(ep.email, '') AS email,
      COALESCE(ep.paid_for,'') AS ticket_type,
      COALESCE(ep.number_of_attendees, 0) AS attendees_total,
      COALESCE(ec.verifier_id,'') AS verifier_id,
      CASE WHEN ec.revoked_yn = TRUE THEN -ec.count_checked_in ELSE ec.count_checked_in END AS delta,
      ec.revoked_yn,
      CASE
        WHEN LEAST(GREATEST(roll.net_checked_in,0), ep.number_of_attendees) >= ep.number_of_attendees
          THEN 'Full'
        WHEN COALESCE(roll.net_checked_in, 0) = 0
          THEN 'Not started'
        ELSE 'Partial'
      END AS status
    FROM event_checkin ec
    JOIN event_payment ep ON ep.id = ec.payment_id
    LEFT JOIN roll ON roll.payment_id = ep.id
    ORDER BY COALESCE(ec.revoked_at, ec.created_at) DESC
    LIMIT :limit;
    """)
    with engine.begin() as conn:
        df = pd.read_sql(sql, conn, params={"tz": LOCAL_TZ, "limit": limit})
    return df

# ── KPIs ─────────────────────────────────────────────────────
try:
    (total, checked, remaining,
     tx_total, tx_full, tx_partial, tx_not_started,
     attendees_not_started, attendees_remaining_in_progress) = load_totals_and_status()
except Exception as e:
    st.error(f"Error loading totals: {e}")
    st.stop()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Attendees", f"{total:,}")
k2.metric("Checked-in", f"{checked:,}")
k3.metric("Remaining", f"{remaining:,}")
k4.metric("Transactions", f"{tx_total:,}")
k5.metric("Completed Trans.", f"{tx_full:,}")

st.markdown("---")

# ── Charts (left) + Recent Check-ins (right) ─────────────────
left, right = st.columns([1, 1.4])

with left:
    st.subheader("Attendance (Headcount)")
    try:
        admitted_sum, revoked_sum = load_revokes_summary()
        revoke_rate = (revoked_sum / admitted_sum * 100) if admitted_sum > 0 else 0.0

        # Colors (WCAG-friendly on your light background)
        GREEN = "#16a34a"   # checked/complete
        BLUE  = "#3b82f6"   # in-progress (transactions that have begun)
        ORANGE= "#f59e0b"   # not started

        # ── Donut A: Attendees status (Headcount) — no "Partial" label here
        
        try:
            import altair as alt
            not_checked = attendees_not_started + attendees_remaining_in_progress
            data_att = pd.DataFrame({
                "label": ["Checked-in", "Not checked-in"],
                "value": [checked, not_checked],
            })
            donut_att = alt.Chart(data_att).mark_arc(innerRadius=70).encode(
                theta=alt.Theta("value:Q"),
                color=alt.Color(
                    "label:N",
                    legend=alt.Legend(title=None),
                    scale=alt.Scale(
                        domain=["Checked-in", "Not checked-in"],
                        range=[GREEN, ORANGE],  # green for checked, orange for not yet scanned
                    ),
                ),
                tooltip=["label:N", "value:Q"],
            ).properties(height=260, title="Attendees status (Headcount)")
            st.altair_chart(donut_att, use_container_width=True)
        except Exception:
            not_checked = attendees_not_started + attendees_remaining_in_progress
            st.write(
                f"**Attendees (Headcount):** "
                f"✅ Checked-in {checked:,} • "
                f"🟠 Not checked-in {not_checked:,}"
            )

        # KPI tiles under the donut
        not_checked = attendees_not_started + attendees_remaining_in_progress
        cols = st.columns(3)
        with cols[0]:
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<div style='font-weight:600; color:#374151;'>Checked-in</div>"
                f"<div style='font-size:1.8rem; font-weight:700;'>{checked:,}</div>"
                f"</div>", unsafe_allow_html=True
            )
        with cols[1]:
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<div style='font-weight:600; color:#374151;'>Not checked-in</div>"
                f"<div style='font-size:1.8rem; font-weight:700;'>{not_checked:,}</div>"
                f"</div>", unsafe_allow_html=True
            )
        with cols[2]:
            completion_pct = (checked / total * 100) if total > 0 else 0.0
            st.markdown(
                f"<div style='text-align:center;'>"
                f"<div style='font-weight:600; color:#374151;'>Completion</div>"
                f"<div style='font-size:1.8rem; font-weight:700;'>{completion_pct:.1f}%</div>"
                f"</div>", unsafe_allow_html=True
            )

        # Caption (headcount-only wording; no "in progress" here)
        st.caption(
            "Headcount view. Orange = not yet scanned (includes both orders that have not started and those in progress). "
            f"Revoked entries: {revoked_sum:,} ({revoke_rate:.1f}% of admits)."
        )


        # ── Transactions Progress (Payment level) — 100% stacked horizontal bar
        st.markdown("#### Transactions Progress (Individual Payment level)")

        # Always show preview toggle; default ON only when there is no live data yet
        preview_tx = st.checkbox("Preview with sample data", value=(tx_total == 0), key="preview_tx")

        # Choose data source
        if preview_tx:
            total_tx_sample   = max(tx_total, 15)
            tx_full_v         = max(1, int(round(total_tx_sample * 0.30)))
            tx_partial_v      = max(1, int(round(total_tx_sample * 0.40)))
            tx_not_started_v  = max(0, total_tx_sample - tx_full_v - tx_partial_v)
            total_tx_v        = total_tx_sample
            preview_note      = " (preview)"
        else:
            tx_full_v, tx_partial_v, tx_not_started_v = tx_full, tx_partial, tx_not_started
            total_tx_v   = tx_total if tx_total > 0 else 1
            preview_note = ""

        try:
            import altair as alt

            # Build dataframe for the bar
            df_pf = pd.DataFrame({
                "status": ["Full", "Partial", "Not started"],
                "count":  [tx_full_v, tx_partial_v, tx_not_started_v],
            })
            df_pf["pct"]   = df_pf["count"] / (total_tx_v if total_tx_v else 1)
            df_pf["label"] = df_pf.apply(lambda r: f'{int(r["count"])} ({r["pct"]:.0%})', axis=1)
            df_pf["group"] = "All transactions"

            # Main 100% stacked bar (legend disabled here — we render a manual one below)
            bar = alt.Chart(df_pf).mark_bar(height=36).encode(
                y=alt.Y("group:N", axis=None),
                x=alt.X("count:Q", stack="normalize", axis=alt.Axis(format="%", title=None)),
                color=alt.Color(
                    "status:N",
                    scale=alt.Scale(
                        domain=["Full", "Partial", "Not started"],
                        range=[GREEN, BLUE, ORANGE],
                    ),
                    legend=None,  # manual legend below so it ALWAYS shows
                ),
                tooltip=[
                    alt.Tooltip("status:N", title="Status"),
                    alt.Tooltip("count:Q",  title="Count"),
                    alt.Tooltip("pct:Q",    title="Share", format=".0%"),
                ],
            ).properties(height=60, title=f"Share of orders by status{preview_note}")

            # In-bar white labels (only on non-zero segments)
            labels = alt.Chart(df_pf[df_pf["count"] > 0]).mark_text(
                baseline="middle", dy=0, color="white"
            ).encode(
                y=alt.Y("group:N", axis=None),
                x=alt.X("count:Q", stack="normalize"),
                text="label:N",
            )

            st.altair_chart(bar + labels, use_container_width=True)

            # Always-visible legend (HTML, independent of Altair)
            st.markdown(
                f"""
                <div style="display:flex; gap:16px; align-items:center; font-size:0.9rem; margin-top:6px;">
                <span><span style="display:inline-block; width:12px; height:12px; background:{GREEN}; border-radius:2px; margin-right:6px;"></span>Full</span>
                <span><span style="display:inline-block; width:12px; height:12px; background:{BLUE}; border-radius:2px; margin-right:6px;"></span>Partial</span>
                <span><span style="display:inline-block; width:12px; height:12px; background:{ORANGE}; border-radius:2px; margin-right:6px;"></span>Not started</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if preview_tx:
                st.caption("Preview with sample data — toggle off to see live numbers.")
        except Exception:
            pct = lambda n, d: (n / d * 100) if d else 0
            st.write(
                f"**Transactions (Payment level){preview_note}:** "
                f"✅ Full {tx_full_v:,} ({pct(tx_full_v, total_tx_v):.0f}%) • "
                f"🔵 Partial {tx_partial_v:,} ({pct(tx_partial_v, total_tx_v):.0f}%) • "
                f"🟠 Not started {tx_not_started_v:,} ({pct(tx_not_started_v, total_tx_v):.0f}%)"
            )


    except Exception as e:
        st.error(f"Error rendering progress: {e}")

with right:
    st.subheader("Recent Check-ins")

    NUM_ROWS_VIEWPORT = 10
    ROW_PX = 34
    HEADER_PX = 38
    PADDING_PX = 16
    TABLE_HEIGHT = HEADER_PX + NUM_ROWS_VIEWPORT * ROW_PX + PADDING_PX

    try:
        recent = load_recent(500)
        if recent.empty:
            st.info("No recent events.")
        else:
            # We don't display ts_local or ticket_type anymore, but keep parse for consistency if needed later
            recent["ts_local"] = pd.to_datetime(recent["ts_local"]).dt.strftime("%Y-%m-%d %H:%M:%S")

            def _payee_cell(row):
                name = (row.get("username") or "").strip()
                email = (row.get("email") or "").strip()
                if name and email:
                    return f"{name}\n{email}"   # newline between name and email
                return name or email or "(unknown)"

            recent["Payee"] = recent.apply(_payee_cell, axis=1)
            recent["Δ"] = recent["delta"]
            recent = recent.drop(columns=["delta"])

        display_df = recent.rename(columns={
            "verifier_id": "Verifier",
            "revoked_yn": "Revoke",
            "status": "Status",
        })[["Payee", "Verifier", "Δ", "Revoke", "Status"]]

        # ---- Render as custom HTML (scrollable, no index, Payee on two lines) ----
        from html import escape

        def _bool_icon(v):
            s = str(v).lower()
            if s in ("true", "t", "1", "yes", "y"):  return "✅"
            if s in ("false", "f", "0", "no", "n"):  return "—"
            return escape(str(v))

        rows_html = []
        for _, r in display_df.iterrows():
            payee_html  = escape(str(r["Payee"])).replace("\n", "<br>")
            verifier    = escape(str(r["Verifier"]))
            delta_raw   = r["Δ"]
            # color Δ: green for +, red for −
            try:
                d = float(delta_raw)
            except Exception:
                d = None
            if d is None or d == 0:
                delta_html = escape(str(delta_raw))
                delta_style = ""
            else:
                delta_html = f"{'+' if d>0 else ''}{int(d) if d.is_integer() else d}"
                delta_style = "color:#16a34a;" if d > 0 else "color:#b91c1c;"  # green / red
            revoke      = _bool_icon(r["Revoke"])
            status      = escape(str(r["Status"]))
            rows_html.append(
                f"<tr>"
                f"<td class='payee'>{payee_html}</td>"
                f"<td>{verifier}</td>"
                f"<td style='text-align:right; {delta_style}'>{delta_html}</td>"
                f"<td style='text-align:center;'>{revoke}</td>"
                f"<td>{status}</td>"
                f"</tr>"
            )

        table_html = f"""
        <style>
        .recent-wrap {{
            max-height:{TABLE_HEIGHT}px; overflow-y:auto;
            border-radius:12px; border:1px solid rgba(0,0,0,0.08);
            background:transparent;
        }}
        .recent-table {{ width:100%; border-collapse:separate; border-spacing:0; }}
        .recent-table th, .recent-table td {{ padding:10px 12px; border-bottom:1px solid rgba(0,0,0,0.06); }}
        .recent-table thead th {{
            position: sticky; top: 0; z-index: 1;
            background: rgba(0,0,0,0.03);
            border-bottom:1px solid rgba(0,0,0,0.12);
            text-align:left;
        }}
        .recent-table th[title] {{ text-decoration: underline dotted; cursor: help; }}
        .recent-table td.payee {{ white-space: pre-line; }}
        </style>
        <div class="recent-wrap">
        <table class="recent-table">
            <thead>
            <tr>
                <th title="Buyer on the payment (name and email)">Payee</th>
                <th title="Staff/volunteer who scanned">Verifier</th>
                <th title="Net change for this event row: + admits, − revokes">Δ</th>
                <th title="This row is a revoke (undo) action">Revoke</th>
                <th title="Current order status from net admits vs quantity">Status</th>
            </tr>
            </thead>
            <tbody>
            {''.join(rows_html)}
            </tbody>
        </table>
        </div>
        """
        st.markdown(table_html, unsafe_allow_html=True)
        st.caption("Status reflects current **net** totals per transaction.")

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
