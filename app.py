import streamlit as st
import pandas as pd
from broker_api import IndianBrokerAPI
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="QuantBengal Pro", layout="wide", page_icon="📈")

# --- CUSTOM CSS FOR PROFESSIONAL LOOK ---
st.markdown("""
    <style>
    .metric-card {background-color: #f0f2f6; padding: 15px; border-radius: 10px; text-align: center; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);}
    .strategy-box {background-color: #e8f4f8; border-left: 5px solid #1f77b4; padding: 15px; margin-bottom: 20px;}
    </style>
""", unsafe_allow_html=True)

# --- HEADER ---
st.title("🚀 QuantBengal Algorithmic Engine")
st.markdown("**Automated Options Trading System for Tech Professionals**")
st.markdown("---")

# --- THE STRATEGY EXPLANATION (For the User) ---
st.markdown('<div class="strategy-box">', unsafe_allow_html=True)
st.markdown("""
### 🧠 How The Engine Works (The Trading Rule)
This system does not gamble. It uses a mathematical **Momentum Breakout Strategy** designed to catch highly profitable trends while avoiding choppy markets.
*   **The Trend:** We monitor the **9 EMA** (Fast) and **21 EMA** (Slow).
*   **The Volume:** We verify strength using the **RSI (14)**.
*   **BUY CALL Logic:** If the 9 EMA crosses *above* the 21 EMA **AND** RSI is > 55, the engine automatically buys ATM Calls.
*   **BUY PUT Logic:** If the 9 EMA crosses *below* the 21 EMA **AND** RSI is < 45, the engine automatically buys ATM Puts.
""")
st.markdown('</div>', unsafe_allow_html=True)

# --- DASHBOARD CONTROLS ---
col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="Engine Status", value="🟢 ACTIVE", delta="API Connected")
    if st.button("🔄 Force Refresh Live Data"):
        st.rerun()

st.markdown("---")
st.write("📡 Fetching Live Market Data from Exchange...")

try:
    # --- FETCH LIVE DATA ---
    broker = IndianBrokerAPI()
    candles = broker.get_data()

    if candles and len(candles) >= 30:
        # Convert to DataFrame
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        latest_price = df['close'].iloc[-1]
        
        # Calculate Indicators exactly like the strategy bot
        df['ema_9'] = EMAIndicator(close=df['close'], window=9).ema_indicator()
        df['ema_21'] = EMAIndicator(close=df['close'], window=21).ema_indicator()
        df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
        
        latest = df.iloc[-1]
        
        # --- DISPLAY LIVE METRICS ---
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Market Price (Spot)", f"₹{latest_price}")
        col_b.metric("9 EMA (Fast)", round(latest['ema_9'], 2))
        col_c.metric("21 EMA (Slow)", round(latest['ema_21'], 2))
        col_d.metric("RSI Strength", round(latest['rsi'], 2))

        # --- DETERMINE LIVE SIGNAL DISPLAY ---
        signal_display = "⚖️ HOLDING (Market in Range)"
        alert_color = "warning"
        
        previous = df.iloc[-2]
        if previous['ema_9'] <= previous['ema_21'] and latest['ema_9'] > latest['ema_21'] and latest['rsi'] > 55:
            signal_display = "🟢 BUY CALL TRIGGERED (Bullish Momentum Breakout)"
            alert_color = "success"
        elif previous['ema_9'] >= previous['ema_21'] and latest['ema_9'] < latest['ema_21'] and latest['rsi'] < 45:
            signal_display = "🔴 BUY PUT TRIGGERED (Bearish Momentum Breakdown)"
            alert_color = "error"

        st.markdown("### 🎯 Current System Action:")
        if alert_color == "success":
            st.success(signal_display)
        elif alert_color == "error":
            st.error(signal_display)
        else:
            st.warning(signal_display)

        # --- SHOW RECENT DATA TABLE ---
        st.markdown("### 📊 Live OHLC Data Feed (15 Min Interval)")
        df['ts'] = pd.to_datetime(df['ts']).dt.strftime('%Y-%m-%d %H:%M')
        # Display only relevant columns rounded to 2 decimals
        display_df = df[['ts', 'close', 'ema_9', 'ema_21', 'rsi']].tail(5).round(2)
        st.dataframe(display_df, use_container_width=True)
        
    else:
        st.error("Market data unavailable or insufficient to calculate moving averages. Waiting for next market session.")

except Exception as e:
    st.error(f"Failed to connect to Broker Engine. Ensure Secrets are configured. Error: {e}")
