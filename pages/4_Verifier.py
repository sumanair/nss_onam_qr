# pages/4_Verifier.py
import json
import re
import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from streamlit_js_eval import streamlit_js_eval

from utils.styling import inject_global_styles, inject_sidebar_styles
from utils.auth_sidebar import render_auth_in_sidebar, require_auth
from services import attendance_service
from utils import qr_scan_utils


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _safe_rerun() -> None:
    rerun = getattr(st, "rerun", None)
    (rerun or getattr(st, "experimental_rerun"))()

def je(expr: str, key: str):
    """Safe wrapper for streamlit_js_eval using the required js_expressions= keyword."""
    return streamlit_js_eval(js_expressions=expr, key=key)

# Robust recursive txn finder (handles transaction_id / transactionId / txid etc)
_TXN_KEYS = {"transactionid","transaction_id","txn","txid"}
def _find_txn_any(obj):
    def _norm(s: str) -> str:
        return "".join(str(s).lower().split()).replace("_","")
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if _norm(k) in _TXN_KEYS and v:
                    return str(v)
            # breadth doesn’t matter; just explore
            for v in cur.values():
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return ""

def _extract_payload_json_py(text: str):
    """Return (decoded_json_obj_or_None, reason). Does NOT try to find txn."""
    if not text:
        return None, "empty"
    s = text.strip()

    # Raw JSON?
    if s.startswith("{") and s.endswith("}"):
        try:
            return json.loads(s), "raw_json"
        except Exception:
            pass

    # URL with ?data/payload/qr/p
    if s.startswith(("http://", "https://")):
        try:
            from urllib.parse import urlparse, parse_qs, unquote
            u = urlparse(s)
            q = parse_qs(u.query or "")
            for k in ("data", "payload", "qr", "p"):
                if k in q and q[k]:
                    raw = unquote(q[k][0])
                    b = qr_scan_utils._b64_try(raw)
                    cand = b or raw
                    try:
                        return json.loads(cand), f"url_param:{k}"
                    except Exception:
                        try:
                            import binascii
                            bytes_ = binascii.unhexlify(raw)
                            txt2 = bytes_.decode("utf-8", errors="ignore")
                            return json.loads(txt2), f"url_param_hex:{k}"
                        except Exception:
                            pass
            last = (u.path or "").split("/")[-1]
            if last:
                decoded = qr_scan_utils._b64_try(last)
                if decoded:
                    try:
                        return json.loads(decoded), "url_lastseg_b64"
                    except Exception:
                        pass
        except Exception:
            return None, "url_parse_fail"

    # Raw base64 JSON?
    b2 = qr_scan_utils._b64_try(s)
    if b2:
        try:
            return json.loads(b2), "raw_b64"
        except Exception:
            return None, "raw_b64_parse_fail"

    return None, "unknown_format"


# ──────────────────────────────────────────────
# Page setup
# ──────────────────────────────────────────────
st.set_page_config(page_title="Verifier • Attendance Check-In", layout="centered")
inject_global_styles()
inject_sidebar_styles()

render_auth_in_sidebar()
require_auth()

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

st.title("🛂 Attendance Check-In (Verifier)")

# Role guard
if (st.session_state.get("role") or "").lower() not in {"verifier", "admin"}:
    st.error("You do not have verifier access.")
    st.stop()

# ──────────────────────────────────────────────
# HTML5 Scanner → JS renders; Python extracts txn
# ──────────────────────────────────────────────
from streamlit.components.v1 import html as st_html

