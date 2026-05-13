import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import requests, json, os, base64, urllib3, time, math
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
def kst_now(): return datetime.now(KST)
def kst_strftime(fmt): return kst_now().strftime(fmt)
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

# ── 종목코드 → 종목명 매핑 (API 이름 누락 시 fallback) ──
# ── 종목명 매핑 테이블 (KIS API 이름 없을 때 fallback — 주의: 틀릴 수 있음) ──
# get_stock_name()은 API 이름을 우선 사용하므로 이 테이블은 거의 사용되지 않음
STOCK_NAMES = {
    # 검증된 코드만 포함 (KRX 실제 코드 기준)
    '005930':'삼성전자','000660':'SK하이닉스','373220':'LG에너지솔루션',
    '207940':'삼성바이오로직스','005380':'현대차','005490':'POSCO홀딩스',
    '035420':'NAVER','000270':'기아','051910':'LG화학',
    '028260':'삼성물산','034730':'SK','066570':'LG전자',
    '017670':'SK텔레콤','032830':'삼성생명','105560':'KB금융','055550':'신한지주',
    '009150':'삼성전기','011070':'LG이노텍','012450':'한화에어로스페이스',
    '035720':'카카오','006400':'삼성SDI','003550':'LG',
    '247540':'에코프로비엠','086520':'에코프로','352820':'하이브',
    '058470':'리노공업','140860':'파크시스템스','039440':'에스티아이',
    '084370':'유진테크','454910':'두산로보틱스','039030':'이오테크닉스',
    '064760':'티씨케이','036830':'솔브레인홀딩스',
}


def get_stock_name(code, api_name=''):
    """KIS API 이름만 사용 — 로컬 테이블 사용 안 함 (잘못된 매핑 방지)"""
    if api_name and api_name.strip():
        return api_name.strip()
    return code  # API 이름 없으면 코드만 표시
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
    "scan_blacklist":[],"scan_vol_min":50,"scan_rsi_min":20,"scan_rsi_max":75,
}
for k,v in DEFAULTS.items():
    if k not in st.session_state: st.session_state[k]=v

# ── 서버 메모리 저장소 (같은 프로세스 내 재시작에도 유지) ──
@st.cache_resource
def get_server_store():
    return {"ck": None, "cp": None, "tg": None, "agreed": False,
            "scan_data": None, "scan_ts": 0, "scan_str": ""}

server_store = get_server_store()

qp = st.query_params

# URL 파라미터 없으면 서버 저장소에서 자동 복원
if not qp.get("ck") and server_store.get("ck"):
    qp["ck"] = server_store["ck"]
    if server_store.get("cp"): qp["cp"] = server_store["cp"]
    if server_store.get("tg"): qp["tg"] = server_store["tg"]
    qp["agreed"] = "1"
    st.rerun()

if qp.get("agreed")=="1" or server_store.get("agreed"):
    st.session_state.agreed = True
if qp.get("no_pin")=="1": st.session_state.use_pin = False
if qp.get("auto_conn")=="1": st.session_state.auto_connect = True
if not st.session_state.use_pin: st.session_state.auth = True

# 텔레그램 복원
if qp.get("tg") and not st.session_state.get("tg_token"):
    try:
        tg_data = json.loads(base64.b64decode(qp.get("tg","")).decode())
        st.session_state["tg_token"] = tg_data.get("t","")
        st.session_state["tg_chat"]  = tg_data.get("c","")
    except: pass

# URL 키 자동 불러오기 + 연결
if (qp.get("ck") and st.session_state.auth
        and not st.session_state.kis_token
        and not st.session_state.get("_auto_loaded")):
    st.session_state["_auto_loaded"] = True
    try:
        d = py_load(qp.get("ck",""), PASSWORD)
        st.session_state.kis_ak  = d.get("ak","")
        st.session_state.kis_sec = d.get("sec","")
        st.session_state.kis_acc = d.get("acc","")
        st.session_state.kis_env = d.get("env","실전투자")
        st.session_state["_do_auto_connect"] = True
        st.rerun()
    except: pass

if qp.get("auth")=="1" and not st.session_state.auth:
    st.session_state.auth = True
    try: del qp["auth"]
    except: pass
    st.rerun()

# HTML 컴포넌트 PIN via URL
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
            st.session_state['_do_auto_connect']=True
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
    if st.session_state.get('_pin_connect_msg'):
        del st.session_state['_pin_connect_msg']
        st.toast("🔗 저장된 키로 자동 연결 중...", icon="⚡")
    do_connect(st.session_state.kis_ak, st.session_state.kis_sec,
               st.session_state.kis_acc, st.session_state.kis_env)
    st.rerun()

