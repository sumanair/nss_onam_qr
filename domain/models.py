from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class EventPayment:
    transaction_id: str
    username: str
    email: str
    phone: str
    address: Optional[str]
    membership_paid: bool
    early_bird_applied: bool
    payment_date: Optional[datetime]
    amount: float
    paid_for: str
    remarks: Optional[str]
    qr_generated: bool
    qr_generated_at: Optional[datetime]
    qr_sent: bool
    qr_sent_at: Optional[datetime]
    qr_code_filename: Optional[str]
    qr_s3_url: Optional[str]
    number_of_attendees: int
    last_updated_at: Optional[datetime]
    qr_reissued_yn: bool = False
