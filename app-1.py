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
            ("kis_ak",""),("kis_sec",""),("kis_acc",""),("kis_env","실전투자"),
            ("pin_val",""),("save_msg",""),("save_msg_ok",True)]:
    if k not in st.session_state: st.session_state[k]=v

qp = st.query_params
saved_creds   = qp.get('ck','')
saved_pin_chk = qp.get('cp','')

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
    except Exception as e:
        return {'error':str(e)}

# ────────────────────────────────────────
# PIN on_change handler
# ────────────────────────────────────────
def on_pin_change():
    val = st.session_state.get('pin_val','')
    if len(val) == 4:
        if val == PASSWORD:
            st.session_state.auth = True
            st.session_state.wrong = False
        else:
            st.session_state.wrong = True
            st.session_state.pin_val = ''

# ════════════════════════════════════════
# 비밀번호 화면
# ════════════════════════════════════════
if not st.session_state.auth:
    wrong_msg = "❌ 비밀번호가 틀렸습니다" if st.session_state.wrong else ""
    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=Share+Tech+Mono&display=swap');
body,.stApp{{background:#020408!important}}
.lw{{display:flex;flex-direction:column;align-items:center;justify-content:center;
  min-height:80vh;background:#020408;font-family:'Share Tech Mono',monospace;padding:20px}}
.lt{{font-family:'Orbitron',monospace;font-size:clamp(22px,6vw,40px);font-weight:700;
  letter-spacing:6px;background:linear-gradient(90deg,#00d4ff,#00ff88);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  text-align:center;margin-bottom:4px}}
.ls{{font-size:11px;color:#4a5568;letter-spacing:2px;margin-bottom:28px;text-align:center}}
.lb{{background:#0a0e1a;border:1px solid #1a2535;border-radius:16px;
  padding:28px 24px 20px;width:min(300px,90vw);box-shadow:0 0 40px rgba(0,212,255,.08)}}
.ll{{font-size:11px;color:#4a5568;letter-spacing:2px;margin-bottom:10px;text-align:center}}
.ld{{display:flex;justify-content:center;gap:12px;margin-bottom:20px}}
.dot{{width:12px;height:12px;border-radius:50%;border:2px solid #1a3a4a;background:transparent;transition:all .2s}}
.dot.f{{background:#00d4ff;border-color:#00d4ff;box-shadow:0 0 8px rgba(0,212,255,.6)}}
.np{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}
.nb{{padding:16px 0;border-radius:12px;border:1px solid #1a2535;background:#0d1220;
  color:#e2e8f0;font-family:'Share Tech Mono',monospace;font-size:20px;
  cursor:pointer;text-align:center;transition:background .15s,transform .1s;
  -webkit-tap-highlight-color:transparent;user-select:none;touch-action:manipulation}}
.nb:active{{background:#1a2535;transform:scale(.93)}}
.nb.d{{font-size:15px;color:#64748b}}.nb.e{{visibility:hidden}}
.le{{text-align:center;color:#ff4d6d;font-size:11px;margin-top:12px;min-height:16px}}
</style>
<div class="lw">
  <div class="lt">K · ALPHA</div>
  <div class="ls">TRADING TERMINAL · SECURE ACCESS</div>
  <div class="lb">
    <div class="ll">🔒 PIN 번호 입력</div>
    <div class="ld">
      <div class="dot" id="d0"></div><div class="dot" id="d1"></div>
      <div class="dot" id="d2"></div><div class="dot" id="d3"></div>
    </div>
    <div class="np">
      {''.join([f'<div class="nb" onclick="pp({i})">{i}</div>' for i in [1,2,3,4,5,6,7,8,9]])}
      <div class="nb e"></div>
      <div class="nb" onclick="pp(0)">0</div>
      <div class="nb d" onclick="pd()">⌫</div>
    </div>
    <div class="le">{wrong_msg}</div>
  </div>
</div>
<script>
let p=""; const PW="{PASSWORD}"; let done=false;
function ud(){{
  for(let i=0;i<4;i++){{
    const d=document.getElementById("d"+i);
    if(i<p.length){{d.classList.add("f");d.style.cssText="";}}
    else{{d.classList.remove("f");d.style.cssText="";}}
  }}
}}
function fill(val){{
  // Streamlit text_input 찾아서 값 설정
  const inp=document.querySelector('input[data-testid="stTextInput-RootElement"] input, input[type="password"]');
  if(!inp)return false;
  const proto=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value');
  proto.set.call(inp,val);
  inp.dispatchEvent(new Event('input',{{bubbles:true}}));
  inp.dispatchEvent(new Event('change',{{bubbles:true}}));
  inp.dispatchEvent(new FocusEvent('blur',{{bubbles:true}}));
  return true;
}}
function pp(n){{
  if(done||p.length>=4)return;
  p+=String(n); ud();
  if(p.length===4){{
    done=true;
    if(p===PW){{
      // 정답: Streamlit input 채우고 blur 발생
      setTimeout(()=>{{
        if(!fill(p)){{
          // fallback: 직접 input 찾기
          document.querySelectorAll('input').forEach(i=>{{
            if(i.type==='password'||i.getAttribute('aria-label')==='PIN')fill2(i,p);
          }});
        }}
      }},50);
    }}else{{
      // 오답: 빨간 점 표시 후 리셋
      document.querySelectorAll('.dot').forEach(d=>{{
        d.style.background='#ff4d6d';d.style.borderColor='#ff4d6d';
      }});
      fill(p); // Streamlit에 전달해서 wrong 처리
      setTimeout(()=>{{p="";done=false;ud();}},800);
    }}
  }}
}}
function pd(){{if(done)return;p=p.slice(0,-1);ud();}}
document.addEventListener('keydown',e=>{{
  if(e.key>='0'&&e.key<='9')pp(parseInt(e.key));
  else if(e.key==='Backspace')pd();
}});
</script>""", unsafe_allow_html=True)

    # on_change 기반 PIN 처리 (blur 이벤트가 트리거)
    st.text_input("PIN", type="password", max_chars=4,
                   label_visibility="collapsed",
                   key="pin_val",
                   on_change=on_pin_change,
                   placeholder="")
    st.stop()

# ════════════════════════════════════════
# KIS API 연결 패널
# ════════════════════════════════════════
label = (f"🔑 KIS API  ✅ {st.session_state.kis_env} 연결됨"
         if st.session_state.kis_token else "🔑 KIS API 연결 ▾")

with st.expander(label, expanded=not bool(st.session_state.kis_token)):

    # ── 간편비번 저장/불러오기 (HTML 컴포넌트로 — 모바일 레이아웃 보장) ──
    has_saved = bool(saved_creds)
    components.html(f"""
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0a0e1a;font-family:'Share Tech Mono',monospace;padding:10px 12px;border:1px solid #1a2535;border-radius:8px}}
.title{{font-size:10px;color:#4a5568;letter-spacing:1px;margin-bottom:8px}}
.saved-hint{{font-size:10px;color:#ffc800;margin-bottom:6px;min-height:14px}}
.row{{display:flex;gap:8px;align-items:center;margin-bottom:6px}}
.pin-inp{{width:100px;padding:8px 10px;background:#0d1220;border:1px solid #1a2535;
  border-radius:6px;color:#e2e8f0;font-family:'Share Tech Mono',monospace;
  font-size:16px;letter-spacing:8px;text-align:center;outline:none;flex-shrink:0}}
.pin-inp:focus{{border-color:#00d4ff}}
.btn{{flex:1;padding:9px 4px;border-radius:6px;border:none;cursor:pointer;
  font-family:'Share Tech Mono',monospace;font-size:12px;transition:all .15s;
  -webkit-tap-highlight-color:transparent;touch-action:manipulation;white-space:nowrap}}
.bs{{background:rgba(0,212,255,.12);border:1px solid rgba(0,212,255,.35);color:#00d4ff}}
.bs:active{{background:rgba(0,212,255,.25)}}
.bl{{background:rgba(0,255,136,.1);border:1px solid rgba(0,255,136,.3);color:#00ff88}}
.bl:active{{background:rgba(0,255,136,.2)}}
.bd{{width:36px;flex:none;background:rgba(255,77,109,.08);border:1px solid rgba(255,77,109,.2);color:#ff4d6d;font-size:14px}}
.msg{{font-size:10px;min-height:14px;padding:2px 0}}
</style>
<div>
  <div class="title">🔒 간편비번 저장/불러오기</div>
  <div class="saved-hint" id="sh">{'💾 저장된 키 있음 — PIN 입력 후 불러오기' if has_saved else ''}</div>
  <div class="row">
    <input type="password" class="pin-inp" id="pin" placeholder="····" maxlength="4" inputmode="numeric" oninput="this.value=this.value.replace(/\\D/g,'')">
    <button class="btn bs" onclick="doSave()">💾 저장</button>
    <button class="btn bl" onclick="doLoad()">📂 불러오기</button>
    <button class="btn bd" onclick="doDel()">🗑</button>
  </div>
  <div class="msg" id="msg"></div>
</div>
<script>
const SK='{saved_creds}',CK='{saved_pin_chk}';
function xor(s,p){{return s.split('').map((c,i)=>String.fromCharCode(c.charCodeAt(0)^p.charCodeAt(i%4))).join('');}}
function msg(t,ok){{const e=document.getElementById('msg');e.textContent=t;e.style.color=ok?'#00ff88':'#ff4d6d';setTimeout(()=>e.textContent='',3500);}}
function getParentInputs(){{
  try{{return Array.from(window.parent.document.querySelectorAll('[data-testid="stTextInput"] input'));}}
  catch(e){{return [];}}
}}
function setVal(inp,v){{
  try{{
    const s=Object.getOwnPropertyDescriptor(window.parent.HTMLInputElement.prototype,'value').set;
    s.call(inp,v);
    ['input','change'].forEach(ev=>inp.dispatchEvent(new Event(ev,{{bubbles:true}})));
  }}catch(e){{inp.value=v;}}
}}
function getFormData(){{
  // parent frame inputs 순서: 비번입력(이 iframe), 실전/모의(radio), 앱키, 시크릿, 계좌번호
  const ins=getParentInputs();
  let ak='',sec='',acc='';
  ins.forEach(inp=>{{
    if(inp.closest('iframe'))return;
    const val=inp.value;
    if(!val)return;
    if(!ak){{ak=val;}}
    else if(!sec){{sec=val;}}
    else if(!acc&&inp.type!=='password'){{acc=val;}}
  }});
  // radio value
  let env='실전투자';
  try{{
    const radios=window.parent.document.querySelectorAll('[data-testid="stRadio"] input[type="radio"]');
    radios.forEach(r=>{{if(r.checked)env=r.nextSibling?.textContent?.trim()||env;}});
  }}catch(e){{}}
  return {{ak,sec,acc,env}};
}}
function doSave(){{
  const pin=document.getElementById('pin').value;
  if(!/^\\d{{4}}$/.test(pin)){{msg('❌ 4자리 숫자 입력',false);return;}}
  const {{ak,sec,acc,env}}=getFormData();
  if(!ak||!sec){{msg('❌ 먼저 앱키/시크릿 입력 후 저장',false);return;}}
  try{{
    const payload=JSON.stringify({{ak,sec,acc,env}});
    function xorEnc(s,p){{return s.split('').map((c,i)=>String.fromCharCode(c.charCodeAt(0)^p.charCodeAt(i%4))).join('');}}
    const enc=btoa(Array.from(xorEnc(payload,pin)).map(c=>c.charCodeAt(0).toString(16).padStart(2,'0')).join(''));
    const chk=btoa(pin+':kalpha');
    // URL 파라미터에 저장 (parent frame)
    try{{
      const url=new URL(window.parent.location.href);
      url.searchParams.set('ck',enc);
      url.searchParams.set('cp',chk);
      window.parent.history.replaceState(null,'',url.toString());
      document.getElementById('sh').textContent='💾 저장됨 (페이지 새로고침 후 URL 북마크)';
      document.getElementById('sh').style.color='#00ff88';
      msg('✅ URL에 저장 완료 — 이 페이지를 북마크하세요!',true);
    }}catch(e){{
      // Same-origin 차단 시 localStorage 폴백
      localStorage.setItem('kalpha_ck',enc);
      localStorage.setItem('kalpha_cp',chk);
      msg('✅ 로컬 저장 완료',true);
    }}
  }}catch(e){{msg('❌ 저장 실패: '+e.message,false);}}
}}
function doLoad(){{
  const pin=document.getElementById('pin').value;
  if(!/^\\d{{4}}$/.test(pin)){{msg('❌ 4자리 숫자 입력',false);return;}}
  // 소스 확인: URL params > localStorage
  let enc=SK, chk=CK;
  if(!enc){{enc=localStorage.getItem('kalpha_ck')||'';chk=localStorage.getItem('kalpha_cp')||'';}}
  if(!enc){{msg('❌ 저장된 키 없음. 먼저 저장하세요.',false);return;}}
  if(chk&&atob(chk)!==pin+':kalpha'){{msg('❌ PIN이 틀렸습니다',false);return;}}
  try{{
    function xorDec(s,p){{return s.split('').map((c,i)=>String.fromCharCode(c.charCodeAt(0)^p.charCodeAt(i%4))).join('');}}
    const hexStr=atob(enc);
    const bytes=[];for(let i=0;i<hexStr.length;i+=2)bytes.push(parseInt(hexStr.substr(i,2),16));
    const data=JSON.parse(xorDec(bytes.map(b=>String.fromCharCode(b)).join(''),pin));
    // parent inputs에 값 주입
    const ins=getParentInputs();
    let idx=0;
    ins.forEach(inp=>{{
      if(inp.closest('iframe'))return;
      if(idx===0&&data.ak){{setVal(inp,data.ak);idx++;}}
      else if(idx===1&&data.sec){{setVal(inp,data.sec);idx++;}}
      else if(idx===2&&data.acc&&inp.type!=='password'){{setVal(inp,data.acc);idx++;}}
    }});
    msg('✅ 불러오기 완료! 연결 버튼을 눌러주세요',true);
  }}catch(e){{msg('❌ 복호화 실패. PIN을 확인하세요',false);}}
}}
function doDel(){{
  if(!confirm('저장된 키를 삭제할까요?'))return;
  try{{const url=new URL(window.parent.location.href);url.searchParams.delete('ck');url.searchParams.delete('cp');window.parent.history.replaceState(null,'',url.toString());}}catch(e){{}}
  localStorage.removeItem('kalpha_ck');localStorage.removeItem('kalpha_cp');
  document.getElementById('sh').textContent='';
  msg('🗑 삭제 완료',true);
}}
// localStorage에도 저장된 게 있으면 힌트 표시
if(!'{saved_creds}'&&localStorage.getItem('kalpha_ck')){{
  document.getElementById('sh').textContent='💾 저장된 키 있음 (로컬) — PIN 입력 후 불러오기';
}}
</script>""", height=110, scrolling=False)

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
    ca, cb = st.columns([5,1])
    with cb:
        if st.button("↻", use_container_width=True, key="btn_ref", help="갱신"):
            fetch_prices.clear(); fetch_balance.clear(); st.rerun()
    with ca:
        with st.spinner("현재가·잔고 조회 중..."):
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
