# pages/4_Verifier.py
import os
import re
import json
import base64
import datetime
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs, unquote

import pandas as pd
import streamlit as st
from sqlalchemy import text
from dotenv import load_dotenv

from utils.db import get_engine
from utils.styling import inject_global_styles

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
# Helpers
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
        return _extract_txn_from_json_text(s)
    if s.startswith(("http://", "https://")):
        return _extract_txn_from_url(s)
    decoded = _b64_try(s)
    if decoded:
        return _extract_txn_from_json_text(decoded)
    if re.fullmatch(r"[A-Za-z0-9\-_=]{6,}", s):
        return s
    return None

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
# Layout
# ──────────────────────────────────────────────────────────────
left, right = st.columns([1, 1])

# ──────────────────────────────────────────────────────────────
# Single, clean HTML5 scanner (QrScanner)
# ──────────────────────────────────────────────────────────────
with left:
    st.subheader("📹 Live Scan")

    decoded_text = None
    qr_error = None

    from streamlit.components.v1 import html as st_html
    from streamlit_js_eval import streamlit_js_eval  # pip install streamlit-js-eval

    qrbox_max = 560  # max width in px; shrinks on phones

    # NB: keep regex literals to simple, valid flags only. No dynamic flags.
    HTML_TEMPLATE = r"""
<style>
  #qr-wrap { display:flex; flex-direction:column; align-items:center; }
  #qr-box  { width:min(92vw, __QRBOX__px); aspect-ratio: 3 / 4; position:relative; }
  #qr-video{ width:100%; height:100%; object-fit:cover; border-radius:12px;
             box-shadow:0 4px 12px rgba(0,0,0,.12); background:#000; }
  .corner{position:absolute;width:18%;height:18%;border:4px solid #f4b000;border-radius:14px;}
  .tl{top:4%;left:4%;border-right:none;border-bottom:none;}
  .tr{top:4%;right:4%;border-left:none;border-bottom:none;}
  .bl{bottom:4%;left:4%;border-right:none;border-top:none;}
  .br{bottom:4%;right:4%;border-left:none;border-top:none;}
  #status{ margin-top:8px; color:#444; font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial; }
  #result{ margin-top:8px; max-width:min(92vw,__QRBOX__px); font-family:monospace; }
  #startbtn{ margin:8px 0 0; padding:10px 14px; border-radius:10px; border:1px solid #ddd; background:#fff; }
</style>

<div id="qr-wrap">
  <div id="qr-box">
    <video id="qr-video" muted playsinline></video>
    <div class="corner tl"></div><div class="corner tr"></div>
    <div class="corner bl"></div><div class="corner br"></div>
  </div>
  <button id="startbtn">🎥 Start camera</button>
  <div id="status"></div>
  <div id="result"></div>
</div>

<script type="module">
  import QrScanner from 'https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner.min.js';
  QrScanner.WORKER_PATH = 'https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner-worker.min.js';

  const video   = document.getElementById('qr-video');
  const status  = document.getElementById('status');
  const resultEl= document.getElementById('result');
  const btn     = document.getElementById('startbtn');

  // values polled by Streamlit
  window.qrDecoded = null;
  window.qrError   = null;

  function renderJsonAsTable(obj) {
    try {
      const entries = Object.entries(obj || {})
        .map(([k,v]) => `<tr><th style='text-align:left;padding:4px 6px;border:1px solid #ddd;'>${k}</th>
                           <td style='padding:4px 6px;border:1px solid #ddd;'>${
                             (v && typeof v === 'object')
                               ? `<pre style="white-space:pre-wrap;margin:0">${JSON.stringify(v,null,2)}</pre>` : v
                           }</td></tr>`).join('');
      return `<table style='width:100%;border-collapse:collapse;margin-top:6px;font-family:monospace'><tbody>${entries}</tbody></table>`;
    } catch { return ''; }
  }

  function b64UrlDecode(s){
    try { return atob((s||'').replace(/-/g,'+').replace(/_/g,'/')); }
    catch { return null; }
  }
  function hexToUtf8(hex){
    if(!hex) return '';
    const arr = (hex.match(/.{1,2}/g)||[]).map(b => parseInt(b,16));
    return new TextDecoder().decode(new Uint8Array(arr));
  }

  async function startScanner() {
    btn.disabled = true;
    status.textContent = "Initializing camera…";

    // prefer rear camera when available
    let deviceId;
    try {
      const cams = await QrScanner.listCameras(true);
      const rear = cams.find(c => /back|rear|environment/i.test(c.label||''));
      deviceId = (rear || cams[cams.length-1] || {}).id;
    } catch {}

    const scanner = new QrScanner(
      video,
      (result) => {
        try {
          let txt = result?.data || result || ''; // qr-scanner returns object when returnDetailedScanResult:true
          // If it looks like a URL with ?data= try to decode
          if (/^https?:\/\/.*/.test(txt)) {
            const u = new URL(txt);
            const d = u.searchParams.get('data') || u.searchParams.get('payload') || u.searchParams.get('qr') || u.searchParams.get('p');
            if (d) {
              const b = b64UrlDecode(d);
              txt = b ?? hexToUtf8(decodeURIComponent(d));
            }
          }
          window.qrDecoded = txt || null;
          try {
            const obj = JSON.parse(txt); const main = obj.data || obj;
            resultEl.innerHTML = "<b>✅ Decoded</b>" + renderJsonAsTable(main);
          } catch { resultEl.textContent = txt ? ("✅ " + txt) : "No data"; }
        } catch (e) {
          window.qrError = e?.message || String(e);
        } finally {
          scanner.stop();
          status.textContent = "Scan complete.";
        }
      },
      {
        preferredCamera: deviceId || undefined,
        highlightScanRegion: true,
        highlightCodeOutline: true,
        returnDetailedScanResult: true
      }
    );
    scanner.setInversionMode('both');

    try {
      video.setAttribute('autoplay',''); // iOS hint
      await scanner.start();
      status.textContent = "Point the QR inside the frame…";
    } catch (err) {
      window.qrError = err?.message || String(err);
      status.textContent = "Camera access denied or not available.";
      btn.disabled = false;
    }
  }

  btn.addEventListener('click', startScanner);
</script>
"""
    st_html(HTML_TEMPLATE.replace("__QRBOX__", str(qrbox_max)), height=640, scrolling=False)

    # poll JS -> Python
    decoded_text = streamlit_js_eval(js_expressions="window.qrDecoded || null", key="qr_poll_v1")
    qr_error     = streamlit_js_eval(js_expressions="window.qrError || null",   key="qr_err_v1")

    if qr_error:
        st.caption(f"Scanner notice: {qr_error}")

    # Post‑process
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
        st.info("Tap **Start camera** and point it at the QR.")

# ──────────────────────────────────────────────────────────────
# Manual entry + results / actions
# ──────────────────────────────────────────────────────────────
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
checked   = _coerce_int(
    row.get("number_of_attendees") if row.get("number_checked_in") is None
    else row.get("number_checked_in"), 0
)
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
