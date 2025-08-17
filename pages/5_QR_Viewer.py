# pages/5_QR_Viewer.py
import base64
import json
from typing import Any, Dict
import streamlit as st
import math, re

st.set_page_config(page_title="QR Data Viewer", layout="centered")

# ───────────────────────────────────────────────
# Hide sidebar/header/toolbar + tighten top padding
# ───────────────────────────────────────────────
st.markdown("""
<style>
  /* Hide sidebar & nav */
  [data-testid="stSidebar"], [data-testid="stSidebarNav"] { display: none !important; }

  /* Hide Streamlit top white bar / main menu / toolbar */
  [data-testid="stHeader"], 
  [data-testid="stToolbar"], 
  [data-testid="stDecoration"], 
  [data-testid="stStatusWidget"], 
  [data-testid="stMainMenu"], 
  #MainMenu, 
  footer, 
  header {display: none !important;}

  /* Pull content up (remove gap) */
  .block-container { padding-top: 0.5rem !important; }


  /* App background */
  .stApp { background: linear-gradient(to bottom right, #fffdf5, #ffffff); }

  /* Main card */
  .qr-container {
      margin: 24px auto 20px auto;
      max-width: 900px;
      width: 95%;
      padding: 30px;
      background-color: #ffffff;
      box-shadow: 0 8px 24px rgba(0,0,0,0.08);
      border-radius: 16px;
  }

  .qr-title-main {
      font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, "Helvetica Neue", Arial;
      font-size: 28px;
      color: #b91c1c;  /* NSSNT deep red */
      text-align: center;
      font-weight: 700;
      margin-bottom: 6px;
  }
  .qr-title-confirm {
      font-size: 20px;
      text-align: center;
      font-weight: 700;
      color: #444;
      margin-bottom: 20px;
  }

  .decoded-table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      font-family: 'Courier New', monospace;
  }
  .decoded-table th, .decoded-table td {
      border: 1px solid #e0e0e0;
      padding: 10px;
      vertical-align: top;
      word-break: break-word;
  }
  .decoded-table th {
      background-color: #FCFCE8; /* light cream */
      font-weight: 600;
      text-align: left;
      width: 240px;
  }
  .decoded-table tr:nth-child(even) td {
      background-color: #fafafa;
  }

  .meta-box {
      margin-top: 24px;
      padding: 16px 18px;
      background-color: #fff8e1;
      border: 1px solid #f4d06f;
      border-radius: 10px;
  }
  .meta-title {
      font-weight: 600;
      color: #7a5d00;
      margin-bottom: 8px;
  }
  .logo-wrap {
      text-align: center;
      margin-bottom: 10px;
  }
</style>
""", unsafe_allow_html=True)

# ───────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────
def _base64url_to_utf8(b64: str) -> str:
    b64_fixed = b64.replace('-', '+').replace('_', '/')
    pad = (-len(b64_fixed)) % 4
    if pad: b64_fixed += '=' * pad
    return base64.b64decode(b64_fixed).decode('utf-8', errors='strict')

def _strip_transaction_ids(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_transaction_ids(v) for k, v in obj.items()
                if k not in ("transaction_id", "event")}
    if isinstance(obj, list):
        return [_strip_transaction_ids(x) for x in obj]
    return obj

_LABEL_OVERRIDES = {
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
    """Normalize values for display: hide NaN/None/null-ish, clean phone."""
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    if isinstance(v, str) and v.strip().lower() in {"nan", "none", "null"}:
        return ""
    if key and key.lower() in {"phone", "phone_number", "mobile"}:
        s = re.sub(r"\D+", "", str(v))  # keep digits only
        return s  # empty string if nothing left
    return str(v)

def _render_table(obj: Any) -> str:
    if isinstance(obj, dict):
        rows = []
        for k, v in obj.items():
            label = _pretty_label(str(k))
            if isinstance(v, (dict, list)):
                cell_html = _render_table(v)
            else:
                cell_html = _escape_html(_to_display(v, key=str(k)))
            rows.append(f"<tr><th>{_escape_html(label)}</th><td>{cell_html}</td></tr>")
        return f"<table class='decoded-table'>{''.join(rows)}</table>"
    elif isinstance(obj, list):
        rows = []
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                cell_html = _render_table(v)
            else:
                cell_html = _escape_html(_to_display(v))
            rows.append(f"<tr><th>[{i}]</th><td>{cell_html}</td></tr>")
        return f"<table class='decoded-table'>{''.join(rows)}</table>"
    else:
        return _escape_html(_to_display(obj))

def _compose_title(event_name: str) -> str:
    """Ensure title starts with 'NSS NT ' exactly once."""
    e = (event_name or "").strip()
    return e if e.lower().startswith("nss nt") else f"NSS NT {e}"

# ───────────────────────────────────────────────
# Parse ?data=
# ───────────────────────────────────────────────
qp = st.query_params
data_param = qp.get("data")

st.markdown("<div class='qr-container'>", unsafe_allow_html=True)

# Logo + generic title when no payload
if not data_param:
    st.markdown("""
    <div class="logo-wrap">
        <img src="https://sumanair.github.io/scanner/assets/nssnt_logo.png" alt="NSS North Texas Logo" width="120">
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div class='qr-title-main'>QR Data Viewer</div>", unsafe_allow_html=True)
    st.info("No `data` parameter found in the URL.")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# Decode & parse
try:
    raw_json_str = _base64url_to_utf8(data_param)
    parsed: Dict[str, Any] = json.loads(raw_json_str)
except Exception as e:
    st.markdown("""
    <div class="logo-wrap">
        <img src="https://sumanair.github.io/scanner/assets/nssnt_logo.png" alt="NSS North Texas Logo" width="120">
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div class='qr-title-main'>QR Data Viewer</div>", unsafe_allow_html=True)
    st.error(f"Error decoding or parsing the base64-encoded payload: {e}")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

main = parsed.get("data", {})
meta = parsed.get("metadata_from_qrmaker", {})
main_sanitized = _strip_transaction_ids(main)

# ───────────────────────────────────────────────
# Heading (Logo → Title → Subtitle)
# ───────────────────────────────────────────────
event_name = main.get("event", "")
st.markdown("""
<div class="logo-wrap">
    <img src="https://sumanair.github.io/scanner/assets/nssnt_logo.png" alt="NSS North Texas Logo" width="120">
</div>
""", unsafe_allow_html=True)

if isinstance(event_name, str) and event_name.strip():
    st.markdown(f"<div class='qr-title-main'>{_compose_title(event_name)}</div>", unsafe_allow_html=True)
    st.markdown("<div class='qr-title-confirm'>Reservation Confirmation</div>", unsafe_allow_html=True)
else:
    st.markdown("<div class='qr-title-main'>QR Data Viewer</div>", unsafe_allow_html=True)

# ───────────────────────────────────────────────
# Main table + optional metadata
# ───────────────────────────────────────────────
st.markdown(_render_table(main_sanitized), unsafe_allow_html=True)

if meta:
    st.markdown(
        f"<div class='meta-box'><div class='meta-title'>Metadata</div>{_render_table(meta)}</div>",
        unsafe_allow_html=True
    )

st.markdown("</div>", unsafe_allow_html=True)
