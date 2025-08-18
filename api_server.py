# api_server.py
import os
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

from services import attendance_service  # uses batch-aware child table

# ──────────────────────────────────────────────
# CORS (tighten in prod; keep only what you need)
# ──────────────────────────────────────────────
# main.py
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI(title="NSSNT Verifier API")

ALLOWED_ORIGINS = [
    "http://localhost:4173",            # vite preview
    "http://localhost:3000",            # ( dev server)
    "https://verify.nssnt-events.com",  # prod SPA
    "https://nssnt-events.com",         # apex (if it will call API)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,           # ok if you use cookies/auth headers
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=600,
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
    if not token or token != expected:
        # secrets.compare_digest optional here—but equal-time compare is nice-to-have
        raise HTTPException(status_code=401, detail="Unauthorized")

# ──────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────
class Summary(BaseModel):
    username: str
    email: str
    number_of_attendees: int
    number_checked_in: int
    remaining: int
    all_attendees_checked_in: bool

class CheckinReq(BaseModel):
    transaction_id: str = Field(..., min_length=3)
    delta: int
    verifier_id: str | None = None  # optional audit tag (device/user)
    notes: str | None = None        # optional free-text note

class CheckinResp(BaseModel):
    message: str
    checked_in: int
    remaining: int

# ──────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"ok": True}

# ──────────────────────────────────────────────
# GET summary
# ──────────────────────────────────────────────
@app.get(
    "/api/attendance/summary",
    response_model=Summary,
    dependencies=[Depends(require_api_key)],
)
def get_summary(transaction_id: str):
    row = attendance_service.fetch_attendance_row_by_txn(transaction_id)
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # row already includes derived fields from child table
    return Summary(
        username=row["username"],
        email=row["email"],
        number_of_attendees=int(row["number_of_attendees"]),
        number_checked_in=int(row["number_checked_in"]),
        remaining=int(row.get("remaining", max(0, int(row["number_of_attendees"]) - int(row["number_checked_in"])))),
        all_attendees_checked_in=bool(row.get("all_attendees_checked_in")),
    )

# ──────────────────────────────────────────────
# POST check-in (atomic delta; batch-aware; audit via triggers)
#   delta > 0 → create a new batch of that size
#   delta < 0 → rewind the most recent active batches
# ──────────────────────────────────────────────
@app.post(
    "/api/checkin",
    response_model=CheckinResp,
    dependencies=[Depends(require_api_key)],
)
def post_checkin(payload: CheckinReq):
    ok, msg = attendance_service.update_checkins(
        payload.transaction_id,
        int(payload.delta),
        verifier_id=payload.verifier_id,
        notes=payload.notes,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    # Return updated counts
    row = attendance_service.fetch_attendance_row_by_txn(payload.transaction_id)
    if not row:
        # Extremely unlikely; transaction was just updated
        raise HTTPException(status_code=404, detail="Transaction not found")

    return CheckinResp(
        message=msg,
        checked_in=int(row["number_checked_in"]),
        remaining=int(row["remaining"]),
    )
