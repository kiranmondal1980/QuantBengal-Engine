import streamlit as st
import pandas as pd

st.set_page_config(page_title="QuantBengal Dashboard", layout="wide")

st.title("📊 QuantBengal F&O Engine")
st.subheader("Live Paper Trading Dashboard")

# Placeholder for your data
st.write("Fetching engine status...")

# Logic: Read your log file or csv here
# For now, let's just show a dummy chart to confirm it works
st.line_chart([100, 102, 101, 105, 107])

if st.button('Refresh Data'):
    st.experimental_rerun()