# ── 실시간 거래량 순위 스캔 (KOSPI + KOSDAQ) ──
# ── KOSPI/KOSDAQ 주요 종목 코드 (ETF 제외, 시총 상위) ──
KOSPI_CODES = [
    # 시총 상위 (대형주)
    '005930','000660','373220','207940','005380','005490','035420','000270','012330','051910',
    '028260','034730','066570','003670','017670','086790','032830','105560','055550','316140',
    '009150','011070','012450','047050','003490','018880','096770','010950','015760','034220',
    '000810','011200','161390','267260','042660','035720','006400','005387','003550','010140',
    '006360','011780','008770','001040','307950','088350','009830','271560','005940','036570',
    '241560','326030','009540','011790','000720','078935','139480','047810','030200','010130',
    '004020','002790','024110','069960','180640','036460','086280','004990','003090','023590',
    '001450','013360','079550','008560','005850','002380','001520','007070','000100','082640',
    '120110','004170','000880','032640','029780','005290','018260','003580','005870','000040',
    # 중형주 추가
    '010620','020560','003240','001740','047040','000670','023530','004000','002350','006120',
    '016360','000240','017800','004210','005180','003410','007660','010060','014680','033240',
    '005010','006800','001780','002390','004370','009970','011170','011300','012630','013360',
    '014580','017810','018470','019170','020000','021240','023960','024110','025000','025860',
    '026960','028050','028670','029530','031430','032350','033600','034020','034120','034730',
    '036570','037270','039570','040000','041650','042700','043000','044380','045390','046070',
    '047050','047810','048550','049770','051600','052690','053210','054040','055190','056360',
    '057050','058430','059090','060720','062240','064350','066570','067670','068290','070960',
    '072130','073240','075580','077970','078930','079550','080160','082270','084010','085620',
    '086790','089360','090350','091810','092200','093050','095700','096040','097520','099430',
    '100220','101060','101140','102460','103140','104480','105630','108670','111770','112610',
    '115390','116490','117580','119650','120030','121600','122630','123360','128940','130960',
    '131970','133820','138040','138930','140910','141070','145990','148440','149940','152100',
    '155660','161390','170900','175330','176710','178920','180060','181710','185650','192080',
    '194370','196170','198290','199380','200130','204320','207940','210980','214420','214900',
    '215600','217270','218410','222800','225220','228760','232140','233740','235980','241560',
    '242040','243070','247540','248070','251270','253450','255220','259960','261200','263720',
    '267250','267980','271560','272550','276280','278280','283140','284740','286940','287410',
    '289860','290080','294870','298080','302920','305630','306200','307950','309900','315640',
    '316140','320000','321070','323410','326030','329180','332370','334970','336260','336570',
]
KOSDAQ_CODES = [
    '247540','086520','196170','352820','141080','263750','066970','357780','145020','256840',
    '029960','039030','058470','140860','046080','091990','272210','122870','112040','054040',
    '039440','064760','036830','084370','454910','320000','035900','095340','041510','151910',
    '085370','252990','067160','079940','067900','009420','033780','214150','041830','086900',
    '108860','042700','139670','302920','204210','056080','253590','078070','040350','110020',
    '137400','049630','038680','041440','083930','025870','036180','035760','030350','084110',
    '140670','058970','012510','052900','237690','211050','036800','048260','038110','086390',
    '237750','352480','099800','108320','145720','263720','038500','200130','215200','068760',
    '046890','244880','290650','006280','143240','026960','222080','063160','048830','034020',
    '036810','048870','053300','060310','069510','073570','078600','080160','086060','086520',
]

@st.cache_data(ttl=30, show_spinner=False)  # 30초 캐시
def fetch_gist_scan(gist_id):
    """GitHub Gist에서 최신 스캔 결과 즉시 로드"""
    if not gist_id: return None
    try:
        r = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={'Accept':'application/vnd.github.v3+json'},
            timeout=5)
        if r.status_code != 200: return None
        content = r.json().get('files',{}).get('kalpha_scan.json',{}).get('content','')
        return json.loads(content) if content else None
    except: return None

@st.cache_data(ttl=86400, show_spinner=False)  # 하루 캐시
def fetch_stock_name(token, base_url, ak, secret, code):
    """KIS 종목 정보 검색으로 한글 종목명 조회"""
    try:
        headers = {'Content-Type':'application/json','authorization':f'Bearer {token}',
                   'appkey':ak,'appsecret':secret,'tr_id':'CTPF1002R'}
        r = requests.get(f"{base_url}/uapi/domestic-stock/v1/quotations/search-stock-info",
            params={'PDNO':code,'PRDT_TYPE_CD':'300'},
            headers=headers, verify=False, timeout=5)
        o = r.json().get('output',{})
        name = (o.get('prdt_abrv_name') or o.get('prdt_name') or
                o.get('hts_kor_isnm') or '').strip()
        return name if name else code
    except:
        return code

