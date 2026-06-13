"""
K-ALPHA 백그라운드 스캔 워커
GitHub Actions 실행 → 결과를 GitHub Gist에 저장
→ Streamlit 앱이 열리면 Gist에서 즉시 읽기 (0초)

장중 자동 스캔: 평일(공휴일 제외) 08:00~15:30 KST
장외/주말/공휴일: 수동 실행(MANUAL_INTERVAL)만 허용
"""
import os, json, time, datetime, requests, urllib3
urllib3.disable_warnings()

KIS_AK   = os.environ.get('KIS_AK','').strip()
KIS_SEC  = os.environ.get('KIS_SEC','').strip()
KIS_ACC  = os.environ.get('KIS_ACC','').strip()
KIS_ENV  = os.environ.get('KIS_ENV','real').strip()
TG_TOKEN = os.environ.get('TG_TOKEN','').strip()

# 개인방 채팅ID + 간격
TG_CHAT        = os.environ.get('TG_CHAT','').strip()
_iv_p_raw      = os.environ.get('MANUAL_INTERVAL','').strip() or os.environ.get('INTERVAL','10').strip()
try:    TG_INTERVAL = max(10, min(240, int(_iv_p_raw)))
except: TG_INTERVAL = 10

# 그룹방 채팅ID + 간격 (별도 환경변수, 없으면 비활성)
TG_GROUP_CHAT  = os.environ.get('TG_GROUP_CHAT','').strip()
_iv_g_raw      = os.environ.get('TG_GROUP_INTERVAL','').strip()
try:    TG_GROUP_INTERVAL = max(10, min(240, int(_iv_g_raw))) if _iv_g_raw else 0
except: TG_GROUP_INTERVAL = 0   # 0 = 그룹방 미설정

# 그룹방 2
TG_GROUP2_CHAT = os.environ.get('TG_GROUP2_CHAT','').strip()
_iv_g2_raw     = os.environ.get('TG_GROUP2_INTERVAL','').strip()
try:    TG_GROUP2_INTERVAL = max(10, min(240, int(_iv_g2_raw))) if _iv_g2_raw else 0
except: TG_GROUP2_INTERVAL = 0

# 그룹방 3
TG_GROUP3_CHAT = os.environ.get('TG_GROUP3_CHAT','').strip()
_iv_g3_raw     = os.environ.get('TG_GROUP3_INTERVAL','').strip()
try:    TG_GROUP3_INTERVAL = max(10, min(240, int(_iv_g3_raw))) if _iv_g3_raw else 0
except: TG_GROUP3_INTERVAL = 0

GIST_ID  = os.environ.get('GIST_ID','').strip()
GH_TOKEN = os.environ.get('GH_TOKEN','').strip()

# 하위 호환: INTERVAL 변수는 개인방 기준
INTERVAL = TG_INTERVAL

BASE_URL = ("https://openapi.koreainvestment.com:9443" if KIS_ENV=='real'
            else "https://openapivts.koreainvestment.com:29443")

ETF_KW = ['ETF','KODEX','TIGER','KBSTAR','ARIRANG','HANARO','KOSEF','ACE ',
          '인버스','레버리지','선물','리츠','REIT','스팩','SPAC']

def is_etf(n): return any(k in n.upper() for k in ETF_KW)

# 종목코드 → 종목명 매핑 (KIS API 이름 없을 때 fallback)
_STOCK_NAMES = {
    '005930':'삼성전자','000660':'SK하이닉스','373220':'LG에너지솔루션',
    '207940':'삼성바이오로직스','005380':'현대차','005490':'POSCO홀딩스',
    '035420':'NAVER','000270':'기아','051910':'LG화학','028260':'삼성물산',
    '034730':'SK','066570':'LG전자','017670':'SK텔레콤','032830':'삼성생명',
    '105560':'KB금융','055550':'신한지주','009150':'삼성전기','011070':'LG이노텍',
    '012450':'한화에어로스페이스','035720':'카카오','006400':'삼성SDI','003550':'LG',
    '247540':'에코프로비엠','086520':'에코프로','352820':'하이브','058470':'리노공업',
    '140860':'파크시스템스','039440':'에스티아이','084370':'유진테크','064760':'티씨케이',
    '036830':'솔브레인홀딩스','015760':'한국전력','001450':'현대해상','000810':'삼성화재',
    '005940':'NH투자증권','086790':'하나금융지주','316140':'우리금융지주','139480':'이마트',
    '271560':'오리온','004020':'현대제철','011200':'HMM','161390':'한국타이어앤테크놀로지',
    '009830':'한화솔루션','003490':'대한항공','018880':'한온시스템','096770':'SK이노베이션',
    '010950':'S-Oil','015760':'한국전력','034220':'LG디스플레이','003670':'포스코퓨처엠',
    '047050':'포스코인터내셔널','006360':'GS건설','011780':'금호석유','008770':'호텔신라',
    '001040':'CJ','307950':'현대오토에버','088350':'한화생명','241560':'두산밥캣',
    '326030':'SK바이오팜','009540':'HD한국조선해양','011790':'SKC','000720':'현대건설',
    '078935':'GS에너지','030200':'KT','010130':'고려아연','002790':'아모레퍼시픽',
    '024110':'기업은행','069960':'현대백화점','180640':'한진칼','036460':'한국가스공사',
    '086280':'현대글로비스','004990':'롯데지주','003090':'대웅제약','023590':'우리카드',
    '001520':'동양','007070':'GS리테일','000100':'유한양행','082640':'동원산업',
}

def kst_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)

def _lbl(m):
    """분 -> '10분', '1시간', '1시간30분' 형태 레이블"""
    if m < 60:    return f"{m}분"
    if m % 60==0: return f"{m//60}시간"
    return f"{m//60}시간{m%60}분"

# ── 한국 공휴일 (MMDD 형식) ────────────────────────────────────────
KR_HOLIDAYS = {
    # 2025
    '20250101','20250127','20250128','20250129','20250130',
    '20250301','20250505','20250506','20250606','20250815',
    '20251003','20251004','20251005','20251006','20251007',
    '20251009','20251225',
    # 2026
    '20260101','20260216','20260217','20260218','20260219',
    '20260301','20260505','20260525','20260606','20260815',
    '20260924','20260925','20260926','20260927',
    '20261003','20261009','20261225',
    # 2027
    '20270101','20270205','20270206','20270207','20270208',
    '20270301','20270505','20270513','20270606','20270816',
    '20271014','20271015','20271016','20271017',
    '20271011','20271225',
}

