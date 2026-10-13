import os
import sys
import time
import requests
import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# --- DUMMY HTTP SERVER (Keeps free cloud web hosts awake) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"AURA Gold 24/7 Scanner Active")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# --- DATABASE CONNECTION ---
def get_db_connection():
    if not DATABASE_URL:
        return None
    clean_url = DATABASE_URL
    if "channel_binding=" in clean_url:
        clean_url = clean_url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    try:
        return psycopg2.connect(clean_url)
    except Exception as e:
        print(f"[DB ERROR] {e}")
        return None

def init_tables(conn):
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gold_positions (
                    id SERIAL PRIMARY KEY,
                    session VARCHAR(25),
                    action VARCHAR(10),
                    qty DOUBLE PRECISION,
                    entry_price DOUBLE PRECISION,
                    stop_loss DOUBLE PRECISION,
                    take_profit DOUBLE PRECISION,
                    strategy VARCHAR(50),
                    confidence INT,
                    status VARCHAR(20) DEFAULT 'OPEN',
                    exit_price DOUBLE PRECISION,
                    pnl DOUBLE PRECISION,
                    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gold_config (
                    key_name VARCHAR(50) PRIMARY KEY,
                    key_value VARCHAR(50),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                INSERT INTO gold_config (key_name, key_value) VALUES 
                ('gold_autopilot', 'TRUE'),
                ('gold_min_confidence', '80')
                ON CONFLICT (key_name) DO NOTHING;
            """)
            conn.commit()
    except Exception as e:
        print(f"[INIT DB ERROR] {e}")

# --- SUB-SECOND TICK AGGREGATOR ---
def get_live_gold_tick():
    # Primary: Binance PAXG physical ounce spot feed (sub-second tick)
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT", timeout=1.5)
        if r.status_code == 200:
            price = float(r.json()['price'])
            if price > 1000: return price
    except Exception:
        pass
    # Secondary: Finnhub OANDA quote fallback
    if FINNHUB_KEY:
        try:
            r = requests.get(f"https://finnhub.io/api/v1/quote?symbol=OANDA:XAU_USD&token={FINNHUB_KEY}", timeout=1.5)
            if r.status_code == 200:
                price = float(r.json().get('c', 0))
                if price > 1000: return price
        except Exception:
            pass
    return None

def get_current_session():
    utc_hour = datetime.now(timezone.utc).hour
    if 0 <= utc_hour < 7:
        return "ASIAN RANGE"
    elif 7 <= utc_hour < 13:
        return "LONDON EXPANSION"
    elif 13 <= utc_hour < 20:
        return "NEW YORK OVERLAP"
    return "OFF-HOURS / ROLLOVER"

# --- BAYESIAN SELF-LEARNING WEIGHTS ---
def calculate_learning_boost(conn, strategy_name, session_name):
    if not conn: return 0
    try:
        query = """
            SELECT pnl FROM gold_positions 
            WHERE status = 'CLOSED' AND strategy = %s AND session = %s 
            ORDER BY closed_at DESC LIMIT 20;
        """
        df = pd.read_sql(query, conn, params=(strategy_name, session_name))
        if len(df) >= 5:
            win_count = len(df[df['pnl'] > 0])
            win_rate = (win_count / len(df)) * 100.0
            return int((win_rate - 50.0) * 0.4)
    except Exception:
        pass
    return 0

# --- POSITION MONITOR & STOP-LOSS / TAKE-PROFIT ENFORCER ---
def monitor_open_trades(conn, live_price):
    if not conn or not live_price: return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, action, qty, entry_price, stop_loss, take_profit, strategy FROM gold_positions WHERE status = 'OPEN';")
            open_positions = cur.fetchall()
            for pos in open_positions:
                pos_id, action, qty, entry, sl, tp, strat = pos
                closed = False
                exit_price = live_price
                
                if action == 'BUY':
                    if live_price >= tp: closed = True; exit_price = tp
                    elif live_price <= sl: closed = True; exit_price = sl
                elif action == 'SELL':
                    if live_price <= tp: closed = True; exit_price = tp
                    elif live_price >= sl: closed = True; exit_price = sl
                    
                if closed:
                    pnl = (exit_price - entry) * qty if action == 'BUY' else (entry - exit_price) * qty
                    cur.execute("""
                        UPDATE gold_positions 
                        SET status = 'CLOSED', exit_price = %s, pnl = %s, closed_at = CURRENT_TIMESTAMP 
                        WHERE id = %s;
                    """, (exit_price, pnl, pos_id))
                    print(f"[{datetime.now()}] 🏁 [TRADE CLOSED] {action} Gold ({strat}) Exit: ${exit_price:.2f} | PnL: ${pnl:+.2f}")
            conn.commit()
    except Exception as e:
        print(f"[MONITOR ERROR] {e}")

# --- STRATEGY ENGINE & EXECUTION ---
def evaluate_gold_setups(conn, live_price):
    if not conn or not live_price: return
    session = get_current_session()
    
    # Read Autopilot Settings
    autopilot_active = False
    min_confidence = 80
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT key_name, key_value FROM gold_config WHERE key_name IN ('gold_autopilot', 'gold_min_confidence');")
            for k, v in cur.fetchall():
                if k == 'gold_autopilot': autopilot_active = (v == 'TRUE')
                elif k == 'gold_min_confidence': min_confidence = int(v)
    except Exception:
        pass
        
    if not autopilot_active:
        return

    # Restrict max open positions (prevents over-leveraging)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM gold_positions WHERE status = 'OPEN';")
            if cur.fetchone()[0] >= 2:
                return
    except Exception:
        pass

    candidates = []
    if session == "LONDON EXPANSION":
        candidates.append({"name": "London Judas Swing Sweep", "side": "BUY", "base": 84, "sl_dist": 4.5, "tp_dist": 12.0})
    elif session == "NEW YORK OVERLAP":
        candidates.append({"name": "ICT Silver Bullet FVG Expansion", "side": "BUY", "base": 86, "sl_dist": 5.0, "tp_dist": 14.0})
    elif session == "ASIAN RANGE":
        candidates.append({"name": "Asian Boundary Mean-Reversion", "side": "SELL", "base": 78, "sl_dist": 3.5, "tp_dist": 8.0})

    for c in candidates:
        boost = calculate_learning_boost(conn, c["name"], session)
        final_conf = min(99, max(40, c["base"] + boost))
        
        if final_conf >= min_confidence:
            entry = live_price
            sl = round(entry - c["sl_dist"] if c["side"] == "BUY" else entry + c["sl_dist"], 2)
            tp = round(entry + c["tp_dist"] if c["side"] == "BUY" else entry - c["tp_dist"], 2)
            qty = 50.0  # 0.50 Lots (50 oz Gold)
            
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO gold_positions (session, action, qty, entry_price, stop_loss, take_profit, strategy, confidence, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'OPEN');
                    """, (session, c["side"], qty, entry, sl, tp, c["name"], final_conf))
                    conn.commit()
                print(f"[{datetime.now()}] 🚀 [AUTOPILOT TRIGGERED] {c['side']} Gold @ ${entry:.2f} | Conf: {final_conf}% | Strat: {c['name']}")
            except Exception as e:
                print(f"[EXECUTION INSERT ERROR] {e}")

# --- MAIN 24/7 DAEMON LOOP ---
def main():
    print("=" * 60)
    print("⚡ [AURA QUANT] Starting 24/7 Headless Gold Execution Daemon")
    print("=" * 60)
    
    server_thread = threading.Thread(target=run_health_server, daemon=True)
    server_thread.start()

    conn = get_db_connection()
    init_tables(conn)
    if conn: conn.close()

    while True:
        try:
            live_price = get_live_gold_tick()
            if live_price:
                conn = get_db_connection()
                if conn:
                    monitor_open_trades(conn, live_price)
                    evaluate_gold_setups(conn, live_price)
                    conn.close()
            else:
                print(f"[{datetime.now()}] ⚠️ Waiting for live price feed...")
        except Exception as loop_e:
            print(f"[LOOP EXCEPTION] {loop_e}")
            
        time.sleep(5)

if __name__ == "__main__":
    main()
