import os
from dotenv import load_dotenv
import streamlit as st
import streamlit_authenticator as stauth
from pathlib import Path
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

from utils.styling import inject_global_styles
inject_global_styles()

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


st.markdown("""
<h2 class="big-title">
    <span class='emoji'>🎫</span> NSS Event QR Issuance & Verification
</h1>
""", unsafe_allow_html=True)
st.markdown("<div class='subtitle'>Secure, simple event check-in — from sheet to QR to scanner</div>", unsafe_allow_html=True)

cols = st.columns(3)
# cols[0].info("🛠️ **Admin Panel**\n\nUpload attendee data and issue QR codes.")
# cols[1].info("📤 **Issuance & Reissue**\n\nGenerate, preview, and email QR codes.")
# cols[2].info("✅ **Verifier View**\n\nScan and check in attendees at the event.")

with st.container():
    st.markdown('<div class="card-button">', unsafe_allow_html=True)
    st.subheader("🛠️ Admin Panel")
    st.write("Upload attendee data and issue QR codes.")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card-button">', unsafe_allow_html=True)
    st.subheader("📨 Issuance & Reissue")
    st.write("Generate, preview, and email QR codes.")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card-button">', unsafe_allow_html=True)
    st.subheader("✅ Verifier View")
    st.write("Scan and check in attendees at the event.")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("""

    <div style="
        background-color: #FFF7E6;
        padding: 1rem;
        border-left: 5px solid #800000;
        border-radius: 8px;
        margin-top: 2rem;
        color: #5A0000;
    ">
        🔐 <strong>Please use the <em>sidebar to log in</em></strong> and access restricted pages.
        🌐 Public QR view is available via the menu.
    </div>
    """,
    unsafe_allow_html=True
)



