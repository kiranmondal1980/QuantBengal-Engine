import streamlit as st
import pandas as pd
from broker_api import IndianBrokerAPI
from datetime import datetime
import pytz

st.set_page_config(page_title="QuantBengal Pro", layout="wide")

st.title("🚀 QuantBengal F&O Engine")
st.markdown("---")

# Initialize Engine
broker = IndianBrokerAPI()

# Dashboard Layout
col1, col2 = st.columns([1, 2])

with col1:
    st.metric(label="System Status", value="ACTIVE")
    if st.button('🔄 Refresh Market Data'):
        st.rerun()

with col2:
    st.subheader("Live Market Analysis")
    
    # Attempt to fetch data
    data = broker.get_historical_data()
    
    # Check if data was returned
    if data and 'latest_price' in data:
        st.success(f"**Connected to Live Market**")
        st.metric(label="Bank Nifty Spot Price", value=f"₹{data['latest_price']}")
        
        # Create a clean table for the last 5 candles
        df = pd.DataFrame({'Close': data['close'][-5:], 'High': data['high'][-5:]})
        st.table(df)
    else:
        # Check if it's market hours
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        
        if now.weekday() < 5 and 9 <= now.hour < 16:
            st.error("Market is open, but API is not returning data. Check your API Keys/TOTP.")
        else:
            st.info("Market is closed. Waiting for next session.")

st.markdown("### 📜 Automated Trade History")
history = pd.DataFrame({
    'Time': ['09:15', '10:30', '12:45'],
    'Signal': ['BUY_CALL', 'BUY_PUT', 'HOLD'],
    'Price': [44500, 44200, 44350],
    'Status': ['Executed', 'Executed', 'Waiting']
})
st.dataframe(history, use_container_width=True)
