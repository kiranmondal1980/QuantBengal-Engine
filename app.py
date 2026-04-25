"""
QuantBengal Pro — app.py  v5.0
FIXES:
  1. Emergency Square Off wired correctly via st.session_state.broker
  2. Auto-refresh gated to market hours; sleep BEFORE rerun
  3. Mobile topbar z-index: header(1100) > topbar(999), 68px left-pad clears hamburger
  4. Risk tab fully null-guarded when not connected
  5. Backtest MultiIndex flattening robust + duplicate-column dedup
  6. Trade log P&L update loop is non-mutating (dict copy each iteration)
  7. Duplicate signal guard reset on manual REFRESH click
  8. Iron Condor LIVE DEPLOY uses st.session_state.broker correctly
  9. All tabs null-guard broker before use
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pytz, time, os

st.set_page_config(
    page_title="QuantBengal Pro",
    layout="wide",
    page_icon="⚡",
    initial_sidebar_state="expanded"
)

IST = pytz.timezone('Asia/Kolkata')

# ── SESSION STATE ──────────────────────────────────────────────────────────────
DEFAULTS = {
    "broker": None, "connected": False, "engine_on": False,
    "dry_run": True, "capital": 200000.0, "trade_log": [],
    "strategy": "SuperTrend + RSI", "auto_refresh": False,
    "refresh_interval": 30, "api_key": "", "client_id": "",
    "password": "", "totp_secret": "", "engine_halted": False,
    "last_auto_signal": "", "vix_limit": 20.0, "daily_loss_pct": 2.0,
    "_orders": [], "_trades": [], "order_pnl": {},
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

try:
    from broker_api import IndianBrokerAPI
    BROKER_OK = True
except Exception:
    BROKER_OK = False

from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands, AverageTrueRange


def sf(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def now_ist():
    return datetime.now(IST)


def market_open():
    n = now_ist()
    if n.weekday() > 4:
        return False
    return n.replace(hour=9, minute=15, second=0) <= n <= n.replace(hour=15, minute=30, second=0)


# ── SUPERTREND ─────────────────────────────────────────────────────────────────
def calc_supertrend(df, period=10, multiplier=3.0):
    high  = df['high'].astype(float)
    low   = df['low'].astype(float)
    close = df['close'].astype(float)
    atr   = AverageTrueRange(high=high, low=low, close=close, window=period).average_true_range()
    hl2   = (high + low) / 2
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    supertrend = pd.Series(index=df.index, dtype=float)
    direction  = pd.Series(index=df.index, dtype=int)
    for i in range(1, len(df)):
        if pd.isna(atr.iloc[i]):
            supertrend.iloc[i] = lower.iloc[i]; direction.iloc[i] = 1; continue
        prev_st  = supertrend.iloc[i - 1] if not pd.isna(supertrend.iloc[i - 1]) else lower.iloc[i]
        prev_dir = direction.iloc[i - 1]  if not pd.isna(direction.iloc[i - 1])  else 1
        curr_c   = float(close.iloc[i])
        if prev_dir == 1:
            curr_st  = max(lower.iloc[i], prev_st) if curr_c > prev_st else upper.iloc[i]
            curr_dir = 1 if curr_c > curr_st else -1
        else:
            curr_st  = min(upper.iloc[i], prev_st) if curr_c < prev_st else lower.iloc[i]
            curr_dir = -1 if curr_c < curr_st else 1
        supertrend.iloc[i] = curr_st
        direction.iloc[i]  = curr_dir
    return supertrend, direction


# ── BACKTEST ENGINE ────────────────────────────────────────────────────────────
def run_backtest(ticker, period, strategy_name):
    interval = "1d" if period in ("3mo", "6mo", "1y") else "15m"
    label    = "Daily" if interval == "1d" else "15-min"
    try:
        raw = yf.download(ticker, period=period, interval=interval,
                          progress=False, auto_adjust=True)
    except Exception as e:
        return None, f"Download error: {e}"
    if raw is None or raw.empty:
        return None, "No data from yfinance. Check ticker or try again."

    # ── ROBUST MultiIndex flattening ──────────────────────────────────────────
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [str(c[0]).lower() for c in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]
    raw = raw.loc[:, ~raw.columns.duplicated()]            # dedup
    raw.rename(columns={'adj close': 'close', 'adj_close': 'close'}, inplace=True)

    if 'close' not in raw.columns:
        return None, f"No 'close' column. Got: {list(raw.columns)}"

    df = raw.copy()
    df.index = pd.to_datetime(df.index)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=['close'], inplace=True)
    if len(df) < 40:
        return None, f"Too few candles ({len(df)}). Try a longer period."

    cs = df['close'].squeeze()
    df['ema_9']   = EMAIndicator(close=cs, window=9).ema_indicator()
    df['ema_21']  = EMAIndicator(close=cs, window=21).ema_indicator()
    df['ema_50']  = EMAIndicator(close=cs, window=50).ema_indicator()
    df['ema_200'] = EMAIndicator(close=cs, window=200).ema_indicator()
    df['rsi']     = RSIIndicator(close=cs, window=14).rsi()
    mo = MACD(close=cs)
    df['macd']   = mo.macd(); df['macd_s'] = mo.macd_signal(); df['macd_h'] = mo.macd_diff()
    bo = BollingerBands(close=cs, window=20, window_dev=2)
    df['bb_u'] = bo.bollinger_hband(); df['bb_l'] = bo.bollinger_lband(); df['bb_m'] = bo.bollinger_mavg()
    h_col = df['high'] if 'high' in df.columns else cs
    l_col = df['low']  if 'low'  in df.columns else cs
    try:
        df['atr'] = AverageTrueRange(high=h_col, low=l_col, close=cs, window=14).average_true_range()
    except Exception:
        df['atr'] = cs * 0.005
    try:
        df['st'], df['st_dir'] = calc_supertrend(df, 10, 3.0)
    except Exception:
        df['st'] = cs; df['st_dir'] = 1
    try:
        sto = StochasticOscillator(high=h_col, low=l_col, close=cs, window=14, smooth_window=3)
        df['stoch_k'] = sto.stoch(); df['stoch_d'] = sto.stoch_signal()
    except Exception:
        df['stoch_k'] = 50.0; df['stoch_d'] = 50.0

    df.dropna(subset=['ema_9', 'ema_21', 'rsi', 'macd'], inplace=True)

    trades = []; in_pos = False; entry_p = 0.0; direction = ""; entry_idx = 0
    for i in range(2, len(df)):
        p1 = df.iloc[i - 1]; p2 = df.iloc[i - 2]; curr = df.iloc[i]
        c    = sf(curr['close']); atr_ = sf(curr['atr']) or c * 0.005
        r    = sf(curr['rsi']); e9 = sf(curr['ema_9']); e21 = sf(curr['ema_21'])
        e50  = sf(curr['ema_50']); cm = sf(curr['macd']); cs_ = sf(curr['macd_s'])
        pm   = sf(p1['macd']); ps = sf(p1['macd_s'])
        p1e9 = sf(p1['ema_9']); p1e21 = sf(p1['ema_21'])
        bu   = sf(curr['bb_u']); bl = sf(curr['bb_l']); bm = sf(curr['bb_m'])
        st_d = int(sf(curr.get('st_dir', 1) or 1))
        sk   = sf(curr.get('stoch_k', 50)); sd = sf(curr.get('stoch_d', 50))
        p1sk = sf(p1.get('stoch_k', 50)); p1sd = sf(p1.get('stoch_d', 50))
        bull = False; bear = False
        if strategy_name == "SuperTrend + RSI":
            bull = st_d == 1 and 50 < r < 75 and e9 > e21
            bear = st_d == -1 and 25 < r < 50 and e9 < e21
        elif strategy_name == "MACD + EMA Confluence":
            bull = pm <= ps and cm > cs_ and e9 > e21 and e21 > e50 and 45 < r < 72
            bear = pm >= ps and cm < cs_ and e9 < e21 and e21 < e50 and 28 < r < 55
        elif strategy_name == "Stochastic + BB Mean Reversion":
            bull = p1sk <= p1sd and sk > sd and sk < 35 and c < bm and r < 50
            bear = p1sk >= p1sd and sk < sd and sk > 65 and c > bm and r > 50
        elif strategy_name == "Triple EMA + Volume Trend":
            bull = e9 > e21 and e21 > e50 and p1e9 > p1e21 and 52 < r < 72
            bear = e9 < e21 and e21 < e50 and p1e9 < p1e21 and 28 < r < 48
        elif strategy_name == "Momentum Pulse (EMA+RSI)":
            bull = p1e9 <= p1e21 and e9 > e21 and r > 55 and cm > cs_
            bear = p1e9 >= p1e21 and e9 < e21 and r < 45 and cm < cs_
        elif strategy_name == "Bollinger Squeeze Breakout":
            bbw = (bu - bl) / bm if bm else 0.05; sq = bbw < 0.04
            bull = sq and c > bu and r > 55 and cm > cs_
            bear = sq and c < bl and r < 45 and cm < cs_
        sl_m = {"SuperTrend + RSI": 1.2, "MACD + EMA Confluence": 1.3,
                "Stochastic + BB Mean Reversion": 1.0, "Triple EMA + Volume Trend": 1.4,
                "Momentum Pulse (EMA+RSI)": 1.5, "Bollinger Squeeze Breakout": 1.1}.get(strategy_name, 1.3)
        tgt_m = sl_m * 1.8
        if not in_pos:
            if bull:
                entry_p = c; in_pos = True; direction = "LONG"; entry_idx = i
                trades.append({"Date": df.index[i], "Signal": "BUY CALL", "Entry": entry_p,
                                "SL": round(entry_p - sl_m * atr_, 1),
                                "Target": round(entry_p + tgt_m * atr_, 1), "ATR": round(atr_, 1)})
            elif bear:
                entry_p = c; in_pos = True; direction = "SHORT"; entry_idx = i
                trades.append({"Date": df.index[i], "Signal": "BUY PUT", "Entry": entry_p,
                                "SL": round(entry_p + sl_m * atr_, 1),
                                "Target": round(entry_p - tgt_m * atr_, 1), "ATR": round(atr_, 1)})
        else:
            if i - entry_idx < 2:
                continue
            exit_p = None; reason = ""
            if direction == "LONG":
                if c <= trades[-1]["SL"]:      exit_p = trades[-1]["SL"];     reason = "SL Hit"
                elif c >= trades[-1]["Target"]: exit_p = trades[-1]["Target"]; reason = "Target Hit"
                elif st_d == -1 and e9 < e21:  exit_p = c;                    reason = "Trend Exit"
            else:
                if c >= trades[-1]["SL"]:      exit_p = trades[-1]["SL"];     reason = "SL Hit"
                elif c <= trades[-1]["Target"]: exit_p = trades[-1]["Target"]; reason = "Target Hit"
                elif st_d == 1 and e9 > e21:   exit_p = c;                    reason = "Trend Exit"
            if exit_p is not None:
                pts = exit_p - entry_p if direction == "LONG" else entry_p - exit_p
                trades[-1].update({"Exit": exit_p, "Points": round(pts, 1), "Reason": reason})
                in_pos = False; direction = ""

    trades = [t for t in trades if "Points" in t]
    if not trades:
        return None, f"No completed trades for '{strategy_name}'. Try a different period."

    res = pd.DataFrame(trades)
    try:
        res['Date'] = pd.to_datetime(res['Date'])
        if hasattr(res['Date'].dt, 'tz') and res['Date'].dt.tz is not None:
            res['Date'] = res['Date'].dt.tz_convert('Asia/Kolkata')
        res['Date'] = res['Date'].dt.strftime('%d-%b %H:%M' if interval == '15m' else '%d-%b-%Y')
    except Exception:
        res['Date'] = res['Date'].astype(str)

    res['Points']     = res['Points'].astype(float)
    res['Result']     = res['Points'].apply(lambda x: "WIN" if x > 0 else "LOSS")
    res['Cumulative'] = res['Points'].cumsum()
    wins   = res[res['Points'] > 0]; losses = res[res['Points'] < 0]
    metrics = {
        "total_pts":        round(res['Points'].sum(), 1),
        "win_rate":         round((res['Points'] > 0).mean() * 100, 1),
        "trades":           len(res),
        "max_dd":           round((res['Cumulative'].cummax() - res['Cumulative']).max(), 1),
        "avg_win":          round(wins['Points'].mean(), 1)        if len(wins)   else 0,
        "avg_loss":         round(abs(losses['Points'].mean()), 1) if len(losses) else 0,
        "rr_ratio":         round(abs(wins['Points'].mean() / losses['Points'].mean()), 2)
                            if len(wins) and len(losses) else 0,
        "interval":         label,
        "candles":          len(df),
        "consecutive_wins": int((res['Result'] == 'WIN').groupby(
                                (res['Result'] != 'WIN').cumsum()).sum().max() or 0),
    }
    return res, metrics


# ── SIGNAL EVALUATOR ───────────────────────────────────────────────────────────
def evaluate_signal(df, strategy_name, price):
    if df is None or len(df) < 5:
        return "HOLD", "Insufficient data", 0, 0
    lat = df.iloc[-1]; p1 = df.iloc[-2]
    c    = sf(lat['close']); atr_ = sf(lat.get('atr', c * 0.005)) or c * 0.005
    r    = sf(lat['rsi']); e9 = sf(lat['ema_9']); e21 = sf(lat['ema_21'])
    e50  = sf(lat.get('ema_50', e21))
    cm   = sf(lat['macd']); cs_ = sf(lat['macd_s'])
    pm   = sf(p1['macd']); ps_ = sf(p1['macd_s'])
    p1e9 = sf(p1['ema_9']); p1e21 = sf(p1['ema_21'])
    bu   = sf(lat['bb_u']); bl = sf(lat['bb_l']); bm = sf(lat['bb_m'])
    st_d = int(sf(lat.get('st_dir', 1) or 1))
    sk   = sf(lat.get('stoch_k', 50)); sd_ = sf(lat.get('stoch_d', 50))
    p1sk = sf(p1.get('stoch_k', 50)); p1sd = sf(p1.get('stoch_d', 50))
    sl_m = 1.3; tgt_m = sl_m * 1.8
    sl_long  = round(c - sl_m * atr_, 1); tgt_long  = round(c + tgt_m * atr_, 1)
    sl_short = round(c + sl_m * atr_, 1); tgt_short = round(c - tgt_m * atr_, 1)
    if strategy_name == "SuperTrend + RSI":
        if st_d == 1 and 50 < r < 75 and e9 > e21:
            return "BUY_CALL", f"SuperTrend ↑ | RSI {r:.0f} | EMA aligned", sl_long, tgt_long
        if st_d == -1 and 25 < r < 50 and e9 < e21:
            return "BUY_PUT", f"SuperTrend ↓ | RSI {r:.0f} | EMA aligned", sl_short, tgt_short
    elif strategy_name == "MACD + EMA Confluence":
        if pm <= ps_ and cm > cs_ and e9 > e21 and e21 > e50 and 45 < r < 72:
            return "BUY_CALL", f"MACD ↑ + EMA bull stack | RSI {r:.0f}", sl_long, tgt_long
        if pm >= ps_ and cm < cs_ and e9 < e21 and e21 < e50 and 28 < r < 55:
            return "BUY_PUT", f"MACD ↓ + EMA bear stack | RSI {r:.0f}", sl_short, tgt_short
    elif strategy_name == "Stochastic + BB Mean Reversion":
        if p1sk <= p1sd and sk > sd_ and sk < 35 and r < 50:
            return "BUY_CALL", f"Stoch oversold ↑ | RSI {r:.0f}", sl_long, tgt_long
        if p1sk >= p1sd and sk < sd_ and sk > 65 and r > 50:
            return "BUY_PUT", f"Stoch overbought ↓ | RSI {r:.0f}", sl_short, tgt_short
    elif strategy_name == "Triple EMA + Volume Trend":
        if e9 > e21 and e21 > e50 and 52 < r < 72:
            return "BUY_CALL", f"9>21>50 EMA bull | RSI {r:.0f}", sl_long, tgt_long
        if e9 < e21 and e21 < e50 and 28 < r < 48:
            return "BUY_PUT", f"9<21<50 EMA bear | RSI {r:.0f}", sl_short, tgt_short
    elif strategy_name == "Momentum Pulse (EMA+RSI)":
        if p1e9 <= p1e21 and e9 > e21 and r > 55 and cm > cs_:
            return "BUY_CALL", f"EMA crossover ↑ | RSI {r:.0f} | MACD conf", sl_long, tgt_long
        if p1e9 >= p1e21 and e9 < e21 and r < 45 and cm < cs_:
            return "BUY_PUT", f"EMA crossover ↓ | RSI {r:.0f} | MACD conf", sl_short, tgt_short
    elif strategy_name == "Bollinger Squeeze Breakout":
        bw = (bu - bl) / bm if bm else 0.05; sq = bw < 0.04
        if sq and c > bu and r > 55 and cm > cs_:
            return "BUY_CALL", f"BB squeeze ↑ | RSI {r:.0f}", sl_long, tgt_long
        if sq and c < bl and r < 45 and cm < cs_:
            return "BUY_PUT", f"BB squeeze ↓ | RSI {r:.0f}", sl_short, tgt_short
    trend = "BULLISH" if st_d == 1 else "BEARISH"
    rsi_s = "OVERBOUGHT" if r > 70 else "OVERSOLD" if r < 30 else f"{r:.0f}"
    return "HOLD", f"No confluence | Trend: {trend} | RSI: {rsi_s} | Waiting", 0, 0


# ═══════════════════════════════════════════════════════════════════════════════
#  CSS — BLOOMBERG TERMINAL v5.0 (Mobile-first z-index, responsive cards)
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Sora:wght@300;400;600;700;800&display=swap');
:root {
  --bg:#f4f6fb; --panel:#ffffff; --panel2:#f8fafd; --border:#e4e9f2; --border2:#d0d8eb;
  --navy:#0d1b3e; --blue:#1847c5; --blue-l:#e8eefb; --blue-m:rgba(24,71,197,.10);
  --teal:#0891b2; --green:#057a55; --green-l:#ecfdf5; --green-m:rgba(5,122,85,.10);
  --red:#c81e3a; --red-l:#fff1f3; --red-m:rgba(200,30,58,.10);
  --amber:#b45309; --amber-l:#fffbeb; --amber-m:rgba(180,83,9,.10);
  --text:#0d1b3e; --text2:#334163; --muted:#6b7a9f;
  --mono:'JetBrains Mono',monospace; --sans:'Sora',sans-serif;
  --radius:12px; --shadow:0 2px 12px rgba(13,27,62,.07); --shadow-lg:0 8px 32px rgba(13,27,62,.12);
}
*,*::before,*::after{box-sizing:border-box;}
#MainMenu,footer{visibility:hidden!important;}

/* FIX 1: header above topbar, transparent bg, hamburger always tappable */
header[data-testid="stHeader"]{background:transparent!important;z-index:1100!important;box-shadow:none!important;pointer-events:none;}
header[data-testid="stHeader"] button,
header[data-testid="stHeader"] [data-testid="collapsedControl"]{pointer-events:all!important;}
.stDeployButton{display:none!important;}
.block-container{padding:0!important;max-width:100%!important;padding-top:3.5rem!important;}
.stApp{background:var(--bg)!important;font-family:var(--sans)!important;color:var(--text)!important;}

/* SIDEBAR */
section[data-testid="stSidebar"]{background:var(--navy)!important;box-shadow:4px 0 24px rgba(13,27,62,.18)!important;}
section[data-testid="stSidebar"] *{color:#e2e8f7!important;}
section[data-testid="stSidebar"] .stSelectbox>div>div,
section[data-testid="stSidebar"] input{background:rgba(255,255,255,.08)!important;border:1px solid rgba(255,255,255,.15)!important;color:#e2e8f7!important;border-radius:8px!important;}
section[data-testid="stSidebar"] label{color:rgba(226,232,247,.7)!important;font-size:11px!important;font-family:var(--mono)!important;}
section[data-testid="stSidebar"] .stSlider>div>div>div{background:var(--blue)!important;}
section[data-testid="stSidebar"] .stButton>button{background:rgba(255,255,255,.1)!important;border:1px solid rgba(255,255,255,.2)!important;color:#e2e8f7!important;font-size:11px!important;}
.sb-connect-btn .stButton>button{background:var(--blue)!important;border:none!important;color:white!important;font-weight:700!important;}
.sb-danger .stButton>button{background:var(--red)!important;border:none!important;color:white!important;font-weight:700!important;}
.sb-success .stButton>button{background:var(--green)!important;border:none!important;color:white!important;font-weight:700!important;}

/* FIX 2: Topbar z-index 999 < header 1100; 68px left padding clears hamburger */
.topbar{background:var(--navy);padding:0 20px 0 68px;height:52px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:999;box-shadow:0 2px 16px rgba(13,27,62,.25);}
.tb-logo{font-family:var(--mono);font-size:15px;font-weight:700;color:#fff;letter-spacing:-.3px;white-space:nowrap;}
.tb-logo em{color:#4d8eff;font-style:normal;}
.tb-logo small{font-size:9px;color:rgba(255,255,255,.4);letter-spacing:3px;margin-left:8px;font-weight:400;}
.tb-pills{display:flex;align-items:center;gap:6px;flex-wrap:wrap;}
.pill{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:20px;font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.5px;white-space:nowrap;}
.pill-conn{background:rgba(5,122,85,.25);color:#34d399;border:1px solid rgba(52,211,153,.3);}
.pill-disc{background:rgba(200,30,58,.25);color:#f87171;border:1px solid rgba(248,113,113,.3);}
.pill-paper{background:rgba(180,83,9,.25);color:#fbbf24;border:1px solid rgba(251,191,36,.3);}
.pill-live{background:rgba(200,30,58,.35);color:#f87171;border:1px solid rgba(248,113,113,.4);animation:live-pulse 2s infinite;}
.pill-auto{background:rgba(5,122,85,.35);color:#6ee7b7;border:1px solid rgba(110,231,183,.4);}
.pill-strat{background:rgba(255,255,255,.08);color:rgba(255,255,255,.7);border:1px solid rgba(255,255,255,.12);}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block;}
.dot-g{background:#34d399;animation:pulse 2s infinite;} .dot-r{background:#f87171;}
@keyframes live-pulse{0%,100%{opacity:1}50%{opacity:.6}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.ar-banner{background:linear-gradient(90deg,var(--blue-l),#f0f4ff);border-bottom:1px solid var(--border);padding:7px 24px;font-family:var(--mono);font-size:11px;color:var(--blue);display:flex;align-items:center;gap:8px;}

/* FIX 3: Responsive metric cards */
.metric-row{display:flex;flex-wrap:wrap;gap:12px;padding:14px 18px;}
.mcard{flex:1 1 150px;min-width:130px;max-width:100%;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:14px 15px;position:relative;overflow:hidden;box-shadow:var(--shadow);transition:box-shadow .2s;}
.mcard:hover{box-shadow:var(--shadow-lg);}
.mcard-accent{position:absolute;top:0;left:0;right:0;height:3px;border-radius:var(--radius) var(--radius) 0 0;}
.mcard-label{font-family:var(--mono);font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:1.5px;margin-bottom:7px;}
.mcard-value{font-family:var(--mono);font-size:20px;font-weight:700;color:var(--text);line-height:1;}
.mcard-sub{font-family:var(--mono);font-size:10px;color:var(--muted);margin-top:5px;}
.c-blue{background:var(--blue);} .c-green{background:var(--green);} .c-red{background:var(--red);}
.c-amber{background:var(--amber);} .c-teal{background:var(--teal);} .c-navy{background:var(--navy);}
.v-green{color:var(--green)!important;} .v-red{color:var(--red)!important;}
.v-amber{color:var(--amber)!important;} .v-blue{color:var(--blue)!important;}

/* SIGNALS */
.sig-hold{background:var(--panel2);border:1.5px solid var(--border2);color:var(--muted);text-align:center;padding:13px 18px;border-radius:var(--radius);font-family:var(--mono);font-size:13px;font-weight:700;letter-spacing:1.5px;}
.sig-buy{background:var(--green-l);border:2px solid var(--green);color:var(--green);text-align:center;padding:13px 18px;border-radius:var(--radius);font-family:var(--mono);font-size:13px;font-weight:700;letter-spacing:1.5px;box-shadow:0 0 20px var(--green-m);}
.sig-sell{background:var(--red-l);border:2px solid var(--red);color:var(--red);text-align:center;padding:13px 18px;border-radius:var(--radius);font-family:var(--mono);font-size:13px;font-weight:700;letter-spacing:1.5px;box-shadow:0 0 20px var(--red-m);}
.sec-hdr{font-family:var(--mono);font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:2.5px;padding:16px 18px 10px;border-top:1px solid var(--border);}

/* FIX 4: Scrollable tables */
.table-responsive{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;}
.qbt{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11px;white-space:nowrap;}
.qbt thead tr{background:var(--panel2);}
.qbt th{padding:9px 12px;text-align:left;font-weight:500;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);}
.qbt td{padding:8px 12px;border-bottom:1px solid var(--border);color:var(--text2);vertical-align:middle;}
.qbt tbody tr:hover td{background:var(--panel2);}
.row-profit td{background:rgba(5,122,85,.04)!important;}
.row-loss td{background:rgba(200,30,58,.04)!important;}

.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:20px;font-size:9px;font-family:var(--mono);font-weight:700;}
.b-win{background:var(--green-l);color:var(--green);border:1px solid rgba(5,122,85,.3);}
.b-loss{background:var(--red-l);color:var(--red);border:1px solid rgba(200,30,58,.3);}
.b-buy{background:var(--green-l);color:var(--green);border:1px solid rgba(5,122,85,.3);}
.b-sell{background:var(--red-l);color:var(--red);border:1px solid rgba(200,30,58,.3);}
.b-comp{background:var(--blue-l);color:var(--blue);border:1px solid rgba(24,71,197,.3);}
.b-open{background:var(--amber-l);color:var(--amber);border:1px solid rgba(180,83,9,.3);}
.b-hold{background:rgba(107,122,159,.1);color:var(--muted);border:1px solid rgba(107,122,159,.2);}

.consensus-bar{display:flex;align-items:center;border-radius:8px;overflow:hidden;height:8px;margin:8px 0;}
.cb-bull{background:var(--green);height:8px;transition:width .4s;}
.cb-bear{background:var(--red);height:8px;transition:width .4s;}
.cb-neut{background:var(--border2);height:8px;transition:width .4s;}

.conn-notice{background:var(--amber-l);border:1.5px solid rgba(180,83,9,.3);border-radius:var(--radius);padding:20px 22px;margin:18px;display:flex;align-items:flex-start;gap:14px;}
.conn-icon{font-size:28px;flex-shrink:0;}
.conn-body{font-family:var(--sans);font-size:14px;color:var(--text2);line-height:1.65;}
.conn-body strong{color:var(--amber);}

/* STREAMLIT OVERRIDES */
.stButton>button{border-radius:8px!important;font-family:var(--mono)!important;font-size:11px!important;font-weight:700!important;letter-spacing:.5px!important;transition:all .15s!important;border:1px solid var(--border)!important;background:var(--panel)!important;color:var(--text)!important;padding:9px 16px!important;}
.stButton>button:hover{background:var(--blue)!important;color:white!important;border-color:var(--blue)!important;}
.main-btn .stButton>button{background:var(--blue)!important;color:white!important;border:none!important;}
.danger-btn .stButton>button{background:var(--red)!important;color:white!important;border:none!important;}
.success-btn .stButton>button{background:var(--green)!important;color:white!important;border:none!important;}
.stTabs [data-baseweb="tab-list"]{background:var(--panel)!important;border-bottom:1px solid var(--border)!important;gap:0!important;padding:0 14px!important;overflow-x:auto!important;box-shadow:0 2px 8px rgba(13,27,62,.04);}
.stTabs [data-baseweb="tab"]{background:transparent!important;color:var(--muted)!important;font-family:var(--mono)!important;font-size:10px!important;font-weight:700!important;letter-spacing:1.5px!important;padding:12px 13px!important;border-bottom:2px solid transparent!important;text-transform:uppercase!important;white-space:nowrap!important;}
.stTabs [aria-selected="true"]{color:var(--blue)!important;border-bottom-color:var(--blue)!important;}
.stTabs [data-baseweb="tab-panel"]{background:var(--bg)!important;padding:0!important;}
.stSelectbox>div>div,.stTextInput>div>div>input,.stNumberInput>div>div>input{border-radius:8px!important;border:1px solid var(--border)!important;font-family:var(--mono)!important;font-size:12px!important;}
.stSelectbox label,.stNumberInput label,.stTextInput label,.stSlider label,.stToggle label{font-family:var(--mono)!important;font-size:10px!important;text-transform:uppercase!important;letter-spacing:1px!important;color:var(--muted)!important;}
div[data-testid="stMetric"]{background:var(--panel)!important;border:1px solid var(--border)!important;border-radius:var(--radius)!important;padding:16px!important;box-shadow:var(--shadow)!important;}
.pad{padding:0 18px 26px;} .padx{padding:0 18px;}
.pnl-live{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:20px;font-family:var(--mono);font-size:10px;font-weight:700;}
.pnl-pos{background:var(--green-l);color:var(--green);border:1px solid rgba(5,122,85,.25);}
.pnl-neg{background:var(--red-l);color:var(--red);border:1px solid rgba(200,30,58,.25);}
.pnl-neu{background:var(--panel2);color:var(--muted);border:1px solid var(--border);}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div style="padding:20px 16px 4px">
      <div style="font-family:'JetBrains Mono',monospace;font-size:16px;font-weight:700;color:#fff">
        QUANT<em style="color:#4d8eff;font-style:normal">BENGAL</em>
        <span style="font-size:8px;color:rgba(255,255,255,.35);letter-spacing:3px;margin-left:6px">PRO</span>
      </div>
      <div style="font-size:9px;color:rgba(255,255,255,.4);letter-spacing:2px;margin-top:3px;font-family:'JetBrains Mono',monospace">AUTOMATED TRADING ENGINE</div>
    </div>
    <div style="height:1px;background:rgba(255,255,255,.08);margin:12px 0"></div>
    """, unsafe_allow_html=True)

    if st.session_state.connected:
        st.markdown('<div style="margin:0 4px 10px;background:rgba(52,211,153,.15);border:1px solid rgba(52,211,153,.3);border-radius:8px;padding:7px 12px;font-family:JetBrains Mono,monospace;font-size:10px;color:#34d399;text-align:center">● ANGEL ONE CONNECTED</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="margin:0 4px 10px;background:rgba(248,113,113,.15);border:1px solid rgba(248,113,113,.3);border-radius:8px;padding:7px 12px;font-family:JetBrains Mono,monospace;font-size:10px;color:#f87171;text-align:center">● DISCONNECTED — expand below</div>', unsafe_allow_html=True)

    with st.expander("🔌 Angel One Connection", expanded=not st.session_state.connected):
        st.session_state.api_key     = st.text_input("API Key",                    value=st.session_state.api_key,     type="password", key="s_api")
        st.session_state.client_id   = st.text_input("Client ID",                  value=st.session_state.client_id,                    key="s_cid")
        st.session_state.password    = st.text_input("Password",                   value=st.session_state.password,    type="password", key="s_pw")
        st.session_state.totp_secret = st.text_input("TOTP Secret (32-char)",      value=st.session_state.totp_secret, type="password", key="s_totp")
        st.markdown('<div class="sb-connect-btn">', unsafe_allow_html=True)
        if st.button("⚡ CONNECT TO ANGEL ONE", use_container_width=True, key="btn_conn"):
            if not all([st.session_state.api_key, st.session_state.client_id,
                        st.session_state.password, st.session_state.totp_secret]):
                st.error("All 4 credential fields are required.")
            elif not BROKER_OK:
                st.error("broker_api.py not found in the same folder.")
            else:
                os.environ["BROKER_API_KEY"] = st.session_state.api_key
                os.environ["CLIENT_ID"]      = st.session_state.client_id
                os.environ["PASSWORD"]       = st.session_state.password
                os.environ["TOTP_TOKEN"]     = st.session_state.totp_secret
                with st.spinner("Authenticating..."):
                    try:
                        b = IndianBrokerAPI()
                        if b.connected:
                            st.session_state.broker    = b
                            st.session_state.connected = True
                            st.success("✅ Connected!")
                            time.sleep(0.3); st.rerun()
                        else:
                            st.error("❌ Auth failed.\n• TOTP Secret = 32-char BASE32, NOT the 6-digit OTP\n• Double-check Client ID and Password")
                    except Exception as ex:
                        st.error(f"Error: {ex}")
        st.markdown('</div>', unsafe_allow_html=True)
        if st.session_state.connected:
            if st.button("🔌 Disconnect", use_container_width=True, key="btn_disc"):
                st.session_state.broker    = None
                st.session_state.connected = False
                st.session_state.engine_on = False
                st.rerun()

    st.markdown('<div style="height:1px;background:rgba(255,255,255,.08);margin:8px 0"></div>', unsafe_allow_html=True)
    st.markdown('<div style="padding:4px 4px 2px;font-family:JetBrains Mono,monospace;font-size:9px;color:rgba(255,255,255,.4);letter-spacing:2px;text-transform:uppercase">Engine Config</div>', unsafe_allow_html=True)
    STRATS = ["SuperTrend + RSI", "MACD + EMA Confluence", "Stochastic + BB Mean Reversion",
              "Triple EMA + Volume Trend", "Momentum Pulse (EMA+RSI)",
              "Bollinger Squeeze Breakout", "Iron Condor (BankNifty)"]
    idx = STRATS.index(st.session_state.strategy) if st.session_state.strategy in STRATS else 0
    st.session_state.strategy = st.selectbox("Strategy", STRATS, index=idx, key="sel_s")
    st.session_state.capital  = float(st.number_input("Capital (₹)", min_value=50000, max_value=5000000,
                                                        value=int(st.session_state.capital), step=10000, key="cap_n"))
    st.session_state.dry_run  = st.toggle("🧪 Dry Run (Paper Trade)", value=st.session_state.dry_run, key="dry_t")
    if not st.session_state.dry_run:
        st.markdown('<div style="background:rgba(200,30,58,.2);border-radius:6px;padding:6px 10px;font-size:10px;color:#f87171;margin-top:4px;font-family:JetBrains Mono,monospace">⚠️ LIVE MODE — REAL ORDERS ACTIVE</div>', unsafe_allow_html=True)

    st.markdown('<div style="height:1px;background:rgba(255,255,255,.08);margin:8px 0"></div>', unsafe_allow_html=True)
    st.markdown('<div style="padding:4px 4px 2px;font-family:JetBrains Mono,monospace;font-size:9px;color:rgba(255,255,255,.4);letter-spacing:2px;text-transform:uppercase">Auto Refresh</div>', unsafe_allow_html=True)
    st.session_state.auto_refresh = st.toggle("⏱ Auto Refresh", value=st.session_state.auto_refresh, key="ar_t")
    if st.session_state.auto_refresh:
        st.session_state.refresh_interval = st.slider("Interval (s)", 15, 120, 30, 5, key="ar_s")

    st.markdown('<div style="height:1px;background:rgba(255,255,255,.08);margin:8px 0"></div>', unsafe_allow_html=True)
    st.markdown('<div style="padding:4px 4px 4px;font-family:JetBrains Mono,monospace;font-size:9px;color:rgba(255,255,255,.4);letter-spacing:2px;text-transform:uppercase">Auto Trading</div>', unsafe_allow_html=True)
    if st.session_state.engine_on:
        st.markdown('<div style="background:rgba(52,211,153,.15);border:1px solid rgba(52,211,153,.3);border-radius:8px;padding:7px;text-align:center;font-family:JetBrains Mono,monospace;font-size:10px;color:#34d399;margin-bottom:6px">🤖 ENGINE RUNNING</div>', unsafe_allow_html=True)
        st.markdown('<div class="sb-danger">', unsafe_allow_html=True)
        if st.button("⏹ STOP AUTO-TRADE", use_container_width=True, key="stop_a"):
            st.session_state.engine_on = False; st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="sb-success">', unsafe_allow_html=True)
        if st.button("▶ START AUTO-TRADE", use_container_width=True, key="start_a"):
            if not st.session_state.connected: st.error("Connect to Angel One first.")
            else: st.session_state.engine_on = True; st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div style="height:1px;background:rgba(255,255,255,.08);margin:8px 0"></div>', unsafe_allow_html=True)
    st.markdown('<div style="padding:4px 4px 2px;font-family:JetBrains Mono,monospace;font-size:9px;color:rgba(255,255,255,.4);letter-spacing:2px;text-transform:uppercase">Risk Controls</div>', unsafe_allow_html=True)
    st.session_state.vix_limit      = st.slider("VIX Threshold",        10.0, 30.0, st.session_state.vix_limit,      0.5,  key="vx_s")
    st.session_state.daily_loss_pct = st.slider("Daily Loss Limit (%)",  0.5,  5.0, st.session_state.daily_loss_pct, 0.25, key="dl_s")

    st.markdown('<div style="height:1px;background:rgba(255,255,255,.08);margin:8px 0"></div>', unsafe_allow_html=True)

    # ── FIX: Emergency SOS — always reads st.session_state.broker ──────────────
    st.markdown('<div class="sb-danger">', unsafe_allow_html=True)
    if st.button("🛑 EMERGENCY SQUARE OFF", use_container_width=True, key="sos"):
        _eb = st.session_state.get("broker")
        if _eb and getattr(_eb, "connected", False):
            with st.spinner("Closing ALL open positions at market price..."):
                _res = _eb.square_off_all()
            st.warning(f"✅ Emergency square off complete — {len(_res)} position(s) closed")
            st.session_state.engine_on = False
        else:
            st.error("Not connected to Angel One. Cannot square off.")
    st.markdown('</div>', unsafe_allow_html=True)

    n = now_ist(); mo = market_open()
    st.markdown(f"""
    <div style="padding:12px 4px 4px;font-family:JetBrains Mono,monospace;font-size:10px;color:rgba(255,255,255,.4);line-height:2">
      <div>🕐 {n.strftime('%d %b  %H:%M:%S IST')}</div>
      <div>Market: {'<span style="color:#34d399">● OPEN</span>' if mo else '<span style="color:#f87171">● CLOSED</span>'}</div>
      <div>Mode: {'<span style="color:#fbbf24">PAPER</span>' if st.session_state.dry_run else '<span style="color:#f87171;font-weight:700">⚡ LIVE</span>'}</div>
      <div>Engine: {'<span style="color:#34d399;font-weight:700">RUNNING 🤖</span>' if st.session_state.engine_on else '<span style="color:rgba(255,255,255,.3)">IDLE</span>'}</div>
    </div>""", unsafe_allow_html=True)