@st.cache_data(ttl=60, show_spinner=False)
def fetch_volume_ranking(token, base_url, ak, secret, mkt_code='J', top_n=100):
    """거래량 순위 API → 실패 시 개별 현재가 조회 fallback"""
    tr_id = 'FHPST01710000'
    headers = {'Content-Type':'application/json','authorization':f'Bearer {token}',
               'appkey':ak,'appsecret':secret,'tr_id':tr_id}
    stocks = []
    try:
        r = requests.get(f"{base_url}/uapi/domestic-stock/v1/ranking/volume",
            params={'FID_COND_MRK_DIV_CODE':mkt_code,'FID_COND_SCR_DIV_CODE':'20171',
                    'FID_INPUT_ISCD':'0000','FID_DIV_CLS_CODE':'0','FID_BLNG_CLS_CODE':'0',
                    'FID_TRGT_CLS_CODE':'111111111','FID_TRGT_EXLS_CLS_CODE':'000000',
                    'FID_INPUT_PRICE_1':'','FID_INPUT_PRICE_2':'',
                    'FID_VOL_CNT':str(top_n),'FID_INPUT_DATE_1':''},
            headers=headers, verify=False, timeout=15)
        raw = r.json().get('output','') or []
        for item in raw:
            # 종목코드: 가능한 모든 필드명 시도
            code = (item.get('mksc_shrn_iscd') or item.get('stck_shrn_iscd') or
                    item.get('iscd') or item.get('code') or '').strip()
            # 종목명: API 이름 + fallback 테이블
            api_name = (item.get('hts_kor_isnm') or item.get('stck_kor_isnm') or
                        item.get('prdt_abrv_name') or item.get('prdt_name') or
                        item.get('kor_isnm') or '').strip()
            name = get_stock_name(code, api_name)
            if name == code and token:  # 이름 없으면 종목 정보 API 시도
                name = fetch_stock_name(token, base_url, ak, secret, code)
            if not code or is_etf(name): continue
            try:
                price   = int(item.get('stck_prpr','0') or 0)
                sign    = item.get('prdy_vrss_sign','3')
                change  = int(item.get('prdy_vrss','0') or 0)
                chg_pct = float(item.get('prdy_ctrt','0') or 0)
                tr_amt  = int(item.get('acml_tr_pbmn','0') or 0) // 100000000
                if price <= 0: continue
                stocks.append({'code':code,'name':name,'price':price,
                    'change':change,'sign':sign,
                    'changePct':-chg_pct if sign in ['4','5'] else chg_pct,
                    'up':sign in ['1','2'],'vol':0,'trAmt':tr_amt,
                    'mkt':'kospi' if mkt_code=='J' else 'kosdaq'})
            except: continue
    except: pass

    # Fallback: 개별 현재가 조회 (J와 Q 둘 다 시도 → 이름 반드시 확보)
    if not stocks:
        codes = KOSPI_CODES if mkt_code == 'J' else KOSDAQ_CODES
        price_headers = {'Content-Type':'application/json','authorization':f'Bearer {token}',
                         'appkey':ak,'appsecret':secret,'tr_id':'FHKST01010100'}
        for code in codes[:top_n]:
            try:
                # J, Q 순으로 시도 (이름 있는 응답 사용)
                found = None
                for mkt_try in (['J','Q'] if mkt_code=='J' else ['Q','J']):
                    rp = requests.get(f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
                        params={'FID_COND_MRKT_DIV_CODE': mkt_try,'FID_INPUT_ISCD':code},
                        headers=price_headers, verify=False, timeout=4)
                    o = rp.json().get('output',{})
                    if not o.get('stck_prpr'): continue
                    # 이름 필드: 여러 가지 시도
                    name_raw = (o.get('hts_kor_isnm') or o.get('prdt_abrv_name') or
                                o.get('prdt_name') or o.get('stck_kor_isnm') or '').strip()
                    if name_raw:  # 이름 있는 응답 발견
                        found = (o, name_raw)
                        break
                    elif not found and o.get('stck_prpr'):
                        found = (o, '')  # 이름은 없지만 가격은 있음

                if not found: continue
                o, name_raw = found
                name = get_stock_name(code, name_raw)
                # 이름이 코드 그대로면 종목 정보 API로 한번 더 시도
                if name == code and token:
                    name = fetch_stock_name(token, base_url, ak, secret, code)
                if is_etf(name): continue
                sign    = o.get('prdy_vrss_sign','3')
                price   = int(o.get('stck_prpr','0') or 0)
                change  = int(o.get('prdy_vrss','0') or 0)
                chg_pct = float(o.get('prdy_ctrt','0') or 0)
                tr_amt  = int(o.get('acml_tr_pbmn','0') or 0) // 100000000
                if price <= 0: continue
                stocks.append({'code':code,'name':name,'price':price,
                    'change':change,'sign':sign,
                    'changePct':-chg_pct if sign in ['4','5'] else chg_pct,
                    'up':sign in ['1','2'],'vol':0,'trAmt':tr_amt,
                    'mkt':'kospi' if mkt_code=='J' else 'kosdaq'})
                time.sleep(0.08)
            except: continue
    return stocks

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
    """
    스윙 매매 핵심 원칙 기반 종목 분류
    ① 실시간스윙  : 기술적 지지 근접 + 모멘텀 + 수급 동반
    ② 급등전야    : 거래량 폭발 + 강한 모멘텀 (단기 추세 전환)
    ③ 내일관심    : 눌림목 구간 + 저변동성 + 수급 대기
    ④ 중소형주    : 소형 모멘텀 + 피보나치 되돌림 근접
    """
    # ── 0. 중복 제거 및 블랙리스트 필터 ──────────────────────────────
    seen = {}
    unique = []
    for s in all_stocks:
        if s['code'] not in seen:
            seen[s['code']] = True
            unique.append(s)
    stocks = [s for s in unique if s['code'] not in blacklist]

    swing, surge, tomorrow, smallmid = [], [], [], []

    for s in stocks:
        pct  = s.get('changePct', 0)   # 등락률 (%)
        tr   = s.get('trAmt', 0)        # 거래대금 (억원)
        price= s.get('price', 0)

        # ── 기본 거래대금 필터 (유동성 확보) ──
        if tr < vol_min or price <= 0:
            continue

        # ── RSI 근사치 계산 (등락률 기반) ──
        # 실제 RSI는 14일 데이터 필요 → 당일 등락률로 근사
        rsi_approx = max(10, min(90, 50 + pct * 2.8))
        if not (rsi_min <= rsi_approx <= rsi_max):
            continue
        s['rsiApprox'] = round(rsi_approx, 1)

        # ── MA 이격도 근사 (당일 등락률 → 5일 누적 추정) ──
        # 양봉 연속 시 MA 근접 하향 → 이격도 100~103 추정
        proximity_ok   = 0.3 <= pct <= 4.5   # MA 근접 상향 돌파 구간
        ma_support_ok  = -0.5 <= pct <= 2.5  # MA 지지 확인 구간

        # ── 거래대금 등급 (수급 강도) ──
        vol_grade = (
            4 if tr >= 2000 else   # 초대형 수급
            3 if tr >= 800  else   # 대형 수급
            2 if tr >= 300  else   # 중형 수급
            1 if tr >= 100  else   # 소형 수급
            0
        )

        # ── 피보나치 61.8% 되돌림 근사 ──
        # 눌림목 구간: -10%~-20% 조정 후 반등 초기
        fib_pullback = -3.0 <= pct <= 0.5 and tr >= 80

        # ── 쌍끌이 수급 근사 (거래대금 급증 + 상승) ──
        dual_buying = pct >= 1.0 and vol_grade >= 2

        # ════════════════════════════════════════════
        # ① 실시간 스윙 (기술적 지지 + 모멘텀 + 수급)
        #    - MA 근접 상향 돌파 (이격도 100~103 추정)
        #    - 거래대금 200억 이상 (기관/외국인 수급 추정)
        #    - 등락률 +0.5%~+4% (과열 아닌 모멘텀)
        # ════════════════════════════════════════════
        if proximity_ok and 0.5 <= pct <= 4.5 and vol_grade >= 2:
            # 점수: 기본 70 + 모멘텀(최대 12) + 수급(최대 16) + RSI보너스(최대 7)
            momentum_sc = min(12, int(pct * 3))
            vol_sc      = min(16, vol_grade * 4)
            rsi_bonus   = 7 if 45 <= rsi_approx <= 65 else 0   # 과매수 아닌 구간
            score = min(97, 70 + momentum_sc + vol_sc + rsi_bonus)
            s2 = dict(s)
            s2.update({'score': score, 'grade': 'S' if score>=87 else 'A' if score>=77 else 'B',
                       'cat': 'swing'})
            swing.append(s2)

        # ════════════════════════════════════════════
        # ② 급등전야 (거래량 폭발 + 강한 모멘텀)
        #    - 등락률 +4%+ (강한 추세 전환 신호)
        #    - 거래대금 100억+ (유의미한 수급 진입)
        #    - 베타 1.0+ 추정: 고변동 종목 선별
        # ════════════════════════════════════════════
        if pct >= 4.0 and vol_grade >= 1:
            # 점수: 기본 65 + 모멘텀(최대 18) + 수급(최대 15)
            momentum_sc = min(18, int(pct * 2))
            vol_sc      = min(15, vol_grade * 4)
            score = min(97, 65 + momentum_sc + vol_sc)
            s2 = dict(s)
            s2.update({'score': score, 'grade': 'S' if score>=87 else 'A' if score>=77 else 'B',
                       'cat': 'surge'})
            surge.append(s2)

        # ════════════════════════════════════════════
        # ③ 내일관심 (눌림목 + 피보나치 되돌림)
        #    - 등락률 -1%~+1.5% (저변동성 횡보/눌림)
        #    - 거래대금 50억+ (수급 대기 추정)
        #    - 피보나치 61.8% 되돌림 구간 근사
        # ════════════════════════════════════════════
        if ma_support_ok and -1.0 <= pct <= 1.5 and tr >= 50:
            # 점수: 기본 60 + 수급(최대 18) + 안정성보너스(최대 10) + 피보나치(최대 5)
            vol_sc  = min(18, vol_grade * 5)
            stab_sc = 10 if abs(pct) <= 0.5 else 5 if abs(pct) <= 1.0 else 0
            fib_sc  = 5 if fib_pullback else 0
            score = min(92, 60 + vol_sc + stab_sc + fib_sc)
            s2 = dict(s)
            s2.update({'score': score, 'grade': 'S' if score>=82 else 'A' if score>=72 else 'B',
                       'cat': 'tomorrow'})
            tomorrow.append(s2)

        # ════════════════════════════════════════════
        # ④ 중소형 모멘텀 (소형 + 피보나치 + 쌍끌이)
        #    - 거래대금 50억~700억 (중소형 범위)
        #    - 등락률 -2%~+4% (과열 제외한 움직임)
        #    - 쌍끌이 수급 또는 피보나치 되돌림
        # ════════════════════════════════════════════
        if 50 <= tr <= 700 and -2.0 <= pct <= 4.0:
            vol_sc   = min(12, tr // 55)
            mom_sc   = min(10, int(abs(pct) * 3))
            dual_sc  = 8 if dual_buying else 0
            fib_sc   = 5 if fib_pullback else 0
            score = min(92, 62 + vol_sc + mom_sc + dual_sc + fib_sc)
            s2 = dict(s)
            s2.update({'score': score, 'grade': 'S' if score>=82 else 'A' if score>=72 else 'B',
                       'cat': 'smallmid'})
            smallmid.append(s2)

    # ── 점수순 정렬 + 카테고리 내 중복 제거 ──────────────────────────
    def top(lst, n):
        sorted_lst = sorted(lst, key=lambda x: x.get('score', 0), reverse=True)
        seen_codes = set()
        result = []
        for s in sorted_lst:
            if s['code'] not in seen_codes:
                seen_codes.add(s['code'])
                result.append(s)
            if len(result) >= n:
                break
        return result

    return {
        'swing':    top(swing, 10),
        'surge':    top(surge, 10),
        'tomorrow': top(tomorrow, 10),
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
                # PIN 정확 → 저장된 키 자동 불러오기 + 자동 연결
                if qp.get('ck'):
                    try:
                        d=py_load(qp.get('ck',''), PASSWORD)
                        st.session_state.kis_ak  = d.get('ak','')
                        st.session_state.kis_sec = d.get('sec','')
                        st.session_state.kis_acc = d.get('acc','')
                        st.session_state.kis_env = d.get('env','실전투자')
                        st.session_state['_do_auto_connect'] = True
                        server_store['ck'] = qp.get('ck','')
                        server_store['cp'] = qp.get('cp','')
                        server_store['agreed'] = True
                        st.session_state['_pin_connect_msg'] = True
                    except: pass
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

# ════ 3. 자동 새로고침 (KIS 연결 시에만) ════
if st.session_state.auth and st.session_state.kis_token:
    iv_min = st.session_state.get('tg_interval_min', 10)
    # 설정된 간격마다 자동 재실행 (스캔 + 텔레그램)
    _refresh_count = st_autorefresh(
        interval=iv_min * 60 * 1000,  # ms
        limit=None,
        key="auto_scan_refresh"
    )

# ════ 4. 메인 패널 ════
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

    # 저장 상태 표시 (자동 저장됨)
    if saved_ck:
        st.markdown("""<div style="font-family:'Share Tech Mono',monospace;font-size:11px;
          color:#00ff88;padding:6px 10px;background:rgba(0,255,136,0.08);
          border:1px solid rgba(0,255,136,0.2);border-radius:6px;margin-bottom:4px">
          ✅ API 키 저장됨 — PIN 입력 시 자동 연결</div>""", unsafe_allow_html=True)
    else:
        st.markdown("""<div style="font-family:'Share Tech Mono',monospace;font-size:11px;
          color:#ffc800;padding:6px 10px;background:rgba(255,200,0,0.08);
          border:1px solid rgba(255,200,0,0.2);border-radius:6px;margin-bottom:4px">
          ⚡ KIS API 연결 성공 시 자동 저장됩니다</div>""", unsafe_allow_html=True)

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
                    if ok:
                        ck_v=py_save(ak,sec,acc,env_label,PASSWORD)
                        cp_v=base64.b64encode((PASSWORD+":kalpha").encode()).decode()
                        qp['ck']=ck_v; qp['cp']=cp_v; qp['agreed']='1'
                        # 서버 저장소에 저장 (앱 재시작 시 자동 복원)
                        server_store['ck'] = ck_v
                        server_store['cp'] = cp_v
                        server_store['agreed'] = True
                        components.html(f"""<script>
try{{localStorage.setItem('ka_ck_v9',{json.dumps(ck_v)});
     localStorage.setItem('ka_cp_v9',{json.dumps(cp_v)});}}catch(e){{}}
</script>""", height=0, scrolling=False)
                        st.success("✅ 연결 성공! 자동 저장됨")
                        st.rerun()
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
                            st.session_state['tg_token']=tg_token
                            st.session_state['tg_chat']=tg_chat
                            tg_enc=base64.b64encode(json.dumps({'t':tg_token,'c':tg_chat}).encode()).decode()
                            qp['tg']=tg_enc
                            server_store['tg'] = tg_enc  # 서버 저장소
                            components.html(f"<script>try{{localStorage.setItem('ka_tg_v1',{json.dumps(tg_enc)});}}catch(e){{}}</script>",height=0,scrolling=False)
                            st.success("✅ 전송 성공! 텔레그램 자동 저장됨")
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

# ════ 5. 실시간 스캔 & 데이터 준비 ════
prices_json="{}"; balance_json="{}"; price_ts=""
scan_json="{}"; scan_count=0

if st.session_state.kis_token:
    iv_min = st.session_state.get('tg_interval_min', 10)
    GIST_ID = os.environ.get('GIST_ID','')

    ca, cb = st.columns([5,1])
    with cb:
        if st.button("↻", key="btn_ref", help="즉시 갱신"):
            server_store['scan_ts'] = 0
            fetch_gist_scan.clear()
            st.rerun()
    with ca:
        st.markdown(f'<div style="font-family:monospace;font-size:12px;color:#4a5568;padding:2px 0">'
                    f'⟳ {iv_min}분 자동갱신 · <span style="color:#00ff88">{kst_strftime("%H:%M:%S")}</span></div>',
                    unsafe_allow_html=True)

    # ── 1순위: GitHub Gist (즉시, 0초) ──
    gist_data = fetch_gist_scan(GIST_ID) if GIST_ID else None

    if gist_data:
        # Gist 데이터로 즉시 표시
        scan_result = gist_data
        scan_json   = json.dumps(scan_result, ensure_ascii=False)
        scan_count  = gist_data.get('total', 0)
        price_ts    = gist_data.get('ts', kst_strftime("%H:%M:%S"))
        prices_json = "{}"
        balance_json = "{}"
        kospi_n  = gist_data.get('kospi_n', 0)
        kosdaq_n = gist_data.get('kosdaq_n', 0)
        age_sec  = int(time.time() - gist_data.get('updated_at', time.time()))
        st.markdown(f'<div style="font-family:monospace;font-size:12px;color:#00d4ff;padding:2px 0">'
                    f'⚡ Gist 즉시 로드 · KOSPI {kospi_n}+KOSDAQ {kosdaq_n}종목 · '
                    f'{age_sec//60}분 {age_sec%60}초 전 스캔</div>', unsafe_allow_html=True)

    else:
        # ── 2순위: 직접 KIS 스캔 (Gist 없을 때) ──
        cache_stale = (time.time() - server_store.get('scan_ts', 0)) > iv_min*60
        cached = server_store.get('scan_data')

        if cached and not cache_stale:
            kospi_stocks  = cached['kospi']
            kosdaq_stocks = cached['kosdaq']
            all_stocks    = cached['all']
            balance       = cached['balance']
            price_ts      = server_store['scan_str']
        else:
            with st.spinner("📡 KIS 직접 스캔 중..."):
                kospi_stocks = fetch_volume_ranking(
                    st.session_state.kis_token, st.session_state.kis_base_url,
                    st.session_state.kis_ak, st.session_state.kis_sec, 'J', 300)
                kosdaq_stocks = fetch_volume_ranking(
                    st.session_state.kis_token, st.session_state.kis_base_url,
                    st.session_state.kis_ak, st.session_state.kis_sec, 'Q', 100)
                balance = fetch_balance(
                    st.session_state.kis_token, st.session_state.kis_base_url,
                    st.session_state.kis_ak, st.session_state.kis_sec, st.session_state.kis_acc)
            all_stocks = kospi_stocks + kosdaq_stocks
            price_ts   = kst_strftime("%H:%M:%S")
            server_store['scan_data'] = {'kospi':kospi_stocks,'kosdaq':kosdaq_stocks,
                                          'all':all_stocks,'balance':balance}
            server_store['scan_ts']  = time.time()
            server_store['scan_str'] = price_ts

        cats = categorize_stocks(all_stocks, st.session_state.scan_blacklist,
                                  st.session_state.scan_vol_min,
                                  st.session_state.scan_rsi_min, st.session_state.scan_rsi_max)
        scan_count  = len(all_stocks)
        scan_result = {
            'swing':    [build_card(s,'swing')    for s in cats['swing']],
            'surge':    [build_card(s,'surge')    for s in cats['surge']],
            'tomorrow': [build_card(s,'tomorrow') for s in cats['tomorrow']],
            'smallmid': [build_card(s,'smallmid') for s in cats['smallmid']],
            'ts': price_ts, 'total': scan_count,
        }
        scan_json    = json.dumps(scan_result, ensure_ascii=False)
        prices       = {s['code']:{'price':s['price'],'change':s.get('change',0),
                                    'changePct':s['changePct'],'up':s['up']} for s in all_stocks}
        prices_json  = json.dumps(prices)
        balance_json = json.dumps(balance) if balance and not balance.get('error') else "{}"

        st.markdown(f'<div style="font-family:monospace;font-size:12px;color:#00d4ff;padding:2px 0">'
                    f'📊 KOSPI {len(kospi_stocks)}+KOSDAQ {len(kosdaq_stocks)}종목 · {price_ts}</div>',
                    unsafe_allow_html=True)

        # 텔레그램
        tg_token = st.session_state.get('tg_token','')
        tg_chat  = st.session_state.get('tg_chat','')
        if tg_token and tg_chat and all_stocks:
            bucket = int(time.time() // (iv_min*60))
            if bucket != st.session_state.get('_tg_bucket',-1):
                st.session_state['_tg_bucket'] = bucket
                now_ts = kst_strftime('%H:%M:%S')
                is_mkt = 9 <= int(kst_strftime('%H')) <= 15
                mkt_label = '🟢장중' if is_mkt else '🔴장마감'

                def fmt_s(s, cat):
                    pct=s.get('changePct',0); sign='+' if pct>=0 else ''
                    card=build_card(s,cat); icon='🔴' if s.get('grade')=='S' else '🟡'
                    return (f"{icon} <b>{s['name']}</b> ({s['code']})\n"
                            f"   💰 {s['price']:,}원 {sign}{pct:.2f}% | {s.get('trAmt',0):,}억\n"
                            f"   📈 매입:{card['buy']} | 손절:{card['stop']} | RR {card['rr']}")

                lines = [f"📡 <b>K-ALPHA {iv_min}분 스캔</b> [{now_ts}] {mkt_label}\n"
                         f"KOSPI {len(kospi_stocks)}+KOSDAQ {len(kosdaq_stocks)}종목\n━━━━━━━━━━━━━━━━"]

                swing_list    = cats.get('swing', [])[:10]
                surge_list    = cats.get('surge', [])[:10]
                tomorrow_list = cats.get('tomorrow', [])[:10]
                smallmid_list = cats.get('smallmid', [])[:10]

                if swing_list:
                    lines.append(f"🔥 <b>[실시간스윙 TOP{len(swing_list)}]</b>")
                    for s in swing_list: lines.append(fmt_s(s,'swing'))
                if surge_list:
                    lines.append(f"\n⚡ <b>[급등전야 TOP{len(surge_list)}]</b>")
                    for s in surge_list: lines.append(fmt_s(s,'surge'))
                if tomorrow_list:
                    lines.append(f"\n🔭 <b>[내일관심 TOP{len(tomorrow_list)}]</b>")
                    for s in tomorrow_list: lines.append(fmt_s(s,'tomorrow'))
                if smallmid_list:
                    lines.append(f"\n⬟ <b>[중소형주 TOP{len(smallmid_list)}]</b>")
                    for s in smallmid_list: lines.append(fmt_s(s,'smallmid'))
                if not any([swing_list, surge_list, tomorrow_list, smallmid_list]):
                    fallback = sorted(all_stocks, key=lambda x:x.get('trAmt',0), reverse=True)[:10]
                    lines.append("📊 <b>[거래대금 상위 TOP10]</b>")
                    for s in fallback: lines.append(fmt_s(s,'swing'))

                lines.append(f"━━━━━━━━━━━━━━━━\n📊 {scan_count}종목 완료")
                try: requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage",
                        json={"chat_id":tg_chat,"text":"\n\n".join(lines),"parse_mode":"HTML"},timeout=10)
                except: pass

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
📊 KOSPI {len(kospi_stocks)}종목 + KOSDAQ {len(kosdaq_stocks)}종목 스캔 완료 · <span style="color:#00ff88">{kst_strftime('%H:%M:%S')}</span><br>
🔍 실시간스윙 {len(cats['swing'])}개 · 급등전야 {len(cats['surge'])}개 · 내일관심 {len(cats['tomorrow'])}개 · 중소형주 {len(cats['smallmid'])}개
</div>""", unsafe_allow_html=True)

    # ── 텔레그램 자동 알림 ──
    tg_token = st.session_state.get('tg_token','')
    tg_chat  = st.session_state.get('tg_chat','')
    if tg_token and tg_chat and all_stocks:
        bucket = int(time.time() // (iv_min * 60))
        if bucket != st.session_state.get('_tg_bucket', -1):
            st.session_state['_tg_bucket'] = bucket

            now_ts    = kst_strftime('%H:%M:%S')
            is_market = 9 <= int(kst_strftime('%H')) <= 15
            mkt_label = "🟢 장중" if is_market else "🔴 장 마감"

            def fmt_stock(s, cat):
                pct = s.get('changePct', 0); sign = '+' if pct >= 0 else ''
                card = build_card(s, cat)
                icon = '🔴' if s.get('grade') == 'S' else '🟡'
                return (f"{icon} <b>{s['name']}</b> ({s['code']})\n"
                        f"   💰 현재가: <b>{s['price']:,}원</b> {sign}{pct:.2f}% | 거래대금 {s.get('trAmt',0):,}억\n"
                        f"   📈 매입가: {card['buy']}원 | 손절: {card['stop']}원 | RR {card['rr']}")

            swing_list    = cats.get('swing', [])[:10]
            surge_list    = cats.get('surge', [])[:10]
            tomorrow_list = cats.get('tomorrow', [])[:10]
            smallmid_list = cats.get('smallmid', [])[:10]

            lines = [f"📡 <b>K-ALPHA {iv_min}분 자동 스캔</b> [{now_ts}] {mkt_label}\n"
                     f"KOSPI {len(kospi_stocks)}종목 + KOSDAQ {len(kosdaq_stocks)}종목\n"
                     "━━━━━━━━━━━━━━━━"]

            if swing_list:
                lines.append(f"🔥 <b>[실시간스윙 TOP{len(swing_list)}]</b>")
                for s in swing_list: lines.append(fmt_stock(s, 'swing'))
            if surge_list:
                lines.append(f"\n⚡ <b>[급등전야 TOP{len(surge_list)}]</b>")
                for s in surge_list: lines.append(fmt_stock(s, 'surge'))
            if tomorrow_list:
                lines.append(f"\n🔭 <b>[내일관심 TOP{len(tomorrow_list)}]</b>")
                for s in tomorrow_list: lines.append(fmt_stock(s, 'tomorrow'))
            if smallmid_list:
                lines.append(f"\n⬟ <b>[중소형주 TOP{len(smallmid_list)}]</b>")
                for s in smallmid_list: lines.append(fmt_stock(s, 'smallmid'))
            if not any([swing_list, surge_list, tomorrow_list, smallmid_list]):
                fallback = sorted(all_stocks, key=lambda x: x.get('trAmt',0), reverse=True)[:10]
                lines.append("📊 <b>[거래대금 상위 TOP10]</b>")
                for s in fallback: lines.append(fmt_stock(s, 'swing'))

            lines.append(f"━━━━━━━━━━━━━━━━\n📊 {scan_count}종목 스캔 완료 · 다음 알림 {iv_min}분 후")

            try:
                msg_body = {"text": "\n\n".join(lines), "parse_mode": "HTML"}
                resp = requests.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": tg_chat, **msg_body}, timeout=10)
                requests.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": "-1003985375563", **msg_body}, timeout=10)
                if resp.json().get('ok'):
                    st.toast(f"📱 텔레그램 전송 완료 ({now_ts})", icon="✅")
            except Exception as e:
                st.caption(f"텔레그램 오류: {e}")

# ════ 6. HTML 터미널 ════
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
window.__SCAN_VOL_MIN__ = {st.session_state.get('scan_vol_min',50)};
window.__SCAN_RSI_MIN__ = {st.session_state.get('scan_rsi_min',20)};
window.__SCAN_RSI_MAX__ = {st.session_state.get('scan_rsi_max',75)};
</script>"""
html=html.replace("</head>",inject+"\n</head>")
components.html(html,height=5000,scrolling=False)
