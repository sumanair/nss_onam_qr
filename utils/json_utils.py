# utils/json_utils.py
import datetime
import pandas as pd
import decimal
import numpy as np

def to_jsonable(value):
    """Convert common non-JSON-serializable types to safe JSON values."""
    if isinstance(value, pd.Timestamp):
        return value.tz_localize(None).isoformat()
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)  # or float(value)
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return value
