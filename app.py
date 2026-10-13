import streamlit as st
import pandas as pd
import numpy as np
import requests
import psycopg2
from datetime import datetime, timezone
import json
import streamlit.components.v1 as components

# ==============================================================================
# 1. PAGE SETUP & GLASSMORPHIC STYLING
# ==============================================================================
st.set_page_config(
    page_title="AURA // XAU/USD Spot Terminal",
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

    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #D4AF37 0%, #FFDF00 100%) !important;
        color: #080A0E !important;
        font-weight: 700 !important;
        border: none !important;
        box-shadow: 0 0 14px rgba(212, 175, 55, 0.25) !important;
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. NEON DATABASE UTILITIES
# ==============================================================================
def get_db_conn():
    db_url = st.secrets.get("DATABASE_URL", "")
    if db_url:
        if "channel_binding=" in db_url:
            db_url = db_url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        try:
            return psycopg2.connect(db_url)
        except Exception:
            return None
    return None

def get_config_val(key, default=""):
    conn = get_db_conn()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT key_value FROM gold_config WHERE key_name = %s;", (key,))
                res = cur.fetchone()
                if res: default = res[0]
            conn.close()
        except Exception:
            if conn: conn.close()
    return default

def set_config_val(key, val):
    conn = get_db_conn()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE gold_config SET key_value = %s, updated_at = CURRENT_TIMESTAMP WHERE key_name = %s;", (str(val), key))
                conn.commit()
            conn.close()
        except Exception:
            if conn: conn.close()

# ==============================================================================
# 3. HIGH-FREQUENCY PRICE & SESSION ENGINES
# ==============================================================================
@st.cache_data(ttl=1)
def get_live_gold_price():
    # 1. Binance PAXG Physical 1oz Spot Ticker (Sub-second tick, 24/7)
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT", timeout=1.0)
        if r.status_code == 200:
            price = float(r.json()['price'])
            if price > 1000: return price
    except Exception:
        pass

    # 2. Finnhub OANDA Spot Gold Fallback
    if FINNHUB_KEY:
        try:
            r = requests.get(f"https://finnhub.io/api/v1/quote?symbol=OANDA:XAU_USD&token={FINNHUB_KEY}", timeout=1.5)
            if r.status_code == 200:
                price = float(r.json().get('c', 0))
                if price > 1000: return price
        except Exception:
            pass

    return 2650.00

def get_current_gold_session():
    utc_hour = datetime.now(timezone.utc).hour
    if 0 <= utc_hour < 7:
        return "ASIAN RANGE", "🟡 MEDIUM"
    elif 7 <= utc_hour < 13:
        return "LONDON EXPANSION", "🔥 HIGH"
    elif 13 <= utc_hour < 20:
        return "NEW YORK OVERLAP", "⚡ PEAK"
    else:
        return "OFF-HOURS / ROLLOVER", "⚪ LOW"

def get_self_learning_adjustment(strategy_name, session_name):
    conn = get_db_conn()
    if not conn: return 0, 50.0
    try:
        query = """
            SELECT pnl FROM gold_positions 
            WHERE status = 'CLOSED' AND strategy = %s AND session = %s 
            ORDER BY closed_at DESC LIMIT 20;
        """
        df = pd.read_sql(query, conn, params=(strategy_name, session_name))
        conn.close()
        if len(df) >= 5:
            win_count = len(df[df['pnl'] > 0])
            win_rate = (win_count / len(df)) * 100.0
            return int((win_rate - 50.0) * 0.4), win_rate
    except Exception:
        if conn: conn.close()
    return 0, 50.0

# ==============================================================================
# 4. HEADER BAR
# ==============================================================================
session_name, liquidity_level = get_current_gold_session()
is_autopilot = (get_config_val("gold_autopilot", "FALSE") == "TRUE")

c_head1, c_head2 = st.columns([2, 1])
with c_head1:
    st.markdown("<div class='gold-title'>AURA // GOLD SPOT TERMINAL</div>", unsafe_allow_html=True)
    st.caption("Institutional High-Frequency Execution Engine | Dedicated Asset: XAU/USD")
with c_head2:
    st.markdown(f"""
        <div style='text-align: right; margin-top: 10px;'>
            <span class='session-badge'>SESSION: <b style='color:#FFDF00;'>{session_name}</b></span>
            <span class='session-badge' style='margin-left:8px;'>VOLATILITY: <b>{liquidity_level}</b></span>
        </div>
    """, unsafe_allow_html=True)

st.divider()

# ==============================================================================
# 5. LIVE METRICS FRAGMENT (Sub-Second UI Ticks)
# ==============================================================================
@st.fragment(run_every=2)
def render_live_gold_metrics():
    live_p = get_live_gold_price()
    
    conn = get_db_conn()
    positions = []
    realized_pnl = 0.0
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT action, qty, entry_price, status, pnl FROM gold_positions;")
                for r in cur.fetchall():
                    if r[3] == 'CLOSED' and r[4] is not None:
                        realized_pnl += float(r[4])
                    elif r[3] == 'OPEN':
                        positions.append({'action': r[0], 'qty': float(r[1]), 'entry': float(r[2])})
            conn.close()
        except Exception:
            if conn: conn.close()

    unrealized_pnl = 0.0
    for pos in positions:
        diff = (live_p - pos['entry']) if pos['action'] == 'BUY' else (pos['entry'] - live_p)
        unrealized_pnl += (diff * pos['qty'])

    starting_equity = 100000.0
    total_equity = starting_equity + realized_pnl + unrealized_pnl
    total_pnl = realized_pnl + unrealized_pnl

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("XAU/USD SPOT", f"${live_p:,.2f}", "Raw Spread: 0.12 pts")
    m2.metric("PORTFOLIO EQUITY", f"${total_equity:,.2f}", f"${total_pnl:+,.2f} Total Net")
    m3.metric("UNREALIZED P&L", f"${unrealized_pnl:+,.2f}", f"Active Trades: {len(positions)}")
    m4.metric("AUTOPILOT ENGINE", "ONLINE 🟢" if is_autopilot else "MANUAL 🟡", f"Threshold: {get_config_val('gold_min_confidence', '80')}%")

render_live_gold_metrics()

# ==============================================================================
# 6. MASTER TABS
# ==============================================================================
tab_desk, tab_matrix, tab_positions, tab_settings = st.tabs([
    "01 // EXECUTION DESK",
    "02 // STRATEGY MATRIX & SETUPS",
    "03 // POSITIONS & AUDIT LOG",
    "04 // AUTOPILOT CONTROLS"
])

with tab_desk:
    col_chart, col_order = st.columns([2.2, 1.0])
    with col_chart:
        components.html("""
        <div class="tradingview-widget-container" style="height:550px;width:100%">
          <div id="tv_gold_chart" style="height:550px;width:100%"></div>
          <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
          <script type="text/javascript">
          new TradingView.widget({
            "autosize": true,
            "symbol": "TVC:GOLD",
            "interval": "5",
            "timezone": "Etc/UTC",
            "theme": "dark",
            "style": "1",
            "locale": "en",
            "toolbar_bg": "#080A0E",
            "enable_publishing": false,
            "hide_side_toolbar": false,
            "container_id": "tv_gold_chart"
          });
          </script>
        </div>
        """, height=560)
        
    with col_order:
        st.markdown("### ⚡ Fast Order Ticket")
        current_p = get_live_gold_price()
        
        ord_side = st.radio("Order Direction:", ["BUY / LONG 🟢", "SELL / SHORT 🔴"], horizontal=True)
        ord_qty = st.number_input("Position Size (Standard Lots - 100 oz):", min_value=0.01, max_value=50.0, value=0.50, step=0.05)
        
        sl_points = st.number_input("Stop Loss Distance ($/oz):", min_value=1.0, value=5.0, step=0.5)
        tp_points = st.number_input("Take Profit Distance ($/oz):", min_value=2.0, value=12.
