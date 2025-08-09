# utils/db.py
import os
from sqlalchemy import create_engine

def get_engine():
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    pwd  = os.getenv("DB_PASSWORD")
    return create_engine(f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{name}", pool_pre_ping=True)
