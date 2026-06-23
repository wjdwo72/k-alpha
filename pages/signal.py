import streamlit as st
import streamlit.components.v1 as components
import os, json

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

# 관리자앱 세션에서 KIS 크리덴셜 읽기
_ak   = st.session_state.get('kis_ak',  '') or ''
_sec  = st.session_state.get('kis_sec', '') or ''
_acc  = st.session_state.get('kis_acc', '') or ''
_env  = st.session_state.get('kis_env', '실전투자') or '실전투자'
_base = st.session_state.get('kis_base_url', '') or ''
_server_val = 'mock' if '모의' in _env or 'vts' in _base else 'real'

# API 설정 섹션 숨김 + 자동 연결 주입
_inject = f"""<style>
/* API 설정 & 종목 패널 숨김 */
.api-section {{ display:none!important; }}
.panel-title {{ display:none!important; }}
</style>
<script>
(function() {{
  var ak  = {json.dumps(_ak)};
  var sec = {json.dumps(_sec)};
  var acc = {json.dumps(_acc)};
  var srv = {json.dumps(_server_val)};
  function _autoConnect() {{
    // signal.html 의 실제 input ID: appKey, secretKey, acctNo, serverType
    var eAk  = document.getElementById('appKey');
    var eSec = document.getElementById('secretKey');
    var eAcc = document.getElementById('acctNo');
    var eSrv = document.getElementById('serverType');
    if (!eAk) {{ setTimeout(_autoConnect, 300); return; }}
    if (ak)  eAk.value  = ak;
    if (sec) eSec.value = sec;
    if (acc) eAcc.value = acc;
    if (srv && eSrv) eSrv.value = srv;
    if (ak && sec && acc && typeof connectKIS === 'function') {{
      connectKIS();
    }}
  }}
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', _autoConnect);
  }} else {{
    setTimeout(_autoConnect, 300);
  }}
}})();
</script>"""

html = html.replace('</head>', _inject + '\n</head>')

components.html(html, height=960, scrolling=True)