def is_korean_holiday(dt=None):
    """주어진 날짜(또는 현재 KST)가 한국 공휴일이면 True"""
    if dt is None: dt = kst_now()
    return dt.strftime('%Y%m%d') in KR_HOLIDAYS

def is_market_open(dt=None):
    """
    한국 주식시장 장중 여부:
    - 평일(월~금), 공휴일 아님
    - 08:00~15:30 KST (08:00부터 프리마켓/개장 준비 포함)
    """
    if dt is None: dt = kst_now()
    if dt.weekday() >= 5: return False          # 주말
    if is_korean_holiday(dt): return False       # 공휴일
    total = dt.hour * 60 + dt.minute
    return 480 <= total <= 930                   # 08:00(480) ~ 15:30(930)

def should_scan():
    """
    자동 스캔 여부:
    - 장중(08:00~15:30 KST, 평일, 비공휴일)이면 True
    - 저녁 20:00 KST 1회 종합분석 허용
    - workflow_dispatch 수동 실행이면 무조건 True
    """
    if os.environ.get('GITHUB_EVENT_NAME','') == 'workflow_dispatch': return True
    if os.environ.get('MANUAL_INTERVAL','').strip(): return True
    t = kst_now()
    if t.weekday() >= 5 or is_korean_holiday(t): return False
    total = t.hour * 60 + t.minute
    return (480 <= total <= 930) or (1200 <= total <= 1215)

def should_send_tg(interval_min):
    """
    interval_min 간격으로 텔레그램을 보내야 하면 True.
    cron은 10분마다 실행됨 → interval_min이 10의 배수여야 정확히 동작.
    (현재분 % interval_min) < 4 : cron 지연 허용
    """
    if os.environ.get('MANUAL_INTERVAL','').strip(): return True
    t     = kst_now()
    total = t.hour * 60 + t.minute
    return (total % interval_min) < 4

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_token():
    try:
        r = requests.post(f"{BASE_URL}/oauth2/tokenP",
            json={"grant_type":"client_credentials","appkey":KIS_AK,"appsecret":KIS_SEC},
            verify=False, timeout=15)
        if r.status_code != 200:
            print(f"❌ KIS 토큰 오류: HTTP {r.status_code} — {r.text[:100]}")
            return ''
        data = r.json()
        token = data.get('access_token','')
        if not token:
            print(f"❌ KIS 토큰 없음: {data}")
        return token
    except Exception as e:
        print(f"❌ KIS 토큰 요청 실패: {e}")
        return ''

def fetch_ranking(token, mkt, top_n):
    h = {'Content-Type':'application/json','authorization':f'Bearer {token}',
         'appkey':KIS_AK,'appsecret':KIS_SEC,'tr_id':'FHPST01710000'}
    stocks = []
    try:
        r = requests.get(f"{BASE_URL}/uapi/domestic-stock/v1/ranking/volume",
            params={'FID_COND_MRK_DIV_CODE':mkt,'FID_COND_SCR_DIV_CODE':'20171',
                    'FID_INPUT_ISCD':'0000','FID_DIV_CLS_CODE':'0','FID_BLNG_CLS_CODE':'0',
                    'FID_TRGT_CLS_CODE':'111111111','FID_TRGT_EXLS_CLS_CODE':'000000',
                    'FID_INPUT_PRICE_1':'','FID_INPUT_PRICE_2':'',
                    'FID_VOL_CNT':str(top_n),'FID_INPUT_DATE_1':''},
            headers=h, verify=False, timeout=15)
        for item in (r.json().get('output','') or []):
            code = (item.get('mksc_shrn_iscd') or item.get('stck_shrn_iscd') or '').strip()
            name = (item.get('hts_kor_isnm') or item.get('prdt_abrv_name') or '').strip()
            if not code or not name or is_etf(name): continue
            try:
                price   = int(item.get('stck_prpr','0') or 0)
                sign    = item.get('prdy_vrss_sign','3')
                chg_pct = float(item.get('prdy_ctrt','0') or 0)
                tr_amt  = int(item.get('acml_tr_pbmn','0') or 0) // 100000000
                if price <= 0: continue
                stocks.append({'code':code,'name':name,'price':price,
                    'changePct':-chg_pct if sign in ['4','5'] else chg_pct,
                    'trAmt':tr_amt,'up':sign in ['1','2'],
                    'mkt':'kospi' if mkt=='J' else 'kosdaq'})
            except: continue
    except Exception as e:
        print(f"랭킹 API 오류({mkt}): {e}")
    return stocks

def build_fundamental_reasons(s, cat):
    """
    기본적 분석(기업 내부 요인) + 외부요인분석(거시경제·산업 환경) 사유 생성
    실시간 거래 데이터 기반 추정값
    """
    pct   = s.get('changePct', 0)
    tr    = s.get('trAmt', 0)
    price = s.get('price', 0)
    mkt   = s.get('mkt', 'kospi')
    sign  = '+' if pct >= 0 else ''

    # ── 기술적 분석 (기존) ──
    tech_reasons = [
        {'icon':'◈','cat':'green',
         'text':f"거래대금 {tr:,}억 · 거래량순위 상위 종목"},
        {'icon':'◉','cat':'',
         'text':f"등락률 {sign}{pct:.2f}% · RSI 추정 {round(50+pct*2.5)}"},
        {'icon':'▲','cat':'orange',
         'text':f"매입가 {int(price*0.995):,}원 → 목표 {int(price*1.10):,}원 · 손절 {int(price*0.97):,}원"},
    ]

    # ── 기본적 분석 — 기업 내부 요인 ──
    fund_parts = []
    if tr >= 2000:
        fund_parts.append("기관·외국인 대규모 순매수 추정 (거래대금 2,000억+)")
    elif tr >= 800:
        fund_parts.append("기관 매수세 유입 추정 (거래대금 800억+)")
    elif tr >= 300:
        fund_parts.append("외국인·기관 중형 수급 진입 추정")
    else:
        fund_parts.append("개인 중심 수급 · 단기 모멘텀 주도")

    if pct >= 8:
        fund_parts.append("실적 서프라이즈 또는 긍정 공시 가능성")
    elif pct >= 4:
        fund_parts.append("단기 실적 개선·사업 확장 뉴스 반응")
    elif pct >= 1:
        fund_parts.append("점진적 실적 개선 기대 · MA 상향 돌파 시도")
    elif pct >= -1:
        fund_parts.append("횡보 구간 · 저점 매집 가능성")
    else:
        fund_parts.append("단기 조정 · 피보나치 지지선 반등 대기")

    if mkt == 'kospi':
        fund_parts.append("KOSPI 대형주 · 안정적 실적 기반")
    else:
        fund_parts.append("KOSDAQ 중소형주 · 고성장 섹터 · 변동성 주의")

    # ── 외부요인 분석 — 거시경제·산업 환경 ──
    macro_parts = []
    now_h = kst_now().hour
    if 8 <= now_h < 9:
        macro_parts.append("프리마켓 구간 · 미국 선물·뉴스 반영 초기")
    elif 9 <= now_h < 11:
        macro_parts.append("오전 장 · 외국인·기관 방향성 확인 구간")
    elif 11 <= now_h < 13:
        macro_parts.append("점심 전후 · 유동성 감소 · 단기 변동성 주의")
    else:
        macro_parts.append("오후 장 · 프로그램 매매·수급 정리 구간")

    if tr >= 1000:
        macro_parts.append("시장 전체 활성화 · 외국인 관심 업종")
    elif tr >= 300:
        macro_parts.append("업종 테마 수급 집중 · 정책·뉴스 모멘텀")
    else:
        macro_parts.append("개별 재료 중심 움직임")

    if pct >= 3:
        macro_parts.append("금리·환율 우호 또는 섹터 호재 반응")
    elif pct <= -3:
        macro_parts.append("글로벌 리스크오프 또는 섹터 악재 가능성")
    else:
        macro_parts.append("관망세 · 미국 FOMC·환율 방향성 주시")

    return tech_reasons + [
        {'icon':'🏢','cat':'blue',
         'text':'[기본적 분석] ' + ' · '.join(fund_parts)},
        {'icon':'🌐','cat':'purple',
         'text':'[외부요인] ' + ' · '.join(macro_parts)},
    ]

