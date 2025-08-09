# pages/4_Verifier.py
import os
import re
import json
import base64
import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse, parse_qs, unquote

import cv2
import numpy as np
import pandas as pd
import streamlit as st
from sqlalchemy import text
from dotenv import load_dotenv

from utils.db import get_engine
from utils.styling import inject_global_styles

# ── optional scanners / components ─────────────────────────────────────────────
_HTML5_CUSTOM = True
try:
    import streamlit.components.v1 as components
    from streamlit_js_eval import streamlit_js_eval  # pip install streamlit-js-eval
except Exception:
    _HTML5_CUSTOM = False

_SCANNER_AVAILABLE = True
try:
    from streamlit_qrcode_scanner import qrcode_scanner  # pip install streamlit-qrcode-scanner
except Exception:
    _SCANNER_AVAILABLE = False

# ──────────────────────────────────────────────────────────────
# Page setup
# ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Verifier • Attendance Check‑In", layout="wide")
inject_global_styles()

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

LOGO = "NSS-Logo-Transparent-2-300x300.png"
if Path(LOGO).exists():
    with st.sidebar:
        st.image(LOGO, use_container_width=True)

st.title("🛂 Attendance Check‑In (Verifier)")

engine = get_engine()

# ──────────────────────────────────────────────────────────────
# Role guard (allow verifier or admin)
# ──────────────────────────────────────────────────────────────
if not st.session_state.get("authenticated", False):
    st.error("Please log in to access this page.")
    st.stop()

VERIFIER_USERNAME = (os.getenv("VERIFIER_USERNAME") or "").strip().lower()
VERIFIER_NAME     = (os.getenv("VERIFIER_NAME") or "").strip().lower()
ADMIN_USERNAME    = (os.getenv("ADMIN_USERNAME") or "").strip().lower()
ADMIN_NAME        = (os.getenv("ADMIN_NAME") or "").strip().lower()

current_username = str(
    st.session_state.get("username")
    or st.session_state.get("user")
    or st.session_state.get("email")
    or ""
).strip().lower()
current_display_name = str(st.session_state.get("name") or "").strip().lower()

if (st.session_state.get("role") or "").lower() not in {"admin", "verifier"}:
    is_verifier = any([
        current_username and current_username == VERIFIER_USERNAME,
        current_display_name and current_display_name == VERIFIER_NAME,
    ])
    is_admin = any([
        ADMIN_USERNAME and current_username == ADMIN_USERNAME,
        ADMIN_NAME and current_display_name == ADMIN_NAME,
    ])
    st.session_state.role = "admin" if is_admin else ("verifier" if is_verifier else "user")

role = (st.session_state.get("role") or "").lower()
if role not in {"verifier", "admin"}:
    st.error("You do not have verifier access.")
    with st.expander("Troubleshooter"):
        st.write({
            "session.username": st.session_state.get("username"),
            "session.name": st.session_state.get("name"),
            "session.email": st.session_state.get("email"),
            "session.role": st.session_state.get("role"),
            "VERIFIER_USERNAME": VERIFIER_USERNAME,
            "VERIFIER_NAME": VERIFIER_NAME,
            "ADMIN_USERNAME": ADMIN_USERNAME,
            "ADMIN_NAME": ADMIN_NAME,
        })
    st.stop()

# ──────────────────────────────────────────────────────────────
# Helpers: parsing & DB
# ──────────────────────────────────────────────────────────────
def _coerce_int(v, default=0) -> int:
    try:
        n = int(pd.to_numeric(v, errors="coerce") or default)
        return max(0, n)
    except Exception:
        return default

