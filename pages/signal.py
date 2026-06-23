import streamlit as st
import streamlit.components.v1 as components
import os

st.set_page_config(
    page_title="K-Alpha 패턴 매매 시그널",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Streamlit UI 완전 숨김
st.markdown("""<style>
  #MainMenu,header,footer,
  [data-testid="stSidebar"],
  [data-testid="stToolbar"],
  [data-testid="stDecoration"],
  [data-testid="stStatusWidget"],
  .stDeployButton,
  section[data-testid="stSidebarContent"],
  div[data-testid="collapsedControl"],
  .css-1544g2n, .css-18e3th9,
  .block-container { display:none!important; }
  html,body,[data-testid="stAppViewContainer"] {
    background:#0a0e1a!important;
    padding:0!important; margin:0!important;
  }
</style>""", unsafe_allow_html=True)

_html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'signal.html')
try:
    with open(_html_path, encoding='utf-8') as f:
        html_content = f.read()
except FileNotFoundError:
    st.error("signal.html 파일을 찾을 수 없습니다.")
    st.stop()

components.html(html_content, height=980, scrolling=True)
