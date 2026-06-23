import streamlit as st
import streamlit.components.v1 as components
import os

st.set_page_config(
    page_title="K-Alpha 패턴 매매 시그널",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Streamlit chrome 숨김 — block-container는 숨기면 iframe도 사라지므로 유지
st.markdown("""<style>
  #MainMenu, header, footer,
  [data-testid="stSidebar"],
  [data-testid="stToolbar"],
  [data-testid="stDecoration"],
  [data-testid="stStatusWidget"],
  .stDeployButton,
  div[data-testid="collapsedControl"] { display:none!important; }

  html, body,
  [data-testid="stAppViewContainer"],
  [data-testid="stAppViewBlockContainer"],
  .main, .block-container {
    background:#0a0e1a!important;
    padding:0!important;
    margin:0!important;
    max-width:100%!important;
  }
  iframe { border:none!important; display:block!important; }
</style>""", unsafe_allow_html=True)

_html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'signal.html')
try:
    with open(_html_path, encoding='utf-8') as f:
        html_content = f.read()
except FileNotFoundError:
    st.error("signal.html 파일을 찾을 수 없습니다.")
    st.stop()

components.html(html_content, height=960, scrolling=True)
