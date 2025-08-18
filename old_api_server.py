# api_server.py
import os
import datetime
import secrets
from pathlib import Path
from dotenv import load_dotenv

# ──────────────────────────────────────────────
# Load env BEFORE importing attendance_service / get_engine()
# ──────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
load_dotenv(HERE / "pages" / ".env", override=False)

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from services import attendance_service  # your existing DB helpers
from sqlalchemy import text
from utils.db import get_engine  # reuse project engine

# ──────────────────────────────────────────────
# CORS (tighten in prod; keep only what you need)
# ──────────────────────────────────────────────
ALLOW_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    os.getenv("VERIFIER_ORIGIN", ""),  # e.g. https://nssnt.org
]

app = FastAPI(title="NSSNT Verifier API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in ALLOW_ORIGINS if o],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Simple API-key auth (env driven)
#   - Set VERIFIER_API_KEY in .env to enable
#   - Clients send X-API-Key: <key>  OR  Authorization: Bearer <key>
# ──────────────────────────────────────────────
def require_api_key(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    expected = os.getenv("VERIFIER_API_KEY")
    if not expected:
        # auth disabled (e.g., local dev)
        return
    token = None
    if x_api_key:
        token = x_api_key.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")

# ──────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────
class Summary(BaseModel):
    username: str
    email: str
    number_of_attendees: int
    number_checked_in: int

class CheckinReq(BaseModel):
    transaction_id: str = Field(..., min_length=3)
    delta: int
    verifier_id: str | None = None  # optional audit tag (device/user)

# ──────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"ok": True}

# ──────────────────────────────────────────────
# GET summary
# ──────────────────────────────────────────────
@app.get("/api/attendance/summary", response_model=Summary, dependencies=[Depends(require_api_key)])
def get_summary(transaction_id: str):
    row = attendance_service.fetch_attendance_row_by_txn(transaction_id)
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return Summary(
        username=row["username"],
        email=row["email"],
        number_of_attendees=int(row["number_of_attendees"]),
        number_checked_in=int(row["number_checked_in"]),
    )

# ──────────────────────────────────────────────
# POST check-in (atomic delta + audit stamp)
# ──────────────────────────────────────────────
@app.post("/api/checkin", dependencies=[Depends(require_api_key)])
def post_checkin(payload: CheckinReq):
    # Apply the bounded atomic update using your existing logic
    ok, msg = attendance_service.update_checkins(payload.transaction_id, int(payload.delta))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    # Lightweight audit: who/when (doesn't affect counts)
    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE event_payment
                       SET last_checked_in_at = :now,
                           last_checked_in_by = :by,
                           last_updated_at    = :now
                     WHERE transaction_id = :txn
                """),
                {
                    "now": datetime.datetime.now(),  # match your schema's TIMESTAMP
                    "by": (payload.verifier_id or "").strip() or None,
                    "txn": payload.transaction_id,
                }
            )
    except Exception:
        # Don't fail the request if audit fails; counts are already updated atomically
        pass

    # Return updated count for convenience
    row = attendance_service.fetch_attendance_row_by_txn(payload.transaction_id)
    checked = int(row["number_checked_in"]) if row else None
    return {"message": msg, "checked_in": checked}