def send_telegram_long(token, chat_id, text):
    """4096자 초과 시 분할 전송"""
    MAX = 4000
    if len(text) <= MAX:
        return send_telegram(text, chat_id)
    # 종목 구분자로 분할
    parts = []
    current = ""
    for chunk in text.split('\n\n'):
        if len(current) + len(chunk) + 2 > MAX:
            if current:
                parts.append(current.strip())
            current = chunk
        else:
            current = (current + '\n\n' + chunk) if current else chunk
    if current:
        parts.append(current.strip())
    ok = True
    for i, part in enumerate(parts):
        prefix = f"[{i+1}/{len(parts)}] " if len(parts) > 1 else ""
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": prefix + part, "parse_mode": "HTML"},
            timeout=15)
        if not r.json().get('ok'):
            ok = False
            print(f"❌ 분할 전송 실패 ({i+1}/{len(parts)}): {r.text[:100]}")
        time.sleep(0.5)
    return ok
def categorize(stocks):
    """app.py categorize_stocks()와 동일한 로직"""
    seen = set()
    unique = []
    for s in stocks:
        if s['code'] not in seen:
            seen.add(s['code'])
            unique.append(s)

    swing, surge, tomorrow_list, smallmid = [], [], [], []

    for s in unique:
        pct   = s.get('changePct', 0)
        tr    = s.get('trAmt', 0)
        price = s.get('price', 0)
        if tr < 30 or price <= 0:
            continue
        rsi_approx   = max(10, min(90, 50 + pct * 2.8))
        proximity_ok = 0.3 <= pct <= 4.5
        fib_pullback = -3.0 <= pct <= 0.5 and tr >= 80
        vol_grade = (4 if tr >= 2000 else 3 if tr >= 800 else
                     2 if tr >= 300  else 1 if tr >= 100 else 0)
        dual_buying = pct >= 1.0 and vol_grade >= 2

        # 실시간 스윙
        if proximity_ok and 0.3 <= pct <= 6.0 and vol_grade >= 1:
            sc = min(97, 70 + min(12,int(pct*3)) + min(16,vol_grade*4) + (7 if 45<=rsi_approx<=65 else 0))
            s2 = dict(s); s2.update({'score':sc,'grade':'S' if sc>=87 else 'A' if sc>=77 else 'B','cat':'swing','rsiApprox':round(rsi_approx,1)})
            swing.append(s2)

        # 급등전야
        if pct >= 4.0 and vol_grade >= 1:
            sc = min(97, 65 + min(18,int(pct*2)) + min(15,vol_grade*4))
            s2 = dict(s); s2.update({'score':sc,'grade':'S' if sc>=87 else 'A' if sc>=77 else 'B','cat':'surge','rsiApprox':round(rsi_approx,1)})
            surge.append(s2)

        # 내일관심
        if -2.0 <= pct <= 2.5 and tr >= 50:
            sc = min(92, 60 + min(18,vol_grade*5) + (10 if abs(pct)<=0.5 else 5 if abs(pct)<=1.0 else 0) + (5 if fib_pullback else 0))
            s2 = dict(s); s2.update({'score':sc,'grade':'S' if sc>=82 else 'A' if sc>=72 else 'B','cat':'tomorrow','rsiApprox':round(rsi_approx,1)})
            tomorrow_list.append(s2)

        # 중소형주
        if 50 <= tr <= 700 and -2.0 <= pct <= 4.0:
            if not (s.get('mkt','kospi')=='kospi' and (price>50000 or tr>400)):
                sc = min(92, 62 + min(12,tr//55) + min(10,int(abs(pct)*3)) + (8 if dual_buying else 0) + (5 if fib_pullback else 0))
                s2 = dict(s); s2.update({'score':sc,'grade':'S' if sc>=82 else 'A' if sc>=72 else 'B','cat':'smallmid','rsiApprox':round(rsi_approx,1)})
                smallmid.append(s2)

    def top(lst, n):
        seen2=set(); res=[]
        for x in sorted(lst, key=lambda x:x.get('score',0), reverse=True):
            if x['code'] not in seen2: seen2.add(x['code']); res.append(x)
            if len(res)>=n: break
        return res
    return {'swing':top(swing,50),'surge':top(surge,50),'tomorrow':top(tomorrow_list,50),'smallmid':top(smallmid,50)}

def build_card(s, cat):
    p = s['price']
    buy=int(p*0.995); stop=int(p*0.97); tgt=int(p*1.10)
    rr=round((tgt-p)/(p-stop+1),1)
    pct=s.get('changePct',0); sign='+' if pct>=0 else ''
    return {
        'name':s['name'],'code':s['code'],
        'score':s.get('score',70),'grade':s.get('grade','B'),
        'price':f"{p:,}",'change':f"{sign}{pct:.2f}%",'up':s['up'],
        'buy':f"{buy:,}",'target':f"{tgt:,}",'stop':f"{stop:,}",
        'rr':str(rr),'vol':s.get('trAmt',0),'mkt':s.get('mkt','kospi'),
        'rsiApprox':round(50+pct*2.5,1),'cat':cat,
        'reasons': build_fundamental_reasons(s, cat),
        'inds':[
            {'label':s.get('mkt','KOSPI').upper(),'cat':'green'},
            {'label':f"RR {rr}",'cat':''},
            {'label':f"거래대금 {s.get('trAmt',0):,}억",'cat':'orange'},
        ],
        'chart3m':[],'chartD':[]
    }

def load_gist_config():
    """앱에서 저장한 kalpha_config.json을 Gist에서 읽어 설정 적용"""
    if not GIST_ID or not GH_TOKEN:
        return {}
    try:
        r = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={'Authorization':f'token {GH_TOKEN}','Accept':'application/vnd.github.v3+json'},
            timeout=10)
        content = r.json().get('files',{}).get('kalpha_config.json',{}).get('content','')
        return json.loads(content) if content else {}
    except Exception as e:
        print(f"⚠ Gist 설정 로드 실패: {e}"); return {}

def save_to_gist(data):
    """결과를 GitHub Gist에 저장"""
    if not GIST_ID or not GH_TOKEN:
        print("⚠ GIST_ID 또는 GH_TOKEN 없음 — Gist 저장 건너뜀")
        return False
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={'Authorization':f'token {GH_TOKEN}','Accept':'application/vnd.github.v3+json'},
            json={"files":{"kalpha_scan.json":{"content":json.dumps(data,ensure_ascii=False)}}},
            timeout=15)
        ok = r.status_code == 200
        print(f"{'✅ Gist 저장 완료' if ok else f'❌ Gist 저장 실패 {r.status_code}'}")
        return ok
    except Exception as e:
        print(f"❌ Gist 오류: {e}"); return False

