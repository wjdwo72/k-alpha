"""
K-ALPHA 백그라운드 스캔 워커
GitHub Actions에서 실행 — 앱이 꺼져도 자동 스캔 & 텔레그램 발송

Secrets 설정 (GitHub → Settings → Secrets → Actions):
  KIS_AK    = 앱키
  KIS_SEC   = 시크릿
  KIS_ACC   = 계좌번호 (예: 69108332-01)
  KIS_ENV   = real  (실전) 또는 vts (모의)
  TG_TOKEN  = 텔레그램 봇 토큰
  TG_CHAT   = 텔레그램 Chat ID
  INTERVAL  = 전송 간격 분 (5/10/15/20/30, 기본값 10)
"""
import os, json, time, math, requests, urllib3
urllib3.disable_warnings()

# ── 환경변수 ──
KIS_AK   = os.environ.get('KIS_AK','').strip()
KIS_SEC  = os.environ.get('KIS_SEC','').strip()
KIS_ACC  = os.environ.get('KIS_ACC','').strip()
KIS_ENV  = os.environ.get('KIS_ENV','real').strip()
TG_TOKEN = os.environ.get('TG_TOKEN','').strip()
TG_CHAT  = os.environ.get('TG_CHAT','').strip()

# 전송 간격: 수동 입력 우선, 없으면 Secret, 없으면 기본 10분
_iv = os.environ.get('MANUAL_INTERVAL','').strip() or os.environ.get('INTERVAL','10').strip()
try: INTERVAL = int(_iv)
except: INTERVAL = 10
INTERVAL = max(5, min(60, INTERVAL))  # 5~60분 범위

BASE_URL = ("https://openapi.koreainvestment.com:9443" if KIS_ENV=='real'
            else "https://openapivts.koreainvestment.com:29443")

ETF_KW = ['ETF','KODEX','TIGER','KBSTAR','ARIRANG','HANARO','KOSEF','ACE ',
          '인버스','레버리지','선물','리츠','REIT','스팩','SPAC']

def is_etf(n): return any(k in n.upper() for k in ETF_KW)

def should_send_now():
    """현재 시각이 전송 간격의 배수인지 확인"""
    now = time.localtime(time.time() + 9*3600)  # KST
    total_min = now.tm_hour * 60 + now.tm_min
    # 9:00(540) ~ 15:30(930) 장중만
    if not (540 <= total_min <= 930): return False
    # 주말 제외
    if now.tm_wday >= 5: return False
    # 간격 체크 (5분 단위 실행이므로 현재 분이 간격의 배수인지)
    return (now.tm_min % INTERVAL) < 5

def get_token():
    r = requests.post(f"{BASE_URL}/oauth2/tokenP",
        json={"grant_type":"client_credentials","appkey":KIS_AK,"appsecret":KIS_SEC},
        verify=False, timeout=12)
    return r.json().get('access_token','')

def fetch_ranking(token, mkt, top_n=150):
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
        print(f"거래량순위 오류 ({mkt}): {e}")
    return stocks

