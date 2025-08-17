# pages/_issue_screen.py
"""
Shared issue/reissue screen.
- Keeps UI, form, and list navigation.
- Delegates QR generation/upload + bytes caching to services.qr_service
- Delegates S3 delete/get to services.s3_service
- Delegates email composition/sending (inline QR + BCC + links) to services.email_service

Call render_issue_like_page(...) from:
- pages/2_Issuance.py
- pages/3_Reissuance.py
with different SQL WHERE + flags.
"""

import os, re, datetime, html, unicodedata
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd
import streamlit as st
from sqlalchemy import text

from dotenv import load_dotenv
from utils.db import get_engine
from utils.json_utils import to_jsonable
from utils.auth_sidebar import render_auth_in_sidebar, require_auth
from utils.styling import inject_global_styles, inject_sidebar_styles

# NEW: services & config
from services.qr_service import build_preview_url, regenerate_and_upload
from services.s3_service import delete_key as s3_delete_key, get_bytes as s3_get_bytes
from services.email_service import send_issue_or_reissue
from utils.session_cache import get_qr_bytes, put_qr_bytes
from config import EVENT_NAME, S3_PREFIX

# ---------- tiny helpers ----------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _clean(s: str) -> str:
    if s is None: return ""
    s = str(s).replace("\xa0", " ")
    return unicodedata.normalize("NFC", s)

def _clean_field(val: Any) -> str:
        if val is None:
            return ""
        s = str(val).strip()
        if s.lower() in {"nan", "none", "null"}:
            return ""
        return s

def _truncate_middle(s: str, max_len: int = 36) -> str:
    s = str(s or "")
    if len(s) <= max_len: return s
    keep = max_len - 3
    left = keep // 2
    right = keep - left
    return f"{s[:left]}...{s[-right:]}"

def _time_ago(dt) -> str:
    if not dt: return ""
    try: dt = pd.to_datetime(dt)
    except Exception: return ""
    now = pd.Timestamp.now(tz=getattr(dt, "tz", None))
    delta = now - pd.Timestamp(dt)
    secs = int(delta.total_seconds())
    if secs <  60: return f"{secs}s ago"
    mins = secs // 60
    if mins <  60: return f"{mins}m ago"
    hrs  = mins // 60
    if hrs  < 24: return f"{hrs}h ago"
    days = hrs  // 24
    return f"{days}d ago"

def _coerce_attendees(v, default=1) -> int:
    n = int(pd.to_numeric(v, errors="coerce") or default)
    return max(0, n)

def _with_cache_buster(url: str, ts: int) -> str:
    if not url: return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v={ts}"

def _parse_recipients(raw: str) -> List[str]:
    if not raw: return []
    tokens = re.split(r"[,\n;\s]+", raw)
    emails, seen = [], set()
    for tok in tokens:
        e = tok.strip()
        if e and EMAIL_RE.match(e) and e.lower() not in seen:
            emails.append(e); seen.add(e.lower())
    return emails

