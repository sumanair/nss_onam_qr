import streamlit as st

def put_qr_bytes(txn: str, data: bytes):
    st.session_state.setdefault("qr_bytes", {})[txn] = data

def get_qr_bytes(txn: str) -> bytes | None:
    return (st.session_state.get("qr_bytes") or {}).get(txn)

def drop_qr_bytes(txn: str):
    (st.session_state.get("qr_bytes") or {}).pop(txn, None)
