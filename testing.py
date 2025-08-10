from sqlalchemy import text
from utils.db import get_engine
from pathlib import Path
import os

from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

engine = get_engine()
with engine.connect() as conn:
    r = conn.execute(text("""
        SELECT transaction_id, username, number_of_attendees, number_checked_in
        FROM event_payment
        WHERE transaction_id = :t
    """), {"t": "14891421-566d-4b7d-a2b0-122aa5ab70f0"}).mappings().all()
print(r)
