import streamlit as st
import pandas as pd
from broker_api import IndianBrokerAPI
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="QuantBengal Pro Terminal", layout="wide", page_icon="📈")

# --- CORPORATE LIGHT THEME CSS ---
st.markdown("""
    <style>
    /* Global Background */
    .stApp {
        background-color: #f4f7f9;
        color: #2c3e50;
        font-family: 'Inter', -apple-system, sans-serif;
    }

    /* Header Bar - Deep Corporate Blue */
    .header-bar {
        background-color: #ffffff;
        padding: 20px 40px;
        border-bottom: 4px solid #1e3a8a;
        margin-bottom: 30px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
    .header-text { margin: 0; color: #1e3a8a; font-size: 26px; font-weight: 800; letter-spacing: -0.5px; }
    .header-tag { color: #64748b; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }

    /* Rules Section - Professional Card */
    .rule-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 25px;
        margin-bottom: 30px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02);
    }
    .rule-header { color: #1e3a8a; font-size: 14px; font-weight: 700; text-transform: uppercase; margin-bottom: 15px; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px; }
    .rule-list { list-style: none; padding: 0; margin: 0; }
    .rule-list li { margin-bottom: 8px; font-size: 14px; color: #475569; display: flex; align-items: center; }
    .blue-dot { height: 8px; width: 8px; background-color: #1e3a8a; border-radius: 50%; display: inline-block; margin-right: 10px; }
    .red-dot { height: 8px; width: 8px; background-color: #dc2626; border-radius: 50%; display: inline-block; margin-right: 10px; }

    /* Metric Cards Styling */
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 20px !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02) !important;
    }
    div[data-testid="stMetricValue"] { color: #1e3a8a !important; font-size: 28px !important; font-weight: 700 !important; }
    div[data-testid="stMetricLabel"] { color: #64748b !important; font-size: 12px !important; text-transform: uppercase !important; font-weight: 600 !important; }

    /* Action Banners */
    .banner { padding: 20px; border-radius: 8px; font-weight: 700; text-align: center; font-size: 18px; margin: 30px 0; border: 1px solid transparent; }
    .banner-hold { background-color: #f1f5f9; color: #475569; border-color: #cbd5e1; }
    .banner-buy { background-color: #eff6ff; color: #1e40af; border-color: #bfdbfe; border-left: 10px solid #1e3a8a; }
    .banner-sell { background-color: #fef2f2; color: #991b1b; border-color: #fecaca; border-left: 10px solid #dc2626; }

    /* Data Table Styling */
    .styled-table { width: 100%; border-collapse: collapse; margin-top: 20px; background-color: white; border-radius: 8px; overflow: hidden; }
    .styled-table th { background-color: #f8fafc; color: #1e3a8a; text-align: left; padding: 15px; font-size: 12px; font-weight: 700; border-bottom: 2px solid #e2e8f0; text-transform: uppercase; }
    .styled-table td { padding: 15px; border-bottom: 1px solid #f1f5f9; color: #334155; font-size: 14px; }
    .styled-table tr:hover { background-color: #f8fafc; }

    /* Button */
    .stButton>button {
        background-color: #1e3a8a !important;
        color: white !important;
        border-radius: 4px !important;
        border: none !important;
        padding: 10px 25px !important;
        font-weight: 600 !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- CORPORATE HEADER ---
st.markdown("""
<div class="header-bar">
    <div>
        <h1 class="header-text">QUANTBENGAL <span style="color:#dc2626">PRO</span></h1>
        <p class="header-tag">Institutional Algorithm Execution Terminal</p>
    </div>
    <div style="text-align:right">
        <p style="color:#10b981; font-weight:700; margin:0; font-size:14px;">● SYSTEM ONLINE</p>
        <p style="color:#64748b; font-size:11px; margin:0;">VER 4.2.0 | SECURE CONNECTION</p>
    </div>
</div>
""", unsafe_allow_html=True)

# --- MAIN CONTENT ---
col_main1, col_main2 = st.columns([1, 2])

with col_main1:
    st.markdown("""
    <div class="rule-card">
        <div class="rule-header">Execution Logic (15m Momentum)</div>
        <ul class="rule-list">
            <li><span class="blue-dot"></span><b>Buy Signal:</b> 9 EMA > 21 EMA + RSI > 55</li>
            <li><span class="red-dot"></span><b>Sell Signal:</b> 9 EMA < 21 EMA + RSI < 45</li>
            <li><span class="blue-dot" style="background-color:#cbd5e1"></span><b>Risk Control:</b> Neutral on Sideways</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("SYNC TERMINAL DATA"):
        st.rerun()

with col_main2:
    try:
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

            # --- METRICS ---
            m1, m2, m3 = st.columns(3)
            m1.metric("NIFTY 50 INDEX", f"₹{latest_price:,.2f}")
            m2.metric("MOMENTUM RSI", f"{latest['rsi']:.2f}")
            m3.metric("TREND (9/21 EMA)", f"{latest['ema_9']-latest['ema_21']:.2f} Pts")

            # --- SIGNAL BANNER ---
            if previous['ema_9'] <= previous['ema_21'] and latest['ema_9'] > latest['ema_21'] and latest['rsi'] > 55:
                st.markdown('<div class="banner banner-buy">PRO-SIGNAL: EXECUTE LONG (BUY CALL)</div>', unsafe_allow_html=True)
            elif previous['ema_9'] >= previous['ema_21'] and latest['ema_9'] < latest['ema_21'] and latest['rsi'] < 45:
                st.markdown('<div class="banner banner-sell">PRO-SIGNAL: EXECUTE SHORT (BUY PUT)</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="banner banner-hold">PRO-SIGNAL: NEUTRAL (AWAITING MOMENTUM)</div>', unsafe_allow_html=True)

            # --- TABLE ---
            st.markdown("<div style='margin-top:20px; font-weight:700; color:#1e3a8a; font-size:14px;'>LIVE DATA FEED</div>", unsafe_allow_html=True)
            df['ts'] = pd.to_datetime(df['ts']).dt.strftime('%H:%M')
            display_df = df[['ts', 'close', 'ema_9', 'ema_21', 'rsi']].tail(5).round(2)
            
            # Custom HTML Table
            table_html = """<table class="styled-table"><thead><tr><th>Time</th><th>Price</th><th>9 EMA</th><th>21 EMA</th><th>RSI</th></tr></thead><tbody>"""
            for i, row in display_df.iterrows():
                table_html += f"<tr><td>{row['ts']}</td><td>₹{row['close']}</td><td>{row['ema_9']}</td><td>{row['ema_21']}</td><td>{row['rsi']}</td></tr>"
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)

        else:
            st.warning("Establishing Data Stream... Awaiting Market Feed.")

    except Exception as e:
        st.error(f"Hardware/API Connection Error: {e}")
