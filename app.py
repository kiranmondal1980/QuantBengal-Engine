import streamlit as st
import pandas as pd
from flask import Flask, request, jsonify
import threading

app = Flask(__name__)

# This will store the latest signal from TradingView
trade_signals = []

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    trade_signals.append(data)
    return jsonify({"status": "received"}), 200

# Function to run Flask in the background
def run_flask():
    app.run(port=5000)

# Start Flask in a background thread
threading.Thread(target=run_flask, daemon=True).start()

# Streamlit UI
st.title("🚀 QuantBengal TradingView Engine")
st.write("Listening for TradingView Alerts on /webhook")

if st.button("Refresh Signals"):
    st.rerun()

st.subheader("Last 5 Signals")
if trade_signals:
    df = pd.DataFrame(trade_signals)
    st.table(df.tail(5))
else:
    st.info("Waiting for TradingView signal...")
