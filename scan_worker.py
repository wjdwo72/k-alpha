"""
K-ALPHA 백그라운드 스캔 워커
GitHub Actions 실행 → 결과를 GitHub Gist에 저장
→ Streamlit 앱이 열리면 Gist에서 즉시 읽기 (0초)
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
    """분 → '10분', '1시간', '1시간30분' 형태 레이블"""
    if m < 60:   return f"{m}분"
    if m % 60==0: return f"{m//60}시간"
    return f"{m//60}시간{m%60}분"

def should_send(interval_min):
    """해당 간격 기준으로 지금 전송해야 하면 True"""
    is_manual = bool(os.environ.get('MANUAL_INTERVAL','').strip())
    if is_manual: return True
    t = kst_now()
    total = t.hour*60 + t.minute
    if not (540 <= total <= 930): return False   # 09:00~15:30
    if t.weekday() >= 5: return False            # 주말 제외
    return (total % interval_min) < 5           # 간격 단위 bucket

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

def categorize(stocks):
    swing, surge, smallmid = [], [], []
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
            # tomorrow list not used for gist but keep for completeness
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
    return {'swing':top(swing,5),'surge':top(surge,5),'smallmid':top(smallmid,10)}

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
        'reasons':[
            {'icon':'◈','cat':'green','text':f"거래대금 {s.get('trAmt',0):,}억 · 거래량순위 상위"},
            {'icon':'◉','cat':'','text':f"등락률 {sign}{pct:.2f}% · RSI 추정 {round(50+pct*2.5)}"},
            {'icon':'▲','cat':'orange','text':f"매입가 {buy:,}원 → 목표 {tgt:,}원 · 손절 {stop:,}원"},
        ],
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

    t = kst_now()
    ts = f"{t.hour:02d}:{t.minute:02d}:{t.second:02d}"
    print(f"[{ts} KST] 개인간격:{TG_INTERVAL}분 | 그룹간격:{TG_GROUP_INTERVAL or 'OFF'}분 | 환경:{KIS_ENV}")

    # 개인방 또는 그룹방 중 하나라도 전송 타이밍이면 스캔 실행
    send_personal = TG_CHAT and should_send(TG_INTERVAL)
    send_group    = TG_GROUP_CHAT and TG_GROUP_INTERVAL > 0 and should_send(TG_GROUP_INTERVAL)

    if not send_personal and not send_group:
        print("⏭ 스킵 (장외/간격미해당)"); return

    print("🔑 토큰 발급 중...")
    token = get_token()
    if not token: print("❌ 토큰 발급 실패"); return

    print("📊 거래량 순위 조회...")
    kospi  = fetch_ranking(token, 'J', 300)
    kosdaq = fetch_ranking(token, 'Q', 100)
    all_s  = kospi + kosdaq
    print(f"KOSPI {len(kospi)} + KOSDAQ {len(kosdaq)} = {len(all_s)}종목")

    if not all_s: print("❌ 결과 없음"); return

    cats = categorize(all_s)

    # Gist 저장 (앱이 즉시 읽음)
    scan_result = {
        'swing':    [build_card(s,'swing')    for s in cats['swing']],
        'surge':    [build_card(s,'surge')    for s in cats['surge']],
        'smallmid': [build_card(s,'smallmid') for s in cats['smallmid']],
        'tomorrow': [],
        'ts': ts, 'total': len(all_s),
        'kospi_n': len(kospi), 'kosdaq_n': len(kosdaq),
        'updated_at': time.time()
    }
    save_to_gist(scan_result)

    if not TG_TOKEN:
        print("⚠ TG_TOKEN 없음 — 텔레그램 전송 건너뜀"); return

    is_market = 9 <= t.hour <= 15

    def build_msg(iv_min):
        iv_lbl = _lbl(iv_min)
        mkt_lbl = '🟢장중' if is_market else '🔴장마감'
        top_main  = (cats['swing']+cats['surge'])[:5]
        top_small = cats['smallmid'][:5]
        if not top_main:
            top_main = sorted(all_s, key=lambda x:x.get('trAmt',0), reverse=True)[:5]
            for s in top_main: s.setdefault('score',75); s.setdefault('grade','B')
        lines = [
            f"📡 <b>K-ALPHA {iv_lbl} 자동 스캔</b> [{ts}] {mkt_lbl}\n"
            f"KOSPI {len(kospi)}종목 + KOSDAQ {len(kosdaq)}종목\n━━━━━━━━━━━━━━━━",
            "🔥 <b>[실시간 스윙/급등 TOP5]</b>" if cats['swing'] else "📊 <b>[거래대금 상위 TOP5]</b>"
        ]
        for s in top_main: lines.append(fmt_tg(s))
        if top_small:
            lines.append("\n⬟ <b>[중소형주 TOP5]</b>")
            for s in top_small: lines.append(fmt_tg(s))
        lines.append(f"━━━━━━━━━━━━━━━━\n📊 {len(all_s)}종목 스캔완료 · 다음 {iv_lbl} 후")
        return "\n\n".join(lines)

    # 개인방 전송
    if send_personal:
        msg_p = build_msg(TG_INTERVAL)
        ok_p = send_telegram(msg_p, TG_CHAT)
        print(f"{'✅ 개인방 전송' if ok_p else '❌ 개인방 실패'}")

    # 그룹방 전송
    if send_group:
        msg_g = build_msg(TG_GROUP_INTERVAL)
        ok_g = send_telegram(msg_g, TG_GROUP_CHAT)
        print(f"{'✅ 그룹방 전송' if ok_g else '❌ 그룹방 실패'}")

    print("✅ 완료")

if __name__ == '__main__':
    main()
