import streamlit as st
import pandas as pd
from broker_api import IndianBrokerAPI
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
import yfinance as yf

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="QuantBengal Pro | Institutional Terminal", layout="wide", page_icon="📈")

# --- 2. PREMIUM CORPORATE UI (BLUE & RED) ---
st.markdown("""
    <style>
    .stApp { background-color: #f8fafc; color: #1e293b; font-family: 'Segoe UI', sans-serif; }
    .header-bar {
        background-color: #ffffff; padding: 1.5rem 3rem; border-bottom: 4px solid #1e3a8a;
        display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    .main-title { color: #1e3a8a; font-size: 28px; font-weight: 800; margin: 0; }
    .pro-tag { color: #dc2626; }
    
    /* Tutorial Styling */
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
tab1, tab2, tab3, tab4 = st.tabs(["📈 LIVE TRADING VIEW", "🔬 STRATEGY EXPLAINED", "🎓 MASTER TUTORIAL", "📊 PERFORMANCE AUDIT"])

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
                
                # Indicators Calculated for all modes to ensure table updates correctly
                df['ema_9'] = EMAIndicator(close=df['close'], window=9).ema_indicator()
                df['ema_21'] = EMAIndicator(close=df['close'], window=21).ema_indicator()
                df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
                bb = BollingerBands(close=df["close"], window=20, window_dev=2)
                df['upper_band'] = bb.bollinger_hband()
                df['lower_band'] = bb.bollinger_lband()
                
                latest, prev = df.iloc[-1], df.iloc[-2]
                
                # Metrics Row
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

                # Data Table
                st.markdown(f"**DATA TERMINAL: {algo_mode.upper()}**")
                display_df = df[table_cols].tail(6).round(2)
                table_html = f"""<table class="styled-table"><thead><tr>{' '.join([f'<th>{c.upper()}</th>' for c in table_cols])}</tr></thead><tbody>"""
                for _, r in display_df.iterrows():
                    table_html += "<tr>" + "".join([f"<td>{r[c]}</td>" for c in table_cols]) + "</tr>"
                st.markdown(table_html + "</tbody></table>", unsafe_allow_html=True)
            else: st.info("Initializing Secure Connection...")
        except Exception as e: st.error(f"Hardware Error: {e}")

with tab2:
    st.markdown("### 🔬 Strategy Definitions")
    c1, c2, c3 = st.columns(3)
    with c1: st.info("**Trend Rider:** Uses Moving Average crossovers to identify if a new trend has started.")
    with c2: st.info("**Morning Breakout:** Exploits the high volatility of the first 15 minutes of trading.")
    with c3: st.info("**Safety Zone:** Identifies price extremes. Perfect for non-trending, sideways markets.")

with tab3:
    st.markdown('<div class="tutorial-container">', unsafe_allow_html=True)
    st.markdown("<h1 style='color:#1e3a8a; margin-top:0;'>🎓 QuantBengal Master Tutorial</h1>", unsafe_allow_html=True)
    st.markdown("<p style='color:#64748b;'>Welcome to the future of automated trading. Follow this guide to master the platform.</p><hr>", unsafe_allow_html=True)

with tab4:
    # Notice the 4 spaces before st.markdown
    st.markdown("### 📊 30-Day Historical Performance Audit")
    st.write("This module runs the 'Trend Rider' logic through real market data from the last 30 days.")
    
    if st.button("🚀 RUN BACKTEST"):
        with st.spinner("Analyzing 30 days of market candles..."):
            # All following lines must be indented further...
            hist_data = yf.download("^NSEI", period="1mo", interval="15m")
            
            if not hist_data.empty:
                # FIX: Ensure data is 1-dimensional by using .squeeze()
                # and selecting only the 'Close' column clearly.
                close_prices = hist_data['Close'].squeeze()
                
                df_hist = hist_data.copy()
                
                # 2. Apply Indicators using the flattened close_prices
                df_hist['ema_9'] = EMAIndicator(close=close_prices, window=9).ema_indicator()
                df_hist['ema_21'] = EMAIndicator(close=close_prices, window=21).ema_indicator()
                df_hist['rsi'] = RSIIndicator(close=close_prices, window=14).rsi()
                
                # 3. Simulation Logic
                trades = []
                in_pos = False
                entry_price = 0
                
                for i in range(1, len(df_hist)):
                    # Check for BUY_CALL Crossover
                    if not in_pos:
                        if df_hist['ema_9'].iloc[i-1] <= df_hist['ema_21'].iloc[i-1] and \
                           df_hist['ema_9'].iloc[i] > df_hist['ema_21'].iloc[i] and \
                           df_hist['rsi'].iloc[i] > 55:
                            
                            entry_price = df_hist['Close'].iloc[i]
                            trades.append({'Date': df_hist.index[i], 'Signal': 'BUY_CALL', 'Entry': entry_price})
                            in_pos = True
                            
                    # Exit logic (Exit when EMA crosses back)
                    elif in_pos:
                        if df_hist['ema_9'].iloc[i] < df_hist['ema_21'].iloc[i]:
                            exit_p = df_hist['Close'].iloc[i]
                            trades[-1]['Exit'] = exit_p
                            trades[-1]['Points'] = exit_p - entry_price
                            in_pos = False

                # 4. Show Results
                res = pd.DataFrame(trades)
                if not res.empty:
                    m1, m2, m3 = st.columns(3)
                    win_rate = (res['Points'] > 0).mean() * 100
                    total_pnl = res['Points'].sum()
                    
                    with m1: st.metric("WIN RATE", f"{win_rate:.1f}%")
                    with m2: st.metric("TOTAL POINTS Gained", f"+{total_pnl:.1f}")
                    with m3: st.metric("TOTAL SIGNALS", len(res))
                    
                    # Charting the performance
                    st.markdown("#### Cumulative Profit Curve")
                    res['Cumulative'] = res['Points'].cumsum()
                    st.line_chart(res.set_index('Date')['Cumulative'])
                    
                    st.markdown("#### Detailed Backtest Trade Log")
                    st.dataframe(res.style.format(precision=2), use_container_width=True)
                else:
                    st.warning("No signals were found in this 30-day period.")
            else:
                st.error("Failed to fetch historical data from Yahoo Finance.")
    
    # STEP 1
    st.markdown("""<div class="tut-step">
        <span class="blue-badge">Step 1</span>
        <div class="tut-header">The Engine Setup (SmartAPI)</div>
        <div class="tut-text">Your first task is to link your Demat account. Log into the <b>Angel One SmartAPI</b> portal and create an app. Copy your <b>API Key</b> and your <b>TOTP Secret</b>. These are the "keys" that allow our math engine to speak to the market.</div>
    </div>""", unsafe_allow_html=True)
    
    # STEP 2
    st.markdown("""<div class="tut-step">
        <span class="blue-badge">Step 2</span>
        <div class="tut-header">Choosing Your Strategy</div>
        <div class="tut-text">Every market condition requires a different tool:
            <ul>
                <li><b>The Trend Rider:</b> Use this when the market is moving fast up or down.</li>
                <li><b>The Morning Breakout:</b> Check this only between 9:45 AM and 10:30 AM.</li>
                <li><b>The Safety Zone:</b> Use this when the market is boring and moving sideways.</li>
            </ul>
        </div>
    </div>""", unsafe_allow_html=True)
    
    # STEP 3
    st.markdown("""<div class="tut-step">
        <span class="blue-badge">Step 3</span>
        <div class="tut-header">Executing Trades</div>
        <div class="tut-text">Watch the <b>Execution Banner</b>. It will turn <b style='color:#1e40af;'>BLUE</b> for a Bullish trade and <b style='color:#dc2626;'>RED</b> for a Bearish trade. The bot on GitHub Actions is programmed to execute these trades every 15 minutes automatically.</div>
    </div>""", unsafe_allow_html=True)
    
    # STEP 4
    st.markdown("""<div class="tut-step">
        <span class="blue-badge">Step 4</span>
        <div class="tut-header">Risk Management</div>
        <div class="tut-text">Never risk more than 2% of your capital on a single trade. The "RSI" indicator on your dashboard helps you see if a move is exhausted before you entry. If RSI is above 70, think twice before buying more!</div>
    </div>""", unsafe_allow_html=True)
    
    st.success("🏁 **Ready to Start?** Switch back to the 'Live Trading View' to begin monitoring the engine.")
    st.markdown('</div>', unsafe_allow_html=True)
