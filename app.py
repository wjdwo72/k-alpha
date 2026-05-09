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

def py_xor(text, pin):
    pb = pin.encode()
    return bytes([ord(c)^pb[i%4] for i,c in enumerate(text)])

def py_save(ak,sec,acc,env,pin):
    return base64.b64encode(py_xor(json.dumps({'ak':ak,'sec':sec,'acc':acc,'env':env}),pin)).decode()

def py_load(encoded, pin):
    raw = base64.b64decode(encoded)
    pb = pin.encode()
    return json.loads(''.join(chr(b^pb[i%4]) for i,b in enumerate(raw)))

for k,v in [("auth",False),("wrong",False),("kis_token",None),("kis_base_url",None),
            ("kis_ak",""),("kis_sec",""),("kis_acc",""),("kis_env","실전투자")]:
    if k not in st.session_state: st.session_state[k]=v

# ── URL 파라미터로 PIN 인증 체크 ──
qp = st.query_params
if qp.get('auth','') == '1' and not st.session_state.auth:
    st.session_state.auth = True
    try: del qp['auth']
    except: pass
    st.rerun()

# ── URL 파라미터로 저장된 키 불러오기 체크 ──
if qp.get('do_load','') == '1':
    enc  = qp.get('ck','')
    chk  = qp.get('cp','')
    pin2 = qp.get('lp','')
    if enc and pin2:
        try:
            if not chk or base64.b64decode(chk).decode() == pin2+':kalpha':
                data = py_load(enc, pin2)
                st.session_state.kis_ak  = data.get('ak','')
                st.session_state.kis_sec = data.get('sec','')
                st.session_state.kis_acc = data.get('acc','')
                st.session_state.kis_env = data.get('env','실전투자')
                st.session_state['load_ok'] = True
        except: pass
    try:
        del qp['do_load']
        if 'lp' in qp: del qp['lp']
    except: pass
    st.rerun()

