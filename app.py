import streamlit as st
import pandas as pd
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
    .header-bar {
        background-color: #ffffff; padding: 1.5rem 3rem; border-bottom: 4px solid #1e3a8a;
        display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    .main-title { color: #1e3a8a; font-size: 28px; font-weight: 800; margin: 0; }
    .pro-tag { color: #dc2626; }
    
    /* Simplified Strategy Cards */
    .simple-card {
        background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
        padding: 20px; margin-bottom: 1rem; box-shadow: 0 4px 6px rgba(0,0,0,0.02);
    }
    .green-light { color: #059669; font-weight: 700; }
    .red-light { color: #dc2626; font-weight: 700; }
    
    /* Professional Banners */
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
st.markdown('<div class="header-bar"><h1 class="main-title">QUANTBENGAL <span class="pro-tag">PRO</span></h1><div style="color:#10b981; font-weight:700;">● SYSTEM ACTIVE</div></div>', unsafe_allow_html=True)

# --- 4. NAVIGATION TABS ---
tab1, tab2, tab3 = st.tabs(["📈 LIVE TRADING VIEW", "🔬 STRATEGY EXPLAINED", "❓ BEGINNER GUIDE"])

with tab1:
    col_ctrl, col_main = st.columns([1, 3])
    
    with col_ctrl:
        st.markdown("### ⚙️ Engine Settings")
        # Beginner-friendly names for algorithms
        algo_mode = st.selectbox(
            "CHOOSE YOUR TRADING STYLE", 
            ["The Trend Rider", "The Morning Breakout", "The Safety Zone"]
        )
        if st.button("🔄 UPDATE LIVE DATA"):
            st.rerun()
        st.divider()
        st.write("**Current Market:** Nifty 50 Index")
        st.write("**Timeframe:** 15 Minute Candles")

    with col_main:
        try:
            broker = IndianBrokerAPI()
            candles = broker.get_data()
            
            if candles and len(candles) >= 30:
                df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                df['ts'] = pd.to_datetime(df['ts']).dt.strftime('%H:%M')
                
                # GLOBAL CALCULATIONS (Calculates everything so tables update correctly)
                df['ema_9'] = EMAIndicator(close=df['close'], window=9).ema_indicator()
                df['ema_21'] = EMAIndicator(close=df['close'], window=21).ema_indicator()
                df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
                bb = BollingerBands(close=df["close"], window=20, window_dev=2)
                df['upper_band'] = bb.bollinger_hband()
                df['lower_band'] = bb.bollinger_lband()
                
                latest = df.iloc[-1]
                prev = df.iloc[-2]
                
                # TOP METRICS
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("CURRENT PRICE", f"₹{latest['close']:,.2f}")
                
                # LOGIC & TABLE DATA SELECTION
                sig, style = "WAITING FOR SIGNAL...", "banner-hold"
                
                if algo_mode == "The Trend Rider":
                    table_cols = ['ts', 'close', 'ema_9', 'ema_21', 'rsi']
                    m2.metric("FAST TREND", round(latest['ema_9'], 1))
                    m3.metric("SLOW TREND", round(latest['ema_21'], 1))
                    m4.metric("STRENGTH", round(latest['rsi'], 1))
                    
                    if prev['ema_9'] <= prev['ema_21'] and latest['ema_9'] > latest['ema_21'] and latest['rsi'] > 55:
                        sig, style = "✅ TREND IS UP: BUY CALL", "banner-buy"
                    elif prev['ema_9'] >= prev['ema_21'] and latest['ema_9'] < latest['ema_21'] and latest['rsi'] < 45:
                        sig, style = "🚨 TREND IS DOWN: BUY PUT", "banner-sell"

                elif algo_mode == "The Morning Breakout":
                    orb_h, orb_l = df.iloc[0]['high'], df.iloc[0]['low']
                    table_cols = ['ts', 'close', 'high', 'low']
                    m2.metric("9:15 HIGH", f"₹{orb_h}")
                    m3.metric("9:15 LOW", f"₹{orb_l}")
                    m4.metric("STATUS", "LIVE")
                    
                    if latest['close'] > orb_h:
                        sig, style = "✅ MORNING BREAKOUT: BUY CALL", "banner-buy"
                    elif latest['close'] < orb_l:
                        sig, style = "🚨 MORNING BREAKDOWN: BUY PUT", "banner-sell"

                elif algo_mode == "The Safety Zone":
                    table_cols = ['ts', 'close', 'lower_band', 'upper_band', 'rsi']
                    m2.metric("BOTTOM BARRIER", round(latest['lower_band'], 1))
                    m3.metric("TOP BARRIER", round(latest['upper_band'], 1))
                    m4.metric("RSI STRENGTH", round(latest['rsi'], 1))
                    
                    if latest['close'] <= latest['lower_band']:
                        sig, style = "✅ PRICE TOO LOW: BUY CALL", "banner-buy"
                    elif latest['close'] >= latest['upper_band']:
                        sig, style = "🚨 PRICE TOO HIGH: BUY PUT", "banner-sell"

                st.markdown(f'<div class="banner {style}">{sig}</div>', unsafe_allow_html=True)

                # DATA STREAM TABLE
                st.markdown(f"**LIVE DATA STREAM: {algo_mode}**")
                display_df = df[table_cols].tail(6).round(2)
                
                # Build custom HTML table
                table_html = f"""<table class="styled-table"><thead><tr>{' '.join([f'<th>{c.upper()}</th>' for c in table_cols])}</tr></thead><tbody>"""
                for _, r in display_df.iterrows():
                    table_html += "<tr>" + "".join([f"<td>{r[c]}</td>" for c in table_cols]) + "</tr>"
                st.markdown(table_html + "</tbody></table>", unsafe_allow_html=True)

            else:
                st.info("🔄 Connecting to Exchange Data...")
        except Exception as e:
            st.error(f"Hardware Link Offline: {e}")

with tab2:
    st.markdown("### 🔬 How Our Strategies Make Money")
    st.write("Each strategy is designed for a specific type of market behavior.")
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""<div class="simple-card"><h4>The Trend Rider</h4><p>Follows the market when it moves strongly in one direction.</p>
        <p class="green-light">🟢 BUY CALL when Blue line crosses Red line upwards.</p>
        <p class="red-light">🔴 BUY PUT when Blue line crosses Red line downwards.</p></div>""", unsafe_allow_html=True)
    with c2:
        st.markdown("""<div class="simple-card"><h4>The Morning Breakout</h4><p>Captures the big move that happens in the first 1 hour.</p>
        <p class="green-light">🟢 BUY CALL if price breaks above 9:15 AM High.</p>
        <p class="red-light">🔴 BUY PUT if price breaks below 9:15 AM Low.</p></div>""", unsafe_allow_html=True)
    with c3:
        st.markdown("""<div class="simple-card"><h4>The Safety Zone</h4><p>Best for sideways markets. It tells you when price is "Too Cheap" or "Too Expensive".</p>
        <p class="green-light">🟢 BUY CALL if price hits the bottom zone.</p>
        <p class="red-light">🔴 BUY PUT if price hits the top zone.</p></div>""", unsafe_allow_html=True)

with tab3:
    st.markdown("""
    <div class="simple-card">
        <h3>📖 Step-By-Step Beginner Guide</h3>
        <p><b>Step 1:</b> Enter your Angel One API keys in the app settings (Secrets).</p>
        <p><b>Step 2:</b> Choose "The Trend Rider" if the market is moving fast. Choose "The Safety Zone" if the market is moving slow.</p>
        <p><b>Step 3:</b> Watch the <b>Signal Banner</b>. If it stays Gray, the market is not safe. If it turns Blue or Red, the math is ready.</p>
        <p><b>Step 4:</b> The bot on GitHub is doing the hard work in the background. This page is just for you to watch the live math.</p>
    </div>
    """, unsafe_allow_html=True)
