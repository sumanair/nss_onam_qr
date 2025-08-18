# Home.py
import os
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv


qp = st.query_params
page = qp.get("page")
data = qp.get("data")
tx   = qp.get("tx")

# If a target page is specified, stash extras (data/tx) before switching
if page:
    if data: st.session_state["_qr_data"] = data

    target = f"pages/{page}" if not str(page).endswith(".py") else str(page)
    try:
        st.switch_page(target)
    except Exception:
        for cand in ["pages/5_QR_Viewer.py", "pages/QR_Viewer.py"]:
            try:
                st.switch_page(cand)
                break
            except Exception:
                pass

# ── Page config FIRST ─────────────────────────────────────────
st.set_page_config(
    page_title="🎟️ NSS Event QR Issuance",
    page_icon="🎫",
    layout="centered",
)

# ── Env + styling ─────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

from utils.styling import inject_global_styles, inject_sidebar_styles
from utils.auth_sidebar import render_auth_in_sidebar, require_auth
inject_global_styles()
inject_sidebar_styles()

# ── Sidebar auth on EVERY page ────────────────────────────────
render_auth_in_sidebar()     # <- shows login/logout in sidebar (cookie-based)
# If Home should be public, comment out the next line:
# require_auth()

# ── Hero ──────────────────────────────────────────────────────
st.markdown(
    """
    <h2 class="big-title">
        <span class='emoji'>🎫</span> NSS Event QR Issuance & Verification
    </h2>
    <div class='subtitle'>Secure, simple event check-in — from sheet to QR to scanner</div>
    """,
    unsafe_allow_html=True,
)

# ── Robust page URL helper (works with server.baseUrlPath) ────
def page_href(page_name: str) -> str:
    base = st.get_option("server.baseUrlPath") or ""
    base = "" if base in ("", "/") else "/" + base.strip("/")
    return f"{base}/{page_name}"

admin_href    = page_href("Admin")        # pages/1_Admin.py
issuance_href = page_href("Issuance")     # pages/2_Issuance.py
reissue_href  = page_href("Reissuance")   # pages/3_Reissuance.py
verifier_href = page_href("Verifier")     # pages/4_Verifier.py

# ── Feature cards ─────────────────────────────────────────────
st.markdown(f"""
<div class="feature-grid">

  <div class="feature-card">
    <div class="fc-head">
      <div class="fc-icon">🛠️</div>
      <div class="fc-title"><a href="{admin_href}">Admin Panel</a></div>
    </div>
    <div class="fc-body">
      <p class="fc-desc">
        Upload attendee spreadsheets, validate columns, and import data safely.
        Admins can manage records in bulk with clear visibility into changes.
      </p>
    </div>
  </div>

  <div class="feature-card">
    <div class="fc-head">
      <div class="fc-icon">📨</div>
      <div class="fc-title"><a href="{issuance_href}">Issuance &amp; Reissue</a></div>
    </div>
    <div class="fc-body">
      <a class="fc-link" href="{issuance_href}">Go to Issuance</a>
      <a class="fc-link" href="{reissue_href}">Go to Reissue</a>
      <p class="fc-desc">
        Generate personalized QR codes, preview them instantly, and email links directly
        to participants. Easily reissue codes if details change.
      </p>
    </div>
  </div>

  <div class="feature-card">
    <div class="fc-head">
      <div class="fc-icon">✅</div>
      <div class="fc-title"><a href="{verifier_href}">Verifier View</a></div>
    </div>
    <div class="fc-body">
      <p class="fc-desc">
        Scan QR codes on-site using a camera or phone, confirm validity instantly,
        and mark check-ins with automatic attendance tracking and audit logs.
      </p>
    </div>
  </div>

</div>
""", unsafe_allow_html=True)
