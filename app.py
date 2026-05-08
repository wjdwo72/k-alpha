import streamlit as st
import streamlit.components.v1 as components
import os

# ── 페이지 설정 ──
st.set_page_config(
    page_title="K-ALPHA Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── 전체 여백/패딩 제거 ──
st.markdown("""
<style>
  #MainMenu, header, footer { visibility: hidden; }
  .block-container { padding: 0 !important; margin: 0 !important; max-width: 100% !important; }
  [data-testid="stAppViewContainer"] { background: #020408; }
  .stApp { background: #020408; }
</style>
""", unsafe_allow_html=True)

PASSWORD = "4545"

# ── 세션 초기화 ──
if "auth" not in st.session_state:
    st.session_state.auth = False
if "wrong" not in st.session_state:
    st.session_state.wrong = False

# ─────────────────────────────────────────
# 비밀번호 화면
# ─────────────────────────────────────────
if not st.session_state.auth:
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=Share+Tech+Mono&display=swap');
    body, .stApp {{ background:#020408 !important; }}

    .lock-wrap {{
        display:flex; flex-direction:column; align-items:center; justify-content:center;
        min-height:100vh; background:#020408;
        font-family:'Share Tech Mono',monospace;
    }}
    .lock-title {{
        font-family:'Orbitron',monospace; font-size:clamp(22px,6vw,42px);
        font-weight:700; letter-spacing:6px;
        background:linear-gradient(90deg,#00d4ff,#00ff88);
        -webkit-background-clip:text; -webkit-text-fill-color:transparent;
        margin-bottom:6px; text-align:center;
    }}
    .lock-sub {{
        font-size:11px; color:#4a5568; letter-spacing:2px;
        margin-bottom:40px; text-align:center;
    }}
    .lock-box {{
        background:#0a0e1a; border:1px solid #1a2535;
        border-radius:16px; padding:36px 32px 28px;
        width:min(340px,90vw); box-shadow:0 0 40px rgba(0,212,255,0.08);
    }}
    .lock-label {{
        font-size:11px; color:#4a5568; letter-spacing:2px;
        margin-bottom:10px; text-align:center;
    }}
    .lock-dots {{
        display:flex; justify-content:center; gap:16px; margin-bottom:28px;
    }}
    .lock-dot {{
        width:14px; height:14px; border-radius:50%;
        border:2px solid #1a3a4a; background:transparent;
        transition:all 0.2s;
    }}
    .lock-dot.filled {{ background:#00d4ff; border-color:#00d4ff;
        box-shadow:0 0 8px rgba(0,212,255,0.6); }}
    .lock-numpad {{
        display:grid; grid-template-columns:repeat(3,1fr); gap:10px;
    }}
    .lock-btn {{
        padding:18px 0; border-radius:10px; border:1px solid #1a2535;
        background:#0d1220; color:#e2e8f0;
        font-family:'Share Tech Mono',monospace; font-size:18px;
        cursor:pointer; text-align:center; transition:all 0.15s;
        -webkit-tap-highlight-color:transparent;
    }}
    .lock-btn:active {{ background:#1a2535; transform:scale(0.95); }}
    .lock-btn.del {{ font-size:16px; color:#64748b; }}
    .lock-btn.empty {{ visibility:hidden; }}
    .lock-error {{
        text-align:center; color:#ff4d6d; font-size:11px;
        margin-top:16px; letter-spacing:1px; min-height:16px;
    }}
    </style>

    <div class="lock-wrap">
        <div class="lock-title">K · ALPHA</div>
        <div class="lock-sub">TRADING TERMINAL · SECURE ACCESS</div>
        <div class="lock-box">
            <div class="lock-label">🔒 PIN 번호 입력</div>
            <div class="lock-dots" id="dots">
                <div class="lock-dot" id="d0"></div>
                <div class="lock-dot" id="d1"></div>
                <div class="lock-dot" id="d2"></div>
                <div class="lock-dot" id="d3"></div>
            </div>
            <div class="lock-numpad">
                {''.join([f'<div class="lock-btn" onclick="pinPress({i})">{i}</div>' for i in [1,2,3,4,5,6,7,8,9]])}
                <div class="lock-btn empty"></div>
                <div class="lock-btn" onclick="pinPress(0)">0</div>
                <div class="lock-btn del" onclick="pinDel()">⌫</div>
            </div>
            <div class="lock-error" id="lock-err">{"❌ 비밀번호가 틀렸습니다" if st.session_state.wrong else ""}</div>
        </div>
    </div>

    <script>
    let pin = "";
    const correct = "{PASSWORD}";

    function pinPress(n) {{
        if (pin.length >= 4) return;
        pin += String(n);
        updateDots();
        if (pin.length === 4) {{
            setTimeout(() => {{
                if (pin === correct) {{
                    // Streamlit hidden input으로 전달
                    document.getElementById("pin-hidden").value = pin;
                    document.getElementById("pin-submit").click();
                }} else {{
                    document.getElementById("lock-err").textContent = "❌ 비밀번호가 틀렸습니다";
                    document.querySelectorAll(".lock-dot").forEach(d => {{
                        d.style.background = "#ff4d6d";
                        d.style.borderColor = "#ff4d6d";
                        d.style.boxShadow = "0 0 8px rgba(255,77,109,0.6)";
                    }});
                    setTimeout(() => {{ pin = ""; updateDots(); document.getElementById("lock-err").textContent = ""; }}, 700);
                }}
            }}, 100);
        }}
    }}

    function pinDel() {{
        pin = pin.slice(0,-1);
        updateDots();
    }}

    function updateDots() {{
        for(let i=0;i<4;i++) {{
            const d = document.getElementById("d"+i);
            if(i < pin.length) {{
                d.classList.add("filled");
                d.style.background = ""; d.style.borderColor = ""; d.style.boxShadow = "";
            }} else {{
                d.classList.remove("filled");
                d.style.background = ""; d.style.borderColor = ""; d.style.boxShadow = "";
            }}
        }}
    }}

    // 키보드 지원
    document.addEventListener("keydown", e => {{
        if (e.key >= "0" && e.key <= "9") pinPress(parseInt(e.key));
        if (e.key === "Backspace") pinDel();
    }});
    </script>
    """, unsafe_allow_html=True)

    # 숨겨진 Streamlit 입력
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        pin_input = st.text_input("PIN", key="pin_field", type="password",
                                   max_chars=4, label_visibility="collapsed")
        if st.button("확인", key="pin_btn", use_container_width=True):
            if pin_input == PASSWORD:
                st.session_state.auth = True
                st.session_state.wrong = False
                st.rerun()
            else:
                st.session_state.wrong = True
                st.rerun()

# ─────────────────────────────────────────
# 메인 터미널
# ─────────────────────────────────────────
else:
    html_file = "app.html"
    if not os.path.exists(html_file):
        st.error(f"'{html_file}' 파일을 찾을 수 없습니다. GitHub 저장소에 업로드하세요.")
        st.stop()

    with open(html_file, "r", encoding="utf-8") as f:
        html_content = f.read()

    components.html(html_content, height=1000, scrolling=True)

    # 로그아웃
    with st.sidebar:
        st.markdown("### K-ALPHA")
        if st.button("🔒 로그아웃"):
            st.session_state.auth = False
            st.rerun()
