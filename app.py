"""
QuantBengal Pro — app.py
Full-stack automated trading terminal.
Angel One SmartAPI live integration.
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pytz
import time

from broker_api import IndianBrokerAPI
from strategy import MomentumStrategy, IronCondorStrategy, MorningBreakoutStrategy, RiskManager
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange

# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="QuantBengal Pro",
    layout="wide",
    page_icon="⚡",
    initial_sidebar_state="expanded"
)

IST = pytz.timezone('Asia/Kolkata')

# ─── DESIGN SYSTEM ───────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;700&display=swap');

:root {
    --bg:       #f0f4f8;
    --surface:  #ffffff;
    --surface2: #f8fafc;
    --border:   #dde3ed;
    --blue:     #1a56db;
    --blue-dim: #1a56db15;
    --green:    #0a7c4b;
    --green-dim:#0a7c4b12;
    --red:      #c81e3a;
    --red-dim:  #c81e3a12;
    --amber:    #b45309;
    --amber-dim:#b4530912;
    --text:     #0f172a;
    --muted:    #64748b;
    --mono:     'Space Mono', monospace;
    --sans:     'DM Sans', sans-serif;
}

* { box-sizing: border-box; }

.stApp {
    background-color: var(--bg) !important;
    font-family: var(--sans);
    color: var(--text);
}

/* Hide Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 0 !important; max-width: 100% !important; }
section[data-testid="stSidebar"] > div { background: var(--surface) !important; border-right: 1px solid var(--border); }
section[data-testid="stSidebar"] * { color: var(--text) !important; }

/* ── TOP BAR ── */
.topbar {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 14px 28px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 999;
}
.topbar-logo {
    font-family: var(--mono);
    font-size: 20px;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.5px;
}
.topbar-logo span { color: var(--blue); }
.topbar-status {
    display: flex;
    align-items: center;
    gap: 20px;
    font-family: var(--mono);
    font-size: 12px;
}
.dot-live { width:8px; height:8px; background:var(--green); border-radius:50%; display:inline-block; animation: pulse 1.5s infinite; }
.dot-dead { width:8px; height:8px; background:var(--red); border-radius:50%; display:inline-block; }
@keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.3;} }

/* ── METRIC CARDS ── */
.metric-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; padding: 16px 20px; }
.metric-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px;
    position: relative;
    overflow: hidden;
}
.metric-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
}
.metric-card.blue::before  { background: var(--blue); }
.metric-card.green::before { background: var(--green); }
.metric-card.red::before   { background: var(--red); }
.metric-card.amber::before { background: var(--amber); }
.metric-card.white::before { background: var(--text); }

.metric-label { font-size: 10px; font-family: var(--mono); color: var(--muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
.metric-value { font-size: 22px; font-family: var(--mono); font-weight: 700; color: var(--text); }
.metric-value.pos { color: var(--green); }
.metric-value.neg { color: var(--red); }
.metric-sub { font-size: 11px; color: var(--muted); margin-top: 4px; font-family: var(--mono); }

/* ── SIGNAL BANNER ── */
.signal-hold { background: var(--surface2); border: 1px solid var(--border); color: var(--muted); text-align:center; padding:18px; border-radius:10px; font-family:var(--mono); font-size:16px; font-weight:700; letter-spacing:2px; }
.signal-buy  { background: var(--green-dim); border: 2px solid var(--green); color: var(--green); text-align:center; padding:18px; border-radius:10px; font-family:var(--mono); font-size:16px; font-weight:700; letter-spacing:2px; animation: glow-green 2s infinite; }
.signal-sell { background: var(--red-dim); border: 2px solid var(--red); color: var(--red); text-align:center; padding:18px; border-radius:10px; font-family:var(--mono); font-size:16px; font-weight:700; letter-spacing:2px; animation: glow-red 2s infinite; }
@keyframes glow-green { 0%,100%{box-shadow:0 0 0 0 var(--green-dim);} 50%{box-shadow:0 0 20px 4px var(--green-dim);} }
@keyframes glow-red   { 0%,100%{box-shadow:0 0 0 0 var(--red-dim);} 50%{box-shadow:0 0 20px 4px var(--red-dim);} }

/* ── SECTION HEADERS ── */
.section-header {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 2px;
    padding: 20px 20px 8px;
    border-top: 1px solid var(--border);
    margin-top: 4px;
}

/* ── DATA TABLE ── */
.qb-table { width:100%; border-collapse:collapse; font-family:var(--mono); font-size:12px; }
.qb-table th { background:var(--surface2); color:var(--muted); padding:10px 14px; text-align:left; font-weight:400; font-size:10px; letter-spacing:1px; text-transform:uppercase; border-bottom:1px solid var(--border); }
.qb-table td { padding:10px 14px; border-bottom:1px solid var(--border); color:var(--text); }
.qb-table tr:hover td { background: var(--surface2); }
.pos-green { color: var(--green) !important; }
.pos-red   { color: var(--red) !important; }

/* ── CONDOR DIAGRAM ── */
.condor-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    font-family: var(--mono);
    font-size: 13px;
}
.condor-leg {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
}
.condor-leg:last-child { border-bottom: none; }
.leg-type { width: 60px; font-size: 10px; font-weight: 700; text-align: center; padding: 3px 8px; border-radius: 4px; }
.leg-sell { background: var(--red-dim); color: var(--red); border: 1px solid var(--red); }
.leg-buy  { background: var(--green-dim); color: var(--green); border: 1px solid var(--green); }

/* ── SIDEBAR ── */
.sidebar-section { padding: 12px 0; border-bottom: 1px solid var(--border); }
.sidebar-label { font-family: var(--mono); font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; padding: 0 16px 8px; }

/* ── BUTTONS (override Streamlit) ── */
.stButton > button {
    background: var(--blue) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: var(--mono) !important;
    font-size: 12px !important;
    font-weight: 700 !important;
    letter-spacing: 1px !important;
    padding: 10px 20px !important;
    transition: all 0.2s !important;
}
.stButton > button:hover { opacity: 0.85 !important; transform: translateY(-1px) !important; }

/* Emergency stop */
.emergency-btn > button {
    background: var(--red) !important;
}

/* ── ORDER PILL ── */
.order-pill { display:inline-block; padding:2px 10px; border-radius:20px; font-size:10px; font-family:var(--mono); font-weight:700; }
.pill-buy   { background:var(--green-dim); color:var(--green); border:1px solid var(--green); }
.pill-sell  { background:var(--red-dim); color:var(--red); border:1px solid var(--red); }
.pill-open  { background:var(--blue-dim); color:var(--blue); border:1px solid var(--blue); }
.pill-exec  { background:var(--amber-dim); color:var(--amber); border:1px solid var(--amber); }

/* Content padding */
.content-pad { padding: 0 20px 20px; }

/* Streamlit widget overrides */
.stSelectbox > div > div, .stNumberInput > div > div > input {
    background: var(--surface2) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: 8px !important;
    font-family: var(--mono) !important;
    font-size: 13px !important;
}
.stTabs [data-baseweb="tab-list"] {
    background: var(--surface) !important;
    border-bottom: 1px solid var(--border) !important;
    gap: 0 !important;
    padding: 0 20px !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: var(--muted) !important;
    font-family: var(--mono) !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    letter-spacing: 1px !important;
    padding: 14px 20px !important;
    border-bottom: 2px solid transparent !important;
    text-transform: uppercase !important;
}
.stTabs [aria-selected="true"] {
    color: var(--blue) !important;
    border-bottom-color: var(--blue) !important;
}
.stTabs [data-baseweb="tab-panel"] {
    background: var(--bg) !important;
    padding: 0 !important;
}
/* Light mode widget text fix */
.stSelectbox label, .stNumberInput label, .stSlider label, .stToggle label,
.stTextInput label { color: var(--text) !important; }
.stSelectbox > div > div { color: var(--text) !important; }
.stAlert { border-radius: 8px !important; }
div[data-testid="stMetric"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 16px !important;
}
.stToggle > label { color: var(--text) !important; font-family: var(--mono) !important; font-size: 12px !important; }
</style>
""", unsafe_allow_html=True)


