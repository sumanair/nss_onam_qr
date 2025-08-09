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

# ── soft import: streamlit-webrtc (live scan) ───────────────────────────────────
_WEBRTC_AVAILABLE = True
try:
    from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, WebRtcMode
    import av
except Exception:
    _WEBRTC_AVAILABLE = False

# ── soft import: pyzbar (fallback decoder) ─────────────────────────────────────
_PYZBAR_AVAILABLE = True
try:
    from pyzbar.pyzbar import decode as zbar_decode
except Exception:
    _PYZBAR_AVAILABLE = False

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
    # Handles ...?transaction_id=..., ?txn=..., or ?data=<base64(json)>
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
    """Still-photo fallback decode (used if WebRTC unavailable)."""
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

    # optional: pyzbar fallback on stills
    if _PYZBAR_AVAILABLE:
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            for obj in zbar_decode(gray):
                txt = obj.data.decode("utf-8", errors="ignore")
                if txt:
                    return [txt]
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
        checked = _coerce_int(current["number_of_attendees"] if current.get("number_checked_in") is None else current["number_checked_in"], 0)
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
    """
    Try to get a JSON payload embedded in a URL (?data= / ?payload= / ?qr= / ?p=),
    or base64-encoded JSON, or direct JSON string. Returns dict or {"_raw": "..."}.
    """
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
# Live QR scanner (WebRTC) – robust processor
# ──────────────────────────────────────────────────────────────
if _WEBRTC_AVAILABLE:
    class QRVideoProcessor(VideoProcessorBase):
        def __init__(self):
            self.last_texts: List[str] = []
            self.det = cv2.QRCodeDetector()
            self.use_mirror = False  # toggled via session state

        def _preprocess(self, img_bgr):
            # Optional mirror
            if self.use_mirror:
                img_bgr = cv2.flip(img_bgr, 1)

            # Upscale small frames
            h, w = img_bgr.shape[:2]
            if w < 640:
                scale = 640 / float(w)
                img_bgr = cv2.resize(img_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            # Local contrast
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            # Gentle denoise
            gray = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
            # Adaptive threshold
            thr = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 5
            )
            return img_bgr, thr

        def _try_decode_opencv(self, bin_img):
            texts = []
            boxes = []

            # Multi
            try:
                ok, decoded, points, _ = self.det.detectAndDecodeMulti(bin_img)
                if ok and decoded:
                    for i, d in enumerate(decoded):
                        if d and points is not None:
                            texts.append(d)
                            boxes.append(points[i].astype(int).reshape(-1, 2))
            except Exception:
                pass

            # Single
            if not texts:
                try:
                    d_single, p_single = self.det.detectAndDecode(bin_img)
                    if d_single:
                        texts.append(d_single)
                        if p_single is not None and len(p_single) == 4:
                            boxes.append(p_single.astype(int))
                except Exception:
                    pass

            return texts, boxes

        def _try_decode_pyzbar(self, img_bgr):
            texts = []
            boxes = []
            if not _PYZBAR_AVAILABLE:
                return texts, boxes
            try:
                gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
                for obj in zbar_decode(gray):
                    txt = obj.data.decode("utf-8", errors="ignore")
                    if txt:
                        texts.append(txt)
                        # polygon points if available
                        pts = []
                        if getattr(obj, "polygon", None):
                            pts = [[p.x, p.y] for p in obj.polygon]
                        elif getattr(obj, "rect", None):
                            x, y, w, h = obj.rect.left, obj.rect.top, obj.rect.width, obj.rect.height
                            pts = [[x, y], [x+w, y], [x+w, y+h], [x, y+h]]
                        if pts:
                            boxes.append(np.array(pts, dtype=int))
            except Exception:
                pass
            return texts, boxes

        def recv(self, frame: "av.VideoFrame") -> "av.VideoFrame":
            img = frame.to_ndarray(format="bgr24")

            # Read mirror toggle from session
            self.use_mirror = bool(st.session_state.get("qr_mirror", False))

            # Preprocess
            img_bgr, bin_img = self._preprocess(img)

            # Try multiple rotations (opencv)
            rotations = [
                bin_img,
                cv2.rotate(bin_img, cv2.ROTATE_90_CLOCKWISE),
                cv2.rotate(bin_img, cv2.ROTATE_180),
                cv2.rotate(bin_img, cv2.ROTATE_90_COUNTERCLOCKWISE),
            ]

            texts = []
            boxes = []
            for rot in rotations:
                t, b = self._try_decode_opencv(rot)
                if t:
                    texts, boxes = t, b
                    break

            # If still nothing, try pyzbar fallback on the (preprocessed) BGR
            if not texts:
                t2, b2 = self._try_decode_pyzbar(img_bgr)
                if t2:
                    texts, boxes = t2, b2

            # Draw boxes only when we got text
            if texts and boxes:
                for pts in boxes:
                    for i in range(len(pts)):
                        cv2.line(img_bgr, tuple(pts[i]), tuple(pts[(i + 1) % len(pts)]), (0, 255, 0), 2)

            self.last_texts = texts
            return av.VideoFrame.from_ndarray(img_bgr, format="bgr24")

