import streamlit as st

@st.cache_resource
def get_server_store():
    return {
        "ck": None, "cp": None, "tg": None, "tg_grp": None,
        "tg_grp2": None, "tg_grp3": None, "agreed": False,
        "scan_data": None, "scan_ts": 0, "scan_str": "",
        "google_key": None,
    }
