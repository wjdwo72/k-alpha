import streamlit as st
import streamlit.components.v1 as components
import requests, json, os, base64, urllib3
urllib3.disable_warnings()

st.set_page_config(page_title="K-ALPHA Terminal", page_icon="📈",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""<style>
  #MainMenu,header,footer{visibility:hidden}
  .block-container{padding:0!important;margin:0!important;max-width:100%!important}
  .stApp{background:#020408}
  div[data-testid="stExpander"]{background:#0a0e1a;border:1px solid #1a2535!important;border-radius:8px;margin-bottom:6px}
  div[data-testid="stExpander"] summary{color:#00d4ff;font-family:monospace;font-size:13px}
  .stTextInput>div>div>input{background:#0d1220!important;color:#e2e8f0!important;border-color:#1a2535!important;font-family:monospace!important}
  .stButton>button{font-family:monospace}
  .stRadio>div{flex-direction:row;gap:10px}
</style>""", unsafe_allow_html=True)

PASSWORD = "4545"

for k,v in [("auth",False),("wrong",False),("kis_token",None),
            ("kis_base_url",None),("kis_ak",""),("kis_sec",""),("kis_acc",""),
            ("kis_env","실전투자"),("pin_msg",""),("pin_msg_ok",True),
            ("load_ak",""),("load_sec",""),("load_acc",""),("load_env","실전투자")]:
    if k not in st.session_state: st.session_state[k]=v

# ── XOR 암호화 ──
def xor_enc(text, pin):
    return ''.join(chr(ord(c) ^ ord(pin[i%4])) for i,c in enumerate(text))

def save_encode(ak, sec, acc, env, pin):
    payload = json.dumps({"ak":ak,"sec":sec,"acc":acc,"env":env})
    try: return base64.b64encode(xor_enc(payload,pin).encode('latin-1')).decode()
    except: return None

def load_decode(code, pin):
    try:
        raw = base64.b64decode(code).decode('latin-1')
        return json.loads(xor_enc(raw, pin))
    except: return None

# ────────────────────────────────────────
# 비밀번호 화면
# ────────────────────────────────────────
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
.nb{{padding:16px 0;border-radius:10px;border:1px solid #1a2535;background:#0d1220;color:#e2e8f0;font-family:'Share Tech Mono',monospace;font-size:18px;cursor:pointer;text-align:center;transition:all .15s;-webkit-tap-highlight-color:transparent;user-select:none}}
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
    c1,c2,c3=st.columns([1,2,1])
    with c2:
        pi=st.text_input("PIN",key="pin_field",type="password",max_chars=4,label_visibility="collapsed")
        if st.button("확인",key="pin_btn",use_container_width=True):
            if pi==PASSWORD: st.session_state.auth=True; st.session_state.wrong=False; st.rerun()
            else: st.session_state.wrong=True; st.rerun()
    st.stop()

# ────────────────────────────────────────
# KIS API 연결 패널
# ────────────────────────────────────────
label = (f"🔑 KIS API  ✅ {st.session_state.kis_env} 연결됨"
         if st.session_state.kis_token else "🔑 KIS API 연결 ▾")

with st.expander(label, expanded=not bool(st.session_state.kis_token)):

    # ── 간편비번 저장/불러오기 (localStorage 기반) ──
    components.html(f"""
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:transparent; font-family:'Share Tech Mono',monospace; }}
  .pin-wrap {{ background:#0a0e1a; border:1px solid #1a2535; border-radius:8px;
               padding:10px 12px; margin-bottom:2px; }}
  .pin-title {{ font-size:10px; color:#4a5568; letter-spacing:1px; margin-bottom:8px; }}
  .pin-row {{ display:flex; gap:6px; align-items:center; }}
  .pin-input {{ flex:0 0 120px; padding:8px 10px; background:#0d1220; border:1px solid #1a2535;
                border-radius:6px; color:#e2e8f0; font-family:'Share Tech Mono',monospace;
                font-size:14px; letter-spacing:8px; text-align:center; outline:none; width:120px; }}
  .pin-input:focus {{ border-color:#00d4ff; }}
  .btn {{ flex:1; padding:8px 6px; border-radius:6px; border:none; cursor:pointer;
           font-family:'Share Tech Mono',monospace; font-size:11px; transition:all .15s;
           -webkit-tap-highlight-color:transparent; }}
  .btn-save {{ background:rgba(0,212,255,.12); border:1px solid rgba(0,212,255,.35); color:#00d4ff; }}
  .btn-save:active {{ background:rgba(0,212,255,.25); }}
  .btn-load {{ background:rgba(0,255,136,.1); border:1px solid rgba(0,255,136,.3); color:#00ff88; }}
  .btn-load:active {{ background:rgba(0,255,136,.2); }}
  .btn-del  {{ flex:0 0 36px; background:rgba(255,77,109,.08); border:1px solid rgba(255,77,109,.2);
               color:#ff4d6d; font-size:14px; }}
  .msg {{ font-size:10px; margin-top:6px; min-height:14px; letter-spacing:.5px; }}
  .has-saved {{ font-size:10px; color:#ffc800; margin-bottom:4px; letter-spacing:.5px; }}
</style>
<div class="pin-wrap">
  <div class="pin-title">🔒 간편비번으로 API 키 저장/불러오기</div>
  <div class="has-saved" id="has-saved"></div>
  <div class="pin-row">
    <input type="password" class="pin-input" id="pin" placeholder="····"
           maxlength="4" inputmode="numeric" oninput="this.value=this.value.replace(/\\D/g,'')">
    <button class="btn btn-save" onclick="doSave()">💾 저장</button>
    <button class="btn btn-load" onclick="doLoad()">📂 불러오기</button>
    <button class="btn btn-del"  onclick="doDel()" title="삭제">🗑</button>
  </div>
  <div class="msg" id="msg"></div>
</div>

<script>
const STORAGE_KEY = 'k_alpha_api_v2';
const CHECK_KEY   = 'k_alpha_pin_chk';

function xorEnc(str, pin) {{
  return str.split('').map((c,i) =>
    String.fromCharCode(c.charCodeAt(0) ^ pin.charCodeAt(i%4))
  ).join('');
}}

function showMsg(txt, ok) {{
  const el = document.getElementById('msg');
  el.textContent = txt;
  el.style.color = ok ? '#00ff88' : '#ff4d6d';
  setTimeout(() => el.textContent = '', 3000);
}}

function checkHasSaved() {{
  const saved = localStorage.getItem(STORAGE_KEY);
  const el = document.getElementById('has-saved');
  if (saved) {{ el.textContent = '💾 저장된 키 있음 — PIN 입력 후 불러오기 클릭'; }}
  else {{ el.textContent = ''; }}
}}
checkHasSaved();

function getParentInputs() {{
  try {{
    const inputs = window.parent.document.querySelectorAll('[data-testid="stTextInput"] input');
    return inputs;
  }} catch(e) {{ return null; }}
}}

function setReactInput(input, value) {{
  try {{
    const setter = Object.getOwnPropertyDescriptor(window.parent.HTMLInputElement.prototype,'value').set;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {{bubbles:true}}));
    input.dispatchEvent(new Event('change', {{bubbles:true}}));
  }} catch(e) {{}}
}}

function doSave() {{
  const pin = document.getElementById('pin').value;
  if (!/^\\d{{4}}$/.test(pin)) {{ showMsg('❌ 4자리 숫자 입력', false); return; }}

  // 부모 프레임 입력값 읽기
  const inputs = getParentInputs();
  if (!inputs || inputs.length < 3) {{ showMsg('❌ 입력값을 먼저 입력하세요', false); return; }}

  // 앱키, 시크릿, 계좌번호 순서로 읽기 (password 타입 포함)
  let ak='', sec='', acc='';
  let idx = 0;
  inputs.forEach(inp => {{
    const val = inp.value;
    if (!val) return;
    if (idx===0) {{ ak=val; idx++; }}
    else if (idx===1) {{ sec=val; idx++; }}
    else if (idx===2) {{ acc=val; idx++; }}
  }});

  if (!ak || !sec) {{ showMsg('❌ 앱키/시크릿이 비어있습니다', false); return; }}

  // 서버 환경 읽기
  let env = '실전투자';
  try {{
    const radios = window.parent.document.querySelectorAll('[data-testid="stRadio"] label');
    radios.forEach(r => {{ if (r.querySelector('input:checked')) env = r.textContent.trim(); }});
  }} catch(e) {{}}

  const payload = JSON.stringify({{ak, sec, acc, env}});
  try {{
    const encoded = btoa(xorEnc(payload, pin).split('').map(c=>c.charCodeAt(0).toString(16).padStart(2,'0')).join(''));
    localStorage.setItem(STORAGE_KEY, encoded);
    localStorage.setItem(CHECK_KEY, btoa(pin+':kalpha'));
    checkHasSaved();
    showMsg('✅ 저장 완료', true);
  }} catch(e) {{ showMsg('❌ 저장 실패', false); }}
}}

function doLoad() {{
  const pin = document.getElementById('pin').value;
  if (!/^\\d{{4}}$/.test(pin)) {{ showMsg('❌ 4자리 숫자 입력', false); return; }}

  const saved = localStorage.getItem(STORAGE_KEY);
  const chk   = localStorage.getItem(CHECK_KEY);
  if (!saved) {{ showMsg('❌ 저장된 키 없음', false); return; }}
  if (chk && atob(chk) !== pin+':kalpha') {{ showMsg('❌ PIN 틀림', false); return; }}

  try {{
    const hexStr = atob(saved);
    const bytes = [];
    for (let i=0; i<hexStr.length; i+=2) bytes.push(parseInt(hexStr.substr(i,2),16));
    const decoded = xorEnc(bytes.map(b=>String.fromCharCode(b)).join(''), pin);
    const data = JSON.parse(decoded);

    // 부모 프레임 입력에 값 주입
    const inputs = getParentInputs();
    if (inputs && inputs.length >= 3) {{
      let idx2=0;
      inputs.forEach(inp => {{
        if (idx2===0) {{ setReactInput(inp, data.ak||''); idx2++; }}
        else if (idx2===1) {{ setReactInput(inp, data.sec||''); idx2++; }}
        else if (idx2===2 && inp.type!=='password') {{ setReactInput(inp, data.acc||''); idx2++; }}
      }});
    }}

    showMsg('✅ 불러오기 완료 — 연결 버튼을 누르세요', true);
  }} catch(e) {{ showMsg('❌ 복호화 실패 — PIN 확인', false); }}
}}

function doDel() {{
  if (!confirm('저장된 API 키를 삭제할까요?')) return;
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem(CHECK_KEY);
  checkHasSaved();
  showMsg('🗑 삭제 완료', true);
}}
</script>
""", height=115, scrolling=False)

    # ── 서버 환경 ──
    env_label = st.radio("서버", ["실전투자","모의투자"], horizontal=True,
                          index=0 if st.session_state.kis_env=="실전투자" else 1,
                          label_visibility="collapsed")
    base_url = ("https://openapi.koreainvestment.com:9443" if env_label=="실전투자"
                else "https://openapivts.koreainvestment.com:29443")

    # ── 입력 필드 ──
    c1,c2 = st.columns(2)
    with c1: ak  = st.text_input("앱키", type="password",
                                  value=st.session_state.kis_ak, placeholder="PSxxxxxxxx...")
    with c2: sec = st.text_input("시크릿", type="password", value=st.session_state.kis_sec)
    acc = st.text_input("계좌번호", value=st.session_state.kis_acc, placeholder="69108332-01")

    # ── 연결 버튼 ──
    c1,c2 = st.columns([3,1])
    with c1:
        if st.button("🔗 KIS API 연결", use_container_width=True, type="primary"):
            if not ak or not sec or not acc:
                st.error("앱키 · 시크릿 · 계좌번호를 모두 입력하세요")
            else:
                with st.spinner("KIS 서버 연결 중..."):
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
    with c2:
        if st.session_state.kis_token:
            if st.button("해제", use_container_width=True):
                st.session_state.kis_token=None; st.rerun()

    if st.session_state.kis_token:
        st.success(f"✅ {st.session_state.kis_env} 연결됨 · {acc}")

    with st.expander("🔒 로그아웃"):
        if st.button("로그아웃", use_container_width=True):
            for k in ["auth","kis_token","kis_ak","kis_sec","kis_acc"]:
                st.session_state[k]=False if k=="auth" else None if k=="kis_token" else ""
            st.rerun()

# ── HTML 터미널 ──
if not os.path.exists("app.html"):
    st.error("app.html 파일을 GitHub 저장소에 업로드하세요.")
    st.stop()

with open("app.html","r",encoding="utf-8") as f:
    html = f.read()

if st.session_state.kis_token:
    token    = st.session_state.kis_token
    base_url = st.session_state.kis_base_url
    ak       = st.session_state.kis_ak
    sec      = st.session_state.kis_sec

    # ── Python 서버사이드 현재가 조회 (CORS 없음) ──
    KR_CODES = ['009150','066570','005490','005380','105560',
                '011070','247540','068270','000660','035720',
                '006400','012450','267260','035420','096770']

    @st.cache_data(ttl=30, show_spinner=False)
    def fetch_all_prices(token, base_url, ak, sec):
        prices = {}
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": ak, "appsecret": sec,
            "tr_id": "FHKST01010100",
            "Content-Type": "application/json"
        }
        for code in KR_CODES:
            try:
                r = requests.get(
                    f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
                    params={"FID_COND_MRKT_DIV_CODE":"J","FID_INPUT_ISCD":code},
                    headers=headers, verify=False, timeout=6
                )
                o = r.json().get("output",{})
                if not o.get("stck_prpr"): continue
                sign = o.get("prdy_vrss_sign","3")
                is_down = sign in ("4","5")
                chg_abs = int(o.get("prdy_vrss","0") or 0)
                pct_abs = float(o.get("prdy_ctrt","0") or 0)
                chg = -chg_abs if is_down else chg_abs
                pct = -pct_abs if is_down else pct_abs
                prices[code] = {
                    "price": int(o["stck_prpr"]),
                    "change": chg, "changePct": round(pct,2),
                    "up": not is_down,
                    "high": int(o.get("stck_hgpr","0") or 0),
                    "low":  int(o.get("stck_lwpr","0") or 0),
                }
            except: pass
        return prices

    with st.spinner("현재가 조회 중..."):
        prices = fetch_all_prices(token, base_url, ak, sec)

    inject = f"""<script>
window.__KIS_TOKEN__    = {json.dumps(token)};
window.__KIS_BASE_URL__ = {json.dumps(base_url)};
window.__KIS_AK__       = {json.dumps(ak)};
window.__KIS_SEC__      = {json.dumps(sec)};
window.__KIS_ACC__      = {json.dumps(st.session_state.kis_acc)};
window.__KIS_PRICES__   = {json.dumps(prices)};
</script>"""
    html = html.replace("</head>", inject+"\n</head>")

components.html(html, height=1400, scrolling=True)
