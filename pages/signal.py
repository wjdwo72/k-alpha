import streamlit as st
import streamlit.components.v1 as components
import os, json, sys, base64

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
_server_val = 'mock' if 'vts' in _bu else 'real'
_has_creds  = bool(_ak and _sec and _acc)

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

_inject = f"""<script>
// ── K-ALPHA 관리앱 연동 주입 ──
(function() {{
  var _ak  = {json.dumps(_ak)};
  var _sec = {json.dumps(_sec)};
  var _acc = {json.dumps(_acc)};
  var _tok = {json.dumps(_tok)};
  var _srv = {json.dumps(_server_val)};
  var _has = {json.dumps(_has_creds)};

  // 1) 관리앱 토큰 전역 보관
  if (_tok) window.__ADMIN_TOKEN__  = _tok;
  if (_srv) window.__ADMIN_SERVER__ = _srv;

  // 2) 관리앱 스캔 결과 전역 보관
  window.__ADMIN_SCAN__ = {json.dumps(_admin_scan)};

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

    // 관리앱 스캔 결과로 KALPHA_STOCKS 업데이트
    var sc = window.__ADMIN_SCAN__;
    if (sc && typeof KALPHA_STOCKS !== 'undefined') {{
      var _hasScan = (sc.swing && sc.swing.length > 0) ||
                     (sc.surge && sc.surge.length > 0) ||
                     (sc.tmr   && sc.tmr.length   > 0) ||
                     (sc.small && sc.small.length  > 0);
      if (_hasScan) {{
        if (sc.swing && sc.swing.length > 0) KALPHA_STOCKS.swing = sc.swing;
        if (sc.surge && sc.surge.length > 0) KALPHA_STOCKS.surge = sc.surge;
        if (sc.tmr   && sc.tmr.length   > 0) KALPHA_STOCKS.tmr   = sc.tmr;
        if (sc.small && sc.small.length > 0) KALPHA_STOCKS.small = sc.small;
        if (sc.per   && sc.per.length   > 0) KALPHA_STOCKS.per   = sc.per;
        if (typeof updateKTabCounts === 'function') updateKTabCounts();
        if (typeof renderStockList  === 'function') renderStockList();
      }}
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
#appKey, #secretKey, #acctNo, #serverType,
.api-section > label,
.api-section > button,
#syncStatus,
.api-section > div:first-of-type {{ display:none!important; }}
.panel-title {{ display:none!important; }}
</style>"""

# 크리덴셜 없으면 헤더 배지에만 표시 (경고창 제거 — iframe이 동작 중)

html = html.replace('</head>', _inject + '\n</head>')

components.html(html, height=960, scrolling=True)
