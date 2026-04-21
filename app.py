import streamlit as st
import pandas as pd
from broker_api import IndianBrokerAPI
from ta.momentum import RSIIndicator

st.set_page_config(page_title="QuantBengal Engine", layout="wide")

st.title("🚀 QuantBengal Algorithmic Engine")
st.markdown("---")

# Layout columns for a clean dashboard
col1, col2, col3 = st.columns(3)

with col1:
    st.metric(label="Engine Status", value="ACTIVE", delta="Connected to Angel One")
    if st.button("🔄 Force Refresh Data"):
        st.rerun()

st.write("Fetching Live Market Data...")

try:
    # 1. Connect to the Broker (Uses Streamlit Secrets automatically)
    broker = IndianBrokerAPI()
    candles = broker.get_data()

    if candles and len(candles) >= 15:
        # 2. Format the Data
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        latest_price = df['close'].iloc[-1]
        
        # 3. Calculate RSI exactly like your backend does
        rsi_series = RSIIndicator(close=df['close'], window=14).rsi()
        current_rsi = round(rsi_series.iloc[-1], 2)
        
        # 4. Determine the Signal
        if current_rsi < 30:
            signal_text = "BUY (Oversold)"
            color = "normal"
        elif current_rsi > 70:
            signal_text = "SELL (Overbought)"
            color = "inverse"
        else:
            signal_text = "HOLD (Neutral)"
            color = "off"

        # 5. Display the Numbers
        with col2:
            st.metric(label="Latest Price (SBIN Test)", value=f"₹{latest_price}")
        with col3:
            st.metric(label="Current RSI (14)", value=current_rsi, delta=signal_text, delta_color=color)

        st.markdown("### 📊 Last 5 Market Candles")
        # Clean up the timestamp for the table
        df['ts'] = pd.to_datetime(df['ts']).dt.strftime('%Y-%m-%d %H:%M')
        st.dataframe(df.tail(5)[['ts', 'open', 'high', 'low', 'close']], use_container_width=True)
        
    else:
        st.error("Waiting for sufficient market data to calculate strategy...")

except Exception as e:
    st.error("Failed to connect to Broker Engine. Check Streamlit logs.")
