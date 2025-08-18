# pages/5_QR_Viewer.py
import base64, json, math, re
from typing import Any, Dict
import streamlit as st
from utils.styling import inject_global_styles, inject_sidebar_styles

st.set_page_config(page_title="QR Data Viewer", layout="centered")

# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────
def _get1(q, k):
    v = q.get(k)
    if isinstance(v, list):
        return v[0] if v else None
    return v

def _base64url_to_utf8(b64: str) -> str:
    # robust base64url decode (handle missing padding & urlsafe alphabet)
    b64_fixed = b64.replace("-", "+").replace("_", "/").replace(" ", "+")
    pad = (-len(b64_fixed)) % 4
    if pad: b64_fixed += "=" * pad
    return base64.b64decode(b64_fixed).decode("utf-8", errors="strict")

def _strip_hidden(obj: Any) -> Any:
    # Hide these keys anywhere in the structure
    HIDE = {"transaction_id", "event"}
    if isinstance(obj, dict):
        return {k: _strip_hidden(v) for k, v in obj.items() if k not in HIDE}
    if isinstance(obj, list):
        return [_strip_hidden(x) for x in obj]
    return obj

_LABEL_OVERRIDES = {
    "name": "Name",
    "email": "Email",
    "phone": "Phone",
    "paid_for": "Paid For",
    "amount": "Amount",
    "payment_date": "Payment Date",
    "membership_paid": "Membership Paid",
    "early_bird_applied": "Early Bird Applied",
}
def _pretty_label(key: str) -> str:
    return _LABEL_OVERRIDES.get(key, key.replace("_", " ").title())

def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _to_display(v, key: str | None = None) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    if isinstance(v, str) and v.strip().lower() in {"nan", "none", "null"}:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, str) and v.strip().lower() in {"true", "false"}:
        return "Yes" if v.strip().lower() == "true" else "No"
    if key and key.lower() in {"phone", "phone_number", "mobile"}:
        return re.sub(r"\D+", "", str(v))
    return str(v)

def _render_table(obj: Any) -> str:
    if isinstance(obj, dict):
        rows = []
        for k, v in obj.items():
            label = _pretty_label(str(k))
            cell_html = _render_table(v) if isinstance(v, (dict, list)) \
                        else _escape_html(_to_display(v, key=str(k)))
            rows.append(f"<tr><th>{_escape_html(label)}</th><td>{cell_html}</td></tr>")
        return f"<table class='decoded-table'>{''.join(rows)}</table>"
    elif isinstance(obj, list):
        rows = []
        for i, v in enumerate(obj):
            cell_html = _render_table(v) if isinstance(v, (dict, list)) \
                        else _escape_html(_to_display(v))
            rows.append(f"<tr><th>[{i}]</th><td>{cell_html}</td></tr>")
        return f"<table class='decoded-table'>{''.join(rows)}</table>"
    else:
        return _escape_html(_to_display(obj))

def _compose_title(event_name: str) -> str:
    e = (event_name or "").strip()
    return e if e else "QR Data Viewer"

# ───────────────────────────────────────────────
# Global NSSNT look & feel
# ───────────────────────────────────────────────
inject_global_styles()
inject_sidebar_styles()   # safe even if sidebar is hidden

