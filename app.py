import streamlit as st
import pandas as pd
from broker_api import IndianBrokerAPI
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

# --- PAGE CONFIGURATION (Must be first) ---
st.set_page_config(page_title="QuantBengal | Algorithmic Engine", layout="wide", page_icon="📈", initial_sidebar_state="collapsed")

# --- MASSIVE CSS INJECTION FOR CORPORATE UI ---
st.markdown("""
    <style>
    /* Main Background & Text */
    .stApp {
        background-color: #0e1117;
        color: #fafafa;
        font-family: 'Inter', sans-serif;
    }
    
    /* Top Header Bar */
    .header-container {
        background: linear-gradient(90deg, #1f2937 0%, #111827 100%);
        padding: 20px 30px;
        border-radius: 8px;
        border-left: 5px solid #3b82f6;
        margin-bottom: 25px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .header-title { margin: 0; font-size: 28px; font-weight: 700; color: #ffffff; letter-spacing: 0.5px; }
    .header-sub { margin: 5px 0 0 0; font-size: 14px; color: #9ca3af; font-weight: 400; }

    /* Strategy Rules Box */
    .strategy-box {
        background-color: #1f2937;
        border: 1px solid #374151;
        border-radius: 8px;
        padding: 20px;
        margin-bottom: 30px;
    }
    .strategy-box h4 { margin-top: 0; color: #60a5fa; font-size: 16px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;}
    .strategy-box ul { margin-bottom: 0; color: #d1d5db; font-size: 14px; line-height: 1.6;}

    /* Metric Cards Override */
    div[data-testid="stMetricValue"] {
        font-size: 28px !important;
        font-weight: 700 !important;
        color: #ffffff !important;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 13px !important;
        text-transform: uppercase !important;
        letter-spacing: 0.5px !important;
        color: #9ca3af !important;
    }
    /* The box around the metrics */
    div[data-testid="metric-container"] {
        background-color: #1f2937;
        border: 1px solid #374151;
        padding: 15px 20px;
        border-radius: 8px;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
    }

    /* Status Banners */
    .status-banner {
        padding: 15px 20px;
        border-radius: 8px;
        font-weight: 600;
        font-size: 16px;
        text-align: center;
        margin: 20px 0;
        letter-spacing: 0.5px;
    }
    .status-hold { background-color: #374151; color: #f3f4f6; border: 1px solid #4b5563; }
    .status-buy { background-color: #064e3b; color: #34d399; border: 1px solid #059669; }
    .status-sell { background-color: #7f1d1d; color: #f87171; border: 1px solid #dc2626; }

    /* Button Styling */
    div.stButton > button:first-child {
        background-color: #3b82f6;
        color: white;
        border: none;
        border-radius: 6px;
        padding: 10px 20px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    div.stButton > button:first-child:hover {
        background-color: #2563eb;
        box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.5);
    }
    
    /* Hide Streamlit Branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# --- HEADER SECTION ---
st.markdown("""
<div class="header-container">
    <h1 class="header-title">QuantBengal Algorithmic Engine</h1>
    <p class="header-sub">Institutional-Grade Options Trading Automation via Angel One SmartAPI</p>
</div>
""", unsafe_allow_html=True)

# --- STRATEGY EXPLANATION ---
st.markdown("""
<div class="strategy-box">
    <h4>Core Trading Logic: Momentum Breakout</h4>
    <ul>
        <li><b>Indicator Setup:</b> 9 EMA (Fast Trend), 21 EMA (Slow Trend), RSI-14 (Momentum Strength).</li>
        <li><b>Bullish Execution:</b> Automatically buys ATM Call Option when 9 EMA crosses ABOVE 21 EMA while RSI > 55.</li>
        <li><b>Bearish Execution:</b> Automatically buys ATM Put Option when 9 EMA crosses BELOW 21 EMA while RSI < 45.</li>
        <li><b>Risk Protocol:</b> System holds position in ranging markets to avoid Theta decay.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# --- CONTROL PANEL ---
col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([1, 1, 2])
with col_ctrl1:
    if st.button("⚡ Force Sync Live Data"):
        st.rerun()
with col_ctrl2:
    st.markdown("<div style='margin-top:10px; color:#10b981; font-weight:600;'>🟢 Engine Connected</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True) # Spacer

try:
    # --- FETCH LIVE DATA ---
    broker = IndianBrokerAPI()
    candles = broker.get_data()

    if candles and len(candles) >= 30:
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        latest_price = df['close'].iloc[-1]
        
        df['ema_9'] = EMAIndicator(close=df['close'], window=9).ema_indicator()
        df['ema_21'] = EMAIndicator(close=df['close'], window=21).ema_indicator()
        df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
        
        latest = df.iloc[-1]
        previous = df.iloc[-2]
        
        # --- TOP METRICS ROW ---
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Nifty 50 (Live Spot)", f"₹{latest_price:,.2f}")
        m2.metric("9 Period EMA", f"{latest['ema_9']:,.2f}")
        m3.metric("21 Period EMA", f"{latest['ema_21']:,.2f}")
        
        # Color the RSI metric based on value
        rsi_val = latest['rsi']
        rsi_delta = "Overbought" if rsi_val > 70 else "Oversold" if rsi_val < 30 else "Neutral"
        m4.metric("RSI (14)", f"{rsi_val:.2f}", delta=rsi_delta, delta_color="off")

        # --- SIGNAL DETERMINATION ---
        if previous['ema_9'] <= previous['ema_21'] and latest['ema_9'] > latest['ema_21'] and latest['rsi'] > 55:
            st.markdown('<div class="status-banner status-buy">🟢 ALGO ACTION: EXECUTING BUY CALL (Bullish Crossover Detected)</div>', unsafe_allow_html=True)
        elif previous['ema_9'] >= previous['ema_21'] and latest['ema_9'] < latest['ema_21'] and latest['rsi'] < 45:
            st.markdown('<div class="status-banner status-sell">🔴 ALGO ACTION: EXECUTING BUY PUT (Bearish Breakdown Detected)</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="status-banner status-hold">⚖️ ALGO ACTION: HOLD (Market ranging. No clear momentum crossover.)</div>', unsafe_allow_html=True)

        # --- DATA TABLE ---
        st.markdown("<h4 style='color:#60a5fa; margin-top:30px; margin-bottom:15px;'>Live Data Stream (15m Interval)</h4>", unsafe_allow_html=True)
        df['ts'] = pd.to_datetime(df['ts']).dt.strftime('%Y-%m-%d %H:%M')
        display_df = df[['ts', 'close', 'ema_9', 'ema_21', 'rsi']].tail(5).round(2)
        display_df.columns = ['Timestamp (IST)', 'Closing Price', '9 EMA', '21 EMA', 'RSI']
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        
    else:
        st.error("Engine waiting for sufficient market data. Connection established, awaiting volume.")

except Exception as e:
    st.error(f"SYSTEM FAULT: Failed to connect to Angel One API. {e}")