def fmt_tg(s):
    pct=s.get('changePct',0); sign='+' if pct>=0 else ''
    p=s['price']; buy=int(p*0.995); stop=int(p*0.97); tgt=int(p*1.10)
    rr=round((tgt-p)/(p-stop+1),1)
    score=s.get('score',70); grade=s.get('grade','B')
    icon='🔴' if grade=='S' else '🟡'

    # 리스크 문자열
    risks = []
    if pct >= 7:   risks.append(f'+{pct:.0f}%급등주의')
    elif pct >= 4: risks.append(f'+{pct:.0f}%눌림대기')
    if rr < 1.5:   risks.append(f'RR{rr}낮음')
    risk_str = '·'.join(risks) if risks else '없음'

    lines = [
        f"{icon} <b>{s['name']}</b> ({s['code']})",
        f"   💰 현재가: <b>{p:,}원</b> {sign}{pct:.2f}% | 거래대금 {s.get('trAmt',0):,}억",
        f"   📈 매입가: {buy:,}원 | 손절: {stop:,}원 | RR {rr}",
        f"   🛡 {score}점({grade}) | ⚠ {risk_str}",
    ]

    # 상세 분석 사유
    reasons = build_fundamental_reasons(s, s.get('cat','swing'))
    for r in reasons:
        text = r.get('text','')
        if '[기본적 분석]' in text:
            lines.append(f"   🏢 {text.replace('[기본적 분석] ','')[:120]}")
        elif '[외부요인]' in text:
            lines.append(f"   🌐 {text.replace('[외부요인] ','')[:120]}")
        else:
            lines.append(f"   ▸ {text[:80]}")

    return '\n'.join(lines)

def send_telegram(msg, chat_id):
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id":chat_id,"text":msg,"parse_mode":"HTML"}, timeout=10)
    return r.json().get('ok',False)