def categorize(stocks):
    swing, surge, smallmid = [], [], []
    seen = set()
    for s in stocks:
        if s['code'] in seen: continue
        seen.add(s['code'])
        pct = s.get('changePct',0)
        tr  = s.get('trAmt',0)
        if tr < 50: continue
        if 0.5 <= pct <= 4.0 and tr >= 200:
            sc = min(95, 70+int(pct*5)+min(15, tr//500))
            s2=dict(s); s2['score']=sc; s2['grade']='S' if sc>=85 else 'A'; s2['cat']='swing'
            swing.append(s2)
        elif pct >= 4.0 and tr >= 100:
            sc = min(95, 65+int(pct*3)+min(20, tr//300))
            s2=dict(s); s2['score']=sc; s2['grade']='S' if sc>=85 else 'A'; s2['cat']='surge'
            surge.append(s2)
        if 50 <= tr <= 500 and -2.0 <= pct <= 3.0:
            sc = min(90, 65+min(15, tr//50)+int(pct*5))
            s2=dict(s); s2['score']=sc; s2['grade']='S' if sc>=80 else 'A'; s2['cat']='smallmid'
            smallmid.append(s2)

    def top(lst, n):
        seen2=set(); res=[]
        for x in sorted(lst, key=lambda x: x.get('score',0), reverse=True):
            if x['code'] not in seen2:
                seen2.add(x['code']); res.append(x)
            if len(res)>=n: break
        return res
    return top(swing,5)+top(surge,5), top(smallmid,5)

def fmt(s):
    pct=s.get('changePct',0); sign='+' if pct>=0 else ''
    p=s['price']; buy=int(p*0.995); stop=int(p*0.97); tgt=int(p*1.10)
    rr=round((tgt-p)/(p-stop+1),1)
    icon='🔴' if s.get('grade')=='S' else '🟡'
    return (f"{icon} <b>{s['name']}</b> ({s['code']})\n"
            f"   💰 현재가: <b>{p:,}원</b> {sign}{pct:.2f}% | 거래대금 {s.get('trAmt',0):,}억\n"
            f"   📈 매입가: {buy:,}원 | 손절: {stop:,}원 | RR {rr}")

def send(msg):
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id":TG_CHAT,"text":msg,"parse_mode":"HTML"}, timeout=10)
    return r.json().get('ok', False)

def main():
    if not all([KIS_AK, KIS_SEC, TG_TOKEN, TG_CHAT]):
        print("❌ 환경변수 미설정"); return

    kst = time.localtime(time.time() + 9*3600)
    ts  = f"{kst.tm_hour:02d}:{kst.tm_min:02d}:{kst.tm_sec:02d}"
    print(f"[{ts} KST] 간격:{INTERVAL}분 | 환경:{KIS_ENV}")

    # 수동 실행(workflow_dispatch)이면 무조건 전송
    is_manual = bool(os.environ.get('MANUAL_INTERVAL','').strip())
    if not is_manual and not should_send_now():
        print(f"⏭ 스킵 — 장외시간 또는 전송 간격 미해당 (간격:{INTERVAL}분, 현재분:{kst.tm_min})")
        return

    print("🔍 KIS API 토큰 발급 중...")
    token = get_token()
    if not token:
        print("❌ 토큰 발급 실패"); return

    print("📊 거래량 순위 조회 중...")
    kospi  = fetch_ranking(token, 'J', 150)
    kosdaq = fetch_ranking(token, 'Q', 100)
    all_s  = kospi + kosdaq
    print(f"KOSPI {len(kospi)}종목 + KOSDAQ {len(kosdaq)}종목")

    if not all_s:
        print("❌ 스캔 결과 없음"); return

    main_s, small_s = categorize(all_s)

    # 분류 결과 없으면 거래대금 상위 fallback
    if not main_s:
        main_s = sorted(all_s, key=lambda x: x.get('trAmt',0), reverse=True)[:5]
        for s in main_s: s.setdefault('score',75); s.setdefault('grade','B'); s.setdefault('cat','swing')

    is_market = 9 <= kst.tm_hour <= 15
    mkt_label = "🟢 장중" if is_market else "🔴 장 마감"
    section_title = "🔥 <b>[실시간 스윙/급등 TOP5]</b>" if any(s.get('cat')=='swing' for s in main_s) else "📊 <b>[거래대금 상위 TOP5]</b>"

    lines = [f"📡 <b>K-ALPHA {INTERVAL}분 자동 스캔</b> [{ts}] {mkt_label}\n"
             f"KOSPI {len(kospi)}종목 + KOSDAQ {len(kosdaq)}종목\n━━━━━━━━━━━━━━━━",
             section_title]
    for s in main_s: lines.append(fmt(s))
    if small_s:
        lines.append("\n⬟ <b>[내일의 중소형주 TOP5]</b>")
        for s in small_s: lines.append(fmt(s))
    lines.append(f"━━━━━━━━━━━━━━━━\n📊 {len(all_s)}종목 스캔 완료 · 다음 알림 {INTERVAL}분 후")

    msg = "\n\n".join(lines)
    ok = send(msg)
    print(f"{'✅ 텔레그램 전송 성공' if ok else '❌ 텔레그램 전송 실패'}")

if __name__ == '__main__':
    main()
