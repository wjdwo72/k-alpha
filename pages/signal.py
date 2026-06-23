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

# K-Alpha 동기화 버튼 행 + syncStatus 제거 (프록시 미연결 경고 제거)
html = html.replace(
    '<div style="display:flex;gap:4px;margin-top:4px">\n        <button class="btn btn-primary" style="flex:1;background:linear-gradient(90deg,#7c3aed,#06b6d4)" onclick="syncKAlpha(true)">🔄 K-Alpha 동기화</button>\n        <button class="btn btn-primary" style="flex:0 0 auto;background:#2d4a6e;font-size:11px;padding:6px 8px" onclick="openKAlphaEditor()" title="종목 직접 편집">✏️</button>\n      </div>\n      <div id="syncStatus" style="font-size:10px;color:var(--text3);margin-top:4px;text-align:center"></div>',
    '<div id="syncStatus" style="display:none"></div>'
)

# 자동 자격증명 주입 스크립트를 </body> 직전에 삽입
_inject = f"""<script>
(function() {{
  var ak  = {json.dumps(_ak)};
  var sec = {json.dumps(_sec)};
  var acc = {json.dumps(_acc)};
  var srv = {json.dumps(_server_val)};
  function _fill() {{
    var eAk  = document.getElementById('inp-appkey');
    var eSec = document.getElementById('inp-secret');
    var eAcc = document.getElementById('inp-account');
    var eSrv = document.getElementById('serverType');
    if (!eAk) return setTimeout(_fill, 200);
    if (ak)  eAk.value  = ak;
    if (sec) eSec.value = sec;
    if (acc) eAcc.value = acc;
    if (srv && eSrv) eSrv.value = srv;
    // 크리덴셜이 있으면 자동 연결
    if (ak && sec && acc) {{
      if (typeof connectKIS === 'function') connectKIS();
    }}
  }}
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', _fill);
  }} else {{ _fill(); }}
}})();
</script>"""

html = html.replace('</body>', _inject + '\n</body>')

components.html(html, height=960, scrolling=True)