qrbox_max = 640
HTML_TEMPLATE = r"""
<style>
  #qr-wrap { display:flex; flex-direction:column; align-items:center; }
  #qr-box  { width:min(98vw, __QRBOX__px); aspect-ratio: 3 / 4; position:relative; }
  #qr-video{ width:100%; height:100%; object-fit:cover; border-radius:12px;
             box-shadow:0 4px 12px rgba(0,0,0,.12); background:#000; }
  .corner{position:absolute;width:18%;height:18%;border:4px solid #f4b000;border-radius:14px;}
  .tl{top:4%;left:4%;border-right:none;border-bottom:none;}
  .tr{top:4%;right:4%;border-left:none;border-bottom:none;}
  .bl{bottom:4%;left:4%;border-right:none;border-top:none;}
  .br{bottom:4%;right:4%;border-left:none;border-top:none;}
  #status{ margin-top:10px; color:#444; font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial; }
  #resultwrap{ margin-top:12px; width:min(98vw,__QRBOX__px); max-height:48vh; overflow:auto; -webkit-overflow-scrolling: touch; }
  #resulttitle{ font-weight:700; margin:6px 0 8px 0; display:flex; align-items:center; gap:.4rem; }
  #resulttbl{ width:100%; border-collapse:collapse; table-layout:auto; font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; font-size:.95rem; }
  #resulttbl th, #resulttbl td { border:1px solid #ddd; padding:8px 10px; vertical-align:top; word-break:break-word; overflow-wrap:anywhere; white-space:pre-wrap; }
  #startbtn{ margin:12px 0 0; padding:12px 16px; border-radius:12px; border:1px solid #ddd; background:#fff; cursor:pointer; font-size:16px; }
</style>

<div id="qr-wrap">
  <div id="qr-box">
    <video id="qr-video" muted playsinline></video>
    <div class="corner tl"></div><div class="corner tr"></div>
    <div class="corner bl"></div><div class="corner br"></div>
  </div>
  <button id="startbtn">🎥 Start camera</button>
  <div id="status">Tap “Start camera” and point the code inside the frame.</div>
  <div id="resultwrap"></div>
</div>

<script type="module">
  import QrScanner from 'https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner.min.js';
  QrScanner.WORKER_PATH = 'https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner-worker.min.js';

  const video   = document.getElementById('qr-video');
  const status  = document.getElementById('status');
  const resultWrap = document.getElementById('resultwrap');
  const btn     = document.getElementById('startbtn');

  const HIDE_KEYS = ["transaction_id","transactionid","txn","txid"];
  const b64UrlDecode = (s) => { try { return atob((s||'').replace(/-/g,'+').replace(/_/g,'/')); } catch { return null; } };
  function hexToUtf8(hex){ if(!hex) return ''; const arr=(hex.match(/.{1,2}/g)||[]).map(b=>parseInt(b,16)); return new TextDecoder().decode(new Uint8Array(arr)); }

  function stripHidden(obj){
    if(!obj) return obj;
    if(Array.isArray(obj)) return obj.map(stripHidden);
    if(typeof obj==='object'){
      const out={};
      for(const [k,v] of Object.entries(obj)){
        if(!HIDE_KEYS.includes(String(k).toLowerCase())) out[k]=stripHidden(v);
      }
      return out;
    }
    return obj;
  }

  function renderJsonAsTable(obj) {
    const rows = Object.entries(obj||{}).map(([k,v])=>{
      const val = (v && typeof v==='object') ? JSON.stringify(v,null,2) : (v ?? "");
      return `<tr><th>${k}</th><td>${val}</td></tr>`;
    }).join('');
    return `<div id="resulttitle">✅ <span>Decoded</span></div><table id="resulttbl"><tbody>${rows}</tbody></table>`;
  }

  function hardClearBeforeStart() {
    try {
      const el = document.getElementById('resultwrap');
      if (el) el.innerHTML = "";
      localStorage.removeItem('nssnt_qr_bundle');
      localStorage.removeItem('nssnt_qr_err');
      localStorage.removeItem('nssnt_qr_ts');
      localStorage.setItem('nssnt_qr_start', Date.now().toString());
    } catch {}
  }

  async function startScanner() {
    btn.disabled = true;
    status.textContent = "Initializing camera…";

    // Prefer rear camera
    let deviceId;
    try {
      const cams = await QrScanner.listCameras(true);
      const rear = cams.find(c => /back|rear|environment/i.test(c.label||''));
      deviceId = (rear || cams[cams.length-1] || {}).id;
    } catch {}

    const scanner = new QrScanner(
      video,
      (result) => {
        let txt = result?.data || result || '';
        let debug = { hadUrl:false, wrote: false };

        try {
          // Handle URL payloads
          if (/^https?:\/\//i.test(txt)) {
            debug.hadUrl = true;
            try {
              const u = new URL(txt);
              const pnames = ["data","payload","qr","p"];
              let payload = null;
              for (const k of pnames){ const v=u.searchParams.get(k); if(v){ payload=v; break; } }
              if (payload){
                const b = b64UrlDecode(payload);
                txt = b ? b : hexToUtf8(decodeURIComponent(payload));
              }
            } catch (e) {
              debug.urlErr = String(e?.message || e);
            }
          }

          // Try to parse JSON just for preview; Python will extract txn
          let obj = null, main = null, jsonStr = "";
          try { obj = JSON.parse(txt); main = obj?.data ?? obj; jsonStr = JSON.stringify(obj); debug.json=true; } catch { debug.json=false; }

          // Render preview (without txn)
          resultWrap.innerHTML = "";
          if (main) {
            const shown = stripHidden(main);
            resultWrap.innerHTML = renderJsonAsTable(shown);
          } else {
            resultWrap.textContent = txt ? ("✅ " + txt) : "No data";
          }

          // ALWAYS write full raw + parsed json string (if any). Python does txn.
          const bundle = JSON.stringify({ raw: (txt || ""), json: jsonStr });
          localStorage.setItem('nssnt_qr_bundle', bundle);
          localStorage.setItem('nssnt_qr_ts', Date.now().toString());
          debug.wrote = true;

        } catch (e) {
          localStorage.setItem('nssnt_qr_err', (e?.message || String(e)));
        } finally {
          localStorage.setItem('nssnt_qr_debug', JSON.stringify(debug));
          scanner.stop();
          status.textContent = "Scan complete. Tap Start to scan another.";
          btn.disabled = false;
        }
      },
      { preferredCamera: deviceId || undefined, returnDetailedScanResult: true }
    );
    scanner.setInversionMode('both');

    try {
      video.setAttribute('autoplay',''); // iOS hint
      await scanner.start();
      status.textContent = "Point the QR inside the frame…";
    } catch (err) {
      localStorage.setItem('nssnt_qr_err', (err?.message || String(err)));
      status.textContent = "Camera access denied or not available.";
      btn.disabled = false;
    }
  }

  btn.addEventListener('click', async () => { hardClearBeforeStart(); await startScanner(); });
</script>
"""