# ---------- styles (central so both pages look identical) ----------
def inject_issue_styles():
    st.markdown("""
    <style>
    .block-container { padding-top: 1.2rem; }
    .small-muted { color:#6b7280; font-size:0.85rem; }

    /* Expander & inputs on white with thicker borders */
    div[data-testid="stExpander"]{
      background:#ffffff !important;
      border:2px solid #d1d5db;
      border-radius:12px;
    }
    div[data-testid="stExpander"] div[data-testid="stExpanderContent"]{
      background:#ffffff !important;
      border-radius:0 0 12px 12px;
    }

    div[data-baseweb="input"] > div, div[data-baseweb="base-input"] > div {
      background:#ffffff !important; border:2px solid #cbd5e1 !important; border-radius:10px !important;
    }
    textarea, input, select {
      background:#ffffff !important; border:2px solid #cbd5e1 !important; border-radius:10px !important;
    }
    div[data-baseweb="input"] > div:focus-within, textarea:focus, input:focus, select:focus {
      border-color:#2563eb !important; box-shadow:0 0 0 2px rgba(37,99,235,.15) !important;
    }
    div[data-testid="stNumberInput"] button { border-left:2px solid #cbd5e1 !important; background:#fafafa !important; }

    /* Form labels bolder & slightly larger */
    div[data-testid="stExpander"] label { font-weight:700 !important; font-size:1.05rem !important; }

    /* QR detail card */
    .qr-card { border:2px solid #d1d5db; border-radius:14px; padding:14px; background:#fff; }

    /* Open in new tab link (right, tight to QR) */
    .qr-link { display:inline-block; margin:0; font-weight:600; }

    /* Badges */
    .badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:0.75rem; margin-right:6px; border:1px solid #e5e7eb; }
    .badge-green { background:#ecfdf5; border-color:#a7f3d0; }
    .badge-amber { background:#fffbeb; border-color:#fcd34d; }
    </style>
    """, unsafe_allow_html=True)

