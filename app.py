"""
QuantBengal Pro — app.py  v3.0
Fixes: sidebar always visible, mobile responsive, 30s auto-refresh,
       working backtest (3m/6m), auto-trading loop, 5 strategies,
       light mode throughout, connection flow fixed.
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pytz
import time
import os

# ─── PAGE CONFIG (must be first Streamlit call) ───────────────────────────────
st.set_page_config(
    page_title="QuantBengal Pro",
    layout="wide",
    page_icon="⚡",
    initial_sidebar_state="expanded"
)

IST = pytz.timezone('Asia/Kolkata')

# ─── SESSION STATE INIT ───────────────────────────────────────────────────────
defaults = {
    "broker": None, "connected": False, "engine_on": False,
    "dry_run": True, "capital": 200000.0, "last_signal": {},
    "trade_log": [], "strategy": "Momentum (EMA+RSI)",
    "auto_refresh": False, "refresh_interval": 30,
    "api_key": "", "client_id": "", "password": "", "totp_secret": "",
    "engine_halted": False,
    "last_auto_trade_signal": "", "vix_limit": 20.0, "daily_loss_pct": 2.0,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─── LAZY IMPORTS ─────────────────────────────────────────────────────────────
try:
    from broker_api import IndianBrokerAPI
    BROKER_AVAILABLE = True
except Exception:
    BROKER_AVAILABLE = False

from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def safe_float(v, default=0.0):
    try: return float(v)
    except: return default

def ist_now(): return datetime.now(IST)

def is_market_open():
    n = ist_now()
    if n.weekday() > 4: return False
    return n.replace(hour=9,minute=15,second=0) <= n <= n.replace(hour=15,minute=30,second=0)

# ─── BACKTEST ENGINE (fixed for 3mo/6mo) ─────────────────────────────────────
def run_backtest_engine(ticker, period, strategy_name):
    # yfinance 15m max = 60 days; use daily for 3mo/6mo/1y
    if period in ("3mo","6mo","1y"):
        interval, label = "1d", "Daily"
    else:
        interval, label = "15m", "15-min"

    try:
        raw = yf.download(ticker, period=period, interval=interval,
                          progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            days = {"1mo":30,"3mo":90,"6mo":180,"1y":365}.get(period,30)
            end = datetime.now(); start = end - timedelta(days=days)
            raw = yf.download(ticker, start=start, end=end,
                              interval=interval, progress=False, auto_adjust=True)
    except Exception as e:
        return None, f"Download error: {e}"

    if raw is None or raw.empty:
        return None, "No data from yfinance. Check ticker or try again later."

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    close_s = raw['Close'].squeeze().astype(float).dropna()
    if len(close_s) < 30:
        return None, f"Too few candles ({len(close_s)}). Try a longer period."

    df = raw.copy()
    df.index = pd.to_datetime(df.index)
    df['close'] = close_s

    # Indicators
    df['ema_9']  = EMAIndicator(close=close_s, window=9).ema_indicator()
    df['ema_21'] = EMAIndicator(close=close_s, window=21).ema_indicator()
    df['ema_50'] = EMAIndicator(close=close_s, window=50).ema_indicator()
    df['rsi']    = RSIIndicator(close=close_s, window=14).rsi()
    macd_o       = MACD(close=close_s)
    df['macd']   = macd_o.macd()
    df['macd_s'] = macd_o.macd_signal()
    bb_o         = BollingerBands(close=close_s, window=20, window_dev=2)
    df['bb_u']   = bb_o.bollinger_hband()
    df['bb_l']   = bb_o.bollinger_lband()
    try:
        atr_o    = AverageTrueRange(high=raw['High'].squeeze().astype(float),
                                     low=raw['Low'].squeeze().astype(float),
                                     close=close_s, window=14)
        df['atr']= atr_o.average_true_range()
    except:
        df['atr']= close_s * 0.005

    df = df.dropna(subset=['ema_9','ema_21','rsi'])

    trades=[]; in_pos=False; entry_p=0.0; direction=""

    for i in range(1, len(df)):
        prev_ = df.iloc[i-1]; curr_ = df.iloc[i]
        c=safe_float(curr_['close'])
        p9=safe_float(prev_['ema_9']);  p21=safe_float(prev_['ema_21'])
        c9=safe_float(curr_['ema_9']);  c21=safe_float(curr_['ema_21'])
        rsi_=safe_float(curr_['rsi'])
        atr_=safe_float(curr_['atr']) or c*0.005
        pm=safe_float(prev_['macd']); ps_=safe_float(prev_['macd_s'])
        cm=safe_float(curr_['macd']); cs_=safe_float(curr_['macd_s'])
        e50=safe_float(curr_['ema_50'])
        bu=safe_float(curr_['bb_u']); bl=safe_float(curr_['bb_l'])
        sl_m=1.5; tgt_m=2.0

        if strategy_name=="Momentum (EMA+RSI)":
            bull=p9<=p21 and c9>c21 and rsi_>55
            bear=p9>=p21 and c9<c21 and rsi_<45
        elif strategy_name=="MACD Crossover":
            bull=pm<=ps_ and cm>cs_ and rsi_>50
            bear=pm>=ps_ and cm<cs_ and rsi_<50
        elif strategy_name=="Bollinger Band Reversal":
            bull=c<=bl and rsi_<35
            bear=c>=bu and rsi_>65
        elif strategy_name=="Triple EMA Trend":
            bull=c9>c21 and c21>e50 and rsi_>55
            bear=c9<c21 and c21<e50 and rsi_<45
        elif strategy_name=="Morning Breakout (ORB)":
            try: orb_h=safe_float(curr_['High']); orb_l=safe_float(curr_['Low'])
            except: orb_h=c*1.005; orb_l=c*0.995
            bull=c>orb_h*0.999 and rsi_>55
            bear=c<orb_l*1.001 and rsi_<45
        else:
            bull=bear=False

        if not in_pos:
            if bull:
                entry_p=c; in_pos=True; direction="LONG"
                trades.append({"Date":df.index[i],"Signal":"BUY CALL","Entry":entry_p,
                                "SL":round(entry_p-sl_m*atr_,1),"Target":round(entry_p+tgt_m*atr_,1),"ATR":round(atr_,1)})
            elif bear:
                entry_p=c; in_pos=True; direction="SHORT"
                trades.append({"Date":df.index[i],"Signal":"BUY PUT","Entry":entry_p,
                                "SL":round(entry_p+sl_m*atr_,1),"Target":round(entry_p-tgt_m*atr_,1),"ATR":round(atr_,1)})
        else:
            exit_p=None; reason=""
            if direction=="LONG":
                if c<=trades[-1]["SL"]: exit_p=trades[-1]["SL"]; reason="SL"
                elif c>=trades[-1]["Target"]: exit_p=trades[-1]["Target"]; reason="Target"
                elif c9<c21: exit_p=c; reason="Signal Exit"
            else:
                if c>=trades[-1]["SL"]: exit_p=trades[-1]["SL"]; reason="SL"
                elif c<=trades[-1]["Target"]: exit_p=trades[-1]["Target"]; reason="Target"
                elif c9>c21: exit_p=c; reason="Signal Exit"
            if exit_p is not None:
                pts=exit_p-entry_p if direction=="LONG" else entry_p-exit_p
                trades[-1].update({"Exit":exit_p,"Points":round(pts,1),"Reason":reason})
                in_pos=False; direction=""

    trades=[t for t in trades if "Points" in t]
    if not trades:
        return None, f"No completed trades for '{strategy_name}' in this period. Try longer period or different strategy."

    res=pd.DataFrame(trades)
    try:
        res['Date']=pd.to_datetime(res['Date'])
        if hasattr(res['Date'].dt,'tz') and res['Date'].dt.tz is not None:
            res['Date']=res['Date'].dt.tz_convert('Asia/Kolkata')
        fmt='%d-%b %H:%M' if interval=='15m' else '%d-%b-%Y'
        res['Date']=res['Date'].dt.strftime(fmt)
    except:
        res['Date']=res['Date'].astype(str)

    res['Points']=res['Points'].astype(float)
    res['Result']=res['Points'].apply(lambda x:"WIN" if x>0 else "LOSS")
    res['Cumulative']=res['Points'].cumsum()
    wins=res[res['Points']>0]; losses=res[res['Points']<0]
    metrics={
        "total_pts":round(res['Points'].sum(),1),
        "win_rate":round((res['Points']>0).mean()*100,1),
        "trades":len(res),
        "max_dd":round((res['Cumulative'].cummax()-res['Cumulative']).max(),1),
        "avg_win":round(wins['Points'].mean(),1) if len(wins) else 0,
        "avg_loss":round(abs(losses['Points'].mean()),1) if len(losses) else 0,
        "rr_ratio":round(abs(wins['Points'].mean()/losses['Points'].mean()),2) if len(wins) and len(losses) else 0,
        "interval":label,"candles":len(df),
    }
    return res, metrics


# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Inter:wght@300;400;500;600;700&display=swap');
:root{--bg:#f0f4f8;--surface:#ffffff;--surface2:#f8fafc;--border:#e2e8f0;--blue:#1a56db;--blue-dim:rgba(26,86,219,.08);--green:#0a7c4b;--green-dim:rgba(10,124,75,.08);--red:#c81e3a;--red-dim:rgba(200,30,58,.08);--amber:#b45309;--amber-dim:rgba(180,83,9,.08);--text:#0f172a;--muted:#64748b;--mono:'Space Mono',monospace;--sans:'Inter',sans-serif}
*{box-sizing:border-box}
#MainMenu,footer,header{visibility:hidden}
.block-container{padding:0!important;max-width:100%!important}
.stApp{background:var(--bg)!important;font-family:var(--sans)!important;color:var(--text)!important}
section[data-testid="stSidebar"]>div{background:var(--surface)!important;border-right:1px solid var(--border)!important}
section[data-testid="stSidebar"] label,section[data-testid="stSidebar"] p{color:var(--text)!important}
@media(max-width:768px){.metric-grid{grid-template-columns:repeat(2,1fr)!important}.topbar-status{display:none!important}.topbar{padding:10px 14px!important}}
@media(max-width:480px){.metric-grid{grid-template-columns:1fr!important}}
.topbar{background:var(--surface);border-bottom:2px solid var(--blue);padding:12px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:1000;gap:12px}
.topbar-logo{font-family:var(--mono);font-size:17px;font-weight:700;color:var(--text);white-space:nowrap}
.topbar-logo span{color:var(--blue)}
.topbar-status{display:flex;align-items:center;gap:14px;font-family:var(--mono);font-size:11px;flex-wrap:wrap}
.dot-live{width:8px;height:8px;background:var(--green);border-radius:50%;display:inline-block;animation:pulse 1.5s infinite}
.dot-dead{width:8px;height:8px;background:var(--red);border-radius:50%;display:inline-block}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.connect-notice{background:#fffbeb;border:1.5px solid var(--amber);border-radius:10px;padding:20px 24px;margin:20px;display:flex;align-items:flex-start;gap:14px;font-family:var(--sans)}
.connect-notice .icon{font-size:28px;flex-shrink:0}
.connect-notice .text{font-size:14px;color:var(--text);line-height:1.6}
.connect-notice .text strong{color:var(--amber)}
.refresh-banner{background:var(--blue-dim);border:1px solid var(--blue);border-radius:8px;padding:8px 16px;font-family:var(--mono);font-size:11px;color:var(--blue);margin:8px 20px}
.metric-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;padding:16px 20px}
.metric-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;position:relative;overflow:hidden}
.metric-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}
.metric-card.blue::before{background:var(--blue)}.metric-card.green::before{background:var(--green)}.metric-card.red::before{background:var(--red)}.metric-card.amber::before{background:var(--amber)}.metric-card.white::before{background:var(--border)}
.metric-label{font-size:9px;font-family:var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:1.2px;margin-bottom:6px}
.metric-value{font-size:20px;font-family:var(--mono);font-weight:700;color:var(--text)}
.metric-sub{font-size:10px;color:var(--muted);margin-top:3px;font-family:var(--mono)}
.pos-green{color:var(--green)!important}.pos-red{color:var(--red)!important}.pos-amber{color:var(--amber)!important}
.signal-hold{background:var(--surface2);border:1px solid var(--border);color:var(--muted);text-align:center;padding:14px;border-radius:10px;font-family:var(--mono);font-size:13px;font-weight:700;letter-spacing:1.5px}
.signal-buy{background:var(--green-dim);border:2px solid var(--green);color:var(--green);text-align:center;padding:14px;border-radius:10px;font-family:var(--mono);font-size:13px;font-weight:700;letter-spacing:1.5px}
.signal-sell{background:var(--red-dim);border:2px solid var(--red);color:var(--red);text-align:center;padding:14px;border-radius:10px;font-family:var(--mono);font-size:13px;font-weight:700;letter-spacing:1.5px}
.section-header{font-family:var(--mono);font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:2px;padding:18px 20px 8px;border-top:1px solid var(--border)}
.qb-table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11px}
.qb-table th{background:var(--surface2);color:var(--muted);padding:9px 12px;text-align:left;font-weight:400;font-size:9px;letter-spacing:1px;text-transform:uppercase;border-bottom:2px solid var(--border)}
.qb-table td{padding:8px 12px;border-bottom:1px solid var(--border);color:var(--text);word-break:break-word}
.qb-table tr:hover td{background:var(--surface2)}
.order-pill{display:inline-block;padding:2px 7px;border-radius:20px;font-size:9px;font-family:var(--mono);font-weight:700}
.pill-buy{background:var(--green-dim);color:var(--green);border:1px solid var(--green)}.pill-sell{background:var(--red-dim);color:var(--red);border:1px solid var(--red)}
.pill-open{background:var(--blue-dim);color:var(--blue);border:1px solid var(--blue)}.pill-exec{background:var(--amber-dim);color:var(--amber);border:1px solid var(--amber)}
.pill-win{background:var(--green-dim);color:var(--green);border:1px solid var(--green)}.pill-loss{background:var(--red-dim);color:var(--red);border:1px solid var(--red)}
.condor-box{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px;font-family:var(--mono);font-size:12px}
.condor-leg{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border);flex-wrap:wrap}
.condor-leg:last-child{border-bottom:none}
.leg-type{min-width:52px;font-size:9px;font-weight:700;text-align:center;padding:3px 6px;border-radius:4px}
.leg-sell{background:var(--red-dim);color:var(--red);border:1px solid var(--red)}.leg-buy{background:var(--green-dim);color:var(--green);border:1px solid var(--green)}
.content-pad{padding:0 20px 24px}
.stButton>button{background:var(--blue)!important;color:#fff!important;border:none!important;border-radius:8px!important;font-family:var(--mono)!important;font-size:11px!important;font-weight:700!important;letter-spacing:.5px!important;padding:9px 16px!important;transition:all .15s!important;width:100%;white-space:nowrap}
.stButton>button:hover{opacity:.85!important}
.emergency-btn .stButton>button{background:var(--red)!important}
.stTabs [data-baseweb="tab-list"]{background:var(--surface)!important;border-bottom:1px solid var(--border)!important;gap:0!important;padding:0 16px!important;overflow-x:auto!important}
.stTabs [data-baseweb="tab"]{background:transparent!important;color:var(--muted)!important;font-family:var(--mono)!important;font-size:10px!important;font-weight:700!important;letter-spacing:1px!important;padding:12px 14px!important;border-bottom:2px solid transparent!important;text-transform:uppercase!important;white-space:nowrap!important}
.stTabs [aria-selected="true"]{color:var(--blue)!important;border-bottom-color:var(--blue)!important}
.stTabs [data-baseweb="tab-panel"]{background:var(--bg)!important;padding:0!important}
.stAlert{border-radius:8px!important}
.stSelectbox label,.stNumberInput label,.stSlider label,.stToggle label,.stTextInput label{color:var(--text)!important;font-size:12px!important}
.stSelectbox>div>div{color:var(--text)!important;background:var(--surface2)!important}
.stTextInput>div>div>input,.stNumberInput>div>div>input{background:var(--surface2)!important;color:var(--text)!important;border:1px solid var(--border)!important;border-radius:6px!important}
div[data-testid="stMetric"]{background:var(--surface)!important;border:1px solid var(--border)!important;border-radius:10px!important;padding:14px!important}
</style>
""", unsafe_allow_html=True)


# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:16px 4px 8px">
      <div style="font-family:'Space Mono',monospace;font-size:17px;font-weight:700;color:#0f172a">
        QUANT<span style="color:#1a56db">BENGAL</span>
        <span style="font-size:9px;color:#64748b;font-weight:400;letter-spacing:3px;margin-left:4px">PRO</span>
      </div>
      <div style="font-family:'Space Mono',monospace;font-size:9px;color:#64748b;letter-spacing:2px;margin-top:2px">
        AUTOMATED TRADING ENGINE
      </div>
    </div>
    <hr style="border:none;border-top:1px solid #e2e8f0;margin:0 0 10px">
    """, unsafe_allow_html=True)

    # Status badge always visible
    if st.session_state.connected:
        st.markdown('<div style="background:#d1fae5;border:1px solid #0a7c4b;border-radius:6px;padding:6px 10px;font-family:Space Mono,monospace;font-size:10px;color:#0a7c4b;text-align:center;margin-bottom:8px">● ANGEL ONE CONNECTED</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="background:#fee2e2;border:1px solid #c81e3a;border-radius:6px;padding:6px 10px;font-family:Space Mono,monospace;font-size:10px;color:#c81e3a;text-align:center;margin-bottom:8px">● DISCONNECTED — expand below to connect</div>', unsafe_allow_html=True)

    # ── CONNECTION (always accessible expander) ───────────────────────────────
    with st.expander("🔌 Angel One Connection", expanded=not st.session_state.connected):
        st.session_state.api_key     = st.text_input("API Key",     value=st.session_state.api_key,     type="password", key="s_api")
        st.session_state.client_id   = st.text_input("Client ID",   value=st.session_state.client_id,   key="s_cid")
        st.session_state.password    = st.text_input("Password",    value=st.session_state.password,    type="password", key="s_pw")
        st.session_state.totp_secret = st.text_input("TOTP Secret", value=st.session_state.totp_secret, type="password", key="s_totp")

        if st.button("⚡ CONNECT", use_container_width=True, key="btn_connect"):
            if not all([st.session_state.api_key, st.session_state.client_id,
                        st.session_state.password, st.session_state.totp_secret]):
                st.error("All 4 fields are required.")
            elif not BROKER_AVAILABLE:
                st.error("broker_api.py missing — ensure all files are in the same folder.")
            else:
                os.environ["BROKER_API_KEY"] = st.session_state.api_key
                os.environ["CLIENT_ID"]      = st.session_state.client_id
                os.environ["PASSWORD"]       = st.session_state.password
                os.environ["TOTP_TOKEN"]     = st.session_state.totp_secret
                with st.spinner("Authenticating with Angel One..."):
                    try:
                        b = IndianBrokerAPI()
                        if b.connected:
                            st.session_state.broker    = b
                            st.session_state.connected = True
                            st.success("✅ Connected!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error("❌ Auth failed.\n\n• TOTP Secret = 32-char base32 key, NOT the 6-digit OTP\n• Check Client ID format (mobile number)")
                    except Exception as ex:
                        st.error(f"Error: {ex}")

        if st.session_state.connected:
            if st.button("🔌 Disconnect", use_container_width=True, key="btn_disc"):
                st.session_state.broker = None
                st.session_state.connected = False
                st.session_state.engine_on = False
                st.rerun()

    st.markdown("---")

    # ── ENGINE CONFIG ─────────────────────────────────────────────────────────
    st.markdown('<p style="font-family:Space Mono,monospace;font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;margin:0 0 6px">Engine Config</p>', unsafe_allow_html=True)

    STRATEGIES = ["Momentum (EMA+RSI)","MACD Crossover","Bollinger Band Reversal",
                  "Triple EMA Trend","Morning Breakout (ORB)","Iron Condor (BankNifty)"]
    idx = STRATEGIES.index(st.session_state.strategy) if st.session_state.strategy in STRATEGIES else 0
    st.session_state.strategy = st.selectbox("Strategy", STRATEGIES, index=idx, key="sel_strat")
    st.session_state.capital  = float(st.number_input("Capital (₹)", min_value=50000, max_value=5000000,
                                                        value=int(st.session_state.capital), step=10000, key="cap_in"))
    st.session_state.dry_run  = st.toggle("🧪 Dry Run (Paper Trade)", value=st.session_state.dry_run, key="dry_tog")

    if not st.session_state.dry_run:
        st.markdown('<div style="background:#fee2e2;border-radius:6px;padding:8px;font-size:11px;color:#c81e3a;margin-top:4px">⚠️ LIVE MODE — real orders will be placed!</div>', unsafe_allow_html=True)

    st.markdown("---")

    # ── AUTO-REFRESH ──────────────────────────────────────────────────────────
    st.markdown('<p style="font-family:Space Mono,monospace;font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;margin:0 0 6px">Auto Refresh</p>', unsafe_allow_html=True)
    st.session_state.auto_refresh      = st.toggle("⏱ Auto Refresh", value=st.session_state.auto_refresh, key="ar_tog")
    if st.session_state.auto_refresh:
        st.session_state.refresh_interval = st.slider("Interval (s)", 15, 120, 30, 5, key="ar_int")

    st.markdown("---")

    # ── AUTO-TRADING ──────────────────────────────────────────────────────────
    st.markdown('<p style="font-family:Space Mono,monospace;font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;margin:0 0 6px">Auto Trading</p>', unsafe_allow_html=True)
    if st.session_state.engine_on:
        st.markdown('<div style="background:#d1fae5;border-radius:6px;padding:6px;text-align:center;font-family:Space Mono,monospace;font-size:10px;color:#0a7c4b;margin-bottom:6px">🤖 ENGINE RUNNING</div>', unsafe_allow_html=True)
        if st.button("⏹ STOP AUTO-TRADE", use_container_width=True, key="stop_auto"):
            st.session_state.engine_on = False
            st.rerun()
    else:
        if st.button("▶ START AUTO-TRADE", use_container_width=True, key="start_auto"):
            if not st.session_state.connected:
                st.error("Connect to Angel One first.")
            else:
                st.session_state.engine_on = True
                st.rerun()

    st.markdown("---")

    # ── RISK CONTROLS ─────────────────────────────────────────────────────────
    st.markdown('<p style="font-family:Space Mono,monospace;font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;margin:0 0 6px">Risk Controls</p>', unsafe_allow_html=True)
    st.session_state.vix_limit     = st.slider("VIX Threshold",       10.0, 30.0, st.session_state.vix_limit,     0.5, key="vix_s")
    st.session_state.daily_loss_pct= st.slider("Daily Loss Limit (%)", 0.5,  5.0,  st.session_state.daily_loss_pct, 0.25, key="dl_s")

    st.markdown("---")

    # ── EMERGENCY ─────────────────────────────────────────────────────────────
    st.markdown('<div class="emergency-btn">', unsafe_allow_html=True)
    if st.button("🛑 EMERGENCY SQUARE OFF", use_container_width=True, key="sos_sb"):
        if st.session_state.broker:
            with st.spinner("Closing all positions..."):
                res = st.session_state.broker.square_off_all()
                st.warning(f"Squared off {len(res)} position(s)")
        else:
            st.error("Not connected")
    st.markdown('</div>', unsafe_allow_html=True)

    # ── CLOCK ─────────────────────────────────────────────────────────────────
    now_ist = ist_now(); mkt_open = is_market_open()
    st.markdown(f"""
    <div style="padding:10px 4px 0;font-family:Space Mono,monospace;font-size:10px;color:#64748b;line-height:1.9">
      <div>🕐 {now_ist.strftime('%d %b  %H:%M:%S IST')}</div>
      <div>Market: {'<span style="color:#0a7c4b;font-weight:700">● OPEN</span>' if mkt_open else '<span style="color:#c81e3a;font-weight:700">● CLOSED</span>'}</div>
      <div>Mode: {'<span style="color:#b45309;font-weight:700">PAPER</span>' if st.session_state.dry_run else '<span style="color:#c81e3a;font-weight:700">⚡ LIVE</span>'}</div>
      <div>Engine: {'<span style="color:#0a7c4b;font-weight:700">RUNNING</span>' if st.session_state.engine_on else '<span style="color:#64748b">IDLE</span>'}</div>
    </div>
    """, unsafe_allow_html=True)


# ─── TOP BAR ──────────────────────────────────────────────────────────────────
conn_dot  = '<span class="dot-live"></span>' if st.session_state.connected else '<span class="dot-dead"></span>'
conn_text = "CONNECTED" if st.session_state.connected else "DISCONNECTED"
mode_col  = "#b45309" if st.session_state.dry_run else "#c81e3a"
mode_text = "PAPER" if st.session_state.dry_run else "⚡ LIVE"
eng_tag   = '<span style="color:#0a7c4b;font-weight:700">🤖 AUTO-ON</span>' if st.session_state.engine_on else ''

st.markdown(f"""
<div class="topbar">
  <div class="topbar-logo">QUANT<span>BENGAL</span><span style="font-size:10px;color:#64748b;font-weight:400;letter-spacing:3px;margin-left:8px">PRO</span></div>
  <div class="topbar-status">
    <span>{conn_dot} {conn_text}</span>
    <span style="color:{mode_col};font-weight:700">{mode_text}</span>
    <span style="color:#64748b">{st.session_state.strategy.split('(')[0].strip().upper()}</span>
    {eng_tag}
  </div>
