import streamlit as st
import pandas as pd
from broker_api import IndianBrokerAPI
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

# --- 1. TERMINAL CONFIGURATION ---
st.set_page_config(page_title="QuantBengal Pro | Institutional Terminal", layout="wide", page_icon="📈")

# --- 2. PROFESSIONAL CORPORATE CSS (BLUE & RED THEME) ---
st.markdown("""
    <style>
    .stApp { background-color: #f8fafc; color: #1e293b; font-family: 'Inter', sans-serif; }
    
    /* Global Header */
    .header-container {
        background-color: #ffffff;
        padding: 1.5rem 3rem;
        border-bottom: 4px solid #1e3a8a;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
    }
    .main-title { color: #1e3a8a; font-size: 32px; font-weight: 800; margin: 0; }
    .pro-tag { color: #dc2626; }
    .status-indicator { color: #10b981; font-weight: 700; font-size: 14px; }

    /* Tabs Styling */
    .stTabs [data-baseweb="tab-list"] { gap: 20px; margin-left: 3rem; }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        background-color: transparent;
        border-radius: 4px 4px 0 0;
        font-weight: 600;
        color: #64748b;
    }
    .stTabs [aria-selected="true"] { color: #1e3a8a !important; border-bottom: 3px solid #1e3a8a !important; }

    /* Corporate Cards */
    .corporate-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 25px;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02);
    }
    .card-title { color: #1e3a8a; font-size: 16px; font-weight: 700; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px; margin-bottom: 15px; text-transform: uppercase; }

    /* Signal Banners */
    .banner { padding: 20px; border-radius: 8px; font-weight: 800; text-align: center; font-size: 20px; margin: 20px 0; border: 1px solid transparent; text-transform: uppercase; }
    .banner-hold { background-color: #f1f5f9; color: #475569; border-color: #cbd5e1; }
    .banner-buy { background-color: #eff6ff; color: #1e40af; border-color: #bfdbfe; border-left: 12px solid #1e3a8a; }
    .banner-sell { background-color: #fef2f2; color: #991b1b; border-color: #fecaca; border-left: 12px solid #dc2626; }

    /* Professional Table */
    .styled-table { width: 100%; border-collapse: collapse; background-color: white; font-size: 14px; }
    .styled-table th { background-color: #f8fafc; color: #1e3a8a; text-align: left; padding: 12px; font-weight: 700; border-bottom: 2px solid #e2e8f0; }
    .styled-table td { padding: 12px; border-bottom: 1px solid #f1f5f9; color: #334155; }
    
    /* Buttons */
    .stButton>button { background-color: #1e3a8a !important; color: white !important; font-weight: 700 !important; border-radius: 4px !important; width: 100%; }
    </style>
""", unsafe_allow_html=True)

# --- 3. CORPORATE HEADER ---
st.markdown("""
<div class="header-container">
    <h1 class="main-title">QUANTBENGAL <span class="pro-tag">PRO</span></h1>
    <div class="status-indicator">● SYSTEM PRODUCTION LIVE</div>
</div>
""", unsafe_allow_html=True)

# --- 4. TOP NAVIGATION TABS (NOTHING HIDDEN) ---
tab1, tab2, tab3 = st.tabs(["📈 LIVE TERMINAL", "🛠️ STRATEGY SUITE", "📖 BEGINNER USER GUIDE"])

