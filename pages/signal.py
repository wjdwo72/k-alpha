import streamlit as st
import streamlit.components.v1 as components
import os, json, sys

# store.py는 k-alpha 루트에 있음
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

# server_store에서 KIS 크리덴셜 읽기 (관리자앱과 공유, 다른 탭도 OK)
_ss = get_server_store()
_ak  = _ss.get('kis_ak',  '') or st.session_state.get('kis_ak',  '') or ''
_sec = _ss.get('kis_sec', '') or st.session_state.get('kis_sec', '') or ''
_acc = _ss.get('kis_acc', '') or st.session_state.get('kis_acc', '') or ''
_tok = _ss.get('kis_token','') or st.session_state.get('kis_token','') or ''
_bu  = _ss.get('kis_base_url','') or st.session_state.get('kis_base_url','') or ''
_server_val = 'mock' if 'vts' in _bu else 'real'
_has_creds  = bool(_ak and _sec and _acc)

_inject = f"""<script>
// ── K-ALPHA 관리앱 연동 주입 ──
(function() {{
  var _ak  = {json.dumps(_ak)};
  var _sec = {json.dumps(_sec)};
  var _acc = {json.dumps(_acc)};
  var _tok = {json.dumps(_tok)};
  var _srv = {json.dumps(_server_val)};
  var _has = {json.dumps(_has_creds)};

  // 1) 관리앱 토큰 전역 보관 (window.onload 이전 실행)
  if (_tok) window.__ADMIN_TOKEN__  = _tok;
  if (_srv) window.__ADMIN_SERVER__ = _srv;

  // 2) fetch 가로채기: 프록시 /token 요청에 크리덴셜 자동 주입
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

  // 3) DOM 로드 후: 입력 필드 채우기 + 연동 배지 삽입
  function _onReady() {{
    var eAk  = document.getElementById('appKey');
    var eSec = document.getElementById('secretKey');
    var eAcc = document.getElementById('acctNo');
    var eSrv = document.getElementById('serverType');
    if (eAk  && _ak)  eAk.value  = _ak;
    if (eSec && _sec) eSec.value = _sec;
    if (eAcc && _acc) eAcc.value = _acc;
    if (eSrv && _srv) eSrv.value = _srv;

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

html = html.replace('</head>', _inject + '\n</head>')

components.html(html, height=960, scrolling=True)