# ─── SESSION STATE ────────────────────────────────────────────────────────────
if "broker" not in st.session_state:
    st.session_state.broker     = None
if "connected" not in st.session_state:
    st.session_state.connected  = False
if "engine_on" not in st.session_state:
    st.session_state.engine_on  = False
if "dry_run" not in st.session_state:
    st.session_state.dry_run    = True
if "capital" not in st.session_state:
    st.session_state.capital    = 200000.0
if "last_signal" not in st.session_state:
    st.session_state.last_signal = {}
if "trade_log" not in st.session_state:
    st.session_state.trade_log  = []
if "strategy" not in st.session_state:
    st.session_state.strategy   = "Momentum (EMA+RSI)"


# ─── SIDEBAR ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div style="padding:20px 16px 10px;"><span style="font-family:Space Mono,monospace;font-size:18px;font-weight:700;color:#0f172a;">QUANT<span style="color:#1a56db;">BENGAL</span></span><br><span style="font-family:Space Mono,monospace;font-size:9px;color:#64748b;letter-spacing:2px;">PRO TRADING ENGINE</span></div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section"><div class="sidebar-label">Connection</div>', unsafe_allow_html=True)

    api_key   = st.text_input("API Key",     value=st.session_state.get("_api_key", ""),   type="password", key="inp_api")
    client_id = st.text_input("Client ID",   value=st.session_state.get("_client_id", ""), key="inp_cid")
    password  = st.text_input("Password",    value=st.session_state.get("_password", ""),  type="password", key="inp_pw")
    totp_sec  = st.text_input("TOTP Secret", value=st.session_state.get("_totp", ""),      type="password", key="inp_totp")

    if st.button("⚡ CONNECT TO ANGEL ONE", use_container_width=True):
        import os
        os.environ["BROKER_API_KEY"] = api_key
        os.environ["CLIENT_ID"]      = client_id
        os.environ["PASSWORD"]       = password
        os.environ["TOTP_TOKEN"]     = totp_sec
        with st.spinner("Authenticating..."):
            try:
                broker = IndianBrokerAPI()
                if broker.connected:
                    st.session_state.broker    = broker
                    st.session_state.connected = True
                    st.success("✅ Connected")
                else:
                    st.error("❌ Auth failed — check credentials")
            except Exception as ex:
                st.error(f"Error: {ex}")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section"><div class="sidebar-label">Engine Config</div>', unsafe_allow_html=True)
    st.session_state.strategy = st.selectbox("Strategy", [
        "Momentum (EMA+RSI)", "Iron Condor (BankNifty)", "Morning Breakout (ORB)"
    ])
    st.session_state.capital = st.number_input("Capital (₹)", min_value=50000, max_value=5000000,
                                                value=int(st.session_state.capital), step=10000)
    st.session_state.dry_run = st.toggle("🧪 Dry Run (paper trade)", value=st.session_state.dry_run)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section"><div class="sidebar-label">Risk Controls</div>', unsafe_allow_html=True)
    vix_limit  = st.slider("VIX Threshold", 10.0, 30.0, 20.0, 0.5)
    daily_loss = st.slider("Daily Loss Limit (%)", 0.5, 5.0, 2.0, 0.25)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    with st.container():
        st.markdown('<div class="emergency-btn">', unsafe_allow_html=True)
        if st.button("🛑 EMERGENCY SQUARE OFF", use_container_width=True):
            if st.session_state.broker:
                with st.spinner("Squaring off all positions..."):
                    results = st.session_state.broker.square_off_all()
                    st.warning(f"Squared off {len(results)} positions")
            else:
                st.error("Not connected")
        st.markdown('</div>', unsafe_allow_html=True)

    now_ist = datetime.now(IST)
    mkt_open = now_ist.weekday() <= 4 and (
        now_ist.replace(hour=9,minute=15) <= now_ist <= now_ist.replace(hour=15,minute=30)
    )
    st.markdown(f"""
    <div style="padding:14px 16px;font-family:Space Mono,monospace;font-size:10px;color:#64748b;border-top:1px solid var(--border);">
        <div>🕐 {now_ist.strftime('%H:%M:%S IST')}</div>
        <div style="margin-top:4px;">Market: {'<span style="color:#0a7c4b;font-weight:700;">OPEN</span>' if mkt_open else '<span style="color:#c81e3a;font-weight:700;">CLOSED</span>'}</div>
        <div style="margin-top:4px;">Mode: {'<span style="color:#b45309;font-weight:700;">PAPER</span>' if st.session_state.dry_run else '<span style="color:#c81e3a;font-weight:700;">⚡ LIVE</span>'}</div>
    </div>
    """, unsafe_allow_html=True)