def _b64_try(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s:
        return None
    s2 = s.replace("-", "+").replace("_", "/")
    pad = "=" * ((4 - len(s2) % 4) % 4)
    try:
        return base64.b64decode(s2 + pad).decode("utf-8", errors="ignore")
    except Exception:
        return None

def _extract_txn_from_json_text(txt: str) -> Optional[str]:
    try:
        data = json.loads(txt)
        for k in ("transaction_id", "txn", "txid"):
            if isinstance(data, dict) and data.get(k):
                return str(data[k])
    except Exception:
        pass
    return None

def _extract_txn_from_url(url: str) -> Optional[str]:
    try:
        u = urlparse(url)
    except Exception:
        return None
    q = parse_qs(u.query or "")

    for k in ("transaction_id", "txn", "txid"):
        if k in q and q[k]:
            return q[k][0]

    for k in ("data", "payload", "qr", "p"):
        if k in q and q[k]:
            decoded = _b64_try(unquote(q[k][0]))
            if decoded:
                tx = _extract_txn_from_json_text(decoded)
                if tx:
                    return tx

    last = (u.path or "").split("/")[-1]
    if last:
        decoded = _b64_try(last)
        if decoded:
            tx = _extract_txn_from_json_text(decoded)
            if tx:
                return tx
    return None

def parse_scanned_text_to_txn(text: str) -> Optional[str]:
    if not text:
        return None
    s = text.strip()
    if s.startswith("{") and s.endswith("}"):
        tx = _extract_txn_from_json_text(s);  return tx
    if s.startswith(("http://", "https://")):
        tx = _extract_txn_from_url(s);        return tx
    decoded = _b64_try(s)
    if decoded:
        tx = _extract_txn_from_json_text(decoded);  return tx
    if re.fullmatch(r"[A-Za-z0-9\-_=]{6,}", s):
        return s
    return None

def decode_qr_from_image_bytes(buf: bytes) -> List[str]:
    npbuf = np.frombuffer(buf, np.uint8)
    img = cv2.imdecode(npbuf, cv2.IMREAD_COLOR)
    if img is None:
        return []
    det = cv2.QRCodeDetector()
    try:
        ok, decoded, _, _ = det.detectAndDecodeMulti(img)
        if ok and decoded:
            return [d for d in decoded if d]
    except Exception:
        pass
    try:
        d_single, _ = det.detectAndDecode(img)
        if d_single:
            return [d_single]
    except Exception:
        pass
    return []

def fetch_attendance_row(txn_id: str) -> Optional[dict]:
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT transaction_id, username, number_of_attendees, number_checked_in
                FROM event_payment
                WHERE transaction_id = :txn
                LIMIT 1
            """),
            {"txn": txn_id}
        ).mappings().first()
        return dict(row) if row else None

def add_checkins(txn_id: str, add_count: int) -> Tuple[bool, str]:
    if add_count <= 0:
        return False, "Nothing to add."
    with engine.begin() as conn:
        current = conn.execute(
            text("""
                SELECT number_of_attendees, number_checked_in
                FROM event_payment
                WHERE transaction_id = :txn
                FOR UPDATE
            """),
            {"txn": txn_id}
        ).mappings().first()
        if not current:
            return False, "Transaction not found."

        total   = _coerce_int(current["number_of_attendees"], 0)
        checked = _coerce_int(
            current["number_of_attendees"] if current.get("number_checked_in") is None
            else current["number_checked_in"], 0
        )
        remain  = max(0, total - checked)
        if add_count > remain:
            return False, f"Only {remain} attendee(s) remaining. Cannot admit {add_count}."

        conn.execute(
            text("""
                UPDATE event_payment
                SET number_checked_in = number_checked_in + :add,
                    last_updated_at = :now
                WHERE transaction_id = :txn
            """),
            {"add": int(add_count), "txn": txn_id, "now": datetime.datetime.now()}
        )
    return True, f"Checked in {add_count} attendee(s)."

def extract_payload_json(decoded_text: str) -> Optional[dict]:
    if not decoded_text:
        return None
    try:
        if decoded_text.startswith(("http://", "https://")):
            u = urlparse(decoded_text)
            q = parse_qs(u.query or "")
            for k in ("data", "payload", "qr", "p"):
                if k in q and q[k]:
                    decoded = _b64_try(unquote(q[k][0]))
                    if decoded:
                        try:
                            return json.loads(decoded)
                        except Exception:
                            return {"_raw": decoded}
    except Exception:
        pass

    b = _b64_try(decoded_text)
    if b:
        try:
            return json.loads(b)
        except Exception:
            return {"_raw": b}

    if decoded_text.strip().startswith("{") and decoded_text.strip().endswith("}"):
        try:
            return json.loads(decoded_text)
        except Exception:
            pass

    return None

# ──────────────────────────────────────────────────────────────
# Scan / manual input
# ──────────────────────────────────────────────────────────────
left, right = st.columns([1, 1])

with left:
    st.subheader("📹 Live Scan ")

    decoded_text = None
    qr_error = None

    # 1) Primary: custom qr-scanner (using placeholder replacement to avoid f-string brace issues)
    if _HTML5_CUSTOM:
        qrbox_size = 420  # visual width of the video element
        HTML_TEMPLATE = """
<div id="qr-wrap" style="display:flex;flex-direction:column;align-items:center;">
  <div style="width:100%;max-width:__QRBOX__px;">
    <video id="qr-video" muted autoplay playsinline style="
      width:100%;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,.12);"></video>
  </div>
  <div id="status" style="margin-top:8px;color:#444;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial;"></div>
  <div id="result" style="margin-top:8px;max-width:__QRBOX__px;font-family:monospace;"></div>
