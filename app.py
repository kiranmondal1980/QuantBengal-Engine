import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from broker_api import IndianBrokerAPI
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="QuantBengal Pro | Institutional Terminal", layout="wide", page_icon="📈")

# --- 2. PREMIUM CORPORATE UI (BLUE & RED) ---
st.markdown("""
    <style>
    .stApp { background-color: #f8fafc; color: #1e293b; font-family: 'Segoe UI', sans-serif; }
    .header-bar { background-color: #ffffff; padding: 1.5rem 3rem; border-bottom: 4px solid #1e3a8a; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
    .main-title { color: #1e3a8a; font-size: 28px; font-weight: 800; margin: 0; }
    .pro-tag { color: #dc2626; }
    
    /* Tutorial / Guide Styling */
    .tutorial-container { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 30px; margin-bottom: 20px; }
    .tut-step { border-left: 4px solid #1e3a8a; padding-left: 20px; margin-bottom: 30px; }
    .tut-header { color: #1e3a8a; font-size: 20px; font-weight: 700; margin-bottom: 10px; }
    .tut-text { color: #475569; font-size: 15px; line-height: 1.6; }
    .blue-badge { background-color: #eff6ff; color: #1e40af; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; text-transform: uppercase; }
    
    /* Signal Banners */
    .banner { padding: 20px; border-radius: 8px; font-weight: 800; text-align: center; font-size: 18px; margin: 15px 0; text-transform: uppercase; }
    .banner-hold { background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }
    .banner-buy { background-color: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; border-left: 12px solid #1e3a8a; }
    .banner-sell { background-color: #fef2f2; color: #991b1b; border: 1px solid #fecaca; border-left: 12px solid #dc2626; }

    /* Clean Data Table */
    .styled-table { width: 100%; border-collapse: collapse; background-color: white; font-size: 14px; border-radius: 8px; overflow: hidden;}
    .styled-table th { background-color: #f8fafc; color: #1e3a8a; text-align: left; padding: 12px; font-weight: 700; border-bottom: 2px solid #e2e8f0; }
    .styled-table td { padding: 12px; border-bottom: 1px solid #f1f5f9; color: #334155; }
    </style>
""", unsafe_allow_html=True)

# --- 3. TOP HEADER ---
st.markdown('<div class="header-bar"><h1 class="main-title">QUANTBENGAL <span class="pro-tag">PRO</span></h1><div style="color:#10b981; font-weight:700;">● PRODUCTION ENGINE LIVE</div></div>', unsafe_allow_html=True)

# --- 4. NAVIGATION TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["📈 LIVE TERMINAL", "🔬 STRATEGY SUITE", "📊 PERFORMANCE AUDIT", "🎓 MASTER TUTORIAL"])