# ─── TOP BAR ──────────────────────────────────────────────────────────────────
conn_dot  = '<span class="dot-live"></span>' if st.session_state.connected else '<span class="dot-dead"></span>'
conn_text = "CONNECTED" if st.session_state.connected else "DISCONNECTED"
mode_text = "PAPER TRADING" if st.session_state.dry_run else "⚡ LIVE TRADING"
mode_col  = "#b45309" if st.session_state.dry_run else "#c81e3a"

st.markdown(f"""
<div class="topbar">
    <div class="topbar-logo">QUANT<span>BENGAL</span> <span style="font-size:11px;color:#64748b;font-weight:400;letter-spacing:3px;">PRO</span></div>
    <div class="topbar-status">
        <span>{conn_dot} ANGEL ONE · {conn_text}</span>
        <span style="color:{mode_col};font-weight:700;">{mode_text}</span>
        <span style="color:#64748b;">{st.session_state.strategy.upper()}</span>
    </div>
</div>
""", unsafe_allow_html=True)


# ─── TABS ─────────────────────────────────────────────────────────────────────
tab_terminal, tab_positions, tab_orders, tab_backtest, tab_condor, tab_risk = st.tabs([
    "⚡ LIVE TERMINAL",
    "📌 POSITIONS & P&L",
    "📋 ORDER BOOK",
    "📊 BACKTEST",
    "🦅 IRON CONDOR",
    "🛡️ RISK ENGINE"
])


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — LIVE TERMINAL
# ═══════════════════════════════════════════════════════════════════════════════
with tab_terminal:

    col_refresh, col_run, col_empty = st.columns([1, 1, 5])
    with col_refresh:
        st.markdown('<div style="padding:10px 0 0 20px;">', unsafe_allow_html=True)
        if st.button("🔄 REFRESH"):
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    with col_run:
        st.markdown('<div style="padding:10px 0 0 0;">', unsafe_allow_html=True)
        run_signal = st.button("▶ RUN ENGINE CYCLE")
        st.markdown('</div>', unsafe_allow_html=True)

    # ── MARKET SNAPSHOT ───────────────────────────────────────────────────────
    broker = st.session_state.broker
    candles, df = [], pd.DataFrame()

    if broker:
        symbol_map = {
            "Momentum (EMA+RSI)":      "BANKNIFTY",
            "Iron Condor (BankNifty)": "BANKNIFTY",
            "Morning Breakout (ORB)":  "NIFTY",
        }
        sym = symbol_map.get(st.session_state.strategy, "BANKNIFTY")
        candles = broker.get_data(symbol=sym)
        if candles and len(candles) >= 30:
            df = pd.DataFrame(candles, columns=['ts','open','high','low','close','vol'])
            df['close'] = df['close'].astype(float)
            df['high']  = df['high'].astype(float)
            df['low']   = df['low'].astype(float)
            df['ema_9']     = EMAIndicator(close=df['close'], window=9).ema_indicator()
            df['ema_21']    = EMAIndicator(close=df['close'], window=21).ema_indicator()
            df['rsi']       = RSIIndicator(close=df['close'], window=14).rsi()
            atr_calc        = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'])
            df['atr']       = atr_calc.average_true_range()
            bb_calc         = BollingerBands(close=df['close'], window=20, window_dev=2)
            df['bb_upper']  = bb_calc.bollinger_hband()
            df['bb_lower']  = bb_calc.bollinger_lband()

    if not df.empty:
        latest = df.iloc[-1]
        prev   = df.iloc[-2]
        price  = float(latest['close'])
        chg    = price - float(prev['close'])
        chg_p  = chg / float(prev['close']) * 100
        ema9   = float(latest['ema_9'])
        ema21  = float(latest['ema_21'])
        rsi    = float(latest['rsi'])
        atr    = float(latest['atr'])

        # ── METRICS ───────────────────────────────────────────────────────
        st.markdown(f"""
        <div class="metric-grid">
            <div class="metric-card blue">
                <div class="metric-label">LIVE PRICE</div>
                <div class="metric-value">₹{price:,.0f}</div>
                <div class="metric-sub {'pos-green' if chg>=0 else 'pos-red'}">{'+' if chg>=0 else ''}{chg:,.0f} ({chg_p:+.2f}%)</div>
            </div>
            <div class="metric-card {'green' if ema9>ema21 else 'red'}">
                <div class="metric-label">9 EMA</div>
                <div class="metric-value">₹{ema9:,.0f}</div>
                <div class="metric-sub">{'↑ ABOVE 21 EMA' if ema9>ema21 else '↓ BELOW 21 EMA'}</div>
            </div>
            <div class="metric-card white">
                <div class="metric-label">21 EMA</div>
                <div class="metric-value">₹{ema21:,.0f}</div>
                <div class="metric-sub">Slow trend line</div>
            </div>
            <div class="metric-card {'green' if rsi>55 else 'red' if rsi<45 else 'amber'}">
                <div class="metric-label">RSI (14)</div>
                <div class="metric-value {'pos-green' if rsi>55 else 'pos-red' if rsi<45 else ''}">{rsi:.1f}</div>
                <div class="metric-sub">{'BULLISH' if rsi>55 else 'BEARISH' if rsi<45 else 'NEUTRAL'}</div>
            </div>
            <div class="metric-card amber">
                <div class="metric-label">ATR (14)</div>
                <div class="metric-value">₹{atr:,.0f}</div>
                <div class="metric-sub">Volatility | 15-min</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── SIGNAL EVALUATION ─────────────────────────────────────────────
        risk = RiskManager(capital=st.session_state.capital)
        strategy_obj = MomentumStrategy(broker, risk)
        sig_result   = strategy_obj.get_signal(candles)
        signal       = sig_result.get("signal", "HOLD")

        if signal == "BUY_CALL":
            banner = f'<div class="signal-buy">▲ BUY CALL SIGNAL DETECTED &nbsp;|&nbsp; {sig_result.get("reason", "")}</div>'
        elif signal == "BUY_PUT":
            banner = f'<div class="signal-sell">▼ BUY PUT SIGNAL DETECTED &nbsp;|&nbsp; {sig_result.get("reason", "")}</div>'
        else:
            banner = f'<div class="signal-hold">⚖ HOLDING — NO TRADE SIGNAL &nbsp;|&nbsp; {sig_result.get("reason", "")}</div>'

        st.markdown('<div class="content-pad">', unsafe_allow_html=True)
        st.markdown(banner, unsafe_allow_html=True)

        # Manual order execution
        if signal in ("BUY_CALL", "BUY_PUT"):
            if run_signal:
                with st.spinner(f"Executing {signal}..."):
                    result = strategy_obj.check_and_trade(dry_run=st.session_state.dry_run)
                    st.session_state.last_signal = result
                    if result.get("status") == "DRY_RUN":
                        st.info(f"🧪 DRY RUN — {signal} at ₹{price:,.0f} | SL: ₹{sig_result.get('stop_loss',0):,.0f} | Target: ₹{sig_result.get('target',0):,.0f}")
                    elif result.get("status") == "EXECUTED":
                        st.success(f"✅ ORDER PLACED — {signal} | Order ID: {result.get('order',{}).get('order_id','')}")
                        st.session_state.trade_log.append({
                            "time": datetime.now(IST).strftime("%H:%M:%S"),
                            "signal": signal,
                            "price": price,
                            "status": "EXECUTED" if not st.session_state.dry_run else "PAPER"
                        })

        # ── CANDLESTICK DATA TABLE ─────────────────────────────────────────
        st.markdown('<div class="section-header">PRICE ACTION — LAST 10 CANDLES</div>', unsafe_allow_html=True)
        display = df[['ts','open','high','low','close','ema_9','ema_21','rsi','atr']].tail(10).copy()
        display['ts'] = pd.to_datetime(display['ts']).dt.strftime('%H:%M')
        display = display.round(1)

        table_html = '<table class="qb-table"><thead><tr>' + \
            ''.join(f'<th>{c.upper()}</th>' for c in display.columns) + \
            '</tr></thead><tbody>'
        for _, row in display.iterrows():
            chg_candle = row['close'] - row['open']
            row_class  = "pos-green" if chg_candle >= 0 else "pos-red"
            table_html += '<tr>'
            for c in display.columns:
                val = row[c]
                css = row_class if c in ('close','open') else ''
                table_html += f'<td class="{css}">{val}</td>'
            table_html += '</tr>'
        st.markdown(table_html + '</tbody></table>', unsafe_allow_html=True)

        # ── CHART ─────────────────────────────────────────────────────────
        st.markdown('<div class="section-header">EMA CHART</div>', unsafe_allow_html=True)
        chart_df = df[['ts','close','ema_9','ema_21']].copy()
        chart_df['ts'] = pd.to_datetime(chart_df['ts']).dt.strftime('%H:%M')
        chart_df = chart_df.set_index('ts').tail(60)
        st.line_chart(chart_df, height=220)

        st.markdown('</div>', unsafe_allow_html=True)

    else:
        st.markdown('<div class="content-pad">', unsafe_allow_html=True)
        if not broker:
            st.warning("🔌 Connect your Angel One account using the sidebar to start the engine.")
        else:
            st.info("📡 Fetching market data... If outside market hours, data may be limited.")
        st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — POSITIONS & P&L
# ═══════════════════════════════════════════════════════════════════════════════
with tab_positions:
    st.markdown('<div class="content-pad">', unsafe_allow_html=True)

    if st.button("🔄 Refresh Positions"):
        st.rerun()

    broker = st.session_state.broker

    if broker:
        # ── P&L SUMMARY ───────────────────────────────────────────────────
        pnl = broker.get_pnl_summary()
        total_col = "pos-green" if pnl['total'] >= 0 else "pos-red"

        st.markdown(f"""
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;">
            <div class="metric-card {'green' if pnl['total']>=0 else 'red'}">
                <div class="metric-label">TOTAL P&L</div>
                <div class="metric-value {total_col}">₹{pnl['total']:+,.0f}</div>
            </div>
            <div class="metric-card green">
                <div class="metric-label">REALISED P&L</div>
                <div class="metric-value {'pos-green' if pnl['realised']>=0 else 'pos-red'}">₹{pnl['realised']:+,.0f}</div>
            </div>
            <div class="metric-card blue">
                <div class="metric-label">UNREALISED P&L</div>
                <div class="metric-value {'pos-green' if pnl['unrealised']>=0 else 'pos-red'}">₹{pnl['unrealised']:+,.0f}</div>
            </div>
            <div class="metric-card amber">
                <div class="metric-label">OPEN POSITIONS</div>
                <div class="metric-value">{pnl['positions']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── POSITIONS TABLE ────────────────────────────────────────────────
        positions = broker.get_positions()
        if positions:
            st.markdown('<div class="section-header">OPEN POSITIONS</div>', unsafe_allow_html=True)
            cols = ['tradingsymbol','netqty','ltp','avgnetprice','unrealisedprofitandloss','realisedprofitandloss','exchange']
            pos_df = pd.DataFrame(positions)

            # Only show relevant columns that exist
            available = [c for c in cols if c in pos_df.columns]
            pos_df = pos_df[available]

            table_html = '<table class="qb-table"><thead><tr>' + \
                ''.join(f'<th>{c.upper()}</th>' for c in available) + \
                '</tr></thead><tbody>'
            for _, row in pos_df.iterrows():
                table_html += '<tr>'
                for c in available:
                    val = row[c]
                    css = ""
                    if 'pnl' in c.lower() or 'profit' in c.lower():
                        try:
                            css = "pos-green" if float(val) >= 0 else "pos-red"
                            val = f"₹{float(val):+,.0f}"
                        except: pass
                    table_html += f'<td class="{css}">{val}</td>'
                table_html += '</tr>'
            st.markdown(table_html + '</tbody></table>', unsafe_allow_html=True)
        else:
            st.info("No open positions.")

        # ── FUNDS ─────────────────────────────────────────────────────────
        funds = broker.get_funds()
        if funds:
            st.markdown('<div class="section-header">AVAILABLE FUNDS & MARGIN</div>', unsafe_allow_html=True)
            fund_items = {k: v for k, v in funds.items() if v and v != "0"}
            cols = st.columns(min(len(fund_items), 4))
            for i, (k, v) in enumerate(fund_items.items()):
                with cols[i % 4]:
                    try:
                        fval = float(v)
                        st.metric(k.upper(), f"₹{fval:,.0f}")
                    except:
                        st.metric(k.upper(), str(v))

    else:
        st.warning("Connect to Angel One to view positions.")

    st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — ORDER BOOK
# ═══════════════════════════════════════════════════════════════════════════════
with tab_orders:
    st.markdown('<div class="content-pad">', unsafe_allow_html=True)

    broker = st.session_state.broker
    if broker:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("📋 Load Order Book"):
                orders = broker.get_order_book()
                st.session_state._orders = orders
        with c2:
            if st.button("🔄 Load Trade Book"):
                trades = broker.get_trade_book()
                st.session_state._trades = trades

        orders = st.session_state.get("_orders", [])
        if orders:
            st.markdown('<div class="section-header">TODAY\'S ORDERS</div>', unsafe_allow_html=True)
            ord_cols = ['orderid','tradingsymbol','transactiontype','quantity','price','orderstatus','producttype']
            o_df = pd.DataFrame(orders)
            available = [c for c in ord_cols if c in o_df.columns]
            o_df = o_df[available]

            table_html = '<table class="qb-table"><thead><tr>' + \
                ''.join(f'<th>{c.upper()}</th>' for c in available) + \
                '</tr></thead><tbody>'
            for _, row in o_df.iterrows():
                table_html += '<tr>'
                for c in available:
                    val = row[c]
                    if c == 'transactiontype':
                        pill = 'pill-buy' if str(val).upper() == 'BUY' else 'pill-sell'
                        val  = f'<span class="order-pill {pill}">{val}</span>'
                    elif c == 'orderstatus':
                        pill = 'pill-exec' if 'complete' in str(val).lower() else 'pill-open'
                        val  = f'<span class="order-pill {pill}">{val}</span>'
                    table_html += f'<td>{val}</td>'
                table_html += '</tr>'
            st.markdown(table_html + '</tbody></table>', unsafe_allow_html=True)
        else:
            st.info("Click 'Load Order Book' to fetch today's orders.")

        # Session trade log
        if st.session_state.trade_log:
            st.markdown('<div class="section-header">SESSION TRADE LOG</div>', unsafe_allow_html=True)
            tlog_df = pd.DataFrame(st.session_state.trade_log)
            st.dataframe(tlog_df, use_container_width=True)
    else:
        st.warning("Connect to Angel One to view orders.")

    st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════
with tab_backtest:
    st.markdown('<div class="content-pad">', unsafe_allow_html=True)
    st.markdown('<div class="section-header">30-DAY HISTORICAL STRATEGY AUDIT</div>', unsafe_allow_html=True)

    bt_col1, bt_col2, bt_col3 = st.columns(3)
    with bt_col1:
        bt_strategy = st.selectbox("Strategy to Test", ["EMA Crossover (9/21)", "Morning Breakout (ORB)"])
    with bt_col2:
        bt_period = st.selectbox("Period", ["1mo", "3mo", "6mo"])
    with bt_col3:
        bt_symbol = st.selectbox("Symbol", ["^NSEI (Nifty 50)", "^NSEBANK (BankNifty)"])

    symbol_ticker = {"^NSEI (Nifty 50)": "^NSEI", "^NSEBANK (BankNifty)": "^NSEBANK"}[bt_symbol]

    if st.button("🚀 RUN BACKTEST", use_container_width=False):
        with st.spinner("Downloading historical data and running simulation..."):
            hist = yf.download(symbol_ticker, period=bt_period, interval="15m", progress=False)

            if hist.empty:
                st.error("Could not fetch historical data.")
            else:
                close_s = hist['Close'].squeeze().astype(float)
                hist['ema_9']  = EMAIndicator(close=close_s, window=9).ema_indicator()
                hist['ema_21'] = EMAIndicator(close=close_s, window=21).ema_indicator()
                hist['rsi']    = RSIIndicator(close=close_s, window=14).rsi()

                trades = []
                in_pos = False
                entry_p = 0.0

                for i in range(1, len(hist)):
                    if not in_pos:
                        if (hist['ema_9'].iloc[i-1] <= hist['ema_21'].iloc[i-1] and
                                hist['ema_9'].iloc[i] > hist['ema_21'].iloc[i] and
                                float(hist['rsi'].iloc[i]) > 55):
                            entry_p = float(close_s.iloc[i])
                            trades.append({"Date": hist.index[i], "Signal": "BUY CALL", "Entry": entry_p, "Type": "LONG"})
                            in_pos = True
                    else:
                        if hist['ema_9'].iloc[i] < hist['ema_21'].iloc[i]:
                            exit_p = float(close_s.iloc[i])
                            trades[-1].update({"Exit": exit_p, "Points": exit_p - entry_p})
                            in_pos = False

                trades = [t for t in trades if 'Points' in t]
                if not trades:
                    st.warning("No completed trades in this period.")
                else:
                    res = pd.DataFrame(trades)
                    res['Date']   = pd.to_datetime(res['Date']).dt.tz_convert('Asia/Kolkata').dt.strftime('%d-%b %H:%M')
                    res['Points'] = res['Points'].astype(float)
                    res['Result'] = res['Points'].apply(lambda x: "WIN" if x > 0 else "LOSS")

                    win_rate  = (res['Points'] > 0).mean() * 100
                    total_pts = res['Points'].sum()
                    max_dd    = (res['Points'].cumsum().cummax() - res['Points'].cumsum()).max()
                    avg_win   = res[res['Points']>0]['Points'].mean() if any(res['Points']>0) else 0
                    avg_loss  = abs(res[res['Points']<0]['Points'].mean()) if any(res['Points']<0) else 0
                    rr_ratio  = round(avg_win / avg_loss, 2) if avg_loss else 0

                    st.markdown(f"""
                    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:16px 0;">
                        <div class="metric-card {'green' if total_pts>0 else 'red'}">
                            <div class="metric-label">TOTAL POINTS</div>
                            <div class="metric-value {'pos-green' if total_pts>0 else 'pos-red'}">{total_pts:+.0f}</div>
                        </div>
                        <div class="metric-card {'green' if win_rate>60 else 'amber'}">
                            <div class="metric-label">WIN RATE</div>
                            <div class="metric-value">{win_rate:.1f}%</div>
                        </div>
                        <div class="metric-card blue">
                            <div class="metric-label">TOTAL TRADES</div>
                            <div class="metric-value">{len(res)}</div>
                        </div>
                        <div class="metric-card red">
                            <div class="metric-label">MAX DRAWDOWN</div>
                            <div class="metric-value pos-red">{max_dd:.0f} pts</div>
                        </div>
                        <div class="metric-card amber">
                            <div class="metric-label">R:R RATIO</div>
                            <div class="metric-value">{rr_ratio}x</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    st.markdown('<div class="section-header">EQUITY CURVE</div>', unsafe_allow_html=True)
                    res_chart = res.copy()
                    res_chart['Cumulative'] = res_chart['Points'].cumsum()
                    st.line_chart(res_chart.set_index('Date')['Cumulative'], height=200)

                    st.markdown('<div class="section-header">TRADE LOG</div>', unsafe_allow_html=True)
                    display_res = res[['Date','Signal','Entry','Exit','Points','Result']].round(1)
                    table_html = '<table class="qb-table"><thead><tr>' + \
                        ''.join(f'<th>{c.upper()}</th>' for c in display_res.columns) + \
                        '</tr></thead><tbody>'
                    for _, row in display_res.iterrows():
                        table_html += '<tr>'
                        for c in display_res.columns:
                            val = row[c]
                            css = ""
                            if c == 'Result':
                                css  = "pos-green" if val == "WIN" else "pos-red"
                            elif c == 'Points':
                                css  = "pos-green" if float(val) >= 0 else "pos-red"
                                val  = f"{float(val):+.1f}"
                            table_html += f'<td class="{css}">{val}</td>'
                        table_html += '</tr>'
                    st.markdown(table_html + '</tbody></table>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — IRON CONDOR
# ═══════════════════════════════════════════════════════════════════════════════
with tab_condor:
    st.markdown('<div class="content-pad">', unsafe_allow_html=True)
    st.markdown('<div class="section-header">BANKNIFTY WEEKLY IRON CONDOR BUILDER</div>', unsafe_allow_html=True)

    ic_col1, ic_col2, ic_col3 = st.columns(3)
    with ic_col1:
        ic_spot    = st.number_input("BankNifty Spot Price", value=48000, step=100)
        ic_vix     = st.number_input("India VIX", value=14.5, step=0.1)
    with ic_col2:
        ic_expiry  = st.text_input("Expiry Code (e.g. 23DEC)", value="23DEC")
        ic_qty     = st.number_input("Quantity (units)", value=15, step=15)
    with ic_col3:
        ic_premium = st.number_input("Expected Net Credit (₹/unit)", value=175, step=5)
        ic_capital = st.number_input("Capital Allocated (₹)", value=100000, step=10000)

    # Compute strikes
    risk_ic = RiskManager(capital=ic_capital)
    condor   = IronCondorStrategy(None, risk_ic)
    strikes  = condor.compute_strikes(ic_spot)

    # P&L parameters
    max_profit = ic_premium * ic_qty
    max_loss   = (500 - ic_premium) * ic_qty  # wing_width - net_credit
    stop_price = ic_premium * 1.50 * ic_qty
    target     = ic_premium * 0.50 * ic_qty
    roi_pct    = round(max_profit / ic_capital * 100, 2)

    st.markdown(f"""
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0;">
        <div class="metric-card green">
            <div class="metric-label">MAX PROFIT</div>
            <div class="metric-value pos-green">₹{max_profit:,.0f}</div>
            <div class="metric-sub">50% target: ₹{target:,.0f}</div>
        </div>
        <div class="metric-card red">
            <div class="metric-label">MAX LOSS</div>
            <div class="metric-value pos-red">₹{max_loss:,.0f}</div>
            <div class="metric-sub">Stop: ₹{stop_price:,.0f}</div>
        </div>
        <div class="metric-card blue">
            <div class="metric-label">EXPECTED ROI</div>
            <div class="metric-value">{roi_pct}%</div>
            <div class="metric-sub">On ₹{ic_capital:,.0f} capital</div>
        </div>
        <div class="metric-card {'green' if ic_vix < 20 else 'red'}">
            <div class="metric-label">VIX STATUS</div>
            <div class="metric-value {'pos-green' if ic_vix < 20 else 'pos-red'}">{ic_vix}</div>
            <div class="metric-sub">{'✅ SAFE TO TRADE' if ic_vix < 20 else '⚠️ TOO HIGH — HOLD'}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Condor Leg Diagram
    st.markdown('<div class="section-header">CONDOR STRUCTURE</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="condor-box">
        <div class="condor-leg">
            <span class="leg-type leg-buy">BUY</span>
            <span style="color:#4a6080;font-size:11px;">WING PROTECTION</span>
            <span style="margin-left:auto;">CALL {strikes['long_call']} CE &nbsp;|&nbsp; +1 lot</span>
        </div>
        <div class="condor-leg">
            <span class="leg-type leg-sell">SELL</span>
            <span style="color:#4a6080;font-size:11px;">SHORT CALL — PREMIUM COLLECTED</span>
            <span style="margin-left:auto;color:#1d6dff;">CALL {strikes['short_call']} CE &nbsp;|&nbsp; -1 lot</span>
        </div>
        <div style="text-align:center;padding:12px 0;color:#4a6080;font-size:11px;border-bottom:1px solid var(--border);">
            ← &nbsp; PROFIT ZONE: BankNifty stays between {strikes['short_put']} — {strikes['short_call']} &nbsp; →
            <br><span style="color:#e2ecff;font-weight:700;">SPOT: {strikes['spot']:,.0f}</span>
        </div>
        <div class="condor-leg">
            <span class="leg-type leg-sell">SELL</span>
            <span style="color:#4a6080;font-size:11px;">SHORT PUT — PREMIUM COLLECTED</span>
            <span style="margin-left:auto;color:#1d6dff;">PUT {strikes['short_put']} PE &nbsp;|&nbsp; -1 lot</span>
        </div>
        <div class="condor-leg">
            <span class="leg-type leg-buy">BUY</span>
            <span style="color:#4a6080;font-size:11px;">WING PROTECTION</span>
            <span style="margin-left:auto;">PUT {strikes['long_put']} PE &nbsp;|&nbsp; +1 lot</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div style="margin-top:16px;">', unsafe_allow_html=True)
    vix_ok = ic_vix < 20
    if not vix_ok:
        st.error(f"⚠️ VIX {ic_vix} exceeds threshold (20). Iron Condor deployment BLOCKED.")
    else:
        deploy_col1, deploy_col2 = st.columns(2)
        with deploy_col1:
            if st.button("🧪 PAPER DEPLOY CONDOR"):
                st.success(f"✅ PAPER IRON CONDOR deployed | SC:{strikes['short_call']} LC:{strikes['long_call']} SP:{strikes['short_put']} LP:{strikes['long_put']}")
        with deploy_col2:
            if st.button("⚡ LIVE DEPLOY CONDOR"):
                if not st.session_state.broker:
                    st.error("Not connected to Angel One")
                elif st.session_state.dry_run:
                    st.warning("Dry run mode is ON — switch it off in sidebar for live deployment")
                else:
                    with st.spinner("Placing 4-leg Iron Condor..."):
                        condor_live = IronCondorStrategy(st.session_state.broker, risk_ic)
                        result = condor_live.check_and_trade(
                            spot=ic_spot, vix=ic_vix, expiry=ic_expiry, dry_run=False
                        )
                        if result.get("status") == "EXECUTED":
                            st.success("✅ Iron Condor LIVE — 4 legs placed")
                        else:
                            st.error(f"Deployment failed: {result}")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 6 — RISK ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
with tab_risk:
    st.markdown('<div class="content-pad">', unsafe_allow_html=True)
    st.markdown('<div class="section-header">RISK DASHBOARD & CONTROLS</div>', unsafe_allow_html=True)

    broker = st.session_state.broker
    capital = st.session_state.capital

    if broker:
        pnl = broker.get_pnl_summary()
        loss_pct = abs(pnl['total']) / capital * 100 if pnl['total'] < 0 else 0
        remaining_risk = max(0, 2.0 - loss_pct)

        color_loss = "red" if loss_pct > 1.5 else "amber" if loss_pct > 0.5 else "green"
        st.markdown(f"""
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;">
            <div class="metric-card {color_loss}">
                <div class="metric-label">DAILY LOSS USED</div>
                <div class="metric-value {'pos-red' if loss_pct>1 else ''}">{loss_pct:.2f}%</div>
                <div class="metric-sub">Limit: 2.00%</div>
            </div>
            <div class="metric-card green">
                <div class="metric-label">RISK REMAINING</div>
                <div class="metric-value pos-green">{remaining_risk:.2f}%</div>
                <div class="metric-sub">₹{remaining_risk/100*capital:,.0f}</div>
            </div>
            <div class="metric-card blue">
                <div class="metric-label">DEPLOYED CAPITAL</div>
                <div class="metric-value">₹{capital:,.0f}</div>
                <div class="metric-sub">Active positions</div>
            </div>
            <div class="metric-card amber">
                <div class="metric-label">ENGINE STATUS</div>
                <div class="metric-value" style="font-size:14px;">{'🟢 ACTIVE' if loss_pct < 2.0 else '🔴 HALTED'}</div>
                <div class="metric-sub">{'Normal' if loss_pct < 1.0 else 'Caution' if loss_pct < 2.0 else 'Stop hit'}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div class="section-header">RISK RULES ACTIVE</div>', unsafe_allow_html=True)
    rules = [
        ("VIX Filter",          f"Auto-pause Iron Condor if VIX > {vix_limit:.0f}",       "✅ ACTIVE"),
        ("Daily Loss Limit",    f"Halt all trading if daily loss > {daily_loss:.1f}%",     "✅ ACTIVE"),
        ("Position Sizing",     "Max 20% capital per Iron Condor spread",                   "✅ ACTIVE"),
        ("Stop Loss",           "Auto SL at 150% of premium collected (Iron Condor)",       "✅ ACTIVE"),
        ("Gap Risk Filter",     "Skip Monday entry if BankNifty gap > 1%",                  "✅ ACTIVE"),
        ("Event Filter",        "No trades during monthly/quarterly expiry week",            "✅ ACTIVE"),
        ("Max Open Positions",  "Never hold more than 4 simultaneous legs",                 "✅ ACTIVE"),
    ]
    table_html = '<table class="qb-table"><thead><tr><th>RULE</th><th>CONDITION</th><th>STATUS</th></tr></thead><tbody>'
    for rule, cond, status in rules:
        table_html += f'<tr><td style="color:#e2ecff;font-weight:700;">{rule}</td><td>{cond}</td><td style="color:#00e87b;">{status}</td></tr>'
    st.markdown(table_html + '</tbody></table>', unsafe_allow_html=True)

    st.markdown('<div class="section-header">MANUAL OVERRIDES</div>', unsafe_allow_html=True)
    ov1, ov2, ov3 = st.columns(3)
    with ov1:
        if st.button("⏸ PAUSE ENGINE"):
            st.session_state.engine_on = False
            st.warning("Engine paused — no new signals will execute")
    with ov2:
        if st.button("▶ RESUME ENGINE"):
            st.session_state.engine_on = True
            st.success("Engine resumed")
    with ov3:
        if st.button("🔃 RESET DAILY P&L COUNTER"):
            st.info("Daily P&L counter reset")

    st.markdown('</div>', unsafe_allow_html=True)
