import streamlit as st
import pandas as pd
from broker_api import IndianBrokerAPI
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="QuantBengal Pro Terminal", layout="wide", page_icon="📈")

# --- 2. ENHANCED CORPORATE CSS ---
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
    
    /* Sidebar Styling */
    section[data-testid="stSidebar"] { background-color: #1e3a8a !important; color: white !important; }
    section[data-testid="stSidebar"] .stRadio label { color: white !important; font-weight: 600 !important; }
    section[data-testid="stSidebar"] hr { border-color: #3b82f6 !important; }

    /* Info Cards & Guide Boxes */
    .guide-step {
        background-color: #ffffff;
        border-left: 5px solid #3b82f6;
        padding: 20px;
        margin-bottom: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .step-number { background-color: #1e3a8a; color: white; padding: 2px 10px; border-radius: 50%; margin-right: 10px; font-weight: bold; }
    
    /* Metrics & Banners */
    div[data-testid="stMetric"] { background-color: #ffffff; border: 1px solid #e2e8f0; padding: 15px !important; border-radius: 8px !important; }
    .banner { padding: 20px; border-radius: 8px; font-weight: 700; text-align: center; font-size: 18px; margin: 20px 0; }
    .banner-hold { background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }
    .banner-buy { background-color: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; border-left: 10px solid #1e3a8a; }
    .banner-sell { background-color: #fef2f2; color: #991b1b; border: 1px solid #fecaca; border-left: 10px solid #dc2626; }

    .styled-table { width: 100%; border-collapse: collapse; background-color: white; border-radius: 8px; overflow: hidden; margin-top: 10px; }
    .styled-table th { background-color: #f8fafc; color: #1e3a8a; text-align: left; padding: 12px; font-size: 11px; font-weight: 700; text-transform: uppercase; border-bottom: 2px solid #e2e8f0; }
    .styled-table td { padding: 12px; border-bottom: 1px solid #f1f5f9; font-size: 13px; color: #334155; }
    </style>
""", unsafe_allow_html=True)

# --- 3. SIDEBAR NAVIGATION ---
with st.sidebar:
    st.markdown("<h2 style='color:white; margin-bottom:0;'>QuantBengal</h2>", unsafe_allow_html=True)
    st.markdown("<p style='color:#bfdbfe; font-size:12px; margin-top:0;'>ALGO TERMINAL v5.2</p>", unsafe_allow_html=True)
    st.markdown("---")
    
    nav = st.radio("MAIN NAVIGATION", ["📈 Live Terminal", "📖 User Guide"])
    
    st.markdown("---")
    if nav == "📈 Live Terminal":
        st.markdown("### 🛠️ SETTINGS")
        algo_choice = st.selectbox(
            "TRADING ALGORITHM",
            ["Momentum Breakout (9/21 EMA)", "Opening Range Breakout (ORB)", "Mean Reversion (Bollinger)"]
        )
        if st.button("⚡ SYNC MARKET"):
            st.rerun()
    
    st.markdown("<br><br><p style='color:#93c5fd; font-size:10px;'>SECURE CONNECTION: ACTIVE</p>", unsafe_allow_html=True)

# --- 4. TOP CORPORATE HEADER ---
st.markdown(f"""
<div class="header-bar">
    <div>
        <h1 class="header-text">QUANTBENGAL <span style="color:#dc2626">PRO</span></h1>
        <p style="color:#64748b; font-size:12px; margin:0;">{ "REAL-TIME EXECUTION ENGINE" if nav == "📈 Live Terminal" else "BEGINNER ONBOARDING GUIDE" }</p>
    </div>
    <div style="text-align:right">
        <p style="color:#10b981; font-weight:700; margin:0; font-size:14px;">● SYSTEM ONLINE</p>
    </div>
</div>
""", unsafe_allow_html=True)

# --- 5. PAGE LOGIC: USER GUIDE ---
if nav == "📖 User Guide":
    st.subheader("Welcome, Trader. Let's get you started.")
    
    st.markdown("""
    <div class="guide-step">
        <span class="step-number">1</span> <b>Connect Your Angel One Account</b><br>
        <p style='color:#64748b; font-size:14px; margin-top:5px;'>
        Log into your Angel One SmartAPI dashboard and generate your <b>API Key</b>. 
        Then, enable <b>TOTP</b> in your profile settings to get your Secret Key. 
        Input these into the 'Secrets' configuration of your application.</p>
    </div>
    
    <div class="guide-step">
        <span class="step-number">2</span> <b>Select Your Strategy</b><br>
        <p style='color:#64748b; font-size:14px; margin-top:5px;'>
        Use the sidebar to choose an algorithm. 
        <b>9/21 EMA</b> is best for trending markets. 
        <b>Bollinger</b> is best for sideways markets. 
        <b>ORB</b> is best for the first 30 minutes of the day.</p>
    </div>
    
    <div class="guide-step">
        <span class="step-number">3</span> <b>Monitor the 'Pro-Signal' Banner</b><br>
        <p style='color:#64748b; font-size:14px; margin-top:5px;'>
        The system analyzes every 15-minute candle. 
        When the banner turns <b style='color:#1e40af;'>BLUE</b>, it's a Buy Call signal. 
        When it turns <b style='color:#991b1b;'>RED</b>, it's a Buy Put signal. 
        GRAY means the market is too risky to trade.</p>
    </div>
    
    <div class="guide-step">
        <span class="step-number">4</span> <b>Automated Execution</b><br>
        <p style='color:#64748b; font-size:14px; margin-top:5px;'>
        The background engine runs automatically every 15 minutes on GitHub. 
        You don't need to keep this dashboard open for trades to happen. 
        The engine will execute based on the logic shown in the terminal.</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.info("💡 **Pro-Tip for Beginners:** Start with Paper Trading for the first 7 days to understand how the RSI and EMA values interact with Nifty price action.")

# --- 6. PAGE LOGIC: LIVE TERMINAL ---
else:
    try:
        broker = IndianBrokerAPI()
        candles = broker.get_data()

        if candles and len(candles) >= 30:
            df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            latest_price = df['close'].iloc[-1]
            latest = df.iloc[-1]
            previous = df.iloc[-2]
            
            # (Strategy Calculations - Same as previous version)
            signal_text = "AWAITING MARKET MOMENTUM"
            banner_class = "banner-hold"
            
            if algo_choice == "Momentum Breakout (9/21 EMA)":
                df['ema_9'] = EMAIndicator(close=df['close'], window=9).ema_indicator()
                df['ema_21'] = EMAIndicator(close=df['close'], window=21).ema_indicator()
                df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
                if df['ema_9'].iloc[-2] <= df['ema_21'].iloc[-2] and df['ema_9'].iloc[-1] > df['ema_21'].iloc[-1] and df['rsi'].iloc[-1] > 55:
                    signal_text = "ALGO ALERT: BULLISH CROSSOVER - BUY CALL"; banner_class = "banner-buy"
                elif df['ema_9'].iloc[-2] >= df['ema_21'].iloc[-2] and df['ema_9'].iloc[-1] < df['ema_21'].iloc[-1] and df['rsi'].iloc[-1] < 45:
                    signal_text = "ALGO ALERT: BEARISH BREAKDOWN - BUY PUT"; banner_class = "banner-sell"

            elif algo_choice == "Opening Range Breakout (ORB)":
                orb_h, orb_l = df.iloc[0]['high'], df.iloc[0]['low']
                if latest['close'] > orb_h: signal_text = "ALGO ALERT: ORB BREAKOUT - BUY CALL"; banner_class = "banner-buy"
                elif latest['close'] < orb_l: signal_text = "ALGO ALERT: ORB BREAKDOWN - BUY PUT"; banner_class = "banner-sell"

            elif algo_choice == "Mean Reversion (Bollinger)":
                bb = BollingerBands(close=df["close"], window=20, window_dev=2)
                df['bb_h'], df['bb_l'] = bb.bollinger_hband(), bb.bollinger_lband()
                if latest['close'] <= df['bb_l'].iloc[-1]: signal_text = "ALGO ALERT: BB BOTTOM - BUY CALL"; banner_class = "banner-buy"
                elif latest['close'] >= df['bb_h'].iloc[-1]: signal_text = "ALGO ALERT: BB TOP - BUY PUT"; banner_class = "banner-sell"

            # --- DISPLAY ---
            m1, m2, m3 = st.columns(3)
            m1.metric("NIFTY 50 SPOT", f"₹{latest_price:,.2f}")
            m2.metric("STRATEGY STATUS", "ACTIVE")
            m3.metric("API LATENCY", "LOW")
            
            st.markdown(f'<div class="banner {banner_class}">{signal_text}</div>', unsafe_allow_html=True)

            st.markdown("<div style='font-weight:700; color:#1e3a8a; margin-top:20px;'>LIVE DATA STREAM</div>", unsafe_allow_html=True)
            df['ts'] = pd.to_datetime(df['ts']).dt.strftime('%H:%M')
            display_df = df[['ts', 'close']].tail(5).round(2)
            
            table_html = f"""<table class="styled-table"><thead><tr>{' '.join([f'<th>{c}</th>' for c in display_df.columns])}</tr></thead><tbody>"""
            for _, row in display_df.iterrows():
                table_html += "<tr>" + "".join([f"<td>{row[c]}</td>" for c in display_df.columns]) + "</tr>"
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)

        else: st.warning("INITIALIZING DATA FEED...")
    except Exception as e: st.error(f"HARDWARE ERROR: {e}")
