import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import requests, json, os, base64, urllib3, time, math, concurrent.futures
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
def kst_now(): return datetime.now(KST)
def kst_strftime(fmt): return kst_now().strftime(fmt)
urllib3.disable_warnings()

# ── 한국 공휴일 (YYYYMMDD) ──────────────────────────────────────────
_KR_HOLIDAYS = {
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

def is_kr_holiday(dt=None):
    if dt is None: dt = kst_now()
    return dt.strftime('%Y%m%d') in _KR_HOLIDAYS

def is_market_open(dt=None):
    """08:00~15:30 KST, 평일, 비공휴일이면 True"""
    if dt is None: dt = kst_now()
    if dt.weekday() >= 5: return False
    if is_kr_holiday(dt): return False
    total = dt.hour * 60 + dt.minute
    return 480 <= total <= 930  # 08:00(480) ~ 15:30(930)

# ────────────────────────────────────────────────────────────────
# 백그라운드 스캔 + TG 전송 스레드 (브라우저 없이도 자동 실행)
# ────────────────────────────────────────────────────────────────
@st.cache_resource
def _get_bg_state():
    return {"started": False, "last_scan": 0, "tg_bkt": {}}

def _start_bg_scan_thread():
    import threading, requests as _req, json as _jn

    bg = _get_bg_state()
    if bg["started"]:
        return
    bg["started"] = True

    def _send_tg_msg(tok, chat_id, text):
        try:
            _req.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10)
        except: pass

    def _do_tg_send(ss, sr, label):
        """scan_result → 카테고리별 분할 전송"""
        tok  = ss.get("tg_token", "")
        if not tok: return

        rooms = [
            # (chat_id, interval_min, n, enabled)
            (ss.get("tg_chat",""),           ss.get("tg_interval_min",10),     ss.get("tg_send_count_p",5),  True),
            (ss.get("tg_group1_chat","") or ss.get("tg_group_chat",""),
             ss.get("tg_group1_iv_min",10) or ss.get("tg_group_iv_min",10),
             ss.get("tg_send_count_g1",5),
             ss.get("tg_group1_en", False) or ss.get("tg_group_en", False)),
            (ss.get("tg_group2_chat",""),    ss.get("tg_group2_iv_min",10),    ss.get("tg_send_count_g2",5), ss.get("tg_group2_en", False)),
            (ss.get("tg_group3_chat",""),    ss.get("tg_group3_iv_min",10),    ss.get("tg_send_count_g3",5), ss.get("tg_group3_en", False)),
        ]
        now = time.time()
        for i, (chat, iv_min, n_cat, en) in enumerate(rooms):
            if not en or not chat: continue
            bkt = int(now // (iv_min * 60))
            bkt_key = f"r{i}"
            if bkt == bg["tg_bkt"].get(bkt_key, -1): continue  # 이미 전송됨
            bg["tg_bkt"][bkt_key] = bkt

            # 헤더
            ts = kst_strftime("%H:%M:%S")
            sw  = sr.get("swing",   [])[:n_cat]
            su  = sr.get("surge",   [])[:n_cat]
            tm  = sr.get("tomorrow",[])[:n_cat]
            sml = sr.get("smallmid",[])[:n_cat]
            hdr = (f"📡 <b>K-ALPHA {label} 스캔</b> [{ts}] 🟢장중\n"
                   f"KOSPI {sr.get('kospi_n',0)}+KOSDAQ {sr.get('kosdaq_n',0)}종목\n"
                   f"🔥스윙:{len(sw)} ⚡급등:{len(su)} 🌙내일:{len(tm)} 📦중소형:{len(sml)}")
            _send_tg_msg(tok, chat, hdr)
            time.sleep(0.3)

            def _send_cat(lst, emoji, lbl_cat):
                if not lst: return
                TG_LIM = 3800
                total = len(lst); no = 1; buf = []; bl = 0
                for c in lst:
                    card = _bg_fmt_card(c); clen = len(card)+2
                    if buf and bl+clen > TG_LIM:
                        h = f"{emoji} <b>【{lbl_cat} TOP{total}】 — {no}부</b>"
                        _send_tg_msg(tok, chat, h+"\n"+"\n\n".join(buf))
                        time.sleep(0.3); no+=1; buf=[]; bl=0
                    buf.append(card); bl+=clen
                if buf:
                    h = (f"{emoji} <b>【{lbl_cat} TOP{total}】</b>" if no==1
                         else f"{emoji} <b>【{lbl_cat} TOP{total}】 — {no}부</b>")
                    _send_tg_msg(tok, chat, h+"\n"+"\n\n".join(buf))
                    time.sleep(0.3)

            _send_cat(sw,  "🔥", "실시간 스윙")
            _send_cat(su,  "⚡", "급등전야")
            _send_cat(tm,  "🌙", "내일관심")
            _send_cat(sml, "📦", "중소형주")
            _send_tg_msg(tok, chat, f"━━━━━━━━━━━━━━━━\n📊 총 {sr.get('total',0)}종목 스캔완료\n⏱ 다음 전송 {iv_min}분 후")

    def _bg_fmt_card(c):
        try: p = int(str(c.get("price","0")).replace(",",""))
        except: p = 0
        def _i(v,f):
            try: return int(str(v).replace(",",""))
            except: return f
        buy=_i(c.get("buy"),int(p*0.995)); stop=_i(c.get("stop"),int(p*0.97))
        tgt=_i(c.get("target"),int(p*1.10))
        try: rr=float(str(c.get("rr","")).replace(",",""))
        except: rr=0
        if not rr: rr=round((tgt-p)/(p-stop+1),1) if p>0 else 3.3
        vol=c.get("vol",0)
        try: vol=int(vol)
        except: pass
        pct=c.get("change","0%"); score=c.get("score",70); grade=c.get("grade","B")
        rsi=c.get("rsiApprox",50) or 50; mkt=str(c.get("mkt","KOSPI")).upper()
        chg=0.0
        try: chg=float(str(pct).replace("%","").replace("+",""))
        except: pass
        g="🔴" if grade=="S" else ("🟠" if grade=="A" else ("🟡" if grade=="B" else "⚪"))
        if chg>=7: risk="⚠ 급등주의"
        elif chg>=4: risk="📌 눌림대기"
        elif rr<1.5: risk="⚠ RR낮음"
        elif rsi>72: risk=f"⚠ RSI{rsi:.0f}과매수"
        else: risk="✅ 리스크 정상"
        ls=["━"*18,
            f"{g} <b>{c.get('name','')} ({c.get('code','')})</b>  [{mkt}]",
            f"💰 <b>{p:,}원</b>  {pct}  |  거래대금 <b>{vol:,}억</b>",
            f"📊 RSI {rsi:.0f}  |  K점수 <b>{score}점({grade})</b>  |  RR <b>{rr}</b>",
            f"📈 매입가 {buy:,}원  →  목표 {tgt:,}원  |  손절 {stop:,}원", risk]
        reasons=c.get("reasons",[])
        if reasons:
            ls.append(""); ls.append("📋 <b>K 분석 사유</b>")
            for r in reasons:
                ls.append(f"  ▸ {r.get('text','') if isinstance(r,dict) else str(r)}")
        return "\n".join(ls)

    def _run():
        while True:
            try:
                ss   = get_server_store()
                iv   = ss.get("scan_refresh_min") or 10
                elapsed = time.time() - bg["last_scan"]

                if elapsed >= iv * 60 and is_market_open():
                    tok = ss.get("kis_token")
                    gid = _get_secret("GIST_ID")
                    ght = _get_secret("GH_TOKEN")
                    kb  = ss.get("kis_base_url","https://openapi.kis.or.kr")
                    ka  = ss.get("kis_ak","")
                    ks  = ss.get("kis_sec","")

                    if tok and gid and ght:
                        try:
                            import concurrent.futures as _cf
                            with _cf.ThreadPoolExecutor(max_workers=2) as ex:
                                fk = ex.submit(fetch_volume_ranking,tok,kb,ka,ks,"J",200)
                                fd = ex.submit(fetch_volume_ranking,tok,kb,ka,ks,"Q",100)
                                kp = fk.result(); kd = fd.result()
                            all_s = kp + kd
                            if all_s:
                                ui_n = ss.get("ui_n_per_cat") or 10
                                cats = categorize_stocks(
                                    all_s,
                                    ss.get("scan_blacklist", set()),
                                    ss.get("scan_vol_min") or 50,
                                    ss.get("scan_rsi_min") or 20,
                                    ss.get("scan_rsi_max") or 75,
                                    top_n=min(50, ui_n*3),
                                )
                                _ts = kst_strftime("%H:%M:%S")
                                sr = {
                                    "swing":    [build_card(s,"swing")    for s in cats["swing"]],
                                    "surge":    [build_card(s,"surge")    for s in cats["surge"]],
                                    "tomorrow": [build_card(s,"tomorrow") for s in cats["tomorrow"]],
                                    "smallmid": [build_card(s,"smallmid") for s in cats["smallmid"]],
                                    "ts":_ts,"total":len(all_s),
                                    "kospi_n":len(kp),"kosdaq_n":len(kd),
                                    "updated_at":time.time(),"market_open":True,
                                }
                                sj = _jn.dumps(sr, ensure_ascii=False)
                                r = _req.patch(
                                    f"https://api.github.com/gists/{gid}",
                                    headers={"Authorization":f"token {ght}",
                                             "Accept":"application/vnd.github.v3+json"},
                                    json={"files":{"kalpha_scan.json":{"content":sj}}},
                                    timeout=15)
                                if r.status_code == 200:
                                    ss["scan_result"] = sr
                                    ss["scan_ts"] = time.time()
                                    bg["last_scan"] = time.time()
                                    try: fetch_gist_scan.clear()
                                    except: pass
                                    # 스캔 직후 TG 전송
                                    iv_lbl = f"{iv}분"
                                    _do_tg_send(ss, sr, iv_lbl)
                        except Exception:
                            pass
            except Exception:
                pass
            time.sleep(30)  # 30초마다 경과 체크

    import threading
    threading.Thread(target=_run, daemon=True).start()


def _get_secret(key, default=''):
    """Streamlit secrets 또는 환경변수에서 값 읽기"""
    try:
        v = st.secrets.get(key, '')
        if v: return str(v)
    except: pass
    return os.environ.get(key, default)


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
  /* 모든 라벨/텍스트 가시성 강화 */
  label, label p, .stSlider label, .stSlider label p,
  .stNumberInput label, .stCheckbox label, .stToggle label,
  div[data-testid="stMarkdownContainer"] p,
  .stMarkdown p, .stCaption p,
  div[data-baseweb="tab"] span {
    color:#c8d6e5!important;
  }
  .stMarkdown h3, .stMarkdown h4, .stMarkdown strong, b {
    color:#e2e8f0!important;
  }
  div[data-testid="stTabs"] button[role="tab"] {
    color:#94a3b8!important;
    font-size:13px!important;
  }
  div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color:#00d4ff!important;
  }
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
    # 화면 갱신 주기 (Gist 폴링 — 텔레그램과 무관)
    "scan_refresh_min": 10,
    # 텔레그램 — 전체 발송 ON/OFF
    "tg_all_enabled": True,
    # 텔레그램 — 개인방
    "tg_token":"","tg_chat":"","tg_interval_min":10,"tg_interval_label":"10분",
    # 텔레그램 — 그룹방
    "tg_group_chat":"","tg_group_enabled":False,
    "tg_group_interval_min":30,"tg_group_interval_label":"30분",
    "scan_blacklist":[],"scan_vol_min":50,"scan_rsi_min":20,"scan_rsi_max":75,
    "scan_swing_vol_min":100,"scan_swing_pct_min":0.3,"scan_swing_pct_max":6.0,
    "scan_surge_pct_min":4.0,
    "scan_tomorrow_pct_min":-2.0,"scan_tomorrow_pct_max":2.5,
    "scan_smallmid_vol_min":50,"scan_smallmid_vol_max":700,
    "scan_smallmid_pct_min":-2.0,"scan_smallmid_pct_max":4.0,
    # 텔레그램 — 그룹방 2
    "tg_group2_chat":"","tg_group2_enabled":False,
    "tg_group2_interval_min":30,"tg_group2_interval_label":"30분",
    # 텔레그램 — 그룹방 3
    "tg_group3_chat":"","tg_group3_enabled":False,
    "tg_group3_interval_min":30,"tg_group3_interval_label":"30분",
    # Google AI Studio (Gemini)
    "google_api_key":"",
    # 텔레그램 AI 분석 전송 갯수 (전체 기본값 + 채팅방별)
    "tg_ai_count": 10,
    "tg_ai_count_p": 10, "tg_ai_count_g1": 10, "tg_ai_count_g2": 10, "tg_ai_count_g3": 10,
    # AI 분석 전송 여부 (개인방 포함)
    "tg_ai_send_p":  True,
    "tg_ai_send_g1": False, "tg_ai_send_g2": False, "tg_ai_send_g3": False,
    # 송출 시간 범위 (KST 시 단위, 기본 09~15시)
    "tg_send_start_p": 9,  "tg_send_end_p": 15,
    "tg_send_start_g1": 9, "tg_send_end_g1": 15,
    "tg_send_start_g2": 9, "tg_send_end_g2": 15,
    "tg_send_start_g3": 9, "tg_send_end_g3": 15,
}
for k,v in DEFAULTS.items():
    if k not in st.session_state: st.session_state[k]=v

# ── 서버 메모리 저장소 (같은 프로세스 내 재시작에도 유지) ──
@st.cache_resource
def get_server_store():
    return {"ck": None, "cp": None, "tg": None, "tg_grp": None,
            "tg_grp2": None, "tg_grp3": None, "agreed": False,
            "scan_data": None, "scan_ts": 0, "scan_str": "",
            "google_key": None}

server_store = get_server_store()
# 공유 설정 PC ↔ Mobile 복원
_SYNC_KEYS = ['scan_refresh_min','scan_vol_min','scan_rsi_min','scan_rsi_max',
              'scan_swing_vol_min','scan_swing_pct_min','scan_swing_pct_max',
              'scan_tomorrow_pct_min','scan_tomorrow_pct_max',
              'tg_all_enabled',
              'tg_ai_count_p','tg_ai_count_g1','tg_ai_count_g2','tg_ai_count_g3',
              'tg_send_count_p','tg_send_count_g1','tg_send_count_g2','tg_send_count_g3',
              'ui_n_per_cat',
              'tg_ai_send_p','tg_ai_send_g1','tg_ai_send_g2','tg_ai_send_g3',
              'tg_send_start_p','tg_send_end_p',
              'tg_send_start_g1','tg_send_end_g1',
              'tg_send_start_g2','tg_send_end_g2',
              'tg_send_start_g3','tg_send_end_g3']
if not st.session_state.get('_synced'):
    for _sk, _sv in (server_store.get('ss') or {}).items():
        if _sk in _SYNC_KEYS:
            st.session_state[_sk] = _sv
    st.session_state['_synced'] = True

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
if qp.get("no_pin")=="1" or server_store.get("no_pin")=="1": st.session_state.use_pin = False
if qp.get("auto_conn")=="1": st.session_state.auto_connect = True
if not st.session_state.use_pin: st.session_state.auth = True

# 텔레그램 복원 — 개인방
if qp.get("tg") and not st.session_state.get("tg_token"):
    try:
        tg_data = json.loads(base64.b64decode(qp.get("tg","")).decode())
        st.session_state["tg_token"] = tg_data.get("t","")
        st.session_state["tg_chat"]  = tg_data.get("c","")
    except: pass

# 텔레그램 복원 — 그룹방 (qp 없으면 server_store 폴백)
_tg_grp_src = qp.get("tg_grp") or server_store.get("tg_grp","")
if _tg_grp_src and not st.session_state.get("tg_group_chat"):
    try:
        tg_grp = json.loads(base64.b64decode(_tg_grp_src).decode())
        st.session_state["tg_group_chat"]             = tg_grp.get("c","")
        st.session_state["tg_group_enabled"]          = tg_grp.get("en", False)
        st.session_state["tg_group_interval_min"]     = tg_grp.get("iv", 30)
        st.session_state["tg_group_interval_label"]   = tg_grp.get("ivl","30분")
        if not qp.get("tg_grp"): qp["tg_grp"] = _tg_grp_src
    except: pass

# 텔레그램 복원 — 그룹방 2
_tg_grp2_src = qp.get("tg_grp2") or server_store.get("tg_grp2","")
if _tg_grp2_src and not st.session_state.get("tg_group2_chat"):
    try:
        tg_grp2 = json.loads(base64.b64decode(_tg_grp2_src).decode())
        st.session_state["tg_group2_chat"]           = tg_grp2.get("c","")
        st.session_state["tg_group2_enabled"]        = tg_grp2.get("en", False)
        st.session_state["tg_group2_interval_min"]   = tg_grp2.get("iv", 30)
        st.session_state["tg_group2_interval_label"] = tg_grp2.get("ivl","30분")
        if not qp.get("tg_grp2"): qp["tg_grp2"] = _tg_grp2_src
    except: pass

# 텔레그램 복원 — 그룹방 3
_tg_grp3_src = qp.get("tg_grp3") or server_store.get("tg_grp3","")
if _tg_grp3_src and not st.session_state.get("tg_group3_chat"):
    try:
        tg_grp3 = json.loads(base64.b64decode(_tg_grp3_src).decode())
        st.session_state["tg_group3_chat"]           = tg_grp3.get("c","")
        st.session_state["tg_group3_enabled"]        = tg_grp3.get("en", False)
        st.session_state["tg_group3_interval_min"]   = tg_grp3.get("iv", 30)
        st.session_state["tg_group3_interval_label"] = tg_grp3.get("ivl","30분")
        if not qp.get("tg_grp3"): qp["tg_grp3"] = _tg_grp3_src
    except: pass

# Google API key restore
_gkey_src = qp.get("gkey") or server_store.get("google_key", "")
if _gkey_src and not st.session_state.get("google_api_key"):
    try:
        _gkey = base64.b64decode(_gkey_src).decode()
        st.session_state["google_api_key"] = _gkey
        if not qp.get("gkey"): qp["gkey"] = _gkey_src
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

@st.cache_data(ttl=600, show_spinner=False)   # 10분 캐시 — Gist는 10분마다 갱신
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
                time.sleep(0.04)
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

def categorize_stocks(all_stocks, blacklist, vol_min, rsi_min, rsi_max,
                      swing_vol_min=100, swing_pct_min=0.3, swing_pct_max=6.0,
                      surge_pct_min=4.0,
                      tomorrow_pct_min=-2.0, tomorrow_pct_max=2.5,
                      smallmid_vol_min=50, smallmid_vol_max=700,
                      smallmid_pct_min=-2.0, smallmid_pct_max=4.0,
                      top_n=50):
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
        #    - 거래대금 100억 이상 (수급 확인)
        #    - 등락률 +0.3%~+6% (과열 아닌 모멘텀)
        # ════════════════════════════════════════════
        _sw_vol_grade_min = 1 if swing_vol_min <= 100 else (2 if swing_vol_min <= 300 else 3)
        if proximity_ok and swing_pct_min <= pct <= swing_pct_max and vol_grade >= _sw_vol_grade_min:
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
        if pct >= surge_pct_min and vol_grade >= 1:
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
        if tomorrow_pct_min <= pct <= tomorrow_pct_max and tr >= 50:
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
        if smallmid_vol_min <= tr <= smallmid_vol_max and smallmid_pct_min <= pct <= smallmid_pct_max:
            # 대형주 제외: KOSPI 종목 중 가격 50,000원 초과 or 거래대금 400억 초과는 대형주로 간주
            _is_kospi_largecap = (s.get('mkt','kospi') == 'kospi' and
                                  (price > 50000 or tr > 400))
            if not _is_kospi_largecap:
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
        'swing':    top(swing, top_n),
        'surge':    top(surge, top_n),
        'tomorrow': top(tomorrow, top_n),
        'smallmid': top(smallmid, top_n),
    }

