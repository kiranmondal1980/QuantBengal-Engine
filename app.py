import streamlit as st
import pandas as pd
from broker_api import IndianBrokerAPI
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="QuantBengal | Terminal", layout="wide", page_icon="⚡", initial_sidebar_state="collapsed")

# --- PREMIUM BLUE & RED CORPORATE CSS ---
st.markdown("""
    <style>
    /* Absolute Dark Navy Background */
    .stApp {
        background-color: #060d1a !important;
        color: #ffffff;
        font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Hide Streamlit elements */
    header {visibility: hidden;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}

    /* Premium Header Bar */
    .terminal-header {
        background: linear-gradient(90deg, #0a1428 0%, #060d1a 100%);
        padding: 25px 35px;
        border-radius: 4px;
        border-top: 3px solid #0066ff;
        border-bottom: 1px solid #1a2639;
        margin-bottom: 30px;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
    }
    .t-title { margin: 0; font-size: 32px; font-weight: 800; color: #ffffff; letter-spacing: 1px; text-transform: uppercase;}
    .t-title span { color: #0066ff; }
    .t-sub { margin: 8px 0 0 0; font-size: 13px; color: #8b9ab3; font-weight: 500; letter-spacing: 2px; text-transform: uppercase;}

    /* Sleek Rule Box */
    .rules-panel {
        background-color: rgba(10, 20, 40, 0.6);
        border: 1px solid #1a2639;
        border-left: 4px solid #ff0033;
        border-radius: 4px;
        padding: 20px 25px;
        margin-bottom: 30px;
    }
    .rules-panel h4 { margin-top: 0; color: #ffffff; font-size: 14px; font-weight: 700; letter-spacing: 1.5px;}
    .rules-panel p, .rules-panel li { color: #8b9ab3; font-size: 13px; margin-bottom: 4px;}
    .highlight-blue { color: #0066ff; font-weight: bold;}
    .highlight-red { color: #ff0033; font-weight: bold;}

    /* Custom Metric Cards */
    div[data-testid="metric-container"] {
        background: linear-gradient(180deg, #0d1726 0%, #060d1a 100%);
        border: 1px solid #1a2639;
        border-top: 2px solid #0066ff;
        padding: 20px;
        border-radius: 4px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
    div[data-testid="stMetricValue"] { color: #ffffff !important; font-size: 30px !important; font-weight: 700 !important; font-family: 'Courier New', Courier, monospace;}
    div[data-testid="stMetricLabel"] { color: #8b9ab3 !important; font-size: 12px !important; font-weight: 600 !important; letter-spacing: 1px; text-transform: uppercase;}
    div[data-testid="stMetricDelta"] svg { display: none; } /* Hide default arrows */

    /* Action Banners */
    .action-banner {
        padding: 20px;
        border-radius: 4px;
        font-weight: 800;
        font-size: 18px;
        text-align: center;
        margin: 30px 0;
        letter-spacing: 2px;
        text-transform: uppercase;
        box-shadow: 0 8px 16px rgba(0,0,0,0.4);
    }
    .action-hold { background: linear-gradient(90deg, #0a1428, #1a2639); color: #ffffff; border-left: 5px solid #8b9ab3; border-right: 5px solid #8b9ab3;}
    .action-buy { background: linear-gradient(90deg, #001f4d, #003380); color: #00ccff; border-left: 5px solid #0066ff; border-right: 5px solid #0066ff;}
    .action-sell { background: linear-gradient(90deg, #330000, #660000); color: #ff6666; border-left: 5px solid #ff0033; border-right: 5px solid #ff0033;}

    /* Custom HTML Table for Sleek Look (Overriding Streamlit's ugly white table) */
    .fin-table { width: 100%; border-collapse: collapse; font-family: 'Courier New', Courier, monospace; margin-top: 10px;}
    .fin-table th { background-color: #0a1428; color: #8b9ab3; font-size: 12px; font-weight: 600; padding: 12px 15px; text-align: left; border-bottom: 2px solid #0066ff; text-transform: uppercase;}
    .fin-table td { background-color: #060d1a; color: #ffffff; font-size: 14px; padding: 12px 15px; border-bottom: 1px solid #1a2639; }
    .fin-table tr:hover td { background-color: #0d1726; }
    
    /* Button */
    .stButton>button {
        background-color: transparent !important;
        color: #0066ff !important;
        border: 1px solid #0066ff !important;
        border-radius: 4px !important;
        padding: 5px 20px !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .stButton>button:hover {
        background-color: #0066ff !important;
        color: #ffffff !important;
        box-shadow: 0 0 10px rgba(0, 102, 255, 0.5) !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- TERMINAL HEADER ---
st.markdown("""
<div class="terminal-header">
    <h1 class="t-title">QuantBengal <span>Engine</span></h1>
    <p class="t-sub">Proprietary Algorithmic Execution System // Angel One Bridge</p>
</div>
""", unsafe_allow_html=True)

# --- STRATEGY PANEL ---
st.markdown("""
<div class="rules-panel">
    <h4>SYSTEM LOGIC DEFINITION</h4>
    <p>This terminal executes trades based on strict quantitative momentum rules. Emotional overrides are disabled.</p>
    <ul>
        <li><b>Parameters:</b> 9 EMA (Fast), 21 EMA (Slow), RSI-14 (Momentum).</li>
        <li><b><span class="highlight-blue">CALL EXECUTION:</span></b> Triggered when 9 EMA crosses ABOVE 21 EMA while RSI > 55.</li>
        <li><b><span class="highlight-red">PUT EXECUTION:</span></b> Triggered when 9 EMA crosses BELOW 21 EMA while RSI < 45.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# --- CONTROLS ---
col_btn, col_stat, _ = st.columns([2, 2, 6])
with col_btn:
    if st.button("SYNC LIVE DATA"):
        st.rerun()
with col_stat:
    st.markdown("<div style='margin-top:10px; color:#0066ff; font-weight:700; font-size:12px; letter-spacing:1px;'>[ CONNECTION: SECURE ]</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

try:
    # --- ENGINE LOGIC ---
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
        
        # --- METRIC CARDS ---
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("ASSET: NIFTY 50", f"{latest_price:,.2f}")
        m2.metric("9 EMA (FAST)", f"{latest['ema_9']:,.2f}")
        m3.metric("21 EMA (SLOW)", f"{latest['ema_21']:,.2f}")
        m4.metric("RSI (14)", f"{latest['rsi']:.2f}", delta="Oversold" if latest['rsi'] < 30 else "Overbought" if latest['rsi'] > 70 else "Neutral")

        # --- TERMINAL SIGNALS (BLUE & RED) ---
        if previous['ema_9'] <= previous['ema_21'] and latest['ema_9'] > latest['ema_21'] and latest['rsi'] > 55:
            st.markdown('<div class="action-banner action-buy">SYSTEM ACTION: EXECUTING LONG (CALL) POSITION</div>', unsafe_allow_html=True)
        elif previous['ema_9'] >= previous['ema_21'] and latest['ema_9'] < latest['ema_21'] and latest['rsi'] < 45:
            st.markdown('<div class="action-banner action-sell">SYSTEM ACTION: EXECUTING SHORT (PUT) POSITION</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="action-banner action-hold">SYSTEM ACTION: STANDBY (AWAITING MOMENTUM)</div>', unsafe_allow_html=True)

        # --- CUSTOM HTML TERMINAL TABLE ---
        st.markdown("<h4 style='color:#ffffff; font-size:14px; letter-spacing:1px; text-transform:uppercase;'>System Data Feed</h4>", unsafe_allow_html=True)
        
        # Format the dataframe for the custom HTML
        df['ts'] = pd.to_datetime(df['ts']).dt.strftime('%H:%M | %d-%m-%Y')
        display_df = df[['ts', 'close', 'ema_9', 'ema_21', 'rsi']].tail(5).round(2)
        display_df.columns = ['TIMESTAMP', 'PRICE', '9 EMA', '21 EMA', 'RSI']
        
        # Injecting Pandas DataFrame as custom HTML
        html_table = display_df.to_html(index=False, classes="fin-table")
        st.markdown(html_table, unsafe_allow_html=True)
        
    else:
        st.error("AWAITING DATA STREAM...")

except Exception as e:
    st.error(f"FATAL EXCEPTION: {e}")