st.markdown("""
<style>
:root { --cream:#FFFEE0; --gold:#FFD900; --orange:#F4A300; --maroon:#800000; }
/* Hide chrome */
[data-testid="stSidebar"], [data-testid="stSidebarNav"],
[data-testid="stHeader"], [data-testid="stToolbar"],
[data-testid="stDecoration"], [data-testid="stStatusWidget"],
[data-testid="stMainMenu"], #MainMenu, footer, header { display:none !important; }
.block-container { padding-top:.75rem !important; padding-bottom:1.25rem !important; }
.stApp { background-color:#FFFFE5 !important; }
/* Kasavu bands */
.stApp::before, .stApp::after { content:""; position:fixed; left:0; right:0; height:18px; z-index:999; }
.stApp::before { top:0; background:linear-gradient(to bottom,var(--gold) 0%,var(--gold) 33%,var(--orange) 33%,var(--orange) 66%,var(--maroon) 66%,var(--maroon) 100%); box-shadow:0 1px 0 rgba(0,0,0,0.08); }
.stApp::after { bottom:0; background:linear-gradient(to top,var(--gold) 0%,var(--gold) 33%,var(--orange) 33%,var(--orange) 66%,var(--maroon) 66%,var(--maroon) 100%); box-shadow:0 -1px 0 rgba(0,0,0,0.08); }
/* Card */
.qr-card { position:relative; margin:20px auto; max-width:1000px; width:96%; padding:20px 22px 26px; background:#FFFCF7; border:1px solid #F1E5D1; border-radius:16px; box-shadow:0 6px 18px rgba(128,0,0,0.06); }
.qr-card::before { content:""; position:absolute; inset:0 0 auto 0; height:4px; background:linear-gradient(90deg,#800000,#D72638,#F4D06F); opacity:.9; border-top-left-radius:16px; border-top-right-radius:16px; }
.qr-logo { text-align:center; margin:6px 0 6px; }
.qr-title { font-size:2.1rem; font-weight:900; color:#1f2937; text-align:center; margin:.25rem 0 .15rem; }
.qr-sub { font-size:1.05rem; color:#6b7280; text-align:center; margin-bottom:.9rem; }
/* Table */
.decoded-table { width:100%; max-width:720px; margin:0 auto; border-collapse:collapse; margin-top:.25rem; }
.decoded-table th, .decoded-table td { border:1px solid #E9E2D6; padding:10px 12px; vertical-align:top; word-break:break-word; background:#FFFEFA; color:#111827; font-size:.99rem; }
.decoded-table th { background:#FCFCE8; font-weight:700; color:#5A0000; width:240px; }
.decoded-table tr:nth-child(even) td { background:#FFFDF3; }
.meta-box { margin-top:16px; padding:12px 14px; background:#FFF8E1; border:1px solid #F4D06F; border-radius:12px; }
.meta-title { font-weight:700; color:#7A0000; margin-bottom:6px; }
</style>
""", unsafe_allow_html=True)

logo_html = """
<div class="qr-logo">
  <img src="https://sumanair.github.io/scanner/assets/nssnt_logo.png" alt="NSS North Texas Logo" width="108">
</div>
"""

# ───────────────────────────────────────────────
# Retrieve & decode data (URL first, then session)
# ───────────────────────────────────────────────
raw_b64 = _get1(st.query_params, "data") or st.session_state.get("_qr_data")

st.markdown("<div class='qr-card'>", unsafe_allow_html=True)

if not raw_b64:
    st.markdown(logo_html, unsafe_allow_html=True)
    st.markdown("<div class='qr-title'>QR Data Viewer</div>", unsafe_allow_html=True)
    st.markdown("<div class='qr-sub'>No <code>data</code> parameter found in the URL.</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

try:
    raw_json_str = _base64url_to_utf8(raw_b64)
    parsed: Dict[str, Any] = json.loads(raw_json_str)
except Exception as e:
    st.markdown(logo_html, unsafe_allow_html=True)
    st.markdown("<div class='qr-title'>QR Data Viewer</div>", unsafe_allow_html=True)
    st.error(f"Error decoding or parsing the base64-encoded payload: {e}")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

main = parsed.get("data", parsed)  # support either {"data": {...}} or {...}
event_name = (main.get("event") or "").strip()
main_sanitized = _strip_hidden(main)

# ───────────────────────────────────────────────
# Render
# ───────────────────────────────────────────────
st.markdown(logo_html, unsafe_allow_html=True)
st.markdown(f"<div class='qr-title'>{_compose_title(event_name)}</div>", unsafe_allow_html=True)
st.markdown("<div class='qr-sub'>Reservation Confirmation</div>", unsafe_allow_html=True)

st.markdown(_render_table(main_sanitized), unsafe_allow_html=True)

# Optional: if you also embed metadata, show it
meta = parsed.get("metadata_from_qrmaker", {})
if meta:
    st.markdown(
        f"<div class='meta-box'><div class='meta-title'>Metadata</div>{_render_table(meta)}</div>",
        unsafe_allow_html=True
    )

st.markdown("</div>", unsafe_allow_html=True)

# Clear after use so later visits without params don’t reuse stale data
st.session_state.pop("_qr_data", None)
