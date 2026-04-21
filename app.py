import streamlit as st
import pandas as pd
from broker_api import IndianBrokerAPI
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

# --- 1. PAGE SETUP ---
st.set_page_config(page_title="QuantBengal Pro Terminal", layout="wide", page_icon="📈")

# --- 2. CORPORATE BLUE & RED CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #f8fafc; color: #1e293b; font-family: 'Inter', sans-serif; }
    
    /* Header Bar */
    .header-bar {
        background-color: #ffffff;
        padding: 1rem 2rem;
        border-bottom: 4px solid #1e3a8a;
        margin-bottom: 1.5rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .header-text { margin: 0; color: #1e3a8a; font-size: 24px; font-weight: 800; }
    
    /* Sidebar Area */
    section[data-testid="stSidebar"] { background-color: #1e3a8a !important; color: white !important; width: 350px !important; }
    section[data-testid="stSidebar"] .stMarkdown { color: white !important; }

    /* Card Styling */
    .content-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 20px;
        margin-bottom: 1rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .card-header { 
        color: #1e3a8a; 
        font-size: 14px; 
        font-weight: 700; 
        text-transform: uppercase; 
        border-bottom: 1px solid #f1f5f9; 
        padding-bottom: 8px; 
        margin-bottom: 12px;
        display: flex;
        align-items: center;
    }

    /* Signal Banners */
    .banner { padding: 15px; border-radius: 6px; font-weight: 700; text-align: center; font-size: 16px; margin: 15px 0; border: 1px solid transparent; }
    .banner-hold { background-color: #f1f5f9; color: #475569; border-color: #cbd5e1; }
    .banner-buy { background-color: #eff6ff; color: #1e40af; border-color: #bfdbfe; border-left: 8px solid #1e3a8a; }
    .banner-sell { background-color: #fef2f2; color: #991b1b; border-color: #fecaca; border-left: 8px solid #dc2626; }

    /* Professional Table */
    .styled-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
    .styled-table th { background-color: #f8fafc; color: #1e3a8a; text-align: left; padding: 10px; font-weight: 700; border-bottom: 2px solid #e2e8f0; }
    .styled-table td { padding: 10px; border-bottom: 1px solid #f1f5f9; color: #334155; }
    </style>
""", unsafe_allow_html=True)

# --- 3. TOP BAR ---
st.markdown("""
<div class="header-bar">
    <h1 class="header-text">QUANTBENGAL <span style="color:#dc2626">PRO</span> <span style="font-size:12px; color:#64748b; font-weight:400; margin-left:15px;">INSTITUTIONAL ALGO TERMINAL v6.0</span></h1>
    <div style="text-align:right; color:#10b981; font-weight:700; font-size:13px;">● ENGINE LIVE</div>
</div>
""", unsafe_allow_html=True)

# --- 4. LAYOUT: SIDEBAR (GUIDE) & MAIN (TERMINAL) ---
with st.sidebar:
    st.markdown("### 📖 BEGINNER USER GUIDE")
    st.markdown("""
    ---
    **Step 1: Connection**
    The engine connects via Angel One SmartAPI using your encrypted TOTP. 
    
    **Step 2: Strategy selection**
    Choose your logic. The 9/21 EMA handles trends, while Bollinger handles volatility.
    
    **Step 3: Signal Execution**
    Watch the banner. **BLUE** means the math favors a Buy Call. **RED** favors a Buy Put.
    
    **Step 4: Automation**
    The bot on GitHub executes these trades every 15 minutes. You do not need this page open to trade.
    
    ---
    ### ⚙️ SYSTEM SETTINGS
    """)
    algo_choice = st.selectbox("ACTIVE ALGORITHM", ["9/21 EMA Momentum", "Bollinger Mean Reversion"])
    if st.button("🔄 REFRESH LIVE ENGINE"):
        st.rerun()

# --- 5. MAIN TERMINAL AREA ---
col_left, col_right = st.columns([1, 2.5])

with col_left:
    # PERMANENT STRATEGY RULES VISIBLE HERE
    st.markdown(f"""
    <div class="content-card">
        <div class="card-header">📊 ACTIVE STRATEGY RULES</div>
        <div style="font-size:13px; color:#475569;">
            <b>Current: {algo_choice}</b><br><br>
            • <b>Buy Call:</b> Fast EMA crosses Slow EMA + RSI Strength.<br>
            • <b>Buy Put:</b> Fast EMA drops below Slow EMA + RSI Weakness.<br>
            • <b>Risk:</b> System avoids execution in low-volume sideways markets.
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    st.info("💡 Tip: Use 15m intervals for best results.")

with col_right:
    try:
        broker = IndianBrokerAPI()
        candles = broker.get_data()

        if candles and len(candles) >= 30:
            df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            
            # MATH CALCULATIONS
            df['ema_9'] = EMAIndicator(close=df['close'], window=9).ema_indicator()
            df['ema_21'] = EMAIndicator(close=df['close'], window=21).ema_indicator()
            df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            # METRICS ROW
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("NIFTY 50 SPOT", f"₹{latest['close']:,.2f}")
            m2.metric("9 EMA", f"{latest['ema_9']:,.1f}")
            m3.metric("21 EMA", f"{latest['ema_21']:,.1f}")
            m4.metric("RSI", f"{latest['rsi']:.1f}")

            # SIGNAL LOGIC
            signal = "AWAITING MARKET MOMENTUM"
            style = "banner-hold"
            
            if prev['ema_9'] <= prev['ema_21'] and latest['ema_9'] > latest['ema_21'] and latest['rsi'] > 55:
                signal = "🚀 PRO-SIGNAL: BULLISH CROSSOVER - BUY CALL"; style = "banner-buy"
            elif prev['ema_9'] >= prev['ema_21'] and latest['ema_9'] < latest['ema_21'] and latest['rsi'] < 45:
                signal = "📉 PRO-SIGNAL: BEARISH BREAKDOWN - BUY PUT"; style = "banner-sell"
            
            st.markdown(f'<div class="banner {style}">{signal}</div>', unsafe_allow_html=True)

            # DATA STREAM TABLE (Now with indicators)
            st.markdown("<div class='card-header'>📡 LIVE DATA STREAM (PRICE + MATH)</div>", unsafe_allow_html=True)
            df['ts'] = pd.to_datetime(df['ts']).dt.strftime('%H:%M')
            display_df = df[['ts', 'close', 'ema_9', 'ema_21', 'rsi']].tail(6).round(2)
            
            # Manual HTML table for full control
            table_html = """<table class="styled-table"><thead><tr><th>TIME</th><th>PRICE</th><th>9 EMA</th><th>21 EMA</th><th>RSI</th></tr></thead><tbody>"""
            for _, row in display_df.iterrows():
                table_html += f"<tr><td>{row['ts']}</td><td>₹{row['close']}</td><td>{row['ema_9']}</td><td>{row['ema_21']}</td><td>{row['rsi']}</td></tr>"
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)

        else:
            st.error("Awaiting data from Exchange...")
    except Exception as e:
        st.error(f"Engine Connection Error: {e}")