# ==========================================
# TAB 1: LIVE TERMINAL
# ==========================================
with tab1:
    col_ctrl, col_main = st.columns([1, 3])
    with col_ctrl:
        st.markdown("### ⚙️ Engine Settings")
        algo_mode = st.selectbox("CHOOSE TRADING STYLE", ["The Trend Rider", "The Morning Breakout", "The Safety Zone"])
        if st.button("🔄 REFRESH LIVE DATA"):
            st.rerun()
        st.divider()
        st.write("**Market:** Nifty 50 Index")
        st.write("**Frequency:** 15 Minute Interval")

    with col_main:
        try:
            broker = IndianBrokerAPI()
            candles = broker.get_data()
            if candles and len(candles) >= 30:
                df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                df['ts'] = pd.to_datetime(df['ts']).dt.strftime('%H:%M')
                
                # Indicators Calculated for all modes
                df['ema_9'] = EMAIndicator(close=df['close'], window=9).ema_indicator()
                df['ema_21'] = EMAIndicator(close=df['close'], window=21).ema_indicator()
                df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
                bb = BollingerBands(close=df["close"], window=20, window_dev=2)
                df['upper_band'] = bb.bollinger_hband()
                df['lower_band'] = bb.bollinger_lband()
                
                latest, prev = df.iloc[-1], df.iloc[-2]
                
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("LIVE PRICE", f"₹{latest['close']:,.2f}")
                
                sig, style = "AWAITING MARKET OPPORTUNITY", "banner-hold"
                
                if algo_mode == "The Trend Rider":
                    table_cols = ['ts', 'close', 'ema_9', 'ema_21', 'rsi']
                    m2.metric("FAST EMA", round(latest['ema_9'], 1)); m3.metric("SLOW EMA", round(latest['ema_21'], 1)); m4.metric("RSI", round(latest['rsi'], 1))
                    if prev['ema_9'] <= prev['ema_21'] and latest['ema_9'] > latest['ema_21'] and latest['rsi'] > 55:
                        sig, style = "✅ BULLISH TREND DETECTED: BUY CALL", "banner-buy"
                    elif prev['ema_9'] >= prev['ema_21'] and latest['ema_9'] < latest['ema_21'] and latest['rsi'] < 45:
                        sig, style = "🚨 BEARISH TREND DETECTED: BUY PUT", "banner-sell"

                elif algo_mode == "The Morning Breakout":
                    orb_h, orb_l = df.iloc[0]['high'], df.iloc[0]['low']
                    table_cols = ['ts', 'close', 'high', 'low']
                    m2.metric("9:15 HIGH", f"₹{orb_h}"); m3.metric("9:15 LOW", f"₹{orb_l}"); m4.metric("ZONE", "LIVE")
                    if latest['close'] > orb_h: sig, style = "✅ MORNING BREAKOUT: BUY CALL", "banner-buy"
                    elif latest['close'] < orb_l: sig, style = "🚨 MORNING BREAKDOWN: BUY PUT", "banner-sell"

                elif algo_mode == "The Safety Zone":
                    table_cols = ['ts', 'close', 'lower_band', 'upper_band', 'rsi']
                    m2.metric("MIN ZONE", round(latest['lower_band'], 1)); m3.metric("MAX ZONE", round(latest['upper_band'], 1)); m4.metric("RSI", round(latest['rsi'], 1))
                    if latest['close'] <= latest['lower_band']: sig, style = "✅ OVERSOLD: BUY CALL", "banner-buy"
                    elif latest['close'] >= latest['upper_band']: sig, style = "🚨 OVERBOUGHT: BUY PUT", "banner-sell"

                st.markdown(f'<div class="banner {style}">{sig}</div>', unsafe_allow_html=True)
                st.markdown(f"**DATA TERMINAL: {algo_mode.upper()}**")
                display_df = df[table_cols].tail(6).round(2)
                table_html = f"""<table class="styled-table"><thead><tr>{' '.join([f'<th>{c.upper()}</th>' for c in table_cols])}</tr></thead><tbody>"""
                for _, r in display_df.iterrows():
                    table_html += "<tr>" + "".join([f"<td>{r[c]}</td>" for c in table_cols]) + "</tr>"
                st.markdown(table_html + "</tbody></table>", unsafe_allow_html=True)
            else: st.info("Initializing Secure Connection...")
        except Exception as e: st.error(f"Hardware Error: {e}")

# ==========================================
# TAB 2: STRATEGY SUITE
# ==========================================
with tab2:
    st.markdown("### 🔬 Strategy Definitions")
    c1, c2, c3 = st.columns(3)
    with c1: st.info("**The Trend Rider:** Uses 9 & 21 Moving Average crossovers to identify if a new trend has started. Best for directional markets.")
    with c2: st.info("**The Morning Breakout:** Exploits the high volatility of the first 15 minutes of trading. Wait for the 9:15 range to break.")
    with c3: st.info("**The Safety Zone:** Identifies extreme price levels using Bollinger Bands. Perfect for non-trending, sideways markets.")

