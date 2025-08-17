# utils/auth_sidebar.py
import os
from pathlib import Path
from typing import Dict, Tuple

import streamlit as st
from dotenv import load_dotenv

__all__ = ["render_auth_in_sidebar", "require_auth", "get_authenticator"]  # keep names for compatibility

# --------------------------------------------------------------------
# No streamlit_authenticator: avoids form + the "Press Enter to submit" hint
# --------------------------------------------------------------------

def _safe_rerun() -> None:
    """Call st.rerun() on modern Streamlit; fallback to experimental_rerun() on older versions."""
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()
    else:  # older Streamlit
        getattr(st, "experimental_rerun")()

def _ensure_auth_state() -> None:
    st.session_state.setdefault("authenticated", False)
    st.session_state.setdefault("authentication_status", None)  # compatibility
    st.session_state.setdefault("username", "")
    st.session_state.setdefault("name", "")
    st.session_state.setdefault("role", "")

def _load_env_once() -> None:
    if not st.session_state.get("_env_loaded"):
        env_path = Path(__file__).resolve().parents[1] / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
        st.session_state["_env_loaded"] = True

def _read_creds() -> Dict[str, Dict[str, str]]:
    _load_env_once()
    admin_username     = (os.getenv("ADMIN_USERNAME") or "").strip()
    admin_name         = (os.getenv("ADMIN_NAME") or "").strip()
    admin_password     = (os.getenv("ADMIN_PASSWORD") or "").strip()
    verifier_username  = (os.getenv("VERIFIER_USERNAME") or "").strip()
    verifier_name      = (os.getenv("VERIFIER_NAME") or "").strip()
    verifier_password  = (os.getenv("VERIFIER_PASSWORD") or "").strip()

    missing = [k for k, v in {
        "ADMIN_USERNAME": admin_username,
        "ADMIN_NAME": admin_name,
        "ADMIN_PASSWORD": admin_password,
        "VERIFIER_USERNAME": verifier_username,
        "VERIFIER_NAME": verifier_name,
        "VERIFIER_PASSWORD": verifier_password,
    }.items() if not v]
    if missing:
        with st.sidebar:
            st.error(f"❌ Missing .env values: {', '.join(missing)}")
        st.stop()

    return {
        admin_username.lower():    {"name": admin_name,    "password": admin_password,   "role": "admin"},
        verifier_username.lower(): {"name": verifier_name, "password": verifier_password, "role": "verifier"},
    }

def _check_login(input_user: str, input_pass: str) -> Tuple[bool, str, str, str]:
    """Returns (ok, username, name, role)."""
    directory = _read_creds()
    u = (input_user or "").strip().lower()
    p = (input_pass or "").strip()
    if not u or not p:
        return False, "", "", ""
    rec = directory.get(u)
    if not rec or p != rec["password"]:
        return False, "", "", ""
    return True, u, rec["name"], rec["role"]

# compatibility shim for old imports elsewhere
def get_authenticator():
    return None

def render_auth_in_sidebar() -> None:
    _ensure_auth_state()

    with st.sidebar:
        # Optional logo
        try:
            st.image("NSS-Logo-Transparent-2-300x300.png", use_container_width=True)
        except Exception:
            pass

        st.subheader("Login")

        if st.session_state.get("authenticated"):
            who = st.session_state.get("name") or st.session_state.get("username") or "(unknown)"
            st.success(f"✅ Logged in as {who} ({st.session_state.get('role')})")
            if st.button("🚪 Logout", use_container_width=True):
                for k in ("authenticated", "authentication_status", "username", "name", "role"):
                    st.session_state[k] = "" if k in ("username", "name", "role") else False
                _safe_rerun()
            return

        # No form here ⇒ no "Press Enter to submit form" hint
        user = st.text_input("Username", key="__login_user__", placeholder="Enter username")
        pwd  = st.text_input("Password", key="__login_pass__", type="password", placeholder="Enter password")

        if st.button("Login", use_container_width=True):
            ok, u_norm, name, role = _check_login(user, pwd)
            if ok:
                st.session_state.username = u_norm
                st.session_state.name = name
                st.session_state.role = role
                st.session_state.authenticated = True
                st.session_state.authentication_status = True  # compatibility flag
                st.success("Logged in ✓")
                _safe_rerun()
            else:
                st.session_state.authenticated = False
                st.session_state.authentication_status = False
                st.error("❌ Invalid credentials")

        st.info("🔐 Click **Login** after entering your credentials.")

def require_auth() -> None:
    """Call near the top of a protected page."""
    if not st.session_state.get("authenticated"):
        st.error("Please log in from the sidebar to access this page.")
        st.stop()