def _build_analysis_reasons(s, chg, buy_p, stop_p, tgt_p):
    """기술적 분석 + 기본적 분석(기업 내부) + 외부요인(거시경제·산업) 사유"""
    tr    = s.get('trAmt', 0)
    price = s.get('price', 0)
    mkt   = s.get('mkt', 'kospi')
    sign  = '+' if chg >= 0 else ''
    rsi   = s.get('rsiApprox', round(50 + chg * 2.8, 1))

    # ── 기술적 분석 ──
    tech = [
        {'icon':'◈','cat':'green',
         'text':f"거래대금 {tr:,}억 · 거래량순위 상위 종목"},
        {'icon':'◉','cat':'',
         'text':f"등락률 {sign}{chg:.2f}% · RSI 추정 {rsi:.0f}"},
        {'icon':'▲','cat':'orange',
         'text':f"매입가 {buy_p:,}원 → 목표 {tgt_p:,}원 · 손절 {stop_p:,}원"},
    ]

    # ── 기본적 분석 — 기업 내부 요인 ──
    fund = []
    if tr >= 2000:   fund.append("기관·외국인 대규모 순매수 추정 (거래대금 2,000억+)")
    elif tr >= 800:  fund.append("기관 매수세 유입 추정 (거래대금 800억+)")
    elif tr >= 300:  fund.append("외국인·기관 중형 수급 진입 추정")
    else:            fund.append("개인 중심 수급 · 단기 모멘텀 주도")

    if chg >= 8:    fund.append("실적 서프라이즈 또는 긍정적 공시 가능성")
    elif chg >= 4:  fund.append("단기 실적 개선·사업 확장 뉴스 반응")
    elif chg >= 1:  fund.append("점진적 실적 개선 기대 · MA 상향 돌파 시도")
    elif chg >= -1: fund.append("횡보 구간 · 저점 매집 가능성")
    else:           fund.append("단기 조정 · 피보나치 지지선 반등 대기")

    if mkt == 'kospi': fund.append("KOSPI 대형주 · 안정적 실적 기반 · 배당 가능성")
    else:              fund.append("KOSDAQ 중소형주 · 고성장 섹터 · 변동성 주의")

    # ── 외부요인 분석 — 거시경제·산업 환경 ──
    macro = []
    h = kst_now().hour
    if 8 <= h < 9:    macro.append("프리마켓 구간 · 미국 선물·뉴스 반영 초기")
    elif 9 <= h < 11: macro.append("오전 장 · 외국인·기관 방향성 확인 구간")
    elif 11 <= h < 13:macro.append("점심 전후 · 유동성 감소 · 단기 변동성 주의")
    else:             macro.append("오후 장 · 프로그램 매매·수급 정리 구간")

    if tr >= 1000:   macro.append("시장 전체 활성화 · 외국인 관심 업종 추정")
    elif tr >= 300:  macro.append("업종 테마 수급 집중 · 정책·뉴스 모멘텀")
    else:            macro.append("개별 재료 중심 움직임")

    if chg >= 3:    macro.append("금리·환율 우호 또는 섹터 호재 반응")
    elif chg <= -3: macro.append("글로벌 리스크오프 또는 섹터 악재 가능성")
    else:           macro.append("관망세 · 미국 FOMC·환율 방향성 주시")

    return tech + [
        {'icon':'🏢','cat':'blue',
         'text':'[기본적 분석] ' + ' · '.join(fund)},
        {'icon':'🌐','cat':'purple',
         'text':'[외부요인] ' + ' · '.join(macro)},
    ]

def build_card(s, cat):
    """카드 데이터 포맷팅 (기본적 분석 + 외부요인 포함)"""
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
        'reasons': _build_analysis_reasons(s, chg, buy_p, stop_p, tgt_p),
        'inds': [
            {'label':s.get('mkt','KOSPI').upper(),'cat':'green'},
            {'label':f"RR {rr}",'cat':''},
            {'label':f"거래대금 {s.get('trAmt',0):,}억",'cat':'orange'},
        ],
        'chart3m': [], 'chartD': [], 'cat': cat,
    }

def _gemini_brief(code, name, price_s, chg_s, score, grade, vol_i, buy_s, stop_s, rr_s):
    """Gemini AI 간략 분석 (시간당 세션 캐시). None 반환 시 생략."""
    gkey = st.session_state.get('google_api_key', '')
    if not gkey: return None
    cache = st.session_state.setdefault('_ai_brief_cache', {})
    ck = f"{code}_{kst_now().strftime('%Y%m%d%H')}"
    if ck in cache: return cache[ck]
    # 쿼터 초과 쿨다운 (채널별 공유)
    quota_until = st.session_state.get('_gemini_quota_until', 0)
    if time.time() < quota_until: return None
    try: vol_fmt = f"{int(vol_i):,}억"
    except: vol_fmt = str(vol_i)
    msg = (f"종목: {name}({code})\n현재가: {price_s}원 등락: {chg_s}\n"
           f"K점수: {score}점({grade}) 거래대금: {vol_fmt}\n"
           f"매입가: {buy_s}원 손절: {stop_s}원 RR: {rr_s}\n\n"
           "스윙 관점 간결 분석(한국어, 항목당 1-2줄):\n"
           "1) 종합매력도X점/100-이유\n2) 핵심강점\n3) 주요리스크\n4) 매매전략")
    for attempt in range(3):
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gkey}",
                json={"system_instruction":{"parts":[{"text":"너는 스윙 매매 전문가다. 반드시 한국어, 간결(200자 이내)."}]},
                      "contents":[{"role":"user","parts":[{"text":msg}]}],
                      "generationConfig":{"maxOutputTokens":300,"temperature":0.7}},
                timeout=15
            )
            data = r.json()
            # 쿼터/레이트 리밋 오류 감지
            err = data.get('error', {})
            if err.get('code') in (429, 503) or 'quota' in str(err).lower() or 'rate' in str(err).lower():
                # retry-after 파싱 (메시지에서 숫자 초 추출, 없으면 60초)
                import re as _re
                m = _re.search(r'retry in ([\d.]+)s', str(err))
                wait = float(m.group(1)) if m else 60.0
                st.session_state['_gemini_quota_until'] = time.time() + wait + 5
                return None
            t = (data.get('candidates',[{}])[0]
                 .get('content',{}).get('parts',[{}])[0].get('text',''))
            if t:
                cache[ck] = t.strip()[:450]
                return cache[ck]
            break
        except Exception:
            if attempt < 2:
                time.sleep(2 ** attempt)
    return None


def _send_tg_ai(bot_token, chat_id, stocks, label, ts):
    """AI 분석 메시지 생성 후 텔레그램 전송 (Gist 카드 / KIS raw stock 모두 처리)."""
    if not bot_token or not chat_id or not stocks: return
    gkey = st.session_state.get('google_api_key', '')
    quota_until = st.session_state.get('_gemini_quota_until', 0)

    def _ai_one(x):
        try:
            if 'changePct' in x:
                _pr = x.get('price', 0)
                pct = x.get('changePct', 0); sign = '+' if pct >= 0 else ''
                card = build_card(x, 'swing')
                return _gemini_brief(x['code'], x['name'], f"{int(_pr):,}", f"{sign}{pct:.2f}%",
                                     x.get('score',70), x.get('grade','B'), x.get('trAmt',0),
                                     card['buy'], card['stop'], card['rr'])
            else:
                return _gemini_brief(x.get('code',''), x.get('name',''),
                                     str(x.get('price','?')), str(x.get('change','?')),
                                     x.get('score',70), x.get('grade','B'),
                                     x.get('vol', x.get('trAmt',0)),
                                     str(x.get('buy','?')), str(x.get('stop','?')), str(x.get('rr','?')))
        except: return None

    ai_lines = [f"🤖 <b>AI 심층 분석</b> [{label}·{ts}]\n━━━━━━━━━━━━━━━━"]

    if not gkey:
        # API 키 미설정 — 종목 목록만 발송
        for x in stocks:
            ai_lines.append(f"🔵 <b>{x.get('name','')} ({x.get('code','')})</b>\n⚙ Gemini API 키 미설정 · 앱 설정에서 입력하세요")
    elif time.time() < quota_until:
        # 쿼터 쿨다운 — 남은 시간 표시
        remain = max(0, int(quota_until - time.time()))
        ai_lines.append(f"⏱ API 일일 한도 초과 · 약 {remain//60}분 후 재시도 예정")
        for x in stocks:
            ai_lines.append(f"🔵 <b>{x.get('name','')} ({x.get('code','')})</b>\n— 한도 초과로 분석 생략")
    else:
        # 직렬 호출 (레이트 리밋 방지: 요청 사이 1초 간격)
        results = []
        for x in stocks:
            results.append(_ai_one(x))
            if time.time() < st.session_state.get('_gemini_quota_until', 0):
                break  # 쿼터 초과 감지 시 나머지 스킵
            time.sleep(1)
        for x, text in zip(stocks, results):
            name = x.get('name',''); code = x.get('code','')
            ai_lines.append(f"🔵 <b>{name} ({code})</b>\n{text or '— AI 분석 대기 중'}")

    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id":chat_id,"text":"\n\n".join(ai_lines)[:4000],"parse_mode":"HTML"},
            timeout=10
        )
    except: pass


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
    _agree_cb = st.checkbox("위 내용을 확인하였으며 동의합니다", key="agree_cb")
    c1,c2=st.columns(2)
    with c1:
        if st.button("✗ 동의하지 않음", use_container_width=True): st.warning("동의가 필요합니다.")
    with c2:
        if st.button("✓ 동의하고 시작", use_container_width=True, type="primary", disabled=not _agree_cb):
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

    # ── 1. 면책조항 + 체크박스 (PIN 위에 표시) ──────
    st.markdown("""<div style="background:#0a0e1a;border:1px solid rgba(255,165,0,0.35);
border-radius:10px;padding:12px 14px;margin-bottom:6px;font-family:'Share Tech Mono',monospace">
  <div style="color:#ffc800;font-size:11px;font-weight:700;margin-bottom:8px">⚠ 투자 위험 고지 및 면책 조항</div>
  <div style="font-size:10px;color:#64748b;line-height:1.9">
    • 개발자는 투자 결과에 대해 <b style="color:#ff4d6d">일체의 법적 책임을 지지 않습니다</b><br>
    • 모든 분석·신호는 <b style="color:#ffc800">참고 목적</b>이며 결과를 보장하지 않습니다<br>
    • <b style="color:#ff4d6d">원금 손실 위험</b>이 있으며 최종 판단은 <b style="color:#e2e8f0">이용자 본인</b>에게 있습니다<br>
    • 한국투자증권과 <b style="color:#ffc800">무관한 독립 개인 개발 도구</b>입니다
  </div>
</div>""", unsafe_allow_html=True)
    _pin_discl = st.checkbox("위 면책 조항에 동의합니다", key="_pin_discl_cb")
    if not _pin_discl:
        st.caption("🔒 동의 체크 후 PIN 입력이 활성화됩니다.")
        with st.expander("⚙ PIN 설정 (해제 / 변경)", expanded=False):
            st.caption("면책 조항에 먼저 동의하세요.")
        st.stop()

    # ── 2. K·ALPHA 타이틀 + PIN 입력 ─────────────
    dots=''.join([f'<div style="width:12px;height:12px;border-radius:50%;'
        +(f'background:#00d4ff;border:2px solid #00d4ff;">' if i<len(buf) else 'border:2px solid #1a3a4a;background:transparent">')
        +'</div>' for i in range(4)])
    st.markdown(f"""<div style="text-align:center;padding:16px 0 14px;font-family:'Share Tech Mono',monospace">
  <div style="font-size:clamp(22px,7vw,40px);font-weight:700;letter-spacing:6px;
    background:linear-gradient(90deg,#00d4ff,#00ff88);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px">K · ALPHA</div>
  <div style="font-size:11px;color:#4a5568;letter-spacing:2px;margin-bottom:16px">SECURE ACCESS</div>
  <div style="background:#0a0e1a;border:1px solid #1a2535;border-radius:16px;padding:18px 20px 12px;width:min(280px,86vw);margin:0 auto">
    <div style="font-size:10px;color:#4a5568;margin-bottom:10px">🔒 PIN 번호 입력</div>
    <div style="display:flex;justify-content:center;gap:14px;margin-bottom:12px">{dots}</div>
    {'<div style="color:#ff4d6d;font-size:11px">❌ 비밀번호가 틀렸습니다</div>' if err else ''}
  </div>
</div>""", unsafe_allow_html=True)

    # ── 3. 숫자 키패드 ────────────────────────────
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

    # ── 4. PIN 설정 (해제 / 변경) ─────────────────
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    with st.expander("⚙ PIN 설정 (해제 / 변경)", expanded=False):
        st.caption("현재 PIN을 입력한 후 사용 해제 또는 새 PIN으로 변경하세요.")
        _cur_pin_inp = st.text_input("현재 PIN", type="password", max_chars=4,
                                      placeholder="현재 4자리", key="pin_cur_inp")

        _pin_mode = st.radio("해제 방식",
                             ["🔓 이번만 해제 (PIN 계속 유지)", "🔑 영구 해제 (다음부터 PIN 불필요)"],
                             horizontal=True, key="pin_mode_radio")

        pc1, pc2 = st.columns(2)
        with pc1:
            if st.button("확인", key="btn_pin_disable", use_container_width=True):
                if _cur_pin_inp == PASSWORD:
                    if "영구 해제" in _pin_mode:
                        st.session_state.use_pin = False
                        qp['no_pin'] = '1'
                        server_store['no_pin'] = '1'
                        try: del qp['cp']
                        except: pass
                        st.success("✅ PIN이 영구 해제됐습니다.")
                    else:
                        st.success("✅ 이번만 해제됐습니다. 다음 접속 시 PIN이 필요합니다.")
                    st.session_state.auth = True
                    st.rerun()
                else:
                    st.error("❌ PIN이 틀렸습니다")

        st.divider()
        st.markdown("**🔑 PIN 변경**")
        _new_pin  = st.text_input("새 PIN",      type="password", max_chars=4,
                                   placeholder="새 4자리", key="pin_new_inp")
        _new_pin2 = st.text_input("새 PIN 확인", type="password", max_chars=4,
                                   placeholder="새 4자리 재입력", key="pin_new2_inp")
        with pc2:
            pass  # layout placeholder
        if st.button("💾 PIN 변경 저장", key="btn_pin_chg", use_container_width=True):
            if _cur_pin_inp != PASSWORD:
                st.error("❌ 현재 PIN이 틀렸습니다")
            elif len(_new_pin) != 4 or not _new_pin.isdigit():
                st.error("❌ 새 PIN은 숫자 4자리여야 합니다")
            elif _new_pin != _new_pin2:
                st.error("❌ 새 PIN이 일치하지 않습니다")
            else:
                server_store['app_pin'] = _new_pin
                if qp.get('ck'):
                    try:
                        _d = py_load(qp['ck'], PASSWORD)
                        _new_ck = py_save(_d['ak'], _d['sec'], _d['acc'], _d.get('env','실전투자'), _new_pin)
                        qp['ck'] = _new_ck; server_store['ck'] = _new_ck
                        _new_cp = base64.b64encode((_new_pin+':kalpha').encode()).decode()
                        qp['cp'] = _new_cp; server_store['cp'] = _new_cp
                    except: pass
                st.success(f"✅ PIN이 {_new_pin}으로 변경됐습니다.")
                st.rerun()

    st.stop()

# ════ 3. 자동 새로고침 ════
# Gist 모드: auth만 있으면 동작 (kis_token 없어도 됨 — 백그라운드 스캔 결과 보기 전용)
# 직접KIS 모드: kis_token 필요
# 자동 갱신: 장중(08:00~15:30)에만 / 장외에는 수동 갱신만
_has_gist    = bool(_get_secret('GIST_ID'))
_mkt_open    = is_market_open()
_can_refresh = st.session_state.auth and (_has_gist or st.session_state.kis_token) and _mkt_open

if _can_refresh:
    GIST_ID_ENV  = _get_secret('GIST_ID')
    _ref_min     = st.session_state.get('scan_refresh_min', 10)
    _autorefresh_ms = max(1, _ref_min) * 60 * 1000
    st_autorefresh(interval=_autorefresh_ms, limit=None, key="auto_scan_refresh")