</div>

<script type="module">
  import QrScanner from 'https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner.min.js';
  QrScanner.WORKER_PATH = 'https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner-worker.min.js';

  const video = document.getElementById('qr-video');
  const status = document.getElementById('status');
  const resultEl = document.getElementById('result');
  // globals for Python polling
  window.qrDecoded = null;
  window.qrError = null;
  

  function renderJsonAsTable(obj) {
    const entries = Object.entries(obj || {})
      .map(([k,v]) => `<tr>
          <th style='text-align:left;padding:4px 6px;border:1px solid #ddd;'>${k}</th>
          <td style='padding:4px 6px;border:1px solid #ddd;'>${
            (v && typeof v === 'object')
              ? `<pre style="white-space:pre-wrap;margin:0">${JSON.stringify(v,null,2)}</pre>`
              : v
          }</td>
        </tr>`)
      .join('');
    return `<table style='width:100%;border-collapse:collapse;margin-top:6px;font-family:monospace'>
              <tbody>${entries}</tbody>
            </table>`;
  }

  function hexToUtf8(hex) {
    const bytes = new Uint8Array((hex || '').match(/.{1,2}/g).map(b => parseInt(b, 16)));
    return new TextDecoder().decode(bytes);
  }

  async function start() {
    status.textContent = "Initializing camera…";

    // rear camera preference
    let deviceId = undefined;
    try {
      const cams = await QrScanner.listCameras(true);
      const rear = cams.find(c => /back|rear|environment/i.test(c.label || ''));
      deviceId = (rear || cams[cams.length-1] || {}).id;
    } catch (e) {}

    const scanner = new QrScanner(
      video,
      (result) => {
        try {
          if (/^https?:\/\/.+\\?.*data=/.test(result)) {
            const url = new URL(result);
            const hexData = url.searchParams.get("data");
            if (hexData) {
              const jsonStr = hexToUtf8(decodeURIComponent(hexData));
              window.qrDecoded = jsonStr;  // raw JSON string to Python
              try {
                const obj = JSON.parse(jsonStr);
                const main = obj.data || obj;
                resultEl.innerHTML = "<b>✅ Decoded Data</b>" + renderJsonAsTable(main);
              } catch (e) {
                resultEl.textContent = "✅ Scanned (non-JSON): " + jsonStr;
              }
            } else {
              window.qrDecoded = result;
              resultEl.textContent = "✅ Scanned URL: " + result;
            }
          } else {
            window.qrDecoded = result;
            resultEl.textContent = "✅ QR Text: " + result;
          }
        } catch (e) {
          window.qrError = "Decode error: " + (e?.message || e);
        } finally {
          scanner.stop();
          status.textContent = "Scan complete.";
        }
      },
      {
        preferredCamera: deviceId ? deviceId : undefined,
        highlightScanRegion: true,
        highlightCodeOutline: true
      }
    );

    try {
      await scanner.start();
      status.textContent = "Point the QR into the frame…";
    } catch (err) {
      window.qrError = err?.message || String(err);
      status.textContent = "Camera access denied or not available.";
    }
  }

  if (!window.__qr_started__) {
    window.__qr_started__ = true;
    start();
  }
