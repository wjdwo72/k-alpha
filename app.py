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
            '006400','012450','267260','035420','096770',
            # 내일의 중소형주 Alpha-10
            '058470','140860','039440','320000','084370',
            '454910','039030','005420','064760','036830']

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
            ("kis_ak",""),("kis_sec",""),("kis_acc",""),("kis_env","실전투자"),
            ("agreed",False)]:
    if k not in st.session_state: st.session_state[k]=v

# ── URL 파라미터로 PIN 인증 체크 ──
qp = st.query_params
if qp.get('auth','') == '1' and not st.session_state.auth:
    st.session_state.auth = True
    try: del qp['auth']
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
# 법적 고지 동의 화면
# ════════════════════════════════════════
if not st.session_state.agreed:
    st.markdown("""<style>
body,.stApp{background:#020408!important}
.block-container{padding:12px!important;max-width:520px!important;margin:0 auto!important}
header,footer,[data-testid="stToolbar"]{display:none!important}
</style>""", unsafe_allow_html=True)

    st.markdown("""
<div style="text-align:center;padding:28px 0 18px;font-family:'Share Tech Mono',monospace">
  <div style="font-size:clamp(20px,6vw,32px);font-weight:700;letter-spacing:5px;
    background:linear-gradient(90deg,#00d4ff,#00ff88);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    margin-bottom:4px">K · ALPHA</div>
  <div style="font-size:10px;color:#4a5568;letter-spacing:2px">
    TRADING TERMINAL</div>
</div>

<div style="background:#0a0e1a;border:1px solid rgba(255,165,0,0.4);border-radius:12px;
  padding:20px;margin-bottom:16px;font-family:'Share Tech Mono',monospace">
  <div style="color:#ffc800;font-size:13px;font-weight:700;margin-bottom:14px;
    letter-spacing:1px">⚠ 투자 위험 고지 및 면책 조항</div>

  <div style="color:#94a3b8;font-size:12px;line-height:2;margin-bottom:14px">
    본 서비스(K-ALPHA Terminal)는 <span style="color:#e2e8f0">투자 참고용 정보 제공 도구</span>이며,
    <span style="color:#ff4d6d;font-weight:700">투자 권유 또는 자문 서비스가 아닙니다.</span>
  </div>

  <div style="background:#020408;border-radius:8px;padding:14px;font-size:11px;
    color:#64748b;line-height:2;margin-bottom:14px;border:1px solid #1a2535">
    <div style="color:#94a3b8;margin-bottom:6px;font-size:12px">📋 면책 조항 (Disclaimer)</div>
    • 본 서비스 개발자는 이용자의 투자 결과에 대해 <strong style="color:#ff4d6d">일체의 법적 책임을 지지 않습니다.</strong><br>
    • 제공되는 모든 분석 정보·신호·추천은 <strong style="color:#ffc800">참고 목적</strong>에 한하며,
      실제 투자 결과를 보장하지 않습니다.<br>
    • 주식 투자에는 <strong style="color:#ff4d6d">원금 손실 위험</strong>이 있으며, 투자의 최종 판단과
      책임은 <strong style="color:#e2e8f0">전적으로 이용자 본인</strong>에게 있습니다.<br>
    • 자동매매 기능 사용 시 발생하는 손실·오류·시스템 장애 등에 대해
      개발자는 <strong style="color:#ff4d6d">법적·재정적 책임을 부담하지 않습니다.</strong><br>
    • 본 서비스는 한국투자증권 등 금융기관과 <strong style="color:#ffc800">무관한 독립 개인 개발 도구</strong>입니다.<br>
    • 금융투자상품 거래는 관련 법규에 따라 본인의 판단으로 행하시기 바랍니다.
  </div>

  <div style="background:rgba(255,77,109,0.06);border:1px solid rgba(255,77,109,0.25);
    border-radius:8px;padding:12px;font-size:11px;color:#ff4d6d;line-height:1.8">
    ❗ 본 서비스의 개발자(제작자)는 금융투자업자가 아니며, 본 서비스 이용으로
    인한 <strong>직접적·간접적 손해</strong>에 대해 민사·형사상 책임을 지지 않습니다.<br>
    이용자는 위 내용에 동의하는 경우에만 서비스를 이용할 수 있습니다.
  </div>
</div>
""", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✗ 동의하지 않음", use_container_width=True, key="btn_disagree"):
            st.warning("서비스를 이용하시려면 위 조항에 동의하셔야 합니다.")
    with col2:
        if st.button("✓ 동의하고 시작", use_container_width=True,
                     type="primary", key="btn_agree"):
            st.session_state.agreed = True
            st.rerun()

    st.markdown("""<div style="text-align:center;font-family:'Share Tech Mono',monospace;
      font-size:10px;color:#2d3748;margin-top:12px;line-height:1.8">
      본 고지는 「자본시장과 금융투자업에 관한 법률」 및 관련 규정에 따라<br>
      이용자 보호를 위해 명시합니다. · K-ALPHA Terminal © 2025
    </div>""", unsafe_allow_html=True)
    st.stop()

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

    # ── 간편비번 저장/불러오기 (localStorage → 브라우저 재시작해도 유지) ──
    if st.session_state.get('_kv_action'):
        act = st.session_state.pop('_kv_action')
        pin_v = st.session_state.pop('_kv_pin','')
        if act == 'save':
            ak_v  = st.session_state.kis_ak
            sec_v = st.session_state.kis_sec
            acc_v = st.session_state.kis_acc
            env_v = st.session_state.kis_env
            if ak_v and sec_v and len(pin_v)==4 and pin_v.isdigit():
                ck_val = py_save(ak_v,sec_v,acc_v,env_v,pin_v)
                cp_val = base64.b64encode((pin_v+":kalpha").encode()).decode()
                st.session_state['_saved_ck'] = ck_val
                st.session_state['_saved_cp'] = cp_val
                # JS로 localStorage에도 저장
                st.session_state['_js_save'] = (ck_val, cp_val)
                st.success("✅ 저장 완료! 브라우저에 영구 보존됩니다")
            elif not ak_v or not sec_v:
                st.error("앱키·시크릿 먼저 입력·연결 후 저장하세요")
            else:
                st.error("4자리 숫자 비번을 입력하세요")
        elif act == 'load':
            ck = st.session_state.get('_saved_ck','')
            cp = st.session_state.get('_saved_cp','')
            if not ck:
                st.error("저장된 키 없음 — 먼저 저장하세요")
            elif cp and base64.b64decode(cp).decode() != pin_v+":kalpha":
                st.error("❌ PIN이 틀렸습니다")
            else:
                try:
                    data = py_load(ck, pin_v)
                    st.session_state.kis_ak  = data.get('ak','')
                    st.session_state.kis_sec = data.get('sec','')
                    st.session_state.kis_acc = data.get('acc','')
                    st.session_state.kis_env = data.get('env','실전투자')
                    st.success("✅ 불러오기 완료! 연결 버튼을 누르세요")
                    st.rerun()
                except: st.error("❌ 복호화 실패")
        elif act == 'del':
            st.session_state.pop('_saved_ck',None)
            st.session_state.pop('_saved_cp',None)
            st.session_state['_js_save'] = ('','')  # localStorage도 삭제
            st.rerun()

    # localStorage 읽기/쓰기 컴포넌트
    js_save = st.session_state.pop('_js_save', None)
    ck_init = json.dumps(st.session_state.get('_saved_ck',''))
    cp_init = json.dumps(st.session_state.get('_saved_cp',''))

    load_result = components.html(f"""<!DOCTYPE html>
<html><head><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{background:#0a0e1a;font-family:'Share Tech Mono',monospace;overflow:hidden}}
#hint{{font-size:10px;color:#ffc800;padding:4px 0;min-height:14px}}
</style></head><body>
<div id="hint"></div>
<script>
const CK='kalpha_ck_v4', CP='kalpha_cp_v4';
// Python이 저장 요청한 경우
var jsave={json.dumps(list(js_save) if js_save else None)};
if(jsave&&jsave[0]){{
  localStorage.setItem(CK,jsave[0]);
  localStorage.setItem(CP,jsave[1]);
}}else if(jsave&&jsave[0]===''){{
  localStorage.removeItem(CK);localStorage.removeItem(CP);
}}
// localStorage에서 읽어서 부모로 전달 (window.parent 같은 origin)
var ck=localStorage.getItem(CK)||'';
var cp=localStorage.getItem(CP)||'';
var hint=document.getElementById('hint');
if(ck)hint.textContent='💾 브라우저에 저장된 키 있음';
// 세션에 아직 없으면 window.parent.location으로 URL 파라미터 전달
var pCk={ck_init};
if(ck&&!pCk){{
  try{{
    // Streamlit과 같은 origin이면 작동
    var url=new URL(window.parent.location.href);
    if(!url.searchParams.get('_ck')){{
      url.searchParams.set('_ck',ck);
      url.searchParams.set('_cp',cp);
      window.parent.location.replace(url.toString());
    }}
  }}catch(e){{
    // cross-origin blocked: 부모 페이지 form submit trick
    try{{
      var f=window.parent.document.createElement('form');
      f.method='GET'; f.action=window.parent.location.pathname;
      var i1=window.parent.document.createElement('input');
      i1.name='_ck'; i1.value=ck; f.appendChild(i1);
      var i2=window.parent.document.createElement('input');
      i2.name='_cp'; i2.value=cp; f.appendChild(i2);
      window.parent.document.body.appendChild(f);
      f.submit();
    }}catch(e2){{}}
  }}
}}
</script>
</body></html>""", height=22, scrolling=False)

    # URL 파라미터로 localStorage 데이터 수신
    if qp.get('_ck') and not st.session_state.get('_saved_ck'):
        st.session_state['_saved_ck'] = qp.get('_ck','')
        st.session_state['_saved_cp'] = qp.get('_cp','')
        try:
            del qp['_ck']; del qp['_cp']
        except: pass
        st.rerun()

    has_saved = bool(st.session_state.get('_saved_ck'))

    sv_pin = st.text_input("🔒 간편비번(4자리)", max_chars=4,
                            placeholder="4자리 숫자", key="sv_pin",
                            type="password", label_visibility="visible")

    sc1, sc2, sc3 = st.columns([1,1,0.35])
    with sc1:
        if st.button("💾 저장", use_container_width=True, key="do_save"):
            st.session_state['_kv_action'] = 'save'
            st.session_state['_kv_pin']    = (sv_pin or '').strip()
            st.rerun()
    with sc2:
        if st.button("📂 불러오기", use_container_width=True, key="do_load"):
            st.session_state['_kv_action'] = 'load'
            st.session_state['_kv_pin']    = (sv_pin or '').strip()
            st.rerun()
    with sc3:
        if st.button("🗑", use_container_width=True, key="do_del_key"):
            st.session_state['_kv_action'] = 'del'
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
window.__STREAMLIT_MODE__ = true;
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
components.html(html, height=3500, scrolling=False)