else:
    # 장외/주말/공휴일: 자동 갱신 중단 (수동 ↻ 버튼만 허용)
    _has_gist = bool(_get_secret('GIST_ID'))

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
                if not use_pin:
                    qp['no_pin']='1'
                    server_store['no_pin']='1'
                else:
                    try: del qp['no_pin']
                    except: pass
                    server_store.pop('no_pin', None)
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

        # ── 화면 갱신 주기 ──────────────────────
        _gist_on = bool(_get_secret('GIST_ID'))
        if _gist_on:
            st.markdown(
                '<div style="font-family:monospace;font-size:11px;color:#00d4ff;'
                'padding:6px 10px;background:rgba(0,212,255,0.06);'
                'border:1px solid rgba(0,212,255,0.2);border-radius:6px">'
                '⚡ <b>Gist 백그라운드 모드</b> — GitHub Actions가 자동 스캔·저장<br>'
                '앱은 설정 주기마다 Gist를 읽어 즉시 표시합니다.'
                '</div>', unsafe_allow_html=True)

        _rv_cur = st.session_state.get('scan_refresh_min', 10)
        _rv_new = st.slider(
            "⟳ 자동 스캔 주기 (분)",
            min_value=1, max_value=60,
            value=_rv_cur, step=1,
            key="rv_slider",
            help="앱 화면 갱신 및 GitHub Actions 스캔 주기 (1~60분)")
        st.session_state['scan_refresh_min'] = _rv_new
        st.caption(f"현재 설정: {_rv_new}분마다 자동 스캔 · GitHub Actions 저장 버튼으로 적용")

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
        with st.expander("📊 카테고리별 스캔 조건 설정", expanded=False):
            st.caption("기존 조건을 유지하면서 조정할 수 있습니다.")

            st.markdown("**① 실시간스윙**")
            st.caption("원래 기준: 거래대금 100억+ | 등락률 +0.3%~+6.0%")
            _sw_vol = st.number_input("최소 거래대금 (억원)", min_value=10, max_value=5000,
                value=st.session_state.scan_swing_vol_min, step=10, key="inp_sw_vol")
            st.session_state.scan_swing_vol_min = _sw_vol
            _sw_c1, _sw_c2 = st.columns(2)
            with _sw_c1:
                _sw_pmin = st.number_input("등락률 최소 (%)", min_value=-5.0, max_value=10.0,
                    value=float(st.session_state.scan_swing_pct_min), step=0.1, format="%.1f", key="inp_sw_pmin")
                st.session_state.scan_swing_pct_min = _sw_pmin
            with _sw_c2:
                _sw_pmax = st.number_input("등락률 최대 (%)", min_value=0.0, max_value=30.0,
                    value=float(st.session_state.scan_swing_pct_max), step=0.1, format="%.1f", key="inp_sw_pmax")
                st.session_state.scan_swing_pct_max = _sw_pmax

            st.markdown("**② 급등전야**")
            st.caption("원래 기준: 등락률 +4.0%+")
            _su_pmin = st.number_input("등락률 최소 (%)", min_value=0.0, max_value=20.0,
                value=float(st.session_state.scan_surge_pct_min), step=0.5, format="%.1f", key="inp_su_pmin")
            st.session_state.scan_surge_pct_min = _su_pmin

            st.markdown("**③ 내일관심**")
            st.caption("원래 기준: 등락률 -2.0%~+2.5%")
            _tm_c1, _tm_c2 = st.columns(2)
            with _tm_c1:
                _tm_pmin = st.number_input("등락률 최소 (%)", min_value=-10.0, max_value=0.0,
                    value=float(st.session_state.scan_tomorrow_pct_min), step=0.5, format="%.1f", key="inp_tm_pmin")
                st.session_state.scan_tomorrow_pct_min = _tm_pmin
            with _tm_c2:
                _tm_pmax = st.number_input("등락률 최대 (%)", min_value=0.0, max_value=10.0,
                    value=float(st.session_state.scan_tomorrow_pct_max), step=0.5, format="%.1f", key="inp_tm_pmax")
                st.session_state.scan_tomorrow_pct_max = _tm_pmax

            st.markdown("**④ 중소형주**")
            st.caption("원래 기준: 거래대금 50억~700억 | 등락률 -2.0%~+4.0%")
            _sm_c1, _sm_c2 = st.columns(2)
            with _sm_c1:
                _sm_vmin = st.number_input("거래대금 최소 (억원)", min_value=10, max_value=5000,
                    value=st.session_state.scan_smallmid_vol_min, step=10, key="inp_sm_vmin")
                st.session_state.scan_smallmid_vol_min = _sm_vmin
            with _sm_c2:
                _sm_vmax = st.number_input("거래대금 최대 (억원)", min_value=50, max_value=10000,
                    value=st.session_state.scan_smallmid_vol_max, step=50, key="inp_sm_vmax")
                st.session_state.scan_smallmid_vol_max = _sm_vmax
            _sm_p1, _sm_p2 = st.columns(2)
            with _sm_p1:
                _sm_pmin = st.number_input("등락률 최소 (%)", min_value=-10.0, max_value=0.0,
                    value=float(st.session_state.scan_smallmid_pct_min), step=0.5, format="%.1f", key="inp_sm_pmin")
                st.session_state.scan_smallmid_pct_min = _sm_pmin
            with _sm_p2:
                _sm_pmax = st.number_input("등락률 최대 (%)", min_value=0.0, max_value=20.0,
                    value=float(st.session_state.scan_smallmid_pct_max), step=0.5, format="%.1f", key="inp_sm_pmax")
                st.session_state.scan_smallmid_pct_max = _sm_pmax

            if st.button("↩ 조건 초기화 (원래 기준으로)", key="btn_scan_reset", use_container_width=True):
                st.session_state.scan_swing_vol_min = 100
                st.session_state.scan_swing_pct_min = 0.3
                st.session_state.scan_swing_pct_max = 6.0
                st.session_state.scan_surge_pct_min = 4.0
                st.session_state.scan_tomorrow_pct_min = -2.0
                st.session_state.scan_tomorrow_pct_max = 2.5
                st.session_state.scan_smallmid_vol_min = 50
                st.session_state.scan_smallmid_vol_max = 700
                st.session_state.scan_smallmid_pct_min = -2.0
                st.session_state.scan_smallmid_pct_max = 4.0
                st.rerun()

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

    if st.button("💾 API 키만 저장 (연결 없이)", use_container_width=True, key="btn_kis_save_only"):
        if not ak or not sec or not acc:
            st.error("앱키 / 시크릿 / 계좌번호를 모두 입력하세요")
        else:
            ck_v = py_save(ak, sec, acc, env_label, PASSWORD)
            qp['ck'] = ck_v
            server_store['ck'] = ck_v
            st.session_state.kis_ak  = ak
            st.session_state.kis_sec = sec
            st.session_state.kis_acc = acc
            st.session_state.kis_env = env_label
            st.success("✅ API 키 저장됨 (연결 확인 없음)")

    st.divider()

    # ── 📱 텔레그램 ──────────────────────────────
    with st.expander("📱 텔레그램 알림 설정", expanded=False):

        # ── 전체 발송 ON/OFF ──────────────────────────
        _all_en = st.toggle(
            "📡 메시지 발송 ON/OFF",
            value=st.session_state.get('tg_all_enabled', True),
            key="tog_tg_all",
            help="끄면 앱과 GitHub Actions 모두 전송 중단")
        st.session_state['tg_all_enabled'] = _all_en
        if not _all_en:
            st.warning("⛔ 전송 비활성화 — 모든 채팅방으로 메시지가 발송되지 않습니다.", icon="🔕")
        else:
            st.success("✅ 전송 활성화", icon="📡")

        # ── GitHub Actions 설정 동기화 ────────────────
        def _save_cfg_to_gist():
            _gid = _get_secret('GIST_ID')
            _ght = _get_secret('GH_TOKEN')
            if not _gid or not _ght:
                return False, 'GIST_ID / GH_TOKEN 환경변수 없음'
            cfg = {
                'tg_all_enabled':        st.session_state.get('tg_all_enabled', True),
                'scan_refresh_min':      st.session_state.get('scan_refresh_min', 10),
                'tg_interval_min':       st.session_state.get('tg_interval_min', 10),
                'tg_send_start_p':       st.session_state.get('tg_send_start_p', 9),
                'tg_send_end_p':         st.session_state.get('tg_send_end_p', 15),
                # 그룹방 1
                'tg_group_enabled':      st.session_state.get('tg_group_enabled', False),
                'tg_group_chat':         st.session_state.get('tg_group_chat', ''),
                'tg_group_interval_min': st.session_state.get('tg_group_interval_min', 10),
                'tg_send_start_g1':      st.session_state.get('tg_send_start_g1', 9),
                'tg_send_end_g1':        st.session_state.get('tg_send_end_g1', 15),
                # 그룹방 2
                'tg_group2_enabled':     st.session_state.get('tg_group2_enabled', False),
                'tg_group2_chat':        st.session_state.get('tg_group2_chat', ''),
                'tg_group2_interval_min':st.session_state.get('tg_group2_interval_min', 10),
                'tg_send_start_g2':      st.session_state.get('tg_send_start_g2', 9),
                'tg_send_end_g2':        st.session_state.get('tg_send_end_g2', 15),
                # 그룹방 3
                'tg_group3_enabled':     st.session_state.get('tg_group3_enabled', False),
                'tg_group3_chat':        st.session_state.get('tg_group3_chat', ''),
                'tg_group3_interval_min':st.session_state.get('tg_group3_interval_min', 10),
                'tg_send_start_g3':      st.session_state.get('tg_send_start_g3', 9),
                'tg_send_end_g3':        st.session_state.get('tg_send_end_g3', 15),
                # 채팅방별 종목 수
                'tg_ai_count_p':         st.session_state.get('tg_ai_count_p', 10),
                'tg_ai_count_g1':        st.session_state.get('tg_ai_count_g1', 10),
                'tg_ai_count_g2':        st.session_state.get('tg_ai_count_g2', 10),
                'tg_ai_count_g3':        st.session_state.get('tg_ai_count_g3', 10),
                'saved_at': kst_strftime('%Y-%m-%d %H:%M:%S'),
            }
            try:
                r = requests.patch(
                    f"https://api.github.com/gists/{_gid}",
                    headers={'Authorization':f'token {_ght}','Accept':'application/vnd.github.v3+json'},
                    json={"files":{"kalpha_config.json":{"content":json.dumps(cfg,ensure_ascii=False,indent=2)}}},
                    timeout=15)
                return r.status_code == 200, f"HTTP {r.status_code}"
            except Exception as e:
                return False, str(e)

        st.markdown("---")
        st.markdown("**☁️ GitHub Actions 설정 동기화**")
        st.caption("PC가 꺼져있어도 아래 설정값이 GitHub Actions에 적용됩니다.")
        if st.button("💾 현재 설정을 GitHub Actions에 저장", use_container_width=True, key="btn_sync_cfg"):
            with st.spinner("Gist에 저장 중..."):
                _ok, _msg = _save_cfg_to_gist()
            if _ok:
                st.success("✅ 저장 완료! 다음 GitHub Actions 실행부터 반영됩니다.")
            else:
                st.error(f"❌ 저장 실패: {_msg}")
        st.markdown("---")

        def _iv_map():
            """10분 단위 10~240분 레이블↔분 딕셔너리 (순서 보장 리스트 쌍)"""
            keys, vals = [], []
            for m in range(10, 250, 10):
                if m < 60:   lbl = f"{m}분"
                elif m%60==0: lbl = f"{m//60}시간"
                else:         lbl = f"{m//60}시간{m%60}분"
                keys.append(lbl); vals.append(m)
            return keys, vals
        _iv_keys, _iv_vals = _iv_map()
        _iv_dict = dict(zip(_iv_keys, _iv_vals))

        tab_p, tab_g, tab_g2, tab_g3 = st.tabs(["👤 개인 채팅방", "👥 그룹방 1", "👥 그룹방 2", "👥 그룹방 3"])

        def _show_tg_group_error(err_desc, chat_id_str):
            """텔레그램 그룹 연결 오류 원인 진단 + 해결책 안내"""
            err = (err_desc or '').lower()
            chat_id_str = str(chat_id_str).strip()
            # 채팅ID 형식 진단
            is_supergroup = chat_id_str.startswith('-100')
            is_plain_group = chat_id_str.startswith('-') and not chat_id_str.startswith('-100')
            is_positive = not chat_id_str.startswith('-')

            if 'chat not found' in err:
                if is_plain_group:
                    st.error(f"❌ chat not found")
                    st.markdown("""<div style="background:rgba(255,77,109,0.08);border:1px solid rgba(255,77,109,0.3);
border-radius:8px;padding:12px;font-family:monospace;font-size:12px;color:#e2e8f0;line-height:2">
<b style="color:#ffc800">🔍 원인: 일반 그룹 Chat ID입니다</b><br>
입력한 ID(<code style="color:#ff4d6d">{cid}</code>)는 <b>일반 그룹</b>으로, 봇 메시지를 받을 수 없습니다.<br><br>
<b style="color:#00d4ff">✅ 해결 방법 (둘 중 하나):</b><br>
① 텔레그램 PC앱에서 해당 그룹 → <b>그룹 설정 → 그룹 유형 → 슈퍼그룹으로 전환</b><br>
② <b>새 그룹 생성</b> 시 "슈퍼그룹"으로 만들기 (멤버 200명 이상이면 자동 슈퍼그룹)<br><br>
슈퍼그룹 Chat ID는 <b style="color:#00ff88">-100</b>으로 시작합니다 (예: <code>-1001234567890</code>)
</div>""".format(cid=chat_id_str), unsafe_allow_html=True)
                elif is_positive:
                    st.error(f"❌ chat not found")
                    st.markdown("""<div style="background:rgba(255,77,109,0.08);border:1px solid rgba(255,77,109,0.3);
border-radius:8px;padding:12px;font-family:monospace;font-size:12px;color:#e2e8f0;line-height:2">
<b style="color:#ffc800">🔍 원인: 개인 Chat ID 또는 잘못된 형식</b><br>
그룹 Chat ID는 반드시 <b style="color:#ff4d6d">음수(- 로 시작)</b>여야 합니다.<br>
개인방 Chat ID를 입력하셨다면 <b>개인 채팅방 탭</b>을 이용하세요.
</div>""", unsafe_allow_html=True)
                else:
                    st.error(f"❌ chat not found")
                    st.markdown("""<div style="background:rgba(255,77,109,0.08);border:1px solid rgba(255,77,109,0.3);
border-radius:8px;padding:12px;font-family:monospace;font-size:12px;color:#e2e8f0;line-height:2">
<b style="color:#ffc800">🔍 가능한 원인:</b><br>
① 봇이 그룹에 <b>초대되지 않았거나 강퇴</b>됨<br>
② 봇의 <b>Privacy Mode</b>가 켜져 있음 → BotFather에서 <code>/setprivacy</code> → <b>Disable</b><br>
③ 그룹 Chat ID가 잘못됨 → <b>@userinfobot</b>으로 정확한 ID 확인
</div>""", unsafe_allow_html=True)
            elif 'forbidden' in err or 'kicked' in err:
                st.error(f"❌ {err_desc}")
                st.markdown("""<div style="background:rgba(255,77,109,0.08);border:1px solid rgba(255,77,109,0.3);
border-radius:8px;padding:12px;font-family:monospace;font-size:12px;color:#e2e8f0;line-height:2">
<b style="color:#ffc800">🔍 원인: 봇이 그룹에서 차단됨</b><br>
봇을 그룹에서 <b>다시 초대</b>하고 <b>관리자 권한</b>을 부여하세요.<br>
또는 BotFather → <code>/setprivacy</code> → <b>Disable</b> 후 봇 재초대
</div>""", unsafe_allow_html=True)
            else:
                st.error(f"❌ {err_desc}")
                st.markdown("""<div style="background:rgba(255,77,109,0.08);border:1px solid rgba(255,77,109,0.3);
border-radius:8px;padding:12px;font-family:monospace;font-size:12px;color:#e2e8f0;line-height:2">
<b style="color:#ffc800">🔍 체크리스트:</b><br>
① BotFather → <code>/setprivacy</code> → <b>Disable</b> (필수)<br>
② 봇을 그룹 <b>관리자</b>로 설정<br>
③ @userinfobot 으로 정확한 Chat ID 재확인<br>
④ Bot Token이 개인방 탭에 정상 등록됐는지 확인
</div>""", unsafe_allow_html=True)

        # ── 개인방 탭 ──────────────────────────────
        with tab_p:
            st.caption("봇 토큰과 내 개인 Chat ID를 입력하세요.")
            tg_token = st.text_input("Bot Token", type="password",
                                      value=st.session_state.get('tg_token',''),
                                      placeholder="123456:ABCdef...", key="tg_token_inp")
            tg_chat  = st.text_input("개인 Chat ID",
                                      value=st.session_state.get('tg_chat',''),
                                      placeholder="7863087287", key="tg_chat_inp")

            _cur_p = st.session_state.get('tg_interval_label','10분')
            if _cur_p not in _iv_keys: _cur_p = '10분'
            iv_p_label = st.select_slider("⏱ 개인방 전송 간격",
                                           options=_iv_keys, value=_cur_p, key="tg_iv_p")
            st.session_state['tg_interval_label'] = iv_p_label
            st.session_state['tg_interval_min']   = _iv_dict[iv_p_label]

            _ai_cnt_p = st.slider("🤖 AI 분석 카테고리당 종목 수",
                                   min_value=1, max_value=20,
                                   value=st.session_state.get('tg_ai_count_p', 10),
                                   key="sl_ai_cnt_p")
            st.session_state['tg_ai_count_p'] = _ai_cnt_p
            _ai_send_p = st.checkbox("🤖 개인방 AI 분석 자동 전송",
                                      value=st.session_state.get('tg_ai_send_p', True),
                                      key="cb_ai_send_p")
            st.session_state['tg_ai_send_p'] = _ai_send_p
            st.caption(f"개인방: 카테고리당 {_ai_cnt_p}종목씩" + (" AI 포함" if _ai_send_p else " AI 미전송") + " 전송")

            st.markdown("**🕐 송출 시간 설정 (KST)**")
            _tw_p1, _tw_p2 = st.columns(2)
            with _tw_p1:
                _p_sh = st.number_input("시작 시각 (시)", min_value=0, max_value=23,
                    value=st.session_state.get('tg_send_start_p', 9), step=1,
                    key="inp_p_sh", help="이 시각 이후에만 전송 (예: 9 = 09:00~)")
                st.session_state['tg_send_start_p'] = _p_sh
            with _tw_p2:
                _p_eh = st.number_input("종료 시각 (시)", min_value=0, max_value=23,
                    value=st.session_state.get('tg_send_end_p', 15), step=1,
                    key="inp_p_eh", help="이 시각 이전까지만 전송 (예: 15 = ~15:59)")
                st.session_state['tg_send_end_p'] = _p_eh
            st.caption(f"📡 개인방 송출 시간: {_p_sh:02d}:00 ~ {_p_eh:02d}:59 KST")

            cs1, cs2 = st.columns([2,1])
            with cs1:
                if st.button("💾 Bot Token & Chat ID 저장", key="btn_tg_save",
                             use_container_width=True,
                             disabled=not bool(tg_token and tg_chat)):
                    st.session_state['tg_token'] = tg_token
                    st.session_state['tg_chat']  = tg_chat
                    tg_enc = base64.b64encode(
                        json.dumps({'t':tg_token,'c':tg_chat}).encode()).decode()
                    qp['tg'] = tg_enc
                    server_store['tg'] = tg_enc
                    components.html(
                        f"<script>try{{localStorage.setItem('ka_tg_v1',{json.dumps(tg_enc)});}}catch(e){{}}</script>",
                        height=0, scrolling=False)
                    st.success("✅ 저장 완료")
            with cs2:
                if st.button("🗑 삭제", key="btn_tg_del", use_container_width=True,
                             disabled=not bool(st.session_state.get('tg_token') or
                                               st.session_state.get('tg_chat'))):
                    st.session_state['tg_token'] = ''
                    st.session_state['tg_chat']  = ''
                    server_store['tg'] = None
                    try: del qp['tg']
                    except: pass
                    st.rerun()

            cp1, cp2 = st.columns([2,1])
            with cp1:
                if st.button("📱 개인방 테스트 전송", use_container_width=True, key="btn_tg_p"):
                    if tg_token and tg_chat:
                        try:
                            r = requests.post(
                                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                                json={"chat_id":tg_chat,
                                      "text":"✅ K-ALPHA 개인방 알림 연결 성공!",
                                      "parse_mode":"HTML"}, timeout=8)
                            if r.json().get('ok'):
                                st.session_state['tg_token'] = tg_token
                                st.session_state['tg_chat']  = tg_chat
                                tg_enc = base64.b64encode(
                                    json.dumps({'t':tg_token,'c':tg_chat}).encode()).decode()
                                qp['tg'] = tg_enc
                                server_store['tg'] = tg_enc
                                components.html(
                                    f"<script>try{{localStorage.setItem('ka_tg_v1',{json.dumps(tg_enc)});}}catch(e){{}}</script>",
                                    height=0, scrolling=False)
                                st.success("✅ 개인방 연결 성공!")
                            else:
                                st.error(f"❌ {r.json().get('description')}")
                        except Exception as e:
                            st.error(f"❌ {e}")
                    else:
                        st.error("Token과 Chat ID 입력")

                # ── 포맷 미리보기 테스트 전송 ──
                if st.button("📤 포맷 테스트 전송 (실제 카테고리 전체)", use_container_width=True, key="btn_fmt_test_p"):
                    _tok_ft = st.session_state.get('tg_token','')
                    _chat_ft = st.session_state.get('tg_chat','')
                    _sr_ft  = server_store.get('scan_result') or {}
                    _n_ft   = st.session_state.get('tg_send_count_p', 10)
                    TG_LIM  = 3800
                    def _fmt_ft_p(c):
                        try: p = int(str(c.get('price','0')).replace(',',''))
                        except: p = 0
                        def _i(v,f):
                            try: return int(str(v).replace(',',''))
                            except: return f
                        buy=_i(c.get('buy'),int(p*0.995)); stop=_i(c.get('stop'),int(p*0.97))
                        tgt=_i(c.get('target'),int(p*1.10))
                        try: rr=float(str(c.get('rr','')).replace(',',''))
                        except: rr=0
                        if not rr: rr=round((tgt-p)/(p-stop+1),1) if p>0 else 3.3
                        vol=c.get('vol',0)
                        try: vol=int(vol)
                        except: pass
                        pct=c.get('change','0%'); score=c.get('score',70); grade=c.get('grade','B')
                        rsi=c.get('rsiApprox',50) or 50; mkt=str(c.get('mkt','KOSPI')).upper()
                        chg=0.0
                        try: chg=float(str(pct).replace('%','').replace('+',''))
                        except: pass
                        g_icon='🔴' if grade=='S' else ('🟠' if grade=='A' else ('🟡' if grade=='B' else '⚪'))
                        if chg>=7: risk='⚠ 급등주의'
                        elif chg>=4: risk='📌 눌림대기'
                        elif rr<1.5: risk='⚠ RR낮음'
                        elif rsi>72: risk=f'⚠ RSI{rsi:.0f}과매수'
                        else: risk='✅ 리스크 정상'
                        ls=['━'*18,
                            f"{g_icon} <b>{c.get('name','')} ({c.get('code','')})</b>  [{mkt}]",
                            f"💰 <b>{p:,}원</b>  {pct}  |  거래대금 <b>{vol:,}억</b>",
                            f"📊 RSI {rsi:.0f}  |  K점수 <b>{score}점({grade})</b>  |  RR <b>{rr}</b>",
                            f"📈 매입가 {buy:,}원  →  목표 {tgt:,}원  |  손절 {stop:,}원",
                            risk]
                        reasons=c.get('reasons',[])
                        if reasons:
                            ls.append(''); ls.append('📋 <b>K 분석 사유</b>')
                            for r in reasons:
                                ls.append(f"  ▸ {r.get('text','') if isinstance(r,dict) else str(r)}")
                        return '\n'.join(ls)
                    def _send_ft_p(text):
                        try:
                            requests.post(f"https://api.telegram.org/bot{_tok_ft}/sendMessage",
                                json={"chat_id":_chat_ft,"text":text,"parse_mode":"HTML"},timeout=10)
                        except: pass
                    def _send_cat_ft_p(lst, emoji, label):
                        if not lst: return
                        total=len(lst); no=1; buf=[]; bl=0
                        for stock in lst:
                            card=_fmt_ft_p(stock); clen=len(card)+2
                            if buf and bl+clen>TG_LIM:
                                hdr=f"{emoji} <b>【{label} TOP{total}】 — {no}부</b>"
                                _send_ft_p(hdr+'\n'+'\n\n'.join(buf))
                                import time; time.sleep(0.3)
                                no+=1; buf=[]; bl=0
                            buf.append(card); bl+=clen
                        if buf:
                            hdr=(f"{emoji} <b>【{label} TOP{total}】</b>" if no==1
                                 else f"{emoji} <b>【{label} TOP{total}】 — {no}부</b>")
                            _send_ft_p(hdr+'\n'+'\n\n'.join(buf))
                    if not _tok_ft or not _chat_ft:
                        st.warning("Token·Chat ID 먼저 저장하세요")
                    elif not _sr_ft:
                        st.warning("스캔 데이터 없음 — 앱이 스캔 후 다시 시도하세요")
                    else:
                        sw=_sr_ft.get('swing',[])[:_n_ft]; su=_sr_ft.get('surge',[])[:_n_ft]
                        tm=_sr_ft.get('tomorrow',[])[:_n_ft]; sml=_sr_ft.get('smallmid',[])[:_n_ft]
                        ts_ft=kst_strftime('%H:%M:%S')
                        _send_ft_p(f"🧪 <b>[개인방 포맷 테스트]</b> {ts_ft}\n🔥스윙:{len(sw)} ⚡급등:{len(su)} 🌙내일:{len(tm)} 📦중소형:{len(sml)}")
                        import time; time.sleep(0.3)
                        _send_cat_ft_p(sw,  '🔥', '실시간 스윙')
                        _send_cat_ft_p(su,  '⚡', '급등전야')
                        _send_cat_ft_p(tm,  '🌙', '내일관심')
                        _send_cat_ft_p(sml, '📦', '중소형주')
                        st.success(f"✅ 개인방 포맷 테스트 전송 완료")

            with cp2:
                ok_p = bool(st.session_state.get('tg_token') and st.session_state.get('tg_chat'))
                st.markdown(
                    f'<div style="padding:8px;text-align:center;font-family:monospace;font-size:12px;'
                    f'color:{"#00ff88" if ok_p else "#4a5568"}">{"🟢 연결됨" if ok_p else "⭕ 미연결"}</div>',
                    unsafe_allow_html=True)

        # ── 그룹방 탭 ──────────────────────────────
        with tab_g:
            st.caption("같은 봇 토큰을 사용합니다. 그룹 Chat ID만 별도 입력하세요.")
            st.info("그룹 Chat ID는 보통 `-100` 으로 시작하는 음수입니다.", icon="ℹ️")
            st.warning("⚠️ **텔레그램 채널은 지원되지 않습니다.**\n\n채널이 아닌 **그룹(슈퍼그룹)** 에만 전송 가능합니다. 봇을 그룹에 **관리자**로 추가한 뒤 Chat ID를 입력하세요. 채널 Chat ID를 입력하면 `chat not found` 오류가 발생합니다.", icon="🚫")

            grp_enabled = st.toggle("그룹방 알림 활성화",
                                     value=st.session_state.get('tg_group_enabled', False),
                                     key="tog_grp_en")
            st.session_state['tg_group_enabled'] = grp_enabled

            tg_group_chat = st.text_input("그룹 Chat ID",
                                           value=st.session_state.get('tg_group_chat',''),
                                           placeholder="-1001234567890",
                                           disabled=not grp_enabled,
                                           key="tg_grp_chat_inp")
            # 입력값 즉시 session_state 반영 (disabled 상태에서도 기존값 유지)
            if tg_group_chat:
                st.session_state['tg_group_chat'] = tg_group_chat
            _grp_chat_val = st.session_state.get('tg_group_chat', '')

            _cur_g = st.session_state.get('tg_group_interval_label','30분')
            if _cur_g not in _iv_keys: _cur_g = '30분'
            iv_g_label = st.select_slider("⏱ 그룹방 전송 간격",
                                           options=_iv_keys, value=_cur_g,
                                           disabled=not grp_enabled, key="tg_iv_g")
            st.session_state['tg_group_interval_label'] = iv_g_label
            st.session_state['tg_group_interval_min']   = _iv_dict[iv_g_label]

            _ai_cnt_g1 = st.slider("🤖 AI 분석 카테고리당 종목 수",
                                    min_value=1, max_value=20,
                                    value=st.session_state.get('tg_ai_count_g1', 10),
                                    disabled=not grp_enabled, key="sl_ai_cnt_g1")
            st.session_state['tg_ai_count_g1'] = _ai_cnt_g1
            _ai_send_g1 = st.checkbox("🤖 그룹방 1 AI 분석 자동 전송",
                                       value=st.session_state.get('tg_ai_send_g1', False),
                                       disabled=not grp_enabled, key="cb_ai_send_g1")
            st.session_state['tg_ai_send_g1'] = _ai_send_g1
            st.caption(f"그룹방 1: 카테고리당 {_ai_cnt_g1}종목씩" + (" AI 포함" if _ai_send_g1 else " AI 미전송") + " 전송")

            st.markdown("**🕐 송출 시간 설정 (KST)**")
            _tw_g1a, _tw_g1b = st.columns(2)
            with _tw_g1a:
                _g1_sh = st.number_input("시작 시각 (시)", min_value=0, max_value=23,
                    value=st.session_state.get('tg_send_start_g1', 9), step=1,
                    disabled=not grp_enabled, key="inp_g1_sh")
                st.session_state['tg_send_start_g1'] = _g1_sh
            with _tw_g1b:
                _g1_eh = st.number_input("종료 시각 (시)", min_value=0, max_value=23,
                    value=st.session_state.get('tg_send_end_g1', 15), step=1,
                    disabled=not grp_enabled, key="inp_g1_eh")
                st.session_state['tg_send_end_g1'] = _g1_eh
            st.caption(f"📡 그룹방 1 송출 시간: {_g1_sh:02d}:00 ~ {_g1_eh:02d}:59 KST")

            cgs_g1a, cgs_g1b = st.columns([2,1])
            with cgs_g1a:
                if st.button("💾 그룹방 Chat ID 저장", key="btn_grp1_save",
                             use_container_width=True,
                             disabled=not bool(_grp_chat_val or tg_group_chat)):
                    _sv = tg_group_chat or _grp_chat_val
                    st.session_state['tg_group_chat'] = _sv
                    _enc = base64.b64encode(json.dumps({
                        'c': _sv, 'en': grp_enabled,
                        'iv': _iv_dict[iv_g_label], 'ivl': iv_g_label,
                    }).encode()).decode()
                    qp['tg_grp'] = _enc
                    server_store['tg_grp'] = _enc
                    st.success("✅ 저장 완료")
            with cgs_g1b:
                if st.button("🗑 삭제", key="btn_grp1_del",
                             use_container_width=True,
                             disabled=not bool(st.session_state.get('tg_group_chat'))):
                    st.session_state['tg_group_chat'] = ''
                    st.session_state['tg_group_enabled'] = False
                    server_store['tg_grp'] = None
                    try: del qp['tg_grp']
                    except: pass
                    st.rerun()


            # ── 포맷 미리보기 전송 ──
            if st.button("📤 포맷 테스트 전송 (실제 카테고리 전체)", use_container_width=True,
                         key="btn_fmt_g1", disabled=(not grp_enabled or not _grp_chat_val)):
                _tok_ft = st.session_state.get('tg_token','')
                _sr_ft  = server_store.get('scan_result') or {}
                _n_ft   = st.session_state.get('tg_send_count_g1', 10)
                TG_LIM  = 3800
                def _fmt_ft(c):
                    try: p = int(str(c.get('price','0')).replace(',',''))
                    except: p = 0
                    def _i(v,f):
                        try: return int(str(v).replace(',',''))
                        except: return f
                    buy=_i(c.get('buy'),int(p*0.995)); stop=_i(c.get('stop'),int(p*0.97))
                    tgt=_i(c.get('target'),int(p*1.10))
                    try: rr=float(str(c.get('rr','')).replace(',',''))
                    except: rr=0
                    if not rr: rr=round((tgt-p)/(p-stop+1),1) if p>0 else 3.3
                    vol=c.get('vol',0)
                    try: vol=int(vol)
                    except: pass
                    pct=c.get('change','0%'); score=c.get('score',70); grade=c.get('grade','B')
                    rsi=c.get('rsiApprox',50) or 50; mkt=str(c.get('mkt','KOSPI')).upper()
                    chg=0.0
                    try: chg=float(str(pct).replace('%','').replace('+',''))
                    except: pass
                    g_icon='🔴' if grade=='S' else ('🟠' if grade=='A' else ('🟡' if grade=='B' else '⚪'))
                    if chg>=7: risk='⚠ 급등주의'
                    elif chg>=4: risk='📌 눌림대기'
                    elif rr<1.5: risk='⚠ RR낮음'
                    elif rsi>72: risk=f'⚠ RSI{rsi:.0f}과매수'
                    else: risk='✅ 리스크 정상'
                    ls=['━'*18,
                        f"{g_icon} <b>{c.get('name','')} ({c.get('code','')})</b>  [{mkt}]",
                        f"💰 <b>{p:,}원</b>  {pct}  |  거래대금 <b>{vol:,}억</b>",
                        f"📊 RSI {rsi:.0f}  |  K점수 <b>{score}점({grade})</b>  |  RR <b>{rr}</b>",
                        f"📈 매입가 {buy:,}원  →  목표 {tgt:,}원  |  손절 {stop:,}원",
                        risk]
                    reasons=c.get('reasons',[])
                    if reasons:
                        ls.append(''); ls.append('📋 <b>K 분석 사유</b>')
                        for r in reasons:
                            ls.append(f"  ▸ {r.get('text','') if isinstance(r,dict) else str(r)}")
                    return '\n'.join(ls)
                def _send_ft(text):
                    try:
                        requests.post(f"https://api.telegram.org/bot{_tok_ft}/sendMessage",
                            json={"chat_id":_grp_chat_val,"text":text,"parse_mode":"HTML"},timeout=10)
                    except: pass
                def _send_cat_ft(lst, emoji, label):
                    if not lst: return
                    total=len(lst); no=1; buf=[]; bl=0
                    for stock in lst:
                        card=_fmt_ft(stock); clen=len(card)+2
                        if buf and bl+clen>TG_LIM:
                            hdr=f"{emoji} <b>【{label} TOP{total}】 — {no}부</b>"
                            _send_ft(hdr+'\n'+'\n\n'.join(buf))
                            import time; time.sleep(0.3)
                            no+=1; buf=[]; bl=0
                        buf.append(card); bl+=clen
                    if buf:
                        hdr=(f"{emoji} <b>【{label} TOP{total}】</b>" if no==1
                             else f"{emoji} <b>【{label} TOP{total}】 — {no}부</b>")
                        _send_ft(hdr+'\n'+'\n\n'.join(buf))
                if not _tok_ft:
                    st.warning("Bot Token이 없습니다")
                elif not _sr_ft:
                    st.warning("스캔 데이터 없음 — 앱이 스캔 후 다시 시도하세요")
                else:
                    sw=_sr_ft.get('swing',[])[:_n_ft]; su=_sr_ft.get('surge',[])[:_n_ft]
                    tm=_sr_ft.get('tomorrow',[])[:_n_ft]; sml=_sr_ft.get('smallmid',[])[:_n_ft]
                    ts_ft=kst_strftime('%H:%M:%S')
                    _send_ft(f"🧪 <b>[그룹방1 포맷 테스트]</b> {ts_ft}\n🔥스윙:{len(sw)} ⚡급등:{len(su)} 🌙내일:{len(tm)} 📦중소형:{len(sml)}")
                    import time; time.sleep(0.3)
                    _send_cat_ft(sw,  '🔥', '실시간 스윙')
                    _send_cat_ft(su,  '⚡', '급등전야')
                    _send_cat_ft(tm,  '🌙', '내일관심')
                    _send_cat_ft(sml, '📦', '중소형주')
                    st.success(f"✅ 그룹방1 포맷 테스트 전송 완료")

            cg1, cg2 = st.columns([2,1])
            with cg1:
                if st.button("👥 그룹방 테스트 전송", use_container_width=True,
                              key="btn_tg_g", disabled=(not grp_enabled or not _grp_chat_val)):
                    _tok = st.session_state.get('tg_token','')
                    if _tok and _grp_chat_val:
                        try:
                            # 1단계: 봇이 그룹 멤버인지 먼저 확인
                            _chat_info = requests.get(
                                f"https://api.telegram.org/bot{_tok}/getChat",
                                params={"chat_id": _grp_chat_val}, timeout=8).json()
                            if not _chat_info.get('ok'):
                                _show_tg_group_error(_chat_info.get('description',''), _grp_chat_val)
                            else:
                                r = requests.post(
                                    f"https://api.telegram.org/bot{_tok}/sendMessage",
                                    json={"chat_id": _grp_chat_val,
                                          "text":"✅ K-ALPHA 그룹방 알림 연결 성공!",
                                          "parse_mode":"HTML"}, timeout=8)
                                if r.json().get('ok'):
                                    st.session_state['tg_group_chat'] = _grp_chat_val
                                    grp_enc = base64.b64encode(json.dumps({
                                        'c': _grp_chat_val,
                                        'en': grp_enabled,
                                        'iv': _iv_dict[iv_g_label],
                                        'ivl': iv_g_label,
                                    }).encode()).decode()
                                    qp['tg_grp'] = grp_enc
                                    server_store['tg_grp'] = grp_enc
                                    components.html(
                                        f"<script>try{{localStorage.setItem('ka_tg_grp_v1',{json.dumps(grp_enc)});}}catch(e){{}}</script>",
                                        height=0, scrolling=False)
                                    st.success("✅ 그룹방 연결 성공!")
                                else:
                                    err_d = r.json().get('description','')
                                    if 'not enough rights' in err_d.lower() or 'have no rights' in err_d.lower():
                                        st.error("❌ 봇에게 메시지 전송 권한이 없습니다")
                                        st.markdown("""<div style="background:rgba(255,77,109,0.08);border:1px solid rgba(255,77,109,0.3);
border-radius:8px;padding:12px;font-family:monospace;font-size:12px;color:#e2e8f0;line-height:2">
<b style="color:#ffc800">🔍 원인: 봇 메시지 권한 없음</b><br>
① 그룹 설정 → 봇 → <b>관리자로 설정</b> 후 재시도<br>
② 또는 BotFather → <code>/setprivacy</code> → <b>Disable</b> 후 봇을 그룹에서 내보내고 재초대
</div>""", unsafe_allow_html=True)
                                    else:
                                        _show_tg_group_error(err_d, _grp_chat_val)
                        except Exception as e:
                            st.error(f"❌ {e}")
                    elif not _tok:
                        st.error("개인방 탭에서 Bot Token을 먼저 등록하세요")
                    else:
                        st.error("그룹 Chat ID를 입력하세요")
            with cg2:
                ok_g = bool(grp_enabled and st.session_state.get('tg_group_chat'))
                st.markdown(
                    f'<div style="padding:8px;text-align:center;font-family:monospace;font-size:12px;'
                    f'color:{"#00ff88" if ok_g else "#4a5568"}">{"🟢 연결됨" if ok_g else "⭕ 미연결"}</div>',
                    unsafe_allow_html=True)

            # 그룹방 URL 파라미터 자동 저장 (값 변경 시마다)
            if tg_group_chat:
                st.session_state['tg_group_chat'] = tg_group_chat
                grp_enc = base64.b64encode(json.dumps({
                    'c': tg_group_chat,
                    'en': grp_enabled,
                    'iv': _iv_dict[iv_g_label],
                    'ivl': iv_g_label,
                }).encode()).decode()
                qp['tg_grp'] = grp_enc
                server_store['tg_grp'] = grp_enc

        # ── 그룹방 2 탭 ──────────────────────────────
        with tab_g2:
            st.caption("같은 봇 토큰을 사용합니다. 그룹방 2 Chat ID를 입력하세요.")
            st.info("그룹 Chat ID는 보통 `-100` 으로 시작하는 음수입니다.", icon="ℹ️")
            st.warning("⚠️ **텔레그램 채널은 지원되지 않습니다.** 채널이 아닌 **그룹(슈퍼그룹)** 에만 전송 가능합니다. 봇을 그룹 **관리자**로 추가 후 Chat ID 입력하세요.", icon="🚫")

            grp2_enabled = st.toggle("그룹방 2 알림 활성화",
                                     value=st.session_state.get('tg_group2_enabled', False),
                                     key="tog_grp2_en")
            st.session_state['tg_group2_enabled'] = grp2_enabled

            tg_group2_chat = st.text_input("그룹방 2 Chat ID",
                                           value=st.session_state.get('tg_group2_chat',''),
                                           placeholder="-1001234567890",
                                           disabled=not grp2_enabled,
                                           key="tg_grp2_chat_inp")
            if tg_group2_chat:
                st.session_state['tg_group2_chat'] = tg_group2_chat
            _grp2_chat_val = st.session_state.get('tg_group2_chat', '')

            _cur_g2 = st.session_state.get('tg_group2_interval_label','30분')
            if _cur_g2 not in _iv_keys: _cur_g2 = '30분'
            iv_g2_label = st.select_slider("⏱ 그룹방 2 전송 간격",
                                           options=_iv_keys, value=_cur_g2,
                                           disabled=not grp2_enabled, key="tg_iv_g2")
            st.session_state['tg_group2_interval_label'] = iv_g2_label
            st.session_state['tg_group2_interval_min']   = _iv_dict[iv_g2_label]

            _ai_cnt_g2 = st.slider("🤖 AI 분석 카테고리당 종목 수",
                                    min_value=1, max_value=20,
                                    value=st.session_state.get('tg_ai_count_g2', 10),
                                    disabled=not grp2_enabled, key="sl_ai_cnt_g2")
            st.session_state['tg_ai_count_g2'] = _ai_cnt_g2
            _ai_send_g2 = st.checkbox("🤖 그룹방 2 AI 분석 자동 전송",
                                       value=st.session_state.get('tg_ai_send_g2', False),
                                       disabled=not grp2_enabled, key="cb_ai_send_g2")
            st.session_state['tg_ai_send_g2'] = _ai_send_g2
            st.caption(f"그룹방 2: 카테고리당 {_ai_cnt_g2}종목씩" + (" AI 포함" if _ai_send_g2 else " AI 미전송") + " 전송")

            st.markdown("**🕐 송출 시간 설정 (KST)**")
            _tw_g2a, _tw_g2b = st.columns(2)
            with _tw_g2a:
                _g2_sh = st.number_input("시작 시각 (시)", min_value=0, max_value=23,
                    value=st.session_state.get('tg_send_start_g2', 9), step=1,
                    disabled=not grp2_enabled, key="inp_g2_sh")
                st.session_state['tg_send_start_g2'] = _g2_sh
            with _tw_g2b:
                _g2_eh = st.number_input("종료 시각 (시)", min_value=0, max_value=23,
                    value=st.session_state.get('tg_send_end_g2', 15), step=1,
                    disabled=not grp2_enabled, key="inp_g2_eh")
                st.session_state['tg_send_end_g2'] = _g2_eh
            st.caption(f"📡 그룹방 2 송출 시간: {_g2_sh:02d}:00 ~ {_g2_eh:02d}:59 KST")

            cgs_g2a, cgs_g2b = st.columns([2,1])
            with cgs_g2a:
                if st.button("💾 그룹방 2 Chat ID 저장", key="btn_grp2_save",
                             use_container_width=True,
                             disabled=not bool(_grp2_chat_val or tg_group2_chat)):
                    _sv2 = tg_group2_chat or _grp2_chat_val
                    st.session_state['tg_group2_chat'] = _sv2
                    _enc2 = base64.b64encode(json.dumps({
                        'c': _sv2, 'en': grp2_enabled,
                        'iv': _iv_dict[iv_g2_label], 'ivl': iv_g2_label,
                    }).encode()).decode()
                    qp['tg_grp2'] = _enc2
                    server_store['tg_grp2'] = _enc2
                    st.success("✅ 저장 완료")
            with cgs_g2b:
                if st.button("🗑 삭제", key="btn_grp2_del",
                             use_container_width=True,
                             disabled=not bool(st.session_state.get('tg_group2_chat'))):
                    st.session_state['tg_group2_chat'] = ''
                    st.session_state['tg_group2_enabled'] = False
                    server_store['tg_grp2'] = None
                    try: del qp['tg_grp2']
                    except: pass
                    st.rerun()


            # ── 포맷 미리보기 전송 ──
            if st.button("📤 포맷 테스트 전송 (실제 카테고리 전체)", use_container_width=True,
                         key="btn_fmt_g2", disabled=(not grp2_enabled or not _grp2_chat_val)):
                _tok_ft = st.session_state.get('tg_token','')
                _sr_ft  = server_store.get('scan_result') or {}
                _n_ft   = st.session_state.get('tg_send_count_g2', 10)
                TG_LIM  = 3800
                def _fmt_ft(c):
                    try: p = int(str(c.get('price','0')).replace(',',''))
                    except: p = 0
                    def _i(v,f):
                        try: return int(str(v).replace(',',''))
                        except: return f
                    buy=_i(c.get('buy'),int(p*0.995)); stop=_i(c.get('stop'),int(p*0.97))
                    tgt=_i(c.get('target'),int(p*1.10))
                    try: rr=float(str(c.get('rr','')).replace(',',''))
                    except: rr=0
                    if not rr: rr=round((tgt-p)/(p-stop+1),1) if p>0 else 3.3
                    vol=c.get('vol',0)
                    try: vol=int(vol)
                    except: pass
                    pct=c.get('change','0%'); score=c.get('score',70); grade=c.get('grade','B')
                    rsi=c.get('rsiApprox',50) or 50; mkt=str(c.get('mkt','KOSPI')).upper()
                    chg=0.0
                    try: chg=float(str(pct).replace('%','').replace('+',''))
                    except: pass
                    g_icon='🔴' if grade=='S' else ('🟠' if grade=='A' else ('🟡' if grade=='B' else '⚪'))
                    if chg>=7: risk='⚠ 급등주의'
                    elif chg>=4: risk='📌 눌림대기'
                    elif rr<1.5: risk='⚠ RR낮음'
                    elif rsi>72: risk=f'⚠ RSI{rsi:.0f}과매수'
                    else: risk='✅ 리스크 정상'
                    ls=['━'*18,
                        f"{g_icon} <b>{c.get('name','')} ({c.get('code','')})</b>  [{mkt}]",
                        f"💰 <b>{p:,}원</b>  {pct}  |  거래대금 <b>{vol:,}억</b>",
                        f"📊 RSI {rsi:.0f}  |  K점수 <b>{score}점({grade})</b>  |  RR <b>{rr}</b>",
                        f"📈 매입가 {buy:,}원  →  목표 {tgt:,}원  |  손절 {stop:,}원",
                        risk]
                    reasons=c.get('reasons',[])
                    if reasons:
                        ls.append(''); ls.append('📋 <b>K 분석 사유</b>')
                        for r in reasons:
                            ls.append(f"  ▸ {r.get('text','') if isinstance(r,dict) else str(r)}")
                    return '\n'.join(ls)
                def _send_ft(text):
                    try:
                        requests.post(f"https://api.telegram.org/bot{_tok_ft}/sendMessage",
                            json={"chat_id":_grp2_chat_val,"text":text,"parse_mode":"HTML"},timeout=10)
                    except: pass
                def _send_cat_ft(lst, emoji, label):
                    if not lst: return
                    total=len(lst); no=1; buf=[]; bl=0
                    for stock in lst:
                        card=_fmt_ft(stock); clen=len(card)+2
                        if buf and bl+clen>TG_LIM:
                            hdr=f"{emoji} <b>【{label} TOP{total}】 — {no}부</b>"
                            _send_ft(hdr+'\n'+'\n\n'.join(buf))
                            import time; time.sleep(0.3)
                            no+=1; buf=[]; bl=0
                        buf.append(card); bl+=clen
                    if buf:
                        hdr=(f"{emoji} <b>【{label} TOP{total}】</b>" if no==1
                             else f"{emoji} <b>【{label} TOP{total}】 — {no}부</b>")
                        _send_ft(hdr+'\n'+'\n\n'.join(buf))
                if not _tok_ft:
                    st.warning("Bot Token이 없습니다")
                elif not _sr_ft:
                    st.warning("스캔 데이터 없음 — 앱이 스캔 후 다시 시도하세요")
                else:
                    sw=_sr_ft.get('swing',[])[:_n_ft]; su=_sr_ft.get('surge',[])[:_n_ft]
                    tm=_sr_ft.get('tomorrow',[])[:_n_ft]; sml=_sr_ft.get('smallmid',[])[:_n_ft]
                    ts_ft=kst_strftime('%H:%M:%S')
                    _send_ft(f"🧪 <b>[그룹방2 포맷 테스트]</b> {ts_ft}\n🔥스윙:{len(sw)} ⚡급등:{len(su)} 🌙내일:{len(tm)} 📦중소형:{len(sml)}")
                    import time; time.sleep(0.3)
                    _send_cat_ft(sw,  '🔥', '실시간 스윙')
                    _send_cat_ft(su,  '⚡', '급등전야')
                    _send_cat_ft(tm,  '🌙', '내일관심')
                    _send_cat_ft(sml, '📦', '중소형주')
                    st.success(f"✅ 그룹방2 포맷 테스트 전송 완료")

            cg2a, cg2b = st.columns([2,1])
            with cg2a:
                if st.button("👥 그룹방 2 테스트 전송", use_container_width=True,
                              key="btn_tg_g2", disabled=(not grp2_enabled or not _grp2_chat_val)):
                    _tok = st.session_state.get('tg_token','')
                    if _tok and _grp2_chat_val:
                        try:
                            _ci2 = requests.get(f"https://api.telegram.org/bot{_tok}/getChat",
                                params={"chat_id": _grp2_chat_val}, timeout=8).json()
                            if not _ci2.get('ok'):
                                _show_tg_group_error(_ci2.get('description',''), _grp2_chat_val)
                            else:
                                r = requests.post(
                                    f"https://api.telegram.org/bot{_tok}/sendMessage",
                                    json={"chat_id": _grp2_chat_val,
                                          "text":"✅ K-ALPHA 그룹방 2 알림 연결 성공!",
                                          "parse_mode":"HTML"}, timeout=8)
                                if r.json().get('ok'):
                                    st.session_state['tg_group2_chat'] = _grp2_chat_val
                                    grp2_enc = base64.b64encode(json.dumps({
                                        'c': _grp2_chat_val,
                                        'en': grp2_enabled,
                                        'iv': _iv_dict[iv_g2_label],
                                        'ivl': iv_g2_label,
                                    }).encode()).decode()
                                    qp['tg_grp2'] = grp2_enc
                                    server_store['tg_grp2'] = grp2_enc
                                    components.html(
                                        f"<script>try{{localStorage.setItem('ka_tg_grp2_v1',{json.dumps(grp2_enc)});}}catch(e){{}}</script>",
                                        height=0, scrolling=False)
                                    st.success("✅ 그룹방 2 연결 성공!")
                                else:
                                    _show_tg_group_error(r.json().get('description',''), _grp2_chat_val)
                        except Exception as e:
                            st.error(f"❌ {e}")
                    elif not _tok:
                        st.error("개인방 탭에서 Bot Token을 먼저 등록하세요")
                    else:
                        st.error("그룹 Chat ID를 입력하세요")
            with cg2b:
                ok_g2 = bool(grp2_enabled and st.session_state.get('tg_group2_chat'))
                st.markdown(
                    f'<div style="padding:8px;text-align:center;font-family:monospace;font-size:12px;'
                    f'color:{"#00ff88" if ok_g2 else "#4a5568"}">{"🟢 연결됨" if ok_g2 else "⭕ 미연결"}</div>',
                    unsafe_allow_html=True)

            if tg_group2_chat:
                st.session_state['tg_group2_chat'] = tg_group2_chat
                grp2_enc = base64.b64encode(json.dumps({
                    'c': tg_group2_chat,
                    'en': grp2_enabled,
                    'iv': _iv_dict[iv_g2_label],
                    'ivl': iv_g2_label,
                }).encode()).decode()
                qp['tg_grp2'] = grp2_enc
                server_store['tg_grp2'] = grp2_enc

        # ── 그룹방 3 탭 ──────────────────────────────
        with tab_g3:
            st.caption("같은 봇 토큰을 사용합니다. 그룹방 3 Chat ID를 입력하세요.")
            st.info("그룹 Chat ID는 보통 `-100` 으로 시작하는 음수입니다.", icon="ℹ️")
            st.warning("⚠️ **텔레그램 채널은 지원되지 않습니다.** 채널이 아닌 **그룹(슈퍼그룹)** 에만 전송 가능합니다. 봇을 그룹 **관리자**로 추가 후 Chat ID 입력하세요.", icon="🚫")

            grp3_enabled = st.toggle("그룹방 3 알림 활성화",
                                     value=st.session_state.get('tg_group3_enabled', False),
                                     key="tog_grp3_en")
            st.session_state['tg_group3_enabled'] = grp3_enabled

            tg_group3_chat = st.text_input("그룹방 3 Chat ID",
                                           value=st.session_state.get('tg_group3_chat',''),
                                           placeholder="-1001234567890",
                                           disabled=not grp3_enabled,
                                           key="tg_grp3_chat_inp")
            if tg_group3_chat:
                st.session_state['tg_group3_chat'] = tg_group3_chat
            _grp3_chat_val = st.session_state.get('tg_group3_chat', '')

            _cur_g3 = st.session_state.get('tg_group3_interval_label','30분')
            if _cur_g3 not in _iv_keys: _cur_g3 = '30분'
            iv_g3_label = st.select_slider("⏱ 그룹방 3 전송 간격",
                                           options=_iv_keys, value=_cur_g3,
                                           disabled=not grp3_enabled, key="tg_iv_g3")
            st.session_state['tg_group3_interval_label'] = iv_g3_label
            st.session_state['tg_group3_interval_min']   = _iv_dict[iv_g3_label]

            _ai_cnt_g3 = st.slider("🤖 AI 분석 카테고리당 종목 수",
                                    min_value=1, max_value=20,
                                    value=st.session_state.get('tg_ai_count_g3', 10),
                                    disabled=not grp3_enabled, key="sl_ai_cnt_g3")
            st.session_state['tg_ai_count_g3'] = _ai_cnt_g3
            _ai_send_g3 = st.checkbox("🤖 그룹방 3 AI 분석 자동 전송",
                                       value=st.session_state.get('tg_ai_send_g3', False),
                                       disabled=not grp3_enabled, key="cb_ai_send_g3")
            st.session_state['tg_ai_send_g3'] = _ai_send_g3
            st.caption(f"그룹방 3: 카테고리당 {_ai_cnt_g3}종목씩" + (" AI 포함" if _ai_send_g3 else " AI 미전송") + " 전송")

            st.markdown("**🕐 송출 시간 설정 (KST)**")
            _tw_g3a, _tw_g3b = st.columns(2)
            with _tw_g3a:
                _g3_sh = st.number_input("시작 시각 (시)", min_value=0, max_value=23,
                    value=st.session_state.get('tg_send_start_g3', 9), step=1,
                    disabled=not grp3_enabled, key="inp_g3_sh")
                st.session_state['tg_send_start_g3'] = _g3_sh
            with _tw_g3b:
                _g3_eh = st.number_input("종료 시각 (시)", min_value=0, max_value=23,
                    value=st.session_state.get('tg_send_end_g3', 15), step=1,
                    disabled=not grp3_enabled, key="inp_g3_eh")
                st.session_state['tg_send_end_g3'] = _g3_eh
            st.caption(f"📡 그룹방 3 송출 시간: {_g3_sh:02d}:00 ~ {_g3_eh:02d}:59 KST")

            cgs_g3a, cgs_g3b = st.columns([2,1])
            with cgs_g3a:
                if st.button("💾 그룹방 3 Chat ID 저장", key="btn_grp3_save",
                             use_container_width=True,
                             disabled=not bool(_grp3_chat_val or tg_group3_chat)):
                    _sv3 = tg_group3_chat or _grp3_chat_val
                    st.session_state['tg_group3_chat'] = _sv3
                    _enc3 = base64.b64encode(json.dumps({
                        'c': _sv3, 'en': grp3_enabled,
                        'iv': _iv_dict[iv_g3_label], 'ivl': iv_g3_label,
                    }).encode()).decode()
                    qp['tg_grp3'] = _enc3
                    server_store['tg_grp3'] = _enc3
                    st.success("✅ 저장 완료")
            with cgs_g3b:
                if st.button("🗑 삭제", key="btn_grp3_del",
                             use_container_width=True,
                             disabled=not bool(st.session_state.get('tg_group3_chat'))):
                    st.session_state['tg_group3_chat'] = ''
                    st.session_state['tg_group3_enabled'] = False
                    server_store['tg_grp3'] = None
                    try: del qp['tg_grp3']
                    except: pass
                    st.rerun()


            cg3a, cg3b = st.columns([2,1])
            with cg3a:
                # ── 포맷 미리보기 전송 ──
                if st.button("📤 포맷 테스트 전송 (실제 카테고리 전체)", use_container_width=True,
                             key="btn_fmt_g3", disabled=(not grp3_enabled or not _grp3_chat_val)):
                    _tok_ft = st.session_state.get('tg_token','')
                    _sr_ft  = server_store.get('scan_result') or {}
                    _n_ft   = st.session_state.get('tg_send_count_g3', 10)
                    TG_LIM  = 3800
                    def _fmt_ft(c):
                        try: p = int(str(c.get('price','0')).replace(',',''))
                        except: p = 0
                        def _i(v,f):
                            try: return int(str(v).replace(',',''))
                            except: return f
                        buy=_i(c.get('buy'),int(p*0.995)); stop=_i(c.get('stop'),int(p*0.97))
                        tgt=_i(c.get('target'),int(p*1.10))
                        try: rr=float(str(c.get('rr','')).replace(',',''))
                        except: rr=0
                        if not rr: rr=round((tgt-p)/(p-stop+1),1) if p>0 else 3.3
                        vol=c.get('vol',0)
                        try: vol=int(vol)
                        except: pass
                        pct=c.get('change','0%'); score=c.get('score',70); grade=c.get('grade','B')
                        rsi=c.get('rsiApprox',50) or 50; mkt=str(c.get('mkt','KOSPI')).upper()
                        chg=0.0
                        try: chg=float(str(pct).replace('%','').replace('+',''))
                        except: pass
                        g_icon='🔴' if grade=='S' else ('🟠' if grade=='A' else ('🟡' if grade=='B' else '⚪'))
                        if chg>=7: risk='⚠ 급등주의'
                        elif chg>=4: risk='📌 눌림대기'
                        elif rr<1.5: risk='⚠ RR낮음'
                        elif rsi>72: risk=f'⚠ RSI{rsi:.0f}과매수'
                        else: risk='✅ 리스크 정상'
                        ls=['━'*18,
                            f"{g_icon} <b>{c.get('name','')} ({c.get('code','')})</b>  [{mkt}]",
                            f"💰 <b>{p:,}원</b>  {pct}  |  거래대금 <b>{vol:,}억</b>",
                            f"📊 RSI {rsi:.0f}  |  K점수 <b>{score}점({grade})</b>  |  RR <b>{rr}</b>",
                            f"📈 매입가 {buy:,}원  →  목표 {tgt:,}원  |  손절 {stop:,}원",
                            risk]
                        reasons=c.get('reasons',[])
                        if reasons:
                            ls.append(''); ls.append('📋 <b>K 분석 사유</b>')
                            for r in reasons:
                                ls.append(f"  ▸ {r.get('text','') if isinstance(r,dict) else str(r)}")
                        return '\n'.join(ls)
                    def _send_ft(text):
                        try:
                            requests.post(f"https://api.telegram.org/bot{_tok_ft}/sendMessage",
                                json={"chat_id":_grp3_chat_val,"text":text,"parse_mode":"HTML"},timeout=10)
                        except: pass
                    def _send_cat_ft(lst, emoji, label):
                        if not lst: return
                        total=len(lst); no=1; buf=[]; bl=0
                        for stock in lst:
                            card=_fmt_ft(stock); clen=len(card)+2
                            if buf and bl+clen>TG_LIM:
                                hdr=f"{emoji} <b>【{label} TOP{total}】 — {no}부</b>"
                                _send_ft(hdr+'\n'+'\n\n'.join(buf))
                                import time; time.sleep(0.3)
                                no+=1; buf=[]; bl=0
                            buf.append(card); bl+=clen
                        if buf:
                            hdr=(f"{emoji} <b>【{label} TOP{total}】</b>" if no==1
                                 else f"{emoji} <b>【{label} TOP{total}】 — {no}부</b>")
                            _send_ft(hdr+'\n'+'\n\n'.join(buf))
                    if not _tok_ft:
                        st.warning("Bot Token이 없습니다")
                    elif not _sr_ft:
                        st.warning("스캔 데이터 없음 — 앱이 스캔 후 다시 시도하세요")
                    else:
                        sw=_sr_ft.get('swing',[])[:_n_ft]; su=_sr_ft.get('surge',[])[:_n_ft]
                        tm=_sr_ft.get('tomorrow',[])[:_n_ft]; sml=_sr_ft.get('smallmid',[])[:_n_ft]
                        ts_ft=kst_strftime('%H:%M:%S')
                        _send_ft(f"🧪 <b>[그룹방3 포맷 테스트]</b> {ts_ft}\n🔥스윙:{len(sw)} ⚡급등:{len(su)} 🌙내일:{len(tm)} 📦중소형:{len(sml)}")
                        import time; time.sleep(0.3)
                        _send_cat_ft(sw,  '🔥', '실시간 스윙')
                        _send_cat_ft(su,  '⚡', '급등전야')
                        _send_cat_ft(tm,  '🌙', '내일관심')
                        _send_cat_ft(sml, '📦', '중소형주')
                        st.success(f"✅ 그룹방3 포맷 테스트 전송 완료")
                if st.button("👥 그룹방 3 테스트 전송", use_container_width=True,
                                  key="btn_tg_g3", disabled=(not grp3_enabled or not _grp3_chat_val)):
                        _tok = st.session_state.get('tg_token','')
                        if _tok and _grp3_chat_val:
                            try:
                                _ci3 = requests.get(f"https://api.telegram.org/bot{_tok}/getChat",
                                    params={"chat_id": _grp3_chat_val}, timeout=8).json()
                                if not _ci3.get('ok'):
                                    _show_tg_group_error(_ci3.get('description',''), _grp3_chat_val)
                                else:
                                    r = requests.post(
                                        f"https://api.telegram.org/bot{_tok}/sendMessage",
                                        json={"chat_id": _grp3_chat_val,
                                              "text":"✅ K-ALPHA 그룹방 3 알림 연결 성공!",
                                              "parse_mode":"HTML"}, timeout=8)
                                    if r.json().get('ok'):
                                        st.session_state['tg_group3_chat'] = _grp3_chat_val
                                        grp3_enc = base64.b64encode(json.dumps({
                                            'c': _grp3_chat_val,
                                            'en': grp3_enabled,
                                            'iv': _iv_dict[iv_g3_label],
                                            'ivl': iv_g3_label,
                                        }).encode()).decode()
                                        qp['tg_grp3'] = grp3_enc
                                        server_store['tg_grp3'] = grp3_enc
                                        components.html(
                                            f"<script>try{{localStorage.setItem('ka_tg_grp3_v1',{json.dumps(grp3_enc)});}}catch(e){{}}</script>",
                                            height=0, scrolling=False)
                                        st.success("✅ 그룹방 3 연결 성공!")
                                    else:
                                        _show_tg_group_error(r.json().get('description',''), _grp3_chat_val)
                            except Exception as e:
                                st.error(f"❌ {e}")
                        elif not _tok:
                            st.error("개인방 탭에서 Bot Token을 먼저 등록하세요")
                        else:
                            st.error("그룹 Chat ID를 입력하세요")
            with cg3b:
                ok_g3 = bool(grp3_enabled and st.session_state.get('tg_group3_chat'))
                st.markdown(
                    f'<div style="padding:8px;text-align:center;font-family:monospace;font-size:12px;'
                    f'color:{"#00ff88" if ok_g3 else "#4a5568"}">{"🟢 연결됨" if ok_g3 else "⭕ 미연결"}</div>',
                    unsafe_allow_html=True)

            if tg_group3_chat:
                st.session_state['tg_group3_chat'] = tg_group3_chat
                grp3_enc = base64.b64encode(json.dumps({
                    'c': tg_group3_chat,
                    'en': grp3_enabled,
                    'iv': _iv_dict[iv_g3_label],
                    'ivl': iv_g3_label,
                }).encode()).decode()
                qp['tg_grp3'] = grp3_enc
                server_store['tg_grp3'] = grp3_enc

        st.divider()
        st.markdown("**📊 채팅방별 카테고리당 종목 갯수** (실제 전송 갯수)")
        _c1, _c2 = st.columns(2)
        with _c1:
            _n_p = st.slider("📱 개인방", min_value=1, max_value=20,
                value=st.session_state.get('tg_send_count_p', 10), key="sl_n_p2")
            st.session_state['tg_send_count_p'] = _n_p
            _n_g2 = st.slider("👥 그룹방 2", min_value=1, max_value=20,
                value=st.session_state.get('tg_send_count_g2', 10), key="sl_n_g2b")
            st.session_state['tg_send_count_g2'] = _n_g2
        with _c2:
            _n_g1 = st.slider("👥 그룹방 1", min_value=1, max_value=20,
                value=st.session_state.get('tg_send_count_g1', 10), key="sl_n_g1b")
            st.session_state['tg_send_count_g1'] = _n_g1
            _n_g3 = st.slider("👥 그룹방 3", min_value=1, max_value=20,
                value=st.session_state.get('tg_send_count_g3', 10), key="sl_n_g3b")
            st.session_state['tg_send_count_g3'] = _n_g3
        st.caption(f"개인방:{_n_p}개 | 그룹방1:{_n_g1}개 | 그룹방2:{_n_g2}개 | 그룹방3:{_n_g3}개")

        st.divider()
        st.markdown("**🖥️ UI 화면 카테고리당 표시 종목 수**")
        _ui_n = st.slider("📊 UI 카테고리당 종목 수", min_value=1, max_value=20,
            value=st.session_state.get('ui_n_per_cat', 10), key="sl_ui_n")
        st.session_state['ui_n_per_cat'] = _ui_n
        st.caption(f"현재 설정: 카테고리당 {_ui_n}개 표시 (실시간 스윙 / 급등전야 / 내일관심 / 중소형주)")

    # ── 🤖 Google AI Studio (Gemini) ──────────────────────────────
    with st.expander("🤖 Google AI 분석 설정 (Gemini)", expanded=False):
        st.caption("종목 카드 'AI 분석' 버튼에서 Google Gemini API로 심층 분석합니다.")
        google_key = st.text_input(
            "Google AI Studio API Key",
            type="password",
            value=st.session_state.get('google_api_key', ''),
            placeholder="AIzaSy...",
            key="google_key_inp"
        )
        _gk_c1, _gk_c2 = st.columns([3, 1])
        with _gk_c1:
            if st.button("💾 API 키 저장", key="btn_gkey_save", use_container_width=True,
                         disabled=not bool(google_key)):
                st.session_state['google_api_key'] = google_key
                _gkey_enc = base64.b64encode(google_key.encode()).decode()
                qp['gkey'] = _gkey_enc
                server_store['google_key'] = _gkey_enc
                st.success("✅ Google API 키 저장됨")
        with _gk_c2:
            if st.button("🗑 삭제", key="btn_gkey_del", use_container_width=True):
                st.session_state['google_api_key'] = ''
                server_store['google_key'] = None
                try:
                    if 'gkey' in qp: del qp['gkey']
                except: pass
                st.rerun()
        ok_google = bool(st.session_state.get('google_api_key'))
        st.markdown(
            f'<div style="padding:6px 10px;font-family:monospace;font-size:11px;'
            f'color:{"#00ff88" if ok_google else "#4a5568"}">{"🟢 Gemini API 등록됨 — 카드에서 AI 심층 분석 가능" if ok_google else "⭕ 키 미등록 — 로컬 분석 사용"}</div>',
            unsafe_allow_html=True
        )
        st.markdown("""<div style="font-family:'Share Tech Mono',monospace;font-size:10px;
color:#4a5568;padding:4px 0;line-height:1.8">
• 키 미등록 시 로컬 KIS 데이터 기반 분석으로 동작<br>
• 발급: aistudio.google.com → Get API Key<br>
• 텔레그램 자동 전송은 로컬 분석 사용 (API 비용 없음)
</div>""", unsafe_allow_html=True)

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
scan_json="{}"; scan_count=0; _scan_json_ready=False
scan_result={'swing':[],'surge':[],'tomorrow':[],'smallmid':[],'ts':'','total':0}
cats={'swing':[],'surge':[],'tomorrow':[],'smallmid':[]}
all_stocks=[]; kospi_stocks=[]; kosdaq_stocks=[]; balance={}

