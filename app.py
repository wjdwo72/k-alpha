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
  .stTextInput label{color:#94a3b8 !important;font-family:'Share Tech Mono',monospace !important;font-size:12px !important}
  .stTextInput label p{color:#94a3b8 !important}
  .stTextInput label strong{color:#00d4ff !important}
  .stRadio label{color:#94a3b8 !important;font-family:'Share Tech Mono',monospace !important}
  .stRadio [data-testid="stMarkdownContainer"] p{color:#e2e8f0 !important}
  .stButton>button{font-family:monospace}
  .stRadio>div{flex-direction:row;gap:10px}
  /* 캡션 색상 */
  .stCaption, .stCaption p{color:#64748b !important;font-family:'Share Tech Mono',monospace !important}
  /* divider */
  hr{border-color:#1a2535 !important}
  /* expander 내부 텍스트 */
  div[data-testid="stExpander"] .stMarkdown p{color:#94a3b8 !important}
  div[data-testid="stExpander"] .stSuccess{background:rgba(0,255,136,.1) !important;border-color:rgba(0,255,136,.3) !important}
  div[data-testid="stExpander"] .stError{background:rgba(255,77,109,.1) !important}
</style>""", unsafe_allow_html=True)

PASSWORD = "4545"
KR_CODES = ['009150','066570','005490','005380','105560',
            '011070','247540','068270','000660','035720',
            '006400','012450','267260','035420','096770',
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

# ── 세션 초기화 ──
for k,v in [("agreed",False),("auth",False),("wrong",False),
            ("kis_token",None),("kis_base_url",None),
            ("kis_ak",""),("kis_sec",""),("kis_acc",""),("kis_env","실전투자")]:
    if k not in st.session_state: st.session_state[k]=v

# ── URL 파라미터 처리 (PIN 인증, 저장키 복원) ──
qp = st.query_params
if qp.get('agreed') == '1' and not st.session_state.agreed:
    st.session_state.agreed = True
if qp.get('auth') == '1' and not st.session_state.auth:
    st.session_state.auth = True
    try: del qp['auth']
    except: pass
    st.rerun()

# ── 저장된 키 URL에서 복원 ──
if qp.get('_ck') and not st.session_state.get('_saved_ck'):
    st.session_state['_saved_ck'] = qp.get('_ck','')
    st.session_state['_saved_cp'] = qp.get('_cp','')
    try: del qp['_ck']; del qp['_cp']
    except: pass

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
        acc_clean = acc.replace('-','').replace(' ','')
        cano = acc_clean[:8]
        acnt_cd = acc_clean[8:10] if len(acc_clean) >= 10 else '01'
        tr_id = 'VTTC8434R' if 'openapivts' in base_url else 'TTTC8434R'
        headers = {'Content-Type':'application/json','authorization':f'Bearer {token}',
                   'appkey':ak,'appsecret':secret,'tr_id':tr_id,'custtype':'P'}
        r = requests.get(f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
            params={'CANO':cano,'ACNT_PRDT_CD':acnt_cd,'AFHR_FLPR_YN':'N','OFL_YN':'',
                    'INQR_DVSN':'02','UNPR_DVSN':'01','FUND_STTL_ICLD_YN':'N',
                    'FNCG_AMT_AUTO_RDPT_YN':'N','PRCS_DVSN':'01',
                    'CTX_AREA_FK100':'','CTX_AREA_NK100':''},
            headers=headers, verify=False, timeout=10)
        data = r.json()
        if data.get('rt_cd') == '0': return data
        return {'error': data.get('msg1','잔고 조회 실패')}
    except Exception as e: return {'error': str(e)}

# ════════════════════════════════════════
# 1. 법적 고지 동의
# ════════════════════════════════════════
if not st.session_state.agreed:
    st.markdown("""<style>
body,.stApp{background:#020408!important}
.block-container{padding:12px!important;max-width:520px!important;margin:0 auto!important}
</style>""", unsafe_allow_html=True)

    st.markdown("""
<div style="text-align:center;padding:24px 0 16px;font-family:'Share Tech Mono',monospace">
  <div style="font-size:28px;font-weight:700;letter-spacing:5px;
    background:linear-gradient(90deg,#00d4ff,#00ff88);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent">K · ALPHA</div>
  <div style="font-size:10px;color:#4a5568;letter-spacing:2px;margin-top:4px">TRADING TERMINAL</div>
</div>

<div style="background:#0a0e1a;border:1px solid rgba(255,165,0,0.4);border-radius:12px;padding:18px;margin-bottom:14px;font-family:'Share Tech Mono',monospace">
  <div style="color:#ffc800;font-size:13px;font-weight:700;margin-bottom:12px">⚠ 투자 위험 고지 및 면책 조항</div>
  <div style="color:#94a3b8;font-size:12px;line-height:2;margin-bottom:12px">
    본 서비스(K-ALPHA Terminal)는 <span style="color:#e2e8f0">투자 참고용 정보 제공 도구</span>이며,
    <span style="color:#ff4d6d;font-weight:700">투자 권유 또는 자문 서비스가 아닙니다.</span>
  </div>
  <div style="background:#020408;border-radius:8px;padding:12px;font-size:11px;color:#64748b;line-height:2;margin-bottom:12px;border:1px solid #1a2535">
    📋 면책 조항<br>
    • 개발자는 이용자의 투자 결과에 대해 <strong style="color:#ff4d6d">일체의 법적 책임을 지지 않습니다.</strong><br>
    • 모든 분석·신호·추천은 <strong style="color:#ffc800">참고 목적</strong>에 한하며 결과를 보장하지 않습니다.<br>
    • 주식 투자에는 <strong style="color:#ff4d6d">원금 손실 위험</strong>이 있으며 최종 판단은 <strong style="color:#e2e8f0">이용자 본인</strong>에게 있습니다.<br>
    • 자동매매 기능 손실·오류에 대해 개발자는 <strong style="color:#ff4d6d">법적·재정적 책임을 부담하지 않습니다.</strong><br>
    • 본 서비스는 한국투자증권과 <strong style="color:#ffc800">무관한 독립 개인 개발 도구</strong>입니다.
  </div>
  <div style="background:rgba(255,77,109,0.06);border:1px solid rgba(255,77,109,0.25);border-radius:8px;padding:10px;font-size:11px;color:#ff4d6d;line-height:1.8">
    ❗ 개발자(제작자)는 금융투자업자가 아니며, 서비스 이용으로 인한
    <strong>직접적·간접적 손해</strong>에 대해 민사·형사상 책임을 지지 않습니다.
  </div>
</div>
""", unsafe_allow_html=True)

    c1,c2=st.columns(2)
    with c1:
        if st.button("✗ 동의하지 않음", use_container_width=True, key="btn_disagree"):
            st.warning("동의가 필요합니다.")
    with c2:
        # 동의 시 URL에 agreed=1 저장 (세션 재시작 시에도 유지)
        if st.button("✓ 동의하고 시작", use_container_width=True, type="primary", key="btn_agree"):
            st.session_state.agreed = True
            qp['agreed'] = '1'
            st.rerun()

    st.markdown("""<div style="text-align:center;font-family:'Share Tech Mono',monospace;
      font-size:10px;color:#2d3748;margin-top:10px">
      「자본시장과 금융투자업에 관한 법률」 관련 고지 · K-ALPHA Terminal © 2025</div>""",
    unsafe_allow_html=True)
    st.stop()

# ════════════════════════════════════════
# 2. PIN 화면
# ════════════════════════════════════════
if not st.session_state.auth:
    # PIN on_change
    if 'pin_buf' not in st.session_state: st.session_state.pin_buf = ''
    if 'pin_err' not in st.session_state: st.session_state.pin_err = False

    def press(n):
        if st.session_state.pin_err:
            st.session_state.pin_buf = ''; st.session_state.pin_err = False
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
        if st.session_state.pin_err: st.session_state.pin_err = False
        st.session_state.pin_buf = st.session_state.pin_buf[:-1]

    def press_ok():
        if len(st.session_state.pin_buf) == 4: press('')

    buf = st.session_state.pin_buf
    err = st.session_state.pin_err

    st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=Share+Tech+Mono&display=swap');
body,.stApp{background:#020408!important}
.block-container{padding:8px!important;max-width:360px!important;margin:0 auto!important}
div[data-testid="column"] .stButton button {
    width:100%!important; height:68px!important;
    background:#0d1220!important; color:#e2e8f0!important;
    border:1px solid #1a2535!important; border-radius:12px!important;
    font-size:22px!important; font-family:'Share Tech Mono',monospace!important;
    padding:0!important; margin:0!important; box-shadow:none!important;
}
div[data-testid="column"] .stButton button:hover{background:#1a2535!important;color:#e2e8f0!important}
div[data-testid="column"] .stButton button:active{background:#1e2a3a!important;transform:scale(.92)!important}
div[data-testid="column"]:last-child .stButton button{background:rgba(0,212,255,.12)!important;border-color:rgba(0,212,255,.4)!important;color:#00d4ff!important}
.del-btn button{width:100%!important;height:52px!important;background:#0d1220!important;color:#64748b!important;border:1px solid #1a2535!important;border-radius:10px!important;font-size:14px!important;font-family:'Share Tech Mono',monospace!important;padding:0!important}
</style>""", unsafe_allow_html=True)

    st.markdown(f"""
<div style="text-align:center;padding:28px 0 18px;font-family:'Share Tech Mono',monospace">
  <div style="font-family:'Orbitron',monospace;font-size:clamp(22px,7vw,40px);font-weight:700;
    letter-spacing:6px;background:linear-gradient(90deg,#00d4ff,#00ff88);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px">K · ALPHA</div>
  <div style="font-size:11px;color:#4a5568;letter-spacing:2px;margin-bottom:20px">TRADING TERMINAL · SECURE ACCESS</div>
  <div style="background:#0a0e1a;border:1px solid #1a2535;border-radius:16px;padding:22px 20px 14px;width:min(280px,86vw);margin:0 auto">
    <div style="font-size:10px;color:#4a5568;letter-spacing:2px;margin-bottom:10px">🔒 PIN 번호 입력</div>
    <div style="display:flex;justify-content:center;gap:14px;margin-bottom:16px">
      {''.join([
        f'<div style="width:12px;height:12px;border-radius:50%;transition:all .2s;'
        + (f'background:#00d4ff;border:2px solid #00d4ff;box-shadow:0 0 8px rgba(0,212,255,.7)">' if i<len(buf) else f'border:2px solid #1a3a4a;background:transparent">')
        + '</div>' for i in range(4)
      ])}
    </div>
    {'<div style="color:#ff4d6d;font-size:11px;margin-bottom:8px">❌ 비밀번호가 틀렸습니다</div>' if err else ''}
  </div>
</div>""", unsafe_allow_html=True)

    for row in [[1,2,3],[4,5,6],[7,8,9]]:
        cols = st.columns(3)
        for c,n in zip(cols,row):
            with c: st.button(str(n), key=f'pb{n}', on_click=press, args=(n,), use_container_width=True)

    c1,c2,c3 = st.columns(3)
    with c1: st.markdown('<div style="height:68px"></div>', unsafe_allow_html=True)
    with c2: st.button('0', key='pb0', on_click=press, args=(0,), use_container_width=True)
    with c3: st.button('↵', key='pb_ok', on_click=press_ok, use_container_width=True)

    st.markdown('<div class="del-btn">', unsafe_allow_html=True)
    st.button('⌫  지우기', key='pb_del', on_click=press_del, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# ════════════════════════════════════════
# 3. KIS API 패널
# ════════════════════════════════════════
if st.session_state.get('_kv_action'):
    act = st.session_state.pop('_kv_action')
    pin_v = st.session_state.pop('_kv_pin','')
    if act == 'save':
        ak_v  = st.session_state.get('kis_ak_inp','') or st.session_state.kis_ak
        sec_v = st.session_state.get('kis_sec_inp','') or st.session_state.kis_sec
        acc_v = st.session_state.get('kis_acc_inp','') or st.session_state.kis_acc
        env_v = st.session_state.get('kis_env_sel','실전투자') or st.session_state.kis_env
        if ak_v and sec_v and len(pin_v)==4 and pin_v.isdigit():
            ck_val = py_save(ak_v,sec_v,acc_v,env_v,pin_v)
            cp_val = base64.b64encode((pin_v+":kalpha").encode()).decode()
            st.session_state['_saved_ck'] = ck_val
            st.session_state['_saved_cp'] = cp_val
            st.session_state['_js_save'] = (ck_val, cp_val)
            st.success("✅ 저장 완료!")
        elif not ak_v or not sec_v:
            st.error("앱키·시크릿 먼저 입력 후 저장")
        else:
            st.error("4자리 숫자 비번 입력")
    elif act == 'load':
        ck = st.session_state.get('_saved_ck','')
        cp = st.session_state.get('_saved_cp','')
        if not ck: st.error("저장된 키 없음")
        elif cp and base64.b64decode(cp).decode() != pin_v+":kalpha": st.error("❌ PIN 틀림")
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
        st.session_state.pop('_saved_ck',None); st.session_state.pop('_saved_cp',None); st.rerun()

label = (f"🔑 KIS API  ✅ {st.session_state.kis_env} 연결됨"
         if st.session_state.kis_token else "🔑 KIS API 연결 ▾")

with st.expander(label, expanded=not bool(st.session_state.kis_token)):

    # ── 간편비번: URL 파라미터에서 읽기 ──
    saved_ck = qp.get('ck','')
    saved_cp = qp.get('cp','')

    # on_click 콜백 처리
    if st.session_state.get('_kv_action'):
        act = st.session_state.pop('_kv_action')
        pin_v = st.session_state.pop('_kv_pin','')
        if act == 'save':
            ak_v  = st.session_state.get('kis_ak_inp','') or st.session_state.kis_ak
            sec_v = st.session_state.get('kis_sec_inp','') or st.session_state.kis_sec
            acc_v = st.session_state.get('kis_acc_inp','') or st.session_state.kis_acc
            env_v = st.session_state.get('kis_env_sel','실전투자') or st.session_state.kis_env
            if ak_v and sec_v and len(pin_v)==4 and pin_v.isdigit():
                ck_val = py_save(ak_v,sec_v,acc_v,env_v,pin_v)
                cp_val = base64.b64encode((pin_v+":kalpha").encode()).decode()
                qp['ck'] = ck_val
                qp['cp'] = cp_val
                st.session_state['_save_ok'] = True
            elif not ak_v or not sec_v:
                st.error("앱키·시크릿 먼저 입력 후 저장")
            else:
                st.error("4자리 숫자 비번 입력")
        elif act == 'load':
            ck = saved_ck
            cp = saved_cp
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
                    st.session_state['_load_ok'] = True
                    st.rerun()
                except:
                    st.error("❌ 복호화 실패")
        elif act == 'del':
            if 'ck' in qp: del qp['ck']
            if 'cp' in qp: del qp['cp']
            st.rerun()

    if st.session_state.pop('_save_ok', False):
        st.success("✅ 저장 완료!")
    if st.session_state.pop('_load_ok', False):
        st.success("✅ 불러오기 완료! 연결 버튼을 누르세요")

    # ── UI (components.html로 완전 분리 → div 누출 없음) ──
    has_saved = bool(saved_ck)
    components.html(f"""<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0a0e1a;font-family:'Share Tech Mono',monospace;padding:10px 12px;border:1px solid #1a2535;border-radius:8px}}
.title{{font-size:11px;color:#94a3b8;letter-spacing:1px;margin-bottom:8px}}
.saved{{font-size:10px;color:#00ff88;margin-bottom:6px;min-height:14px}}
.row{{display:flex;gap:6px;align-items:center;margin-bottom:6px}}
.pin{{width:90px;flex-shrink:0;padding:8px;background:#0d1220;border:1px solid #1a2535;border-radius:6px;color:#e2e8f0;font-size:16px;letter-spacing:6px;text-align:center;outline:none}}
.pin:focus{{border-color:#00d4ff}}
.btn{{flex:1;padding:9px;border-radius:6px;border:none;cursor:pointer;font-family:'Share Tech Mono',monospace;font-size:12px;transition:all .15s;touch-action:manipulation;-webkit-tap-highlight-color:transparent}}
.bs{{background:rgba(0,212,255,.15);border:1px solid rgba(0,212,255,.4);color:#00d4ff}}
.bs:active{{background:rgba(0,212,255,.3)}}
.bl{{background:rgba(0,255,136,.12);border:1px solid rgba(0,255,136,.35);color:#00ff88}}
.bl:active{{background:rgba(0,255,136,.25)}}
.bd{{flex:0 0 36px;background:rgba(255,77,109,.08);border:1px solid rgba(255,77,109,.25);color:#ff4d6d}}
.msg{{font-size:10px;min-height:14px;color:#ffc800}}
</style>
</head><body>
<div class="title">🔒 간편비번 저장/불러오기</div>
<div class="saved" id="saved">{'💾 저장된 키 있음' if has_saved else ''}</div>
<div class="row">
  <input type="password" class="pin" id="pin" placeholder="····" maxlength="4" inputmode="numeric">
  <button class="btn bs" onclick="doSave()">💾 저장</button>
  <button class="btn bl" onclick="doLoad()">📂 불러오기</button>
  <button class="btn bd" onclick="doDel()">🗑</button>
</div>
<div class="msg" id="msg"></div>
<script>
var CK='ka_ck_v6', CP='ka_cp_v6';
var SAVED_CK={json.dumps(saved_ck)};
var SAVED_CP={json.dumps(saved_cp)};

function xor(s,p){{return s.split('').map((c,i)=>String.fromCharCode(c.charCodeAt(0)^p.charCodeAt(i%4))).join('');}}
function msg(t,c){{var e=document.getElementById('msg');e.textContent=t;e.style.color=c||'#ffc800';setTimeout(()=>e.textContent='',3500);}}
function chk(){{
  var ls=localStorage.getItem(CK);
  var el=document.getElementById('saved');
  el.textContent=(SAVED_CK||ls)?'💾 저장된 키 있음':'';
}}
chk();

function doSave(){{
  var pin=document.getElementById('pin').value;
  if(!/^\\d{{4}}$/.test(pin)){{msg('4자리 숫자 입력','#ff4d6d');return;}}
  // localStorage에 저장 (재시작 후 복원용)
  var lsCk=localStorage.getItem(CK), lsCp=localStorage.getItem(CP);
  if(!SAVED_CK&&!lsCk){{msg('먼저 Streamlit에서 앱키 입력 후 저장 클릭','#ff4d6d');return;}}
  // URL param에 있으면 localStorage에도 백업
  if(SAVED_CK){{localStorage.setItem(CK,SAVED_CK);localStorage.setItem(CP,SAVED_CP);}}
  msg('✅ 저장 완료! (브라우저+URL 이중 저장)','#00ff88');
  chk();
}}

function doLoad(){{
  var pin=document.getElementById('pin').value;
  if(!/^\\d{{4}}$/.test(pin)){{msg('4자리 숫자 입력','#ff4d6d');return;}}
  // URL param 우선, 없으면 localStorage
  var ck=SAVED_CK||localStorage.getItem(CK)||'';
  var cp=SAVED_CP||localStorage.getItem(CP)||'';
  if(!ck){{msg('저장된 키 없음','#ff4d6d');return;}}
  try{{
    if(cp&&atob(cp)!==pin+':kalpha'){{msg('❌ PIN이 틀렸습니다','#ff4d6d');return;}}
    // Python에 비번 전달해서 복호화 → URL로 트리거
    var url=new URL(window.parent.location.href);
    url.searchParams.set('_lpin',pin);
    window.parent.location.replace(url.toString());
  }}catch(e){{msg('복호화 실패','#ff4d6d');}}
}}

function doDel(){{
  localStorage.removeItem(CK);localStorage.removeItem(CP);
  try{{var url=new URL(window.parent.location.href);url.searchParams.delete('ck');url.searchParams.delete('cp');window.parent.location.replace(url.toString());}}catch(e){{}}
  msg('🗑 삭제 완료','#94a3b8');
  document.getElementById('saved').textContent='';
}}
</script>
</body></html>""", height=120, scrolling=False)

    # URL로 PIN 전달 → 자동 불러오기
    if qp.get('_lpin') and saved_ck:
        pin_auto = qp.get('_lpin','')
        try:
            del qp['_lpin']
        except: pass
        if saved_cp and base64.b64decode(saved_cp).decode() != pin_auto+":kalpha":
            st.error("❌ PIN 틀림")
        else:
            try:
                data = py_load(saved_ck, pin_auto)
                st.session_state.kis_ak  = data.get('ak','')
                st.session_state.kis_sec = data.get('sec','')
                st.session_state.kis_acc = data.get('acc','')
                st.session_state.kis_env = data.get('env','실전투자')
                st.success("✅ 불러오기 완료! 연결 버튼을 누르세요")
                st.rerun()
            except:
                st.error("❌ 복호화 실패")

    st.divider()

    if st.session_state.get('_kv_action'):
        act = st.session_state.pop('_kv_action')
        pin_v = st.session_state.pop('_kv_pin','')
        if act == 'save':
            ak_v  = st.session_state.get('kis_ak_inp','') or st.session_state.kis_ak
            sec_v = st.session_state.get('kis_sec_inp','') or st.session_state.kis_sec
            acc_v = st.session_state.get('kis_acc_inp','') or st.session_state.kis_acc
            env_v = st.session_state.get('kis_env_sel','실전투자') or st.session_state.kis_env
            if ak_v and sec_v and len(pin_v)==4 and pin_v.isdigit():
                ck_val = py_save(ak_v,sec_v,acc_v,env_v,pin_v)
                cp_val = base64.b64encode((pin_v+":kalpha").encode()).decode()
                # URL 파라미터에 저장 (가장 영구적)
                qp['ck'] = ck_val
                qp['cp'] = cp_val
                st.session_state['_saved_ck'] = ck_val
                st.session_state['_saved_cp'] = cp_val
                st.success("✅ 저장 완료! 이 URL을 북마크하면 영구 보존됩니다")
            elif not ak_v or not sec_v:
                st.error("앱키·시크릿 먼저 입력 후 저장")
            else:
                st.error("4자리 숫자 비번 입력")
        elif act == 'load':
            ck = saved_ck
            cp = saved_cp
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
            if 'ck' in qp: del qp['ck']
            if 'cp' in qp: del qp['cp']
            st.session_state.pop('_saved_ck',None)
            st.session_state.pop('_saved_cp',None)
            st.rerun()

    # 저장 상태 표시
    st.markdown(f"""<div style="background:#0a0e1a;border:1px solid #1a2535;border-radius:8px;
      padding:10px 12px;margin-bottom:8px">
      <div style="font-family:'Share Tech Mono',monospace;font-size:11px;
        color:#94a3b8;letter-spacing:1px;margin-bottom:8px">
        🔒 간편비번 저장/불러오기
        {'&nbsp;&nbsp;<span style="color:#00ff88;font-size:10px">💾 저장된 키 있음</span>' if saved_ck else ''}
      </div>
    </div>""", unsafe_allow_html=True)

    sv_pin = st.text_input(
        "**비번 4자리 입력**",
        max_chars=4, placeholder="예: 1234",
        key="sv_pin", type="password",
        help="API 키 암호화에 사용할 4자리 숫자"
    )

    sc1,sc2,sc3 = st.columns([1,1,0.35])
    with sc1:
        st.button("💾 저장", use_container_width=True, key="do_save",
                  on_click=lambda: (st.session_state.update({'_kv_action':'save',
                    '_kv_pin':(st.session_state.get('sv_pin') or '').strip()})))
    with sc2:
        st.button("📂 불러오기", use_container_width=True, key="do_load",
                  on_click=lambda: (st.session_state.update({'_kv_action':'load',
                    '_kv_pin':(st.session_state.get('sv_pin') or '').strip()})))
    with sc3:
        st.button("🗑", use_container_width=True, key="do_del_key",
                  on_click=lambda: st.session_state.update({'_kv_action':'del'}))

    st.divider()
    env_label = st.radio("서버", ["실전투자","모의투자"], horizontal=True,
                          index=0 if st.session_state.kis_env=="실전투자" else 1,
                          label_visibility="collapsed", key="kis_env_sel")
    base_url = ("https://openapi.koreainvestment.com:9443" if env_label=="실전투자"
                else "https://openapivts.koreainvestment.com:29443")

    ak  = st.text_input("앱키", type="password", value=st.session_state.kis_ak, placeholder="PSxxxxxxxx...", key="kis_ak_inp")
    sec = st.text_input("시크릿", type="password", value=st.session_state.kis_sec, key="kis_sec_inp")
    acc = st.text_input("계좌번호", value=st.session_state.kis_acc, placeholder="69108332-01", key="kis_acc_inp")

    ca,cb = st.columns([3,1])
    with ca:
        if st.button("🔗 KIS API 연결", use_container_width=True, type="primary", key="btn_connect"):
            if not ak or not sec or not acc: st.error("모두 입력하세요")
            else:
                with st.spinner("연결 중..."):
                    try:
                        r=requests.post(f"{base_url}/oauth2/tokenP",
                            json={"grant_type":"client_credentials","appkey":ak,"appsecret":sec},
                            verify=False, timeout=12)
                        d=r.json()
                        if d.get("access_token"):
                            st.session_state.kis_token=d["access_token"]; st.session_state.kis_base_url=base_url
                            st.session_state.kis_ak=ak; st.session_state.kis_sec=sec
                            st.session_state.kis_acc=acc; st.session_state.kis_env=env_label
                            fetch_prices.clear(); fetch_balance.clear()
                            st.success("✅ 연결 성공!"); st.rerun()
                        else: st.error(f"❌ {d.get('msg1','앱키/시크릿 오류')}")
                    except Exception as e: st.error(f"❌ {str(e)[:100]}")
    with cb:
        if st.session_state.kis_token:
            if st.button("해제", key="btn_disc"):
                st.session_state.kis_token=None; fetch_prices.clear(); fetch_balance.clear(); st.rerun()

    if st.session_state.kis_token:
        st.success(f"✅ {st.session_state.kis_env} · {acc}")

    with st.expander("🔒 로그아웃"):
        if st.button("로그아웃", key="btn_logout"):
            for k in ["agreed","auth","kis_token","kis_ak","kis_sec","kis_acc"]:
                st.session_state[k]=False if k in ["agreed","auth"] else None if k=="kis_token" else ""
            try:
                if 'agreed' in qp: del qp['agreed']
            except: pass
            st.rerun()

# ════════════════════════════════════════
# 4. 현재가 + 잔고 조회
# ════════════════════════════════════════
prices_json="{}"; balance_json="{}"; price_ts=""
if st.session_state.kis_token:
    ca,cb = st.columns([5,1])
    with cb:
        if st.button("↻", key="btn_ref", help="갱신"):
            fetch_prices.clear(); fetch_balance.clear(); st.rerun()
    with ca:
        with st.spinner("현재가·잔고 조회 중..."):
            prices  = fetch_prices(st.session_state.kis_token, st.session_state.kis_base_url,
                                    st.session_state.kis_ak, st.session_state.kis_sec, tuple(KR_CODES))
            balance = fetch_balance(st.session_state.kis_token, st.session_state.kis_base_url,
                                     st.session_state.kis_ak, st.session_state.kis_sec, st.session_state.kis_acc)
        price_ts = time.strftime("%H:%M:%S")
        if prices:
            prices_json = json.dumps(prices)
            # 눈에 잘 보이는 스타일로 표시
            st.markdown(f"""<div style="font-family:'Share Tech Mono',monospace;
              font-size:13px;color:#00d4ff;padding:4px 0;letter-spacing:1px">
              📊 <strong>{len(prices)}</strong>종목 현재가 · <span style="color:#00ff88">{price_ts}</span>
            </div>""", unsafe_allow_html=True)
        if balance and not balance.get('error'):
            balance_json = json.dumps(balance)
            # 잔고 요약은 숨김 (HTML 포트폴리오에 표시됨)
        elif balance and balance.get('error'):
            st.caption(f"⚠ 잔고: {balance.get('error','')[:50]}")

# ════════════════════════════════════════
# 5. HTML 터미널
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
components.html(html, height=5000, scrolling=False)
