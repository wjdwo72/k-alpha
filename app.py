import streamlit as st
import streamlit.components.v1 as components
import requests, json, os, urllib3
urllib3.disable_warnings()

st.set_page_config(page_title="K-ALPHA Terminal", page_icon="📈",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
  #MainMenu, header, footer { visibility: hidden; }
  .block-container { padding: 0 !important; margin: 0 !important; max-width: 100% !important; }
  .stApp { background: #020408; }
</style>""", unsafe_allow_html=True)

PASSWORD = "4545"

for k, v in [("auth",False),("wrong",False),("kis_token",None),
             ("kis_base_url",None),("kis_ak",""),("kis_sec",""),("kis_acc",""),("kis_env","실전투자")]:
    if k not in st.session_state: st.session_state[k] = v

# ── 비밀번호 화면 ──
if not st.session_state.auth:
    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=Share+Tech+Mono&display=swap');
body,.stApp{{background:#020408!important}}
.lw{{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;background:#020408;font-family:'Share Tech Mono',monospace}}
.lt{{font-family:'Orbitron',monospace;font-size:clamp(22px,6vw,40px);font-weight:700;letter-spacing:6px;background:linear-gradient(90deg,#00d4ff,#00ff88);-webkit-background-clip:text;-webkit-text-fill-color:transparent;text-align:center;margin-bottom:4px}}
.ls{{font-size:11px;color:#4a5568;letter-spacing:2px;margin-bottom:36px;text-align:center}}
.lb{{background:#0a0e1a;border:1px solid #1a2535;border-radius:16px;padding:32px 28px 24px;width:min(320px,92vw);box-shadow:0 0 40px rgba(0,212,255,.08)}}
.ll{{font-size:11px;color:#4a5568;letter-spacing:2px;margin-bottom:10px;text-align:center}}
.ld{{display:flex;justify-content:center;gap:14px;margin-bottom:24px}}
.dot{{width:13px;height:13px;border-radius:50%;border:2px solid #1a3a4a;background:transparent}}
.dot.f{{background:#00d4ff;border-color:#00d4ff;box-shadow:0 0 8px rgba(0,212,255,.6)}}
.np{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}
.nb{{padding:16px 0;border-radius:10px;border:1px solid #1a2535;background:#0d1220;color:#e2e8f0;font-family:'Share Tech Mono',monospace;font-size:18px;cursor:pointer;text-align:center;transition:all .15s;-webkit-tap-highlight-color:transparent}}
.nb:active{{background:#1a2535;transform:scale(.95)}}
.nb.d{{font-size:15px;color:#64748b}}.nb.e{{visibility:hidden}}
.le{{text-align:center;color:#ff4d6d;font-size:11px;margin-top:14px;min-height:16px}}
</style>
<div class="lw">
  <div class="lt">K · ALPHA</div>
  <div class="ls">TRADING TERMINAL · SECURE ACCESS</div>
  <div class="lb">
    <div class="ll">🔒 PIN 번호 입력</div>
    <div class="ld"><div class="dot" id="d0"></div><div class="dot" id="d1"></div><div class="dot" id="d2"></div><div class="dot" id="d3"></div></div>
    <div class="np">
      {''.join([f'<div class="nb" onclick="pp({i})">{i}</div>' for i in [1,2,3,4,5,6,7,8,9]])}
      <div class="nb e"></div><div class="nb" onclick="pp(0)">0</div><div class="nb d" onclick="pd()">⌫</div>
    </div>
    <div class="le" id="le">{"❌ 비밀번호가 틀렸습니다" if st.session_state.wrong else ""}</div>
  </div>
</div>
<script>
let p="";const c="{PASSWORD}";
function pp(n){{if(p.length>=4)return;p+=String(n);ud();if(p.length===4){{setTimeout(()=>{{if(p===c){{document.getElementById("ph").value=p;document.getElementById("ps").click();}}else{{document.getElementById("le").textContent="❌ 비밀번호가 틀렸습니다";document.querySelectorAll(".dot").forEach(d=>{{d.style.background="#ff4d6d";d.style.borderColor="#ff4d6d";}});setTimeout(()=>{{p="";ud();document.getElementById("le").textContent="";}},700);}}}},100);}}}}
function pd(){{p=p.slice(0,-1);ud();}}
function ud(){{for(let i=0;i<4;i++){{const d=document.getElementById("d"+i);if(i<p.length){{d.classList.add("f");d.style.background="";d.style.borderColor="";}}else{{d.classList.remove("f");d.style.background="";d.style.borderColor="";}}}}}}
document.addEventListener("keydown",e=>{{if(e.key>="0"&&e.key<="9")pp(parseInt(e.key));if(e.key==="Backspace")pd();}});
</script>""", unsafe_allow_html=True)

    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        pi = st.text_input("PIN", key="pin_field", type="password", max_chars=4, label_visibility="collapsed")
        if st.button("확인", key="pin_btn", use_container_width=True):
            if pi == PASSWORD:
                st.session_state.auth = True; st.session_state.wrong = False; st.rerun()
            else:
                st.session_state.wrong = True; st.rerun()
    st.stop()

# ── 사이드바 KIS API (Python 서버사이드 — CORS 없음) ──
with st.sidebar:
    st.markdown("### 🔑 KIS API")
    st.caption("Streamlit 서버 직접 연결 (CORS 우회)")

    env_label = st.radio("서버", ["실전투자","모의투자"], horizontal=True,
                          index=0 if st.session_state.kis_env=="실전투자" else 1,
                          label_visibility="collapsed")
    base_url = ("https://openapi.koreainvestment.com:9443" if env_label=="실전투자"
                else "https://openapivts.koreainvestment.com:29443")

    ak  = st.text_input("앱키", type="password", value=st.session_state.kis_ak)
    sec = st.text_input("시크릿", type="password", value=st.session_state.kis_sec)
    acc = st.text_input("계좌번호", value=st.session_state.kis_acc, placeholder="69108332-01")

    if st.button("🔗 연결", use_container_width=True, type="primary"):
        if not ak or not sec or not acc:
            st.error("모두 입력하세요")
        else:
            with st.spinner("토큰 발급 중..."):
                try:
                    r = requests.post(f"{base_url}/oauth2/tokenP",
                        json={"grant_type":"client_credentials","appkey":ak,"appsecret":sec},
                        verify=False, timeout=12)
                    d = r.json()
                    if d.get("access_token"):
                        st.session_state.kis_token    = d["access_token"]
                        st.session_state.kis_base_url = base_url
                        st.session_state.kis_ak  = ak
                        st.session_state.kis_sec = sec
                        st.session_state.kis_acc = acc
                        st.session_state.kis_env = env_label
                        st.success("✅ 연결 성공!")
                        st.rerun()
                    else:
                        st.error(f"❌ {d.get('msg1','앱키/시크릿 오류')}")
                except Exception as e:
                    st.error(f"❌ {str(e)[:100]}")

    if st.session_state.kis_token:
        st.success(f"✅ {st.session_state.kis_env} 연결됨")
        if st.button("연결 해제"): st.session_state.kis_token=None; st.rerun()

    st.divider()
    if st.button("🔒 로그아웃"):
        st.session_state.auth=False; st.session_state.kis_token=None; st.rerun()

# ── 메인 HTML ──
if not os.path.exists("app.html"):
    st.error("app.html 파일이 없습니다. GitHub 저장소에 업로드하세요.")
    st.stop()

with open("app.html","r",encoding="utf-8") as f:
    html = f.read()

# KIS 토큰 주입
if st.session_state.kis_token:
    inject = f"""<script>
window.__KIS_TOKEN__    = {json.dumps(st.session_state.kis_token)};
window.__KIS_BASE_URL__ = {json.dumps(st.session_state.kis_base_url)};
window.__KIS_AK__       = {json.dumps(st.session_state.kis_ak)};
window.__KIS_SEC__      = {json.dumps(st.session_state.kis_sec)};
window.__KIS_ACC__      = {json.dumps(st.session_state.kis_acc)};
</script>"""
    html = html.replace("</head>", inject+"\n</head>")

components.html(html, height=1300, scrolling=True)