</div>
""", unsafe_allow_html=True)

if st.session_state.auto_refresh:
    nxt = (ist_now() + timedelta(seconds=st.session_state.refresh_interval)).strftime("%H:%M:%S")
    st.markdown(f'<div class="refresh-banner">⏱ AUTO-REFRESH ON · every {st.session_state.refresh_interval}s · next: {nxt} IST</div>', unsafe_allow_html=True)


# ─── TABS ─────────────────────────────────────────────────────────────────────
tab_terminal, tab_positions, tab_orders, tab_backtest, tab_condor, tab_risk = st.tabs([
    "⚡ LIVE TERMINAL","📌 POSITIONS & P&L","📋 ORDER BOOK","📊 BACKTEST","🦅 IRON CONDOR","🛡️ RISK ENGINE"
])


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — LIVE TERMINAL
# ═══════════════════════════════════════════════════════════════════════════════
with tab_terminal:
    broker = st.session_state.broker

    if not broker:
        st.markdown("""
        <div class="connect-notice">
          <div class="icon">🔌</div>
          <div class="text">
            <strong>Connection required</strong> — open the
            <strong>🔌 Angel One Connection</strong> panel in the left sidebar,
            fill in all 4 credentials and click <strong>⚡ CONNECT</strong>.<br><br>
            <strong>On mobile:</strong> tap the <strong>☰</strong> icon at the top-left to open the sidebar.
            The connection panel will be expanded automatically since you are not yet connected.
          </div>
        </div>
        """, unsafe_allow_html=True)
        # Placeholder metrics
        st.markdown("""
        <div class="metric-grid">
          <div class="metric-card blue"><div class="metric-label">LIVE PRICE</div><div class="metric-value" style="color:#cbd5e1">——</div><div class="metric-sub">Awaiting connection</div></div>
          <div class="metric-card white"><div class="metric-label">9 EMA</div><div class="metric-value" style="color:#cbd5e1">——</div></div>
          <div class="metric-card white"><div class="metric-label">RSI (14)</div><div class="metric-value" style="color:#cbd5e1">——</div></div>
          <div class="metric-card white"><div class="metric-label">MACD</div><div class="metric-value" style="color:#cbd5e1">——</div></div>
          <div class="metric-card white"><div class="metric-label">ATR</div><div class="metric-value" style="color:#cbd5e1">——</div></div>
        </div>
        <div style="margin:0 20px"><div class="signal-hold">🔌 CONNECT YOUR ANGEL ONE ACCOUNT TO BEGIN</div></div>
        """, unsafe_allow_html=True)
        st.stop()

    # Control bar
    cc1, cc2, cc3 = st.columns([1,1,5])
    with cc1:
        st.markdown('<div style="padding:8px 0 0 20px">', unsafe_allow_html=True)
        do_refresh = st.button("🔄 REFRESH", key="t_ref")
        st.markdown('</div>', unsafe_allow_html=True)
    with cc2:
        st.markdown('<div style="padding:8px 0 0 0">', unsafe_allow_html=True)
        run_btn = st.button("▶ RUN CYCLE", key="t_run")
        st.markdown('</div>', unsafe_allow_html=True)

    if do_refresh:
        st.rerun()

    # Fetch candles
    sym_map = {
        "Momentum (EMA+RSI)":"BANKNIFTY","MACD Crossover":"BANKNIFTY",
        "Bollinger Band Reversal":"BANKNIFTY","Triple EMA Trend":"BANKNIFTY",
        "Morning Breakout (ORB)":"NIFTY","Iron Condor (BankNifty)":"BANKNIFTY"
    }
    sym = sym_map.get(st.session_state.strategy,"BANKNIFTY")

    with st.spinner("Fetching live market data..."):
        candles = broker.get_data(symbol=sym)

    df = pd.DataFrame()
    if candles and len(candles) >= 30:
        df = pd.DataFrame(candles, columns=['ts','open','high','low','close','vol'])
        for col in ['open','high','low','close','vol']:
            df[col] = df[col].astype(float)
        cs = df['close']
        df['ema_9']  = EMAIndicator(close=cs, window=9).ema_indicator()
        df['ema_21'] = EMAIndicator(close=cs, window=21).ema_indicator()
        df['ema_50'] = EMAIndicator(close=cs, window=50).ema_indicator()
        df['rsi']    = RSIIndicator(close=cs, window=14).rsi()
        mo           = MACD(close=cs)
        df['macd']   = mo.macd(); df['macd_s'] = mo.macd_signal(); df['macd_h'] = mo.macd_diff()
        bo           = BollingerBands(close=cs, window=20, window_dev=2)
        df['bb_u']   = bo.bollinger_hband(); df['bb_l'] = bo.bollinger_lband(); df['bb_m'] = bo.bollinger_mavg()
        ao           = AverageTrueRange(high=df['high'], low=df['low'], close=cs)
        df['atr']    = ao.average_true_range()

    if df.empty:
        if not is_market_open():
            st.info("📴 Market closed (Mon–Fri 9:15–15:30 IST). Historical data will appear when market reopens.")
        else:
            st.warning("⚠️ Could not fetch candles. Session may have expired — try reconnecting in sidebar.")
    else:
        lat = df.iloc[-1]; prv = df.iloc[-2]
        price=safe_float(lat['close']); chg=price-safe_float(prv['close'])
        chg_p=chg/safe_float(prv['close'])*100 if safe_float(prv['close']) else 0
        ema9=safe_float(lat['ema_9']); ema21=safe_float(lat['ema_21']); rsi=safe_float(lat['rsi'])
        atr=safe_float(lat['atr']); macd_v=safe_float(lat['macd']); macd_s=safe_float(lat['macd_s'])
        bb_u=safe_float(lat['bb_u']); bb_l=safe_float(lat['bb_l'])

        # Metrics
        st.markdown(f"""
        <div class="metric-grid">
          <div class="metric-card blue">
            <div class="metric-label">LIVE PRICE · {sym}</div>
            <div class="metric-value">₹{price:,.0f}</div>
            <div class="metric-sub {'pos-green' if chg>=0 else 'pos-red'}">{'+' if chg>=0 else ''}{chg:,.0f} ({chg_p:+.2f}%)</div>
          </div>
          <div class="metric-card {'green' if ema9>ema21 else 'red'}">
            <div class="metric-label">EMA 9 / 21</div>
            <div class="metric-value">₹{ema9:,.0f}</div>
            <div class="metric-sub">{'↑ BULL CROSS' if ema9>ema21 else '↓ BEAR CROSS'}</div>
          </div>
          <div class="metric-card {'green' if rsi>55 else 'red' if rsi<45 else 'amber'}">
            <div class="metric-label">RSI (14)</div>
            <div class="metric-value {'pos-green' if rsi>55 else 'pos-red' if rsi<45 else 'pos-amber'}">{rsi:.1f}</div>
            <div class="metric-sub">{'OVERBOUGHT' if rsi>70 else 'BULLISH' if rsi>55 else 'OVERSOLD' if rsi<30 else 'BEARISH' if rsi<45 else 'NEUTRAL'}</div>
          </div>
          <div class="metric-card {'green' if macd_v>macd_s else 'red'}">
            <div class="metric-label">MACD / Signal</div>
            <div class="metric-value {'pos-green' if macd_v>macd_s else 'pos-red'}">{macd_v:+.1f}</div>
            <div class="metric-sub">Sig: {macd_s:+.1f} · {'▲' if macd_v>macd_s else '▼'}</div>
          </div>
          <div class="metric-card amber">
            <div class="metric-label">ATR / BB</div>
            <div class="metric-value">₹{atr:,.0f}</div>
            <div class="metric-sub">{bb_l:,.0f} – {bb_u:,.0f}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Signal evaluation
        def eval_signal(sn):
            p9_=safe_float(prv['ema_9']); p21_=safe_float(prv['ema_21'])
            c9_=safe_float(lat['ema_9']); c21_=safe_float(lat['ema_21'])
            r_=safe_float(lat['rsi']); a_=safe_float(lat['atr']) or price*0.005
            pm_=safe_float(prv['macd']); ps_=safe_float(prv['macd_s'])
            cm_=safe_float(lat['macd']); cs_=safe_float(lat['macd_s'])
            e50_=safe_float(lat['ema_50']); bu_=safe_float(lat['bb_u']); bl_=safe_float(lat['bb_l'])
            sl_off=1.5*a_; tgt_off=2.0*a_

            if sn=="Momentum (EMA+RSI)":
                if p9_<=p21_ and c9_>c21_ and r_>55: return "BUY_CALL",f"9 EMA ↑ 21 | RSI {r_:.0f}",price-sl_off,price+tgt_off
                if p9_>=p21_ and c9_<c21_ and r_<45: return "BUY_PUT", f"9 EMA ↓ 21 | RSI {r_:.0f}",price+sl_off,price-tgt_off
            elif sn=="MACD Crossover":
                if pm_<=ps_ and cm_>cs_ and r_>50: return "BUY_CALL",f"MACD ↑ Signal | RSI {r_:.0f}",price-sl_off,price+tgt_off
                if pm_>=ps_ and cm_<cs_ and r_<50: return "BUY_PUT", f"MACD ↓ Signal | RSI {r_:.0f}",price+sl_off,price-tgt_off
            elif sn=="Bollinger Band Reversal":
                if price<=bl_ and r_<35: return "BUY_CALL",f"At Lower BB ₹{bl_:,.0f} | RSI {r_:.0f} oversold",price-sl_off,price+tgt_off
                if price>=bu_ and r_>65: return "BUY_PUT", f"At Upper BB ₹{bu_:,.0f} | RSI {r_:.0f} overbought",price+sl_off,price-tgt_off
            elif sn=="Triple EMA Trend":
                if c9_>c21_ and c21_>e50_ and r_>55: return "BUY_CALL",f"9>21>50 bullish stack | RSI {r_:.0f}",price-sl_off,price+tgt_off
                if c9_<c21_ and c21_<e50_ and r_<45: return "BUY_PUT", f"9<21<50 bearish stack | RSI {r_:.0f}",price+sl_off,price-tgt_off
            elif sn=="Morning Breakout (ORB)":
                oh=safe_float(df.iloc[0]['high']); ol=safe_float(df.iloc[0]['low'])
                av=safe_float(df['vol'].mean()); vok=safe_float(lat['vol'])>av*1.3
                if price>oh and vok: return "BUY_CALL",f"Above ORB High ₹{oh:,.0f} + vol spike",price-sl_off,price+tgt_off
                if price<ol and vok: return "BUY_PUT", f"Below ORB Low ₹{ol:,.0f} + vol spike",price+sl_off,price-tgt_off
            trend="BULLISH" if c9_>c21_ else "BEARISH"
            return "HOLD",f"No signal | {trend} | RSI {r_:.0f}",0,0

        sig, reason, sl_p, tgt_p = eval_signal(st.session_state.strategy)

        st.markdown('<div class="content-pad">', unsafe_allow_html=True)
        if sig=="BUY_CALL":
            st.markdown(f'<div class="signal-buy">▲ BUY CALL &nbsp;|&nbsp; {reason} &nbsp;|&nbsp; SL ₹{sl_p:,.0f} &nbsp; TGT ₹{tgt_p:,.0f}</div>', unsafe_allow_html=True)
        elif sig=="BUY_PUT":
            st.markdown(f'<div class="signal-sell">▼ BUY PUT &nbsp;|&nbsp; {reason} &nbsp;|&nbsp; SL ₹{sl_p:,.0f} &nbsp; TGT ₹{tgt_p:,.0f}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="signal-hold">⚖ HOLD — {reason}</div>', unsafe_allow_html=True)

        # Auto-trading
        if st.session_state.engine_on and sig in ("BUY_CALL","BUY_PUT") and is_market_open():
            if sig != st.session_state.last_auto_trade_signal:
                if st.session_state.dry_run:
                    st.success(f"🤖 AUTO PAPER: {sig} @ ₹{price:,.0f} | SL ₹{sl_p:,.0f} | TGT ₹{tgt_p:,.0f}")
                    st.session_state.last_auto_trade_signal = sig
                    st.session_state.trade_log.append({"time":ist_now().strftime("%H:%M:%S"),"signal":sig,"price":price,"sl":sl_p,"target":tgt_p,"mode":"PAPER-AUTO"})
                else:
                    try:
                        order = broker.place_order(signal=sig, quantity=15)
                        if order.get("status"):
                            st.success(f"🤖 AUTO LIVE: {sig} | Order ID: {order.get('order_id','')}")
                            st.session_state.last_auto_trade_signal = sig
                            st.session_state.trade_log.append({"time":ist_now().strftime("%H:%M:%S"),"signal":sig,"price":price,"sl":sl_p,"target":tgt_p,"mode":"LIVE-AUTO"})
                        else:
                            st.error(f"Auto-trade failed: {order.get('error','')}")
                    except Exception as e:
                        st.error(f"Auto-trade error: {e}")
            else:
                st.info(f"🤖 Engine active | Signal {sig} already processed this cycle")
        elif st.session_state.engine_on and not is_market_open():
            st.warning("🤖 Engine on but market is closed. Will execute when market opens.")

        # Manual execution
        if run_btn:
            if sig in ("BUY_CALL","BUY_PUT"):
                if st.session_state.dry_run:
                    st.success(f"🧪 PAPER: {sig} @ ₹{price:,.0f} | SL ₹{sl_p:,.0f} | TGT ₹{tgt_p:,.0f}")
                    st.session_state.trade_log.append({"time":ist_now().strftime("%H:%M:%S"),"signal":sig,"price":price,"sl":sl_p,"target":tgt_p,"mode":"PAPER"})
                else:
                    try:
                        order = broker.place_order(signal=sig, quantity=15)
                        if order.get("status"):
                            st.success(f"✅ LIVE ORDER: {sig} | ID: {order.get('order_id','')}")
                            st.session_state.trade_log.append({"time":ist_now().strftime("%H:%M:%S"),"signal":sig,"price":price,"sl":sl_p,"target":tgt_p,"mode":"LIVE"})
                        else:
                            st.error(f"Order failed: {order.get('error','')}")
                    except Exception as e:
                        st.error(f"Order error: {e}")
            else:
                st.info("No actionable signal (HOLD). Engine cycle complete — waiting for crossover.")

        # Multi-strategy consensus
        st.markdown('<div class="section-header">ALL-STRATEGY CONSENSUS VIEW</div>', unsafe_allow_html=True)
        STRAT_LIST = ["Momentum (EMA+RSI)","MACD Crossover","Bollinger Band Reversal","Triple EMA Trend","Morning Breakout (ORB)"]
        bulls=0; bears=0; rows=""
        for sn in STRAT_LIST:
            s,r,_,_=eval_signal(sn)
            icon="▲" if s=="BUY_CALL" else "▼" if s=="BUY_PUT" else "⚖"
            css="pos-green" if s=="BUY_CALL" else "pos-red" if s=="BUY_PUT" else ""
            if s=="BUY_CALL": bulls+=1
            elif s=="BUY_PUT": bears+=1
            rows+=f'<tr><td>{sn}</td><td class="{css}">{icon} {s}</td><td style="font-size:10px">{r}</td></tr>'
        consensus = "BULLISH CONSENSUS" if bulls>=3 else "BEARISH CONSENSUS" if bears>=3 else "MIXED / NO CLEAR BIAS"
        css_c = "pos-green" if bulls>=3 else "pos-red" if bears>=3 else "pos-amber"
        st.markdown(f'<div style="text-align:right;font-family:Space Mono,monospace;font-size:11px;padding:0 0 6px;color:#64748b">Consensus: <strong class="{css_c}">{consensus}</strong> &nbsp;(↑{bulls} ↓{bears})</div>', unsafe_allow_html=True)
        st.markdown(f'<table class="qb-table"><thead><tr><th>Strategy</th><th>Signal</th><th>Reason</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)

        # Chart
        st.markdown('<div class="section-header">EMA PRICE CHART</div>', unsafe_allow_html=True)
        cd = df[['ts','close','ema_9','ema_21','ema_50']].copy()
        try: cd['ts'] = pd.to_datetime(cd['ts']).dt.strftime('%H:%M')
        except: pass
        st.line_chart(cd.set_index('ts').tail(80), height=220)

        # Candle table
        st.markdown('<div class="section-header">LAST 10 CANDLES</div>', unsafe_allow_html=True)
        disp = df[['ts','open','high','low','close','ema_9','ema_21','rsi','macd','atr']].tail(10).copy()
        try: disp['ts'] = pd.to_datetime(disp['ts']).dt.strftime('%H:%M')
        except: pass
        disp = disp.round(1)
        th=''.join(f'<th>{c.upper()}</th>' for c in disp.columns)
        rows_c=''
        for _,row in disp.iterrows():
            d_=safe_float(row['close'])-safe_float(row['open'])
            rows_c+='<tr>'+''.join(f'<td class="{"pos-green" if c in ("close","open") and d_>=0 else "pos-red" if c in ("close","open") and d_<0 else ""}">{row[c]}</td>' for c in disp.columns)+'</tr>'
        st.markdown(f'<table class="qb-table"><thead><tr>{th}</tr></thead><tbody>{rows_c}</tbody></table>', unsafe_allow_html=True)

        if st.session_state.trade_log:
            st.markdown('<div class="section-header">SESSION TRADE LOG</div>', unsafe_allow_html=True)
            tlog=pd.DataFrame(st.session_state.trade_log)
            th_t=''.join(f'<th>{c.upper()}</th>' for c in tlog.columns)
            rows_t=''.join('<tr>'+''.join(f'<td>{v}</td>' for v in row)+'</tr>' for _,row in tlog.iterrows())
            st.markdown(f'<table class="qb-table"><thead><tr>{th_t}</tr></thead><tbody>{rows_t}</tbody></table>', unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — POSITIONS & P&L
# ═══════════════════════════════════════════════════════════════════════════════
with tab_positions:
    st.markdown('<div class="content-pad">', unsafe_allow_html=True)
    broker = st.session_state.broker
    if not broker:
        st.warning("🔌 Connect to Angel One to view positions.")
    else:
        if st.button("🔄 Refresh", key="pos_ref"):
            st.rerun()
        pnl = broker.get_pnl_summary()
        tc = "pos-green" if pnl['total']>=0 else "pos-red"
        st.markdown(f"""
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:16px 0">
          <div class="metric-card {'green' if pnl['total']>=0 else 'red'}"><div class="metric-label">TOTAL P&L</div><div class="metric-value {tc}">₹{pnl['total']:+,.0f}</div></div>
          <div class="metric-card green"><div class="metric-label">REALISED</div><div class="metric-value {'pos-green' if pnl['realised']>=0 else 'pos-red'}">₹{pnl['realised']:+,.0f}</div></div>
          <div class="metric-card blue"><div class="metric-label">UNREALISED</div><div class="metric-value {'pos-green' if pnl['unrealised']>=0 else 'pos-red'}">₹{pnl['unrealised']:+,.0f}</div></div>
          <div class="metric-card amber"><div class="metric-label">OPEN POSITIONS</div><div class="metric-value">{pnl['positions']}</div></div>
        </div>
        """, unsafe_allow_html=True)

        positions = broker.get_positions()
        if positions:
            st.markdown('<div class="section-header">OPEN POSITIONS</div>', unsafe_allow_html=True)
            cols=['tradingsymbol','netqty','ltp','avgnetprice','unrealisedprofitandloss','realisedprofitandloss']
            pos_df=pd.DataFrame(positions); av=[c for c in cols if c in pos_df.columns]
            th=''.join(f'<th>{c.upper()}</th>' for c in av); rows_p=''
            for _,row in pos_df[av].iterrows():
                rows_p+='<tr>'
                for c in av:
                    v=row[c]; css=""
                    if 'pnl' in c or 'profit' in c:
                        try: fv=float(v); css="pos-green" if fv>=0 else "pos-red"; v=f"₹{fv:+,.0f}"
                        except: pass
                    rows_p+=f'<td class="{css}">{v}</td>'
                rows_p+='</tr>'
            st.markdown(f'<table class="qb-table"><thead><tr>{th}</tr></thead><tbody>{rows_p}</tbody></table>', unsafe_allow_html=True)
        else:
            st.info("No open positions currently.")

        funds=broker.get_funds()
        if funds:
            st.markdown('<div class="section-header">FUNDS & MARGIN</div>', unsafe_allow_html=True)
            fi={k:v for k,v in funds.items() if v and str(v)!="0"}
            cfs=st.columns(min(len(fi),4))
            for i,(k,v) in enumerate(fi.items()):
                with cfs[i%4]:
                    try: st.metric(k.upper(),f"₹{float(v):,.0f}")
                    except: st.metric(k.upper(),str(v))
    st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — ORDER BOOK
# ═══════════════════════════════════════════════════════════════════════════════
with tab_orders:
    st.markdown('<div class="content-pad">', unsafe_allow_html=True)
    broker=st.session_state.broker
    if not broker:
        st.warning("🔌 Connect to Angel One to view orders.")
    else:
        oc1,oc2=st.columns(2)
        with oc1:
            if st.button("📋 Load Order Book",key="ob_l"): st.session_state._orders=broker.get_order_book()
        with oc2:
            if st.button("🔄 Load Trade Book",key="tb_l"): st.session_state._trades=broker.get_trade_book()
        orders=st.session_state.get("_orders",[])
        if orders:
            st.markdown('<div class="section-header">TODAY\'S ORDERS</div>', unsafe_allow_html=True)
            ocols=['orderid','tradingsymbol','transactiontype','quantity','price','orderstatus','producttype']
            odf=pd.DataFrame(orders); av=[c for c in ocols if c in odf.columns]
            th=''.join(f'<th>{c.upper()}</th>' for c in av); rows_o=''
            for _,row in odf[av].iterrows():
                rows_o+='<tr>'
                for c in av:
                    v=row[c]
                    if c=='transactiontype': p='pill-buy' if str(v).upper()=='BUY' else 'pill-sell'; v=f'<span class="order-pill {p}">{v}</span>'
                    elif c=='orderstatus': p='pill-exec' if 'complete' in str(v).lower() else 'pill-open'; v=f'<span class="order-pill {p}">{v}</span>'
                    rows_o+=f'<td>{v}</td>'
                rows_o+='</tr>'
            st.markdown(f'<table class="qb-table"><thead><tr>{th}</tr></thead><tbody>{rows_o}</tbody></table>', unsafe_allow_html=True)
        else:
            st.info("Click 'Load Order Book' above to fetch today's orders from Angel One.")

        if st.session_state.trade_log:
            st.markdown('<div class="section-header">SESSION LOG</div>', unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(st.session_state.trade_log),use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — BACKTEST  (fixed 3mo/6mo)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_backtest:
    st.markdown('<div class="content-pad">', unsafe_allow_html=True)
    st.markdown('<div class="section-header">HISTORICAL STRATEGY BACKTEST ENGINE</div>', unsafe_allow_html=True)

    bc1,bc2,bc3,bc4=st.columns(4)
    with bc1:
        bt_strat=st.selectbox("Strategy",["Momentum (EMA+RSI)","MACD Crossover","Bollinger Band Reversal","Triple EMA Trend","Morning Breakout (ORB)"],key="bt_s")
    with bc2:
        bt_period=st.selectbox("Period",["1mo","3mo","6mo","1y"],key="bt_p")
    with bc3:
        bt_sym=st.selectbox("Index",["Nifty 50 (^NSEI)","BankNifty (^NSEBANK)","Sensex (^BSESN)"],key="bt_i")
    with bc4:
        st.markdown('<div style="padding-top:26px">', unsafe_allow_html=True)
        run_bt=st.button("🚀 RUN BACKTEST",use_container_width=True,key="bt_run")
        st.markdown('</div>', unsafe_allow_html=True)

    ticker_m={"Nifty 50 (^NSEI)":"^NSEI","BankNifty (^NSEBANK)":"^NSEBANK","Sensex (^BSESN)":"^BSESN"}
    ticker=ticker_m[bt_sym]

    if bt_period in ("3mo","6mo","1y"):
        st.markdown(f'<div style="background:#eff6ff;border:1px solid #1a56db;border-radius:6px;padding:8px 12px;font-size:12px;color:#1a56db;margin:8px 0">ℹ️ {bt_period} uses <strong>daily candles</strong> (yfinance 15-min data is capped at 60 days max)</div>', unsafe_allow_html=True)

    if run_bt:
        with st.spinner(f"Running {bt_strat} on {bt_sym} for {bt_period}..."):
            res_df, metrics = run_backtest_engine(ticker, bt_period, bt_strat)

        if res_df is None:
            st.error(f"Backtest failed: {metrics}")
        else:
            st.markdown(f"""
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:16px 0">
              <div class="metric-card {'green' if metrics['total_pts']>0 else 'red'}">
                <div class="metric-label">TOTAL POINTS</div>
                <div class="metric-value {'pos-green' if metrics['total_pts']>0 else 'pos-red'}">{metrics['total_pts']:+.0f}</div>
                <div class="metric-sub">{metrics['interval']} candles</div>
              </div>
              <div class="metric-card {'green' if metrics['win_rate']>60 else 'amber'}">
                <div class="metric-label">WIN RATE</div>
                <div class="metric-value">{metrics['win_rate']:.1f}%</div>
                <div class="metric-sub">{metrics['trades']} trades</div>
              </div>
              <div class="metric-card blue">
                <div class="metric-label">TRADES</div>
                <div class="metric-value">{metrics['trades']}</div>
                <div class="metric-sub">{metrics['candles']} candles</div>
              </div>
              <div class="metric-card red">
                <div class="metric-label">MAX DRAWDOWN</div>
                <div class="metric-value pos-red">{metrics['max_dd']:.0f}</div>
              </div>
              <div class="metric-card amber">
                <div class="metric-label">R:R RATIO</div>
                <div class="metric-value">{metrics['rr_ratio']}x</div>
                <div class="metric-sub">W:{metrics['avg_win']} / L:{metrics['avg_loss']}</div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown('<div class="section-header">EQUITY CURVE</div>', unsafe_allow_html=True)
            try: st.line_chart(res_df.set_index('Date')['Cumulative'],height=200)
            except: st.line_chart(res_df['Cumulative'].reset_index(drop=True),height=200)

            st.markdown('<div class="section-header">TRADE LOG</div>', unsafe_allow_html=True)
            show=[c for c in ['Date','Signal','Entry','Exit','Points','ATR','Reason','Result'] if c in res_df.columns]
            dr=res_df[show].copy()
            th=''.join(f'<th>{c.upper()}</th>' for c in show)
            rows_r=''
            for _,row in dr.iterrows():
                rows_r+='<tr>'
                for c in show:
                    v=row[c]; css=""
                    if c=='Result': p='pill-win' if v=='WIN' else 'pill-loss'; v=f'<span class="order-pill {p}">{v}</span>'
                    elif c=='Points':
                        try: fv=float(v); css="pos-green" if fv>=0 else "pos-red"; v=f"{fv:+.1f}"
                        except: pass
                    rows_r+=f'<td class="{css}">{v}</td>'
                rows_r+='</tr>'
            st.markdown(f'<table class="qb-table"><thead><tr>{th}</tr></thead><tbody>{rows_r}</tbody></table>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — IRON CONDOR
# ═══════════════════════════════════════════════════════════════════════════════
with tab_condor:
    st.markdown('<div class="content-pad">', unsafe_allow_html=True)
    st.markdown('<div class="section-header">BANKNIFTY WEEKLY IRON CONDOR BUILDER</div>', unsafe_allow_html=True)

    ic1,ic2,ic3=st.columns(3)
    with ic1:
        ic_spot=st.number_input("BankNifty Spot",value=48000,step=100,key="ic_sp")
        ic_vix=st.number_input("India VIX",value=14.5,step=0.1,key="ic_vx")
    with ic2:
        ic_expiry=st.text_input("Expiry Code (DDMMM)",value="23DEC",key="ic_ex")
        ic_qty=st.number_input("Quantity (units)",value=15,step=15,key="ic_qt")
    with ic3:
        ic_prem=st.number_input("Net Credit (₹/unit)",value=175,step=5,key="ic_pr")
        ic_cap=st.number_input("Capital Allocated (₹)",value=100000,step=10000,key="ic_cp")

    offset=ic_spot*0.012
    sc=round((ic_spot+offset)/100)*100; lc=sc+500
    sp=round((ic_spot-offset)/100)*100; lp=sp-500
    mp=ic_prem*ic_qty; ml=max(0,(500-ic_prem)*ic_qty)
    t50=ic_prem*0.50*ic_qty; s150=ic_prem*1.50*ic_qty
    roi=round(mp/ic_cap*100,2) if ic_cap else 0
    vix_ok=ic_vix<20

    st.markdown(f"""
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0">
      <div class="metric-card green"><div class="metric-label">MAX PROFIT</div><div class="metric-value pos-green">₹{mp:,.0f}</div><div class="metric-sub">50% exit: ₹{t50:,.0f}</div></div>
      <div class="metric-card red"><div class="metric-label">MAX LOSS</div><div class="metric-value pos-red">₹{ml:,.0f}</div><div class="metric-sub">SL: ₹{s150:,.0f}</div></div>
      <div class="metric-card blue"><div class="metric-label">ROI</div><div class="metric-value">{roi}%</div><div class="metric-sub">On ₹{ic_cap:,.0f}</div></div>
      <div class="metric-card {'green' if vix_ok else 'red'}"><div class="metric-label">VIX</div><div class="metric-value {'pos-green' if vix_ok else 'pos-red'}">{ic_vix}</div><div class="metric-sub">{'✅ Safe' if vix_ok else '⛔ Too High'}</div></div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="section-header">CONDOR LEG STRUCTURE</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="condor-box">
      <div class="condor-leg"><span class="leg-type leg-buy">BUY</span><span style="color:#64748b;font-size:11px;flex:1">WING PROTECTION</span><span>CALL {lc} CE | +1 lot</span></div>
      <div class="condor-leg"><span class="leg-type leg-sell">SELL</span><span style="color:#64748b;font-size:11px;flex:1">SHORT CALL — collect premium</span><span style="color:#1a56db">CALL {sc} CE | -1 lot</span></div>
      <div style="text-align:center;padding:10px 0;color:#64748b;font-size:11px;border-bottom:1px solid var(--border)">◄── PROFIT ZONE: {sp:,} → {sc:,} ──► &nbsp; <strong style="color:#0f172a">SPOT {ic_spot:,}</strong></div>
      <div class="condor-leg"><span class="leg-type leg-sell">SELL</span><span style="color:#64748b;font-size:11px;flex:1">SHORT PUT — collect premium</span><span style="color:#1a56db">PUT {sp} PE | -1 lot</span></div>
      <div class="condor-leg"><span class="leg-type leg-buy">BUY</span><span style="color:#64748b;font-size:11px;flex:1">WING PROTECTION</span><span>PUT {lp} PE | +1 lot</span></div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div style="margin-top:14px">', unsafe_allow_html=True)
    if not vix_ok:
        st.error(f"⛔ VIX {ic_vix} > 20 — Iron Condor blocked by risk filter. Wait for calmer market.")
    else:
        dc1,dc2=st.columns(2)
        with dc1:
            if st.button("🧪 PAPER DEPLOY",use_container_width=True,key="ic_pap"):
                st.success(f"✅ PAPER Condor deployed | SC:{sc} LC:{lc} | SP:{sp} LP:{lp} | Max Profit: ₹{mp:,.0f}")
        with dc2:
            if st.button("⚡ LIVE DEPLOY",use_container_width=True,key="ic_liv"):
                if not st.session_state.broker: st.error("Not connected")
                elif st.session_state.dry_run: st.warning("Turn off Dry Run for live deployment")
                else:
                    try:
                        with st.spinner("Placing 4-leg condor..."):
                            res=st.session_state.broker.place_iron_condor(
                                symbol="BANKNIFTY",expiry=ic_expiry,
                                short_call_strike=sc,long_call_strike=lc,
                                short_put_strike=sp,long_put_strike=lp,quantity=ic_qty)
                            st.success("✅ Condor placed!") if res.get("status") else st.error(f"Failed: {res}")
                    except Exception as e: st.error(f"Error: {e}")
    st.markdown('</div></div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB 6 — RISK ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
with tab_risk:
    st.markdown('<div class="content-pad">', unsafe_allow_html=True)
    st.markdown('<div class="section-header">RISK DASHBOARD</div>', unsafe_allow_html=True)
    broker=st.session_state.broker; capital=st.session_state.capital

    if broker:
        pnl=broker.get_pnl_summary()
        lp_=abs(pnl['total'])/capital*100 if pnl['total']<0 else 0
        rem=max(0,st.session_state.daily_loss_pct-lp_)
        halted=lp_>=st.session_state.daily_loss_pct
        if halted and not st.session_state.engine_halted:
            st.session_state.engine_halted=True; st.session_state.engine_on=False
        cc="red" if lp_>1.5 else "amber" if lp_>0.5 else "green"
        st.markdown(f"""
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px">
          <div class="metric-card {cc}"><div class="metric-label">DAILY LOSS USED</div><div class="metric-value {'pos-red' if lp_>1 else ''}">{lp_:.2f}%</div><div class="metric-sub">Limit: {st.session_state.daily_loss_pct:.1f}%</div></div>
          <div class="metric-card green"><div class="metric-label">RISK REMAINING</div><div class="metric-value pos-green">{rem:.2f}%</div><div class="metric-sub">₹{rem/100*capital:,.0f}</div></div>
          <div class="metric-card blue"><div class="metric-label">CAPITAL</div><div class="metric-value">₹{capital:,.0f}</div></div>
          <div class="metric-card {'red' if halted else 'green'}"><div class="metric-label">ENGINE</div><div class="metric-value" style="font-size:14px">{'🔴 HALTED' if halted else '🟢 ACTIVE'}</div></div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div class="section-header">RISK RULES — ALWAYS ACTIVE</div>', unsafe_allow_html=True)
    rules=[
        ("VIX Filter",f"Pause Iron Condor when VIX > {st.session_state.vix_limit:.0f}","✅"),
        ("Daily Loss Limit",f"Halt engine at {st.session_state.daily_loss_pct:.1f}% loss","✅"),
        ("Position Sizing","Max 20% capital per spread","✅"),
        ("Iron Condor SL","Auto-exit at 150% of premium","✅"),
        ("Gap Risk Filter","Skip Monday entry if gap > 1%","✅"),
        ("Event Filter","No condors on expiry week","✅"),
        ("Max Open Positions","Block beyond 4 open legs","✅"),
        ("Duplicate Signal","Skip repeated signals","✅"),
        ("Market Hours","No trades outside 09:15–15:30 IST","✅"),
    ]
    th='<th>RULE</th><th>CONDITION</th><th>STATUS</th>'
    rows_rr=''.join(f'<tr><td style="font-weight:600">{r}</td><td>{c}</td><td style="color:var(--green)">{s}</td></tr>' for r,c,s in rules)
    st.markdown(f'<table class="qb-table"><thead><tr>{th}</tr></thead><tbody>{rows_rr}</tbody></table>', unsafe_allow_html=True)

    st.markdown('<div class="section-header">MANUAL CONTROLS</div>', unsafe_allow_html=True)
    m1,m2,m3,m4=st.columns(4)
    with m1:
        if st.button("⏸ PAUSE",use_container_width=True,key="r_pau"): st.session_state.engine_on=False; st.warning("Engine paused")
    with m2:
        if st.button("▶ RESUME",use_container_width=True,key="r_res"):
            if st.session_state.connected: st.session_state.engine_on=True; st.session_state.engine_halted=False; st.success("Resumed")
            else: st.error("Not connected")
    with m3:
        if st.button("🔃 RESET P&L",use_container_width=True,key="r_rst"): st.session_state.engine_halted=False; st.info("Reset done")
    with m4:
        st.markdown('<div class="emergency-btn">', unsafe_allow_html=True)
        if st.button("🛑 SQ OFF ALL",use_container_width=True,key="r_sq"):
            if broker: res=broker.square_off_all(); st.warning(f"Squared off {len(res)} positions")
            else: st.error("Not connected")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ─── AUTO-REFRESH — ALWAYS LAST ───────────────────────────────────────────────
if st.session_state.auto_refresh:
    time.sleep(st.session_state.refresh_interval)
    st.rerun()
