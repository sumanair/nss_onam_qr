# services/upload_service.py
from __future__ import annotations
from typing import Dict, Set, List, Tuple
import pandas as pd
from sqlalchemy.engine import Engine

from utils.upload_utils import normalize_upload_df, validate_rows, coerce_schema


def get_table_columns(engine: Engine, table: str = "event_payment") -> list[str]:
    # still useful in some contexts, but we won't use this for inserts anymore
    with engine.connect() as conn:
        cols = pd.read_sql(f"SELECT * FROM {table} LIMIT 0", conn).columns.tolist()
    return cols


def get_insertable_columns(engine: Engine, table: str = "event_payment") -> List[str]:
    """
    Only columns that Postgres will accept in an INSERT:
    - NOT generated (is_generated = 'NEVER')
    - NOT identity (is_identity = 'NO')
    """
    sql = """
    SELECT column_name
    FROM information_schema.columns
    WHERE table_name = %(table)s
      AND (is_generated = 'NEVER' OR is_generated IS NULL)
      AND (is_identity = 'NO' OR is_identity IS NULL)
    ORDER BY ordinal_position
    """
    with engine.connect() as conn:
        rows = pd.read_sql(sql, conn, params={"table": table})
    cols = rows["column_name"].tolist()

    # Optional safety: explicitly drop known computed / system columns if present
    # (helps in older PG versions or if information_schema flags are missing)
    exclude = {"id", "all_attendees_checked_in"}
    return [c for c in cols if c not in exclude]


def load_existing_txn_ids(engine: Engine, table: str = "event_payment") -> Set[str]:
    with engine.connect() as conn:
        existing = pd.read_sql(f"SELECT transaction_id FROM {table}", conn)
    return set(existing["transaction_id"].astype(str)) if not existing.empty else set()


def dedup_new_rows(df: pd.DataFrame, existing_ids: Set[str]) -> pd.DataFrame:
    df = df.copy()
    df["transaction_id"] = df["transaction_id"].astype(str)
    return df[~df["transaction_id"].isin(existing_ids)].copy()


def insert_rows(engine: Engine, df_new: pd.DataFrame, table: str = "event_payment") -> int:
    if df_new.empty:
        return 0
    df_new.to_sql(table, engine, if_exists="append", index=False, method="multi")
    return len(df_new)


def ingest_excel(engine: Engine, file_like, table: str = "event_payment") -> Dict:
    """
    Orchestrates: read → normalize → validate → dedup → coerce_schema(insertable_cols) → insert.
    """
    summary = {"inserted": 0, "skipped_existing": 0, "errors": [], "preview": None}

    df_raw = pd.read_excel(file_like)
    if df_raw.empty:
        summary["errors"].append("Uploaded file is empty.")
        return summary

    df_norm = normalize_upload_df(df_raw)
    df_valid, errs = validate_rows(df_norm)
    if errs:
        summary["errors"].extend(errs)
    if df_valid.empty:
        return summary

    existing_ids = load_existing_txn_ids(engine, table=table)
    df_new = dedup_new_rows(df_valid, existing_ids)
    summary["skipped_existing"] = len(df_valid) - len(df_new)
    if df_new.empty:
        return summary

    # ✅ Use only truly insertable columns
    insertable_cols = get_insertable_columns(engine, table=table)
    df_ready = coerce_schema(df_new, insertable_cols)

    inserted = insert_rows(engine, df_ready, table=table)
    summary["inserted"] = inserted
    summary["preview"] = df_ready.head(5)
    return summary
