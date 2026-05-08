import streamlit as st
import streamlit.components.v1 as components
import requests, json, os, base64, urllib3, time
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
KR_CODES = ['009150','066570','005490','005380','105560',
            '011070','247540','068270','000660','035720',
            '006400','012450','267260','035420','096770']

for k,v in [("auth",False),("wrong",False),("kis_token",None),("kis_base_url",None),
            ("kis_ak",""),("kis_sec",""),("kis_acc",""),("kis_env","실전투자"),
            ("saved_creds",""),("saved_pin_chk",""),("save_msg",""),("load_msg","")]:
    if k not in st.session_state: st.session_state[k]=v

# ── PIN 암호화 (Python) ──
def py_xor(text, pin):
    pb = pin.encode()
    return bytes([ord(c)^pb[i%4] for i,c in enumerate(text)])

def py_save(ak,sec,acc,env,pin):
    payload = json.dumps({'ak':ak,'sec':sec,'acc':acc,'env':env})
    return base64.b64encode(py_xor(payload,pin)).decode()

def py_load(encoded, pin):
    raw = base64.b64decode(encoded)
    pb = pin.encode()
    dec = ''.join(chr(b^pb[i%4]) for i,b in enumerate(raw))
    return json.loads(dec)

# ── KIS 현재가 조회 ──
@st.cache_data(ttl=30, show_spinner=False)
def fetch_prices(token, base_url, ak, secret, codes_tuple):
    prices = {}
    headers = {'Content-Type':'application/json','authorization':f'Bearer {token}',
                'appkey':ak,'appsecret':secret,'tr_id':'FHKST01010100'}
    for code in codes_tuple:
        try:
            r = requests.get(f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
                params={'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code},
                headers=headers, verify=False, timeout=5)
            o = r.json().get('output',{})
            if not o.get('stck_prpr'): continue
            sign = o.get('prdy_vrss_sign','3')
            is_dn = sign in ['4','5']
            ca = int(o.get('prdy_vrss',0)); pa = float(o.get('prdy_ctrt',0))
            prices[code] = {'price':int(o['stck_prpr']),'change':-ca if is_dn else ca,
                            'changePct':-pa if is_dn else pa,'up':sign in ['1','2']}
            time.sleep(0.15)
        except: pass
    return prices

# ── KIS 잔고 조회 ──
@st.cache_data(ttl=60, show_spinner=False)
def fetch_balance(token, base_url, ak, secret, acc):
    try:
        acc_no = acc.replace('-','')
        tr_id = 'VTTC8434R' if 'openapivts' in base_url else 'TTTC8434R'
        headers = {'Content-Type':'application/json','authorization':f'Bearer {token}',
                    'appkey':ak,'appsecret':secret,'tr_id':tr_id}
        r = requests.get(f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
            params={'CANO':acc_no[:8],'ACNT_PRDT_CD':acc_no[8:] or '01',
                    'AFHR_FLPR_YN':'N','OFL_YN':'','INQR_DVSN':'02','UNPR_DVSN':'01',
                    'FUND_STTL_ICLD_YN':'N','FNCG_AMT_AUTO_RDPT_YN':'N',
                    'PRCS_DVSN':'01','CTX_AREA_FK100':'','CTX_AREA_NK100':''},
            headers=headers, verify=False, timeout=10)
        return r.json()
    except Exception as e:
        return {'error': str(e)}

# ════════════════════════════════════════════════
# 비밀번호 화면
# ════════════════════════════════════════════════
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
function submit(){{
  // Streamlit text_input 찾아서 값 설정 후 Enter 발송
  const inp=document.querySelector('input[type="password"]');
  if(!inp)return;
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  setter.call(inp,p);
  inp.dispatchEvent(new Event('input',{{bubbles:true}}));
  inp.dispatchEvent(new KeyboardEvent('keydown',{{key:'Enter',code:'Enter',keyCode:13,bubbles:true}}));
  inp.dispatchEvent(new KeyboardEvent('keypress',{{key:'Enter',code:'Enter',keyCode:13,bubbles:true}}));
  inp.dispatchEvent(new KeyboardEvent('keyup',{{key:'Enter',code:'Enter',keyCode:13,bubbles:true}}));
  // 버튼도 클릭
  setTimeout(()=>{{const btn=document.querySelector('button[kind="secondaryFormSubmit"],button');if(btn)btn.click();}},100);
}}
function pp(n){{
  if(p.length>=4)return;p+=String(n);ud();
  if(p.length===4){{setTimeout(()=>{{
    if(p===c){{submit();}}
    else{{
      document.getElementById("le").textContent="❌ 비밀번호가 틀렸습니다";
      document.querySelectorAll(".dot").forEach(d=>{{d.style.background="#ff4d6d";d.style.borderColor="#ff4d6d";}});
      setTimeout(()=>{{p="";ud();document.getElementById("le").textContent="";}},700);
    }}
  }},100);}}
}}
function pd(){{p=p.slice(0,-1);ud();}}
function ud(){{for(let i=0;i<4;i++){{const d=document.getElementById("d"+i);if(i<p.length){{d.classList.add("f");d.style.background="";d.style.borderColor="";}}else{{d.classList.remove("f");d.style.background="";d.style.borderColor="";}}}}}}
document.addEventListener("keydown",e=>{{if(e.key>="0"&&e.key<="9")pp(parseInt(e.key));if(e.key==="Backspace")pd();}});
</script>""", unsafe_allow_html=True)

    with st.form("pin_form", clear_on_submit=True):
        pi = st.text_input("PIN", type="password", max_chars=4,
                            label_visibility="collapsed", key="pin_field")
        submitted = st.form_submit_button("확인", use_container_width=True)
        if submitted:
            if pi == PASSWORD:
                st.session_state.auth = True; st.session_state.wrong = False; st.rerun()
            else:
                st.session_state.wrong = True; st.rerun()
    st.stop()

# ════════════════════════════════════════════════
# KIS API 연결 패널
# ════════════════════════════════════════════════
label = (f"🔑 KIS API  ✅ {st.session_state.kis_env} 연결됨"
         if st.session_state.kis_token else "🔑 KIS API 연결 ▾")

with st.expander(label, expanded=not bool(st.session_state.kis_token)):

    # ── 간편비번 저장/불러오기 (Python 처리) ──
    st.markdown("<div style='background:#0a0e1a;border:1px solid #1a2535;border-radius:8px;padding:10px;margin-bottom:8px'>"
                "<div style='font-family:monospace;font-size:10px;color:#4a5568;margin-bottom:8px'>🔒 간편비번 저장/불러오기</div>",
                unsafe_allow_html=True)

    if st.session_state.saved_creds:
        st.caption("💾 저장된 키 있음")

    pc1,pc2,pc3,pc4 = st.columns([2,1,1,0.5])
    with pc1:
        save_pin = st.text_input("간편비번", type="password", max_chars=4,
                                  placeholder="····", label_visibility="collapsed",
                                  key="save_pin_inp")
    with pc2:
        if st.button("💾 저장", use_container_width=True, key="btn_save"):
            if save_pin and len(save_pin)==4 and save_pin.isdigit():
                ak_v = st.session_state.get('kis_ak_inp','') or st.session_state.kis_ak
                sec_v= st.session_state.get('kis_sec_inp','') or st.session_state.kis_sec
                acc_v= st.session_state.get('kis_acc_inp','') or st.session_state.kis_acc
                env_v= st.session_state.get('kis_env_sel','실전투자') or st.session_state.kis_env
                if ak_v and sec_v:
                    st.session_state.saved_creds   = py_save(ak_v,sec_v,acc_v,env_v,save_pin)
                    st.session_state.saved_pin_chk = base64.b64encode((save_pin+':kalpha').encode()).decode()
                    st.success("✅ 저장 완료")
                else:
                    st.error("앱키/시크릿 먼저 입력")
            else:
                st.error("4자리 숫자")
    with pc3:
        if st.button("📂 불러오기", use_container_width=True, key="btn_load"):
            if save_pin and len(save_pin)==4 and save_pin.isdigit():
                if st.session_state.saved_creds:
                    chk = st.session_state.saved_pin_chk
                    if chk and base64.b64decode(chk).decode() != save_pin+':kalpha':
                        st.error("❌ PIN 틀림")
                    else:
                        try:
                            data = py_load(st.session_state.saved_creds, save_pin)
                            st.session_state.kis_ak  = data['ak']
                            st.session_state.kis_sec = data['sec']
                            st.session_state.kis_acc = data['acc']
                            st.session_state.kis_env = data.get('env','실전투자')
                            st.success("✅ 불러오기 완료")
                            st.rerun()
                        except:
                            st.error("❌ 복호화 실패")
                else:
                    st.error("저장된 키 없음")
            else:
                st.error("4자리 숫자")
    with pc4:
        if st.button("🗑", use_container_width=True, key="btn_del_creds"):
            st.session_state.saved_creds = ""
            st.session_state.saved_pin_chk = ""
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    # ── 서버 환경 ──
    env_label = st.radio("서버", ["실전투자","모의투자"], horizontal=True,
                          index=0 if st.session_state.kis_env=="실전투자" else 1,
                          label_visibility="collapsed", key="kis_env_sel")
    base_url = ("https://openapi.koreainvestment.com:9443" if env_label=="실전투자"
                else "https://openapivts.koreainvestment.com:29443")

    # ── 입력 필드 ──
    c1,c2 = st.columns(2)
    with c1: ak  = st.text_input("앱키", type="password",
                                  value=st.session_state.kis_ak,
                                  placeholder="PSxxxxxxxx...", key="kis_ak_inp")
    with c2: sec = st.text_input("시크릿", type="password",
                                  value=st.session_state.kis_sec, key="kis_sec_inp")
    acc = st.text_input("계좌번호", value=st.session_state.kis_acc,
                         placeholder="69108332-01", key="kis_acc_inp")

    # ── 연결 버튼 ──
    ca,cb = st.columns([3,1])
    with ca:
        if st.button("🔗 KIS API 연결", use_container_width=True, type="primary", key="btn_connect"):
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
                            fetch_prices.clear()
                            fetch_balance.clear()
                            st.success("✅ 연결 성공!")
                            st.rerun()
                        else:
                            st.error(f"❌ {d.get('msg1','앱키/시크릿 오류')}")
                    except Exception as e:
                        st.error(f"❌ {str(e)[:100]}")
    with cb:
        if st.session_state.kis_token:
            if st.button("해제", use_container_width=True, key="btn_disconnect"):
                st.session_state.kis_token=None
                fetch_prices.clear(); fetch_balance.clear()
                st.rerun()

    if st.session_state.kis_token:
        ca2,cb2 = st.columns([4,1])
        with ca2: st.success(f"✅ {st.session_state.kis_env} · {acc}")
        with cb2:
            if st.button("↻", use_container_width=True, key="btn_refresh_price",
                          help="현재가 갱신"):
                fetch_prices.clear(); fetch_balance.clear(); st.rerun()

    with st.expander("🔒 로그아웃"):
        if st.button("로그아웃", use_container_width=True, key="btn_logout"):
            for k in ["auth","kis_token","kis_ak","kis_sec","kis_acc"]:
                st.session_state[k]=False if k=="auth" else None if k=="kis_token" else ""
            st.rerun()

# ════════════════════════════════════════════════
# 현재가 + 잔고 Python 조회
# ════════════════════════════════════════════════
prices_json   = "{}"
balance_json  = "{}"
price_ts      = ""

if st.session_state.kis_token:
    ca,cb = st.columns([5,1])
    with cb:
        if st.button("↻ 갱신", use_container_width=True, key="btn_global_refresh"):
            fetch_prices.clear(); fetch_balance.clear(); st.rerun()
    with ca:
        with st.spinner("현재가·잔고 조회 중..."):
            prices = fetch_prices(st.session_state.kis_token, st.session_state.kis_base_url,
                                   st.session_state.kis_ak, st.session_state.kis_sec,
                                   tuple(KR_CODES))
            balance = fetch_balance(st.session_state.kis_token, st.session_state.kis_base_url,
                                     st.session_state.kis_ak, st.session_state.kis_sec,
                                     st.session_state.kis_acc)
        price_ts = time.strftime("%H:%M:%S")
        if prices:
            prices_json = json.dumps(prices)
            st.caption(f"📊 현재가 {len(prices)}종목 · 잔고 조회완료 · {price_ts}")
        else:
            st.warning("현재가 조회 실패 — 토큰 만료 시 재연결 필요")
        if balance and not balance.get('error'):
            balance_json = json.dumps(balance)

# ════════════════════════════════════════════════
# HTML 터미널
# ════════════════════════════════════════════════
if not os.path.exists("app.html"):
    st.error("app.html 파일을 GitHub 저장소에 업로드하세요.")
    st.stop()

with open("app.html","r",encoding="utf-8") as f:
    html = f.read()

inject = f"""<script>
window.__KIS_TOKEN__    = {json.dumps(st.session_state.kis_token or '')};
window.__KIS_BASE_URL__ = {json.dumps(st.session_state.kis_base_url or '')};
window.__KIS_AK__       = {json.dumps(st.session_state.kis_ak)};
window.__KIS_SEC__      = {json.dumps(st.session_state.kis_sec)};
window.__KIS_ACC__      = {json.dumps(st.session_state.kis_acc)};
window.__KIS_PRICES__   = {prices_json};
window.__KIS_BALANCE__  = {balance_json};
window.__KIS_PRICE_TS__ = {json.dumps(price_ts)};
</script>"""
html = html.replace("</head>", inject+"\n</head>")

components.html(html, height=1400, scrolling=True)