</script>
        """.strip()

        html = HTML_TEMPLATE.replace("__QRBOX__", str(qrbox_size))
        components.html(html, height=qrbox_size + 220, scrolling=False)

        decoded_text = streamlit_js_eval(js_expressions="window.qrDecoded || null", key="qr_custom_poll")
        qr_error = streamlit_js_eval(js_expressions="window.qrError || null", key="qr_custom_err")

        if qr_error:
            st.caption(f"Scanner notice: {qr_error}")

    # 2) Fallback: streamlit-qrcode-scanner (small fixed box)
    if not decoded_text and _SCANNER_AVAILABLE:
        st.divider()
        st.caption("Fallback scanner:")
        decoded_text = qrcode_scanner(key="qr_live_scanner")

    # 3) Fallback: snapshot camera
    if not decoded_text:
        st.divider()
        st.caption("If live scan doesn’t work, take a quick snapshot instead.")
        cam_file = st.camera_input("Capture QR snapshot")
        if cam_file is not None:
            found = decode_qr_from_image_bytes(cam_file.getvalue())
            if found:
                decoded_text = found[0]

    # Post-process
    if decoded_text:
        st.success("QR detected!")
        st.code(decoded_text, language="text")
        st.session_state["verifier_raw"] = decoded_text
        st.session_state["verifier_payload_json"] = extract_payload_json(decoded_text)
        tx = parse_scanned_text_to_txn(decoded_text)
        if tx:
            st.session_state["verifier_txn"] = tx
        else:
            st.warning("Couldn’t extract a transaction id from the QR.")
    else:
        st.info("Waiting for scan… On phones, open this page over HTTPS so the camera is allowed.")

with right:
    st.subheader("⌨️ Manual Entry")
    manual = st.text_input(
        "Scan or paste Transaction ID / QR contents",
        value=st.session_state.get("verifier_txn", "")
    )
    if st.button("Use this code"):
        if manual.strip():
            st.session_state["verifier_raw"] = manual.strip()
            st.session_state["verifier_payload_json"] = extract_payload_json(manual.strip())
            st.session_state["verifier_txn"] = parse_scanned_text_to_txn(manual.strip()) or manual.strip()
        else:
            st.session_state.pop("verifier_txn", None)
            st.session_state.pop("verifier_raw", None)
            st.session_state.pop("verifier_payload_json", None)

st.divider()

# ──────────────────────────────────────────────────────────────
# Show decoded payload (pretty)
# ──────────────────────────────────────────────────────────────
with st.expander("📦 Decoded Payload", expanded=True):
    payload = st.session_state.get("verifier_payload_json")
    raw = st.session_state.get("verifier_raw")
    if payload:
        st.json(payload)
    elif raw:
        st.write("No JSON payload found. Raw value:")
        st.code(raw, language="text")
    else:
        st.write("Scan a QR to view its payload.")

# ──────────────────────────────────────────────────────────────
# Attendance look‑up and actions
# ──────────────────────────────────────────────────────────────
txn_id = (st.session_state.get("verifier_txn") or "").strip()
if not txn_id:
    st.info("Scan a QR or paste a code to begin.")
    st.stop()

row = fetch_attendance_row(txn_id)
if not row:
    st.error("Transaction not found. Double‑check the code or scan again.")
    st.stop()

username  = row.get("username") or "(unknown)"
total     = _coerce_int(row.get("number_of_attendees"), 0)
checked   = _coerce_int(row.get("number_of_attendees") if row.get("number_checked_in") is None else row.get("number_checked_in"), 0)
remaining = max(0, total - checked)

st.markdown(f"### 👤 {username}")
c1, c2, c3 = st.columns(3)
c1.metric("Purchased", total)
c2.metric("Checked‑in", checked)
c3.metric("Remaining", remaining)

if remaining == 0:
    st.success("All attendees for this ticket have already checked in. ✅")
    st.stop()

admit = st.number_input(
    "Admit now",
    min_value=1, max_value=remaining, value=1, step=1,
    help="How many to admit for this transaction right now."
)

col_a, col_b = st.columns(2)
with col_a:
    if st.button("✅ Update Attendance"):
        ok, msg = add_checkins(txn_id, int(admit))
        if ok:
            st.success(msg)
            st.rerun()
        else:
            st.warning(msg)

with col_b:
    if st.button(f"➡️ Admit All ({remaining})"):
        ok, msg = add_checkins(txn_id, int(remaining))
        if ok:
            st.success(msg)
            st.rerun()
        else:
            st.warning(msg)

st.caption("Tip: if a QR won’t scan, paste the code into Manual Entry.")
