# ui/utils/qr_s3_utils.py

import os
import sys
import json
import base64
import qrcode
import boto3
from dotenv import load_dotenv
from urllib.parse import quote
from datetime import datetime

# Load .env variables
load_dotenv()

# === AWS Config ===
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION")
BUCKET_NAME = os.getenv("BUCKET_NAME")
QR_ROOT_PATH = os.getenv("QR_ROOT_PATH")  # ✅ Add this to your .env

# === S3 Client ===
s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_DEFAULT_REGION
)


# === Payload + URL Encoding ===

def build_qr_payload(row: dict, event_name: str) -> dict:
    return {
        "data": {
            "name": row["username"],
            "email": row["email"],
            "phone": row["phone"],
            "amount": row["amount"],
            "payment_date": row["payment_date"],
            "event": event_name,
            "transaction_id": row["transaction_id"],
            "paid_for": row["paid_for"],
            "membership_paid": row["membership_paid"],
            "early_bird_applied": row["early_bird_applied"]
        }
    }

def encode_qr_url(payload: dict) -> str:
    json_str = json.dumps(payload, separators=(",", ":"))
    base64_data = quote(base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8"))
    return f"{QR_ROOT_PATH}?data={base64_data}"


# === QR Generation and Upload ===

def generate_qr_image(url: str, filename: str, local_folder: str = "qr") -> str:
    os.makedirs(local_folder, exist_ok=True)
    path = os.path.join(local_folder, filename)
    img = qrcode.make(url)
    img.save(path)
    return path

def upload_to_s3(filepath: str, s3_key: str) -> str:
    s3_client.upload_file(filepath, BUCKET_NAME, s3_key)
    s3_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
    return s3_url


# === Main Orchestration Function ===

def generate_and_upload_qr(row: dict, event_name: str) -> str:
    payload = build_qr_payload(row, event_name)
    url = encode_qr_url(payload)
    filename = f"{row['transaction_id']}.png"

    local_path = generate_qr_image(url, filename)
    s3_key = f"qr_codes/{filename}"
    s3_url = upload_to_s3(local_path, s3_key)

    return s3_url
