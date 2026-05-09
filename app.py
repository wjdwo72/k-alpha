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
    wrong_msg = "❌ 비밀번호가 틀렸습니다" if st.session_state.wrong else ""
    if st.session_state.wrong:
        st.session_state.wrong = False

    # ── st.markdown() = 메인 Streamlit 페이지 컨텍스트
    # <script> 태그는 React가 실행 안 함 → onerror 이벤트 핸들러로 우회
    # onclick 속성은 정상 실행됨 (이미 DOM에 등록된 핸들러)
    # window.location.href = '?auth=1' → 메인 Streamlit 페이지 직접 이동 ✅
    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=Share+Tech+Mono&display=swap');
body,.stApp{{background:#020408!important}}
/* Streamlit 기본 UI 완전 숨김 */
header,[data-testid="stHeader"],[data-testid="stToolbar"],
.stDeployButton,[data-testid="stDecoration"],
footer,.stMarkdown>div>div>div:has(.element-container){{display:none!important}}
.block-container{{padding:0!important;max-width:100%!important}}

.pin-wrap{{display:flex;flex-direction:column;align-items:center;
  justify-content:center;min-height:100vh;background:#020408;
  font-family:'Share Tech Mono',monospace;padding:20px}}
.pin-title{{font-family:'Orbitron',monospace;
  font-size:clamp(22px,7vw,40px);font-weight:700;letter-spacing:6px;
  background:linear-gradient(90deg,#00d4ff,#00ff88);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  text-align:center;margin-bottom:6px}}
.pin-sub{{font-size:11px;color:#4a5568;letter-spacing:2px;
  margin-bottom:28px;text-align:center}}
.pin-box{{background:#0a0e1a;border:1px solid #1a2535;border-radius:16px;
  padding:26px 22px 18px;width:min(300px,88vw)}}
.pin-label{{font-size:10px;color:#4a5568;letter-spacing:2px;
  margin-bottom:10px;text-align:center}}
.pin-dots{{display:flex;justify-content:center;gap:14px;margin-bottom:20px}}
.dot{{width:12px;height:12px;border-radius:50%;
  border:2px solid #1a3a4a;background:transparent;transition:all .2s}}
.dot.f{{background:#00d4ff;border-color:#00d4ff;
  box-shadow:0 0 10px rgba(0,212,255,.7)}}
.pin-grid{{display:grid;grid-template-columns:repeat(3,1fr);
  gap:9px;margin-bottom:9px}}
.pb{{padding:17px 0;border-radius:11px;border:1px solid #1a2535;
  background:#0d1220;color:#e2e8f0;font-size:21px;cursor:pointer;
  text-align:center;user-select:none;touch-action:manipulation;
  transition:background .12s,transform .08s;
  -webkit-tap-highlight-color:transparent}}
.pb:active{{background:#1e2a3a;transform:scale(.91)}}
.pb.e{{visibility:hidden}}
.pb.ent{{background:rgba(0,212,255,.1);border-color:rgba(0,212,255,.35);
  color:#00d4ff;font-size:22px}}
.pb.ent.rdy{{background:rgba(0,212,255,.22);border-color:#00d4ff;
  box-shadow:0 0 12px rgba(0,212,255,.4)}}
.pb.del{{color:#64748b;font-size:15px}}
.pin-err{{text-align:center;color:#ff4d6d;font-size:11px;
  margin-top:12px;min-height:16px}}
</style>

<!-- onerror: <script> 대신 이벤트 핸들러로 JS 실행 (React dangerouslySetInnerHTML 우회) -->
<img src="data:image/gif,X" style="display:none;position:absolute"
onerror="(function(){{
  if(window._pinOK)return; window._pinOK=true;
  var p='',done=false,PW='{PASSWORD}';
  function ud(){{
    for(var i=0;i<4;i++){{
      var d=document.getElementById('pd'+i);
      if(d) d.className='dot'+(i<p.length?' f':'');
    }}
    var e=document.getElementById('pb-ent');
    if(e) e.className='pb ent'+(p.length===4?' rdy':'');
  }}
  function err(){{
    var le=document.getElementById('pin-err');
    if(le)le.textContent='❌ 비밀번호가 틀렸습니다';
    document.querySelectorAll('.dot').forEach(function(d){{
      d.style.background='#ff4d6d';d.style.borderColor='#ff4d6d';
    }});
    setTimeout(function(){{
      p='';done=false;ud();
      var le2=document.getElementById('pin-err');
      if(le2)le2.textContent='';
    }},800);
  }}
  window._pinSubmit=function(){{
    if(done||p.length<4)return;
    done=true;
    if(p===PW){{
      var u=new URL(window.location.href);
      u.searchParams.set('auth','1');
      window.location.href=u.toString();
    }}else{{err();}}
  }};
  window._pp=function(n){{
    if(done||p.length>=4)return;
    p+=String(n);ud();
    if(p.length===4)setTimeout(window._pinSubmit,160);
  }};
  window._pd=function(){{if(done)return;p=p.slice(0,-1);ud();}};
  document.addEventListener('keydown',function(e){{
    if(e.key>='0'&&e.key<='9')window._pp(+e.key);
    else if(e.key==='Backspace')window._pd();
    else if(e.key==='Enter')window._pinSubmit();
  }});
}})()">

<div class="pin-wrap">
  <div class="pin-title">K · ALPHA</div>
  <div class="pin-sub">TRADING TERMINAL · SECURE ACCESS</div>
  <div class="pin-box">
    <div class="pin-label">🔒 PIN 번호 입력</div>
    <div class="pin-dots">
      <div class="dot" id="pd0"></div><div class="dot" id="pd1"></div>
      <div class="dot" id="pd2"></div><div class="dot" id="pd3"></div>
    </div>
    <div class="pin-grid">
      <div class="pb" onclick="window._pp(1)">1</div>
      <div class="pb" onclick="window._pp(2)">2</div>
      <div class="pb" onclick="window._pp(3)">3</div>
      <div class="pb" onclick="window._pp(4)">4</div>
      <div class="pb" onclick="window._pp(5)">5</div>
      <div class="pb" onclick="window._pp(6)">6</div>
      <div class="pb" onclick="window._pp(7)">7</div>
      <div class="pb" onclick="window._pp(8)">8</div>
      <div class="pb" onclick="window._pp(9)">9</div>
      <div class="pb e"></div>
      <div class="pb" onclick="window._pp(0)">0</div>
      <div class="pb ent" id="pb-ent" onclick="window._pinSubmit()">↵</div>
    </div>
    <div class="pb del" onclick="window._pd()" style="width:100%;padding:13px 0;margin-top:0">⌫ 지우기</div>
    <div class="pin-err" id="pin-err">{wrong_msg}</div>
  </div>
</div>
""", unsafe_allow_html=True)
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

    # ── 간편비번 저장/불러오기 (components.html — 독립 저장소) ──
    saved_ck = qp.get('ck','')
    saved_cp = qp.get('cp','')
    cur_url_b64 = base64.b64encode(
        f"?ck={saved_ck}&cp={saved_cp}" .encode()
    ).decode() if saved_ck else ''

    components.html(f"""<!DOCTYPE html>
<html><head><style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:#0a0e1a;font-family:'Share Tech Mono',monospace;
  padding:10px 12px;border:1px solid #1a2535;border-radius:8px;height:auto}}
.t{{font-size:10px;color:#4a5568;letter-spacing:1px;margin-bottom:8px}}
.hint{{font-size:10px;min-height:13px;margin-bottom:5px}}
.row{{display:flex;gap:6px;align-items:stretch}}
.pi{{flex:0 0 90px;padding:8px;background:#0d1220;border:1px solid #1a2535;
  border-radius:6px;color:#e2e8f0;font-size:16px;letter-spacing:6px;
  text-align:center;outline:none}}
.pi:focus{{border-color:#00d4ff}}
.b{{flex:1;padding:9px 4px;border-radius:6px;border:none;cursor:pointer;
  font-size:11px;transition:all .15s;touch-action:manipulation;white-space:nowrap;
  -webkit-tap-highlight-color:transparent}}
.bs{{background:rgba(0,212,255,.12);border:1px solid rgba(0,212,255,.35);color:#00d4ff}}
.bs:active{{background:rgba(0,212,255,.25)}}
.bl{{background:rgba(0,255,136,.1);border:1px solid rgba(0,255,136,.3);color:#00ff88}}
.bl:active{{background:rgba(0,255,136,.2)}}
.bd{{flex:0 0 34px;background:rgba(255,77,109,.08);border:1px solid rgba(255,77,109,.2);
  color:#ff4d6d;font-size:14px}}
.msg{{font-size:10px;margin-top:6px;min-height:14px}}
</style></head><body>
<div class="t">🔒 간편비번 저장/불러오기</div>
<div class="hint" id="h">{'💾 저장된 키 있음 — PIN 입력 후 불러오기' if saved_ck else ''}</div>
<div class="row">
  <input type="password" class="pi" id="pin" placeholder="····"
         maxlength="4" inputmode="numeric"
         oninput="this.value=this.value.replace(/\\D/g,'')">
  <button class="b bs" onclick="doSave()">💾 저장</button>
  <button class="b bl" onclick="doLoad()">📂 불러오기</button>
  <button class="b bd" onclick="doDel()">🗑</button>
</div>
<div class="msg" id="msg"></div>
<script>
const SAVED_CK='{saved_ck}', SAVED_CP='{saved_cp}';
const LS_CK='kalpha_ck_v3', LS_CP='kalpha_cp_v3', LS_AK='kalpha_ak', LS_SEC='kalpha_sec', LS_ACC='kalpha_acc', LS_ENV='kalpha_env';

function xor(s,p){{return s.split('').map((c,i)=>String.fromCharCode(c.charCodeAt(0)^p.charCodeAt(i%4))).join('');}}
function msg(t,ok){{const e=document.getElementById('msg');e.textContent=t;e.style.color=ok?'#00ff88':'#ff4d6d';setTimeout(()=>e.textContent='',4000);}}
function hint(){{
  const s=localStorage.getItem(LS_CK)||SAVED_CK;
  document.getElementById('h').textContent=s?'💾 저장된 키 있음 — PIN 입력 후 불러오기':'';
  document.getElementById('h').style.color='#ffc800';
}}
hint();

function doSave(){{
  const pin=document.getElementById('pin').value;
  if(!/^\\d{{4}}$/.test(pin)){{msg('❌ 4자리 숫자 입력',false);return;}}
  // localStorage에서 현재 입력된 키 값 읽기 (저장된 API 키)
  // 사용자가 입력한 값을 URL 파라미터로 전달해서 Python이 저장
  const ak=localStorage.getItem('_tmp_ak')||'';
  const sec=localStorage.getItem('_tmp_sec')||'';
  const acc=localStorage.getItem('_tmp_acc')||'';
  const env=localStorage.getItem('_tmp_env')||'실전투자';
  if(!ak||!sec){{msg('❌ 앱키/시크릿을 먼저 입력하고 [연결]을 한 번 시도하세요',false);return;}}
  try{{
    function enc(payload,p){{
      const bytes=Array.from(payload).map((c,i)=>c.charCodeAt(0)^p.charCodeAt(i%4));
      return btoa(bytes.map(b=>b.toString(16).padStart(2,'0')).join(''));
    }}
    const payload=JSON.stringify({{ak,sec,acc,env}});
    const encrypted=enc(payload,pin);
    const pinChk=btoa(pin+':kalpha');
    localStorage.setItem(LS_CK,encrypted);
    localStorage.setItem(LS_CP,pinChk);
    hint();
    msg('✅ 저장 완료!',true);
  }}catch(e){{msg('❌ 저장 실패: '+e.message,false);}}
}}

function doLoad(){{
  const pin=document.getElementById('pin').value;
  if(!/^\\d{{4}}$/.test(pin)){{msg('❌ 4자리 숫자 입력',false);return;}}
  const enc=localStorage.getItem(LS_CK)||SAVED_CK;
  const chk=localStorage.getItem(LS_CP)||SAVED_CP;
  if(!enc){{msg('❌ 저장된 키 없음. 먼저 저장하세요.',false);return;}}
  if(chk&&atob(chk)!==pin+':kalpha'){{msg('❌ PIN이 틀렸습니다',false);return;}}
  try{{
    function dec(s,p){{
      const hex=atob(s);
      const bytes=[];for(let i=0;i<hex.length;i+=2)bytes.push(parseInt(hex.substr(i,2),16));
      return xor(bytes.map(b=>String.fromCharCode(b)).join(''),p);
    }}
    const data=JSON.parse(dec(enc,pin));
    // URL 파라미터로 Python에 전달 → Python이 session_state 설정
    const url=new URL(window.parent.location.href);
    url.searchParams.set('do_load','1');
    url.searchParams.set('ck',enc);
    url.searchParams.set('cp',chk);
    url.searchParams.set('lp',pin);
    window.parent.location.href=url.toString();
  }}catch(e){{msg('❌ 복호화 실패. PIN을 확인하세요',false);}}
}}

function doDel(){{
  if(!confirm('저장된 키를 삭제할까요?'))return;
  localStorage.removeItem(LS_CK);localStorage.removeItem(LS_CP);
  hint();msg('🗑 삭제 완료',true);
}}

// API 키 입력값 임시 저장 (저장 버튼용)
window.addEventListener('message', e=>{{
  if(e.data&&e.data.type==='api_vals'){{
    localStorage.setItem('_tmp_ak', e.data.ak||'');
    localStorage.setItem('_tmp_sec', e.data.sec||'');
    localStorage.setItem('_tmp_acc', e.data.acc||'');
    localStorage.setItem('_tmp_env', e.data.env||'실전투자');
  }}
}});
</script></body></html>""", height=115, scrolling=False)

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
                         placeholder="69108332-01", key="kis_acc_inp")

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
components.html(html, height=1400, scrolling=True)
