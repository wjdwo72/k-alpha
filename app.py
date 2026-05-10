import streamlit as st
import streamlit.components.v1 as components
import requests, json, os, base64, urllib3, time, math
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
  .stTextInput label,.stTextInput label p{color:#94a3b8!important;font-size:12px!important}
  .stRadio [data-testid="stMarkdownContainer"] p{color:#e2e8f0!important}
  .stButton>button{font-family:monospace}
  .stRadio>div{flex-direction:row;gap:10px}
  div[data-testid="stSelectSlider"] label p{color:#94a3b8!important;font-size:12px!important}
</style>""", unsafe_allow_html=True)

PASSWORD = "4545"

# ETF/리츠/펀드 필터 키워드
ETF_KEYWORDS = ['ETF','KODEX','TIGER','KBSTAR','ARIRANG','HANARO','KOSEF','ACE ',
                '인버스','레버리지','선물','리츠','REIT','인덱스펀드','스팩','SPAC']

def is_etf(name):
    for kw in ETF_KEYWORDS:
        if kw in name.upper(): return True
    return False

def py_xor(t, p):
    pb=p.encode(); return bytes([ord(c)^pb[i%4] for i,c in enumerate(t)])
def py_save(ak, sec, acc, env, pin):
    return base64.b64encode(py_xor(json.dumps({'ak':ak,'sec':sec,'acc':acc,'env':env}),pin)).decode()
def py_load(enc, pin):
    raw=base64.b64decode(enc); pb=pin.encode()
    return json.loads(''.join(chr(b^pb[i%4]) for i,b in enumerate(raw)))

DEFAULTS = {
    "agreed":False,"auth":False,"pin_buf":"","pin_err":False,
    "kis_token":None,"kis_base_url":None,
    "kis_ak":"","kis_sec":"","kis_acc":"","kis_env":"실전투자",
    "use_pin":True,"auto_connect":True,
    "tg_token":"","tg_chat":"","tg_interval_min":10,"tg_interval_label":"10분",
    "scan_blacklist":[],  # 제외 종목 코드 목록
    "scan_vol_min":50,    # 최소 거래대금(억)
    "scan_rsi_min":20,"scan_rsi_max":75,
}
for k,v in DEFAULTS.items():
    if k not in st.session_state: st.session_state[k]=v

qp = st.query_params
if qp.get('agreed')=='1': st.session_state.agreed=True
if qp.get('no_pin')=='1': st.session_state.use_pin=False
if qp.get('auto_conn')=='1': st.session_state.auto_connect=True
if qp.get('auth')=='1' and not st.session_state.auth:
    st.session_state.auth=True
    try: del qp['auth']
    except: pass
    st.rerun()

# 자동 불러오기 (PIN via URL)
if qp.get('_lpin') and qp.get('ck'):
    pin_a=qp.get('_lpin',''); ck_a=qp.get('ck',''); cp_a=qp.get('cp','')
    try: del qp['_lpin']
    except: pass
    if not cp_a or base64.b64decode(cp_a).decode()==pin_a+":kalpha":
        try:
            d=py_load(ck_a,pin_a)
            st.session_state.kis_ak=d.get('ak',''); st.session_state.kis_sec=d.get('sec','')
            st.session_state.kis_acc=d.get('acc',''); st.session_state.kis_env=d.get('env','실전투자')
            st.session_state['_load_ok']=True
            if st.session_state.auto_connect: st.session_state['_do_auto_connect']=True
            st.rerun()
        except: pass

# ── KIS API 연결 함수 ──
def do_connect(ak, sec, acc, env):
    bu = ("https://openapi.koreainvestment.com:9443" if env=="실전투자"
          else "https://openapivts.koreainvestment.com:29443")
    try:
        r=requests.post(f"{bu}/oauth2/tokenP",
            json={"grant_type":"client_credentials","appkey":ak,"appsecret":sec},
            verify=False, timeout=12)
        d=r.json()
        if d.get("access_token"):
            st.session_state.kis_token=d["access_token"]; st.session_state.kis_base_url=bu
            st.session_state.kis_ak=ak; st.session_state.kis_sec=sec
            st.session_state.kis_acc=acc; st.session_state.kis_env=env
            for fn in [fetch_volume_ranking, fetch_balance]: fn.clear()
            return True, None
        return False, d.get('msg1','앱키/시크릿 오류')
    except Exception as e: return False, str(e)[:100]

if st.session_state.get('_do_auto_connect') and st.session_state.kis_ak:
    del st.session_state['_do_auto_connect']
    do_connect(st.session_state.kis_ak, st.session_state.kis_sec,
               st.session_state.kis_acc, st.session_state.kis_env)
    st.rerun()

# ── 실시간 거래량 순위 스캔 (KOSPI + KOSDAQ) ──
@st.cache_data(ttl=600, show_spinner=False)
def fetch_volume_ranking(token, base_url, ak, secret, mkt_code, top_n=150):
    """KIS 거래량 순위 API로 상위 종목 가져오기"""
    tr_id = 'FHPST01710000'
    headers = {'Content-Type':'application/json', 'authorization':f'Bearer {token}',
                'appkey':ak, 'appsecret':secret, 'tr_id':tr_id}
    try:
        r = requests.get(f"{base_url}/uapi/domestic-stock/v1/ranking/volume",
            params={
                'FID_COND_MRK_DIV_CODE': mkt_code,  # J=코스피, Q=코스닥
                'FID_COND_SCR_DIV_CODE': '20171',
                'FID_INPUT_ISCD': '0000',
                'FID_DIV_CLS_CODE': '0',
                'FID_BLNG_CLS_CODE': '0',
                'FID_TRGT_CLS_CODE': '111111111',
                'FID_TRGT_EXLS_CLS_CODE': '000000',
                'FID_INPUT_PRICE_1': '',
                'FID_INPUT_PRICE_2': '',
                'FID_VOL_CNT': str(top_n),
                'FID_INPUT_DATE_1': ''
            },
            headers=headers, verify=False, timeout=15)
        data = r.json()
        stocks = []
        for item in (data.get('output','') or []):
            name = item.get('hts_kor_isnm','')
            code = item.get('stck_shrn_iscd','')
            if not code or not name: continue
            if is_etf(name): continue
            try:
                price    = int(item.get('stck_prpr','0') or 0)
                change   = int(item.get('prdy_vrss','0') or 0)
                sign     = item.get('prdy_vrss_sign','3')
                chg_pct  = float(item.get('prdy_ctrt','0') or 0)
                vol      = int(item.get('acml_vol','0') or 0)
                tr_amt   = int(item.get('acml_tr_pbmn','0') or 0)  # 거래대금(원)
                tr_amt_억 = tr_amt // 100000000
                if price <= 0: continue
                stocks.append({
                    'code': code, 'name': name,
                    'price': price, 'change': change, 'sign': sign,
                    'changePct': -chg_pct if sign in ['4','5'] else chg_pct,
                    'up': sign in ['1','2'],
                    'vol': vol, 'trAmt': tr_amt_억,
                    'mkt': 'kospi' if mkt_code=='J' else 'kosdaq',
                })
            except: continue
        return stocks
    except Exception as e:
        return []

@st.cache_data(ttl=60, show_spinner=False)
def fetch_balance(token, base_url, ak, secret, acc):
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
            headers=h, verify=False, timeout=10)
        d=r.json()
        return d if d.get('rt_cd')=='0' else {'error':d.get('msg1','잔고조회실패')}
    except Exception as e: return {'error':str(e)}

def categorize_stocks(all_stocks, blacklist, vol_min, rsi_min, rsi_max):
    """스캔 결과를 카테고리별로 분류"""
    # 블랙리스트 제외
    stocks = [s for s in all_stocks if s['code'] not in blacklist]

    swing, surge, tomorrow, smallmid = [], [], [], []
    for s in stocks:
        pct = s.get('changePct', 0)
        tr  = s.get('trAmt', 0)

        if tr < vol_min: continue  # 거래대금 필터

        # RSI 근사값 (등락률 기반 단순 추정)
        rsi_approx = 50 + pct * 2.5
        rsi_approx = max(10, min(90, rsi_approx))
        if not (rsi_min <= rsi_approx <= rsi_max): continue

        s['rsiApprox'] = round(rsi_approx, 1)

        # 카테고리 분류 로직
        if 0.5 <= pct <= 4.0 and tr >= 200:
            # 실시간 스윙: 적당한 상승 + 거래대금 충분
            score = min(95, 70 + int(pct*5) + min(15, tr//500))
            s['score']=score; s['grade']='S' if score>=85 else 'A' if score>=75 else 'B'
            swing.append(s)
        elif pct >= 4.0 and tr >= 100:
            # 급등 전야: 급등 중
            score = min(95, 65 + int(pct*3) + min(20, tr//300))
            s['score']=score; s['grade']='S' if score>=85 else 'A' if score>=75 else 'B'
            surge.append(s)
        elif -1.0 <= pct <= 1.5 and tr >= 50:
            # 내일 관심주: 횡보/소폭 상승
            score = min(90, 60 + min(20, tr//200) + int(abs(pct)*3))
            s['score']=score; s['grade']='S' if score>=80 else 'A' if score>=70 else 'B'
            tomorrow.append(s)

        # 내일의 중소형주: 거래대금 50~500억 (중소형)
        if 50 <= tr <= 500 and -2.0 <= pct <= 3.0:
            score = min(90, 65 + min(15, tr//50) + int(pct*5))
            s2 = dict(s); s2['score']=score; s2['grade']='S' if score>=80 else 'A' if score>=70 else 'B'
            smallmid.append(s2)

    # 점수순 정렬, 상위 N개
    def top(lst, n):
        return sorted(lst, key=lambda x: x.get('score',0), reverse=True)[:n]

    return {
        'swing':    top(swing, 5),
        'surge':    top(surge, 5),
        'tomorrow': top(tomorrow, 5),
        'smallmid': top(smallmid, 10),
    }

def build_card(s, cat):
    """카드 데이터 포맷팅"""
    price = s['price']
    chg   = s['changePct']
    sign  = '+' if chg >= 0 else ''
    buy_p = int(price * 0.995)
    stop_p= int(price * 0.97)
    tgt_p = int(price * 1.10)
    rr    = round((tgt_p-price)/(price-stop_p+1), 1)
    return {
        'name': s['name'], 'code': s['code'],
        'score': s.get('score',70), 'grade': s.get('grade','B'),
        'price': f"{price:,}",
        'change': f"{sign}{chg:.2f}%",
        'up': s['up'],
        'buy': f"{buy_p:,}", 'target': f"{tgt_p:,}", 'stop': f"{stop_p:,}",
        'rr': str(rr), 'vol': s.get('trAmt',0),
        'mkt': s.get('mkt','kospi'),
        'rsiApprox': s.get('rsiApprox', 50),
        'reasons': [
            {'icon':'◈','cat':'green','text':f"거래대금 {s.get('trAmt',0):,}억 · 거래량순위 상위 종목"},
            {'icon':'◉','cat':'','text':f"등락률 {sign}{chg:.2f}% · RSI 추정 {s.get('rsiApprox',50):.0f}"},
            {'icon':'▲','cat':'orange','text':f"매입가 {buy_p:,}원 → 목표 {tgt_p:,}원 · 손절 {stop_p:,}원"},
        ],
        'inds': [
            {'label':s.get('mkt','KOSPI').upper(),'cat':'green'},
            {'label':f"RR {rr}",'cat':''},
            {'label':f"거래대금 {s.get('trAmt',0):,}억",'cat':'orange'},
        ],
        'chart3m': [], 'chartD': [], 'cat': cat,
    }

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
    ❗ 개발자는 금융투자업자가 아니며 이용으로 인한 직접·간접 손해에 대해 민사·형사상 책임을 지지 않습니다.
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
if st.session_state.use_pin and not st.session_state.auth:
    def press(n):
        if st.session_state.pin_err: st.session_state.pin_buf=''; st.session_state.pin_err=False
        if len(st.session_state.pin_buf)<4: st.session_state.pin_buf+=str(n)
        if len(st.session_state.pin_buf)==4:
            if st.session_state.pin_buf==PASSWORD:
                st.session_state.auth=True; st.session_state.pin_buf=''; st.session_state.pin_err=False
            else: st.session_state.pin_err=True; st.session_state.pin_buf=''
    def press_del():
        if st.session_state.pin_err: st.session_state.pin_err=False
        st.session_state.pin_buf=st.session_state.pin_buf[:-1]
    def press_ok():
        if len(st.session_state.pin_buf)==4: press('')
    buf=st.session_state.pin_buf; err=st.session_state.pin_err
    st.markdown("""<style>
body,.stApp{background:#020408!important}
.block-container{padding:8px!important;max-width:360px!important;margin:0 auto!important}
div[data-testid="column"] .stButton button{width:100%!important;height:68px!important;
  background:#0d1220!important;color:#e2e8f0!important;border:1px solid #1a2535!important;
  border-radius:12px!important;font-size:22px!important;font-family:'Share Tech Mono',monospace!important;padding:0!important}
div[data-testid="column"] .stButton button:active{transform:scale(.92)!important}
div[data-testid="column"]:last-child .stButton button{background:rgba(0,212,255,.12)!important;border-color:rgba(0,212,255,.4)!important;color:#00d4ff!important}
.del-btn .stButton button{width:100%!important;height:52px!important;background:#0d1220!important;color:#64748b!important;border:1px solid #1a2535!important;border-radius:10px!important;font-size:14px!important;padding:0!important}
</style>""", unsafe_allow_html=True)
    dots=''.join([f'<div style="width:12px;height:12px;border-radius:50%;'
        +(f'background:#00d4ff;border:2px solid #00d4ff;">' if i<len(buf) else 'border:2px solid #1a3a4a;background:transparent">')
        +'</div>' for i in range(4)])
    st.markdown(f"""<div style="text-align:center;padding:28px 0 18px;font-family:'Share Tech Mono',monospace">
  <div style="font-size:clamp(22px,7vw,40px);font-weight:700;letter-spacing:6px;
    background:linear-gradient(90deg,#00d4ff,#00ff88);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px">K · ALPHA</div>
  <div style="font-size:11px;color:#4a5568;letter-spacing:2px;margin-bottom:20px">SECURE ACCESS</div>
  <div style="background:#0a0e1a;border:1px solid #1a2535;border-radius:16px;padding:22px 20px 14px;width:min(280px,86vw);margin:0 auto">
    <div style="font-size:10px;color:#4a5568;margin-bottom:10px">🔒 PIN 번호 입력</div>
    <div style="display:flex;justify-content:center;gap:14px;margin-bottom:16px">{dots}</div>
    {'<div style="color:#ff4d6d;font-size:11px">❌ 비밀번호가 틀렸습니다</div>' if err else ''}
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

# ════ 3. 메인 패널 ════
if st.session_state.pop('_load_ok',False):
    st.success("✅ 불러오기 완료! 연결 버튼을 누르세요")

label=(f"🔑 KIS API  ✅ {st.session_state.kis_env} 연결됨"
       if st.session_state.kis_token else "🔑 KIS API 설정 ▾")

with st.expander(label, expanded=not bool(st.session_state.kis_token)):
    saved_ck=qp.get('ck',''); saved_cp=qp.get('cp','')

    # ── ⚙ 앱 설정 ──────────────────────────────
    with st.expander("⚙ 앱 설정", expanded=False):
        c1,c2 = st.columns(2)
        with c1:
            use_pin = st.toggle("🔒 PIN 잠금", value=st.session_state.use_pin, key="tog_pin",
                                 help="앱 접속 시 4545 PIN 입력 필요")
            if use_pin != st.session_state.use_pin:
                st.session_state.use_pin=use_pin
                if not use_pin: qp['no_pin']='1'
                else:
                    try: del qp['no_pin']
                    except: pass
        with c2:
            auto_c = st.toggle("⚡ 자동 연결", value=st.session_state.auto_connect, key="tog_auto",
                                help="저장키 불러오기 시 KIS 자동 연결")
            if auto_c != st.session_state.auto_connect:
                st.session_state.auto_connect=auto_c
                if auto_c: qp['auto_conn']='1'
                else:
                    try: del qp['auto_conn']
                    except: pass
        st.divider()
        st.markdown("**📊 스캔 필터 설정**")
        vol_min = st.number_input("최소 거래대금 (억원)", min_value=10, max_value=5000,
                                    value=st.session_state.scan_vol_min, step=10, key="scan_vol_inp")
        st.session_state.scan_vol_min = vol_min
        c3,c4=st.columns(2)
        with c3:
            rsi_min=st.number_input("RSI 최소", min_value=0, max_value=100,
                                     value=st.session_state.scan_rsi_min, key="rsi_min_inp")
            st.session_state.scan_rsi_min=rsi_min
        with c4:
            rsi_max=st.number_input("RSI 최대", min_value=0, max_value=100,
                                     value=st.session_state.scan_rsi_max, key="rsi_max_inp")
            st.session_state.scan_rsi_max=rsi_max

        st.divider()
        st.markdown("**🚫 제외 종목 설정**")
        bl_input = st.text_input("제외할 종목코드 (쉼표 구분)", placeholder="005930,000660,...",
                                   key="bl_inp")
        c5,c6=st.columns(2)
        with c5:
            if st.button("추가", key="btn_bl_add", use_container_width=True):
                new_codes=[c.strip() for c in bl_input.split(',') if c.strip()]
                cur=list(st.session_state.scan_blacklist)
                for c in new_codes:
                    if c not in cur: cur.append(c)
                st.session_state.scan_blacklist=cur
                st.rerun()
        with c6:
            if st.button("초기화", key="btn_bl_clr", use_container_width=True):
                st.session_state.scan_blacklist=[]; st.rerun()
        if st.session_state.scan_blacklist:
            st.caption("제외 중: " + ", ".join(st.session_state.scan_blacklist))

    st.divider()

    # ── 간편비번 저장/불러오기 ──────────────────
    components.html(f"""<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:#0a0e1a;font-family:'Share Tech Mono',monospace;
  padding:10px 12px;border:1px solid #1a2535;border-radius:8px;overflow:hidden}}
.t{{font-size:11px;color:#94a3b8;letter-spacing:1px;margin-bottom:8px}}
.s{{font-size:10px;min-height:14px;margin-bottom:5px}}
.row{{display:flex;gap:6px;align-items:stretch}}
.p{{width:88px;flex-shrink:0;padding:9px 6px;background:#0d1220;border:1px solid #1a2535;
  border-radius:6px;color:#e2e8f0;font-size:16px;letter-spacing:6px;text-align:center;outline:none}}
.p:focus{{border-color:#00d4ff}}
.b{{flex:1;padding:9px 4px;border-radius:6px;border:none;cursor:pointer;
  font-family:'Share Tech Mono',monospace;font-size:12px;touch-action:manipulation}}
.bs{{background:rgba(0,212,255,.15);border:1px solid rgba(0,212,255,.4);color:#00d4ff}}
.bl{{background:rgba(0,255,136,.12);border:1px solid rgba(0,255,136,.35);color:#00ff88}}
.bd{{flex:0 0 34px;background:rgba(255,77,109,.08);border:1px solid rgba(255,77,109,.25);color:#ff4d6d}}
.msg{{font-size:10px;margin-top:5px;min-height:14px}}
</style></head><body>
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
var CK='ka_ck_v9',CP='ka_cp_v9';
var SCK={json.dumps(saved_ck)},SCP={json.dumps(saved_cp)};
function m(t,c){{var e=document.getElementById('msg');e.textContent=t;e.style.color=c||'#ffc800';setTimeout(()=>e.textContent='',4000);}}
function chk(){{
  var s=localStorage.getItem(CK)||SCK;
  var el=document.getElementById('s');
  el.textContent=s?'💾 저장된 키 있음 — PIN 입력 후 불러오기':'저장된 키 없음';
  el.style.color=s?'#00ff88':'#64748b';
}}
chk();
function doSave(){{
  var pin=document.getElementById('pin').value;
  if(!/^\\d{{4}}$/.test(pin)){{m('4자리 숫자 입력','#ff4d6d');return;}}
  if(!SCK){{m('앱키 연결 후 [지금 저장] 버튼 사용','#ff4d6d');return;}}
  localStorage.setItem(CK,SCK);localStorage.setItem(CP,SCP);
  m('✅ 브라우저에 저장 완료','#00ff88');chk();
}}
function doLoad(){{
  var pin=document.getElementById('pin').value;
  if(!/^\\d{{4}}$/.test(pin)){{m('4자리 숫자 입력','#ff4d6d');return;}}
  var ck=SCK||localStorage.getItem(CK)||'';
  var cp=SCP||localStorage.getItem(CP)||'';
  if(!ck){{m('저장된 키 없음','#ff4d6d');return;}}
  try{{if(cp&&atob(cp)!==pin+':kalpha'){{m('❌ PIN 틀림','#ff4d6d');return;}}}}catch(e){{}}
  try{{
    var url=new URL(window.parent.location.href);
    if(!url.searchParams.get('ck')){{url.searchParams.set('ck',ck);url.searchParams.set('cp',cp);}}
    url.searchParams.set('_lpin',pin);
    window.parent.location.replace(url.toString());
  }}catch(e){{m('오류','#ff4d6d');}}
}}
function doDel(){{
  localStorage.removeItem(CK);localStorage.removeItem(CP);
  try{{var url=new URL(window.parent.location.href);url.searchParams.delete('ck');url.searchParams.delete('cp');window.parent.location.replace(url.toString());}}catch(e){{}}
  chk();m('🗑 삭제됨','#94a3b8');
}}
if(!SCK){{
  var lk=localStorage.getItem(CK),lp=localStorage.getItem(CP);
  if(lk){{
    try{{
      var url=new URL(window.parent.location.href);
      if(!url.searchParams.get('ck')){{
        url.searchParams.set('ck',lk);url.searchParams.set('cp',lp||'');
        window.parent.location.replace(url.toString());
      }}
    }}catch(e){{}}
  }}
}}
</script></body></html>""", height=115, scrolling=False)

    # 처음 저장 버튼
    if st.session_state.kis_ak and not saved_ck:
        with st.expander("💾 처음 저장하기"):
            sv_pin=st.text_input("저장용 비번(4자리)",max_chars=4,placeholder="4자리",type="password",key="sv_pin_d")
            if st.button("💾 지금 저장",use_container_width=True,key="btn_save_d"):
                pv=(sv_pin or '').strip()
                if len(pv)==4 and pv.isdigit():
                    ck_v=py_save(st.session_state.kis_ak,st.session_state.kis_sec,
                                 st.session_state.kis_acc,st.session_state.kis_env,pv)
                    cp_v=base64.b64encode((pv+":kalpha").encode()).decode()
                    qp['ck']=ck_v; qp['cp']=cp_v
                    st.success("✅ URL에 저장! 이 URL을 북마크하세요.")
                else: st.error("4자리 숫자 입력")

    st.divider()

    # ── KIS API 연결 ──────────────────────────────
    env_label=st.radio("서버",["실전투자","모의투자"],horizontal=True,
                        index=0 if st.session_state.kis_env=="실전투자" else 1,
                        label_visibility="collapsed",key="kis_env_sel")
    base_url=("https://openapi.koreainvestment.com:9443" if env_label=="실전투자"
              else "https://openapivts.koreainvestment.com:29443")
    ak =st.text_input("앱키",type="password",value=st.session_state.kis_ak,placeholder="PSxxxxxxxx...",key="kis_ak_inp")
    sec=st.text_input("시크릿",type="password",value=st.session_state.kis_sec,key="kis_sec_inp")
    acc=st.text_input("계좌번호",value=st.session_state.kis_acc,placeholder="69108332-01",key="kis_acc_inp")

    ca,cb=st.columns([3,1])
    with ca:
        if st.button("🔗 KIS API 연결",use_container_width=True,type="primary",key="btn_connect"):
            if not ak or not sec or not acc: st.error("모두 입력하세요")
            else:
                with st.spinner("연결 중..."):
                    ok,err=do_connect(ak,sec,acc,env_label)
                    if ok: st.success("✅ 연결 성공!"); st.rerun()
                    else: st.error(f"❌ {err}")
    with cb:
        if st.session_state.kis_token:
            if st.button("해제",key="btn_disc"):
                st.session_state.kis_token=None
                for fn in [fetch_volume_ranking, fetch_balance]: fn.clear()
                st.rerun()
    if st.session_state.kis_token:
        st.success(f"✅ {st.session_state.kis_env} 연결됨")

    st.divider()

    # ── 📱 텔레그램 ──────────────────────────────
    with st.expander("📱 텔레그램 알림 설정", expanded=False):
        tg_token=st.text_input("Bot Token",type="password",value=st.session_state.get('tg_token',''),
                                placeholder="숫자:영문",key="tg_token_inp")
        tg_chat=st.text_input("Chat ID",value=st.session_state.get('tg_chat',''),
                               placeholder="7863087287",key="tg_chat_inp")
        interval_opts={"5분":5,"10분":10,"15분":15,"30분":30,"1시간":60}
        iv_label=st.select_slider("⏱ 자동 전송 간격",options=list(interval_opts.keys()),
                                    value=st.session_state.get('tg_interval_label','10분'),key="tg_iv_sel")
        st.session_state['tg_interval_label']=iv_label
        st.session_state['tg_interval_min']=interval_opts[iv_label]
        c_t1,c_t2=st.columns([2,1])
        with c_t1:
            if st.button("📱 테스트 전송",use_container_width=True,key="btn_tg"):
                if tg_token and tg_chat:
                    try:
                        r=requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage",
                            json={"chat_id":tg_chat,"text":"✅ K-ALPHA 알림 연결 성공!","parse_mode":"HTML"},timeout=8)
                        if r.json().get('ok'):
                            st.session_state['tg_token']=tg_token; st.session_state['tg_chat']=tg_chat
                            st.success("✅ 전송 성공!")
                        else: st.error(f"❌ {r.json().get('description')}")
                    except Exception as e: st.error(f"❌ {e}")
                else: st.error("Token과 Chat ID 입력")
        with c_t2:
            ok=bool(st.session_state.get('tg_token') and st.session_state.get('tg_chat'))
            st.markdown(f'<div style="padding:8px;text-align:center;font-family:monospace;font-size:12px;color:{"#00ff88" if ok else "#4a5568"}">{"🟢 연결됨" if ok else "⭕ 미연결"}</div>',
                        unsafe_allow_html=True)

    with st.expander("🔒 로그아웃"):
        if st.button("로그아웃",key="btn_logout"):
            for k in ["agreed","auth","kis_token","kis_ak","kis_sec","kis_acc"]:
                st.session_state[k]=False if k in ["agreed","auth"] else None if k=="kis_token" else ""
            try:
                if 'agreed' in qp: del qp['agreed']
            except: pass
            st.rerun()

# ════ 4. 실시간 스캔 & 데이터 준비 ════
prices_json="{}"; balance_json="{}"; price_ts=""
scan_json="{}"; scan_count=0

if st.session_state.kis_token:
    ca,cb=st.columns([5,1])
    with cb:
        if st.button("↻",key="btn_ref",help="즉시 갱신"):
            for fn in [fetch_volume_ranking, fetch_balance]: fn.clear()
            st.rerun()
    with ca:
        iv_min=st.session_state.get('tg_interval_min',10)
        with st.spinner(f"KOSPI+KOSDAQ 실시간 스캔 중... (자동갱신 {iv_min}분)"):
            # KOSPI 상위 150 + KOSDAQ 상위 150 = 300종목
            kospi_stocks = fetch_volume_ranking(
                st.session_state.kis_token, st.session_state.kis_base_url,
                st.session_state.kis_ak, st.session_state.kis_sec, 'J', 150)
            kosdaq_stocks = fetch_volume_ranking(
                st.session_state.kis_token, st.session_state.kis_base_url,
                st.session_state.kis_ak, st.session_state.kis_sec, 'Q', 150)
            balance = fetch_balance(
                st.session_state.kis_token, st.session_state.kis_base_url,
                st.session_state.kis_ak, st.session_state.kis_sec, st.session_state.kis_acc)

        all_stocks = kospi_stocks + kosdaq_stocks
        price_ts = time.strftime("%H:%M:%S")

        # 스캔 결과 분류
        cats = categorize_stocks(
            all_stocks,
            st.session_state.scan_blacklist,
            st.session_state.scan_vol_min,
            st.session_state.scan_rsi_min,
            st.session_state.scan_rsi_max,
        )
        scan_count = len(all_stocks)

        # 카드 데이터 생성
        scan_result = {
            'swing':    [build_card(s,'swing')    for s in cats['swing']],
            'surge':    [build_card(s,'surge')    for s in cats['surge']],
            'tomorrow': [build_card(s,'tomorrow') for s in cats['tomorrow']],
            'smallmid': [build_card(s,'smallmid') for s in cats['smallmid']],
            'ts': price_ts,
            'total': scan_count,
        }
        scan_json = json.dumps(scan_result, ensure_ascii=False)

        # 현재가 딕셔너리
        prices = {s['code']:{'price':s['price'],'change':s['change'],
                              'changePct':s['changePct'],'up':s['up']}
                  for s in all_stocks}
        prices_json = json.dumps(prices)

        if balance and not balance.get('error'): balance_json=json.dumps(balance)

        # 상태 표시
        st.markdown(f"""<div style="font-family:monospace;font-size:12px;color:#00d4ff;padding:2px 0;line-height:2">
📊 KOSPI {len(kospi_stocks)}종목 + KOSDAQ {len(kosdaq_stocks)}종목 스캔 완료 · <span style="color:#00ff88">{price_ts}</span><br>
🔍 실시간스윙 {len(cats['swing'])}개 · 급등전야 {len(cats['surge'])}개 · 내일관심 {len(cats['tomorrow'])}개 · 중소형주 {len(cats['smallmid'])}개
</div>""", unsafe_allow_html=True)

    # 텔레그램 자동 알림
    tg_token=st.session_state.get('tg_token',''); tg_chat=st.session_state.get('tg_chat','')
    if tg_token and tg_chat and cats.get('swing'):
        bucket=int(time.time()//(iv_min*60))
        if bucket!=st.session_state.get('_tg_bucket',-1):
            st.session_state['_tg_bucket']=bucket
            top5 = (cats['swing']+cats['surge'])[:5]
            lines=[f"📡 <b>K-ALPHA {iv_min}분 자동 스캔</b> [{price_ts}]\n"
                   f"KOSPI {len(kospi_stocks)}종목 + KOSDAQ {len(kosdaq_stocks)}종목\n━━━━━━━━━━━━━━━━"]
            for s in top5:
                pct=s.get('changePct',0); sign='+' if pct>=0 else ''
                lines.append(f"{'🔴' if s.get('grade')=='S' else '🟡'} "
                             f"<b>[{s.get('grade','B')}·{s.get('score',70)}점] {s['name']}</b>\n"
                             f"   {s['price']:,}원 {sign}{pct:.2f}% | 거래대금 {s.get('trAmt',0):,}억")
            lines.append(f"━━━━━━━━━━━━━━━━\n📊 {scan_count}종목 스캔 완료")
            try:
                requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id":tg_chat,"text":"\n\n".join(lines),"parse_mode":"HTML"},timeout=8)
            except: pass

# ════ 5. HTML 터미널 ════
if not os.path.exists("app.html"):
    st.error("app.html 파일을 GitHub 저장소에 업로드하세요."); st.stop()
with open("app.html","r",encoding="utf-8") as f: html=f.read()
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
window.__SCAN_RESULT__  = {scan_json};
window.__SCAN_COUNT__   = {scan_count};
window.__TG_TOKEN__     = {json.dumps(st.session_state.get('tg_token',''))};
window.__TG_CHAT__      = {json.dumps(st.session_state.get('tg_chat',''))};
window.__TG_INTERVAL__  = {st.session_state.get('tg_interval_min',10)*60*1000};
</script>"""
html=html.replace("</head>",inject+"\n</head>")
components.html(html,height=5000,scrolling=False)