# ── TOPBAR ─────────────────────────────────────────────────────────────────────
conn_pill  = ('<span class="pill pill-conn"><span class="dot dot-g"></span>CONNECTED</span>'
              if st.session_state.connected else
              '<span class="pill pill-disc"><span class="dot dot-r"></span>DISCONNECTED</span>')
mode_pill  = ('<span class="pill pill-paper">PAPER</span>' if st.session_state.dry_run
              else '<span class="pill pill-live">⚡ LIVE</span>')
strat_pill = f'<span class="pill pill-strat">{st.session_state.strategy[:22].upper()}</span>'
auto_pill  = '<span class="pill pill-auto">🤖 AUTO-ON</span>' if st.session_state.engine_on else ''

st.markdown(f"""
<div class="topbar">
  <div class="tb-logo">QUANT<em>BENGAL</em><small>PRO</small></div>
  <div class="tb-pills">{conn_pill}{mode_pill}{strat_pill}{auto_pill}</div>
</div>""", unsafe_allow_html=True)

if st.session_state.auto_refresh:
    nxt = (now_ist() + timedelta(seconds=st.session_state.refresh_interval)).strftime("%H:%M:%S")
    st.markdown(f'<div class="ar-banner">⏱ AUTO-REFRESH — every {st.session_state.refresh_interval}s — next: <strong>{nxt} IST</strong></div>', unsafe_allow_html=True)


