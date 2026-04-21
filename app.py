import streamlit as st
import pandas as pd

st.set_page_config(page_title="QuantBengal Dashboard", layout="wide")

st.title("📊 QuantBengal F&O Engine")
st.subheader("Live Paper Trading Dashboard")

# Placeholder for your data
st.write("Fetching engine status...")

# Logic: Your chart
st.line_chart([100, 102, 101, 105, 107])

# The Fix is right here:
if st.button('Refresh Data'):
    st.rerun()