@st.cache_data(ttl=30, show_spinner=False)
def fetch_prices(token, base_url, ak, secret, codes_tuple):
    prices = {}
    headers = {'Content-Type':'application/json','authorization':f'Bearer {token}',
                'appkey':ak,'appsecret':secret,'tr_id':'FHKST01010100'}
    for code in codes_tuple:
        try:
            r=requests.get(f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
                params={'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code},
                headers=headers, verify=False, timeout=5)
            o=r.json().get('output',{})
            if not o.get('stck_prpr'): continue
            sign=o.get('prdy_vrss_sign','3'); is_dn=sign in ['4','5']
            ca=int(o.get('prdy_vrss',0)); pa=float(o.get('prdy_ctrt',0))
            prices[code]={'price':int(o['stck_prpr']),'change':-ca if is_dn else ca,
                          'changePct':-pa if is_dn else pa,'up':sign in ['1','2']}
            time.sleep(0.15)
        except: pass
    return prices

@st.cache_data(ttl=60, show_spinner=False)
def fetch_balance(token, base_url, ak, secret, acc):
    try:
        acc_no=acc.replace('-','')
        tr_id='VTTC8434R' if 'openapivts' in base_url else 'TTTC8434R'
        headers={'Content-Type':'application/json','authorization':f'Bearer {token}',
                  'appkey':ak,'appsecret':secret,'tr_id':tr_id}
        r=requests.get(f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
            params={'CANO':acc_no[:8],'ACNT_PRDT_CD':acc_no[8:] or '01',
                    'AFHR_FLPR_YN':'N','OFL_YN':'','INQR_DVSN':'02','UNPR_DVSN':'01',
                    'FUND_STTL_ICLD_YN':'N','FNCG_AMT_AUTO_RDPT_YN':'N',
                    'PRCS_DVSN':'01','CTX_AREA_FK100':'','CTX_AREA_NK100':''},
            headers=headers, verify=False, timeout=10)
        return r.json()
    except Exception as e: return {'error':str(e)}

# ════════════════════════════════════════
# 비밀번호 화면 (URL 파라미터 방식 — 가장 신뢰성 높음)
# ════════════════════════════════════════
if not st.session_state.auth:
    # ── 세션 초기화 ──
    if 'pin_buf' not in st.session_state:
        st.session_state.pin_buf = ''
    if 'pin_err' not in st.session_state:
        st.session_state.pin_err = False

    # ── 버튼 콜백 ──
    def press(n):
        if st.session_state.pin_err:
            st.session_state.pin_buf = ''
            st.session_state.pin_err = False
        if len(st.session_state.pin_buf) < 4:
            st.session_state.pin_buf += str(n)
        if len(st.session_state.pin_buf) == 4:
            if st.session_state.pin_buf == PASSWORD:
                st.session_state.auth = True
                st.session_state.pin_buf = ''
                st.session_state.pin_err = False
            else:
                st.session_state.pin_err = True
                st.session_state.pin_buf = ''

    def press_del():
        if st.session_state.pin_err:
            st.session_state.pin_err = False
        st.session_state.pin_buf = st.session_state.pin_buf[:-1]

    def press_ok():
        if len(st.session_state.pin_buf) == 4:
            press('')

    buf = st.session_state.pin_buf
    err = st.session_state.pin_err

    # ── PIN 패드 CSS ──
    st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=Share+Tech+Mono&display=swap');
body,.stApp{background:#020408!important}
.block-container{padding:8px!important;max-width:360px!important;margin:0 auto!important}
header,footer,[data-testid="stToolbar"],[data-testid="stDecoration"]{display:none!important}

/* 모든 PIN 버튼 공통 스타일 */
div[data-testid="column"] .stButton button {
    width:100%!important; height:68px!important;
    background:#0d1220!important; color:#e2e8f0!important;
    border:1px solid #1a2535!important; border-radius:12px!important;
    font-size:22px!important; font-family:'Share Tech Mono',monospace!important;
    font-weight:400!important; line-height:1!important;
    padding:0!important; margin:0!important;
    transition:background .12s,transform .08s!important;
    box-shadow:none!important;
}
div[data-testid="column"] .stButton button:hover {
    background:#1a2535!important; border-color:#2a3545!important;
    transform:scale(.96)!important; color:#e2e8f0!important;
}
div[data-testid="column"] .stButton button:active {
    background:#1e2a3a!important; transform:scale(.90)!important;
}
/* 엔터 버튼 */
div[data-testid="column"]:last-child .stButton button {
    background:rgba(0,212,255,.12)!important;
    border-color:rgba(0,212,255,.4)!important; color:#00d4ff!important;
}
div[data-testid="column"]:last-child .stButton button:hover {
    background:rgba(0,212,255,.22)!important;
}
/* 지우기 버튼 */
.del-btn button {
    width:100%!important; height:52px!important;
    background:#0d1220!important; color:#64748b!important;
    border:1px solid #1a2535!important; border-radius:10px!important;
    font-size:14px!important; font-family:'Share Tech Mono',monospace!important;
    padding:0!important;
}
.del-btn button:hover{background:#1a2535!important;color:#94a3b8!important}
</style>""", unsafe_allow_html=True)

    # ── 헤더 ──
    st.markdown(f"""
<div style="text-align:center;padding:32px 0 20px;font-family:'Share Tech Mono',monospace">
  <div style="font-family:'Orbitron',monospace;font-size:clamp(24px,8vw,40px);
    font-weight:700;letter-spacing:6px;
    background:linear-gradient(90deg,#00d4ff,#00ff88);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    margin-bottom:6px">K · ALPHA</div>
  <div style="font-size:11px;color:#4a5568;letter-spacing:2px;margin-bottom:24px">
    TRADING TERMINAL · SECURE ACCESS</div>
  <div style="background:#0a0e1a;border:1px solid #1a2535;border-radius:16px;
    padding:20px 16px 14px;max-width:300px;margin:0 auto">
    <div style="font-size:10px;color:#4a5568;letter-spacing:2px;margin-bottom:12px">
      🔒 PIN 번호 입력</div>
    <div style="display:flex;justify-content:center;gap:14px;margin-bottom:16px">
      {''.join([
        f'<div style="width:12px;height:12px;border-radius:50%;transition:all .2s;'
        + (f'background:#00d4ff;border:2px solid #00d4ff;box-shadow:0 0 8px rgba(0,212,255,.7)">'
           if i < len(buf) else f'border:2px solid #1a3a4a;background:transparent">')
        + '</div>'
        for i in range(4)
      ])}
    </div>
    {'<div style="color:#ff4d6d;font-size:11px;margin-bottom:8px">❌ 비밀번호가 틀렸습니다</div>' if err else ''}
  </div>
</div>""", unsafe_allow_html=True)

    # ── 숫자 패드 ──
    for row in [[1,2,3],[4,5,6],[7,8,9]]:
        cols = st.columns(3)
        for c, n in zip(cols, row):
            with c:
                st.button(str(n), key=f'pb{n}', on_click=press, args=(n,), use_container_width=True)

    # 마지막 행: 빈칸, 0, 엔터
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown('<div style="height:68px"></div>', unsafe_allow_html=True)
    with c2:
        st.button('0', key='pb0', on_click=press, args=(0,), use_container_width=True)
    with c3:
        st.button('↵', key='pb_ok', on_click=press_ok, use_container_width=True)

    # 지우기
    st.markdown('<div class="del-btn">', unsafe_allow_html=True)
    st.button('⌫  지우기', key='pb_del', on_click=press_del, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.stop()

# ════════════════════════════════════════
# KIS API 연결 패널
# ════════════════════════════════════════
if st.session_state.get('load_ok'):
    st.success("✅ API 키 불러오기 완료! 연결 버튼을 누르세요.")
    del st.session_state['load_ok']

label = (f"🔑 KIS API  ✅ {st.session_state.kis_env} 연결됨"
         if st.session_state.kis_token else "🔑 KIS API 연결 ▾")

with st.expander(label, expanded=not bool(st.session_state.kis_token)):

    # ── 간편비번 저장/불러오기 (URL 파라미터 → 영구 보존) ──
    # qp에서 저장된 키 읽기
    saved_ck = qp.get('ck','')
    saved_cp = qp.get('cp','')

    st.markdown(f"""<div style='background:#0a0e1a;border:1px solid #1a2535;border-radius:8px;
      padding:8px 12px;margin-bottom:6px;font-family:monospace;font-size:11px;color:#4a5568'>
      🔒 간편비번 저장/불러오기
      {"&nbsp;&nbsp;<span style='color:#ffc800'>💾 저장된 키 있음</span>" if saved_ck else ""}
      </div>""", unsafe_allow_html=True)

    sv_pin = st.text_input("비번(4자리)", max_chars=4, placeholder="4자리 숫자",
                            key="sv_pin", label_visibility="visible", type="password")

    sc1, sc2, sc3 = st.columns([1,1,0.35])
    with sc1:
        if st.button("💾 저장", use_container_width=True, key="do_save"):
            pin_v = (sv_pin or "").strip()
            if len(pin_v) == 4 and pin_v.isdigit():
                # 현재 입력된 값 우선, 없으면 session_state
                ak_v  = st.session_state.get("kis_ak_inp","")  or st.session_state.kis_ak
                sec_v = st.session_state.get("kis_sec_inp","") or st.session_state.kis_sec
                acc_v = st.session_state.get("kis_acc_inp","") or st.session_state.kis_acc
                env_v = st.session_state.get("kis_env_sel","실전투자")
                if ak_v and sec_v:
                    # URL 파라미터에 저장 → 북마크 시 영구 보존
                    qp['ck'] = py_save(ak_v, sec_v, acc_v, env_v, pin_v)
                    qp['cp'] = base64.b64encode((pin_v+":kalpha").encode()).decode()
                    st.success("✅ 저장 완료! 이 URL을 북마크하세요")
                else:
                    st.error("앱키·시크릿을 먼저 입력하세요")
            else:
                st.error("4자리 숫자를 입력하세요")
    with sc2:
        if st.button("📂 불러오기", use_container_width=True, key="do_load"):
            pin_v = (sv_pin or "").strip()
            ck = qp.get('ck','')
            cp = qp.get('cp','')
            if len(pin_v) == 4 and pin_v.isdigit():
                if not ck:
                    st.error("저장된 키 없음 — 먼저 저장하세요")
                elif cp and base64.b64decode(cp).decode() != pin_v+":kalpha":
                    st.error("❌ PIN이 틀렸습니다")
                else:
                    try:
                        data = py_load(ck, pin_v)
                        st.session_state.kis_ak  = data.get("ak","")
                        st.session_state.kis_sec = data.get("sec","")
                        st.session_state.kis_acc = data.get("acc","")
                        st.session_state.kis_env = data.get("env","실전투자")
                        st.success("✅ 불러오기 완료! 연결 버튼을 누르세요")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 복호화 실패: {e}")
            else:
                st.error("4자리 숫자를 입력하세요")
    with sc3:
        if st.button("🗑", use_container_width=True, key="do_del_key"):
            if 'ck' in qp: del qp['ck']
            if 'cp' in qp: del qp['cp']
            st.rerun()

    st.divider()

    env_label = st.radio("서버", ["실전투자","모의투자"], horizontal=True,
                          index=0 if st.session_state.kis_env=="실전투자" else 1,
                          label_visibility="collapsed", key="kis_env_sel")
    base_url = ("https://openapi.koreainvestment.com:9443" if env_label=="실전투자"
                else "https://openapivts.koreainvestment.com:29443")

    ak  = st.text_input("앱키", type="password", value=st.session_state.kis_ak,
                         placeholder="PSxxxxxxxx...", key="kis_ak_inp")
    sec = st.text_input("시크릿", type="password", value=st.session_state.kis_sec,
                         key="kis_sec_inp")
    acc = st.text_input("계좌번호", value=st.session_state.kis_acc,
                         placeholder="69108332-01  (8자리-2자리)", key="kis_acc_inp")

    # 입력값을 iframe으로 전달 (저장용)
    if ak or sec or acc:
        st.markdown(f"""<script>
(function(){{
  const iframes=document.querySelectorAll('iframe');
  iframes.forEach(f=>{{
    try{{f.contentWindow.postMessage({{
      type:'api_vals',
      ak:{json.dumps(ak)},sec:{json.dumps(sec)},
      acc:{json.dumps(acc)},env:{json.dumps(env_label)}
    }},'*');}}catch(e){{}}
  }});
}})();
</script>""", unsafe_allow_html=True)

    col_a, col_b = st.columns([3,1])
    with col_a:
        if st.button("🔗 KIS API 연결", use_container_width=True,
                      type="primary", key="btn_connect"):
            if not ak or not sec or not acc:
                st.error("앱키 · 시크릿 · 계좌번호를 모두 입력하세요")
            else:
                with st.spinner("KIS 연결 중..."):
                    try:
                        r=requests.post(f"{base_url}/oauth2/tokenP",
                            json={"grant_type":"client_credentials","appkey":ak,"appsecret":sec},
                            verify=False,timeout=12)
                        d=r.json()
                        if d.get("access_token"):
                            st.session_state.kis_token    = d["access_token"]
                            st.session_state.kis_base_url = base_url
                            st.session_state.kis_ak=ak; st.session_state.kis_sec=sec
                            st.session_state.kis_acc=acc; st.session_state.kis_env=env_label
                            fetch_prices.clear(); fetch_balance.clear()
                            st.success("✅ 연결 성공!")
                            st.rerun()
                        else:
                            st.error(f"❌ {d.get('msg1','앱키/시크릿 오류')}")
                    except Exception as e:
                        st.error(f"❌ {str(e)[:100]}")
    with col_b:
        if st.session_state.kis_token:
            if st.button("해제", use_container_width=True, key="btn_disc"):
                st.session_state.kis_token=None
                fetch_prices.clear(); fetch_balance.clear(); st.rerun()

    if st.session_state.kis_token:
        st.success(f"✅ {st.session_state.kis_env} · {acc}")

    with st.expander("🔒 로그아웃"):
        if st.button("로그아웃", use_container_width=True, key="btn_logout"):
            for k in ["auth","kis_token","kis_ak","kis_sec","kis_acc"]:
                st.session_state[k]=False if k=="auth" else None if k=="kis_token" else ""
            st.rerun()

# ════════════════════════════════════════
# 현재가 + 잔고 조회
# ════════════════════════════════════════
prices_json="{}"; balance_json="{}"; price_ts=""
if st.session_state.kis_token:
    ca,cb=st.columns([5,1])
    with cb:
        if st.button("↻", use_container_width=True, key="btn_ref"):
            fetch_prices.clear(); fetch_balance.clear(); st.rerun()
    with ca:
        with st.spinner("조회 중..."):
            prices=fetch_prices(st.session_state.kis_token,st.session_state.kis_base_url,
                                 st.session_state.kis_ak,st.session_state.kis_sec,tuple(KR_CODES))
            balance=fetch_balance(st.session_state.kis_token,st.session_state.kis_base_url,
                                   st.session_state.kis_ak,st.session_state.kis_sec,st.session_state.kis_acc)
        price_ts=time.strftime("%H:%M:%S")
        if prices: prices_json=json.dumps(prices); st.caption(f"📊 {len(prices)}종목 · {price_ts}")
        if balance and not balance.get('error'): balance_json=json.dumps(balance)

# ════════════════════════════════════════
# HTML 터미널
# ════════════════════════════════════════
if not os.path.exists("app.html"):
    st.error("app.html 파일을 GitHub 저장소에 업로드하세요."); st.stop()

with open("app.html","r",encoding="utf-8") as f:
    html=f.read()

inject=f"""<script>
window.__KIS_TOKEN__    = {json.dumps(st.session_state.kis_token or '')};
window.__KIS_BASE_URL__ = {json.dumps(st.session_state.kis_base_url or '')};
window.__KIS_AK__       = {json.dumps(st.session_state.kis_ak)};
window.__KIS_SEC__      = {json.dumps(st.session_state.kis_sec)};
window.__KIS_ACC__      = {json.dumps(st.session_state.kis_acc)};
window.__KIS_PRICES__   = {prices_json};
window.__KIS_BALANCE__  = {balance_json};
window.__KIS_PRICE_TS__ = {json.dumps(price_ts)};
</script>"""
html=html.replace("</head>",inject+"\n</head>")
components.html(html, height=1600, scrolling=True)
