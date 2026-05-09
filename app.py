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
  .stTextInput label,.stTextInput label p{color:#94a3b8!important;font-family:'Share Tech Mono',monospace!important;font-size:12px!important}
  .stRadio [data-testid="stMarkdownContainer"] p{color:#e2e8f0!important}
  .stButton>button{font-family:monospace}
  .stRadio>div{flex-direction:row;gap:10px}
</style>""", unsafe_allow_html=True)

PASSWORD = "4545"
KR_CODES = ['009150','066570','005490','005380','105560',
            '011070','247540','068270','000660','035720',
            '006400','012450','267260','035420','096770',
            '058470','140860','039440','320000','084370',
            '454910','039030','005420','064760','036830']

def py_xor(text, pin):
    pb=pin.encode(); return bytes([ord(c)^pb[i%4] for i,c in enumerate(text)])
def py_save(ak,sec,acc,env,pin):
    return base64.b64encode(py_xor(json.dumps({'ak':ak,'sec':sec,'acc':acc,'env':env}),pin)).decode()
def py_load(encoded, pin):
    raw=base64.b64decode(encoded); pb=pin.encode()
    return json.loads(''.join(chr(b^pb[i%4]) for i,b in enumerate(raw)))

for k,v in [("agreed",False),("auth",False),("wrong",False),
            ("kis_token",None),("kis_base_url",None),
            ("kis_ak",""),("kis_sec",""),("kis_acc",""),("kis_env","실전투자"),
            ("pin_buf",""),("pin_err",False)]:
    if k not in st.session_state: st.session_state[k]=v

qp = st.query_params

# URL params 처리
if qp.get('agreed')=='1': st.session_state.agreed=True
if qp.get('auth')=='1' and not st.session_state.auth:
    st.session_state.auth=True
    try: del qp['auth']
    except: pass
    st.rerun()

# PIN으로 자동 불러오기 (components.html → URL → Python)
if qp.get('_lpin') and qp.get('ck'):
    pin_auto=qp.get('_lpin',''); ck_auto=qp.get('ck',''); cp_auto=qp.get('cp','')
    try: del qp['_lpin']
    except: pass
    if not cp_auto or base64.b64decode(cp_auto).decode()==pin_auto+":kalpha":
        try:
            data=py_load(ck_auto,pin_auto)
            st.session_state.kis_ak=data.get('ak',''); st.session_state.kis_sec=data.get('sec','')
            st.session_state.kis_acc=data.get('acc',''); st.session_state.kis_env=data.get('env','실전투자')
            st.session_state['_load_ok']=True; st.rerun()
        except: st.error("❌ 복호화 실패")
    else: st.error("❌ PIN 틀림")

@st.cache_data(ttl=30, show_spinner=False)
def fetch_prices(token,base_url,ak,secret,codes_tuple):
    prices={}
    headers={'Content-Type':'application/json','authorization':f'Bearer {token}',
              'appkey':ak,'appsecret':secret,'tr_id':'FHKST01010100'}
    for code in codes_tuple:
        try:
            r=requests.get(f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
                params={'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code},
                headers=headers,verify=False,timeout=5)
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
def fetch_balance(token,base_url,ak,secret,acc):
    try:
        a=acc.replace('-','').replace(' ',''); cano=a[:8]; acd=a[8:10] if len(a)>=10 else '01'
        tr='VTTC8434R' if 'openapivts' in base_url else 'TTTC8434R'
        h={'Content-Type':'application/json','authorization':f'Bearer {token}',
           'appkey':ak,'appsecret':secret,'tr_id':tr,'custtype':'P'}
        r=requests.get(f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
            params={'CANO':cano,'ACNT_PRDT_CD':acd,'AFHR_FLPR_YN':'N','OFL_YN':'',
                    'INQR_DVSN':'02','UNPR_DVSN':'01','FUND_STTL_ICLD_YN':'N',
                    'FNCG_AMT_AUTO_RDPT_YN':'N','PRCS_DVSN':'01',
                    'CTX_AREA_FK100':'','CTX_AREA_NK100':''},
            headers=h,verify=False,timeout=10)
        d=r.json()
        return d if d.get('rt_cd')=='0' else {'error':d.get('msg1','잔고조회실패')}
    except Exception as e: return {'error':str(e)}

# ════ 1. 법적 고지 ════
if not st.session_state.agreed:
    st.markdown("""<style>body,.stApp{background:#020408!important}
.block-container{padding:12px!important;max-width:520px!important;margin:0 auto!important}</style>""",
    unsafe_allow_html=True)
    st.markdown("""<div style="text-align:center;padding:20px 0 14px;font-family:'Share Tech Mono',monospace">
  <div style="font-size:28px;font-weight:700;letter-spacing:5px;background:linear-gradient(90deg,#00d4ff,#00ff88);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent">K · ALPHA</div>
  <div style="font-size:10px;color:#4a5568;letter-spacing:2px;margin-top:4px">TRADING TERMINAL</div>
</div>
<div style="background:#0a0e1a;border:1px solid rgba(255,165,0,0.4);border-radius:12px;padding:16px;margin-bottom:12px;font-family:'Share Tech Mono',monospace">
  <div style="color:#ffc800;font-size:13px;font-weight:700;margin-bottom:10px">⚠ 투자 위험 고지 및 면책 조항</div>
  <div style="background:#020408;border-radius:8px;padding:12px;font-size:11px;color:#64748b;line-height:2;margin-bottom:10px;border:1px solid #1a2535">
    • 개발자는 투자 결과에 대해 <strong style="color:#ff4d6d">일체의 법적 책임을 지지 않습니다</strong><br>
    • 모든 분석·신호는 <strong style="color:#ffc800">참고 목적</strong>이며 결과를 보장하지 않습니다<br>
    • <strong style="color:#ff4d6d">원금 손실 위험</strong>이 있으며 최종 판단은 <strong style="color:#e2e8f0">이용자 본인</strong>에게 있습니다<br>
    • 자동매매 손실·오류에 대해 개발자는 <strong style="color:#ff4d6d">법적 책임을 지지 않습니다</strong><br>
    • 한국투자증권과 <strong style="color:#ffc800">무관한 독립 개인 개발 도구</strong>입니다
  </div>
  <div style="background:rgba(255,77,109,0.06);border:1px solid rgba(255,77,109,0.25);border-radius:8px;padding:10px;font-size:11px;color:#ff4d6d;line-height:1.8">
    ❗ 개발자는 금융투자업자가 아니며 서비스 이용으로 인한 <strong>직접·간접 손해</strong>에 대해 민사·형사상 책임을 지지 않습니다.
  </div>
</div>""", unsafe_allow_html=True)
    c1,c2=st.columns(2)
    with c1:
        if st.button("✗ 동의하지 않음", use_container_width=True): st.warning("동의가 필요합니다.")
    with c2:
        if st.button("✓ 동의하고 시작", use_container_width=True, type="primary"):
            st.session_state.agreed=True; qp['agreed']='1'; st.rerun()
    st.stop()

# ════ 2. PIN 화면 ════
if not st.session_state.auth:
    def press(n):
        if st.session_state.pin_err: st.session_state.pin_buf=''; st.session_state.pin_err=False
        if len(st.session_state.pin_buf)<4: st.session_state.pin_buf+=str(n)
        if len(st.session_state.pin_buf)==4:
            if st.session_state.pin_buf==PASSWORD:
                st.session_state.auth=True; st.session_state.pin_buf=''; st.session_state.pin_err=False
            else:
                st.session_state.pin_err=True; st.session_state.pin_buf=''
    def press_del():
        if st.session_state.pin_err: st.session_state.pin_err=False
        st.session_state.pin_buf=st.session_state.pin_buf[:-1]
    def press_ok():
        if len(st.session_state.pin_buf)==4: press('')

    buf=st.session_state.pin_buf; err=st.session_state.pin_err
    st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=Share+Tech+Mono&display=swap');
body,.stApp{background:#020408!important}
.block-container{padding:8px!important;max-width:360px!important;margin:0 auto!important}
div[data-testid="column"] .stButton button{width:100%!important;height:68px!important;
  background:#0d1220!important;color:#e2e8f0!important;border:1px solid #1a2535!important;
  border-radius:12px!important;font-size:22px!important;font-family:'Share Tech Mono',monospace!important;
  padding:0!important;margin:0!important;box-shadow:none!important}
div[data-testid="column"] .stButton button:hover{background:#1a2535!important;color:#e2e8f0!important}
div[data-testid="column"] .stButton button:active{background:#1e2a3a!important;transform:scale(.92)!important}
div[data-testid="column"]:last-child .stButton button{background:rgba(0,212,255,.12)!important;
  border-color:rgba(0,212,255,.4)!important;color:#00d4ff!important}
.del-btn .stButton button{width:100%!important;height:52px!important;background:#0d1220!important;
  color:#64748b!important;border:1px solid #1a2535!important;border-radius:10px!important;
  font-size:14px!important;font-family:'Share Tech Mono',monospace!important;padding:0!important}
</style>""", unsafe_allow_html=True)

    dots=''.join([
        f'<div style="width:12px;height:12px;border-radius:50%;transition:all .2s;'
        +(f'background:#00d4ff;border:2px solid #00d4ff;box-shadow:0 0 8px rgba(0,212,255,.7)">'
          if i<len(buf) else f'border:2px solid #1a3a4a;background:transparent">')
        +'</div>' for i in range(4)])
    err_html='<div style="color:#ff4d6d;font-size:11px;margin-bottom:8px">❌ 비밀번호가 틀렸습니다</div>' if err else ''

    st.markdown(f"""<div style="text-align:center;padding:28px 0 18px;font-family:'Share Tech Mono',monospace">
  <div style="font-family:'Orbitron',monospace;font-size:clamp(22px,7vw,40px);font-weight:700;
    letter-spacing:6px;background:linear-gradient(90deg,#00d4ff,#00ff88);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px">K · ALPHA</div>
  <div style="font-size:11px;color:#4a5568;letter-spacing:2px;margin-bottom:20px">TRADING TERMINAL · SECURE ACCESS</div>
  <div style="background:#0a0e1a;border:1px solid #1a2535;border-radius:16px;padding:22px 20px 14px;
    width:min(280px,86vw);margin:0 auto">
    <div style="font-size:10px;color:#4a5568;letter-spacing:2px;margin-bottom:10px">🔒 PIN 번호 입력</div>
    <div style="display:flex;justify-content:center;gap:14px;margin-bottom:16px">{dots}</div>
    {err_html}
  </div>
</div>""", unsafe_allow_html=True)

    for row in [[1,2,3],[4,5,6],[7,8,9]]:
        cols=st.columns(3)
        for c,n in zip(cols,row):
            with c: st.button(str(n),key=f'pb{n}',on_click=press,args=(n,),use_container_width=True)
    c1,c2,c3=st.columns(3)
    with c1: st.markdown('<div style="height:68px"></div>',unsafe_allow_html=True)
    with c2: st.button('0',key='pb0',on_click=press,args=(0,),use_container_width=True)
    with c3: st.button('↵',key='pb_ok',on_click=press_ok,use_container_width=True)
    st.markdown('<div class="del-btn">',unsafe_allow_html=True)
    st.button('⌫  지우기',key='pb_del',on_click=press_del,use_container_width=True)
    st.markdown('</div>',unsafe_allow_html=True)
    st.stop()

# ════ 3. KIS API 패널 ════
if st.session_state.pop('_load_ok',False):
    st.success("✅ 불러오기 완료! 연결 버튼을 누르세요")

label=(f"🔑 KIS API  ✅ {st.session_state.kis_env} 연결됨"
       if st.session_state.kis_token else "🔑 KIS API 연결 ▾")

with st.expander(label,expanded=not bool(st.session_state.kis_token)):

    saved_ck=qp.get('ck',''); saved_cp=qp.get('cp','')

    # ── 간편비번 저장/불러오기 (components.html 단일 UI) ──
    components.html(f"""<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:#0a0e1a;font-family:'Share Tech Mono',monospace;
  padding:10px 12px;border:1px solid #1a2535;border-radius:8px;overflow:hidden}}
.t{{font-size:11px;color:#94a3b8;letter-spacing:1px;margin-bottom:8px}}
.s{{font-size:10px;min-height:14px;margin-bottom:5px;color:#00ff88}}
.row{{display:flex;gap:6px;align-items:stretch}}
.p{{width:88px;flex-shrink:0;padding:9px 6px;background:#0d1220;border:1px solid #1a2535;
  border-radius:6px;color:#e2e8f0;font-size:16px;letter-spacing:6px;text-align:center;outline:none}}
.p:focus{{border-color:#00d4ff}}
.b{{flex:1;padding:9px 4px;border-radius:6px;border:none;cursor:pointer;
  font-family:'Share Tech Mono',monospace;font-size:12px;transition:all .15s;
  touch-action:manipulation;-webkit-tap-highlight-color:transparent;white-space:nowrap}}
.bs{{background:rgba(0,212,255,.15);border:1px solid rgba(0,212,255,.4);color:#00d4ff}}
.bs:active{{background:rgba(0,212,255,.3)}}
.bl{{background:rgba(0,255,136,.12);border:1px solid rgba(0,255,136,.35);color:#00ff88}}
.bl:active{{background:rgba(0,255,136,.25)}}
.bd{{flex:0 0 34px;background:rgba(255,77,109,.08);border:1px solid rgba(255,77,109,.25);
  color:#ff4d6d;font-size:14px}}
.msg{{font-size:10px;margin-top:5px;min-height:14px}}
</style>
</head><body>
<div class="t">🔒 간편비번 저장/불러오기</div>
<div class="s" id="s">{"💾 저장된 키 있음 — PIN 입력 후 불러오기" if saved_ck else "저장된 키 없음"}</div>
<div class="row">
  <input type="password" class="p" id="pin" placeholder="····"
    maxlength="4" inputmode="numeric" oninput="this.value=this.value.replace(/\\D/g,'')">
  <button class="b bs" onclick="doSave()">💾 저장</button>
  <button class="b bl" onclick="doLoad()">📂 불러오기</button>
  <button class="b bd" onclick="doDel()">🗑</button>
</div>
<div class="msg" id="msg"></div>
<script>
var CK='ka_ck_v7', CP='ka_cp_v7';
var SCK={json.dumps(saved_ck)}, SCP={json.dumps(saved_cp)};
function msg(t,c){{var e=document.getElementById('msg');e.textContent=t;e.style.color=c||'#ffc800';setTimeout(()=>e.textContent='',4000);}}
function chkSaved(){{
  var ls=localStorage.getItem(CK)||SCK;
  var el=document.getElementById('s');
  el.textContent=ls?'💾 저장된 키 있음 — PIN 입력 후 불러오기':'저장된 키 없음';
  el.style.color=ls?'#00ff88':'#64748b';
}}
chkSaved();
function doSave(){{
  var pin=document.getElementById('pin').value;
  if(!/^\\d{{4}}$/.test(pin)){{msg('4자리 숫자 입력','#ff4d6d');return;}}
  if(!SCK){{msg('먼저 앱키 입력 후 Streamlit에서 저장','#ff4d6d');return;}}
  // URL에 있는 암호화 키를 localStorage에 백업
  localStorage.setItem(CK,SCK);localStorage.setItem(CP,SCP);
  msg('✅ 브라우저에 백업 저장 완료','#00ff88');chkSaved();
}}
function doLoad(){{
  var pin=document.getElementById('pin').value;
  if(!/^\\d{{4}}$/.test(pin)){{msg('4자리 숫자 입력','#ff4d6d');return;}}
  var ck=SCK||localStorage.getItem(CK)||'';
  var cp=SCP||localStorage.getItem(CP)||'';
  if(!ck){{msg('저장된 키 없음 — 먼저 저장하세요','#ff4d6d');return;}}
  try{{if(cp&&atob(cp)!==pin+':kalpha'){{msg('❌ PIN이 틀렸습니다','#ff4d6d');return;}}}}catch(e){{}}
  // URL에 PIN 전달 → Python이 복호화
  try{{
    var url=new URL(window.parent.location.href);
    // localStorage 키도 URL에 올리기
    if(!url.searchParams.get('ck')){{url.searchParams.set('ck',ck);url.searchParams.set('cp',cp);}}
    url.searchParams.set('_lpin',pin);
    window.parent.location.replace(url.toString());
  }}catch(e){{msg('브라우저 제한 — PIN: '+pin,'#ff4d6d');}}
}}
function doDel(){{
  localStorage.removeItem(CK);localStorage.removeItem(CP);
  try{{var url=new URL(window.parent.location.href);url.searchParams.delete('ck');url.searchParams.delete('cp');window.parent.location.replace(url.toString());}}catch(e){{}}
  document.getElementById('s').textContent='저장된 키 없음';
  document.getElementById('s').style.color='#64748b';
  msg('🗑 삭제 완료','#94a3b8');
}}
// localStorage → URL 자동 복원
if(!SCK){{
  var lsCk=localStorage.getItem(CK),lsCp=localStorage.getItem(CP);
  if(lsCk){{
    try{{var url=new URL(window.parent.location.href);
      if(!url.searchParams.get('ck')){{url.searchParams.set('ck',lsCk);url.searchParams.set('cp',lsCp||'');
        window.parent.location.replace(url.toString());}}
    }}catch(e){{}}
  }}
}}
</script>
</body></html>""", height=118, scrolling=False)

    # 저장 버튼 (Python side, URL에 저장)
    st.markdown("---")
    with st.expander("📌 처음 저장 방법 (앱키 입력 후)", expanded=False):
        st.markdown("""<div style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#94a3b8;line-height:2">
1. 아래에서 앱키/시크릿/계좌번호 입력<br>
2. 🔗 KIS API 연결 클릭<br>
3. 위 칸에 비번 4자리 입력 → 💾 저장<br>
4. 이 페이지 URL을 <strong style="color:#00d4ff">북마크</strong> 저장<br>
5. 다음 접속: 북마크 URL → 비번 입력 → 📂 불러오기
</div>""", unsafe_allow_html=True)

    env_label=st.radio("서버",["실전투자","모의투자"],horizontal=True,
                        index=0 if st.session_state.kis_env=="실전투자" else 1,
                        label_visibility="collapsed",key="kis_env_sel")
    base_url=("https://openapi.koreainvestment.com:9443" if env_label=="실전투자"
              else "https://openapivts.koreainvestment.com:29443")

    ak=st.text_input("앱키",type="password",value=st.session_state.kis_ak,
                      placeholder="PSxxxxxxxx...",key="kis_ak_inp")
    sec=st.text_input("시크릿",type="password",value=st.session_state.kis_sec,key="kis_sec_inp")
    acc=st.text_input("계좌번호",value=st.session_state.kis_acc,placeholder="69108332-01",key="kis_acc_inp")

    # 최초 저장 버튼 (앱키 있을 때만)
    if ak and sec and not saved_ck:
        sv_pin=st.text_input("저장용 비번(4자리)",max_chars=4,placeholder="4자리",
                              type="password",key="sv_pin_direct")
        if st.button("💾 지금 저장",use_container_width=True,key="btn_save_direct"):
            pin_v=(sv_pin or '').strip()
            if len(pin_v)==4 and pin_v.isdigit():
                ck_v=py_save(ak,sec,acc,env_label,pin_v)
                cp_v=base64.b64encode((pin_v+":kalpha").encode()).decode()
                qp['ck']=ck_v; qp['cp']=cp_v
                st.success("✅ URL에 저장! 이 URL을 북마크하세요.")
            else: st.error("4자리 숫자 입력")

    ca,cb=st.columns([3,1])
    with ca:
        if st.button("🔗 KIS API 연결",use_container_width=True,type="primary",key="btn_connect"):
            if not ak or not sec or not acc: st.error("모두 입력하세요")
            else:
                with st.spinner("연결 중..."):
                    try:
                        r=requests.post(f"{base_url}/oauth2/tokenP",
                            json={"grant_type":"client_credentials","appkey":ak,"appsecret":sec},
                            verify=False,timeout=12)
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
            if st.button("해제",key="btn_disc"):
                st.session_state.kis_token=None; fetch_prices.clear(); fetch_balance.clear(); st.rerun()

    if st.session_state.kis_token:
        st.success(f"✅ {st.session_state.kis_env} · {acc}")

    st.divider()

    # ── 텔레그램 알림 설정 ──
    st.markdown("**📱 텔레그램 알림 설정**", unsafe_allow_html=False)
    tg_token = st.text_input("Bot Token", type="password",
                              value=st.session_state.get('tg_token',''),
                              placeholder="1234567890:ABCdef...",
                              key="tg_token_inp",
                              help="@BotFather에서 발급")
    tg_chat  = st.text_input("Chat ID",
                              value=st.session_state.get('tg_chat',''),
                              placeholder="-100xxxxxxxxx 또는 숫자",
                              key="tg_chat_inp",
                              help="@userinfobot 에서 확인")

    col_tg1, col_tg2 = st.columns([2,1])
    with col_tg1:
        if st.button("📱 테스트 알림 전송", use_container_width=True, key="btn_tg_test"):
            if tg_token and tg_chat:
                try:
                    r = requests.post(
                        f"https://api.telegram.org/bot{tg_token}/sendMessage",
                        json={"chat_id": tg_chat,
                              "text": "✅ K-ALPHA 터미널 알림 연결 성공!\n\n"
                                      "S급 종목 포착 시 자동 알림이 전송됩니다.",
                              "parse_mode": "HTML"},
                        timeout=8)
                    if r.json().get('ok'):
                        st.session_state['tg_token'] = tg_token
                        st.session_state['tg_chat']  = tg_chat
                        st.success("✅ 텔레그램 연결 성공!")
                    else:
                        st.error(f"❌ {r.json().get('description','전송 실패')}")
                except Exception as e:
                    st.error(f"❌ {str(e)[:80]}")
            else:
                st.error("Bot Token과 Chat ID를 입력하세요")
    with col_tg2:
        tg_ok = bool(st.session_state.get('tg_token') and st.session_state.get('tg_chat'))
        st.markdown(f"""<div style="padding:8px;text-align:center;font-family:monospace;font-size:12px;
          color:{'#00ff88' if tg_ok else '#4a5568'}">
          {'🟢 연결됨' if tg_ok else '⭕ 미연결'}</div>""", unsafe_allow_html=True)

    with st.expander("🔒 로그아웃"):
        if st.button("로그아웃",key="btn_logout"):
            for k in ["agreed","auth","kis_token","kis_ak","kis_sec","kis_acc"]:
                st.session_state[k]=False if k in ["agreed","auth"] else None if k=="kis_token" else ""
            try:
                if 'agreed' in qp: del qp['agreed']
            except: pass
            st.rerun()

# ════ 4. 현재가 + 잔고 ════
prices_json="{}"; balance_json="{}"; price_ts=""
if st.session_state.kis_token:
    ca,cb=st.columns([5,1])
    with cb:
        if st.button("↻",key="btn_ref",help="갱신"):
            fetch_prices.clear(); fetch_balance.clear(); st.rerun()
    with ca:
        with st.spinner("조회 중..."):
            prices=fetch_prices(st.session_state.kis_token,st.session_state.kis_base_url,
                                 st.session_state.kis_ak,st.session_state.kis_sec,tuple(KR_CODES))
            balance=fetch_balance(st.session_state.kis_token,st.session_state.kis_base_url,
                                   st.session_state.kis_ak,st.session_state.kis_sec,st.session_state.kis_acc)
        price_ts=time.strftime("%H:%M:%S")
        if prices:
            prices_json=json.dumps(prices)
            st.markdown(f'<div style="font-family:monospace;font-size:13px;color:#00d4ff;padding:2px 0">'
                        f'📊 <strong>{len(prices)}</strong>종목 · <span style="color:#00ff88">{price_ts}</span></div>',
                        unsafe_allow_html=True)
        if balance and not balance.get('error'): balance_json=json.dumps(balance)
        elif balance and balance.get('error'): st.caption(f"⚠ 잔고: {balance.get('error','')[:50]}")

    # ── 텔레그램 S급 알림 (10분마다, 최대 5개) ──
    tg_token = st.session_state.get('tg_token','')
    tg_chat  = st.session_state.get('tg_chat','')
    if tg_token and tg_chat and prices:
        # 10분 간격 체크
        now_min = int(time.time() // 600)  # 10분 단위 버킷
        last_bucket = st.session_state.get('_tg_bucket', -1)
        if now_min != last_bucket:
            st.session_state['_tg_bucket'] = now_min
            DEMO_STOCKS = [
                {'name':'리노공업','code':'058470','score':94,'grade':'S','buy':'182,000','target':'205,000','stop':'176,500','rr':'4.1'},
                {'name':'파크시스템스','code':'140860','score':91,'grade':'S','buy':'211,000','target':'238,000','stop':'204,500','rr':'4.2'},
                {'name':'삼성전기','code':'009150','score':91,'grade':'S','buy':'168,000','target':'182,000','stop':'163,100','rr':'2.6'},
                {'name':'LG이노텍','code':'011070','score':88,'grade':'S','buy':'182,000','target':'210,000','stop':'176,000','rr':'4.7'},
                {'name':'한화에어로스페이스','code':'012450','score':87,'grade':'S','buy':'550,000','target':'640,000','stop':'530,000','rr':'4.5'},
                {'name':'에스티아이','code':'039440','score':88,'grade':'A','buy':'38,500','target':'43,500','stop':'37,300','rr':'4.2'},
                {'name':'유진테크','code':'084370','score':85,'grade':'A','buy':'42,600','target':'48,000','stop':'41,200','rr':'3.9'},
            ]
            candidates = [s for s in DEMO_STOCKS if s['score'] >= 85][:5]
            if candidates:
                lines = [f"📡 <b>K-ALPHA 10분 스캔 알림</b> [{price_ts}]\n━━━━━━━━━━━━━━━━"]
                for s in candidates:
                    p = prices.get(s['code'],{})
                    cur = f"{p.get('price',0):,}" if p.get('price') else s['buy']
                    chg = f"{p.get('changePct',0):+.2f}%" if p.get('changePct') else ''
                    icon = '🔴' if s['grade']=='S' else '🟡'
                    lines.append(
                        f"{icon} <b>[{s['grade']}·{s['score']}점] {s['name']}</b>\n"
                        f"   현재가 {cur}원 {chg} | RR {s['rr']}\n"
                        f"   매입 {s['buy']} → 목표 {s['target']} | 손절 {s['stop']}"
                    )
                lines.append(f"━━━━━━━━━━━━━━━━\n📊 {len(prices)}종목 스캔 완료")
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{tg_token}/sendMessage",
                        json={"chat_id": tg_chat, "text": "\n\n".join(lines), "parse_mode": "HTML"},
                        timeout=8)
                except: pass

# ════ 5. HTML 터미널 ════
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
window.__TG_TOKEN__     = {json.dumps(st.session_state.get('tg_token',''))};
window.__TG_CHAT__      = {json.dumps(st.session_state.get('tg_chat',''))};
</script>"""
html=html.replace("</head>",inject+"\n</head>")
components.html(html,height=5000,scrolling=False)