st_html(HTML_TEMPLATE.replace("__QRBOX__", str(qrbox_max)), height=720, scrolling=False)

# ──────────────────────────────────────────────
# Poll results from localStorage
# ──────────────────────────────────────────────
if st.session_state.get("qr_polling", True):
    st.query_params["_"] = datetime.datetime.now().timestamp()

ts = je("localStorage.getItem('nssnt_qr_ts') || ''", key="qr_ts_bundle_v4")
bundle_str = je("localStorage.getItem('nssnt_qr_bundle') || ''", key="qr_bundle_v4")
qr_error = je("localStorage.getItem('nssnt_qr_err') || ''", key="qr_err_bundle_v4")
start_ts = je("localStorage.getItem('nssnt_qr_start') || ''", key="qr_start_v2")
qr_debug = je("localStorage.getItem('nssnt_qr_debug') || ''", key="qr_dbg_v2")

last_ts = st.session_state.get("qr_last_ts", "")
last_start = st.session_state.get("qr_last_start", "")

# Fresh Start → hard reset server-side as well
if start_ts and start_ts != last_start:
    print("🟢 Start pressed:", start_ts, "(last:", last_start, ") → reset")
    st.session_state["qr_last_start"] = start_ts
    st.session_state.pop("verifier_txn", None)
    st.session_state.pop("verifier_raw", None)
    st.session_state["qr_polling"] = True
    st.session_state["qr_last_ts"] = ""
    je("const el=document.getElementById('resultwrap'); if(el){el.innerHTML='';}", key="qr_clear_ui_on_start")

raw_text = ""
json_text = ""
txn_final = ""
py_payload, py_reason = (None, "empty")

if ts and ts != last_ts and bundle_str:
    print("🔄 New TS:", ts, " (last:", last_ts, ")")
    st.session_state["qr_last_ts"] = ts

    # Parse the JS bundle (no txn inside now)
    try:
        bundle = json.loads(bundle_str)
        raw_text = str(bundle.get("raw") or "")
        json_text = str(bundle.get("json") or "")
        print("📦 bundle sizes → raw:", len(raw_text), " json:", len(json_text))
    except Exception as e:
        print("❌ bundle parse fail:", e)

    # Prefer the pre-parsed JSON from JS; else decode from raw
    payload = None
    if json_text:
        try:
            payload = json.loads(json_text)
            py_reason = "js_json"
        except Exception as e:
            print("❌ js_json parse fail:", e)

    if payload is None:
        payload, py_reason = _extract_payload_json_py(raw_text or "")
    print("🐍 payload decode reason:", py_reason)

    # Python-only txn extraction (robust)
    if payload is not None:
        txn_final = _find_txn_any(payload)
    if not txn_final:
        # last-chance regex on raw text
        m = re.search(r"\b[a-zA-Z0-9_-]{12,64}\b", raw_text or "")
        txn_final = m.group(0) if m else ""

    print("🪪 txn_final:", txn_final)

    # Update session based on what we found
    if txn_final:
        st.session_state["verifier_txn"] = txn_final
        st.session_state["verifier_raw"] = raw_text or json_text or ""
        st.session_state["qr_polling"] = False
    else:
        st.session_state["verifier_raw"] = raw_text or json_text or st.session_state.get("verifier_raw","")

    # Clear bundle to avoid retrigger
    je("localStorage.removeItem('nssnt_qr_bundle');", key="qr_clear_bundle_v2")

