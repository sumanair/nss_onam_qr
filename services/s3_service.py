# services/s3_service.py
from services.aws_session import get_session
from config import S3_BUCKET

_s3 = get_session().client("s3")

def upload_png(local_path: str, key: str) -> str:
    _s3.upload_file(local_path, S3_BUCKET, key)
    return f"https://{S3_BUCKET}.s3.amazonaws.com/{key}"

def delete_key(key: str):
    _s3.delete_object(Bucket=S3_BUCKET, Key=key)

def get_bytes(key: str) -> bytes:
    obj = _s3.get_object(Bucket=S3_BUCKET, Key=key)
    return obj["Body"].read()
