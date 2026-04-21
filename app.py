import streamlit as st
import pandas as pd
from broker_api import IndianBrokerAPI
from strategy import MomentumStrategy

st.set_page_config(page_title="QuantBengal Pro", layout="wide")

st.title("🚀 QuantBengal F&O Engine")
st.markdown("---")

# Initialize Engine
broker = IndianBrokerAPI()
strategy = MomentumStrategy(broker)

# Dashboard Layout
col1, col2 = st.columns([1, 2])

with col1:
    st.metric(label="System Status", value="ACTIVE", delta="Paper Trading")
    if st.button('🔄 Refresh Market Data'):
        st.rerun()

with col2:
    st.subheader("Live Market Analysis")
    data = broker.get_historical_data()
    if data:
        st.write(f"**Latest Bank Nifty Spot Price:** ₹{data['latest_price']}")
        # Display the last 5 candles in a clean table
        df = pd.DataFrame({'Close': data['close'][-5:], 'High': data['high'][-5:]})
        st.table(df)
    else:
        st.error("Market data currently unavailable.")

st.markdown("### 📜 Automated Trade History")
# This simulates what your bot would show. 
# In Phase 2, we will make this pull from your actual Trade Log CSV.
history = pd.DataFrame({
    'Time': ['09:15', '10:30', '12:45'],
    'Signal': ['BUY_CALL', 'BUY_PUT', 'HOLD'],
    'Price': [44500, 44200, 44350],
    'Status': ['Executed', 'Executed', 'Waiting']
})
st.dataframe(history, use_container_width=True)
