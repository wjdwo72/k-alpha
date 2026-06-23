"""
K-Alpha 패턴 시그널 페이지
signal.html을 읽어서 Supabase 크리덴셜을 주입 후 렌더링
"""
import streamlit as st
import streamlit.components.v1 as components
import os

st.set_page_config(
    page_title="K-Alpha 패턴 시그널",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 사이드바·헤더 숨김
st.markdown("""<style>
  #MainMenu,header,footer,[data-testid="stSidebar"]{display:none!important}
  .block-container{padding:0!important;margin:0!important;max-width:100%!important}
</style>""", unsafe_allow_html=True)

def _get_secret(key, default=''):
    try:
        v = st.secrets.get(key, '')
        if v: return str(v)
    except: pass
    return os.environ.get(key, default)

# signal.html 읽기
_html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'signal.html')
try:
    with open(_html_path, encoding='utf-8') as f:
        html_content = f.read()
except FileNotFoundError:
    st.error("signal.html 파일을 찾을 수 없습니다.")
    st.stop()

# Supabase 크리덴셜 주입
sb_url = _get_secret('SUPABASE_URL')
sb_key = _get_secret('SUPABASE_SERVICE_KEY') or _get_secret('SUPABASE_KEY')
html_content = html_content.replace('__SUPABASE_URL__', sb_url)
html_content = html_content.replace('__SUPABASE_KEY__', sb_key)

# 전체화면 렌더링
components.html(html_content, height=900, scrolling=True)