else:
    print("⏸ No new TS. ts:", ts, " last_ts:", last_ts)
    if qr_debug:
        try:
            print("🧪 JS debug:", json.loads(qr_debug))
        except Exception:
            print("🧪 JS debug (raw):", qr_debug[:200])

if qr_error:
    st.caption(f"Scanner notice: {qr_error}")

st.divider()

# ──────────────────────────────────────────────
# Search by name/email (no QR)
# ──────────────────────────────────────────────
with st.expander("🔎 Search by name or email (no QR)"):
    q = st.text_input("Name or email", placeholder="e.g., anita@domain.com")
    if st.button("Search", use_container_width=True):
        if q.strip():
            results = attendance_service.fetch_attendance_by_name_or_email(q)
            if results.empty:
                st.warning("No matches found.")
            else:
                for i, r in results.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**{r['username']}**  \n{r.get('email','')}")
                        st.caption(f"Purchased: {int(r['number_of_attendees'])} • Checked-in: {int(r['number_checked_in'])}")
                        if st.button("Use this record", key=f"use_{i}", use_container_width=True):
                            st.session_state["verifier_txn"] = str(r["transaction_id"])
                            st.session_state["qr_polling"] = False
                            _safe_rerun()

# ──────────────────────────────────────────────
# Attendance counters & actions (DB-backed)
# ──────────────────────────────────────────────
txn_id = (st.session_state.get("verifier_txn") or "").strip()
if not txn_id:
    st.warning("No transaction id yet. Scan a code or use Search above.")
    st.stop()

row = attendance_service.fetch_attendance_row_by_txn(txn_id)
if not row:
    st.error(f"Transaction not found in DB for txn: {txn_id}")
    st.stop()

username  = row.get("username") or "(unknown)"
email     = row.get("email") or ""
total     = attendance_service._coerce_int(row.get("number_of_attendees"), 0)
checked   = attendance_service._coerce_int(row.get("number_checked_in"), 0)
remaining = max(0, total - checked)

st.markdown(f"### 👤 {username}")
if email:
    st.caption(email)

m1, m2, m3 = st.columns(3)
m1.metric("Purchased", total)
m2.metric("Checked-in", checked)
m3.metric("Remaining", remaining)

def _clear_ui_after_success(msg: str):
    st.success(msg)
    st.session_state.pop("verifier_txn", None)
    st.session_state.pop("verifier_raw", None)
    je("const el=document.getElementById('resultwrap'); if(el){el.innerHTML='';}", key="qr_clear_ui")

if remaining == 0:
    st.error("All attendees for this ticket have already checked in.")
else:
    admit = st.number_input("Admit now", min_value=1, max_value=remaining, value=1, step=1)
    a, b, c = st.columns(3)

    if a.button("✅ Update Attendance", use_container_width=True):
        ok, msg = attendance_service.update_checkins(txn_id, int(admit))
        if ok: _clear_ui_after_success(msg)
        else:  st.warning(msg)
        _safe_rerun()

    if checked > 0:
        undo = b.number_input("Undo", min_value=1, max_value=checked, value=1, step=1, key="undo_input")
        if b.button("↩️ Apply Reduction", use_container_width=True):
            ok, msg = attendance_service.update_checkins(txn_id, -int(undo))
            if ok: _clear_ui_after_success(msg)
            else:  st.warning(msg)
            _safe_rerun()
    else:
        b.caption("No check-ins yet to undo.")

    if c.button(f"➡️ Admit All ({remaining})", use_container_width=True):
        ok, msg = attendance_service.update_checkins(txn_id, int(remaining))
        if ok: _clear_ui_after_success(msg)
        else:  st.warning(msg)
        _safe_rerun()