# ---------- core renderer ----------
def render_issue_like_page(
    *,
    page_title: str,
    header_title: str,
    select_sql: str,
    after_send_update_sql: str,
    send_button_label: str = "📩 Send QR",
    event_name: str = EVENT_NAME,
    s3_prefix: str = S3_PREFIX,
    is_reissue: bool = False,   # <— signals email copy to ask user to use NEW QR
):
    # Setup
    load_dotenv(dotenv_path=Path(__file__).parent / ".env")
    st.set_page_config(page_title=page_title, layout="wide")
    inject_global_styles()
    inject_sidebar_styles()
    inject_issue_styles()
    render_auth_in_sidebar()
    require_auth()
    engine = get_engine()

    st.title(page_title)

    # Post-action toast (persisted across reruns)
    toast = st.session_state.pop("issuance_toast", None)
    if toast:
        msg, level = toast
        getattr(st, level if level in {"success","warning","info","error"} else "info")(msg)

    # Header band
    st.markdown(f"""
    <div style="background:#800000; padding:0.75rem 1rem; border-radius:8px; margin: 0 0 1rem 0;">
      <h3 style="color:#FFFBEA; margin:0;">{header_title}</h3>
    </div>
    """, unsafe_allow_html=True)

    # Fetch rows
    with engine.connect() as conn:
        df_list = pd.read_sql(text(select_sql), conn)

    if df_list.empty:
        st.success("✅ All caught up.")
        st.stop()

    # Selector (Prev / centered Pick a record / Next)
    st.markdown("### Select a record to review & issue")
    dfx = df_list.copy()
    dfx["display_name"]  = dfx["username"].fillna("(no name)")
    dfx["display_email"] = dfx["email"].fillna("(no email)")
    dfx["display_file"]  = dfx["qr_code_filename"].fillna("(no file)").map(_truncate_middle)
    dfx["age"] = [
        _time_ago(r["last_updated_at"] or r.get("qr_generated_at") or r.get("qr_sent_at"))
        for _, r in dfx.iterrows()
    ]

    def _label(row) -> str:
        return f"{row['display_name']} · {row['display_email']}  —  {row['display_file']}  ·  {row['age']}"

    options = dfx.index.tolist()
    labels  = [_label(row) for _, row in dfx.iterrows()]

    # Stable mapping (avoid labels[options.index(i)])
    label_by_option: Dict[int, str] = {opt: lbl for opt, lbl in zip(options, labels)}

    if "issuance_pos" not in st.session_state:
        st.session_state["issuance_pos"] = 0
    current_pos = min(st.session_state["issuance_pos"], len(options)-1)

    col_prev, col_sel, col_next = st.columns([1,4,1])
    with col_prev:
        st.button(
            "◀ Prev", use_container_width=True, disabled=(len(options)<=1),
            on_click=lambda: (st.session_state.update(issuance_pos=(current_pos-1)%len(options)), st.rerun())
        )
    with col_sel:
        st.markdown('<div style="text-align:center; font-weight:700; margin-bottom:0.25rem;">Pick a record</div>', unsafe_allow_html=True)
        selected_idx = st.selectbox(
            "Issuance selection",
            options=options,
            format_func=lambda opt: label_by_option.get(opt, str(opt)),
            index=current_pos,
            key="issuance_select",
            label_visibility="collapsed",
        )
    selected_pos = options.index(selected_idx)
    if selected_pos != st.session_state["issuance_pos"]:
        st.session_state["issuance_pos"] = selected_pos
    with col_next:
        st.button(
            "Next ▶", use_container_width=True, disabled=(len(options)<=1),
            on_click=lambda: (st.session_state.update(issuance_pos=(selected_pos+1)%len(options)), st.rerun())
        )

    selected_txn = str(df_list.loc[selected_idx, "transaction_id"])

    # Reload selected row (fresh)
    with engine.connect() as conn:
        selected = conn.execute(
            text("SELECT * FROM event_payment WHERE transaction_id = :txn LIMIT 1"),
            {"txn": selected_txn}
        ).mappings().first()
    if not selected:
        st.error("Could not re-load selected record from DB.")
        st.stop()

    # Prefills
    name_val    = _clean_field(selected.get("username"))
    email_val   = _clean_field(selected.get("email"))
    phone       = _clean_field(selected.get("phone"))
    address     = _clean_field(selected.get("address"))
    paid_for    = _clean_field(selected.get("paid_for"))
    remarks     = _clean_field(selected.get("remarks"))
    amount      = float(selected.get("amount") or 0.0)
    membership  = bool(selected.get("membership_paid") or False)
    earlybird   = bool(selected.get("early_bird_applied") or False)
    num_att_val = _coerce_attendees(selected.get("number_of_attendees"), default=1)
    pay_date    = selected.get("payment_date")
    if isinstance(pay_date, datetime.datetime):
        pay_date = pay_date.date()

    # Cache-buster
    _updated_at = selected.get("last_updated_at") or selected.get("qr_generated_at") or selected.get("qr_sent_at")
    try:
        _updated_ts = int(pd.Timestamp(_updated_at).timestamp()) if _updated_at else int(pd.Timestamp.utcnow().timestamp())
    except Exception:
        _updated_ts = int(pd.Timestamp.utcnow().timestamp())

    # Layout: form (left) + preview (right)
    left, right = st.columns([1,1])

    with left:
        with st.expander("✏️ Edit details (optional)", expanded=True):
            with st.form("issue_form", clear_on_submit=False):
                c0a, c0b = st.columns([1,1])
                with c0a: membership_in = st.checkbox("Membership Paid", value=membership)
                with c0b: earlybird_in  = st.checkbox("Early Bird Applied", value=earlybird)

                c1, c2 = st.columns(2)
                with c1:
                    st.text_input("Name", value=name_val, disabled=True)
                    email_in = st.text_input("Email(s) — comma/semicolon sep.", value=email_val)
                    phone_in = st.text_input("Phone", value=phone)
                with c2:
                    st.date_input("Payment Date", value=pay_date or datetime.date.today(), disabled=True)
                    st.number_input("Amount ($)", value=amount, step=0.01, min_value=0.0, disabled=True)

                c3, c4 = st.columns([1,1])
                with c3: paid_for_in = st.text_input("Paid For", value=paid_for)
                with c4:
                    attendees_in = st.number_input(
                        "Number of Attendees",
                        value=num_att_val, min_value=0, step=1,
                        help="⚠️ Not included in QR payload (internal use only)",
                    )

                address_in = st.text_input("Address", value=address)
                remarks_in = st.text_area(
                    "Remarks", value=remarks, height=80,
                    help="⚠️ Not included in QR payload (internal use only)",
                )

                parsed_preview = _parse_recipients(email_in)
                st.caption("Will send to: " + (", ".join(parsed_preview) if parsed_preview else "(none parsed yet)"))
                save_btn = st.form_submit_button("💾 Save changes (no regen)")

            if save_btn:
                with get_engine().begin() as conn:
                    conn.execute(text("""
                        UPDATE event_payment
                        SET email = :email,
                            paid_for = :paid_for,
                            remarks = :remarks,
                            phone = :phone,
                            address = :address,
                            membership_paid = :membership_paid,
                            early_bird_applied = :early_bird_applied,
                            number_of_attendees = :num_att,
                            last_updated_at = :now
                        WHERE transaction_id = :txn
                    """), {
                        "email": email_in.strip(),
                        "paid_for": paid_for_in.strip(),
                        "remarks": remarks_in.strip(),
                        "phone": phone_in.strip(),
                        "address": address_in.strip(),
                        "membership_paid": bool(membership_in),
                        "early_bird_applied": bool(earlybird_in),
                        "num_att": _coerce_attendees(attendees_in),
                        "now": datetime.datetime.now(),
                        "txn": selected_txn
                    })
                st.success("✅ Saved changes.")
                st.button("🔄 Refresh", on_click=lambda: st.rerun())

    with right:
        # Header row: title + right-aligned open link
        qr_url_from_db = selected.get("qr_s3_url") or ""
        qr_filename    = selected.get("qr_code_filename") or ""
        attendees_display = _coerce_attendees(selected.get("number_of_attendees"), 1)
        display_url = _with_cache_buster(qr_url_from_db, _updated_ts) if qr_url_from_db else None

        hl, hr = st.columns([3,1])
        with hl: st.markdown("#### QR Preview")
        with hr:
            if display_url:
                st.markdown(
                    f'<div style="text-align:right;"><a class="qr-link" href="{display_url}" target="_blank" rel="noopener">Open in new tab</a></div>',
                    unsafe_allow_html=True
                )

        if display_url:
            st.image(display_url, use_container_width=False)
        else:
            # build a temporary preview QR locally (not uploaded)
            tmp_preview_url = build_preview_url(dict(selected), event_name=event_name)
            tmp_name = f"preview_{selected_txn}.png"
            from utils.qr_s3_utils import generate_qr_image  # local-only helper
            local_path = generate_qr_image(tmp_preview_url, tmp_name, local_folder="qr_preview")
            st.warning("No S3 URL found; showing a temporary preview.")
            st.image(local_path, use_container_width=False)

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        badges = []
        if bool(selected.get("membership_paid")): badges.append('<span class="badge badge-green">Member</span>')
        if bool(selected.get("early_bird_applied")): badges.append('<span class="badge badge-amber">Early Bird</span>')
        badges_html = " ".join(badges) if badges else ""
        st.markdown(f"""
            <div class="qr-card">
              <div>
                <div><strong>{html.escape(name_val)}</strong></div>
                <div class="small-muted">{html.escape(email_val)} · Attendees: {attendees_display}</div>
                <div class="small-muted">File: {html.escape(qr_filename or '(none)')}</div>
                <div style="margin-top:6px;">{badges_html}</div>
              </div>
            </div>
        """, unsafe_allow_html=True)

    # Actions
    a1, a2, a3 = st.columns([1,1,2])

    # --- Regenerate & Upload via service ---
    with a1:
        if st.button("♻️ Regenerate QR"):
            try:
                with st.spinner("Regenerating QR..."):
                    # fresh read
                    with engine.connect() as conn:
                        fresh = conn.execute(
                            text("SELECT * FROM event_payment WHERE transaction_id = :txn"),
                            {"txn": selected_txn}
                        ).mappings().first()
                    if not fresh:
                        st.error("Record vanished during regen."); st.stop()

                    s3_url, filename, qr_bytes, old_key = regenerate_and_upload(
                        dict(fresh), event_name=event_name
                    )

                    # ---- Update DB (NO qr_sent/qr_sent_at and NO qr_reissued_* on regen) ----
                    now = datetime.datetime.now()
                    with engine.begin() as conn:
                        conn.execute(text("""
                            UPDATE event_payment
                            SET qr_generated      = TRUE,
                                qr_generated_at   = :now,
                                qr_code_filename  = :fname,
                                qr_s3_url         = :s3,
                                last_updated_at   = :now
                            WHERE transaction_id  = :txn
                        """), {"now": now, "fname": filename, "s3": s3_url, "txn": selected_txn})

                    # Delete prior object (best-effort)
                    try:
                        if old_key and old_key != f"{s3_prefix}{filename}":
                            s3_delete_key(old_key)
                    except Exception as del_err:
                        st.info(f"ℹ️ Old QR not deleted (will be cleaned later): {del_err}")

                    # cache bytes for immediate email send
                    put_qr_bytes(selected_txn, qr_bytes)

                    st.session_state["issuance_toast"] = ("✅ QR regenerated and uploaded.", "success")
                    st.rerun()
            except Exception as e:
                st.error(f"Regen failed: {e}")

    # --- Send via service (inline QR, BCC, links) ---
    with a2:
        if st.button(send_button_label):
            try:
                with st.spinner("Sending email..."):
                    # Reload current row
                    with engine.connect() as conn:
                        rec = conn.execute(text("""
                            SELECT username, email, qr_s3_url, qr_code_filename, number_of_attendees, transaction_id, paid_for, remarks, phone, address, membership_paid, early_bird_applied, payment_date, amount
                            FROM event_payment WHERE transaction_id = :txn LIMIT 1
                        """), {"txn": selected_txn}).mappings().first()
                    if not rec:
                        st.error("Record not found."); st.stop()

                    recipients = _parse_recipients((rec.get("email") or "").strip())
                    if not recipients:
                        st.error("No valid email addresses found. Separate with commas, semicolons, spaces, or newlines.")
                        st.stop()

                    username = _clean(rec.get("username") or "Attendee")
                    s3_url   = (rec.get("qr_s3_url") or "").strip()
                    if not s3_url.startswith(("http://","https://")):
                        st.error("No valid QR URL found for this record. Please regenerate first.")
                        st.stop()

                    # Get QR bytes: prefer cached (from regeneration); else fetch from S3 by key
                    qr_bytes = get_qr_bytes(selected_txn)
                    if not qr_bytes:
                        fname = rec.get("qr_code_filename") or ""
                        if not fname:
                            st.error("QR image not available to embed. Please Regenerate before sending.")
                            st.stop()
                        key = f"{s3_prefix}{fname}"
                        qr_bytes = s3_get_bytes(key)
                        put_qr_bytes(selected_txn, qr_bytes)  # cache for subsequent sends in the same session

                    # The preview URL is what the QR encodes (page where they can view info)
                    # Build from the freshly reloaded row to avoid staleness; also carries ?tx=<transaction_id>
                    preview_url = build_preview_url(dict(rec), event_name=event_name)

                    # send (service handles inline image, default BCC, reissue notice, link copy)
                    successes = send_issue_or_reissue(
                        recipients=recipients,
                        username=username,
                        qr_bytes=qr_bytes,
                        s3_url=s3_url,
                        preview_url=preview_url,
                        is_reissue=is_reissue,
                    )

                    # Persist state in DB
                    if successes:
                        now = datetime.datetime.now()
                        with engine.begin() as conn:
                            conn.execute(text(after_send_update_sql), {"now": now, "txn": selected_txn})

                    # Toasts
                    if successes:
                        st.session_state["issuance_toast"] = (f"✅ Email sent to: {', '.join(successes)}", "success")
                    else:
                        st.session_state["issuance_toast"] = ("❌ Send failed: No recipients accepted.", "error")

                    st.rerun()
            except Exception as e:
                st.error(f"Send failed: {e}")

    with a3:
        st.info("Use ◀ Prev / Next ▶ to move through records.")
