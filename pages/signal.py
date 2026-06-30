import streamlit as st
import streamlit.components.v1 as components
import os, json, sys, base64, requests as _req

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from store import get_server_store

st.set_page_config(
    page_title="K-Alpha 패턴 매매 시그널",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""<style>
  #MainMenu, header, footer,
  [data-testid="stSidebar"],
  [data-testid="stToolbar"],
  [data-testid="stDecoration"],
  div[data-testid="collapsedControl"] { display:none!important; }
  html, body, .main, .block-container,
  [data-testid="stAppViewContainer"] {
    background:#0a0e1a!important;
    padding:0!important; margin:0!important; max-width:100%!important;
  }
  iframe { border:none!important; display:block!important; }
</style>""", unsafe_allow_html=True)

_html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'signal.html')
try:
    with open(_html_path, encoding='utf-8') as f:
        html = f.read()
except FileNotFoundError:
    st.error("signal.html 파일을 찾을 수 없습니다.")
    st.stop()

# server_store에서 KIS 크리덴셜 + 텔레그램 + 스캔 결과 읽기 (관리앱과 공유)
_ss = get_server_store()
_ak  = _ss.get('kis_ak',  '') or st.session_state.get('kis_ak',  '') or ''
_sec = _ss.get('kis_sec', '') or st.session_state.get('kis_sec', '') or ''
_acc = _ss.get('kis_acc', '') or st.session_state.get('kis_acc', '') or ''
_tok = _ss.get('kis_token','') or st.session_state.get('kis_token','') or ''
_bu  = _ss.get('kis_base_url','') or st.session_state.get('kis_base_url','') or ''

# server_store가 비어있으면(멀티워커) Supabase scan_cache id=2 에서 KIS 설정 읽기
if not _ak:
    try:
        import os as _os
        _sb_url = st.secrets.get('SUPABASE_URL','')
        _sb_key = st.secrets.get('SUPABASE_SERVICE_KEY','')
        if _sb_url and _sb_key:
            _r2 = _req.get(
                f"{_sb_url}/rest/v1/scan_cache?id=eq.2&select=data",
                headers={"apikey": _sb_key, "Authorization": f"Bearer {_sb_key}"},
                timeout=5,
            )
            if _r2.ok:
                _rows = _r2.json()
                if _rows and _rows[0].get('data'):
                    _kd = _rows[0]['data']
                    _ak  = _kd.get('kis_ak','')
                    _sec = _kd.get('kis_sec','')
                    _acc = _kd.get('kis_acc','')
                    _bu  = ('https://openapivts.koreainvestment.com:29443'
                            if _kd.get('kis_env','실전투자') == '모의투자'
                            else 'https://openapi.kis.or.kr')
    except:
        pass
_server_val = 'mock' if 'vts' in _bu else 'real'
_has_creds  = bool(_ak and _sec and _acc)
_is_mock    = _server_val == 'mock'

# KIS WebSocket approval_key 발급 (서버사이드 — CORS 불필요)
_api_base = 'https://openapivts.koreainvestment.com:29443' if _is_mock else 'https://openapi.kis.or.kr'
_ws_base  = 'wss://openapivts.koreainvestment.com:29443'  if _is_mock else 'wss://openapi.kis.or.kr'
_ws_key   = ''
_ws_url   = ''
if _ak and _sec:
    try:
        _r = _req.post(
            f'{_api_base}/oauth2/Approval',
            json={'grant_type': 'client_credentials', 'appkey': _ak, 'secretkey': _sec},
            timeout=5
        )
        if _r.ok:
            _ws_key = _r.json().get('approval_key', '')
            _ws_url = f'{_ws_base}/websocket/domestic-stock/v1/stk-sise'
    except Exception:
        pass

# 텔레그램 설정 (관리앱 → signal 페이지 연동)
# app.py는 server_store['tg']에 base64({t:token,c:chat}) 형태로 저장함
def _decode_tg(enc):
    try:
        if enc:
            d = json.loads(base64.b64decode(enc).decode())
            return d.get('t',''), d.get('c','')
    except: pass
    return '', ''

_tg_enc   = _ss.get('tg','') or ''
_tg_token, _tg_chat = _decode_tg(_tg_enc)
if not _tg_token:  # server_store에 없으면 session_state 폴백
    _tg_token = st.session_state.get('tg_token','') or ''
    _tg_chat  = st.session_state.get('tg_chat', '') or ''

# 그룹방
_tg_grp_enc = _ss.get('tg_grp','') or ''
_, _tg_chat2 = _decode_tg(_tg_grp_enc)
if not _tg_chat2:
    _tg_chat2 = st.session_state.get('tg_group_chat','') or ''
# signal.html TG_CFG 포맷: {token, channels:[{id, label, enabled}]}
_tg_channels = []
if _tg_chat:
    _tg_channels.append({'id': _tg_chat,  'label': '관리앱 개인방', 'enabled': True})
if _tg_chat2 and _tg_chat2 != _tg_chat:
    _tg_channels.append({'id': _tg_chat2, 'label': '관리앱 그룹방', 'enabled': True})
_tg_cfg = {'token': _tg_token, 'channels': _tg_channels}

# 관리앱 스캔 결과 → signal.html KALPHA_STOCKS 포맷으로 변환
def _to_stock_list(items):
    seen, out = set(), []
    for s in (items or []):
        c = s.get('code','')
        n = s.get('name','')
        if c and c not in seen:
            seen.add(c)
            out.append({'code': c, 'name': n})
    return out

_scan = _ss.get('scan_result') or {}
_admin_scan = {
    'swing': _to_stock_list(_scan.get('swing', [])),
    'surge': _to_stock_list(_scan.get('surge', [])),
    'tmr':   _to_stock_list(_scan.get('tomorrow', [])),
    'small': _to_stock_list(_scan.get('smallmid', [])),
    'per':   _to_stock_list(_scan.get('per', [])),
    'ts':    _scan.get('ts', ''),
    'total': _scan.get('total', 0),
}
_has_scan = any(len(v) > 0 for v in [_admin_scan['swing'], _admin_scan['surge'],
                                      _admin_scan['tmr'], _admin_scan['small']])

# ── 서버사이드 전체 종목 리스트 (KRX + Naver 복수 폴백) ──
@st.cache_data(ttl=3600)
def _fetch_all_stocks():
    """KOSPI+KOSDAQ 전체 종목 코드+이름 딕셔너리 반환"""
    import datetime
    name_map = {}
    hdrs_krx = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd',
    }

    # 최근 거래일 탐색 (오늘 포함 최대 7일 전까지)
    def _recent_trd_dd():
        d = datetime.date.today()
        for _ in range(10):
            if d.weekday() < 5:  # 월~금
                return d.strftime('%Y%m%d')
            d -= datetime.timedelta(days=1)
        return datetime.date.today().strftime('%Y%m%d')

    trd_dd = _recent_trd_dd()

    # 1차: KRX 데이터포털 API (KOSPI + KOSDAQ)
    for mkt_id in ['STK', 'KSQ']:
        for attempt_dd in [trd_dd, (datetime.date.today() - datetime.timedelta(days=3)).strftime('%Y%m%d')]:
            try:
                r = _req.post(
                    'http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd',
                    headers=hdrs_krx,
                    data={'bld': 'dbms/MDC/STAT/standard/MDCSTAT01901', 'locale': 'ko_KR',
                          'mktId': mkt_id, 'trdDd': attempt_dd, 'money': '1', 'csvxls_isNo': 'false'},
                    timeout=15
                )
                items = r.json().get('output', []) if r.ok else []
                for item in items:
                    code = item.get('ISU_SRT_CD', '')
                    name = item.get('ISU_ABBRV', '')
                    if code and name:
                        name_map[code] = name
                if items:
                    break
            except Exception:
                pass

    # 2차: Naver 주식 전체 목록 (KOSPI/KOSDAQ 페이지별 fetch)
    if len(name_map) < 100:
        hdrs_nv = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://m.stock.naver.com'}
        for mkt in ['KOSPI', 'KOSDAQ']:
            for page in range(1, 30):
                try:
                    r2 = _req.get(
                        f'https://m.stock.naver.com/api/stocks?market={mkt}&type=STOCK&page={page}&pageSize=100',
                        headers=hdrs_nv, timeout=10
                    )
                    if not r2.ok:
                        break
                    data = r2.json()
                    items2 = data if isinstance(data, list) else data.get('stocks', data.get('items', []))
                    if not items2:
                        break
                    for s in items2:
                        code = s.get('itemCode') or s.get('code') or ''
                        name = s.get('itemName') or s.get('name') or ''
                        if code and name:
                            name_map[code] = name
                except Exception:
                    break

    return name_map

_all_stocks = _fetch_all_stocks()

# ── 서버사이드 현재가 일괄 fetch (CORS 우회) ──
@st.cache_data(ttl=60)  # 1분 캐시
def _fetch_prices_server(codes_tuple):
    """Naver /basic API로 종목 현재가 일괄 조회 (서버사이드 — CORS 없음)"""
    prices = {}
    hdrs = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://m.stock.naver.com'}
    for code in codes_tuple:
        try:
            r = _req.get(f'https://m.stock.naver.com/api/stock/{code}/basic',
                         headers=hdrs, timeout=5)
            if r.ok:
                d = r.json()
                def _n(s): return float(str(s or '0').replace(',','')) if s else 0
                price = _n(d.get('closePrice'))
                if price > 0:
                    chg_str = d.get('compareToPreviousClosePrice','0')
                    ratio   = float(d.get('fluctuationsRatio', 0) or 0)
                    chg     = _n(chg_str) * (-1 if ratio < 0 else 1)
                    prices[code] = {'price': price, 'change': chg, 'changePct': ratio}
        except Exception:
            pass
    return prices

# KALPHA_STOCKS 코드 목록 수집 (서버사이드 현재가용)
_scan_codes = set()
for _cat in ['swing','surge','tomorrow','smallmid','per']:
    for _s in (_scan.get(_cat) or []):
        if _s.get('code'): _scan_codes.add(_s['code'])
# 기본 주요 종목 추가
for _c in ['005930','000660','035420','247540','373220','086520','196170']:
    _scan_codes.add(_c)

_server_prices = _fetch_prices_server(tuple(sorted(_scan_codes))) if _scan_codes else {}

_hide_api_css = """
#appKey, #secretKey, #acctNo, #serverType,
.api-section > label,
.api-section > button,
#syncStatus,
.api-section > div:first-of-type { display:none!important; }
""" if _has_creds else ""

_inject = f"""<script>
// ── K-ALPHA 관리앱 연동 주입 ──
(function() {{
  var _ak  = {json.dumps(_ak)};
  var _sec = {json.dumps(_sec)};
  var _acc = {json.dumps(_acc)};
  var _tok = {json.dumps(_tok)};
  var _srv = {json.dumps(_server_val)};
  var _has = {json.dumps(_has_creds)};
  var _bu  = {json.dumps(_bu or 'https://openapi.kis.or.kr')};

  // 1) 관리앱 토큰 + 크리덴셜 전역 보관 (현재가 직접 조회용)
  if (_tok) window.__ADMIN_TOKEN__    = _tok;
  if (_srv) window.__ADMIN_SERVER__   = _srv;
  if (_bu)  window.__ADMIN_BASE_URL__ = _bu;
  if (_ak)  window.__ADMIN_AK__  = _ak;

  // KIS WebSocket (서버사이드 발급 approval_key — CORS 없이 실시간 체결가)
  window.__KIS_WS_KEY__ = {json.dumps(_ws_key)};
  window.__KIS_WS_URL__ = {json.dumps(_ws_url)};
  if (_sec) window.__ADMIN_SEC__ = _sec;

  // 2) 관리앱 스캔 결과 전역 보관
  window.__ADMIN_SCAN__ = {json.dumps(_admin_scan)};

  // 서버사이드 전체 종목 리스트 → NAME_MAP 주입 (KOSPI+KOSDAQ 전종목 검색 가능)
  window.__SERVER_NAME_MAP__ = {json.dumps(_all_stocks)};
  window.addEventListener('load', function() {{
    if (typeof NAME_MAP !== 'undefined' && window.__SERVER_NAME_MAP__) {{
      Object.assign(NAME_MAP, window.__SERVER_NAME_MAP__);
    }}
  }});

  // 서버사이드 현재가 주입 (CORS 우회 — 1분 캐시)
  window.__SERVER_PRICES__ = {json.dumps(_server_prices)};
  // stockList 가격 업데이트 함수 (signal.html의 updateStockPrice 또는 직접 적용)
  window.addEventListener('load', function() {{
    var sp = window.__SERVER_PRICES__;
    if (!sp || !Object.keys(sp).length) return;
    // stockList에 서버가격 반영
    if (typeof stockList !== 'undefined') {{
      stockList.forEach(function(s) {{
        if (sp[s.code]) {{
          s.price      = sp[s.code].price;
          s.change     = sp[s.code].change;
          s.changePct  = sp[s.code].changePct;
        }}
      }});
    }}
    // 현재 선택 종목 현재가 덮어쓰기
    if (typeof currentStock !== 'undefined' && currentStock && sp[currentStock.code]) {{
      var p = sp[currentStock.code];
      var el = document.getElementById('currentPrice');
      var cl = document.getElementById('priceChange');
      if (el) el.textContent = p.price.toLocaleString() + '원';
      if (cl) {{
        var sign = p.change >= 0 ? '+' : '';
        cl.textContent = sign + p.changePct.toFixed(2) + '%';
        cl.style.color = p.change >= 0 ? '#ef4444' : '#3b82f6';
      }}
    }}
    if (typeof renderStockList === 'function') renderStockList();
  }});

  // 3-a) 텔레그램 설정 주입 (관리앱 설정 → signal.html TG_CFG)
  (function() {{
    var _tgCfg = {json.dumps(_tg_cfg)};
    if (_tgCfg.token) {{
      // localStorage 선점 (TG_CFG 변수 초기화 전에 세팅)
      try {{
        localStorage.setItem('tgCfg', JSON.stringify(_tgCfg));
        localStorage.setItem('TG_CFG', JSON.stringify(_tgCfg));
      }} catch(e) {{}}
    }}
  }})();

  // 3) fetch 가로채기: 프록시 /token 요청에 크리덴셜 자동 주입
  if (_has) {{
    var _origFetch = window.fetch;
    window.fetch = function(url, opts) {{
      try {{
        if (typeof url === 'string' && /localhost:9001\/token/.test(url)) {{
          var u = new URL(url);
          if (!u.searchParams.get('appkey'))    u.searchParams.set('appkey',    _ak);
          if (!u.searchParams.get('appsecret')) u.searchParams.set('appsecret', _sec);
          if (!u.searchParams.get('acct'))      u.searchParams.set('acct',      _acc);
          if (!u.searchParams.get('_server'))   u.searchParams.set('_server',   _srv);
          url = u.toString();
        }}
      }} catch(e) {{}}
      return _origFetch.apply(this, [url, opts]);
    }};
  }}

  // 4) DOM 로드 후: 입력 채우기 + 관리앱 스캔 데이터로 KALPHA_STOCKS 덮어쓰기
  function _onReady() {{
    // 입력 필드
    var eAk  = document.getElementById('appKey');
    var eSec = document.getElementById('secretKey');
    var eAcc = document.getElementById('acctNo');
    var eSrv = document.getElementById('serverType');
    if (eAk  && _ak)  eAk.value  = _ak;
    if (eSec && _sec) eSec.value = _sec;
    if (eAcc && _acc) eAcc.value = _acc;
    if (eSrv && _srv) eSrv.value = _srv;

    // 관리앱 스캔 결과로 KALPHA_STOCKS 전체 덮어쓰기 (0인 카테고리도 반영)
    var sc = window.__ADMIN_SCAN__;
    if (sc && typeof KALPHA_STOCKS !== 'undefined' && sc.ts) {{
      // ts(타임스탬프)가 있으면 관리앱이 최소 1회 스캔한 것 → 전체 덮어쓰기
      KALPHA_STOCKS.swing = sc.swing || [];
      KALPHA_STOCKS.surge = sc.surge || [];
      KALPHA_STOCKS.tmr   = sc.tmr   || [];
      KALPHA_STOCKS.small = sc.small || [];
      KALPHA_STOCKS.per   = sc.per   || [];
      if (typeof updateKTabCounts === 'function') updateKTabCounts();
      if (typeof renderStockList  === 'function') renderStockList();
    }}

    // 연동 배지 삽입
    var hdr = document.querySelector('.token-status');
    if (hdr && !document.getElementById('admin-link-badge')) {{
      var badge = document.createElement('span');
      badge.id = 'admin-link-badge';
      badge.style.cssText = [
        'margin-left:10px','padding:2px 10px','border-radius:10px',
        'font-size:10px','font-weight:700','letter-spacing:.5px',
        _has
          ? 'background:rgba(16,185,129,0.15);border:1px solid #10b981;color:#10b981'
          : 'background:rgba(245,158,11,0.15);border:1px solid #f59e0b;color:#f59e0b'
      ].join(';');
      badge.textContent = _has ? '✅ K-ALPHA 관리앱 연동됨' : '⚠️ 관리앱 미연결';
      hdr.insertBefore(badge, hdr.firstChild);
    }}
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', _onReady);
  }} else {{
    setTimeout(_onReady, 100);
  }}

}})();
</script>
<style>
{_hide_api_css}
.panel-title {{ display:none!important; }}
</style>"""

# 크리덴셜 없으면 헤더 배지에만 표시 (경고창 제거 — iframe이 동작 중) v3

html = html.replace('</head>', _inject + '\n</head>')


components.html(html, height=980, scrolling=True)