GIST_ID      = _get_secret('GIST_ID')
_gist_active = bool(GIST_ID and st.session_state.auth)

# Gist 모드: auth만 있으면 동작 (kis_token 없어도 됨)
# 직접 KIS 모드: kis_token 필요

def _send_tg_by_cat(token, chat_id, cats_d, iv_lbl, k_n, kd_n, ts_str, total_n, n=10):
    """카테고리별 분할 전송 — 5종목씩 메시지 나눔"""
    is_mkt  = 9 <= int(kst_strftime('%H')) <= 15
    mkt_lbl = '🟢장중' if is_mkt else '🔴장마감'
    _n = max(1, int(n))

    sw  = cats_d.get('swing',[])[:_n]
    su  = cats_d.get('surge',[])[:_n]
    tm  = cats_d.get('tomorrow',[])[:_n]
    sml = cats_d.get('smallmid',[])[:_n]

    def _do_send(text):
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id":chat_id,"text":text,"parse_mode":"HTML"}, timeout=10)
        except: pass

    # 헤더
    _do_send(
        f"📡 <b>K-ALPHA {iv_lbl} 스캔</b> [{ts_str}] {mkt_lbl}\n"
        f"KOSPI {k_n}+KOSDAQ {kd_n}종목\n"
        f"🔥스윙:{len(sw)} ⚡급등:{len(su)} 🌙내일:{len(tm)} 📦중소형:{len(sml)}"
    )
    time.sleep(0.3)

    if not any([sw, su, tm, sml]):
        _do_send("📊 스캔 결과 없음 — 필터 조건 미달")
        return

    def _fmt_stock_card(c):
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

    TG_LIMIT = 3800   # 텔레그램 4096자 제한 — 안전 마진 확보

    def _send_cat(lst, emoji, label):
        """카테고리별 전송. 4096자 초과 시 자동 분할."""
        if not lst: return
        total = len(lst)
        msg_idx = 1          # 현재 메시지 번호
        buf_cards = []       # 현재 버퍼에 쌓인 카드 텍스트 목록
        buf_len   = 0        # 현재 버퍼 총 글자 수

        def _flush_stub(): pass  # 아래에서 직접 인라인 처리

        # 카드별로 버퍼 채우기 → 초과 시 flush → 새 버퍼
        for stock in lst:
            card_txt = _fmt_stock_card(stock)
            card_len = len(card_txt) + 2   # \n\n 포함

            # 버퍼가 있고, 추가하면 초과 → 현재 버퍼 flush
            if buf_cards and (buf_len + card_len > TG_LIMIT):
                # 헤더 생성 (분할 여부는 나중에 결정 — 일단 번호 붙임)
                hdr = f"{emoji} <b>【{label} TOP{total}】 — {msg_idx}부</b>"
                _do_send(hdr + '\n' + '\n\n'.join(buf_cards))
                time.sleep(0.4)
                msg_idx += 1
                buf_cards = []
                buf_len   = 0

            buf_cards.append(card_txt)
            buf_len += card_len

        # 마지막 버퍼 flush
        if buf_cards:
            if msg_idx == 1:
                # 분할 없음 — 헤더 깔끔하게
                hdr = f"{emoji} <b>【{label} TOP{total}】</b>"
            else:
                hdr = f"{emoji} <b>【{label} TOP{total}】 — {msg_idx}부</b>"
            _do_send(hdr + '\n' + '\n\n'.join(buf_cards))
            time.sleep(0.4)

    _send_cat(sw,  '🔥', '실시간 스윙')
    _send_cat(su,  '⚡', '급등전야')
    _send_cat(tm,  '🌙', '내일관심')
    _send_cat(sml, '📦', '중소형주')
    _do_send(f"{'━'*16}\n📊 총 {total_n}종목 스캔완료\n⏱ 다음 전송 {iv_lbl} 후")

