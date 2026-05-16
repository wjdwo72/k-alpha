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

GIST_ID  = os.environ.get('GIST_ID','').strip()
GH_TOKEN = os.environ.get('GH_TOKEN','').strip()

# 하위 호환: INTERVAL 변수는 개인방 기준
INTERVAL = TG_INTERVAL

BASE_URL = ("https://openapi.koreainvestment.com:9443" if KIS_ENV=='real'
            else "https://openapivts.koreainvestment.com:29443")

ETF_KW = ['ETF','KODEX','TIGER','KBSTAR','ARIRANG','HANARO','KOSEF','ACE ',
          '인버스','레버리지','선물','리츠','REIT','스팩','SPAC']

def is_etf(n): return any(k in n.upper() for k in ETF_KW)

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
    - MANUAL_INTERVAL 있으면 무조건 True (수동 실행)
    """
    if os.environ.get('MANUAL_INTERVAL','').strip(): return True
    return is_market_open()

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

def get_token():
    r = requests.post(f"{BASE_URL}/oauth2/tokenP",
        json={"grant_type":"client_credentials","appkey":KIS_AK,"appsecret":KIS_SEC},
        verify=False, timeout=12)
    return r.json().get('access_token','')

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

def categorize(stocks):
    swing, surge, tomorrow_list, smallmid = [], [], [], []
    seen = set()
    for s in stocks:
        if s['code'] in seen: continue
        seen.add(s['code'])
        pct, tr = s.get('changePct',0), s.get('trAmt',0)
        if tr < 50: continue
        if 0.5 <= pct <= 4.0 and tr >= 200:
            sc = min(95, 70+int(pct*5)+min(15,tr//500))
            s2=dict(s); s2.update({'score':sc,'grade':'S' if sc>=85 else 'A','cat':'swing'})
            swing.append(s2)
        elif pct >= 4.0 and tr >= 100:
            sc = min(95, 65+int(pct*3)+min(20,tr//300))
            s2=dict(s); s2.update({'score':sc,'grade':'S' if sc>=85 else 'A','cat':'surge'})
            surge.append(s2)
        elif -1.0 <= pct <= 1.5 and tr >= 50:
            sc = min(90, 60+min(20,tr//200)+int(abs(pct)*3))
            s2=dict(s); s2.update({'score':sc,'grade':'S' if sc>=80 else 'A','cat':'tomorrow'})
            tomorrow_list.append(s2)
        if 50 <= tr <= 500 and -2.0 <= pct <= 3.0:
            sc = min(90, 65+min(15,tr//50)+int(pct*5))
            s2=dict(s); s2.update({'score':sc,'grade':'S' if sc>=80 else 'A','cat':'smallmid'})
            smallmid.append(s2)

    def top(lst, n):
        seen2=set(); res=[]
        for x in sorted(lst, key=lambda x:x.get('score',0), reverse=True):
            if x['code'] not in seen2: seen2.add(x['code']); res.append(x)
            if len(res)>=n: break
        return res
    return {
        'swing':    top(swing, 5),
        'surge':    top(surge, 5),
        'tomorrow': top(tomorrow_list, 5),
        'smallmid': top(smallmid, 10),
    }

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
    icon='🔴' if s.get('grade')=='S' else '🟡'
    return (f"{icon} <b>{s['name']}</b> ({s['code']})\n"
            f"   💰 현재가: <b>{p:,}원</b> {sign}{pct:.2f}% | 거래대금 {s.get('trAmt',0):,}억\n"
            f"   📈 매입가: {buy:,}원 | 손절: {stop:,}원 | RR {rr}")

def send_telegram(msg, chat_id):
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id":chat_id,"text":msg,"parse_mode":"HTML"}, timeout=10)
    return r.json().get('ok',False)

def main():
    if not all([KIS_AK, KIS_SEC]):
        print("❌ KIS 환경변수 미설정"); return

    t  = kst_now()
    ts = f"{t.hour:02d}:{t.minute:02d}:{t.second:02d}"
    total_min   = t.hour * 60 + t.minute
    is_manual   = bool(os.environ.get('MANUAL_INTERVAL','').strip())
    is_holiday  = is_korean_holiday(t)
    is_weekend  = t.weekday() >= 5
    market_open = is_market_open(t)

    print(f"[{ts} KST] 개인TG:{TG_INTERVAL}분 | 그룹TG:{TG_GROUP_INTERVAL or 'OFF'}분 | 환경:{KIS_ENV}")
    print(f"  수동실행={is_manual} | 주말={is_weekend} | 공휴일={is_holiday} | 장중={market_open}")

    # ── 장외/공휴일/주말: 수동 실행만 허용 ──
    if not should_scan():
        reason = "주말" if is_weekend else ("공휴일" if is_holiday else "장외시간(08:00~15:30 외)")
        print(f"⏭ 스킵 — {reason} (수동: GitHub Actions workflow_dispatch → MANUAL_INTERVAL 설정)")
        return

    print(f"{'🔧 수동 실행' if is_manual else '📈 장중 자동 스캔'} ({ts} KST)")

    send_personal = bool(TG_CHAT and TG_TOKEN and should_send_tg(TG_INTERVAL))
    send_group    = bool(TG_GROUP_CHAT and TG_TOKEN and TG_GROUP_INTERVAL > 0
                        and should_send_tg(TG_GROUP_INTERVAL))

    print("🔑 KIS 토큰 발급 중...")
    token = get_token()
    if not token: print("❌ 토큰 발급 실패"); return

    print("📊 거래량 순위 조회 (KOSPI 300 + KOSDAQ 100)...")
    kospi  = fetch_ranking(token, 'J', 300)
    kosdaq = fetch_ranking(token, 'Q', 100)
    all_s  = kospi + kosdaq
    print(f"  KOSPI {len(kospi)} + KOSDAQ {len(kosdaq)} = {len(all_s)}종목 (ETF 제외)")

    if not all_s: print("❌ 결과 없음"); return

    cats = categorize(all_s)
    print(f"  스윙:{len(cats['swing'])} 급등:{len(cats['surge'])} "
          f"내일:{len(cats['tomorrow'])} 중소형:{len(cats['smallmid'])}")

    scan_result = {
        'swing':    [build_card(s,'swing')    for s in cats['swing']],
        'surge':    [build_card(s,'surge')    for s in cats['surge']],
        'smallmid': [build_card(s,'smallmid') for s in cats['smallmid']],
        'tomorrow': [build_card(s,'tomorrow') for s in cats['tomorrow']],
        'ts': ts, 'total': len(all_s),
        'kospi_n': len(kospi), 'kosdaq_n': len(kosdaq),
        'updated_at': time.time(),
        'is_manual': is_manual,
        'market_open': market_open,
    }
    save_to_gist(scan_result)

    if not TG_TOKEN:
        print("⚠ TG_TOKEN 없음 — 텔레그램 전송 건너뜀"); return

    def build_msg(iv_min):
        iv_lbl   = _lbl(iv_min)
        mkt_lbl  = '🟢장중' if market_open else '🔴장마감(수동)'
        top_main = (cats['swing'] + cats['surge'])[:5]
        top_sm   = cats['smallmid'][:5]
        top_tmrw = cats['tomorrow'][:3]
        if not top_main:
            top_main = sorted(all_s, key=lambda x:x.get('trAmt',0), reverse=True)[:5]
            for s in top_main: s.setdefault('score',75); s.setdefault('grade','B')
        lines = [
            f"📡 <b>K-ALPHA {iv_lbl} 자동 스캔</b> [{ts}] {mkt_lbl}\n"
            f"KOSPI {len(kospi)}종목 + KOSDAQ {len(kosdaq)}종목\n━━━━━━━━━━━━━━━━",
            "🔥 <b>[실시간 스윙/급등 TOP5]</b>" if cats['swing'] else "📊 <b>[거래대금 상위 TOP5]</b>"
        ]
        for s in top_main: lines.append(fmt_tg(s))
        if top_sm:
            lines.append(f"\n⬟ <b>[중소형주 TOP5]</b>")
            for s in top_sm: lines.append(fmt_tg(s))
        if top_tmrw:
            lines.append(f"\n🔭 <b>[내일관심 TOP3]</b>")
            for s in top_tmrw: lines.append(fmt_tg(s))
        lines.append(f"━━━━━━━━━━━━━━━━\n📊 {len(all_s)}종목 스캔완료 · 다음 {iv_lbl} 후")
        return "\n\n".join(lines)

    if send_personal:
        ok_p = send_telegram(build_msg(TG_INTERVAL), TG_CHAT)
        print(f"{'✅ 개인방 전송 완료' if ok_p else '❌ 개인방 전송 실패'}")
    else:
        print(f"⏭ 개인방 TG 스킵 — 간격:{TG_INTERVAL}분 | 나머지:{total_min % TG_INTERVAL}분")

    if TG_GROUP_INTERVAL > 0:
        if send_group:
            ok_g = send_telegram(build_msg(TG_GROUP_INTERVAL), TG_GROUP_CHAT)
            print(f"{'✅ 그룹방 전송 완료' if ok_g else '❌ 그룹방 전송 실패'}")
        else:
            print(f"⏭ 그룹방 TG 스킵 — 나머지:{total_min % TG_GROUP_INTERVAL}분")

    print("✅ 완료")

if __name__ == '__main__':
    main()
