import sys, os
sys.path.insert(0, '.')
os.environ.setdefault('STREAMLIT_SERVER_HEADLESS', 'true')
import streamlit as st; st.cache_data = lambda *a,**kw:(lambda f:f)
from utils.code33_engine import get_code33_data
r = get_code33_data('ADI')
print('Rev labels:', r['rev_labels'])
print('Rev YoY:', r['rev_yoy'])
print('Rev prior vals:', r.get('rev_prior_vals', 'not in output'))
print('Rev curr vals:', r.get('rev_curr_vals', 'not in output'))
