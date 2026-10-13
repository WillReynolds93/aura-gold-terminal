import streamlit as st
import pandas as pd
import numpy as np
import requests
import psycopg2
from datetime import datetime, timezone, timedelta
import json
import streamlit.components.v1 as components

# ==============================================================================
# 1. PAGE SETUP & GLASSMORPHIC STYLING
# ==============================================================================
st.set_page_config(
    page_title="AURA // XAU/USD Institutional Gold Terminal",
    page_icon="🟡",
    layout="wide",
    initial_sidebar_state="expanded"
)

FINNHUB_KEY = st.secrets.get("FINNHUB_API_KEY", "")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=JetBrains+Mono:wght@400;700&display=swap');
    
    .stApp {
        background-color: #080A0E;
        color: #E6EDF3;
        font-family: 'Space Grotesk', sans-serif;
    }
    
    [data-testid="stSidebar"] {
        background-color: #0F1218 !important;
        border-right: 1px solid rgba(255, 215, 0, 0.15) !important;
    }

    .gold-title {
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 700;
        font-size: 2.2rem;
        background: linear-gradient(135deg, #FFDF00 0%, #D4AF37 50%, #FFFFFF 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -0.5px;
    }
    
    .session-badge {
        background: #141822;
        border: 1px solid rgba(212, 175, 55, 0.3);
        border-radius: 6px;
        padding: 6px 14px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.82rem;
        display: inline-block;
    }

    .macro-card {
        background: #11141C;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        padding: 14px;
        text-align: center;
        margin-bottom: 10px;
    }

    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #D4AF37 0%, #FFDF00 100%) !important;
        color: #080A0E !important;
        font-weight: 700 !important;
        border: none !important;
        box-shadow: 0 0 14px rgba(212, 175, 55, 0.25) !important;
    }
</style>
""",