def main():
    # ── 환경변수 디버그 ──
    print("=== ENV DEBUG ===")
    print(f"  TG_TOKEN: {'설정됨' if os.environ.get('TG_TOKEN') else '❌없음'}")
    print(f"  TG_CHAT: {'설정됨' if os.environ.get('TG_CHAT') else '❌없음'}")
    print(f"  TG_GROUP_CHAT raw: [{os.environ.get('TG_GROUP_CHAT','없음')}]")
    print(f"  TG_GROUP_INTERVAL raw: [{os.environ.get('TG_GROUP_INTERVAL','없음')}]")
    print(f"  GIST_ID: {'설정됨' if os.environ.get('GIST_ID') else '❌없음'}")
    print(f"  GH_TOKEN: {'설정됨' if os.environ.get('GH_TOKEN') else '❌없음'}")
    print(f"  KIS_AK: {'설정됨' if os.environ.get('KIS_AK') else '❌없음'}")
    print("=================")
    if not all([KIS_AK, KIS_SEC]):
        print("❌ KIS 환경변수 미설정"); return

    # ── Gist 설정 읽기 (앱에서 저장한 값 우선 적용) ──
    cfg = load_gist_config()
    # Gist cfg 적용 (환경변수 없을 때 보완)
    global TG_INTERVAL, TG_GROUP_INTERVAL, TG_GROUP2_INTERVAL, TG_GROUP3_INTERVAL
    global TG_GROUP_CHAT, TG_GROUP2_CHAT, TG_GROUP3_CHAT
    if cfg:
        if not cfg.get('tg_all_enabled', True):
            print("⏸ 전송 비활성화 — 앱에서 '메시지 발송' 꺼짐"); return
        if cfg.get('tg_interval_min'):     TG_INTERVAL     = max(10, min(240, int(cfg['tg_interval_min'])))
        if cfg.get('tg_group_interval_min'):  TG_GROUP_INTERVAL  = max(10, min(240, int(cfg['tg_group_interval_min'])))
        if cfg.get('tg_group2_interval_min'): TG_GROUP2_INTERVAL = max(10, min(240, int(cfg['tg_group2_interval_min'])))
        if cfg.get('tg_group3_interval_min'): TG_GROUP3_INTERVAL = max(10, min(240, int(cfg['tg_group3_interval_min'])))
        if not TG_GROUP_CHAT  and cfg.get('tg_group_chat'):   TG_GROUP_CHAT  = str(cfg['tg_group_chat'])
        if not TG_GROUP2_CHAT and cfg.get('tg_group2_chat'):  TG_GROUP2_CHAT = str(cfg['tg_group2_chat'])
        if not TG_GROUP3_CHAT and cfg.get('tg_group3_chat'):  TG_GROUP3_CHAT = str(cfg['tg_group3_chat'])
        print(f"  cfg 적용 — 개인:{TG_INTERVAL}분 그룹1:{TG_GROUP_INTERVAL or 'OFF'}분 그룹2:{TG_GROUP2_INTERVAL or 'OFF'}분 그룹3:{TG_GROUP3_INTERVAL or 'OFF'}분")
        print(f"  그룹채팅방 — 그룹1:{'✅' if TG_GROUP_CHAT else '❌'} 그룹2:{'✅' if TG_GROUP2_CHAT else '❌'} 그룹3:{'✅' if TG_GROUP3_CHAT else '❌'}")

    # 송출 시간 범위
    def _in_window(start_h, end_h):
        try:
            start_h = int(start_h) if start_h is not None else 0
            end_h   = int(end_h)   if end_h   is not None else 23
        except: start_h, end_h = 0, 23
        h = kst_now().hour
        if start_h <= end_h:
            return start_h <= h <= end_h
        return h >= start_h or h <= end_h

    t  = kst_now()
    ts = f"{t.hour:02d}:{t.minute:02d}:{t.second:02d}"
    total_min   = t.hour * 60 + t.minute
    is_manual   = bool(os.environ.get('MANUAL_INTERVAL','').strip())
    is_holiday  = is_korean_holiday(t)
    is_weekend  = t.weekday() >= 5
    market_open = is_market_open(t)

    print(f"[{ts} KST] 개인TG:{TG_INTERVAL}분 | 그룹1TG:{TG_GROUP_INTERVAL or 'OFF'}분 | 그룹2TG:{TG_GROUP2_INTERVAL or 'OFF'}분 | 그룹3TG:{TG_GROUP3_INTERVAL or 'OFF'}분 | 환경:{KIS_ENV}")
    print(f"  수동실행={is_manual} | 주말={is_weekend} | 공휴일={is_holiday} | 장중={market_open}")

    # ── 장외/공휴일/주말: 수동 실행만 허용 ──
    if not should_scan():
        reason = "주말" if is_weekend else ("공휴일" if is_holiday else "장외시간(08:00~15:30 외)")
        print(f"⏭ 스킵 — {reason} (수동: GitHub Actions workflow_dispatch → MANUAL_INTERVAL 설정)")
        return

    print(f"{'🔧 수동 실행' if is_manual else '📈 장중 자동 스캔'} ({ts} KST)")

    # ── 스캔 주기 체크 (앱에서 설정한 주기 적용) ──
    if not is_manual and cfg.get('scan_refresh_min'):
        _scan_min = max(1, min(60, int(cfg['scan_refresh_min'])))
        _last_scan = 0
        # Gist에서 마지막 스캔 시각 확인
        try:
            _gr = requests.get(
                f"https://api.github.com/gists/{GIST_ID}",
                headers={'Authorization':f'token {GH_TOKEN}','Accept':'application/vnd.github.v3+json'},
                timeout=8)
            _gc = _gr.json().get('files',{}).get('kalpha_scan.json',{}).get('content','')
            if _gc:
                _last_scan = json.loads(_gc).get('updated_at', 0)
        except: pass
        _elapsed = (time.time() - _last_scan) / 60
        if _last_scan and _elapsed < _scan_min - 0.5:
            print(f"⏭ 스캔 주기 미달 — 마지막: {_elapsed:.1f}분 전 | 설정: {_scan_min}분마다")
            return
        print(f"✅ 스캔 실행 — 마지막: {_elapsed:.1f}분 전 | 설정주기: {_scan_min}분")

    # 전송 대상 결정 (Chat ID 있고 시간 범위 안이면 전송)
    _h = kst_now().hour
    send_personal = bool(TG_CHAT and TG_TOKEN
                         and _in_window(cfg.get('tg_send_start_p', 0), cfg.get('tg_send_end_p', 23)))
    send_group    = bool(TG_GROUP_CHAT and TG_TOKEN and TG_GROUP_INTERVAL > 0
                         and _in_window(cfg.get('tg_send_start_g1', 0), cfg.get('tg_send_end_g1', 23)))
    send_group2   = bool(TG_GROUP2_CHAT and TG_TOKEN and TG_GROUP2_INTERVAL > 0
                         and _in_window(cfg.get('tg_send_start_g2', 0), cfg.get('tg_send_end_g2', 23)))
    send_group3   = bool(TG_GROUP3_CHAT and TG_TOKEN and TG_GROUP3_INTERVAL > 0
                         and _in_window(cfg.get('tg_send_start_g3', 0), cfg.get('tg_send_end_g3', 23)))

    print(f"  TG_CHAT={'✅' if TG_CHAT else '❌'} TG_TOKEN={'✅' if TG_TOKEN else '❌'} "
          f"GROUP_CHAT={'✅' if TG_GROUP_CHAT else '❌'} GROUP_INTERVAL={TG_GROUP_INTERVAL}")
    print(f"  전송: 개인={'✅' if send_personal else '❌'} 그룹1={'✅' if send_group else '❌'} 그룹2={'✅' if send_group2 else '❌'} 그룹3={'✅' if send_group3 else '❌'}")

    if not any([send_personal, send_group, send_group2, send_group3]):
        print("⏭ 전송 대상 없음"); return

    # ── 1순위: Gist에서 앱이 저장한 scan_result 읽기 ──
    scan_result = None
    kospi_n = 0; kosdaq_n = 0; total_n = 0

    if GIST_ID and GH_TOKEN:
        try:
            r = requests.get(
                f"https://api.github.com/gists/{GIST_ID}",
                headers={'Authorization': f'token {GH_TOKEN}', 'Accept': 'application/vnd.github.v3+json'},
                timeout=10)
            files = r.json().get('files', {})
            content = files.get('kalpha_scan.json', {}).get('content', '')
            if content:
                _gs = json.loads(content)
                sw  = len(_gs.get('swing', []))
                su  = len(_gs.get('surge', []))
                tm  = len(_gs.get('tomorrow', []))
                sml = len(_gs.get('smallmid', []))
                age = (time.time() - _gs.get('updated_at', 0)) / 60
                print(f"📋 Gist — {age:.0f}분 전 | 스윙:{sw} 급등:{su} 내일:{tm} 중소형:{sml}")
                if (sw + su + tm + sml) > 0:
                    scan_result = _gs
                    kospi_n  = _gs.get('kospi_n', 0)
                    kosdaq_n = _gs.get('kosdaq_n', 0)
                    total_n  = _gs.get('total', kospi_n + kosdaq_n)
                    print(f"  ✅ Gist 데이터 사용 (KOSPI {kospi_n}+KOSDAQ {kosdaq_n}종목)")
                else:
                    print("  ⚠ Gist 결과 0건 — KIS 직접 스캔 시도")
            else:
                print("  ⚠ Gist kalpha_scan.json 없음 — KIS 직접 스캔 시도")
        except Exception as e:
            print(f"⚠ Gist 로드 실패: {e} — KIS 직접 스캔 시도")
    else:
        print("⚠ GIST_ID 또는 GH_TOKEN 없음 — KIS 직접 스캔 시도")

    # ── 2순위: Gist가 비어있으면 KIS 직접 스캔 ──
    if not scan_result:
        print("🔑 KIS 토큰 발급 중...")
        token = get_token()
        if not token:
            print("❌ 토큰 발급 실패 — 종료"); return

        print("📊 거래량 순위 조회 (KOSPI 300 + KOSDAQ 100)...")
        kospi_raw  = fetch_ranking(token, 'J', 300)
        kosdaq_raw = fetch_ranking(token, 'Q', 100)
        all_s = kospi_raw + kosdaq_raw
        kospi_n  = len(kospi_raw)
        kosdaq_n = len(kosdaq_raw)
        total_n  = len(all_s)
        print(f"  KOSPI {kospi_n} + KOSDAQ {kosdaq_n} = {total_n}종목")

        if not all_s:
            print("❌ 종목 조회 결과 없음"); return

        cats = categorize(all_s)
        print(f"  스윙:{len(cats['swing'])} 급등:{len(cats['surge'])} "
              f"내일:{len(cats['tomorrow'])} 중소형:{len(cats['smallmid'])}")

        scan_result = {
            'swing':    [build_card(s,'swing')    for s in cats['swing']],
            'surge':    [build_card(s,'surge')    for s in cats['surge']],
            'smallmid': [build_card(s,'smallmid') for s in cats['smallmid']],
            'tomorrow': [build_card(s,'tomorrow') for s in cats['tomorrow']],
            'ts': ts, 'total': total_n,
            'kospi_n': kospi_n, 'kosdaq_n': kosdaq_n,
            'updated_at': time.time(),
            'is_manual': is_manual,
            'market_open': market_open,
        }
        # Gist에 저장해 앱도 즉시 사용 가능하게
        save_to_gist(scan_result)

    if not scan_result:
        print("⏭ 스캔 데이터 없음"); return

    if not TG_TOKEN:
        print("⚠ TG_TOKEN 없음 — 텔레그램 전송 건너뜀"); return

    def fmt_card(c):
        """UI 카드와 완전 동일한 포맷 — 저장된 buy/stop/target/rr 사용, truncation 없음"""
        try: p = int(str(c.get('price','0')).replace(',',''))
        except: p = 0
        def _toi(v, fb):
            try: return int(str(v).replace(',',''))
            except: return fb
        buy  = _toi(c.get('buy'),  int(p*0.995))
        stop = _toi(c.get('stop'), int(p*0.97))
        tgt  = _toi(c.get('target'), int(p*1.10))
        try: rr = float(str(c.get('rr','')).replace(',',''))
        except: rr = 0
        if not rr: rr = round((tgt-p)/(p-stop+1),1) if p>0 else 3.3
        vol   = c.get('vol',0)
        try: vol = int(vol)
        except: pass
        pct   = c.get('change','0%')
        score = c.get('score',70); grade = c.get('grade','B')
        rsi   = c.get('rsiApprox',50) or 50
        mkt   = str(c.get('mkt','KOSPI')).upper()
        chg   = 0.0
        try: chg = float(str(pct).replace('%','').replace('+',''))
        except: pass
        if grade=='S':   g_icon='🔴'
        elif grade=='A': g_icon='🟠'
        elif grade=='B': g_icon='🟡'
        else:            g_icon='⚪'
        if chg>=7:      risk_lbl=f'⚠ +{chg:.0f}% 급등 — 추격매수 주의'
        elif chg>=4:    risk_lbl=f'📌 +{chg:.0f}% 눌림 — 단기 조정 가능'
        elif rr<1.5:    risk_lbl='⚠ RR 낮음 — 손절폭 재검토 필요'
        elif rsi>72:    risk_lbl=f'⚠ RSI {rsi:.0f} — 과매수 구간'
        else:           risk_lbl='✅ 리스크 정상'
        lines = [
            '━'*18,
            f"{g_icon} <b>{c.get('name','')} ({c.get('code','')})</b>  [{mkt}]",
            f"💰 <b>{p:,}원</b>  {pct}  |  거래대금 <b>{vol:,}억</b>",
            f"📊 RSI {rsi:.0f}  |  K점수 <b>{score}점({grade})</b>  |  RR <b>{rr}</b>",
            f"📈 매입가 {buy:,}원  →  목표 {tgt:,}원  |  손절 {stop:,}원",
            risk_lbl,
        ]
        reasons = c.get('reasons',[])
        if reasons:
            lines.append('')
            lines.append('📋 <b>K 분석 사유</b>')
            for r in reasons:
                txt = r.get('text','') if isinstance(r,dict) else str(r)
                lines.append(f"  ▸ {txt}")
        return '\n'.join(lines)

    # 날짜+시간 표시 (저녁 20:00 이후엔 날짜 포함)
    _h = kst_now().hour
    ts_display = kst_now().strftime('%-m월%-d일 %H:%M') if (_h >= 20 or _h < 6) else ts

    TG_LIMIT = 3800  # 텔레그램 4096자 제한 — 안전 마진

    def send_by_category(chat_id, iv_min, n=10, menu=None):
        """카테고리별 분리 + 4096자 초과 시 자동 분할 전송"""
        if menu is None:
            menu = {"swing":True,"surge":True,"tomorrow":True,"smallmid":True,"per":False}
        iv_lbl  = _lbl(iv_min)
        mkt_lbl = '🟢장중' if market_open else '🔴장마감'
        _n = max(1, int(n))

        sw  = scan_result.get('swing',[])[:_n]    if menu.get('swing',True)    else []
        su  = scan_result.get('surge',[])[:_n]    if menu.get('surge',True)    else []
        tm  = scan_result.get('tomorrow',[])[:_n]  if menu.get('tomorrow',True) else []
        sml = scan_result.get('smallmid',[])[:_n]  if menu.get('smallmid',True) else []
        per = scan_result.get('per',[])[:_n]        if menu.get('per',False)     else []

        # 헤더
        header = (f"📡 <b>K-ALPHA {iv_lbl} 자동 스캔</b> [{ts_display}] {mkt_lbl}\n"
                  f"KOSPI {kospi_n}+KOSDAQ {kosdaq_n}종목\n"
                  f"🔥스윙:{len(sw)} ⚡급등:{len(su)} 🌙내일:{len(tm)} 📦중소형:{len(sml)}"
                  + (f" 💎PER:{len(per)}" if per else ""))
        send_telegram(header, chat_id)
        time.sleep(0.3)

        if not any([sw, su, tm, sml, per]):
            send_telegram("📊 스캔 결과 없음 — 필터 조건 미달", chat_id)
            return True

        def send_cat(lst, emoji, label):
            """카테고리별 전송. 3800자 초과 시 자동 분할."""
            if not lst: return
            total  = len(lst)
            msg_no = 1
            buf    = []
            buf_len= 0
            for stock in lst:
                card = fmt_card(stock)
                clen = len(card) + 2
                if buf and (buf_len + clen > TG_LIMIT):
                    hdr = f"{emoji} <b>【{label} TOP{total}】 — {msg_no}부</b>"
                    send_telegram(hdr + '\n' + '\n\n'.join(buf), chat_id)
                    time.sleep(0.4)
                    msg_no += 1; buf = []; buf_len = 0
                buf.append(card); buf_len += clen
            if buf:
                hdr = (f"{emoji} <b>【{label} TOP{total}】</b>" if msg_no == 1
                       else f"{emoji} <b>【{label} TOP{total}】 — {msg_no}부</b>")
                send_telegram(hdr + '\n' + '\n\n'.join(buf), chat_id)
                time.sleep(0.4)

        send_cat(sw,  '🔥', '실시간 스윙')
        send_cat(su,  '⚡', '급등전야')
        send_cat(tm,  '🌙', '내일관심')
        send_cat(sml, '📦', '중소형주')
        send_cat(per, '💎', 'PER저평가')
        send_telegram('━'*16 + f"\n📊 총 {total_n}종목 스캔완료\n⏱ 다음 전송 {iv_lbl} 후", chat_id)
        return True

    # 채팅방별 카테고리당 종목 수 (Gist 설정값 우선)
    _n_p  = int(cfg.get('tg_ai_count_p',  10))
    _n_g1 = int(cfg.get('tg_ai_count_g1', 10))
    _n_g2 = int(cfg.get('tg_ai_count_g2', 10))
    _n_g3 = int(cfg.get('tg_ai_count_g3', 10))

    # 채팅방별 메뉴
    _default_menu = {"swing":True,"surge":True,"tomorrow":True,"smallmid":True,"per":False}
    _menu_p  = cfg.get('tg_menu_p',  _default_menu)
    _menu_g1 = cfg.get('tg_menu_g1', _default_menu)
    _menu_g2 = cfg.get('tg_menu_g2', _default_menu)
    _menu_g3 = cfg.get('tg_menu_g3', _default_menu)

    # PER 저평가주 스캔 (cfg에서 활성화된 경우)
    per_stocks = []
    if cfg.get('per_scan_enabled', False) and any([
        _menu_p.get('per'), _menu_g1.get('per'),
        _menu_g2.get('per'), _menu_g3.get('per')
    ]):
        # Gist에서 기존 per 데이터 있으면 재사용
        _existing_per = scan_result.get('per', []) if scan_result else []
        if _existing_per:
            per_stocks = _existing_per
            print(f"  💎 PER 저평가주: Gist 기존 데이터 {len(per_stocks)}종목")
        else:
            print("  💎 PER 저평가주 스캔 중 (KIS API)...")
            try:
                _per_max     = float(cfg.get('per_max', 15.0))
                _per_min     = float(cfg.get('per_min', 0.1))
                _pbr_max     = float(cfg.get('pbr_max', 1.0))
                _roe_min     = float(cfg.get('roe_min', 10.0))
                _per_vol_min = int(cfg.get('per_vol_min', 30))
                _per_top_n   = int(cfg.get('per_top_n', 20))

                _token = get_token()
                if not _token:
                    print("  ⚠ KIS 토큰 없음 — PER 스캔 건너뜀")
                else:
                    _ph = {'Content-Type':'application/json',
                           'authorization':f'Bearer {_token}',
                           'appkey':KIS_AK,'appsecret':KIS_SEC,
                           'tr_id':'FHKST01010100'}
                    # KOSPI + KOSDAQ 후보 코드 (상위 대형주 위주)
                    _KOSPI_CODES = [
                        '005930','000660','373220','207940','005380','005490','035420',
                        '000270','051910','028260','034730','066570','017670','086790',
                        '032830','105560','055550','009150','011070','012450','035720',
                        '006400','003550','247540','086520','196170','352820','141080',
                        '263750','066970','357780','145020','039030','058470','140860',
                        '046080','091990','272210','122870','112040','054040','039440',
                        '064760','036830','084370','454910','320000','035900','095340',
                        '041510','151910','085370','252990','067160','079940','067900',
                        '009420','033780','214150','041830','086900','108860','042700',
                        '139670','302920','204210','056080','253590','078070','040350',
                        '110020','137400','049630','038680','041440','083930','025870',
                        '036180','035760','030350','084110','140670','058970','012510',
                        '052900','237690','211050','036800','048260','038110','086390',
                        '237750','352480','099800','108320','145720','263720','038500',
                        '200130','215200','068760','046890','244880','290650','006280',
                        '143240','026960','222080','063160','048830','034020','036810',
                    ]
                    _per_results = []
                    for _code in _KOSPI_CODES:
                        try:
                            for _mkt_try in ['J', 'Q']:
                                _rp = requests.get(
                                    f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
                                    params={'FID_COND_MRKT_DIV_CODE': _mkt_try,
                                            'FID_INPUT_ISCD': _code},
                                    headers=_ph, verify=False, timeout=4)
                                _o = _rp.json().get('output', {})
                                if not _o.get('stck_prpr'):
                                    continue
                                _price   = float(_o.get('stck_prpr', 0) or 0)
                                _per     = float(_o.get('per', 0) or 0)
                                _pbr     = float(_o.get('pbr', 0) or 0)
                                _eps     = float(_o.get('eps', 0) or 0)
                                _bps     = float(_o.get('bps', 1) or 1)
                                _roe     = (_eps / _bps * 100) if _bps > 0 else 0
                                _tr_raw  = float(_o.get('acml_tr_pbmn', 0) or 0)
                                _tr_amt  = _tr_raw / 1e8
                                _sign_cd = _o.get('prdy_vrss_sign', '3')
                                _chg_raw = float(_o.get('prdy_ctrt', 0) or 0)
                                _chg_pct = -_chg_raw if _sign_cd in ['4','5'] else _chg_raw
                                _name_raw = (_o.get('hts_kor_isnm') or _o.get('prdt_abrv_name') or
                                             _o.get('prdt_name') or _o.get('stck_kor_isnm') or '').strip()
                                _name = _name_raw if _name_raw else _STOCK_NAMES.get(_code, _code)
                                if is_etf(_name): break
                                if not (_per_min < _per < _per_max): break
                                if _pbr > _pbr_max or _pbr <= 0:     break
                                if _roe < _roe_min:                   break
                                if _tr_amt < _per_vol_min:            break
                                if _price <= 0:                       break
                                _mkt_l = 'kospi' if _mkt_try == 'J' else 'kosdaq'
                                _buy  = int(_price*0.995); _stop=int(_price*0.97); _tgt=int(_price*1.10)
                                _rr   = round((_tgt-_price)/(_price-_stop+1),1)
                                _sign = '+' if _chg_pct >= 0 else ''
                                _sc_per = max(0,min(30,int((_per_max-_per)/_per_max*30)))
                                _sc_roe = min(25,int((_roe-_roe_min)/5))
                                _sc_pbr = max(0,min(20,int((_pbr_max-_pbr)/_pbr_max*20)))
                                _sc_vol = min(15,int(_tr_amt/30))
                                _score  = min(95, 50+_sc_per+_sc_roe+_sc_pbr+_sc_vol)
                                _grade  = 'S' if _score>=85 else ('A' if _score>=75 else 'B')
                                _per_results.append({
                                    'code':_code,'name':_name,
                                    'price':f"{int(_price):,}",'change':f"{_sign}{_chg_pct:.2f}%",
                                    'up':_chg_pct>=0,'buy':f"{_buy:,}",'target':f"{_tgt:,}",
                                    'stop':f"{_stop:,}",'rr':str(_rr),'vol':int(_tr_amt),
                                    'mkt':_mkt_l,'rsiApprox':round(50+_chg_pct*2.8,1),
                                    'score':_score,'grade':_grade,
                                    'per':round(_per,1),'pbr':round(_pbr,2),'roe':round(_roe,1),
                                    'cat':'per',
                                    'reasons':[
                                        {'icon':'💎','cat':'green','text':f"PER {_per:.1f}배 · PBR {_pbr:.2f} · ROE {_roe:.1f}%"},
                                        {'icon':'📊','cat':'','text':f"거래대금 {int(_tr_amt):,}억 · {_sign}{_chg_pct:.2f}%"},
                                        {'icon':'📈','cat':'orange','text':f"매입가 {_buy:,}원 → 목표 {_tgt:,}원 · 손절 {_stop:,}원"},
                                        {'icon':'🔍','cat':'blue','text':f"[저평가 분석] PER 저평가 · ROE {_roe:.1f}% 수익성 확인"},
                                    ],
                                    'inds':[{'label':_mkt_l.upper(),'cat':'green'},
                                            {'label':f"PER {_per:.1f}",'cat':'orange'},
                                            {'label':f"ROE {_roe:.1f}%",'cat':''}],
                                    'chart3m':[],'chartD':[]
                                })
                                break
                            time.sleep(0.04)
                        except: continue
                    _per_results.sort(key=lambda x:x['score'],reverse=True)
                    per_stocks = _per_results[:_per_top_n]
                    scan_result['per'] = per_stocks
                    print(f"  💎 PER 저평가주 {len(per_stocks)}종목 스캔 완료")
            except Exception as _e:
                print(f"  ⚠ PER 스캔 실패: {_e}")
    else:
        per_stocks = scan_result.get('per', []) if scan_result else []

    def _filter_by_menu(sr, menu):
        """메뉴 dict에 따라 카테고리 필터링한 dict 반환"""
        filtered = {}
        for cat in ['swing','surge','tomorrow','smallmid','per']:
            filtered[cat] = sr.get(cat, []) if menu.get(cat, cat != 'per') else []
        return filtered

    if send_personal:
        _sr_p = _filter_by_menu(scan_result, _menu_p)
        ok_p = send_by_category(TG_CHAT, TG_INTERVAL, n=_n_p, menu=_menu_p)
        print(f"{'✅ 개인방 전송 완료' if ok_p else '❌ 개인방 전송 실패'}")
    else:
        print(f"⏭ 개인방 TG 스킵 — 간격:{TG_INTERVAL}분 | 나머지:{total_min % TG_INTERVAL}분")

    if TG_GROUP_INTERVAL > 0:
        if send_group:
            ok_g = send_by_category(TG_GROUP_CHAT, TG_GROUP_INTERVAL, n=_n_g1, menu=_menu_g1)
            print(f"{'✅ 그룹방 1 전송 완료' if ok_g else '❌ 그룹방 1 전송 실패'}")
        else:
            print(f"⏭ 그룹방 1 TG 스킵 — 나머지:{total_min % TG_GROUP_INTERVAL}분")

    if TG_GROUP2_INTERVAL > 0:
        if send_group2:
            ok_g2 = send_by_category(TG_GROUP2_CHAT, TG_GROUP2_INTERVAL, n=_n_g2, menu=_menu_g2)
            print(f"{'✅ 그룹방 2 전송 완료' if ok_g2 else '❌ 그룹방 2 전송 실패'}")
        else:
            print(f"⏭ 그룹방 2 TG 스킵 — 나머지:{total_min % TG_GROUP2_INTERVAL}분")

    if TG_GROUP3_INTERVAL > 0:
        if send_group3:
            ok_g3 = send_by_category(TG_GROUP3_CHAT, TG_GROUP3_INTERVAL, n=_n_g3, menu=_menu_g3)
            print(f"{'✅ 그룹방 3 전송 완료' if ok_g3 else '❌ 그룹방 3 전송 실패'}")
        else:
            print(f"⏭ 그룹방 3 TG 스킵 — 나머지:{total_min % TG_GROUP3_INTERVAL}분")

    print("✅ 완료")

if __name__ == '__main__':
    main()