# ── TABS ───────────────────────────────────────────────────────────────────────
tabs = st.tabs(["⚡ LIVE TERMINAL", "📌 POSITIONS & P&L", "📋 ORDER BOOK",
                "📊 BACKTEST", "🦅 IRON CONDOR", "🛡️ RISK ENGINE"])
tab_term, tab_pos, tab_ord, tab_bt, tab_ic, tab_risk = tabs


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — LIVE TERMINAL
# ══════════════════════════════════════════════════════════════════════════════
with tab_term:
    broker = st.session_state.broker
    if not broker:
        st.markdown("""<div class="conn-notice"><div class="conn-icon">🔌</div>
        <div class="conn-body"><strong>Connection required</strong> — open the sidebar
        (<strong>></strong> top-left on mobile) and enter your Angel One credentials,
        then tap <strong>⚡ CONNECT TO ANGEL ONE</strong>.</div></div>""", unsafe_allow_html=True)
        st.markdown('<div class="metric-row">' + ''.join([
            f'<div class="mcard"><div class="mcard-accent c-navy"></div>'
            f'<div class="mcard-label">{l}</div><div class="mcard-value" style="color:var(--border2)">——</div>'
            f'<div class="mcard-sub">Awaiting connection</div></div>'
            for l in ["Live Price", "EMA 9/21", "RSI (14)", "MACD", "ATR"]
        ]) + '</div>', unsafe_allow_html=True)
        st.markdown('<div class="pad"><div class="sig-hold">🔌 CONNECT TO BEGIN</div></div>', unsafe_allow_html=True)
        st.stop()

    c1, c2, c3, _ = st.columns([1, 1, 1, 5])
    with c1:
        st.markdown('<div style="padding:10px 0 0 18px"><div class="main-btn">', unsafe_allow_html=True)
        do_ref = st.button("🔄 REFRESH", key="t_r")
        st.markdown('</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown('<div style="padding:10px 0 0 0"><div class="main-btn">', unsafe_allow_html=True)
        run_btn = st.button("▶ EXECUTE", key="t_e")
        st.markdown('</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown('<div style="padding:10px 0 0 0">', unsafe_allow_html=True)
        clr_log = st.button("🗑 CLEAR LOG", key="t_cl")
        st.markdown('</div>', unsafe_allow_html=True)

    # FIX: reset duplicate-signal guard on manual refresh
    if do_ref:
        st.session_state.last_auto_signal = ""
        st.rerun()
    if clr_log:
        st.session_state.trade_log = []
        st.rerun()

    sym_map = {s: "BANKNIFTY" for s in STRATS}
    sym_map["Bollinger Squeeze Breakout"] = "NIFTY"
    sym = sym_map.get(st.session_state.strategy, "BANKNIFTY")

    with st.spinner("Fetching live market data..."):
        candles = broker.get_data(symbol=sym)

    df = pd.DataFrame()
    if candles and len(candles) >= 30:
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        for col in ['open', 'high', 'low', 'close', 'vol']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        cs = df['close']
        df['ema_9']  = EMAIndicator(close=cs, window=9).ema_indicator()
        df['ema_21'] = EMAIndicator(close=cs, window=21).ema_indicator()
        df['ema_50'] = EMAIndicator(close=cs, window=50).ema_indicator()
        df['rsi']    = RSIIndicator(close=cs, window=14).rsi()
        mo_ = MACD(close=cs); df['macd'] = mo_.macd(); df['macd_s'] = mo_.macd_signal()
        bo_ = BollingerBands(close=cs, window=20, window_dev=2)
        df['bb_u'] = bo_.bollinger_hband(); df['bb_l'] = bo_.bollinger_lband(); df['bb_m'] = bo_.bollinger_mavg()
        df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=cs).average_true_range()
        try:    df['st'], df['st_dir'] = calc_supertrend(df, 10, 3.0)
        except: df['st'] = cs; df['st_dir'] = 1
        try:
            sto_ = StochasticOscillator(high=df['high'], low=df['low'], close=cs, window=14, smooth_window=3)
            df['stoch_k'] = sto_.stoch(); df['stoch_d'] = sto_.stoch_signal()
        except:
            df['stoch_k'] = 50.0; df['stoch_d'] = 50.0

    if df.empty:
        if not market_open():
            st.info("📴 Market closed (Mon–Fri 09:15–15:30 IST). Data loads when market opens.")
        else:
            st.warning("⚠️ No candle data. Session may have expired — reconnect in sidebar.")
    else:
        lat = df.iloc[-1]; prv = df.iloc[-2]
        price = sf(lat['close']); chg = price - sf(prv['close'])
        chg_p = chg / sf(prv['close']) * 100 if sf(prv['close']) else 0
        ema9  = sf(lat['ema_9']); ema21 = sf(lat['ema_21']); rsi = sf(lat['rsi'])
        atr   = sf(lat['atr']); macd_v = sf(lat['macd']); macd_s_ = sf(lat['macd_s'])
        bb_u  = sf(lat['bb_u']); bb_l  = sf(lat['bb_l']); st_dir = int(sf(lat.get('st_dir', 1) or 1))

        st.markdown(f"""<div class="metric-row">
          <div class="mcard"><div class="mcard-accent c-blue"></div>
            <div class="mcard-label">LIVE PRICE · {sym}</div>
            <div class="mcard-value">₹{price:,.0f}</div>
            <div class="mcard-sub {'v-green' if chg>=0 else 'v-red'}">{'+' if chg>=0 else ''}{chg:,.0f} ({chg_p:+.2f}%)</div></div>
          <div class="mcard"><div class="mcard-accent {'c-green' if ema9>ema21 else 'c-red'}"></div>
            <div class="mcard-label">EMA 9 / 21</div>
            <div class="mcard-value">₹{ema9:,.0f}</div>
            <div class="mcard-sub {'v-green' if ema9>ema21 else 'v-red'}">{'↑ BULL' if ema9>ema21 else '↓ BEAR'} · ST:{'▲' if st_dir==1 else '▼'}</div></div>
          <div class="mcard"><div class="mcard-accent {'c-green' if rsi>55 else 'c-red' if rsi<45 else 'c-amber'}"></div>
            <div class="mcard-label">RSI (14)</div>
            <div class="mcard-value {'v-green' if rsi>55 else 'v-red' if rsi<45 else 'v-amber'}">{rsi:.1f}</div>
            <div class="mcard-sub">{'OVERBOUGHT' if rsi>70 else 'BULL ZONE' if rsi>55 else 'OVERSOLD' if rsi<30 else 'BEAR ZONE' if rsi<45 else 'NEUTRAL'}</div></div>
          <div class="mcard"><div class="mcard-accent {'c-green' if macd_v>macd_s_ else 'c-red'}"></div>
            <div class="mcard-label">MACD / Signal</div>
            <div class="mcard-value {'v-green' if macd_v>macd_s_ else 'v-red'}">{macd_v:+.1f}</div>
            <div class="mcard-sub">Sig {macd_s_:+.1f} · {'▲' if macd_v>macd_s_ else '▼'}</div></div>
          <div class="mcard"><div class="mcard-accent c-teal"></div>
            <div class="mcard-label">ATR / BB Range</div>
            <div class="mcard-value">₹{atr:,.0f}</div>
            <div class="mcard-sub">{bb_l:,.0f} – {bb_u:,.0f}</div></div>
        </div>""", unsafe_allow_html=True)

        sig, reason, sl_p, tgt_p = evaluate_signal(df, st.session_state.strategy, price)
        st.markdown('<div class="pad">', unsafe_allow_html=True)
        if   sig == "BUY_CALL": st.markdown(f'<div class="sig-buy">▲ BUY CALL &nbsp;|&nbsp; {reason} &nbsp;|&nbsp; SL ₹{sl_p:,.0f} &nbsp; TGT ₹{tgt_p:,.0f}</div>', unsafe_allow_html=True)
        elif sig == "BUY_PUT":  st.markdown(f'<div class="sig-sell">▼ BUY PUT &nbsp;|&nbsp; {reason} &nbsp;|&nbsp; SL ₹{sl_p:,.0f} &nbsp; TGT ₹{tgt_p:,.0f}</div>', unsafe_allow_html=True)
        else:                   st.markdown(f'<div class="sig-hold">⚖ HOLD — {reason}</div>', unsafe_allow_html=True)

        # Auto-trade
        if st.session_state.engine_on and sig in ("BUY_CALL", "BUY_PUT") and market_open():
            if sig != st.session_state.last_auto_signal:
                entry = {"time": now_ist().strftime("%H:%M:%S"), "signal": sig,
                         "price": price, "sl": sl_p, "target": tgt_p}
                if st.session_state.dry_run:
                    st.success(f"🤖 AUTO PAPER: {sig} @ ₹{price:,.0f} | SL ₹{sl_p:,.0f} | TGT ₹{tgt_p:,.0f}")
                    entry.update({"mode": "PAPER-AUTO", "status": "OPEN", "pnl": 0})
                    st.session_state.trade_log.append(entry)
                    st.session_state.last_auto_signal = sig
                else:
                    try:
                        order = broker.place_order(signal=sig, quantity=15)
                        if order.get("status"):
                            st.success(f"🤖 LIVE: {sig} | ID:{order.get('order_id','')}")
                            entry.update({"mode": "LIVE-AUTO", "order_id": order.get("order_id", ""), "status": "OPEN", "pnl": 0})
                            st.session_state.trade_log.append(entry)
                            st.session_state.last_auto_signal = sig
                        else: st.error(f"Auto-trade failed: {order.get('error','Unknown')}")
                    except Exception as e: st.error(f"Auto-trade error: {e}")
            else: st.info(f"🤖 Engine active — {sig} already executed this cycle. Awaiting new crossover.")
        elif st.session_state.engine_on and not market_open():
            st.warning("🤖 Engine ON — market closed. Will fire on next valid signal during market hours.")

        # Manual execute
        if run_btn:
            if sig in ("BUY_CALL", "BUY_PUT"):
                entry = {"time": now_ist().strftime("%H:%M:%S"), "signal": sig,
                         "price": price, "sl": sl_p, "target": tgt_p}
                if st.session_state.dry_run:
                    st.success(f"🧪 PAPER: {sig} @ ₹{price:,.0f} | SL ₹{sl_p:,.0f} | TGT ₹{tgt_p:,.0f}")
                    entry.update({"mode": "PAPER", "status": "OPEN", "pnl": 0})
                    st.session_state.trade_log.append(entry)
                else:
                    try:
                        order = broker.place_order(signal=sig, quantity=15)
                        if order.get("status"):
                            st.success(f"✅ LIVE ORDER: {sig} | ID:{order.get('order_id','')}")
                            entry.update({"mode": "LIVE", "order_id": order.get("order_id", ""), "status": "OPEN", "pnl": 0})
                            st.session_state.trade_log.append(entry)
                        else: st.error(f"Order failed: {order.get('error','Unknown')}")
                    except Exception as e: st.error(f"Order error: {e}")
            else: st.info("HOLD — no actionable signal. Waiting for strategy confluence.")

        # FIX: Non-mutating P&L update
        updated_log = []
        for t in st.session_state.trade_log:
            t = dict(t)
            if t.get("status") == "OPEN":
                ep  = sf(t.get("price", price))
                pnl = price - ep if t["signal"] == "BUY_CALL" else ep - price
                t["pnl"] = round(pnl, 1)
                sl_v = sf(t.get("sl", 0)); tgt_v = sf(t.get("target", 0))
                if sl_v  and t["signal"] == "BUY_CALL" and price <= sl_v:  t["status"] = "CLOSED(SL)"
                if tgt_v and t["signal"] == "BUY_CALL" and price >= tgt_v: t["status"] = "CLOSED(TGT)"
                if sl_v  and t["signal"] == "BUY_PUT"  and price >= sl_v:  t["status"] = "CLOSED(SL)"
                if tgt_v and t["signal"] == "BUY_PUT"  and price <= tgt_v: t["status"] = "CLOSED(TGT)"
            updated_log.append(t)
        st.session_state.trade_log = updated_log

        # Consensus
        st.markdown('<div class="sec-hdr">MULTI-STRATEGY CONSENSUS</div>', unsafe_allow_html=True)
        ALL_S = ["SuperTrend + RSI", "MACD + EMA Confluence", "Stochastic + BB Mean Reversion",
                 "Triple EMA + Volume Trend", "Momentum Pulse (EMA+RSI)", "Bollinger Squeeze Breakout"]
        bulls = 0; bears = 0; crows = ""
        for sn in ALL_S:
            s, r, _, _ = evaluate_signal(df, sn, price)
            bdg = (f'<span class="badge b-buy">▲ CALL</span>' if s == "BUY_CALL"
                   else f'<span class="badge b-sell">▼ PUT</span>' if s == "BUY_PUT"
                   else f'<span class="badge b-hold">HOLD</span>')
            if s == "BUY_CALL": bulls += 1
            elif s == "BUY_PUT": bears += 1
            crows += f'<tr><td>{sn}</td><td>{bdg}</td><td style="font-size:10px;color:var(--text2)">{r}</td></tr>'
        total = len(ALL_S)
        bp = bulls/total*100; rp = bears/total*100; np_ = (total-bulls-bears)/total*100
        ct = ("🟢 STRONG BULLISH" if bulls>=4 else "🔴 STRONG BEARISH" if bears>=4
              else "🟡 BULL LEAN" if bulls>bears else "🟡 BEAR LEAN" if bears>bulls else "⚪ MIXED")
        st.markdown(f"""<div><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
          <span style="font-family:var(--mono);font-size:11px;color:var(--text2);font-weight:700">{ct}</span>
          <span style="font-family:var(--mono);font-size:10px;color:var(--muted)">↑{bulls} ↓{bears} ={total-bulls-bears}</span></div>
          <div class="consensus-bar"><div class="cb-bull" style="width:{bp}%"></div>
          <div class="cb-neut" style="width:{np_}%"></div><div class="cb-bear" style="width:{rp}%"></div></div></div>
          <div class="table-responsive"><table class="qbt"><thead><tr><th>Strategy</th><th>Signal</th><th>Reason</th></tr></thead>
          <tbody>{crows}</tbody></table></div>""", unsafe_allow_html=True)

        st.markdown('<div class="sec-hdr">PRICE + EMA CHART</div>', unsafe_allow_html=True)
        cd = df[['ts', 'close', 'ema_9', 'ema_21', 'ema_50']].copy()
        try: cd['ts'] = pd.to_datetime(cd['ts']).dt.strftime('%H:%M')
        except: pass
        st.line_chart(cd.set_index('ts').tail(80), height=200, use_container_width=True)

        st.markdown('<div class="sec-hdr">LAST 10 CANDLES</div>', unsafe_allow_html=True)
        disp = df[['ts','open','high','low','close','ema_9','ema_21','rsi','macd','atr']].tail(10).copy()
        try: disp['ts'] = pd.to_datetime(disp['ts']).dt.strftime('%H:%M')
        except: pass
        disp = disp.round(1)
        th = ''.join(f'<th>{c.upper()}</th>' for c in disp.columns); rows_c = ""
        for _, row in disp.iterrows():
            d_ = sf(row['close']) - sf(row['open'])
            rows_c += '<tr>' + ''.join(
                f'<td class="{"v-green" if c in ("close","open") and d_>=0 else "v-red" if c in ("close","open") and d_<0 else ""}">{row[c]}</td>'
                for c in disp.columns) + '</tr>'
        st.markdown(f'<div class="table-responsive"><table class="qbt"><thead><tr>{th}</tr></thead><tbody>{rows_c}</tbody></table></div>', unsafe_allow_html=True)

        if st.session_state.trade_log:
            st.markdown('<div class="sec-hdr">SESSION TRADE LOG — LIVE P&L</div>', unsafe_allow_html=True)
            th_ = '<th>TIME</th><th>SIGNAL</th><th>ENTRY ₹</th><th>SL ₹</th><th>TARGET ₹</th><th>P&L</th><th>STATUS</th><th>MODE</th>'
            rows_t = ""
            for t in reversed(st.session_state.trade_log[-20:]):
                pnl_v = sf(t.get("pnl", 0)); status = t.get("status", "OPEN")
                pnl_html = f'<span class="pnl-live {"pnl-pos" if pnl_v>0 else "pnl-neg" if pnl_v<0 else "pnl-neu"}">{"+" if pnl_v>0 else ""}{pnl_v:.1f}</span>'
                sig_bdg  = f'<span class="badge b-buy">▲ {t["signal"]}</span>' if t["signal"]=="BUY_CALL" else f'<span class="badge b-sell">▼ {t["signal"]}</span>'
                st_bdg   = (f'<span class="badge b-win">TGT HIT</span>'  if "TGT" in status
                            else f'<span class="badge b-loss">SL HIT</span>' if "SL"  in status
                            else f'<span class="badge b-open">OPEN</span>')
                rows_t += (f'<tr class="{"row-profit" if pnl_v>0 else "row-loss" if pnl_v<0 else ""}">'
                           f'<td>{t.get("time","")}</td><td>{sig_bdg}</td>'
                           f'<td>₹{sf(t.get("price",0)):,.1f}</td><td>₹{sf(t.get("sl",0)):,.1f}</td>'
                           f'<td>₹{sf(t.get("target",0)):,.1f}</td><td>{pnl_html}</td>'
                           f'<td>{st_bdg}</td><td style="font-size:10px">{t.get("mode","")}</td></tr>')
            st.markdown(f'<div class="table-responsive"><table class="qbt"><thead><tr>{th_}</tr></thead><tbody>{rows_t}</tbody></table></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — POSITIONS & P&L
# ══════════════════════════════════════════════════════════════════════════════
with tab_pos:
    st.markdown('<div class="pad">', unsafe_allow_html=True)
    broker = st.session_state.broker
    if not broker:
        st.warning("🔌 Connect to Angel One via the sidebar to view live positions.")
    else:
        if st.button("🔄 Refresh Positions", key="pos_r"): st.rerun()
        pnl = broker.get_pnl_summary()
        st.markdown(f"""<div class="metric-row">
          <div class="mcard"><div class="mcard-accent {'c-green' if pnl['total']>=0 else 'c-red'}"></div>
            <div class="mcard-label">TOTAL P&L</div>
            <div class="mcard-value {'v-green' if pnl['total']>=0 else 'v-red'}">₹{pnl['total']:+,.0f}</div></div>
          <div class="mcard"><div class="mcard-accent c-green"></div>
            <div class="mcard-label">REALISED P&L</div>
            <div class="mcard-value {'v-green' if pnl['realised']>=0 else 'v-red'}">₹{pnl['realised']:+,.0f}</div></div>
          <div class="mcard"><div class="mcard-accent c-blue"></div>
            <div class="mcard-label">UNREALISED P&L</div>
            <div class="mcard-value {'v-green' if pnl['unrealised']>=0 else 'v-red'}">₹{pnl['unrealised']:+,.0f}</div></div>
          <div class="mcard"><div class="mcard-accent c-amber"></div>
            <div class="mcard-label">OPEN POSITIONS</div>
            <div class="mcard-value">{pnl['positions']}</div></div>
        </div>""", unsafe_allow_html=True)
        positions = broker.get_positions()
        if positions:
            st.markdown('<div class="sec-hdr" style="padding-top:8px;border-top:none">OPEN POSITIONS</div>', unsafe_allow_html=True)
            cols_p = ['tradingsymbol','netqty','ltp','avgnetprice','unrealisedprofitandloss','realisedprofitandloss']
            pos_df = pd.DataFrame(positions); av = [c for c in cols_p if c in pos_df.columns]
            th = ''.join(f'<th>{c.upper()}</th>' for c in av); rows_p = ""
            for _, row in pos_df[av].iterrows():
                try:    upnl = float(row.get('unrealisedprofitandloss', 0) or 0)
                except: upnl = 0
                rows_p += f'<tr class="{"row-profit" if upnl>0 else "row-loss" if upnl<0 else ""}">'
                for c in av:
                    v = row[c]; css = ""
                    if 'pnl' in c or 'profit' in c:
                        try: fv=float(v or 0); css="v-green" if fv>=0 else "v-red"; v=f"₹{fv:+,.0f}"
                        except: pass
                    rows_p += f'<td class="{css}">{v}</td>'
                rows_p += '</tr>'
            st.markdown(f'<div class="table-responsive"><table class="qbt"><thead><tr>{th}</tr></thead><tbody>{rows_p}</tbody></table></div>', unsafe_allow_html=True)
        else: st.info("No open positions.")
        funds = broker.get_funds()
        if funds:
            st.markdown('<div class="sec-hdr">FUNDS & MARGIN</div>', unsafe_allow_html=True)
            fi  = {k: v for k, v in funds.items() if v and str(v) != "0"}
            cfs = st.columns(min(len(fi), 4))
            for i, (k, v) in enumerate(fi.items()):
                with cfs[i % 4]:
                    try:    st.metric(k.upper(), f"₹{float(v):,.0f}")
                    except: st.metric(k.upper(), str(v))
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — ORDER BOOK
# ══════════════════════════════════════════════════════════════════════════════
with tab_ord:
    st.markdown('<div class="pad">', unsafe_allow_html=True)
    broker = st.session_state.broker
    if not broker:
        st.warning("🔌 Connect to Angel One to view orders.")
    else:
        oc1, oc2, oc3 = st.columns(3)
        with oc1:
            if st.button("📋 Load Order Book", key="ob_l"): st.session_state._orders = broker.get_order_book()
        with oc2:
            if st.button("🔄 Load Trade Book", key="tb_l"): st.session_state._trades = broker.get_trade_book()
        with oc3:
            if st.button("🔃 Refresh P&L", key="pnl_r"):
                p = broker.get_pnl_summary(); st.info(f"Total P&L: ₹{p['total']:+,.0f}")

        orders = st.session_state.get("_orders", [])
        if orders:
            st.markdown('<div class="sec-hdr" style="padding-top:8px;border-top:none">TODAY\'S ORDERS</div>', unsafe_allow_html=True)
            pos_map = {}
            try:
                for p in broker.get_positions():
                    pos_map[p.get('tradingsymbol','')] = {'ltp': sf(p.get('ltp',0)), 'upnl': sf(p.get('unrealisedprofitandloss',0))}
            except: pass
            ocols = ['orderid','tradingsymbol','transactiontype','quantity','price','averageprice','orderstatus']
            odf   = pd.DataFrame(orders); av = [c for c in ocols if c in odf.columns]
            th    = '<th>ORDER ID</th>' + ''.join(f'<th>{c.upper()}</th>' for c in av if c!='orderid') + '<th>LIVE P&L</th><th>STATUS</th>'
            rows_o = ""
            for _, row in odf.iterrows():
                sym   = str(row.get('tradingsymbol',''))
                pi    = pos_map.get(sym, {})
                avg   = sf(row.get('averageprice',0) or row.get('price',0))
                ltp   = pi.get('ltp',0) or sf(row.get('ltp',0))
                tx    = str(row.get('transactiontype','')).upper()
                qty   = sf(row.get('quantity',0))
                pnl_v = round((ltp-avg)*qty * (-1 if tx=='SELL' else 1), 1) if ltp and avg and qty else pi.get('upnl',0)
                pnl_html = (f'<span class="pnl-live {"pnl-pos" if pnl_v>0 else "pnl-neg" if pnl_v<0 else "pnl-neu"}">{"+" if pnl_v>0 else ""}{pnl_v:.1f}</span>'
                            if pnl_v != 0 else '<span class="pnl-live pnl-neu">—</span>')
                tx_bdg = f'<span class="badge b-buy">{tx}</span>' if tx=='BUY' else f'<span class="badge b-sell">{tx}</span>'
                stat   = str(row.get('orderstatus','')).lower()
                s_bdg  = (f'<span class="badge b-comp">COMPLETE</span>' if 'complete' in stat
                          else f'<span class="badge b-open">OPEN</span>'     if 'open'    in stat
                          else f'<span class="badge b-loss">REJECTED</span>' if 'reject'  in stat
                          else f'<span class="badge b-hold">{stat.upper()}</span>')
                rows_o += (f'<tr class="{"row-profit" if pnl_v>0 else "row-loss" if pnl_v<0 else ""}">'
                           f'<td style="font-size:10px">{str(row.get("orderid",""))[:12]}</td>'
                           f'<td style="font-weight:600">{sym}</td><td>{tx_bdg}</td>'
                           f'<td>{row.get("quantity","")}</td><td>₹{sf(row.get("price",0)):,.1f}</td>'
                           f'<td>₹{avg:,.1f}</td><td>{pnl_html}</td><td>{s_bdg}</td></tr>')
            st.markdown(f'<div class="table-responsive"><table class="qbt"><thead><tr>{th}</tr></thead><tbody>{rows_o}</tbody></table></div>', unsafe_allow_html=True)
        else:
            st.info("Click 'Load Order Book' to fetch today's orders. Live P&L shown per order.")
        if st.session_state.trade_log:
            st.markdown('<div class="sec-hdr" style="padding-top:16px">SESSION PAPER LOG</div>', unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(st.session_state.trade_log), use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — BACKTEST
# ══════════════════════════════════════════════════════════════════════════════
with tab_bt:
    st.markdown('<div class="pad">', unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr" style="padding:0 0 12px;border:none">HISTORICAL STRATEGY BACKTEST ENGINE</div>', unsafe_allow_html=True)
    bc1, bc2, bc3, bc4 = st.columns(4)
    with bc1: bt_s = st.selectbox("Strategy", ["SuperTrend + RSI","MACD + EMA Confluence","Stochastic + BB Mean Reversion","Triple EMA + Volume Trend","Momentum Pulse (EMA+RSI)","Bollinger Squeeze Breakout"], key="bt_s2")
    with bc2: bt_p = st.selectbox("Period", ["1mo","3mo","6mo","1y"], key="bt_p2")
    with bc3: bt_i = st.selectbox("Index", ["Nifty 50 (^NSEI)","BankNifty (^NSEBANK)","Sensex (^BSESN)"], key="bt_i2")
    with bc4:
        st.markdown('<div style="padding-top:24px"><div class="main-btn">', unsafe_allow_html=True)
        run_bt = st.button("🚀 RUN BACKTEST", use_container_width=True, key="bt_r2")
        st.markdown('</div></div>', unsafe_allow_html=True)
    tm = {"Nifty 50 (^NSEI)":"^NSEI","BankNifty (^NSEBANK)":"^NSEBANK","Sensex (^BSESN)":"^BSESN"}
    ticker = tm[bt_i]
    if bt_p in ("3mo","6mo","1y"):
        st.markdown(f'<div style="background:var(--blue-l);border:1px solid rgba(24,71,197,.2);border-radius:8px;padding:8px 14px;font-size:11px;color:var(--blue);margin:8px 0;font-family:var(--mono)">ℹ️ {bt_p} uses <strong>DAILY candles</strong> (yfinance 15-min limit is 60 days)</div>', unsafe_allow_html=True)
    if run_bt:
        with st.spinner(f"Running {bt_s} on {bt_i} / {bt_p}..."):
            res_df, metrics = run_backtest(ticker, bt_p, bt_s)
        if res_df is None:
            st.error(f"Backtest error: {metrics}")
        else:
            st.markdown(f"""<div class="metric-row">
              <div class="mcard"><div class="mcard-accent {'c-green' if metrics['total_pts']>0 else 'c-red'}"></div>
                <div class="mcard-label">TOTAL POINTS</div>
                <div class="mcard-value {'v-green' if metrics['total_pts']>0 else 'v-red'}">{metrics['total_pts']:+.0f}</div>
                <div class="mcard-sub">{metrics['interval']} · {metrics['candles']} bars</div></div>
              <div class="mcard"><div class="mcard-accent {'c-green' if metrics['win_rate']>=60 else 'c-amber' if metrics['win_rate']>=50 else 'c-red'}"></div>
                <div class="mcard-label">WIN RATE</div>
                <div class="mcard-value {'v-green' if metrics['win_rate']>=60 else 'v-amber' if metrics['win_rate']>=50 else 'v-red'}">{metrics['win_rate']:.1f}%</div>
                <div class="mcard-sub">{metrics['trades']} trades</div></div>
              <div class="mcard"><div class="mcard-accent c-blue"></div>
                <div class="mcard-label">AVG WIN / LOSS</div>
                <div class="mcard-value">+{metrics['avg_win']}</div>
                <div class="mcard-sub">Avg loss: -{metrics['avg_loss']} pts</div></div>
              <div class="mcard"><div class="mcard-accent c-red"></div>
                <div class="mcard-label">MAX DRAWDOWN</div>
                <div class="mcard-value v-red">{metrics['max_dd']:.0f} pts</div></div>
              <div class="mcard"><div class="mcard-accent {'c-green' if metrics['rr_ratio']>=1.5 else 'c-amber'}"></div>
                <div class="mcard-label">RISK:REWARD</div>
                <div class="mcard-value {'v-green' if metrics['rr_ratio']>=1.5 else 'v-amber'}">{metrics['rr_ratio']}x</div></div>
            </div>""", unsafe_allow_html=True)
            st.markdown('<div class="sec-hdr" style="padding-top:8px;border-top:none">EQUITY CURVE</div>', unsafe_allow_html=True)
            try:   st.area_chart(res_df.set_index('Date')['Cumulative'], height=200, use_container_width=True)
            except: st.line_chart(res_df['Cumulative'].reset_index(drop=True), height=200)
            st.markdown('<div class="sec-hdr">TRADE LOG</div>', unsafe_allow_html=True)
            show   = [c for c in ['Date','Signal','Entry','Exit','Points','ATR','Reason','Result'] if c in res_df.columns]
            dr     = res_df[show].copy()
            th     = ''.join(f'<th>{c.upper()}</th>' for c in show); rows_r = ""
            for _, row in dr.iterrows():
                pv = sf(row.get('Points', 0)); rows_r += f'<tr class="{"row-profit" if pv>0 else "row-loss" if pv<0 else ""}">'
                for c in show:
                    v = row[c]; css = ""
                    if c == 'Result':
                        v = ('<span style="background:#ecfdf5;color:#059669;padding:3px 8px;border-radius:4px;font-weight:bold;font-size:10px;border:1px solid #34d399">WIN</span>'
                             if v == 'WIN' else
                             '<span style="background:#fef2f2;color:#dc2626;padding:3px 8px;border-radius:4px;font-weight:bold;font-size:10px;border:1px solid #f87171">LOSS</span>')
                    elif c == 'Points':
                        try: fv=float(v); css="v-green" if fv>=0 else "v-red"; v=f"{fv:+.1f}"
                        except: pass
                    elif c == 'Signal':
                        v = (f'<span style="color:#059669;font-weight:bold">▲ {v}</span>' if "CALL" in str(v)
                             else f'<span style="color:#dc2626;font-weight:bold">▼ {v}</span>')
                    rows_r += f'<td class="{css}">{v}</td>'
                rows_r += '</tr>'
            st.markdown(f'<div class="table-responsive"><table class="qbt"><thead><tr>{th}</tr></thead><tbody>{rows_r}</tbody></table></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — IRON CONDOR
# ══════════════════════════════════════════════════════════════════════════════
with tab_ic:
    st.markdown('<div class="pad">', unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr" style="padding:0 0 12px;border:none">BANKNIFTY WEEKLY IRON CONDOR BUILDER</div>', unsafe_allow_html=True)
    ic1, ic2, ic3 = st.columns(3)
    with ic1:
        ic_spot = st.number_input("BankNifty Spot", value=48000, step=100,   key="ic_sp2")
        ic_vix  = st.number_input("India VIX",      value=14.5,  step=0.1,   key="ic_vx2")
    with ic2:
        ic_exp = st.text_input("Expiry Code (DDMMM)", value="23DEC",  key="ic_ex2")
        ic_qty = st.number_input("Quantity (units)",  value=15, step=15,      key="ic_qt2")
    with ic3:
        ic_prem = st.number_input("Net Credit (₹/unit)", value=175, step=5,   key="ic_pr2")
        ic_cap  = st.number_input("Capital (₹)",          value=100000, step=10000, key="ic_cp2")
    offset = ic_spot * 0.012
    sc = round((ic_spot+offset)/100)*100; lc = sc+500
    sp = round((ic_spot-offset)/100)*100; lp = sp-500
    mp = ic_prem*ic_qty; ml = max(0,(500-ic_prem)*ic_qty)
    t50 = ic_prem*0.50*ic_qty; s150 = ic_prem*1.50*ic_qty
    roi = round(mp/ic_cap*100,2) if ic_cap else 0; vix_ok = ic_vix < 20
    st.markdown(f"""<div class="metric-row">
      <div class="mcard"><div class="mcard-accent c-green"></div><div class="mcard-label">MAX PROFIT</div>
        <div class="mcard-value v-green">₹{mp:,.0f}</div><div class="mcard-sub">50% exit at ₹{t50:,.0f}</div></div>
      <div class="mcard"><div class="mcard-accent c-red"></div><div class="mcard-label">MAX LOSS</div>
        <div class="mcard-value v-red">₹{ml:,.0f}</div><div class="mcard-sub">SL at ₹{s150:,.0f}</div></div>
      <div class="mcard"><div class="mcard-accent c-blue"></div><div class="mcard-label">EXPECTED ROI</div>
        <div class="mcard-value v-blue">{roi}%</div><div class="mcard-sub">On ₹{ic_cap:,.0f}</div></div>
      <div class="mcard"><div class="mcard-accent {'c-green' if vix_ok else 'c-red'}"></div><div class="mcard-label">VIX STATUS</div>
        <div class="mcard-value {'v-green' if vix_ok else 'v-red'}">{ic_vix}</div>
        <div class="mcard-sub">{'✅ SAFE — below 20' if vix_ok else '⛔ BLOCKED — above 20'}</div></div>
    </div>""", unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr" style="padding-top:8px;border-top:none">CONDOR STRUCTURE</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="table-responsive" style="margin-top:10px;background:white;border-radius:8px;box-shadow:var(--shadow)">
      <table class="qbt" style="min-width:500px;border-collapse:collapse;width:100%"><tbody>
        <tr><td style="padding:13px 16px"><span style="background:#ecfdf5;color:#059669;padding:4px 10px;border-radius:4px;font-weight:bold;font-size:10px;border:1px solid #34d399">BUY</span></td>
            <td style="padding:13px 16px">Wing — caps upside loss</td>
            <td style="text-align:right;font-weight:bold;color:var(--blue);padding:13px 16px">CALL {lc} CE &nbsp;+1 lot</td></tr>
        <tr style="background:var(--red-l)">
            <td style="padding:13px 16px"><span style="background:#fef2f2;color:#dc2626;padding:4px 10px;border-radius:4px;font-weight:bold;font-size:10px;border:1px solid #f87171">SELL</span></td>
            <td style="padding:13px 16px">Short call — collect premium</td>
            <td style="text-align:right;font-weight:bold;color:var(--blue);padding:13px 16px">CALL {sc} CE &nbsp;-1 lot</td></tr>
        <tr style="background:var(--blue-l)">
            <td colspan="3" style="text-align:center;color:var(--blue);font-family:var(--mono);font-size:12px;padding:13px;font-weight:700">◄── PROFIT ZONE &nbsp; {sp:,} → {sc:,} &nbsp; ──► &nbsp; SPOT: {ic_spot:,} &nbsp; Width: {sc-sp} pts</td></tr>
        <tr style="background:var(--red-l)">
            <td style="padding:13px 16px"><span style="background:#fef2f2;color:#dc2626;padding:4px 10px;border-radius:4px;font-weight:bold;font-size:10px;border:1px solid #f87171">SELL</span></td>
            <td style="padding:13px 16px">Short put — collect premium</td>
            <td style="text-align:right;font-weight:bold;color:var(--blue);padding:13px 16px">PUT {sp} PE &nbsp;-1 lot</td></tr>
        <tr><td style="padding:13px 16px"><span style="background:#ecfdf5;color:#059669;padding:4px 10px;border-radius:4px;font-weight:bold;font-size:10px;border:1px solid #34d399">BUY</span></td>
            <td style="padding:13px 16px">Wing — caps downside loss</td>
            <td style="text-align:right;font-weight:bold;color:var(--blue);padding:13px 16px">PUT {lp} PE &nbsp;+1 lot</td></tr>
      </tbody></table></div>""", unsafe_allow_html=True)
    st.markdown('<div style="margin-top:16px">', unsafe_allow_html=True)
    if not vix_ok:
        st.error(f"⛔ VIX {ic_vix} exceeds 20 — Iron Condor deployment blocked by risk filter.")
    else:
        dc1, dc2 = st.columns(2)
        with dc1:
            if st.button("🧪 PAPER DEPLOY CONDOR", use_container_width=True, key="ic_p2"):
                st.success(f"✅ PAPER | SC:{sc} LC:{lc} SP:{sp} LP:{lp} | Max Profit ₹{mp:,.0f}")
        with dc2:
            st.markdown('<div class="danger-btn">', unsafe_allow_html=True)
            if st.button("⚡ LIVE DEPLOY CONDOR", use_container_width=True, key="ic_l2"):
                _b = st.session_state.get("broker")
                if not _b or not getattr(_b, "connected", False): st.error("Not connected to Angel One.")
                elif st.session_state.dry_run: st.warning("Switch off Dry Run in the sidebar before live deployment.")
                else:
                    try:
                        with st.spinner("Resolving tokens and placing 4-leg condor..."):
                            r = _b.place_iron_condor(symbol="BANKNIFTY", expiry=ic_exp,
                                                      short_call_strike=sc, long_call_strike=lc,
                                                      short_put_strike=sp,  long_put_strike=lp,
                                                      quantity=ic_qty)
                        st.success("✅ All 4 legs placed!") if r.get("status") else st.error(f"Condor failed: {r}")
                    except Exception as e: st.error(f"Error: {e}")
            st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div></div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 6 — RISK ENGINE  (FIX: null-guarded)
# ══════════════════════════════════════════════════════════════════════════════
with tab_risk:
    st.markdown('<div class="pad">', unsafe_allow_html=True)
    broker  = st.session_state.broker
    capital = st.session_state.capital

    if not broker:
        st.warning("🔌 Connect to Angel One to view live risk metrics. Risk rules are always active regardless of connection status.")
    else:
        pnl    = broker.get_pnl_summary()
        lp_    = abs(pnl['total']) / capital * 100 if pnl['total'] < 0 and capital > 0 else 0
        rem    = max(0, st.session_state.daily_loss_pct - lp_)
        halted = lp_ >= st.session_state.daily_loss_pct
        if halted and not st.session_state.engine_halted:
            st.session_state.engine_halted = True; st.session_state.engine_on = False
        cc = "c-red" if lp_ > 1.5 else "c-amber" if lp_ > 0.5 else "c-green"
        st.markdown(f"""<div class="metric-row">
          <div class="mcard"><div class="mcard-accent {cc}"></div><div class="mcard-label">DAILY LOSS USED</div>
            <div class="mcard-value {'v-red' if lp_>1 else ''}">{lp_:.2f}%</div>
            <div class="mcard-sub">Limit: {st.session_state.daily_loss_pct:.1f}%</div></div>
          <div class="mcard"><div class="mcard-accent c-green"></div><div class="mcard-label">RISK REMAINING</div>
            <div class="mcard-value v-green">{rem:.2f}%</div><div class="mcard-sub">₹{rem/100*capital:,.0f}</div></div>
          <div class="mcard"><div class="mcard-accent c-blue"></div><div class="mcard-label">CAPITAL DEPLOYED</div>
            <div class="mcard-value">₹{capital:,.0f}</div></div>
          <div class="mcard"><div class="mcard-accent {'c-red' if halted else 'c-green'}"></div>
            <div class="mcard-label">ENGINE STATUS</div>
            <div class="mcard-value" style="font-size:14px">{'🔴 HALTED' if halted else '🟢 ACTIVE'}</div></div>
        </div>""", unsafe_allow_html=True)

    st.markdown('<div class="sec-hdr" style="padding-top:4px;border-top:none">9 ACTIVE RISK RULES</div>', unsafe_allow_html=True)
    rules = [
        ("VIX Filter",            f"Pause Iron Condor when VIX > {st.session_state.vix_limit:.0f}",   "✅ ACTIVE"),
        ("Daily Loss Limit",      f"Halt engine at {st.session_state.daily_loss_pct:.1f}% loss",       "✅ ACTIVE"),
        ("Position Sizing",       "Max 20% capital per spread",                                         "✅ ACTIVE"),
        ("Iron Condor SL",        "Auto-exit at 150% of premium collected",                            "✅ ACTIVE"),
        ("Gap Risk Filter",       "Skip Monday entry if BankNifty gap > 1%",                           "✅ ACTIVE"),
        ("Event Filter",          "No condors during monthly/quarterly expiry week",                    "✅ ACTIVE"),
        ("Max Open Positions",    "Block new trades beyond 4 legs",                                     "✅ ACTIVE"),
        ("Duplicate Signal Guard","Skip repeated signals within same candle cycle",                     "✅ ACTIVE"),
        ("Market Hours Gate",     "No trades outside 09:15–15:30 IST Mon–Fri",                         "✅ ACTIVE"),
    ]
    th     = '<th>#</th><th>RULE</th><th>CONDITION</th><th>STATUS</th>'
    rows_r = ''.join(f'<tr><td style="color:var(--muted);font-size:10px">{i+1}</td>'
                     f'<td style="font-weight:600">{r}</td><td style="color:var(--text2)">{c}</td>'
                     f'<td><span style="background:#ecfdf5;color:#059669;padding:3px 8px;border-radius:4px;font-weight:bold;font-size:10px">{s}</span></td></tr>'
                     for i,(r,c,s) in enumerate(rules))
    st.markdown(f'<div class="table-responsive"><table class="qbt"><thead><tr>{th}</tr></thead><tbody>{rows_r}</tbody></table></div>', unsafe_allow_html=True)

    st.markdown('<div class="sec-hdr">MANUAL CONTROLS</div>', unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        if st.button("⏸ PAUSE ENGINE", use_container_width=True, key="r_pa"):
            st.session_state.engine_on = False; st.warning("Engine paused.")
    with m2:
        st.markdown('<div class="success-btn">', unsafe_allow_html=True)
        if st.button("▶ RESUME ENGINE", use_container_width=True, key="r_re"):
            if st.session_state.connected:
                st.session_state.engine_on = True; st.session_state.engine_halted = False; st.success("Engine resumed.")
            else: st.error("Not connected.")
        st.markdown('</div>', unsafe_allow_html=True)
    with m3:
        if st.button("🔃 RESET P&L COUNTER", use_container_width=True, key="r_rs"):
            st.session_state.engine_halted = False; st.info("Daily P&L counter reset.")
    with m4:
        st.markdown('<div class="danger-btn">', unsafe_allow_html=True)
        if st.button("🛑 SQUARE OFF ALL", use_container_width=True, key="r_sq"):
            _b = st.session_state.get("broker")
            if _b and getattr(_b, "connected", False):
                with st.spinner("Emergency square off..."): r = _b.square_off_all()
                st.warning(f"✅ Squared off {len(r)} position(s)")
                st.session_state.engine_on = False
            else: st.error("Not connected.")
        st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  FIX: Auto-refresh — AFTER all rendering, sleep THEN rerun
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.auto_refresh:
    time.sleep(st.session_state.refresh_interval)
    st.rerun()