# ──────────────────────────────────────────────────────────────
# Scan / manual input
# ──────────────────────────────────────────────────────────────
left, right = st.columns([1, 1])

with left:
    st.subheader("📹 Live Scan")

    if _WEBRTC_AVAILABLE:
        with st.sidebar:
            st.toggle("🔁 Mirror camera", key="qr_mirror", value=False,
                      help="Some webcams feed mirrored frames; toggle if boxes look reversed.")

        ctx = webrtc_streamer(
            key="qr-stream",
            mode=WebRtcMode.SENDRECV,
            video_processor_factory=QRVideoProcessor,
            media_stream_constraints={
                "video": {
                    "facingMode": {"ideal": "environment"},  # rear camera on phones, if available
                    "width": {"ideal": 1280},
                    "height": {"ideal": 720},
                    "frameRate": {"ideal": 30}
                },
                "audio": False
            },
            async_processing=True,
        )

        if ctx and ctx.video_processor:
            texts = ctx.video_processor.last_texts or []
            if texts:
                st.success("QR detected!")
                latest = texts[0]
                st.code(latest, language="text")

                st.session_state["verifier_raw"] = latest
                st.session_state["verifier_payload_json"] = extract_payload_json(latest)
                tx = parse_scanned_text_to_txn(latest)
                if tx:
                    st.session_state["verifier_txn"] = tx
                else:
                    st.warning("Couldn’t extract a transaction id from the QR.")
            else:
                st.info("Point a QR at the camera… steady, good lighting, fill ~60% of frame.")
        else:
            st.info("Initializing camera…")

    else:
        st.warning("Live scan module not found. Falling back to snapshot mode. "
                   "Install with: pip install streamlit-webrtc av")

        cam_file = st.camera_input("Use your device camera (snapshot)")
        if cam_file is not None:
            decoded_texts = decode_qr_from_image_bytes(cam_file.getvalue())
            if decoded_texts:
                st.success("QR detected!")
                for t in decoded_texts:
                    st.code(t, language="text")
                tx = parse_scanned_text_to_txn(decoded_texts[0])
                st.session_state["verifier_raw"] = decoded_texts[0]
                st.session_state["verifier_payload_json"] = extract_payload_json(decoded_texts[0])
                if tx:
                    st.session_state["verifier_txn"] = tx
                else:
                    st.warning("Couldn’t extract a transaction id from the QR. Paste it on the right.")
            else:
                st.warning("No QR code found in the frame.")

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
    min_value=1, max_value=remaining, value=min(1, remaining), step=1,
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

st.caption("Tip: if a QR won’t scan, paste the code text into Manual Entry.")