with tab1:
    col_dash1, col_dash2 = st.columns([1, 3])
    
    with col_dash1:
        st.markdown('<div class="corporate-card"><p class="card-title">Terminal Controls</p>', unsafe_allow_html=True)
        active_algo = st.selectbox("Select Execution Logic", ["Momentum (9/21 EMA)", "Opening Range (ORB)", "Bollinger Mean Reversion"])
        if st.button("REFRESH MARKET DATA"):
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        st.info("💡 Pro-Tip: The engine auto-executes on GitHub every 15 minutes. This dashboard is your live monitoring window.")

    with col_dash2:
        try:
            broker = IndianBrokerAPI()
            candles = broker.get_data()
            if candles and len(candles) >= 30:
                df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                
                # Calculations
                df['ema_9'] = EMAIndicator(close=df['close'], window=9).ema_indicator()
                df['ema_21'] = EMAIndicator(close=df['close'], window=21).ema_indicator()
                df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
                latest = df.iloc[-1]
                prev = df.iloc[-2]

                # Metrics
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("NIFTY SPOT", f"₹{latest['close']:,.2f}")
                m2.metric("9 EMA", f"{latest['ema_9']:,.1f}")
                m3.metric("21 EMA", f"{latest['ema_21']:,.1f}")
                m4.metric("RSI (14)", f"{latest['rsi']:.1f}")

                # Signal Engine
                sig, style = "AWAITING MARKET MOMENTUM", "banner-hold"
                if prev['ema_9'] <= prev['ema_21'] and latest['ema_9'] > latest['ema_21'] and latest['rsi'] > 55:
                    sig, style = "🚀 PRO-SIGNAL: BULLISH CROSSOVER (BUY CALL)", "banner-buy"
                elif prev['ema_9'] >= prev['ema_21'] and latest['ema_9'] < latest['ema_21'] and latest['rsi'] < 45:
                    sig, style = "📉 PRO-SIGNAL: BEARISH BREAKDOWN (BUY PUT)", "banner-sell"
                
                st.markdown(f'<div class="banner {style}">{sig}</div>', unsafe_allow_html=True)

                # Data Table
                st.markdown('<p class="card-title">Institutional Data Stream</p>', unsafe_allow_html=True)
                df['ts'] = pd.to_datetime(df['ts']).dt.strftime('%H:%M')
                display_df = df[['ts', 'close', 'ema_9', 'ema_21', 'rsi']].tail(6).round(2)
                
                table_html = """<table class="styled-table"><thead><tr><th>Time</th><th>Price</th><th>9 EMA</th><th>21 EMA</th><th>RSI</th></tr></thead><tbody>"""
                for _, r in display_df.iterrows():
                    table_html += f"<tr><td>{r['ts']}</td><td>₹{r['close']}</td><td>{r['ema_9']}</td><td>{r['ema_21']}</td><td>{r['rsi']}</td></tr>"
                st.markdown(table_html + "</tbody></table>", unsafe_allow_html=True)
            else:
                st.warning("Establishing API Connection... Awaiting Data.")
        except Exception as e:
            st.error(f"Hardware Error: {e}")

with tab2:
    st.markdown('<div class="corporate-card">', unsafe_allow_html=True)
    st.markdown("""
    <h2 style='color:#1e3a8a;'>Institutional Strategy Repository</h2>
    <hr>
    <div style='display:flex; gap:20px;'>
        <div style='flex:1; border:1px solid #e2e8f0; padding:20px; border-radius:8px;'>
            <h4 style='color:#1e3a8a;'>1. Momentum Breakout (9/21 EMA)</h4>
            <p style='font-size:14px; color:#475569;'>Captures major intraday trends using exponential moving average crossovers confirmed by RSI volume strength.</p>
            <li style='font-size:13px;'><b>Trigger:</b> 9 EMA > 21 EMA</li>
            <li style='font-size:13px;'><b>Confirmation:</b> RSI > 55</li>
        </div>
        <div style='flex:1; border:1px solid #e2e8f0; padding:20px; border-radius:8px;'>
            <h4 style='color:#1e3a8a;'>2. Opening Range Breakout (ORB)</h4>
            <p style='font-size:14px; color:#475569;'>Exploits morning volatility by trading the breakout of the first 15-minute candle's price range.</p>
            <li style='font-size:13px;'><b>Trigger:</b> Price > 9:15 High</li>
            <li style='font-size:13px;'><b>Safety:</b> Avoids execution after 11:00 AM</li>
        </div>
        <div style='flex:1; border:1px solid #e2e8f0; padding:20px; border-radius:8px;'>
            <h4 style='color:#1e3a8a;'>3. Bollinger Mean Reversion</h4>
            <p style='font-size:14px; color:#475569;'>Designed for sideways/choppy markets. Buys at extreme oversold levels and sells at overbought levels.</p>
            <li style='font-size:13px;'><b>Trigger:</b> Price touches Lower Band</li>
            <li style='font-size:13px;'><b>Confirmation:</b> RSI < 30</li>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with tab3:
    st.markdown('<div class="corporate-card">', unsafe_allow_html=True)
    st.markdown("""
    <h2 style='color:#1e3a8a;'>Step-By-Step Beginner Guidance</h2>
    <hr>
    <h4 style='color:#1e3a8a;'>Step 1: Secure API Credentials</h4>
    <p style='font-size:14px;'>Log into your Angel One SmartAPI portal. Copy your <b>API Key</b>, <b>Client ID</b>, and <b>TOTP Secret</b> into the system configuration.</p>
    
    <h4 style='color:#1e3a8a;'>Step 2: Understand the Interface</h4>
    <p style='font-size:14px;'>The <b>Live Terminal</b> shows the index price and the computed math. The <b>Blue Banner</b> indicates a bullish trend, and the <b>Red Banner</b> indicates a bearish trend.</p>
    
    <h4 style='color:#1e3a8a;'>Step 3: Verification</h4>
    <p style='font-size:14px;'>Before committing real capital, compare the RSI and EMA values on this dashboard with your trading chart to ensure 100% mathematical sync.</p>
    
    <h4 style='color:#1e3a8a;'>Step 4: Silent Automation</h4>
    <p style='font-size:14px;'>This terminal is just the "View." The actual trades are executed by your <b>GitHub Bot</b> in the background. You do not need to keep this browser tab open for trades to execute.</p>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
