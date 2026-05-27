import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Overview · Quant Terminal",
    page_icon="●",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
#MainMenu, footer, header,
[data-testid="stToolbar"],
[data-testid="stSidebar"],
[data-testid="collapsedControl"]
{ visibility: hidden !important; height: 0 !important; display: none !important; }
.stApp { background: #0E0E10 !important; padding: 0 !important; }
.block-container { padding: 0 !important; max-width: 100% !important; margin: 0 !important; }
iframe { border: none !important; width: 100% !important; }
</style>
""", unsafe_allow_html=True)

with open("frontend/overview.html", "r", encoding="utf-8") as f:
    html = f.read()

components.html(html, height=1800, scrolling=True)