if _gist_active or st.session_state.kis_token:
    scan_ref_min   = st.session_state.get('scan_refresh_min', 10)
    # ── 백그라운드 스레드용 설정 동기화 ──
    _bg = get_server_store()
    _bg["scan_refresh_min"] = scan_ref_min
    _bg["scan_blacklist"]   = st.session_state.get('scan_blacklist', set())
    _bg["scan_vol_min"]     = st.session_state.get('scan_vol_min', 50)
    _bg["scan_rsi_min"]     = st.session_state.get('scan_rsi_min', 20)
    _bg["scan_rsi_max"]     = st.session_state.get('scan_rsi_max', 75)
    _bg["ui_n_per_cat"]     = st.session_state.get('ui_n_per_cat', 10)
    _bg["kis_token"]        = st.session_state.get('kis_token')
    _bg["kis_base_url"]     = st.session_state.get('kis_base_url','https://openapi.kis.or.kr')
    _bg["kis_ak"]           = st.session_state.get('kis_ak','')
    _bg["kis_sec"]          = st.session_state.get('kis_sec','')
    _bg["tg_token"]         = st.session_state.get('tg_token','')
    _bg["tg_chat"]          = st.session_state.get('tg_chat','')
    _bg["tg_interval_min"]  = st.session_state.get('tg_interval_min', 10)
    _bg["tg_send_count_p"]  = st.session_state.get('tg_send_count_p', 5)
    for _gn, _gk in [('tg_grp','1'),('tg_grp2','2'),('tg_grp3','3')]:
        _gd = server_store.get(_gn,'')
        if _gd:
            try:
                _gj = json.loads(base64.b64decode(_gd).decode())
                _bg[f"tg_group{_gk}_chat"]   = _gj.get('c','')
                _bg[f"tg_group{_gk}_iv_min"] = _gj.get('iv', 10)
                _bg[f"tg_group{_gk}_en"]     = _gj.get('en', False)
                _bg[f"tg_send_count_g{_gk}"] = st.session_state.get(f'tg_send_count_g{_gk}', 5)
            except: pass
    # 그룹방 1의 key 이름 통일 (tg_group_chat → tg_group1_chat)
    if not _bg.get("tg_group1_chat"):
        _bg["tg_group1_chat"]   = _bg.get("tg_group_chat","")
        _bg["tg_group1_iv_min"] = _bg.get("tg_group_iv_min", 10)
        _bg["tg_group1_en"]     = _bg.get("tg_group_en", False)
    _start_bg_scan_thread()
    iv_min         = st.session_state.get('tg_interval_min', 10)

    ca, cb = st.columns([5,1])
    with cb:
        if st.button("↻", key="btn_ref", help="즉시 갱신"):
            server_store['scan_ts'] = 0
            server_store['force_kis'] = True   # KIS 직접 스캔 강제 실행
            # Gist 캐시 클리어 + KIS 캐시도 초기화
            fetch_gist_scan.clear()
            try: fetch_volume_ranking.clear()
            except: pass
            st.rerun()
    with ca:
        if GIST_ID:
            st.markdown(
                f'<div style="font-family:monospace;font-size:12px;color:#4a5568;padding:2px 0">'
                f'⚡ Gist 백그라운드 · ⟳ 10분 자동폴링 · '
                f'<span style="color:#00ff88">{kst_strftime("%H:%M:%S")}</span></div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div style="font-family:monospace;font-size:12px;color:#4a5568;padding:2px 0">'
                f'📡 KIS 직접 스캔 · ⟳ {scan_ref_min}분 자동갱신 · '
                f'<span style="color:#00ff88">{kst_strftime("%H:%M:%S")}</span></div>',
                unsafe_allow_html=True)

    # ── 1순위: GitHub Gist (즉시, 0초) — force_kis면 스킵 ──
    _force_kis = server_store.get('force_kis', False)
    if _force_kis:
        server_store['force_kis'] = False   # 플래그 즉시 소비
    gist_data = (fetch_gist_scan(GIST_ID) if GIST_ID else None) if not _force_kis else None

    if gist_data:
        # Gist 데이터로 즉시 표시
        scan_result  = gist_data
        scan_count   = gist_data.get('total', 0)
        price_ts     = gist_data.get('ts', kst_strftime("%H:%M:%S"))
        kospi_n   = gist_data.get('kospi_n', 0)
        kosdaq_n  = gist_data.get('kosdaq_n', 0)
        age_sec   = int(time.time() - gist_data.get('updated_at', time.time()))
        age_color  = "#00ff88" if age_sec < 700 else "#ffc800"
        _ref_sec   = scan_ref_min * 60
        next_scan  = max(0, _ref_sec - age_sec)   # 설정 주기 기준 남은 초
        _mkt_now   = is_market_open()
        if _mkt_now:
            if next_scan > 0:
                next_lbl = f"{next_scan//60}분 {next_scan%60}초 후"
            else:
                next_lbl = "곧 갱신"
            mkt_badge = '<span style="color:#00ff88">🟢 장중</span>'
        else:
            is_hol = is_kr_holiday()
            is_wkd = kst_now().weekday() >= 5
            reason = "주말" if is_wkd else ("공휴일" if is_hol else "장마감")
            next_lbl = "수동 요청 시만 갱신"
            mkt_badge = f'<span style="color:#ffc800">🔴 {reason} — 자동스캔 중단</span>'
        st.markdown(
            f'<div style="font-family:monospace;font-size:12px;color:#00d4ff;padding:2px 0">'
            f'⚡ Gist 즉시 로드 · KOSPI {kospi_n}+KOSDAQ {kosdaq_n}종목 · '
            f'<span style="color:{age_color}">{age_sec//60}분 {age_sec%60}초 전 스캔</span>'
            f' · {mkt_badge}'
            f' · 다음갱신 <span style="color:#94a3b8">{next_lbl}</span></div>',
            unsafe_allow_html=True)

        # Gist 경로에서도 텔레그램 버킷 체크를 위해 all_stocks 더미 복원
        # (실제 종목 리스트 없이 card 데이터에서 역산)
        _all_cards = (gist_data.get('swing',[]) + gist_data.get('surge',[]) +
                      gist_data.get('smallmid',[]) + gist_data.get('tomorrow',[]))
        all_stocks = []   # Gist 모드에서는 개별 종목 리스트 없음 — 카드 데이터를 직접 사용
        cats       = {k: gist_data.get(k, []) for k in ['swing','surge','tomorrow','smallmid']}
        kospi_stocks  = [{}] * kospi_n   # 개수만 표시용
        kosdaq_stocks = [{}] * kosdaq_n
        # ── Gist 경로 scan_json 세팅 (NULL 버그 수정) ──
        scan_json        = json.dumps(scan_result, ensure_ascii=False)
        prices_json      = "{}"
        balance_json     = "{}"
        _scan_json_ready = True
        # server_store에도 저장해 캐시 복원 시 사용
        server_store['scan_result'] = scan_result
        server_store['prices_json'] = prices_json
        server_store['balance_json'] = balance_json

    # ── Gist/KIS 모두 없으면 백그라운드 스레드가 저장한 scan_result 복원 ──
    if not scan_result.get('swing') and not scan_result.get('surge') and \
       not scan_result.get('tomorrow') and not scan_result.get('smallmid'):
        _bg_sr = get_server_store().get('scan_result')
        if _bg_sr and (_bg_sr.get('swing') or _bg_sr.get('surge') or
                       _bg_sr.get('tomorrow') or _bg_sr.get('smallmid')):
            _ui_n_f = st.session_state.get('ui_n_per_cat', 10)
            scan_result = {
                **_bg_sr,
                'swing':    _bg_sr.get('swing',   [])[:_ui_n_f],
                'surge':    _bg_sr.get('surge',   [])[:_ui_n_f],
                'tomorrow': _bg_sr.get('tomorrow',[])[:_ui_n_f],
                'smallmid': _bg_sr.get('smallmid',[])[:_ui_n_f],
            }
            if not kospi_stocks: kospi_stocks = [{}] * _bg_sr.get('kospi_n', 0)
            if not kosdaq_stocks: kosdaq_stocks = [{}] * _bg_sr.get('kosdaq_n', 0)

    elif st.session_state.kis_token:
        # ── 2순위: 직접 KIS 스캔 (Gist 없을 때, KIS 연결됐을 때만) ──
        # 장외(주말/공휴일/15:30 이후 8:00 이전)는 캐시 유지
        # ↻ 수동 갱신 시에는 장외에도 스캔 허용 (장마감 시점 분석)
        _direct_mkt = is_market_open()
        _manual_refresh = server_store.get('scan_ts') == 0  # ↻ 버튼으로 초기화됐으면 True
        cache_stale = (time.time() - server_store.get('scan_ts', 0)) > scan_ref_min * 60
        cached = server_store.get('scan_data')
        # 장외 + 캐시 있음 + 수동갱신 아님 → 캐시 유지 (자동 스캔 차단)
        if not _direct_mkt and cached and not _manual_refresh:
            cache_stale = False

        if cached and not cache_stale:
            kospi_stocks  = cached.get('kospi', [])
            kosdaq_stocks = cached.get('kosdaq', [])
            balance       = cached.get('balance', {})
            price_ts      = server_store.get('scan_str', '')
            # ── scan_result를 server_store에서 직접 복원 ──
            _sr = server_store.get('scan_result')
            if _sr:
                scan_result      = _sr
                cats             = {k: scan_result.get(k,[]) for k in ['swing','surge','tomorrow','smallmid']}
                scan_count       = scan_result.get('total', 0)
                scan_json        = json.dumps(scan_result, ensure_ascii=False)
                prices_json      = server_store.get('prices_json', '{}')
                balance_json     = server_store.get('balance_json', '{}')
                _scan_json_ready = True
            if not _direct_mkt and cached.get('is_afterhours'):
                _afh_ts = cached.get('afterhours_ts','')
                st.markdown(
                    f'<div style="font-family:monospace;font-size:12px;color:#ffc800;'
                    f'padding:6px 10px;background:rgba(255,200,0,0.06);'
                    f'border:1px solid rgba(255,200,0,0.2);border-radius:6px;margin:4px 0">'
                    f'🔴 장마감 후 분석 데이터 · 스캔 시각 {_afh_ts} · 장중 데이터와 동일한 기준 적용<br>'
                    f'<span style="color:#64748b;font-size:11px">↻ 버튼으로 현재 시점 재스캔 가능</span>'
                    f'</div>', unsafe_allow_html=True)
        else:
            if not _direct_mkt and not _manual_refresh:
                # 장외인데 캐시 없고 수동갱신도 아님 → 안내만 표시
                _reason = "주말" if kst_now().weekday()>=5 else ("공휴일" if is_kr_holiday() else "장마감")
                st.info(
                    f"🔴 **{_reason}** — 자동 스캔이 비활성화되어 있습니다.\n\n"
                    f"↻ 버튼을 누르면 **장마감 시점 기준으로 분석**합니다.\n"
                    f"(종목별 종가·거래대금 기준 스윙/급등 분류)", icon="💤")
                kospi_stocks=[]; kosdaq_stocks=[]; all_stocks=[]; balance={}
                price_ts = kst_strftime("%H:%M:%S")
            else:
                # 장중 스캔 또는 장외 수동 갱신(↻)
                _is_afterhours_scan = not _direct_mkt
                if _is_afterhours_scan:
                    st.markdown(
                        '<div style="font-family:monospace;font-size:12px;color:#ffc800;'
                        'padding:8px 12px;background:rgba(255,200,0,0.08);'
                        'border:1px solid rgba(255,200,0,0.2);border-radius:6px;margin:4px 0">'
                        '🔴 장마감 후 수동 스캔 중... 종가·거래대금 기준으로 분석합니다.<br>'
                        '<span style="color:#64748b;font-size:11px">'
                        '장마감 이후에는 실시간 체결이 없으므로 종가 기준 분류됩니다.</span>'
                        '</div>', unsafe_allow_html=True)
                else:
                    st.markdown(
                        '<div style="font-family:monospace;font-size:12px;color:#ffc800;'
                        'padding:8px 12px;background:rgba(255,200,0,0.08);'
                        'border:1px solid rgba(255,200,0,0.2);border-radius:6px;margin:4px 0">'
                        '📡 KIS 직접 스캔 중... KOSPI 200 + KOSDAQ 100 병렬 조회 중입니다.<br>'
                        '<span style="color:#64748b;font-size:11px">'
                        'Gist 미설정 시 첫 로드에 30~60초 소요됩니다. GIST_ID 환경변수 설정을 권장합니다.</span>'
                        '</div>', unsafe_allow_html=True)
                _scan_t0 = time.time()
                with st.status("📡 KIS 스캔 중...", expanded=True) as _scan_status:
                    st.write("🔄 KOSPI + KOSDAQ 병렬 조회 중...")
                    _t1 = time.time()
                    import concurrent.futures as _cf
                    # session_state는 스레드 안전하지 않으므로 미리 추출
                    _kt = st.session_state.kis_token
                    _kb = st.session_state.kis_base_url
                    _ka = st.session_state.kis_ak
                    _ks = st.session_state.kis_sec
                    with _cf.ThreadPoolExecutor(max_workers=2) as _ex:
                        _f_kp = _ex.submit(fetch_volume_ranking, _kt, _kb, _ka, _ks, 'J', 200)
                        _f_kd = _ex.submit(fetch_volume_ranking, _kt, _kb, _ka, _ks, 'Q', 100)
                        kospi_stocks  = _f_kp.result()
                        kosdaq_stocks = _f_kd.result()
                    _e1 = round(time.time() - _t1, 1)
                    st.write(f"✅ KOSPI {len(kospi_stocks)}종목 + KOSDAQ {len(kosdaq_stocks)}종목 완료 ({_e1}초)")
                    _e2 = 0  # 병렬이라 별도 측정 불필요

                    st.write("🔄 STEP 3/3 — 잔고 조회 중...")
                    _t3 = time.time()
                    balance = fetch_balance(
                        st.session_state.kis_token, st.session_state.kis_base_url,
                        st.session_state.kis_ak, st.session_state.kis_sec, st.session_state.kis_acc)
                    _e3 = round(time.time() - _t3, 1)
                    _total = round(time.time() - _scan_t0, 1)
                    st.write(f"✅ STEP 3/3 — 잔고 조회 완료 ({_e3}초)")
                    _scan_status.update(
                        label=f"✅ 스캔 완료 — 총 {_total}초 소요 "
                              f"(KOSPI {len(kospi_stocks)} + KOSDAQ {len(kosdaq_stocks)}종목)",
                        state="complete", expanded=False)
                all_stocks = kospi_stocks + kosdaq_stocks
                price_ts   = kst_strftime("%H:%M:%S")
                server_store['scan_data'] = {
                    'kospi': kospi_stocks, 'kosdaq': kosdaq_stocks,
                    'all': all_stocks, 'balance': balance,
                    'is_afterhours': _is_afterhours_scan,
                    'afterhours_ts': price_ts,
                }
                server_store['scan_ts']  = time.time()
                server_store['scan_str'] = price_ts
                # scan_result는 categorize 후 아래에서 server_store에 저장됨
                if _is_afterhours_scan:
                    st.success(f"✅ 장마감 시점 분석 완료 — {price_ts} 기준 종가 데이터")

        st.markdown(f'<div style="font-family:monospace;font-size:12px;color:#00d4ff;padding:2px 0">'
                    f'📊 KOSPI {len(kospi_stocks)}+KOSDAQ {len(kosdaq_stocks)}종목 · {price_ts}</div>',
                    unsafe_allow_html=True)

        # ── 텔레그램 자동 전송 (개인방 + 그룹방 각자 간격 독립) ──
        def _ai_reasons(reasons, rsi, chg, rr, score, grade):
            """K 분석 사유 전체를 텔레그램용 멀티라인 문자열로 변환"""
            risks = []
            if rsi > 72:   risks.append(f'RSI{rsi:.0f}과매수')
            if chg >= 7:   risks.append(f'+{chg:.0f}%급등주의')
            elif chg >= 4: risks.append(f'+{chg:.0f}%눌림대기')
            if rr < 1.5:   risks.append(f'RR{rr}낮음')
            risk_str = '·'.join(risks) if risks else '없음'
            lines = [f"   🛡 {score}점({grade}) | ⚠ {risk_str}"]
            for r in reasons:
                text = r.get('text', '')
                if '[기본적 분석]' in text:
                    lines.append(f"   🏢 {text.replace('[기본적 분석] ','')[:80]}")
                elif '[외부요인]' in text:
                    lines.append(f"   🌐 {text.replace('[외부요인] ','')[:80]}")
                else:
                    lines.append(f"   ▸ {text[:80]}")
            return '\n'.join(lines)

        def _compact_ai(c):
            """카드 dict → K 분석 사유 포함 멀티라인"""
            score = c.get('score', 70); grade = c.get('grade', 'B')
            rsi = c.get('rsiApprox', 50) or 50
            rr  = 1.0
            try: rr = float(str(c.get('rr','1.0')).replace(',',''))
            except: pass
            chg = 0.0
            try: chg = float(str(c.get('change','0%')).replace('%','').replace('+',''))
            except: pass
            reasons = c.get('reasons', [])
            if not reasons:
                tr = 0
                try: tr = int(c.get('vol', 0))
                except: pass
                mkt = c.get('mkt', 'kospi')
                fund_parts = []
                if tr >= 2000: fund_parts.append("기관·외국인 대규모 순매수 추정")
                elif tr >= 800: fund_parts.append("기관 매수세 유입 추정")
                elif tr >= 300: fund_parts.append("외국인·기관 중형 수급 진입 추정")
                else: fund_parts.append("개인 중심 수급 · 단기 모멘텀 주도")
                if chg >= 4: fund_parts.append("단기 실적 개선 뉴스 반응")
                elif chg >= 1: fund_parts.append("점진적 실적 개선 기대")
                fund_parts.append("KOSPI 대형주" if mkt == 'kospi' else "KOSDAQ 중소형주 · 고성장 섹터")
                h = kst_now().hour
                if 9 <= h < 11: macro_p = "오전 장 · 외국인·기관 방향성 구간"
                elif 11 <= h < 13: macro_p = "점심 전후 · 단기 변동성 주의"
                else: macro_p = "오후 장 · 프로그램 매매 구간"
                if chg >= 3: macro_p += " · 금리·환율 우호 또는 섹터 호재"
                reasons = [
                    {'icon':'🏢', 'text': '[기본적 분석] ' + ' · '.join(fund_parts)},
                    {'icon':'🌐', 'text': '[외부요인] ' + macro_p},
                ]
            return _ai_reasons(reasons, rsi, chg, rr, score, grade)


        def _build_tg_lines(iv_label_str, cats_d, k_n, kd_n, ts_str, total_n, n=None):
            """하위호환용 — 직접 _send_tg_by_cat 호출로 대체됨 (dead code)"""
            _n = n if n is not None else 10
            is_mkt  = 9 <= int(kst_strftime('%H')) <= 15
            mkt_lbl = '🟢장중' if is_mkt else '🔴장마감'
            def fmt_card(c):
                try: p = int(str(c.get('price','0')).replace(',',''))
                except: p = 0
                buy=int(p*0.995); stop=int(p*0.97); tgt=int(p*1.10)
                rr=round((tgt-p)/(p-stop+1),1) if p>0 else 3.3
                vol=c.get('vol',0)
                try: vol=int(vol)
                except: pass
                pct=c.get('change','0%'); icon='🔴' if c.get('grade')=='S' else '🟡'
                score=c.get('score',70); grade=c.get('grade','B')
                chg=0.0
                try: chg=float(str(pct).replace('%','').replace('+',''))
                except: pass
                risk='+{:.0f}%급등주의'.format(chg) if chg>=7 else ('없음')
                lines=[f"{icon} <b>{c['name']}</b> ({c['code']})",
                       f"   💰 현재가: {p:,}원 {pct} | 거래대금 {vol:,}억",
                       f"   📈 매입가: {buy:,}원 | 손절: {stop:,}원 | RR {rr}",
                       f"   🛡 {score}점({grade}) | ⚠ {risk}"]
                for r in c.get('reasons',[]):
                    txt=r.get('text','') if isinstance(r,dict) else str(r)
                    if '[기본적 분석]' in txt: lines.append(f"   🏢 {txt.replace('[기본적 분석] ','')[:100]}")
                    elif '[외부요인]' in txt:  lines.append(f"   🌐 {txt.replace('[외부요인] ','')[:100]}")
                    else:                       lines.append(f"   ▸ {txt[:80]}")
                return '\n'.join(lines)
            sw=cats_d.get('swing',[])[:_n]; su=cats_d.get('surge',[])[:_n]
            tm=cats_d.get('tomorrow',[])[:_n]; sml=cats_d.get('smallmid',[])[:_n]
            lines=[f"📡 <b>K-ALPHA {iv_label_str} 스캔</b> [{ts_str}] {mkt_lbl}\n"
                   f"KOSPI {k_n}+KOSDAQ {kd_n}종목\n━━━━━━━━━━━━━━━━"]
            if sw: lines.append(f"🔥 <b>[실시간 스윙 TOP{len(sw)}]</b>"); [lines.append(fmt_card(c)) for c in sw]
            if su: lines.append(f"\n⚡ <b>[급등전야 TOP{len(su)}]</b>"); [lines.append(fmt_card(c)) for c in su]
            if tm: lines.append(f"\n🌙 <b>[내일관심 TOP{len(tm)}]</b>"); [lines.append(fmt_card(c)) for c in tm]
            if sml: lines.append(f"\n📦 <b>[중소형주 TOP{len(sml)}]</b>"); [lines.append(fmt_card(c)) for c in sml]
            if not any([sw,su,tm,sml]): lines.append("📊 스캔 결과 없음")
            lines.append(f"━━━━━━━━━━━━━━━━\n📊 {total_n}종목 스캔 완료 · 다음 {iv_label_str} 후")
            return "\n\n".join(lines)

    _tg_tok   = st.session_state.get('tg_token','')
    _tg_chat  = st.session_state.get('tg_chat','')
    _iv_p     = st.session_state.get('tg_interval_min', 10)
    _iv_p_lbl = st.session_state.get('tg_interval_label','10분')
    # server_store에서 그룹방 설정 복원 (매번 최신값 우선)
    _tg_grp_ss = server_store.get('tg_grp','')
    if _tg_grp_ss:
        try:
            _grp_ss = json.loads(base64.b64decode(_tg_grp_ss).decode())
            st.session_state['tg_group_enabled']        = _grp_ss.get('en', False)
            st.session_state['tg_group_chat']           = _grp_ss.get('c','')
            st.session_state['tg_group_interval_min']   = _grp_ss.get('iv', 10)
            st.session_state['tg_group_interval_label'] = _grp_ss.get('ivl','10분')
        except: pass
    _grp_en   = st.session_state.get('tg_group_enabled', False)
    _grp_chat = st.session_state.get('tg_group_chat','')
    _iv_g     = st.session_state.get('tg_group_interval_min', 10)
    _iv_g_lbl = st.session_state.get('tg_group_interval_label','10분')
    _now_ts   = kst_strftime('%H:%M:%S')
    _k_n = len(kospi_stocks); _kd_n = len(kosdaq_stocks)

    def _gist_ai_stocks(n):
        return ((scan_result.get('swing',[]) + scan_result.get('surge',[]))[:n] +
                (scan_result.get('tomorrow',[]) + scan_result.get('smallmid',[]))[:n])

    # ── 스캔 데이터 유무 체크 (빈 결과면 bucket 선점 않음) ──
    _has_data = bool(
        scan_result.get('swing') or scan_result.get('surge') or
        scan_result.get('tomorrow') or scan_result.get('smallmid')
    )
    # 디버그: 전송 조건 표시
    _bkt_g_cur = int(time.time() // (_iv_g * 60))
    _bkt_p_cur = int(time.time() // (_iv_p * 60))
    st.caption(
        f"🔍 전송상태 | 개인방: tok={'✅' if _tg_tok else '❌'} chat={'✅' if _tg_chat else '❌'} "
        f"data={'✅' if _has_data else '❌'} bkt={_bkt_p_cur}(저장:{st.session_state.get('_tg_bkt_p','없음')}) | "
        f"그룹1: en={'✅' if _grp_en else '❌'} chat={'✅' if _grp_chat else '❌'} "
        f"iv={_iv_g}분 bkt={_bkt_g_cur}(저장:{st.session_state.get('_tg_bkt_g','없음')})"
    )

    # 개인방 — 독립 bucket
    if not st.session_state.get('tg_all_enabled', True):
        st.caption("⛔ 메시지 발송 비활성화 중")
    else:
        if _tg_tok and _tg_chat and _has_data:
            _bkt_p = int(time.time() // (_iv_p * 60))
            if _bkt_p != st.session_state.get('_tg_bkt_p', -1):
                st.session_state['_tg_bkt_p'] = _bkt_p
                _n_p = st.session_state.get('tg_send_count_p', 10)
                _send_tg_by_cat(_tg_tok, _tg_chat, scan_result, _iv_p_lbl,
                                _k_n, _kd_n, _now_ts, scan_count, n=_n_p)
                st.toast(f"📱 개인방 전송 완료 ({_now_ts})", icon="✅")
                if st.session_state.get('tg_ai_send_p', True):
                    _send_tg_ai(_tg_tok, _tg_chat, _gist_ai_stocks(_n_p), _iv_p_lbl, _now_ts)

    # 그룹방 1 — 독립 bucket
    if _tg_tok and _grp_en and _grp_chat and _has_data:
        _bkt_g = int(time.time() // (_iv_g * 60))
        if _bkt_g != st.session_state.get('_tg_bkt_g', -1):
            st.session_state['_tg_bkt_g'] = _bkt_g
            _n_g1 = st.session_state.get('tg_send_count_g1', 10)
            _send_tg_by_cat(_tg_tok, _grp_chat, scan_result, _iv_g_lbl,
                            _k_n, _kd_n, _now_ts, scan_count, n=_n_g1)
            st.toast(f"👥 그룹방 전송 완료 ({_now_ts})", icon="✅")
            if st.session_state.get('tg_ai_send_g1', False):
                _send_tg_ai(_tg_tok, _grp_chat, _gist_ai_stocks(_n_g1), _iv_g_lbl, _now_ts)

    # 그룹방 2 — 독립 bucket
    _grp2_en_g   = st.session_state.get('tg_group2_enabled', False)
    _grp2_chat_g = st.session_state.get('tg_group2_chat','')
    _iv_g2_g     = st.session_state.get('tg_group2_interval_min', 30)
    _iv_g2_g_lbl = st.session_state.get('tg_group2_interval_label','30분')
    if _tg_tok and _grp2_en_g and _grp2_chat_g and _has_data:
        _bkt_g2g = int(time.time() // (_iv_g2_g * 60))
        if _bkt_g2g != st.session_state.get('_tg_bkt_g2g', -1):
            st.session_state['_tg_bkt_g2g'] = _bkt_g2g
            _n_g2 = st.session_state.get('tg_send_count_g2', 10)
            _send_tg_by_cat(_tg_tok, _grp2_chat_g, scan_result, _iv_g2_g_lbl,
                            _k_n, _kd_n, _now_ts, scan_count, n=_n_g2)
            st.toast(f"👥 그룹방 2 전송 완료 ({_now_ts})", icon="✅")
            if st.session_state.get('tg_ai_send_g2', False):
                _send_tg_ai(_tg_tok, _grp2_chat_g, _gist_ai_stocks(_n_g2), _iv_g2_g_lbl, _now_ts)

    # 그룹방 3 — 독립 bucket
    _grp3_en_g   = st.session_state.get('tg_group3_enabled', False)
    _grp3_chat_g = st.session_state.get('tg_group3_chat','')
    _iv_g3_g     = st.session_state.get('tg_group3_interval_min', 30)
    _iv_g3_g_lbl = st.session_state.get('tg_group3_interval_label','30분')
    if _tg_tok and _grp3_en_g and _grp3_chat_g and _has_data:
        _bkt_g3g = int(time.time() // (_iv_g3_g * 60))
        if _bkt_g3g != st.session_state.get('_tg_bkt_g3g', -1):
            st.session_state['_tg_bkt_g3g'] = _bkt_g3g
            _n_g3 = st.session_state.get('tg_send_count_g3', 10)
            _send_tg_by_cat(_tg_tok, _grp3_chat_g, scan_result, _iv_g3_g_lbl,
                            _k_n, _kd_n, _now_ts, scan_count, n=_n_g3)
            st.toast(f"👥 그룹방 3 전송 완료 ({_now_ts})", icon="✅")
            if st.session_state.get('tg_ai_send_g3', False):
                _send_tg_ai(_tg_tok, _grp3_chat_g, _gist_ai_stocks(_n_g3), _iv_g3_g_lbl, _now_ts)

    # 스캔 결과 분류 — 직접 KIS 스캔 경로만 실행 (Gist/캐시 경로는 이미 세팅됨)
    if not _scan_json_ready and all_stocks:
        _ui_n = st.session_state.get('ui_n_per_cat', 10)
        cats = categorize_stocks(
            all_stocks,
            st.session_state.scan_blacklist,
            st.session_state.scan_vol_min,
            st.session_state.scan_rsi_min,
            st.session_state.scan_rsi_max,
            swing_vol_min=st.session_state.get('scan_swing_vol_min', 100),
            swing_pct_min=st.session_state.get('scan_swing_pct_min', 0.3),
            swing_pct_max=st.session_state.get('scan_swing_pct_max', 6.0),
            surge_pct_min=st.session_state.get('scan_surge_pct_min', 4.0),
            tomorrow_pct_min=st.session_state.get('scan_tomorrow_pct_min', -2.0),
            tomorrow_pct_max=st.session_state.get('scan_tomorrow_pct_max', 2.5),
            smallmid_vol_min=st.session_state.get('scan_smallmid_vol_min', 50),
            smallmid_vol_max=st.session_state.get('scan_smallmid_vol_max', 700),
            smallmid_pct_min=st.session_state.get('scan_smallmid_pct_min', -2.0),
            smallmid_pct_max=st.session_state.get('scan_smallmid_pct_max', 4.0),
            top_n=_ui_n,
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
            'kospi_n': len(kospi_stocks),
            'kosdaq_n': len(kosdaq_stocks),
            'updated_at': time.time(),
            'market_open': is_market_open(),
        }
        scan_json = json.dumps(scan_result, ensure_ascii=False)

        # ── Gist에 scan_result 저장 (scan_worker가 읽어서 텔레그램 전송) ──
        _gist_id2  = _get_secret('GIST_ID')
        _gh_tok2   = _get_secret('GH_TOKEN')
        if _gist_id2 and _gh_tok2:
            try:
                _gr = requests.patch(
                    f"https://api.github.com/gists/{_gist_id2}",
                    headers={'Authorization':f'token {_gh_tok2}',
                             'Accept':'application/vnd.github.v3+json'},
                    json={"files":{"kalpha_scan.json":{"content":scan_json}}},
                    timeout=10)
                if _gr.status_code == 200:
                    st.toast("☁️ Gist 저장 완료", icon="✅")
                else:
                    st.caption(f"⚠ Gist 저장 실패: {_gr.status_code}")
            except Exception as _ge:
                st.caption(f"⚠ Gist 저장 오류: {_ge}")

        # 현재가 딕셔너리
        prices = {s['code']:{'price':s['price'],'change':s['change'],
                              'changePct':s['changePct'],'up':s['up']}
                  for s in all_stocks}
        prices_json = json.dumps(prices)
        if balance and not balance.get('error'): balance_json = json.dumps(balance)

        # ── server_store에 scan_result 직접 저장 (다음 캐시 복원 시 사용) ──
        server_store['scan_result']  = scan_result
        server_store['prices_json']  = prices_json
        server_store['balance_json'] = balance_json
        if server_store.get('scan_data'):
            server_store['scan_data']['scan_result']  = scan_result
            server_store['scan_data']['prices_json']  = prices_json
            server_store['scan_data']['balance_json'] = balance_json
        _scan_json_ready = True

    # 상태 표시
    _dm = is_market_open()
    _dm_lbl = '🟢 장중' if _dm else ('🔴 주말' if kst_now().weekday()>=5 else ('🔴 공휴일' if is_kr_holiday() else '🔴 장마감'))
    st.markdown(f"""<div style="font-family:monospace;font-size:12px;color:#00d4ff;padding:2px 0;line-height:2">
📊 KOSPI {len(kospi_stocks)}종목 + KOSDAQ {len(kosdaq_stocks)}종목 · <span style="color:#00ff88">{kst_strftime('%H:%M:%S')}</span> · {_dm_lbl}<br>
🔍 실시간스윙 {len(cats['swing'])}개 · 급등전야 {len(cats['surge'])}개 · 내일관심 {len(cats['tomorrow'])}개 · 중소형주 {len(cats['smallmid'])}개 · <span style='color:#94a3b8'>UI표시 {st.session_state.get('ui_n_per_cat',10)}개설정</span>
</div>""", unsafe_allow_html=True)

    # ── 텔레그램 자동 알림 (개인방 + 그룹방 각자 간격 독립) ──
    _tg_tok2   = st.session_state.get('tg_token','')
    _tg_chat2  = st.session_state.get('tg_chat','')
    _iv_p2     = st.session_state.get('tg_interval_min', 10)
    _iv_p2_lbl = st.session_state.get('tg_interval_label','10분')
    _grp_en2   = st.session_state.get('tg_group_enabled', False)
    _grp_chat2 = st.session_state.get('tg_group_chat','')
    _iv_g2     = st.session_state.get('tg_group_interval_min', 30)
    _iv_g2_lbl = st.session_state.get('tg_group_interval_label','30분')
    _now2      = kst_strftime('%H:%M:%S')
    _kn2  = len(kospi_stocks); _kdn2 = len(kosdaq_stocks)

    def _compact_ai2(s, card):
        """원시 stock dict + card dict → K 분석 사유 포함 멀티라인"""
        score = s.get('score', 70); grade = s.get('grade', 'B')
        rsi   = s.get('rsiApprox', 50) or 50
        rr    = 1.0
        try: rr = float(str(card.get('rr','1.0')).replace(',',''))
        except: pass
        chg = s.get('changePct', 0) or 0
        risks = []
        if rsi > 72:   risks.append(f'RSI{rsi:.0f}과매수')
        if chg >= 7:   risks.append(f'+{chg:.0f}%급등주의')
        elif chg >= 4: risks.append(f'+{chg:.0f}%눌림대기')
        if rr < 1.5:   risks.append(f'RR{rr}낮음')
        risk_str = '·'.join(risks) if risks else '없음'
        lines = [f"   🛡 {score}점({grade}) | ⚠ {risk_str}"]
        for r in card.get('reasons', []):
            text = r.get('text', '')
            if '[기본적 분석]' in text:
                lines.append(f"   🏢 {text.replace('[기본적 분석] ','')[:80]}")
            elif '[외부요인]' in text:
                lines.append(f"   🌐 {text.replace('[외부요인] ','')[:80]}")
            else:
                lines.append(f"   ▸ {text[:80]}")
        return '\n'.join(lines)

    def _fmt2(s, cat):
        pct = s.get('changePct',0); sign = '+' if pct>=0 else ''
        card = build_card(s, cat); icon = '🔴' if s.get('grade')=='S' else '🟡'
        _pr = s.get('price',0)
        try: _pr = int(_pr)
        except: pass
        return (f"{icon} {s['name']} ({s['code']})\n"
                f"   💰 현재가: {_pr:,}원 {sign}{pct:.2f}% | 거래대금 {s.get('trAmt',0):,}억\n"
                f"   📈 매입가: {card['buy']}원 | 손절: {card['stop']}원 | RR {card['rr']}\n"
                f"{_compact_ai2(s, card)}")

    def _mk_msg2(iv_lbl, all_s, k_n, kd_n, ts_str, n=None):
        is_mkt = 9 <= int(kst_strftime('%H')) <= 15
        mkt_lbl = '🟢장중' if is_mkt else '🔴장마감'
        _n2 = n if n is not None else 10
        # UI와 동일한 scan_result 데이터 사용 (cats는 라이브 스캔 결과라 다를 수 있음)
        def _fmt_card(c):
                """UI 카드 완전 동일 포맷"""
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

        swing_list    = scan_result.get('swing',[])[:_n2]
        surge_list    = scan_result.get('surge',[])[:_n2]
        tomorrow_list = scan_result.get('tomorrow',[])[:_n2]
        smallmid_list = scan_result.get('smallmid',[])[:_n2]
        ls = [f"📡 <b>K-ALPHA {iv_lbl} 스캔</b> [{ts_str}] {mkt_lbl}\n"
              f"KOSPI {k_n}+KOSDAQ {kd_n}종목\n━━━━━━━━━━━━━━━━"]
        if swing_list:
            ls.append(f"🔥 <b>[실시간 스윙 TOP{len(swing_list)}]</b>")
            for c in swing_list: ls.append(_fmt_card(c))
        if surge_list:
            ls.append(f"\n⚡ <b>[급등전야 TOP{len(surge_list)}]</b>")
            for c in surge_list: ls.append(_fmt_card(c))
        if tomorrow_list:
            ls.append(f"\n🌙 <b>[내일관심 TOP{len(tomorrow_list)}]</b>")
            for c in tomorrow_list: ls.append(_fmt_card(c))
        if smallmid_list:
            ls.append(f"\n📦 <b>[중소형주 TOP{len(smallmid_list)}]</b>")
            for c in smallmid_list: ls.append(_fmt_card(c))
        if not any([swing_list, surge_list, tomorrow_list, smallmid_list]):
            ls.append("📊 스캔 결과 없음 — 필터 조건 미달")
        ls.append(f"━━━━━━━━━━━━━━━━\n📊 {len(all_s)}종목 스캔 완료 · 다음 알림 {iv_lbl} 후")
        return "\n\n".join(ls)

    def _kis_ai_stocks(n):
        return ((scan_result.get('swing',[]) + scan_result.get('surge',[]))[:n] +
                (scan_result.get('tomorrow',[]) + scan_result.get('smallmid',[]))[:n])

    # scan_result 데이터 유무 (Gist 모드에서 all_stocks=[]이어도 전송 가능)
    _has_sr2 = bool(
        scan_result.get('swing') or scan_result.get('surge') or
        scan_result.get('tomorrow') or scan_result.get('smallmid')
    )
    # 종목 수 표시용 (Gist 모드에선 scan_result.total 사용)
    _all_for_count = all_stocks if all_stocks else [None] * scan_result.get('total', 0)

    # ── 송출 시간 범위 체크 헬퍼 ──
    def _in_time_window(start_h, end_h):
        """현재 KST 시각이 [start_h:00 ~ end_h:59] 범위이면 True"""
        h = kst_now().hour
        if start_h <= end_h:
            return start_h <= h <= end_h
        else:  # 자정 넘는 경우 (예: 22~06)
            return h >= start_h or h <= end_h

    # 전체 발송 ON/OFF 체크
    if not st.session_state.get('tg_all_enabled', True):
        st.caption("⛔ 메시지 발송 비활성화 중")
    else:
        # 개인방 — 독립 bucket (카테고리별 분할 전송)
        _has_sr_p = bool(scan_result.get('swing') or scan_result.get('surge') or
                         scan_result.get('tomorrow') or scan_result.get('smallmid'))
        if _tg_tok2 and _tg_chat2 and (all_stocks or _has_sr_p):
            _bkt_p2 = int(time.time() // (_iv_p2 * 60))
            if _bkt_p2 != st.session_state.get('_tg_bkt_p', -1):
                st.session_state['_tg_bkt_p'] = _bkt_p2
                _p_start = st.session_state.get('tg_send_start_p', 9)
                _p_end   = st.session_state.get('tg_send_end_p', 15)
                if _in_time_window(_p_start, _p_end):
                    try:
                        _n_kp = st.session_state.get('tg_send_count_p', 10)
                        _send_tg_by_cat(_tg_tok2, _tg_chat2, scan_result,
                                        _iv_p2_lbl, _kn2, _kdn2, _now2,
                                        scan_result.get('total', len(all_stocks)), n=_n_kp)
                        st.toast(f"📱 개인방 전송 완료 ({_now2})", icon="✅")
                        if st.session_state.get('tg_ai_send_p', True):
                            _send_tg_ai(_tg_tok2, _tg_chat2, _kis_ai_stocks(_n_kp), _iv_p2_lbl, _now2)
                    except Exception as e:
                        st.caption(f"개인방 텔레그램 오류: {e}")
                else:
                    st.caption(f"⏸ 개인방 — 송출 시간 외 ({_p_start:02d}:00~{_p_end:02d}:59 KST)")

        # 그룹방 — 독립 bucket
        if _tg_tok2 and _grp_en2 and _grp_chat2 and (all_stocks or _has_sr2):
            _bkt_g2 = int(time.time() // (_iv_g2 * 60))
            if _bkt_g2 != st.session_state.get('_tg_bkt_g2_b', -1):
                st.session_state['_tg_bkt_g2_b'] = _bkt_g2
                _g1_start = st.session_state.get('tg_send_start_g1', 9)
                _g1_end   = st.session_state.get('tg_send_end_g1', 15)
                if _in_time_window(_g1_start, _g1_end):
                    try:
                        _n_kg1 = st.session_state.get('tg_send_count_g1', 10)
                        msg2g = _mk_msg2(_iv_g2_lbl, _all_for_count, _kn2, _kdn2, _now2, n=_n_kg1)
                        r2g = requests.post(f"https://api.telegram.org/bot{_tg_tok2}/sendMessage",
                            json={"chat_id":_grp_chat2,"text":msg2g,"parse_mode":"HTML"}, timeout=10)
                        if r2g.json().get('ok'):
                            st.toast(f"👥 그룹방 전송 완료 ({_now2})", icon="✅")
                            if st.session_state.get('tg_ai_send_g1', False):
                                _send_tg_ai(_tg_tok2, _grp_chat2, _kis_ai_stocks(_n_kg1), _iv_g2_lbl, _now2)
                    except Exception as e:
                        st.caption(f"그룹방 텔레그램 오류: {e}")
                else:
                    st.caption(f"⏸ 그룹방 1 — 송출 시간 외 ({_g1_start:02d}:00~{_g1_end:02d}:59 KST)")

        # 그룹방 2 — 독립 bucket
        _grp2_en2   = st.session_state.get('tg_group2_enabled', False)
        _grp2_chat2 = st.session_state.get('tg_group2_chat','')
        _iv_g2b     = st.session_state.get('tg_group2_interval_min', 30)
        _iv_g2b_lbl = st.session_state.get('tg_group2_interval_label','30분')
        if _tg_tok2 and _grp2_en2 and _grp2_chat2 and (all_stocks or _has_sr2):
            _bkt_g2b = int(time.time() // (_iv_g2b * 60))
            if _bkt_g2b != st.session_state.get('_tg_bkt_g2b', -1):
                st.session_state['_tg_bkt_g2b'] = _bkt_g2b
                _g2_start = st.session_state.get('tg_send_start_g2', 9)
                _g2_end   = st.session_state.get('tg_send_end_g2', 15)
                if _in_time_window(_g2_start, _g2_end):
                    try:
                        _n_kg2 = st.session_state.get('tg_send_count_g2', 10)
                        msg2g2 = _mk_msg2(_iv_g2b_lbl, _all_for_count, _kn2, _kdn2, _now2, n=_n_kg2)
                        r2g2 = requests.post(f"https://api.telegram.org/bot{_tg_tok2}/sendMessage",
                            json={"chat_id":_grp2_chat2,"text":msg2g2,"parse_mode":"HTML"}, timeout=10)
                        if r2g2.json().get('ok'):
                            st.toast(f"👥 그룹방 2 전송 완료 ({_now2})", icon="✅")
                            if st.session_state.get('tg_ai_send_g2', False):
                                _send_tg_ai(_tg_tok2, _grp2_chat2, _kis_ai_stocks(_n_kg2), _iv_g2b_lbl, _now2)
                    except Exception as e:
                        st.caption(f"그룹방 2 텔레그램 오류: {e}")
                else:
                    st.caption(f"⏸ 그룹방 2 — 송출 시간 외 ({_g2_start:02d}:00~{_g2_end:02d}:59 KST)")

        # 그룹방 3 — 독립 bucket
        _grp3_en2   = st.session_state.get('tg_group3_enabled', False)
        _grp3_chat2 = st.session_state.get('tg_group3_chat','')
        _iv_g3b     = st.session_state.get('tg_group3_interval_min', 30)
        _iv_g3b_lbl = st.session_state.get('tg_group3_interval_label','30분')
        if _tg_tok2 and _grp3_en2 and _grp3_chat2 and (all_stocks or _has_sr2):
            _bkt_g3b = int(time.time() // (_iv_g3b * 60))
            if _bkt_g3b != st.session_state.get('_tg_bkt_g3b', -1):
                st.session_state['_tg_bkt_g3b'] = _bkt_g3b
                _g3_start = st.session_state.get('tg_send_start_g3', 9)
                _g3_end   = st.session_state.get('tg_send_end_g3', 15)
                if _in_time_window(_g3_start, _g3_end):
                    try:
                        _n_kg3 = st.session_state.get('tg_send_count_g3', 10)
                        msg2g3 = _mk_msg2(_iv_g3b_lbl, all_stocks, _kn2, _kdn2, _now2, n=_n_kg3)
                        r2g3 = requests.post(f"https://api.telegram.org/bot{_tg_tok2}/sendMessage",
                            json={"chat_id":_grp3_chat2,"text":msg2g3,"parse_mode":"HTML"}, timeout=10)
                        if r2g3.json().get('ok'):
                            st.toast(f"👥 그룹방 3 전송 완료 ({_now2})", icon="✅")
                            if st.session_state.get('tg_ai_send_g3', False):
                                _send_tg_ai(_tg_tok2, _grp3_chat2, _kis_ai_stocks(_n_kg3), _iv_g3b_lbl, _now2)
                    except Exception as e:
                        st.caption(f"그룹방 3 텔레그램 오류: {e}")
                else:
                    st.caption(f"⏸ 그룹방 3 — 송출 시간 외 ({_g3_start:02d}:00~{_g3_end:02d}:59 KST)")

# ════ 6. HTML 터미널 ════
if not os.path.exists("app.html"):
    st.error("app.html 파일을 GitHub 저장소에 업로드하세요."); st.stop()

# scan_json 최종 안전장치 — scan_result와 동기화
if scan_result.get('swing') or scan_result.get('surge') or scan_result.get('tomorrow') or scan_result.get('smallmid'):
    scan_json = json.dumps(scan_result, ensure_ascii=False)
@st.cache_data(ttl=86400, show_spinner=False)
def _load_app_html():
    with open("app.html","r",encoding="utf-8") as f: return f.read()
html = _load_app_html()
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
window.__UI_N_CAT__     = {st.session_state.get('ui_n_per_cat', 10)};
window.__ORIG_COUNTS__  = null;
window.__SCAN_COUNT__   = {scan_count};
window.__TG_TOKEN__     = {json.dumps(st.session_state.get('tg_token',''))};
window.__TG_CHAT__      = {json.dumps(st.session_state.get('tg_chat',''))};
window.__TG_INTERVAL__  = {st.session_state.get('tg_interval_min',10)*60*1000};
window.__GOOGLE_API_KEY__ = {json.dumps(st.session_state.get('google_api_key',''))};
window.__TG_AI_COUNT__  = {st.session_state.get('tg_ai_count', 5)};
window.__SCAN_VOL_MIN__ = {st.session_state.get('scan_vol_min',50)};
window.__SCAN_RSI_MIN__ = {st.session_state.get('scan_rsi_min',20)};
window.__SCAN_RSI_MAX__ = {st.session_state.get('scan_rsi_max',75)};
</script>"""
html=html.replace("</head>",inject+"\n</head>")
# 설정 서버 저장 (PC ↔ Mobile 연동)
server_store['ss'] = {k: st.session_state.get(k) for k in _SYNC_KEYS if st.session_state.get(k) is not None}

components.html(html,height=15000,scrolling=False)
