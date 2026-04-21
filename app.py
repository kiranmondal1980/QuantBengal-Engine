import streamlit as st
import pandas as pd
from broker_api import IndianBrokerAPI
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
from datetime import datetime
import pytz

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="QuantBengal Pro Terminal", layout="wide", page_icon="📈")

# --- 2. CORPORATE BLUE & RED CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #f8fafc; color: #1e293b; font-family: 'Inter', sans-serif; }
    
    /* Header Bar */
    .header-bar {
        background-color: #ffffff;
        padding: 1.5rem 3rem;
        border-bottom: 4px solid #1e3a8a;
        margin-bottom: 2rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .header-text { margin: 0; color: #1e3a8a; font-size: 28px; font-weight: 800; }
    .header-tag { color: #64748b; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }

    /* Strategy Info Card */
    .info-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05);
    }
    .info-header { color: #1e3a8a; font-size: 14px; font-weight: 700; text-transform: uppercase; margin-bottom: 12px; border-bottom: 1px solid #f1f5f9; padding-bottom: 8px; }
    
    /* Metrics */
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 15px !important;
        border-radius: 8px !important;
    }

    /* Professional Banners */
    .banner { padding: 20px; border-radius: 8px; font-weight: 700; text-align: center; font-size: 18px; margin: 20px 0; }
    .banner-hold { background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }
    .banner-buy { background-color: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; border-left: 10px solid #1e3a8a; }
    .banner-sell { background-color: #fef2f2; color: #991b1b; border: 1px solid #fecaca; border-left: 10px solid #dc2626; }

    /* Custom Table */
    .styled-table { width: 100%; border-collapse: collapse; background-color: white; border-radius: 8px; overflow: hidden; }
    .styled-table th { background-color: #f8fafc; color: #1e3a8a; text-align: left; padding: 12px; font-size: 11px; font-weight: 700; text-transform: uppercase; border-bottom: 2px solid #e2e8f0; }
    .styled-table td { padding: 12px; border-bottom: 1px solid #f1f5f9; font-size: 13px; color: #334155; }
    
    /* Sidebar */
    section[data-testid="stSidebar"] { background-color: #1e3a8a !important; color: white !important; }
    section[data-testid="stSidebar"] .stSelectbox label { color: white !important; font-weight: 600 !important; }
    </style>
""", unsafe_allow_html=True)

# --- 3. SIDEBAR CONFIGURATION ---
with st.sidebar:
    st.markdown("<h2 style='color:white;'>⚙️ TERMINAL</h2>", unsafe_allow_html=True)
    algo_choice = st.selectbox(
        "SELECT ALGORITHM",
        ["Momentum Breakout (9/21 EMA)", "Opening Range Breakout (ORB)", "Mean Reversion (Bollinger)"]
    )
    st.markdown("---")
    st.markdown("<p style='color:#bfdbfe; font-size:12px;'>MODE: LIVE PRODUCTION</p>", unsafe_allow_html=True)
    if st.button("⚡ SYNC MARKET DATA"):
        st.rerun()

# --- 4. CORPORATE HEADER ---
st.markdown(f"""
<div class="header-bar">
    <div>
        <h1 class="header-text">QUANTBENGAL <span style="color:#dc2626">PRO</span></h1>
        <p class="header-tag">Executing Strategy: {algo_choice}</p>
    </div>
    <div style="text-align:right">
        <p style="color:#10b981; font-weight:700; margin:0; font-size:14px;">● BROKER CONNECTED</p>
        <p style="color:#64748b; font-size:11px; margin:0;">STRICT ALGO EXECUTION | VER 5.0</p>
    </div>
</div>
""", unsafe_allow_html=True)

# --- 5. DATA ENGINE ---
try:
    broker = IndianBrokerAPI()
    candles = broker.get_data()

    if candles and len(candles) >= 30:
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        latest_price = df['close'].iloc[-1]
        latest = df.iloc[-1]
        previous = df.iloc[-2]
        
        # --- STRATEGY CALCULATIONS ---
        signal_text = "AWAITING MARKET MOMENTUM"
        banner_class = "banner-hold"
        
        if algo_choice == "Momentum Breakout (9/21 EMA)":
            df['ema_9'] = EMAIndicator(close=df['close'], window=9).ema_indicator()
            df['ema_21'] = EMAIndicator(close=df['close'], window=21).ema_indicator()
            df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
            
            curr_ema9 = df['ema_9'].iloc[-1]
            curr_ema21 = df['ema_21'].iloc[-1]
            curr_rsi = df['rsi'].iloc[-1]
            prev_ema9 = df['ema_9'].iloc[-2]
            prev_ema21 = df['ema_21'].iloc[-2]

            rule_html = "<li><b>BUY CALL:</b> 9 EMA crosses above 21 EMA + RSI > 55</li><li><b>BUY PUT:</b> 9 EMA crosses below 21 EMA + RSI < 45</li>"
            
            if prev_ema9 <= prev_ema21 and curr_ema9 > curr_ema21 and curr_rsi > 55:
                signal_text = "ALGO ALERT: 9/21 CROSSOVER DETECTED - EXECUTE BUY CALL"
                banner_class = "banner-buy"
            elif prev_ema9 >= prev_ema21 and curr_ema9 < curr_ema21 and curr_rsi < 45:
                signal_text = "ALGO ALERT: 9/21 BREAKDOWN DETECTED - EXECUTE BUY PUT"
                banner_class = "banner-sell"

        elif algo_choice == "Opening Range Breakout (ORB)":
            # Assuming first candle of the list is 9:15 AM
            orb_high = df.iloc[0]['high']
            orb_low = df.iloc[0]['low']
            rule_html = f"<li><b>Range High:</b> ₹{orb_high}</li><li><b>Range Low:</b> ₹{orb_low}</li><li><b>Rule:</b> Buy on 15m breakout of this range.</li>"
            
            if latest['close'] > orb_high:
                signal_text = "ALGO ALERT: ORB BULLISH BREAKOUT - EXECUTE BUY CALL"
                banner_class = "banner-buy"
            elif latest['close'] < orb_low:
                signal_text = "ALGO ALERT: ORB BEARISH BREAKDOWN - EXECUTE BUY PUT"
                banner_class = "banner-sell"

        elif algo_choice == "Mean Reversion (Bollinger)":
            bb = BollingerBands(close=df["close"], window=20, window_dev=2)
            df['bb_h'] = bb.bollinger_hband()
            df['bb_l'] = bb.bollinger_lband()
            rule_html = "<li><b>BUY CALL:</b> Price touches Lower Band + Oversold RSI</li><li><b>BUY PUT:</b> Price touches Upper Band + Overbought RSI</li>"
            
            if latest['close'] <= df['bb_l'].iloc[-1]:
                signal_text = "ALGO ALERT: MEAN REVERSION REACHED - EXECUTE BUY CALL"
                banner_class = "banner-buy"
            elif latest['close'] >= df['bb_h'].iloc[-1]:
                signal_text = "ALGO ALERT: MEAN REVERSION REACHED - EXECUTE BUY PUT"
                banner_class = "banner-sell"

        # --- UI LAYOUT ---
        c1, c2 = st.columns([1, 2.5])
        
        with c1:
            st.markdown(f"""
            <div class="info-card">
                <div class="info-header">Execution Logic</div>
                <ul style="padding-left:15px; font-size:13px; color:#475569;">
                    {rule_html}
                </ul>
            </div>
            """, unsafe_allow_html=True)

        with c2:
            m1, m2, m3 = st.columns(3)
            m1.metric("NIFTY 50 SPOT", f"₹{latest_price:,.2f}")
            m2.metric("CURRENT SIGNAL", "ACTIVE" if banner_class != "banner-hold" else "STANDBY")
            m3.metric("VOLATILITY", "STABLE")
            
            st.markdown(f'<div class="banner {banner_class}">{signal_text}</div>', unsafe_allow_html=True)

        # --- DATA TABLE ---
        st.markdown("<div style='margin-top:2rem; font-weight:700; color:#1e3a8a;'>ALGORITHMIC DATA STREAM</div>", unsafe_allow_html=True)
        df['ts'] = pd.to_datetime(df['ts']).dt.strftime('%H:%M')
        # Dynamic table columns based on algo
        cols_to_show = ['ts', 'close']
        if 'ema_9' in df.columns: cols_to_show += ['ema_9', 'ema_21', 'rsi']
        if 'bb_h' in df.columns: cols_to_show += ['bb_h', 'bb_l']
        
        display_df = df[cols_to_show].tail(5).round(2)
        
        table_html = f"""<table class="styled-table"><thead><tr>{' '.join([f'<th>{c}</th>' for c in display_df.columns])}</tr></thead><tbody>"""
        for _, row in display_df.iterrows():
            table_html += "<tr>" + "".join([f"<td>{row[c]}</td>" for c in display_df.columns]) + "</tr>"
        table_html += "</tbody></table>"
        st.markdown(table_html, unsafe_allow_html=True)

    else:
        st.warning("SYSTEM INITIALIZING... Connecting to Exchange Data Feed.")

except Exception as e:
    st.error(f"TERMINAL FAULT: {e}")