# ==========================================
# TAB 3: PERFORMANCE AUDIT (BACKTESTING)
# ==========================================
with tab3:
    st.markdown("### 📊 30-Day Historical Performance Audit")
    st.write("Analysis of 'The Trend Rider' (9/21 EMA) logic on real Nifty 50 data from the past month.")
    
    if st.button("🚀 RUN 30-DAY BACKTEST"):
        with st.spinner("Analyzing historical candles..."):
            hist_data = yf.download("^NSEI", period="1mo", interval="15m", progress=False)
            
            if not hist_data.empty:
                # FIX: Force data into 1D array of pure float numbers to prevent Pandas crash
                close_prices = hist_data['Close'].squeeze().astype(float)
                
                df_hist = hist_data.copy()
                df_hist['ema_9'] = EMAIndicator(close=close_prices, window=9).ema_indicator()
                df_hist['ema_21'] = EMAIndicator(close=close_prices, window=21).ema_indicator()
                df_hist['rsi'] = RSIIndicator(close=close_prices, window=14).rsi()
                
                trades = []
                in_pos = False
                entry_price = 0.0
                
                for i in range(1, len(df_hist)):
                    if not in_pos:
                        if df_hist['ema_9'].iloc[i-1] <= df_hist['ema_21'].iloc[i-1] and df_hist['ema_9'].iloc[i] > df_hist['ema_21'].iloc[i] and df_hist['rsi'].iloc[i] > 55:
                            entry_price = float(close_prices.iloc[i])
                            trades.append({'Date': df_hist.index[i], 'Signal': 'BUY CALL', 'Entry': entry_price})
                            in_pos = True
                    elif in_pos:
                        if df_hist['ema_9'].iloc[i] < df_hist['ema_21'].iloc[i]:
                            exit_p = float(close_prices.iloc[i])
                            trades[-1]['Exit'] = exit_p
                            trades[-1]['Points'] = exit_p - entry_price
                            in_pos = False
                
                # Clean up any open trades at the end of the month
                trades = [t for t in trades if 'Points' in t]
                
                res_df = pd.DataFrame(trades)
                if not res_df.empty:
                    # Double ensure Points is float for math
                    res_df['Points'] = res_df['Points'].astype(float)
                    
                    m1, m2, m3 = st.columns(3)
                    win_rate = (res_df['Points'] > 0).mean() * 100
                    total_pts = res_df['Points'].sum()
                    
                    with m1: st.metric("WIN RATE", f"{win_rate:.1f}%")
                    with m2: st.metric("TOTAL INDEX POINTS", f"+{total_pts:.1f}")
                    with m3: st.metric("TOTAL TRADES", len(res_df))
                    
                    st.markdown("#### Cumulative Profit Curve (Index Points)")
                    res_df['Cumulative'] = res_df['Points'].cumsum()
                    st.line_chart(res_df.set_index('Date')['Cumulative'])
                    
                    st.markdown("#### Detailed Historical Trade Log")
                    st.dataframe(res_df.round(2), use_container_width=True)
                else:
                    st.warning("No complete trades found in the last 30 days.")
            else:
                st.error("Failed to fetch historical data.")

# ==========================================
# TAB 4: MASTER TUTORIAL
# ==========================================
with tab4:
    st.markdown('<div class="tutorial-container">', unsafe_allow_html=True)
    st.markdown("<h1 style='color:#1e3a8a; margin-top:0;'>🎓 QuantBengal Master Tutorial</h1>", unsafe_allow_html=True)
    st.markdown("<p style='color:#64748b;'>Follow this guide to master the platform.</p><hr>", unsafe_allow_html=True)
    
    st.markdown("""<div class="tut-step">
        <span class="blue-badge">Step 1</span><div class="tut-header">The Engine Setup</div>
        <div class="tut-text">Link your Demat account. Log into the <b>Angel One SmartAPI</b> portal and copy your <b>API Key</b> and <b>TOTP Secret</b> into the Settings.</div>
    </div>""", unsafe_allow_html=True)
    
    st.markdown("""<div class="tut-step">
        <span class="blue-badge">Step 2</span><div class="tut-header">Choosing Your Strategy</div>
        <div class="tut-text">Every market condition requires a different tool. Use the <b>Live Terminal</b> sidebar to switch between Trend, Morning Breakout, and Safety Zone.</div>
    </div>""", unsafe_allow_html=True)
    
    st.markdown("""<div class="tut-step">
        <span class="blue-badge">Step 3</span><div class="tut-header">Executing Trades</div>
        <div class="tut-text">Watch the <b>Execution Banner</b>. It turns <b style='color:#1e40af;'>BLUE</b> for Buy Call and <b style='color:#dc2626;'>RED</b> for Buy Put. If it's gray, the system is protecting your capital by holding.</div>
    </div>""", unsafe_allow_html=True)
    
    st.markdown("""<div class="tut-step">
        <span class="blue-badge">Step 4</span><div class="tut-header">Risk Management</div>
        <div class="tut-text">Never risk more than 2% of your capital. Run the <b>Performance Audit</b> tab to see the mathematical history of the strategy before you commit money.</div>
    </div>""", unsafe_allow_html=True)
    
    st.success("🏁 **Ready to Start?** Switch back to the 'Live Terminal' to begin monitoring the engine.")
    st.markdown('</div>', unsafe_allow_html=True)
