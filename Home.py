import os
from dotenv import load_dotenv
import streamlit as st
import streamlit_authenticator as stauth
from pathlib import Path
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# Grab credentials
admin_username = os.getenv("ADMIN_USERNAME")
admin_name = os.getenv("ADMIN_NAME")
admin_password = os.getenv("ADMIN_PASSWORD")

verifier_username = os.getenv("VERIFIER_USERNAME")
verifier_name = os.getenv("VERIFIER_NAME")
verifier_password = os.getenv("VERIFIER_PASSWORD")

# --- Safety check ---
required_vars = {
    "ADMIN_USERNAME": admin_username,
    "ADMIN_NAME": admin_name,
    "ADMIN_PASSWORD": admin_password,
    "VERIFIER_USERNAME": verifier_username,
    "VERIFIER_NAME": verifier_name,
    "VERIFIER_PASSWORD": verifier_password
}

missing = [k for k, v in required_vars.items() if not v]
if missing:
    st.error(f"❌ Missing the following .env values: {', '.join(missing)}")
    st.stop()
# --- Config ---
st.set_page_config(page_title="🎟️ NSS Event QR Issuance", layout="centered")

# --- Sidebar Logo ---
with st.sidebar:
    st.image("NSS-Logo-Transparent-2-300x300.png", use_container_width=True)

# Get credentials from .env
credentials = {
    "usernames": {
        os.getenv("ADMIN_USERNAME"): {
            "name": os.getenv("ADMIN_NAME"),
            "password": os.getenv("ADMIN_PASSWORD"),
        },
        os.getenv("VERIFIER_USERNAME"): {
            "name": os.getenv("VERIFIER_NAME"),
            "password": os.getenv("VERIFIER_PASSWORD"),
        },
    }
}

authenticator = stauth.Authenticate(
    credentials,
    cookie_name="nss_qr_app",
    key="auth",
    cookie_expiry_days=1
)

# ✅ Login (DO NOT UNPACK)
authenticator.login(
    location="sidebar",
    fields={"Form name": "Login"}
)

# ✅ Use session state instead
auth_status = st.session_state.get("authentication_status")

if auth_status:
    st.session_state.authenticated = True
    st.session_state.username = st.session_state.get("username")
    st.sidebar.success(f"✅ Logged in as {st.session_state.get('name')}")
    authenticator.logout(location="sidebar", button_name="🚪 Logout")

elif auth_status is False:
    st.sidebar.error("❌ Invalid credentials")

else:
    st.sidebar.warning("🔐 Please log in to access features.")

# --- Home Page Content ---

st.markdown("""

    <style>
    .big-title {
        font-size: 2.5rem;
        font-weight: 800;
        margin-bottom: 0.25rem;
    }
    .subtitle {
        font-size: 1.2rem;
        margin-bottom: 2rem;
        color: #666;
    }
    .info-box {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 6px solid #3b82f6;
    }
    </style>

""", unsafe_allow_html=True)

st.markdown("<div class='big-title'>🎫 NSS Event QR Issuance & Verification</div>", unsafe_allow_html=True)
st.markdown("<div class='subtitle'>Secure, simple event check-in — from sheet to QR to scanner</div>", unsafe_allow_html=True)

cols = st.columns(3)
cols[0].info("🛠️ **Admin Panel**\n\nUpload attendee data and issue QR codes.")
cols[1].info("📤 **Issuance & Reissue**\n\nGenerate, preview, and email QR codes.")
cols[2].info("✅ **Verifier View**\n\nScan and check in attendees at the event.")

st.markdown("---")
st.markdown("""
<div class='info-box'>
🔐 Please use the **sidebar to log in** and access restricted pages.  
🌐 Public QR view is available via QR code links.
</div>
""", unsafe_allow_html=True)

