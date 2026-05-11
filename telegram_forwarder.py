import streamlit as st
import requests
import time
import json
from datetime import datetime

st.set_page_config(page_title="Telegram Forwarder", page_icon="📨", layout="centered")

# ── Secrets에서 설정 불러오기 ──
BOT_TOKEN   = st.secrets["BOT_TOKEN"]       # 봇 토큰
GROUP_ID    = st.secrets["GROUP_ID"]        # 그룹채팅 ID (예: -1001234567890)
ALLOWED_IDS = st.secrets.get("ALLOWED_IDS", "")  # 허용된 발신자 chat_id (콤마 구분, 선택)

allowed_list = [x.strip() for x in str(ALLOWED_IDS).split(",") if x.strip()]

# ── 상태 초기화 ──
if "last_update_id" not in st.session_state:
    st.session_state.last_update_id = 0
if "log" not in st.session_state:
    st.session_state.log = []

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

def get_updates(offset=0):
    try:
        r = requests.get(f"{BASE}/getUpdates",
                         params={"offset": offset, "timeout": 5},
                         timeout=10)
        return r.json().get("result", [])
    except:
        return []

def forward_to_group(text, from_name, from_id):
    header = f"📨 <b>새 메시지</b>\n👤 {from_name} (<code>{from_id}</code>)\n🕐 {datetime.now().strftime('%H:%M:%S')}\n─────────────\n"
    payload = {
        "chat_id": GROUP_ID,
        "text": header + text,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(f"{BASE}/sendMessage", json=payload, timeout=10)
        return r.json().get("ok", False)
    except:
        return False

def send_reply(chat_id, text):
    """봇이 원래 발신자에게 자동 응답"""
    try:
        requests.post(f"{BASE}/sendMessage",
                      json={"chat_id": chat_id,
                            "text": f"✅ 메시지가 전달되었습니다.\n\n내용: {text}"},
                      timeout=10)
    except:
        pass

# ── UI ──
st.title("📨 Telegram 메시지 포워더")
st.caption("봇에게 온 메시지를 그룹채팅으로 자동 전달합니다.")

col1, col2, col3 = st.columns(3)
col1.metric("전달된 메시지", len(st.session_state.log))
col2.metric("마지막 업데이트 ID", st.session_state.last_update_id)
col3.metric("그룹 ID", GROUP_ID)

st.divider()

# 자동 새로고침 (10초 간격)
refresh_interval = st.slider("새로고침 간격 (초)", 5, 60, 10, key="interval")

if st.button("▶ 지금 바로 확인", use_container_width=True):
    updates = get_updates(st.session_state.last_update_id + 1)
    new_count = 0
    for upd in updates:
        uid = upd.get("update_id", 0)
        if uid > st.session_state.last_update_id:
            st.session_state.last_update_id = uid

        msg = upd.get("message") or upd.get("channel_post")
        if not msg:
            continue

        text      = msg.get("text", "")
        from_id   = str(msg.get("chat", {}).get("id", ""))
        from_name = (msg.get("chat", {}).get("first_name", "") + " " +
                     msg.get("chat", {}).get("last_name", "")).strip()
        if not from_name:
            from_name = msg.get("chat", {}).get("username", "알 수 없음")

        if not text:
            continue

        # 허용 목록 필터 (설정 시)
        if allowed_list and from_id not in allowed_list:
            continue

        # 그룹으로 전달
        ok = forward_to_group(text, from_name, from_id)
        if ok:
            new_count += 1
            log_entry = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "from": from_name,
                "id": from_id,
                "text": text[:80],
                "status": "✅ 전달됨"
            }
            st.session_state.log.insert(0, log_entry)
            # 자동 응답 (선택)
            send_reply(from_id, text[:50])

    st.success(f"{new_count}개 메시지 전달 완료!" if new_count else "새 메시지 없음")

st.divider()
st.subheader("📋 전달 로그")
if st.session_state.log:
    for entry in st.session_state.log[:30]:  # 최근 30개
        st.markdown(
            f"`{entry['time']}` **{entry['from']}** (`{entry['id']}`): "
            f"{entry['text']} {entry['status']}"
        )
else:
    st.info("아직 전달된 메시지가 없습니다.")

# 자동 새로고침
time.sleep(refresh_interval)
st.rerun()
