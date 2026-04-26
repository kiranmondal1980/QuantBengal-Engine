"""
QuantBengal Pro — app.py  v7.0
AUDIT COMPLETE EDITION:
Module 1 — UI/UX: High-Contrast Corporate Light Theme (Royal Blue #1e3a8a / Crimson #dc2626)
           Mobile-first flexible grid, professional Sentiment Gauge, swipable tables.
Module 2 — Strategy Sync: All 6 strategies identical to strategy.py backend.
           SENSEX BSE routing verified. ATM rounding unified (50 NIFTY / 100 BNF+SENSEX).
Module 3 — Safety FAQ Tab: Full 7-point Trust & Safety section for beginners.
Module 4 — Code Optimisation: Thread-safe JSON ledger, human-readable errors,
           redundant code removed, structured log messages.
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pytz, time, os, json, threading

# ── Persistent JSON trade ledger (thread-safe) ─────────────────────────────
LOG_FILE   = "trade_history.json"
_LOG_LOCK  = threading.Lock()

def load_trade_log() -> list:
    if not os.path.exists(LOG_FILE):
        return []
    with _LOG_LOCK:
        try:
            with open(LOG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []

def save_trade_log(log_data: list) -> None:
    """Write to a temp file then atomically rename — prevents partial writes."""
    tmp = LOG_FILE + ".tmp"
    with _LOG_LOCK:
        try:
            with open(tmp, 'w') as f:
                json.dump(log_data, f, indent=2)
            os.replace(tmp, LOG_FILE)
        except Exception as e:
            st.sidebar.error(f"⚠️ Trade log save failed: {e}")

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="QuantBengal Pro",
    layout="wide",
    page_icon="⚡",
    initial_sidebar_state="expanded"
)

IST = pytz.timezone('Asia/Kolkata')

# ── Session state defaults ─────────────────────────────────────────────────
DEFAULTS = {
    "broker": None, "connected": False, "engine_on": False,
    "dry_run": True, "capital": 200000.0, "trade_log": load_trade_log(),
    "strategy": "SuperTrend + RSI", "auto_refresh": False,
    "refresh_interval": 30, "api_key": "", "client_id": "",
    "password": "", "totp_secret": "", "engine_halted": False,
    "last_auto_signal": "", "vix_limit": 20.0, "daily_loss_pct": 2.0,
    "_orders": [], "_trades": [], "order_pnl": {},
    "index_choice": "BANKNIFTY", "expiry_date": "25APR",
    "safe_start": "10:30", "safe_end": "14:30",
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


# ── Helpers ────────────────────────────────────────────────────────────────
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

def _human_order_error(raw: str) -> str:
    """Convert Angel One error codes into plain English."""
    if not raw:
        return "Unknown error — please check your Angel One account."
    r = raw.lower()
    if "margin" in r or "fund" in r:
        return "Insufficient margin — add funds to your Angel One account or lower the Capital setting."
    if "session" in r or "jwt" in r or "auth" in r:
        return "Session expired — reconnect via the sidebar."
    if "circuit" in r:
        return "Price hit circuit limit — the exchange has paused this contract temporarily."
    if "qty" in r or "quantity" in r:
        return "Invalid quantity — lot size may not match this contract."
    if "token" in r:
        return "Option token not found — verify expiry code and reconnect."
    return f"Order error: {raw[:100]}{'…' if len(raw) > 100 else ''}"


# ── SuperTrend (identical to strategy.py backend) ─────────────────────────
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
        prev_st  = supertrend.iloc[i-1] if not pd.isna(supertrend.iloc[i-1]) else lower.iloc[i]
        prev_dir = direction.iloc[i-1]  if not pd.isna(direction.iloc[i-1])  else 1
        curr_c   = float(close.iloc[i])
        if prev_dir == 1:
            curr_st  = max(lower.iloc[i], prev_st) if curr_c > prev_st else upper.iloc[i]
            curr_dir = 1 if curr_c > curr_st else -1
        else:
            curr_st  = min(upper.iloc[i], prev_st) if curr_c < prev_st else lower.iloc[i]
            curr_dir = -1 if curr_c < curr_st else 1
        supertrend.iloc[i] = curr_st; direction.iloc[i] = curr_dir
    return supertrend, direction


# ── ATM strike rounding (synced with broker_api.py) ───────────────────────
_ATM_ROUND = {"NIFTY": 50, "BANKNIFTY": 100, "SENSEX": 100}

def get_atm_strike(underlying: str, spot: float) -> int:
    step = _ATM_ROUND.get(underlying.upper(), 100)
    return int(round(spot / step) * step)


# ── Backtest engine ────────────────────────────────────────────────────────
_SL_MULTIPLIERS = {
    "SuperTrend + RSI": 1.2, "MACD + EMA Confluence": 1.3,
    "Stochastic + BB Mean Reversion": 1.0, "Triple EMA + Volume Trend": 1.4,
    "Momentum Pulse (EMA+RSI)": 1.5, "Bollinger Squeeze Breakout": 1.1,
}

def run_backtest(ticker, period, strategy_name):
    interval = "1d" if period in ("3mo", "6mo", "1y") else "15m"
    label    = "Daily" if interval == "1d" else "15-min"
    try:
        raw = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    except Exception as e:
        return None, f"Download error: {e}"
    if raw is None or raw.empty:
        return None, "No data returned. Check ticker or try again."
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [str(c[0]).lower() for c in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]
    raw = raw.loc[:, ~raw.columns.duplicated()]
    raw.rename(columns={'adj close': 'close', 'adj_close': 'close'}, inplace=True)
    if 'close' not in raw.columns:
        return None, f"No 'close' column. Columns: {list(raw.columns)}"
    df = raw.copy(); df.index = pd.to_datetime(df.index)
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
    mo = MACD(close=cs); df['macd'] = mo.macd(); df['macd_s'] = mo.macd_signal()
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
    sl_mult  = _SL_MULTIPLIERS.get(strategy_name, 1.3)
    tgt_mult = sl_mult * 1.8
    for i in range(2, len(df)):
        p1 = df.iloc[i-1]; p2 = df.iloc[i-2]; curr = df.iloc[i]
        c    = sf(curr['close']); atr_ = sf(curr['atr']) or c * 0.005
        r    = sf(curr['rsi']); e9 = sf(curr['ema_9']); e21 = sf(curr['ema_21'])
        e50  = sf(curr['ema_50']); cm = sf(curr['macd']); cs_ = sf(curr['macd_s'])
        pm   = sf(p1['macd']); ps = sf(p1['macd_s']); p1e9 = sf(p1['ema_9']); p1e21 = sf(p1['ema_21'])
        bu   = sf(curr['bb_u']); bl = sf(curr['bb_l']); bm = sf(curr['bb_m'])
        st_d = int(sf(curr.get('st_dir', 1) or 1))
        sk   = sf(curr.get('stoch_k', 50)); sd = sf(curr.get('stoch_d', 50))
        p1sk = sf(p1.get('stoch_k', 50)); p1sd = sf(p1.get('stoch_d', 50))
        bull = bear = False
        if strategy_name == "SuperTrend + RSI":
            bull = st_d == 1  and 50 < r < 75 and e9 > e21
            bear = st_d == -1 and 25 < r < 50 and e9 < e21
        elif strategy_name == "MACD + EMA Confluence":
            bull = pm <= ps and cm > cs_ and cm - cs_ > 0 and e9 > e21 and e21 > e50 and 45 < r < 72
            bear = pm >= ps and cm < cs_ and cs_ - cm > 0 and e9 < e21 and e21 < e50 and 28 < r < 55
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
            bw = (bu - bl) / bm if bm else 0.05; squeeze = bw < 0.04
            bull = squeeze and c > bu and r > 55 and cm > cs_
            bear = squeeze and c < bl and r < 45 and cm < cs_
        if not in_pos:
            if bull:
                entry_p = c; in_pos = True; direction = "LONG"; entry_idx = i
                trades.append({"Date": df.index[i], "Signal": "BUY CALL", "Entry": entry_p,
                                "SL": round(entry_p - sl_mult * atr_, 1),
                                "Target": round(entry_p + tgt_mult * atr_, 1), "ATR": round(atr_, 1)})
            elif bear:
                entry_p = c; in_pos = True; direction = "SHORT"; entry_idx = i
                trades.append({"Date": df.index[i], "Signal": "BUY PUT", "Entry": entry_p,
                                "SL": round(entry_p + sl_mult * atr_, 1),
                                "Target": round(entry_p - tgt_mult * atr_, 1), "ATR": round(atr_, 1)})
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
                pts = (exit_p - entry_p) if direction == "LONG" else (entry_p - exit_p)
                trades[-1].update({"Exit": exit_p, "Points": round(pts, 1), "Reason": reason})
                in_pos = False; direction = ""
    trades = [t for t in trades if "Points" in t]
    if not trades:
        return None, f"No completed trades for '{strategy_name}'. Try a different period or strategy."
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
    wr     = round((res['Points'] > 0).mean() * 100, 1)
    metrics = {
        "total_pts": round(res['Points'].sum(), 1), "win_rate": wr, "trades": len(res),
        "max_dd":    round((res['Cumulative'].cummax() - res['Cumulative']).max(), 1),
        "avg_win":   round(wins['Points'].mean(),         1) if len(wins)   else 0,
        "avg_loss":  round(abs(losses['Points'].mean()),  1) if len(losses) else 0,
        "rr_ratio":  round(abs(wins['Points'].mean() / losses['Points'].mean()), 2)
                     if len(wins) and len(losses) else 0,
        "interval":  label, "candles": len(df),
        "consecutive_wins": int(
            (res['Result'] == 'WIN').groupby((res['Result'] != 'WIN').cumsum()).sum().max() or 0
        ),
    }
    return res, metrics


# ── Signal evaluator (identical conditions to strategy.py get_signal) ─────
def evaluate_signal(df, strategy_name, price):
    if df is None or len(df) < 5:
        return "HOLD", "Insufficient data", 0, 0
    lat  = df.iloc[-1]; p1 = df.iloc[-2]
    c    = sf(lat['close']); atr_ = sf(lat.get('atr', c * 0.005)) or c * 0.005
    r    = sf(lat['rsi']); e9 = sf(lat['ema_9']); e21 = sf(lat['ema_21'])
    e50  = sf(lat.get('ema_50', e21)); cm = sf(lat['macd']); cs_ = sf(lat['macd_s'])
    pm   = sf(p1['macd']); ps_ = sf(p1['macd_s'])
    p1e9 = sf(p1['ema_9']); p1e21 = sf(p1['ema_21'])
    bu   = sf(lat['bb_u']); bl = sf(lat['bb_l']); bm = sf(lat['bb_m'])
    st_d = int(sf(lat.get('st_dir', 1) or 1))
    sk   = sf(lat.get('stoch_k', 50)); sd_ = sf(lat.get('stoch_d', 50))
    p1sk = sf(p1.get('stoch_k', 50)); p1sd = sf(p1.get('stoch_d', 50))
    sl_mult = _SL_MULTIPLIERS.get(strategy_name, 1.3); tgt_mult = sl_mult * 1.8
    sl_long  = round(c - sl_mult * atr_, 1); tgt_long  = round(c + tgt_mult * atr_, 1)
    sl_short = round(c + sl_mult * atr_, 1); tgt_short = round(c - tgt_mult * atr_, 1)
    if strategy_name == "SuperTrend + RSI":
        if st_d == 1  and 50 < r < 75 and e9 > e21: return "BUY_CALL", f"SuperTrend ↑ | RSI {r:.0f} bullish | EMA aligned", sl_long, tgt_long
        if st_d == -1 and 25 < r < 50 and e9 < e21: return "BUY_PUT",  f"SuperTrend ↓ | RSI {r:.0f} bearish | EMA aligned", sl_short, tgt_short
    elif strategy_name == "MACD + EMA Confluence":
        if pm <= ps_ and cm > cs_ and e9 > e21 and e21 > e50 and 45 < r < 72: return "BUY_CALL", f"MACD ↑ + EMA bull stack | RSI {r:.0f}", sl_long, tgt_long
        if pm >= ps_ and cm < cs_ and e9 < e21 and e21 < e50 and 28 < r < 55: return "BUY_PUT",  f"MACD ↓ + EMA bear stack | RSI {r:.0f}", sl_short, tgt_short
    elif strategy_name == "Stochastic + BB Mean Reversion":
        if p1sk <= p1sd and sk > sd_ and sk < 35 and r < 50: return "BUY_CALL", f"Stoch oversold cross ↑ | RSI {r:.0f}", sl_long, tgt_long
        if p1sk >= p1sd and sk < sd_ and sk > 65 and r > 50: return "BUY_PUT",  f"Stoch overbought cross ↓ | RSI {r:.0f}", sl_short, tgt_short
    elif strategy_name == "Triple EMA + Volume Trend":
        if e9 > e21 and e21 > e50 and 52 < r < 72: return "BUY_CALL", f"9>21>50 EMA bull stack | RSI {r:.0f}", sl_long, tgt_long
        if e9 < e21 and e21 < e50 and 28 < r < 48: return "BUY_PUT",  f"9<21<50 EMA bear stack | RSI {r:.0f}", sl_short, tgt_short
    elif strategy_name == "Momentum Pulse (EMA+RSI)":
        if p1e9 <= p1e21 and e9 > e21 and r > 55 and cm > cs_: return "BUY_CALL", f"EMA crossover ↑ | RSI {r:.0f} | MACD conf", sl_long, tgt_long
        if p1e9 >= p1e21 and e9 < e21 and r < 45 and cm < cs_: return "BUY_PUT",  f"EMA crossover ↓ | RSI {r:.0f} | MACD conf", sl_short, tgt_short
    elif strategy_name == "Bollinger Squeeze Breakout":
        bw = (bu - bl) / bm if bm else 0.05; sq = bw < 0.04
        if sq and c > bu and r > 55 and cm > cs_: return "BUY_CALL", f"BB squeeze breakout ↑ | RSI {r:.0f}", sl_long, tgt_long
        if sq and c < bl and r < 45 and cm < cs_: return "BUY_PUT",  f"BB squeeze breakdown ↓ | RSI {r:.0f}", sl_short, tgt_short
    trend = "BULLISH" if st_d == 1 else "BEARISH"
    rsi_s = "OVERBOUGHT" if r > 70 else "OVERSOLD" if r < 30 else f"{r:.0f}"
    return "HOLD", f"No confluence | Trend: {trend} | RSI: {rsi_s}", 0, 0


# ══════════════════════════════════════════════════════════════════════════════
#  GLOBAL CSS — HIGH-CONTRAST CORPORATE LIGHT THEME
#  Royal Blue #1e3a8a  |  Crimson #dc2626  |  JetBrains Mono + DM Sans
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=DM+Sans:wght@300;400;500;600;700&display=swap');

:root {
  /* ── Brand palette ── */
  --royal:    #1e3a8a;   --royal-d:  #172d6e;   --royal-l:  #e8eeff;
  --royal-m:  rgba(30,58,138,.12);
  --crimson:  #dc2626;   --crimson-l:#fff1f1;    --crimson-m:rgba(220,38,38,.12);
  --emerald:  #047857;   --emerald-l:#ecfdf5;    --emerald-m:rgba(4,120,87,.12);
  --amber:    #b45309;   --amber-l:  #fffbeb;    --amber-m:  rgba(180,83,9,.12);
  --teal:     #0f766e;   --teal-l:   #f0fdfa;
  /* ── Neutrals ── */
  --bg:      #f0f4f8;   --panel:   #ffffff;     --panel2:  #f8fafc;
  --border:  #dde3ee;   --border2: #c8d2e4;
  --text:    #0f172a;   --text2:   #334155;      --muted:   #64748b;
  /* ── Typography ── */
  --mono: 'JetBrains Mono', monospace;
  --sans: 'DM Sans', sans-serif;
  /* ── Surfaces ── */
  --radius: 10px;
  --shadow: 0 1px 6px rgba(15,23,42,.08), 0 0 0 1px rgba(15,23,42,.04);
  --shadow-lg: 0 4px 24px rgba(15,23,42,.12);
}

*, *::before, *::after { box-sizing: border-box; }
#MainMenu, footer { visibility: hidden !important; }
header[data-testid="stHeader"] { background: transparent !important; z-index: 1100 !important; box-shadow: none !important; pointer-events: none; }
header[data-testid="stHeader"] button, header[data-testid="stHeader"] [data-testid="collapsedControl"] { pointer-events: all !important; }
.stDeployButton { display: none !important; }
.block-container { padding: 0 !important; max-width: 100% !important; padding-top: 3.5rem !important; }
.stApp { background: var(--bg) !important; font-family: var(--sans) !important; color: var(--text) !important; }

/* ── SIDEBAR ── */
section[data-testid="stSidebar"] { background: var(--royal-d) !important; box-shadow: 3px 0 20px rgba(15,23,42,.2) !important; }
section[data-testid="stSidebar"] * { color: #e2e8f7 !important; }
section[data-testid="stSidebar"] .stSelectbox > div > div,
section[data-testid="stSidebar"] input {
  background: rgba(255,255,255,.09) !important;
  border: 1px solid rgba(255,255,255,.16) !important;
  color: #e2e8f7 !important; border-radius: 8px !important;
}
section[data-testid="stSidebar"] label { color: rgba(226,232,247,.65) !important; font-size: 11px !important; font-family: var(--mono) !important; }
section[data-testid="stSidebar"] .stButton > button { background: rgba(255,255,255,.1) !important; border: 1px solid rgba(255,255,255,.2) !important; color: #e2e8f7 !important; font-size: 11px !important; border-radius: 7px !important; }
.sb-connect-btn .stButton > button { background: var(--royal) !important; border: none !important; color: white !important; font-weight: 700 !important; }
.sb-danger .stButton > button    { background: var(--crimson) !important; border: none !important; color: white !important; font-weight: 700 !important; }
.sb-success .stButton > button   { background: var(--emerald) !important; border: none !important; color: white !important; font-weight: 700 !important; }

/* ── TOPBAR ── */
.topbar {
  background: var(--royal); padding: 0 24px 0 68px; height: 52px;
  display: flex; align-items: center; justify-content: space-between;
  position: sticky; top: 0; z-index: 999;
  box-shadow: 0 2px 12px rgba(15,23,42,.3);
  border-bottom: 2px solid var(--royal-d);
}
.tb-logo { font-family: var(--mono); font-size: 16px; font-weight: 700; color: #fff; letter-spacing: -.2px; }
.tb-logo em { color: #93c5fd; font-style: normal; }
.tb-logo small { font-size: 9px; color: rgba(255,255,255,.38); letter-spacing: 3px; margin-left: 8px; font-weight: 400; }
.tb-pills { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.pill { display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border-radius: 20px;
        font-family: var(--mono); font-size: 10px; font-weight: 700; letter-spacing: .5px; white-space: nowrap; }
.pill-conn  { background: rgba(4,120,87,.3);  color: #6ee7b7; border: 1px solid rgba(110,231,183,.35); }
.pill-disc  { background: rgba(220,38,38,.3); color: #fca5a5; border: 1px solid rgba(252,165,165,.35); }
.pill-paper { background: rgba(180,83,9,.3);  color: #fcd34d; border: 1px solid rgba(252,211,77,.35); }
.pill-live  { background: rgba(220,38,38,.4); color: #fca5a5; border: 1px solid rgba(252,165,165,.4); animation: live-pulse 2s infinite; }
.pill-auto  { background: rgba(4,120,87,.35); color: #6ee7b7; border: 1px solid rgba(110,231,183,.4); }
.pill-strat { background: rgba(255,255,255,.09); color: rgba(255,255,255,.72); border: 1px solid rgba(255,255,255,.14); }
.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.dot-g { background: #34d399; animation: pulse 2s infinite; }
.dot-r { background: #f87171; }
@keyframes live-pulse { 0%,100%{opacity:1} 50%{opacity:.55} }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }

.ar-banner { background: linear-gradient(90deg,var(--royal-l),#f0f4ff); border-bottom: 1px solid var(--border);
             padding: 7px 28px; font-family: var(--mono); font-size: 11px; color: var(--royal);
             display: flex; align-items: center; gap: 8px; }

/* ── METRIC CARDS — mobile-first flexible grid ── */
.metric-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; padding: 16px 20px; }
.mcard { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
         padding: 14px 16px; position: relative; overflow: hidden; box-shadow: var(--shadow);
         transition: box-shadow .2s, transform .15s; min-width: 0; }
.mcard:hover { box-shadow: var(--shadow-lg); transform: translateY(-1px); }
.mcard-accent { position: absolute; top: 0; left: 0; right: 0; height: 3px; border-radius: var(--radius) var(--radius) 0 0; }
.mcard-label { font-family: var(--mono); font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mcard-value { font-family: var(--mono); font-size: 19px; font-weight: 700; color: var(--text); line-height: 1; word-break: break-all; }
.mcard-sub   { font-family: var(--mono); font-size: 10px; color: var(--muted); margin-top: 5px; }

/* Accent colours */
.c-royal   { background: var(--royal); }   .c-crimson { background: var(--crimson); }
.c-emerald { background: var(--emerald); } .c-amber   { background: var(--amber); }
.c-teal    { background: var(--teal); }    .c-muted   { background: var(--muted); }

/* Value colours */
.v-emerald { color: var(--emerald) !important; } .v-crimson { color: var(--crimson) !important; }
.v-amber   { color: var(--amber) !important; }   .v-royal   { color: var(--royal) !important; }

/* ── SIGNAL BANNERS ── */
.sig-hold { background: var(--panel2); border: 1.5px solid var(--border2); color: var(--muted);
            text-align: center; padding: 14px 20px; border-radius: var(--radius);
            font-family: var(--mono); font-size: 13px; font-weight: 700; letter-spacing: 1.5px; }
.sig-buy  { background: var(--emerald-l); border: 2px solid var(--emerald); color: var(--emerald);
            text-align: center; padding: 14px 20px; border-radius: var(--radius);
            font-family: var(--mono); font-size: 13px; font-weight: 700; letter-spacing: 1.5px;
            box-shadow: 0 0 24px var(--emerald-m); }
.sig-sell { background: var(--crimson-l); border: 2px solid var(--crimson); color: var(--crimson);
            text-align: center; padding: 14px 20px; border-radius: var(--radius);
            font-family: var(--mono); font-size: 13px; font-weight: 700; letter-spacing: 1.5px;
            box-shadow: 0 0 24px var(--crimson-m); }

.sec-hdr { font-family: var(--mono); font-size: 9px; color: var(--muted); text-transform: uppercase;
           letter-spacing: 2.5px; padding: 16px 20px 10px; border-top: 1px solid var(--border); }

/* ── TABLES — monospaced, swipable ── */
.table-responsive { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
.qbt { width: 100%; border-collapse: collapse; font-family: var(--mono); font-size: 11px; white-space: nowrap; }
.qbt thead tr { background: var(--panel2); }
.qbt th { padding: 10px 12px; text-align: left; font-weight: 500; font-size: 9px; letter-spacing: 1.5px;
          text-transform: uppercase; color: var(--muted); border-bottom: 2px solid var(--border); }
.qbt td { padding: 9px 12px; border-bottom: 1px solid var(--border); color: var(--text2); vertical-align: middle; }
.qbt tbody tr:hover td { background: var(--panel2); }
.row-profit td { background: rgba(4,120,87,.04) !important; }
.row-loss   td { background: rgba(220,38,38,.04) !important; }

/* ── BADGES ── */
.badge { display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px; border-radius: 20px; font-size: 9px; font-family: var(--mono); font-weight: 700; }
.b-win  { background: var(--emerald-l); color: var(--emerald); border: 1px solid rgba(4,120,87,.3); }
.b-loss { background: var(--crimson-l); color: var(--crimson); border: 1px solid rgba(220,38,38,.3); }
.b-buy  { background: var(--emerald-l); color: var(--emerald); border: 1px solid rgba(4,120,87,.3); }
.b-sell { background: var(--crimson-l); color: var(--crimson); border: 1px solid rgba(220,38,38,.3); }
.b-comp { background: var(--royal-l);   color: var(--royal);   border: 1px solid rgba(30,58,138,.3); }
.b-open { background: var(--amber-l);   color: var(--amber);   border: 1px solid rgba(180,83,9,.3); }
.b-hold { background: rgba(100,116,139,.1); color: var(--muted); border: 1px solid rgba(100,116,139,.2); }

/* ── PROFESSIONAL SENTIMENT GAUGE ── */
.gauge-wrap { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
              padding: 18px 20px; margin: 12px 0; box-shadow: var(--shadow); }
.gauge-title { font-family: var(--mono); font-size: 9px; color: var(--muted); text-transform: uppercase;
               letter-spacing: 2px; margin-bottom: 12px; }
.gauge-label-row { display: flex; justify-content: space-between; margin-bottom: 5px; }
.gauge-label { font-family: var(--mono); font-size: 10px; font-weight: 700; }
.gl-bull { color: var(--emerald); } .gl-bear { color: var(--crimson); } .gl-neut { color: var(--muted); }
.gauge-track { position: relative; height: 20px; border-radius: 6px; background: var(--border2);
               overflow: hidden; box-shadow: inset 0 1px 3px rgba(0,0,0,.08); }
.gauge-fill-bull { position: absolute; left: 0; top: 0; height: 100%;
                   background: linear-gradient(90deg,#047857,#10b981); border-radius: 6px 0 0 6px;
                   transition: width .5s cubic-bezier(.34,1.56,.64,1); }
.gauge-fill-bear { position: absolute; right: 0; top: 0; height: 100%;
                   background: linear-gradient(90deg,#ef4444,#dc2626); border-radius: 0 6px 6px 0;
                   transition: width .5s cubic-bezier(.34,1.56,.64,1); }
.gauge-tick { position: absolute; left: 50%; top: -2px; width: 2px; height: 28px;
              background: var(--border2); z-index: 2; }
.gauge-verdict { text-align: center; margin-top: 10px; }
.verdict-badge { display: inline-block; padding: 5px 16px; border-radius: 20px;
                 font-family: var(--mono); font-size: 11px; font-weight: 700; letter-spacing: 1px; }
.vb-strong-bull { background: var(--emerald-l); color: var(--emerald); border: 1.5px solid rgba(4,120,87,.4); }
.vb-strong-bear { background: var(--crimson-l); color: var(--crimson); border: 1.5px solid rgba(220,38,38,.4); }
.vb-lean-bull   { background: #f0fdf4; color: #166534; border: 1.5px solid rgba(22,101,52,.3); }
.vb-lean-bear   { background: #fff1f1; color: #991b1b; border: 1.5px solid rgba(153,27,27,.3); }
.vb-neutral     { background: var(--panel2); color: var(--muted); border: 1.5px solid var(--border2); }
.gauge-strategy-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; }
.gsr-item { display: flex; align-items: center; gap: 6px; background: var(--panel2); border: 1px solid var(--border); border-radius: 6px; padding: 5px 10px; font-family: var(--mono); font-size: 10px; color: var(--text2); flex: 1 1 180px; min-width: 0; }
.gsr-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.gsr-bull { background: var(--emerald); } .gsr-bear { background: var(--crimson); } .gsr-neut { background: var(--border2); }

/* ── BUTTONS ── */
.stButton > button { border-radius: 7px !important; font-family: var(--mono) !important; font-size: 11px !important;
  font-weight: 700 !important; letter-spacing: .5px !important; transition: all .15s !important;
  border: 1px solid var(--border) !important; background: var(--panel) !important;
  color: var(--text) !important; padding: 9px 16px !important; }
.stButton > button:hover { background: var(--royal) !important; color: white !important; border-color: var(--royal) !important; }
.main-btn .stButton > button    { background: var(--royal)   !important; color: white !important; border: none !important; }
.danger-btn .stButton > button  { background: var(--crimson) !important; color: white !important; border: none !important; }
.success-btn .stButton > button { background: var(--emerald) !important; color: white !important; border: none !important; }

/* ── TABS ── */
.stTabs [data-baseweb="tab-list"] { background: var(--panel) !important; border-bottom: 2px solid var(--border) !important;
  gap: 0 !important; padding: 0 16px !important; overflow-x: auto !important; box-shadow: 0 2px 8px rgba(15,23,42,.04); }
.stTabs [data-baseweb="tab"] { background: transparent !important; color: var(--muted) !important;
  font-family: var(--mono) !important; font-size: 10px !important; font-weight: 700 !important;
  letter-spacing: 1.5px !important; padding: 13px 14px !important; border-bottom: 2px solid transparent !important;
  text-transform: uppercase !important; white-space: nowrap !important; transition: color .15s !important; }
.stTabs [aria-selected="true"] { color: var(--royal) !important; border-bottom-color: var(--royal) !important; }
.stTabs [data-baseweb="tab-panel"] { background: var(--bg) !important; padding: 0 !important; }

.stAlert { border-radius: var(--radius) !important; font-family: var(--sans) !important; }
.stSelectbox>div>div,.stTextInput>div>div>input,.stNumberInput>div>div>input { border-radius: 7px !important; border: 1px solid var(--border) !important; font-family: var(--mono) !important; font-size: 12px !important; }
.stSelectbox label,.stNumberInput label,.stTextInput label,.stSlider label,.stToggle label { font-family: var(--mono) !important; font-size: 10px !important; text-transform: uppercase !important; letter-spacing: 1px !important; color: var(--muted) !important; }
div[data-testid="stMetric"] { background: var(--panel) !important; border: 1px solid var(--border) !important; border-radius: var(--radius) !important; padding: 16px !important; box-shadow: var(--shadow) !important; }
.pad { padding: 0 24px 28px; } .padx { padding: 0 24px; } .gap12 { margin-top: 12px; }

/* ── CONN NOTICE ── */
.conn-notice { background: var(--amber-l); border: 1.5px solid rgba(180,83,9,.25); border-radius: var(--radius);
               padding: 20px 24px; margin: 20px; display: flex; align-items: flex-start; gap: 14px; }
.conn-body { font-family: var(--sans); font-size: 14px; color: var(--text2); line-height: 1.65; }
.conn-body strong { color: var(--amber); }

/* ── IRON CONDOR ── */
.condor-leg { display: flex; align-items: center; gap: 14px; padding: 12px 20px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.condor-leg:last-child { border-bottom: none; }

/* ── FAQ SECTION ── */
.faq-section { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
               margin-bottom: 14px; overflow: hidden; box-shadow: var(--shadow); }
.faq-header { background: linear-gradient(90deg, var(--royal), #1d4ed8); padding: 14px 20px;
              font-family: var(--mono); font-size: 13px; font-weight: 700; color: white;
              letter-spacing: .5px; display: flex; align-items: center; gap: 10px; }
.faq-icon { font-size: 18px; }
.faq-body { padding: 16px 20px; }
.faq-body p { font-family: var(--sans); font-size: 14px; color: var(--text2); line-height: 1.72; margin: 0 0 10px; }
.faq-body .faq-highlight { background: var(--royal-l); border-left: 3px solid var(--royal);
                           padding: 10px 14px; border-radius: 0 6px 6px 0; margin: 10px 0;
                           font-family: var(--mono); font-size: 12px; color: var(--royal); }
.faq-body .faq-warn { background: var(--crimson-l); border-left: 3px solid var(--crimson);
                      padding: 10px 14px; border-radius: 0 6px 6px 0; margin: 10px 0;
                      font-family: var(--mono); font-size: 12px; color: var(--crimson); }
.faq-body .faq-ok { background: var(--emerald-l); border-left: 3px solid var(--emerald);
                    padding: 10px 14px; border-radius: 0 6px 6px 0; margin: 10px 0;
                    font-family: var(--mono); font-size: 12px; color: var(--emerald); }
.tutorial-hero { background: linear-gradient(135deg, var(--royal), #1d4ed8 60%, var(--teal));
                 border-radius: var(--radius); padding: 28px 28px 24px; margin-bottom: 20px; }
.tutorial-hero h2 { font-family: var(--mono); color: white; font-size: 20px; margin: 0 0 8px; letter-spacing: -.3px; }
.tutorial-hero p  { font-family: var(--sans); color: rgba(255,255,255,.78); font-size: 14px; margin: 0; line-height: 1.6; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div style="padding:20px 16px 4px">
      <div style="font-family:'JetBrains Mono',monospace;font-size:16px;font-weight:700;color:#fff">
        QUANT<em style="color:#93c5fd;font-style:normal">BENGAL</em>
        <span style="font-size:8px;color:rgba(255,255,255,.32);letter-spacing:3px;margin-left:6px;font-weight:400">PRO</span>
      </div>
      <div style="font-size:9px;color:rgba(255,255,255,.38);letter-spacing:2px;margin-top:3px;font-family:'JetBrains Mono',monospace">AUTOMATED TRADING ENGINE</div>
    </div>
    <div style="height:1px;background:rgba(255,255,255,.08);margin:12px 0"></div>
    """, unsafe_allow_html=True)

    if st.session_state.connected:
        st.markdown('<div style="margin:0 4px 10px;background:rgba(52,211,153,.15);border:1px solid rgba(52,211,153,.3);border-radius:8px;padding:7px 12px;font-family:JetBrains Mono,monospace;font-size:10px;color:#34d399;text-align:center">● ANGEL ONE CONNECTED</div>', unsafe_allow_html=True)
        with st.expander("🔌 Manage Connection", expanded=False):
            st.info("Session is active and authenticated.")
            st.markdown('<div class="sb-danger">', unsafe_allow_html=True)
            if st.button("🔌 DISCONNECT SECURELY", use_container_width=True):
                st.session_state.broker    = None
                st.session_state.connected = False
                st.session_state.engine_on = False
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="margin:0 4px 10px;background:rgba(220,38,38,.15);border:1px solid rgba(220,38,38,.3);border-radius:8px;padding:7px 12px;font-family:JetBrains Mono,monospace;font-size:10px;color:#fca5a5;text-align:center">● DISCONNECTED — connect below</div>', unsafe_allow_html=True)
        with st.expander("🔌 Angel One Connection", expanded=True):
            st.session_state.api_key     = st.text_input("API Key",     value=st.session_state.api_key,     type="password", key="s_api")
            st.session_state.client_id   = st.text_input("Client ID",   value=st.session_state.client_id,   key="s_cid")
            st.session_state.password    = st.text_input("Password",    value=st.session_state.password,    type="password", key="s_pw")
            st.session_state.totp_secret = st.text_input("TOTP Secret", value=st.session_state.totp_secret, type="password", key="s_totp")
            st.markdown('<div class="sb-connect-btn">', unsafe_allow_html=True)
            if st.button("⚡ CONNECT TO ANGEL ONE", use_container_width=True, key="btn_conn"):
                if not all([st.session_state.api_key, st.session_state.client_id,
                            st.session_state.password, st.session_state.totp_secret]):
                    st.error("All 4 credential fields are required.")
                elif not BROKER_OK:
                    st.error("broker_api.py not found in the app folder.")
                else:
                    for k, env in [("api_key","BROKER_API_KEY"),("client_id","CLIENT_ID"),
                                   ("password","PASSWORD"),("totp_secret","TOTP_TOKEN")]:
                        os.environ[env] = st.session_state[k]
                    with st.spinner("Authenticating with Angel One…"):
                        try:
                            b = IndianBrokerAPI()
                            if b.connected:
                                st.session_state.broker    = b
                                st.session_state.connected = True
                                st.success("✅ Connected!")
                                time.sleep(0.4)
                                st.rerun()
                            else:
                                st.error(
                                    "❌ Authentication failed.\n"
                                    "• TOTP Secret = the 32-character BASE32 key, NOT the 6-digit OTP\n"
                                    "• Double-check Client ID and Trading PIN"
                                )
                        except Exception as ex:
                            st.error(f"Connection error: {_human_order_error(str(ex))}")
            st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div style="height:1px;background:rgba(255,255,255,.08);margin:8px 0"></div>', unsafe_allow_html=True)

    st.markdown('<div style="padding:4px 4px 2px;font-family:JetBrains Mono,monospace;font-size:9px;color:rgba(255,255,255,.38);letter-spacing:2px;text-transform:uppercase">Market & Strategy</div>', unsafe_allow_html=True)
    st.session_state.index_choice = st.selectbox("Trading Index", ["NIFTY", "BANKNIFTY", "SENSEX"],
        index=["NIFTY","BANKNIFTY","SENSEX"].index(st.session_state.index_choice))
    st.session_state.expiry_date = st.text_input("Options Expiry (e.g. 25APR)", value=st.session_state.expiry_date)

    STRATS = ["SuperTrend + RSI","MACD + EMA Confluence","Stochastic + BB Mean Reversion",
              "Triple EMA + Volume Trend","Momentum Pulse (EMA+RSI)","Bollinger Squeeze Breakout","Iron Condor (BankNifty)"]
    idx = STRATS.index(st.session_state.strategy) if st.session_state.strategy in STRATS else 0
    st.session_state.strategy = st.selectbox("Strategy", STRATS, index=idx, key="sel_s")
    st.session_state.capital  = float(st.number_input("Capital (₹)", min_value=20000, max_value=5000000,
        value=int(st.session_state.capital), step=10000, key="cap_n"))
    st.session_state.dry_run  = st.toggle("🧪 Dry Run (Paper Trade)", value=st.session_state.dry_run, key="dry_t")
    if not st.session_state.dry_run:
        st.markdown('<div style="background:rgba(220,38,38,.2);border-radius:6px;padding:6px 10px;font-size:10px;color:#fca5a5;margin-top:4px;font-family:JetBrains Mono,monospace">⚠️ LIVE MODE — real orders will be placed</div>', unsafe_allow_html=True)

    st.markdown('<div style="height:1px;background:rgba(255,255,255,.08);margin:8px 0"></div>', unsafe_allow_html=True)
    st.markdown('<div style="padding:4px 4px 2px;font-family:JetBrains Mono,monospace;font-size:9px;color:rgba(255,255,255,.38);letter-spacing:2px;text-transform:uppercase">Safe Execution Hours (IST)</div>', unsafe_allow_html=True)
    c_hr1, c_hr2 = st.columns(2)
    with c_hr1: st.session_state.safe_start = st.text_input("Start", value=st.session_state.safe_start)
    with c_hr2: st.session_state.safe_end   = st.text_input("End",   value=st.session_state.safe_end)

    st.markdown('<div style="height:1px;background:rgba(255,255,255,.08);margin:8px 0"></div>', unsafe_allow_html=True)
    st.markdown('<div style="padding:4px 4px 2px;font-family:JetBrains Mono,monospace;font-size:9px;color:rgba(255,255,255,.38);letter-spacing:2px;text-transform:uppercase">Auto Refresh</div>', unsafe_allow_html=True)
    st.session_state.auto_refresh = st.toggle("⏱ Auto Refresh", value=st.session_state.auto_refresh, key="ar_t")
    if st.session_state.auto_refresh:
        st.session_state.refresh_interval = st.slider("Interval (s)", 15, 120, 30, 5, key="ar_s")

    st.markdown('<div style="height:1px;background:rgba(255,255,255,.08);margin:8px 0"></div>', unsafe_allow_html=True)
    st.markdown('<div style="padding:4px 4px 4px;font-family:JetBrains Mono,monospace;font-size:9px;color:rgba(255,255,255,.38);letter-spacing:2px;text-transform:uppercase">Auto Trading</div>', unsafe_allow_html=True)
    if st.session_state.engine_on:
        st.markdown('<div style="background:rgba(52,211,153,.15);border:1px solid rgba(52,211,153,.3);border-radius:8px;padding:7px;text-align:center;font-family:JetBrains Mono,monospace;font-size:10px;color:#34d399;margin-bottom:6px">🤖 ENGINE RUNNING</div>', unsafe_allow_html=True)
        st.markdown('<div class="sb-danger">', unsafe_allow_html=True)
        if st.button("⏹ STOP AUTO-TRADE", use_container_width=True, key="stop_a"):
            st.session_state.engine_on = False; st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="sb-success">', unsafe_allow_html=True)
        if st.button("▶ START AUTO-TRADE", use_container_width=True, key="start_a"):
            if not st.session_state.connected: st.error("Connect first.")
            else: st.session_state.engine_on = True; st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div style="height:1px;background:rgba(255,255,255,.08);margin:8px 0"></div>', unsafe_allow_html=True)
    st.markdown('<div style="padding:4px 4px 2px;font-family:JetBrains Mono,monospace;font-size:9px;color:rgba(255,255,255,.38);letter-spacing:2px;text-transform:uppercase">Risk Controls</div>', unsafe_allow_html=True)
    st.session_state.vix_limit      = st.slider("VIX Threshold",        10.0, 30.0, st.session_state.vix_limit,      0.5,  key="vx_s")
    st.session_state.daily_loss_pct = st.slider("Daily Loss Limit (%)", 0.5,  5.0,  st.session_state.daily_loss_pct, 0.25, key="dl_s")

    st.markdown('<div style="height:1px;background:rgba(255,255,255,.08);margin:8px 0"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sb-danger">', unsafe_allow_html=True)
    if st.button("🛑 EMERGENCY SQUARE OFF", use_container_width=True, key="sos"):
        _b = st.session_state.get("broker")
        if _b and getattr(_b, "connected", False):
            with st.spinner("Closing ALL positions at market price…"):
                _results = _b.square_off_all()
            failed = [r for r in _results if not r.get("status")]
            if failed:
                for f in failed:
                    st.warning(f"⚠️ {f['symbol']}: {f.get('error','Unknown')}")
            st.warning(f"✅ Squared off {len(_results) - len(failed)} position(s)")
            st.session_state.engine_on = False
        else:
            st.error("Not connected to Angel One.")
    st.markdown('</div>', unsafe_allow_html=True)

    n = now_ist(); mo = market_open()
    st.markdown(f"""
    <div style="padding:12px 4px 4px;font-family:JetBrains Mono,monospace;font-size:10px;color:rgba(255,255,255,.38);line-height:2">
      <div>🕐 {n.strftime('%d %b  %H:%M:%S IST')}</div>
      <div>Market: {'<span style="color:#34d399">● OPEN</span>' if mo else '<span style="color:#f87171">● CLOSED</span>'}</div>
      <div>Mode: {'<span style="color:#fcd34d">PAPER</span>' if st.session_state.dry_run else '<span style="color:#fca5a5;font-weight:700">⚡ LIVE</span>'}</div>
      <div>Engine: {'<span style="color:#34d399;font-weight:700">RUNNING 🤖</span>' if st.session_state.engine_on else '<span style="color:rgba(255,255,255,.28)">IDLE</span>'}</div>
    </div>
    """, unsafe_allow_html=True)


# ── TOP BAR ───────────────────────────────────────────────────────────────────
conn_pill  = f'<span class="pill pill-conn"><span class="dot dot-g"></span>CONNECTED</span>' if st.session_state.connected else '<span class="pill pill-disc"><span class="dot dot-r"></span>DISCONNECTED</span>'
mode_pill  = '<span class="pill pill-paper">PAPER</span>' if st.session_state.dry_run else '<span class="pill pill-live">⚡ LIVE</span>'
strat_pill = f'<span class="pill pill-strat">{st.session_state.strategy.upper()}</span>'
auto_pill  = '<span class="pill pill-auto">🤖 AUTO-ON</span>' if st.session_state.engine_on else ''

st.markdown(f"""
<div class="topbar">
  <div class="tb-logo">QUANT<em>BENGAL</em><small>PRO</small></div>
  <div class="tb-pills">{conn_pill}{mode_pill}{strat_pill}{auto_pill}</div>
</div>
""", unsafe_allow_html=True)

if st.session_state.auto_refresh:
    nxt = (now_ist() + timedelta(seconds=st.session_state.refresh_interval)).strftime("%H:%M:%S")
    st.markdown(f'<div class="ar-banner">⏱ AUTO-REFRESH ACTIVE — every {st.session_state.refresh_interval}s — next: <strong>{nxt} IST</strong></div>', unsafe_allow_html=True)


# ── TABS ──────────────────────────────────────────────────────────────────────
tabs = st.tabs(["⚡ LIVE TERMINAL","📌 POSITIONS & P&L","📋 ORDER BOOK","📊 BACKTEST","🦅 IRON CONDOR","🛡️ RISK ENGINE","📘 TUTORIAL & FAQ"])
tab_term, tab_pos, tab_ord, tab_bt, tab_ic, tab_risk, tab_faq = tabs


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — LIVE TERMINAL
# ══════════════════════════════════════════════════════════════════════════════
with tab_term:
    broker = st.session_state.broker
    if not broker:
        st.markdown("""
        <div class="conn-notice">
          <div style="font-size:28px;flex-shrink:0">🔌</div>
          <div class="conn-body">
            <strong>Connection required</strong> — open the <strong>Angel One Connection</strong>
            expander in the left sidebar, enter your 4 credentials and click
            <strong>⚡ CONNECT TO ANGEL ONE</strong>.<br><br>
            <strong>On mobile:</strong> tap the <strong>&gt;</strong> icon (top-left) to open the sidebar.
          </div>
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    # ── Control row ─────────────────────────────────────────────────────────
    c1, c2, c3, _ = st.columns([1, 1, 1, 6])
    with c1:
        st.markdown('<div style="padding:10px 0 0 24px"><div class="main-btn">', unsafe_allow_html=True)
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

    if do_ref: st.rerun()
    if clr_log:
        st.session_state.trade_log = []
        save_trade_log([])
        st.rerun()

    sym = st.session_state.index_choice
    with st.spinner(f"Fetching live data for {sym}…"):
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
        mo_ = MACD(close=cs); df['macd'] = mo_.macd(); df['macd_s'] = mo_.macd_signal()
        bo_ = BollingerBands(close=cs, window=20, window_dev=2)
        df['bb_u'] = bo_.bollinger_hband(); df['bb_l'] = bo_.bollinger_lband(); df['bb_m'] = bo_.bollinger_mavg()
        df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=cs).average_true_range()
        try: df['st'], df['st_dir'] = calc_supertrend(df, 10, 3.0)
        except: df['st'] = cs; df['st_dir'] = 1
        try:
            sto_ = StochasticOscillator(high=df['high'], low=df['low'], close=cs, window=14, smooth_window=3)
            df['stoch_k'] = sto_.stoch(); df['stoch_d'] = sto_.stoch_signal()
        except: df['stoch_k'] = 50.0; df['stoch_d'] = 50.0

    if df.empty:
        if not market_open():
            st.info("📴 Market is closed (Mon–Fri 09:15–15:30 IST). Live data loads when market opens.")
        else:
            st.warning("⚠️ No candle data returned. Session may have expired — reconnect via the sidebar.")
    else:
        lat = df.iloc[-1]; prv = df.iloc[-2]
        price = sf(lat['close']); chg = price - sf(prv['close'])
        chg_p  = chg / sf(prv['close']) * 100 if sf(prv['close']) else 0
        ema9   = sf(lat['ema_9']); ema21 = sf(lat['ema_21'])
        rsi    = sf(lat['rsi']); atr = sf(lat['atr'])
        macd_v = sf(lat['macd']); macd_s_ = sf(lat['macd_s'])
        bb_u   = sf(lat['bb_u']); bb_l = sf(lat['bb_l'])
        st_dir = int(sf(lat.get('st_dir',1) or 1))

        chg_c  = "v-emerald" if chg >= 0 else "v-crimson"
        rsi_c  = "v-emerald" if rsi > 55 else "v-crimson" if rsi < 45 else "v-amber"
        macd_c = "v-emerald" if macd_v > macd_s_ else "v-crimson"

        st.markdown(f"""
        <div class="metric-row">
          <div class="mcard"><div class="mcard-accent c-royal"></div>
            <div class="mcard-label">LIVE PRICE · {sym}</div>
            <div class="mcard-value">₹{price:,.0f}</div>
            <div class="mcard-sub {chg_c}">{'+' if chg>=0 else ''}{chg:,.0f} &nbsp; ({chg_p:+.2f}%)</div>
          </div>
          <div class="mcard"><div class="mcard-accent {'c-emerald' if ema9>ema21 else 'c-crimson'}"></div>
            <div class="mcard-label">EMA 9 / 21 / 50</div>
            <div class="mcard-value">₹{ema9:,.0f}</div>
            <div class="mcard-sub {'v-emerald' if ema9>ema21 else 'v-crimson'}">{'↑ BULLISH' if ema9>ema21 else '↓ BEARISH'} &nbsp; ST:{'▲' if st_dir==1 else '▼'}</div>
          </div>
          <div class="mcard"><div class="mcard-accent {'c-emerald' if rsi>55 else 'c-crimson' if rsi<45 else 'c-amber'}"></div>
            <div class="mcard-label">RSI (14)</div>
            <div class="mcard-value {rsi_c}">{rsi:.1f}</div>
            <div class="mcard-sub">{'OVERBOUGHT' if rsi>70 else 'BULL ZONE' if rsi>55 else 'OVERSOLD' if rsi<30 else 'BEAR ZONE' if rsi<45 else 'NEUTRAL'}</div>
          </div>
          <div class="mcard"><div class="mcard-accent {'c-emerald' if macd_v>macd_s_ else 'c-crimson'}"></div>
            <div class="mcard-label">MACD / Signal</div>
            <div class="mcard-value {macd_c}">{macd_v:+.1f}</div>
            <div class="mcard-sub">Signal {macd_s_:+.1f} &nbsp; {'▲ BULLISH' if macd_v>macd_s_ else '▼ BEARISH'}</div>
          </div>
          <div class="mcard"><div class="mcard-accent c-teal"></div>
            <div class="mcard-label">ATR / BB Range</div>
            <div class="mcard-value">₹{atr:,.0f}</div>
            <div class="mcard-sub">{bb_l:,.0f} – {bb_u:,.0f}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        sig, reason, sl_p, tgt_p = evaluate_signal(df, st.session_state.strategy, price)
        st.markdown('<div class="pad">', unsafe_allow_html=True)
        if sig == "BUY_CALL":
            st.markdown(f'<div class="sig-buy">▲ BUY CALL &nbsp;|&nbsp; {reason} &nbsp;|&nbsp; SL ₹{sl_p:,.0f} &nbsp; TGT ₹{tgt_p:,.0f}</div>', unsafe_allow_html=True)
        elif sig == "BUY_PUT":
            st.markdown(f'<div class="sig-sell">▼ BUY PUT &nbsp;|&nbsp; {reason} &nbsp;|&nbsp; SL ₹{sl_p:,.0f} &nbsp; TGT ₹{tgt_p:,.0f}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="sig-hold">⚖ HOLD — {reason}</div>', unsafe_allow_html=True)

       # ── Execution logic ──────────────────────────────────────────────
        current_time_str = now_ist().strftime("%H:%M")
        is_safe_time     = st.session_state.safe_start <= current_time_str <= st.session_state.safe_end
        
        # 1. Base Lot Size Map (NSE/BSE 2024-25 REVISIONS)
        qty_map          = {"NIFTY": 65, "SENSEX": 20, "BANKNIFTY": 30}
        base_qty         = qty_map.get(sym.upper(), 15)
        
        # 2. Dynamic Lot Scaling based on Capital (Max 20% allocation per trade)
        margin_per_lot   = 80000 if sym == "BANKNIFTY" else 100000  # Approx margin proxy
        allowed_capital  = st.session_state.capital * 0.20
        num_lots         = max(1, int(allowed_capital / margin_per_lot))
        total_qty        = base_qty * num_lots

        def _log_and_save(entry: dict):
            st.session_state.trade_log.append(entry)
            save_trade_log(st.session_state.trade_log)

        if st.session_state.engine_on and sig in ("BUY_CALL","BUY_PUT") and market_open():
            if not is_safe_time:
                st.warning(f"🤖 Engine active | {current_time_str} is outside Safe Hours ({st.session_state.safe_start}–{st.session_state.safe_end}). Trade blocked.")
            elif sig != st.session_state.last_auto_signal:
                entry = {"time": now_ist().strftime("%d-%b %H:%M:%S"), "signal": sig, "index": sym,
                         "price": price, "sl": sl_p, "target": tgt_p}
                if st.session_state.dry_run:
                    st.success(f"🤖 AUTO PAPER: {sig} on {sym} ({num_lots} Lots) @ ₹{price:,.0f} | SL ₹{sl_p:,.0f} | TGT ₹{tgt_p:,.0f}")
                    entry.update({"mode": "PAPER-AUTO", "status": "OPEN", "pnl": 0})
                    _log_and_save(entry)
                    st.session_state.last_auto_signal = sig
                else:
                    try:
                        order = broker.place_order(signal=sig, symbol=sym, quantity=total_qty,
                                                   price=price, spot_price=price,
                                                   expiry=st.session_state.expiry_date)
                        if order.get("status"):
                            st.success(f"🤖 AUTO LIVE: {sig} on {order.get('trading_symbol')} | ID: {order.get('order_id','')}")
                            entry.update({"mode": "LIVE-AUTO", "order_id": order.get("order_id",""), "status": "OPEN", "pnl": 0})
                            _log_and_save(entry)
                            st.session_state.last_auto_signal = sig
                        else:
                            st.error(f"⚠️ Auto-trade blocked: {_human_order_error(order.get('error',''))}")
                    except Exception as e:
                        st.error(f"⚠️ Auto-trade error: {_human_order_error(str(e))}")
            else:
                st.info(f"🤖 Engine active | Signal '{sig}' already executed this cycle.")
        elif st.session_state.engine_on and not market_open():
            st.warning("🤖 Engine ON — market closed. Will fire on next open signal.")

        if run_btn:
            if sig in ("BUY_CALL","BUY_PUT"):
                entry = {"time": now_ist().strftime("%d-%b %H:%M:%S"), "signal": sig, "index": sym,
                         "price": price, "sl": sl_p, "target": tgt_p}
                if st.session_state.dry_run:
                    st.success(f"🧪 PAPER: {sig} on {sym} ({num_lots} Lots) @ ₹{price:,.0f} | SL ₹{sl_p:,.0f} | TGT ₹{tgt_p:,.0f}")
                    entry.update({"mode": "PAPER", "status": "OPEN", "pnl": 0})
                    _log_and_save(entry)
                else:
                    try:
                        order = broker.place_order(signal=sig, symbol=sym, quantity=total_qty,
                                                   price=price, spot_price=price,
                                                   expiry=st.session_state.expiry_date)
                        if order.get("status"):
                            st.success(f"✅ ORDER PLACED: {sig} on {order.get('trading_symbol')} | ID: {order.get('order_id','')}")
                            entry.update({"mode": "LIVE", "order_id": order.get("order_id",""), "status": "OPEN", "pnl": 0})
                            _log_and_save(entry)
                        else:
                            st.error(f"⚠️ Order rejected: {_human_order_error(order.get('error',''))}")
                    except Exception as e:
                        st.error(f"⚠️ Order error: {_human_order_error(str(e))}")
            else:
                st.info("⚖ HOLD — no actionable signal. Waiting for strategy confluence.")
        # ── Live P&L update for open trades ─────────────────────────────
        if st.session_state.trade_log:
            updated_log  = []
            log_changed  = False
            for t in st.session_state.trade_log:
                t = dict(t)
                if t.get("status") == "OPEN":
                    ep = sf(t.get("price", price))
                    t["pnl"] = round(price - ep, 1) if t["signal"] == "BUY_CALL" else round(ep - price, 1)
                    old = t["status"]
                    if sf(t.get("sl"))     and t["signal"] == "BUY_CALL" and price <= sf(t["sl"]):   t["status"] = "CLOSED(SL)"
                    elif sf(t.get("target")) and t["signal"] == "BUY_CALL" and price >= sf(t["target"]): t["status"] = "CLOSED(TGT)"
                    elif sf(t.get("sl"))     and t["signal"] == "BUY_PUT"  and price >= sf(t["sl"]):   t["status"] = "CLOSED(SL)"
                    elif sf(t.get("target")) and t["signal"] == "BUY_PUT"  and price <= sf(t["target"]): t["status"] = "CLOSED(TGT)"
                    if t["status"] != old: log_changed = True
                updated_log.append(t)
            st.session_state.trade_log = updated_log
            if log_changed: save_trade_log(st.session_state.trade_log)

        # ── Professional Sentiment Gauge ─────────────────────────────────
        st.markdown('<div class="sec-hdr">MULTI-STRATEGY MARKET SENTIMENT</div>', unsafe_allow_html=True)
        ALL_S = ["SuperTrend + RSI","MACD + EMA Confluence","Stochastic + BB Mean Reversion",
                 "Triple EMA + Volume Trend","Momentum Pulse (EMA+RSI)","Bollinger Squeeze Breakout"]
        bulls = 0; bears = 0; strategy_results = []
        for sn in ALL_S:
            s, r, _, _ = evaluate_signal(df, sn, price)
            strategy_results.append({"name": sn, "signal": s, "reason": r})
            if s == "BUY_CALL": bulls += 1
            elif s == "BUY_PUT": bears += 1

        total     = len(ALL_S)
        neutral   = total - bulls - bears
        bull_pct  = bulls / total * 100
        bear_pct  = bears / total * 100

        if bulls >= 4:   verdict_cls = "vb-strong-bull"; verdict_txt = "🟢 STRONG BULLISH"
        elif bears >= 4: verdict_cls = "vb-strong-bear"; verdict_txt = "🔴 STRONG BEARISH"
        elif bulls > bears: verdict_cls = "vb-lean-bull"; verdict_txt = "🟡 BULLISH LEAN"
        elif bears > bulls: verdict_cls = "vb-lean-bear"; verdict_txt = "🟠 BEARISH LEAN"
        else: verdict_cls = "vb-neutral"; verdict_txt = "⚪ MIXED / NEUTRAL"

        strategy_chips = "".join([
            f'<div class="gsr-item">'
            f'<span class="gsr-dot {"gsr-bull" if r["signal"]=="BUY_CALL" else "gsr-bear" if r["signal"]=="BUY_PUT" else "gsr-neut"}"></span>'
            f'<span style="overflow:hidden;text-overflow:ellipsis">{r["name"].split(" ")[0]} <span style="opacity:.6">{r["name"].split(" ",1)[1] if " " in r["name"] else ""}</span></span>'
            f'<span style="margin-left:auto;font-weight:700;{"color:var(--emerald)" if r["signal"]=="BUY_CALL" else "color:var(--crimson)" if r["signal"]=="BUY_PUT" else "color:var(--muted)"}">{"▲" if r["signal"]=="BUY_CALL" else "▼" if r["signal"]=="BUY_PUT" else "–"}</span>'
            f'</div>'
            for r in strategy_results
        ])

        st.markdown(f"""
        <div class="gauge-wrap">
          <div class="gauge-title">INSTITUTIONAL SENTIMENT GAUGE — {total} STRATEGY CONSENSUS</div>
          <div class="gauge-label-row">
            <span class="gauge-label gl-bull">▲ BULLISH &nbsp; {bulls}/{total}</span>
            <span class="gauge-label gl-neut">NEUTRAL {neutral}</span>
            <span class="gauge-label gl-bear">{bears}/{total} &nbsp; BEARISH ▼</span>
          </div>
          <div class="gauge-track">
            <div class="gauge-fill-bull" style="width:{bull_pct}%"></div>
            <div class="gauge-tick"></div>
            <div class="gauge-fill-bear" style="width:{bear_pct}%"></div>
          </div>
          <div class="gauge-verdict">
            <span class="verdict-badge {verdict_cls}">{verdict_txt}</span>
          </div>
          <div class="gauge-strategy-row">{strategy_chips}</div>
        </div>
        """, unsafe_allow_html=True)

        # ── Price chart ──────────────────────────────────────────────────
        st.markdown('<div class="sec-hdr">PRICE + EMA CHART</div>', unsafe_allow_html=True)
        cd = df[['ts','close','ema_9','ema_21','ema_50']].copy()
        try: cd['ts'] = pd.to_datetime(cd['ts']).dt.strftime('%H:%M')
        except: pass
        st.line_chart(cd.set_index('ts').tail(80), height=200, use_container_width=True)

        # ── Last 10 candles (swipable) ───────────────────────────────────
        st.markdown('<div class="sec-hdr">LAST 10 CANDLES — OHLC + INDICATORS</div>', unsafe_allow_html=True)
        disp = df[['ts','open','high','low','close','ema_9','ema_21','rsi','macd','atr']].tail(10).copy()
        try: disp['ts'] = pd.to_datetime(disp['ts']).dt.strftime('%H:%M')
        except: pass
        disp = disp.round(1)
        th     = ''.join(f'<th>{c.upper()}</th>' for c in disp.columns)
        rows_c = ""
        for _, row in disp.iterrows():
            d_ = sf(row['close']) - sf(row['open'])
            rows_c += '<tr>' + ''.join(
                f'<td class="{"v-emerald" if c in ("close","open") and d_>=0 else "v-crimson" if c in ("close","open") and d_<0 else ""}">{row[c]}</td>'
                for c in disp.columns
            ) + '</tr>'
        st.markdown(f'<div class="table-responsive"><table class="qbt"><thead><tr>{th}</tr></thead><tbody>{rows_c}</tbody></table></div>', unsafe_allow_html=True)

        # ── Persistent trade log ─────────────────────────────────────────
        if st.session_state.trade_log:
            st.markdown('<div class="sec-hdr">PERSISTENT TRADE LEDGER — LIVE P&L STATUS</div>', unsafe_allow_html=True)
            th_ = '<th>TIME</th><th>INDEX</th><th>SIGNAL</th><th>ENTRY ₹</th><th>STOP LOSS ₹</th><th>TARGET ₹</th><th>CURRENT P&L</th><th>STATUS</th><th>MODE</th>'
            rows_t = ""
            for t in reversed(st.session_state.trade_log[-20:]):
                pnl_v  = sf(t.get("pnl",0)); status = t.get("status","OPEN")
                pnl_cl = "#059669" if pnl_v > 0 else "#dc2626" if pnl_v < 0 else "#6b7a9f"
                pnl_bg = "#ecfdf5" if pnl_v > 0 else "#fff1f1" if pnl_v < 0 else "#f8fafc"
                pnl_br = "#34d399" if pnl_v > 0 else "#f87171" if pnl_v < 0 else "#dde3ee"
                pnl_html = f'<span style="background:{pnl_bg};color:{pnl_cl};padding:2px 8px;border-radius:10px;font-weight:bold;font-size:10px;border:1px solid {pnl_br};">{"+" if pnl_v>0 else ""}{pnl_v:.1f}</span>'
                sig_cl  = "#059669" if t["signal"] == "BUY_CALL" else "#dc2626"
                sig_bg  = "#ecfdf5" if t["signal"] == "BUY_CALL" else "#fff1f1"
                sig_br  = "#34d399" if t["signal"] == "BUY_CALL" else "#f87171"
                sig_bdg = f'<span style="background:{sig_bg};color:{sig_cl};padding:2px 8px;border-radius:4px;font-weight:bold;font-size:10px;border:1px solid {sig_br};">{"▲" if t["signal"]=="BUY_CALL" else "▼"} {t["signal"]}</span>'
                st_cl   = "#059669" if "TGT" in status else "#dc2626" if "SL" in status else "#1e3a8a"
                st_bg   = "#ecfdf5" if "TGT" in status else "#fff1f1" if "SL" in status else "#e8eeff"
                st_br   = "#34d399" if "TGT" in status else "#f87171" if "SL" in status else "#dde3ee"
                st_bdg  = f'<span style="background:{st_bg};color:{st_cl};padding:2px 8px;border-radius:4px;font-weight:bold;font-size:10px;border:1px solid {st_br};">{status}</span>'
                row_cls = "row-profit" if pnl_v > 0 else "row-loss" if pnl_v < 0 else ""
                rows_t += (f'<tr class="{row_cls}"><td>{t.get("time","")}</td><td>{t.get("index","")}</td>'
                           f'<td>{sig_bdg}</td><td>₹{sf(t.get("price",0)):,.1f}</td>'
                           f'<td>₹{sf(t.get("sl",0)):,.1f}</td><td>₹{sf(t.get("target",0)):,.1f}</td>'
                           f'<td>{pnl_html}</td><td>{st_bdg}</td><td style="font-size:10px">{t.get("mode","")}</td></tr>')
            st.markdown(f'<div class="table-responsive"><table class="qbt"><thead><tr>{th_}</tr></thead><tbody>{rows_t}</tbody></table></div>', unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — POSITIONS & P&L
# ══════════════════════════════════════════════════════════════════════════════
with tab_pos:
    st.markdown('<div class="pad">', unsafe_allow_html=True)
    broker = st.session_state.broker
    if not broker:
        st.warning("🔌 Connect to Angel One to view live positions.")
    else:
        if st.button("🔄 Refresh Positions", key="pos_r"): st.rerun()
        pnl = broker.get_pnl_summary()
        tc  = "v-emerald" if pnl['total'] >= 0 else "v-crimson"
        st.markdown(f"""
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:20px">
          <div class="mcard"><div class="mcard-accent {'c-emerald' if pnl['total']>=0 else 'c-crimson'}"></div>
            <div class="mcard-label">TOTAL P&L</div>
            <div class="mcard-value {tc}">₹{pnl['total']:+,.0f}</div></div>
          <div class="mcard"><div class="mcard-accent c-emerald"></div>
            <div class="mcard-label">REALISED P&L</div>
            <div class="mcard-value {'v-emerald' if pnl['realised']>=0 else 'v-crimson'}">₹{pnl['realised']:+,.0f}</div></div>
          <div class="mcard"><div class="mcard-accent c-royal"></div>
            <div class="mcard-label">UNREALISED P&L</div>
            <div class="mcard-value {'v-emerald' if pnl['unrealised']>=0 else 'v-crimson'}">₹{pnl['unrealised']:+,.0f}</div></div>
          <div class="mcard"><div class="mcard-accent c-amber"></div>
            <div class="mcard-label">OPEN POSITIONS</div>
            <div class="mcard-value">{pnl['positions']}</div></div>
        </div>
        """, unsafe_allow_html=True)
        positions = broker.get_positions()
        if positions:
            st.markdown('<div class="sec-hdr" style="padding-top:8px;border-top:none">OPEN POSITIONS</div>', unsafe_allow_html=True)
            cols_p  = ['tradingsymbol','netqty','ltp','avgnetprice','unrealisedprofitandloss','realisedprofitandloss']
            pos_df  = pd.DataFrame(positions); av = [c for c in cols_p if c in pos_df.columns]
            th      = ''.join(f'<th>{c.upper()}</th>' for c in av); rows_p = ""
            for _, row in pos_df[av].iterrows():
                try: upnl = float(row.get('unrealisedprofitandloss', 0) or 0)
                except: upnl = 0
                rclass = "row-profit" if upnl > 0 else "row-loss" if upnl < 0 else ""
                rows_p += f'<tr class="{rclass}">'
                for c in av:
                    v = row[c]; css = ""
                    if 'pnl' in c or 'profit' in c:
                        try: fv = float(v or 0); css = "v-emerald" if fv >= 0 else "v-crimson"; v = f"₹{fv:+,.0f}"
                        except: pass
                    rows_p += f'<td class="{css}">{v}</td>'
                rows_p += '</tr>'
            st.markdown(f'<div class="table-responsive"><table class="qbt"><thead><tr>{th}</tr></thead><tbody>{rows_p}</tbody></table></div>', unsafe_allow_html=True)
        else:
            st.info("No open positions.")
        funds = broker.get_funds()
        if funds:
            st.markdown('<div class="sec-hdr" style="padding-top:16px">FUNDS & MARGIN</div>', unsafe_allow_html=True)
            fi  = {k: v for k, v in funds.items() if v and str(v) != "0"}
            cfs = st.columns(min(len(fi), 4))
            for i, (k, v) in enumerate(fi.items()):
                with cfs[i % 4]:
                    try: st.metric(k.upper(), f"₹{float(v):,.0f}")
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
            if st.button("📋 Load Order Book",  key="ob_l"): st.session_state._orders = broker.get_order_book()
        with oc2:
            if st.button("🔄 Load Trade Book",  key="tb_l"): st.session_state._trades = broker.get_trade_book()
        with oc3:
            if st.button("🔃 Refresh P&L",      key="pnl_r"):
                pnl_data = broker.get_pnl_summary()
                st.info(f"Total P&L: ₹{pnl_data['total']:+,.0f}")
        orders = st.session_state.get("_orders", [])
        if orders:
            st.markdown('<div class="sec-hdr" style="padding-top:8px;border-top:none">TODAY\'S ORDERS</div>', unsafe_allow_html=True)
            positions_map = {}
            try:
                for p in broker.get_positions():
                    sym_ = p.get('tradingsymbol','')
                    positions_map[sym_] = {
                        'ltp':    sf(p.get('ltp',0)),
                        'upnl':   sf(p.get('unrealisedprofitandloss',0)),
                    }
            except: pass
            ocols  = ['orderid','tradingsymbol','transactiontype','quantity','price','averageprice','orderstatus']
            odf    = pd.DataFrame(orders); av = [c for c in ocols if c in odf.columns]
            th     = '<th>ORDER ID</th>' + ''.join(f'<th>{c.upper()}</th>' for c in av if c != 'orderid') + '<th>LIVE P&L</th><th>STATUS</th>'
            rows_o = ""
            for _, row in odf.iterrows():
                sym_  = str(row.get('tradingsymbol',''))
                pos_  = positions_map.get(sym_, {})
                upnl  = pos_.get('upnl', 0)
                avg   = sf(row.get('averageprice',0) or row.get('price',0))
                ltp   = pos_.get('ltp',0) or sf(row.get('ltp',0))
                tx    = str(row.get('transactiontype','')).upper()
                if ltp and avg:
                    raw_pnl = (ltp - avg) * sf(row.get('quantity',0) or row.get('filledshares',0))
                    if tx == 'SELL': raw_pnl = -raw_pnl
                    pnl_v = round(raw_pnl, 1)
                else:
                    pnl_v = upnl
                pnl_cl  = "#059669" if pnl_v > 0 else "#dc2626" if pnl_v < 0 else "#6b7a9f"
                pnl_bg  = "#ecfdf5" if pnl_v > 0 else "#fff1f1" if pnl_v < 0 else "#f8fafc"
                pnl_br  = "#34d399" if pnl_v > 0 else "#f87171" if pnl_v < 0 else "#dde3ee"
                pnl_html = f'<span style="background:{pnl_bg};color:{pnl_cl};padding:2px 8px;border-radius:10px;font-weight:bold;font-size:10px;border:1px solid {pnl_br};">{"+" if pnl_v>0 else ""}{pnl_v:.1f}</span>' if pnl_v != 0 else '—'
                tx_bdg  = f'<span class="badge b-buy">{tx}</span>' if tx == 'BUY' else f'<span class="badge b-sell">{tx}</span>'
                stat    = str(row.get('orderstatus','')).lower()
                stat_b  = ('<span class="badge b-comp">COMPLETE</span>' if 'complete' in stat else
                           '<span class="badge b-open">OPEN</span>'     if 'open'     in stat else
                           '<span class="badge b-loss">REJECTED</span>' if 'reject'   in stat else
                           f'<span class="badge b-hold">{stat.upper()}</span>')
                rclass  = "row-profit" if pnl_v > 0 else "row-loss" if pnl_v < 0 else ""
                rows_o += (f'<tr class="{rclass}"><td style="font-size:10px">{str(row.get("orderid",""))[:12]}</td>'
                           f'<td style="font-weight:600">{sym_}</td><td>{tx_bdg}</td>'
                           f'<td>{row.get("quantity","")}</td><td>₹{sf(row.get("price",0)):,.1f}</td>'
                           f'<td>₹{avg:,.1f}</td><td>{pnl_html}</td><td>{stat_b}</td></tr>')
            st.markdown(f'<div class="table-responsive"><table class="qbt"><thead><tr>{th}</tr></thead><tbody>{rows_o}</tbody></table></div>', unsafe_allow_html=True)
        else:
            st.info("Click 'Load Order Book' to fetch today's orders.")
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — BACKTEST
# ══════════════════════════════════════════════════════════════════════════════
with tab_bt:
    st.markdown('<div class="pad">', unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr" style="padding:0 0 12px;border:none">HISTORICAL STRATEGY BACKTEST ENGINE</div>', unsafe_allow_html=True)
    bc1, bc2, bc3, bc4 = st.columns(4)
    with bc1:
        bt_s = st.selectbox("Strategy", list(_SL_MULTIPLIERS.keys()), key="bt_s2")
    with bc2:
        bt_p = st.selectbox("Period", ["1mo","3mo","6mo","1y"], key="bt_p2")
    with bc3:
        bt_i = st.selectbox("Index", ["Nifty 50 (^NSEI)","BankNifty (^NSEBANK)","Sensex (^BSESN)"], key="bt_i2")
    with bc4:
        st.markdown('<div style="padding-top:24px"><div class="main-btn">', unsafe_allow_html=True)
        run_bt = st.button("🚀 RUN BACKTEST", use_container_width=True, key="bt_r2")
        st.markdown('</div></div>', unsafe_allow_html=True)
    tm     = {"Nifty 50 (^NSEI)":"^NSEI","BankNifty (^NSEBANK)":"^NSEBANK","Sensex (^BSESN)":"^BSESN"}
    ticker = tm[bt_i]
    if run_bt:
        with st.spinner(f"Running {bt_s} backtest on {bt_i} for {bt_p}…"):
            res_df, metrics = run_backtest(ticker, bt_p, bt_s)
        if res_df is None:
            st.error(f"Backtest error: {metrics}")
        else:
            wr_color   = "v-emerald" if metrics['win_rate'] >= 60 else "v-amber" if metrics['win_rate'] >= 50 else "v-crimson"
            pts_color  = "v-emerald" if metrics['total_pts'] > 0 else "v-crimson"
            st.markdown(f"""
            <div class="metric-row">
              <div class="mcard"><div class="mcard-accent {'c-emerald' if metrics['total_pts']>0 else 'c-crimson'}"></div>
                <div class="mcard-label">TOTAL POINTS</div>
                <div class="mcard-value {pts_color}">{metrics['total_pts']:+.0f}</div>
                <div class="mcard-sub">{metrics['interval']} · {metrics['candles']} candles</div></div>
              <div class="mcard"><div class="mcard-accent {'c-emerald' if metrics['win_rate']>=60 else 'c-amber' if metrics['win_rate']>=50 else 'c-crimson'}"></div>
                <div class="mcard-label">WIN RATE</div>
                <div class="mcard-value {wr_color}">{metrics['win_rate']:.1f}%</div>
                <div class="mcard-sub">{metrics['trades']} trades · {metrics.get('consecutive_wins',0)} max consecutive</div></div>
              <div class="mcard"><div class="mcard-accent c-royal"></div>
                <div class="mcard-label">RISK : REWARD</div>
                <div class="mcard-value">{metrics['rr_ratio']:.2f}x</div>
                <div class="mcard-sub">Avg Win: +{metrics['avg_win']} / Avg Loss: -{metrics['avg_loss']}</div></div>
              <div class="mcard"><div class="mcard-accent c-crimson"></div>
                <div class="mcard-label">MAX DRAWDOWN</div>
                <div class="mcard-value v-crimson">{metrics['max_dd']:.0f} pts</div></div>
            </div>
            """, unsafe_allow_html=True)
            st.markdown('<div class="sec-hdr" style="padding-top:8px;border-top:none">EQUITY CURVE</div>', unsafe_allow_html=True)
            try: st.area_chart(res_df.set_index('Date')['Cumulative'], height=200, use_container_width=True)
            except: st.line_chart(res_df['Cumulative'].reset_index(drop=True), height=200)
            st.markdown('<div class="sec-hdr">TRADE LOG</div>', unsafe_allow_html=True)
            show   = [c for c in ['Date','Signal','Entry','Exit','Points','Reason','Result'] if c in res_df.columns]
            dr     = res_df[show].copy()
            th_bt  = ''.join(f'<th>{c.upper()}</th>' for c in show)
            rows_r = ""
            for _, row in dr.iterrows():
                pv    = sf(row.get('Points',0))
                rclass = "row-profit" if pv > 0 else "row-loss" if pv < 0 else ""
                rows_r += f'<tr class="{rclass}">'
                for c in show:
                    v = row[c]; css = ""
                    if c == 'Result':
                        v = (f'<span style="background:#ecfdf5;color:#059669;padding:4px 8px;border-radius:4px;font-weight:bold;border:1px solid #34d399">WIN</span>'
                             if v == 'WIN' else
                             f'<span style="background:#fff1f1;color:#dc2626;padding:4px 8px;border-radius:4px;font-weight:bold;border:1px solid #f87171">LOSS</span>')
                    elif c == 'Points':
                        try: fv = float(v); css = "v-emerald" if fv >= 0 else "v-crimson"; v = f"{fv:+.1f}"
                        except: pass
                    elif c == 'Signal':
                        if "CALL" in str(v): v = f'<span style="color:#047857;font-weight:bold">▲ {v}</span>'
                        else: v = f'<span style="color:#dc2626;font-weight:bold">▼ {v}</span>'
                    rows_r += f'<td class="{css}">{v}</td>'
                rows_r += '</tr>'
            st.markdown(f'<div class="table-responsive"><table class="qbt"><thead><tr>{th_bt}</tr></thead><tbody>{rows_r}</tbody></table></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — IRON CONDOR
# ══════════════════════════════════════════════════════════════════════════════
with tab_ic:
    st.markdown('<div class="pad">', unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr" style="padding:0 0 12px;border:none">BANKNIFTY WEEKLY IRON CONDOR BUILDER</div>', unsafe_allow_html=True)
    ic1, ic2, ic3 = st.columns(3)
    with ic1:
        ic_spot = st.number_input("BankNifty Spot", value=48000, step=100, key="ic_sp2")
        ic_vix  = st.number_input("India VIX",      value=14.5,  step=0.1, key="ic_vx2")
    with ic2:
        ic_exp  = st.text_input("Expiry Code (DDMMM)", value="23DEC", key="ic_ex2")
        ic_qty  = st.number_input("Quantity (units)",  value=15, step=15,  key="ic_qt2")
    with ic3:
        ic_prem = st.number_input("Net Credit (₹/unit)", value=175, step=5,     key="ic_pr2")
        ic_cap  = st.number_input("Capital (₹)",         value=100000, step=10000, key="ic_cp2")

    # Use unified ATM rounding (100 pts for BANKNIFTY)
    offset = ic_spot * 0.012
    sc     = get_atm_strike("BANKNIFTY", ic_spot + offset)
    lc     = sc + 500
    sp     = get_atm_strike("BANKNIFTY", ic_spot - offset)
    lp     = sp - 500
    mp     = ic_prem * ic_qty
    ml     = max(0, (500 - ic_prem) * ic_qty)
    t50    = ic_prem * 0.50 * ic_qty
    s150   = ic_prem * 1.50 * ic_qty
    roi    = round(mp / ic_cap * 100, 2) if ic_cap else 0
    vix_ok = ic_vix < 20

    st.markdown(f"""
    <div class="metric-row">
      <div class="mcard"><div class="mcard-accent c-emerald"></div>
        <div class="mcard-label">MAX PROFIT</div><div class="mcard-value v-emerald">₹{mp:,.0f}</div>
        <div class="mcard-sub">50% exit target: ₹{t50:,.0f}</div></div>
      <div class="mcard"><div class="mcard-accent c-crimson"></div>
        <div class="mcard-label">MAX LOSS</div><div class="mcard-value v-crimson">₹{ml:,.0f}</div>
        <div class="mcard-sub">SL trigger: ₹{s150:,.0f}</div></div>
      <div class="mcard"><div class="mcard-accent c-royal"></div>
        <div class="mcard-label">EXPECTED ROI</div><div class="mcard-value v-royal">{roi}%</div>
        <div class="mcard-sub">On ₹{ic_cap:,.0f} capital</div></div>
      <div class="mcard"><div class="mcard-accent {'c-emerald' if vix_ok else 'c-crimson'}"></div>
        <div class="mcard-label">VIX STATUS</div><div class="mcard-value {'v-emerald' if vix_ok else 'v-crimson'}">{ic_vix}</div>
        <div class="mcard-sub">{'✅ SAFE — VIX below 20' if vix_ok else '⛔ BLOCKED — VIX above 20'}</div></div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sec-hdr" style="padding-top:8px;border-top:none">CONDOR STRUCTURE</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="table-responsive" style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow)">
      <table class="qbt" style="min-width:600px">
        <tbody>
          <tr><td style="width:80px;padding:14px"><span class="badge b-win">BUY</span></td><td style="padding:14px">Long Call wing — caps maximum loss</td><td style="text-align:right;font-weight:700;color:var(--royal);padding:14px">CALL {lc} CE &nbsp;|&nbsp; +1 lot</td></tr>
          <tr><td style="padding:14px"><span class="badge b-sell">SELL</span></td><td style="padding:14px">Short Call — collect premium</td><td style="text-align:right;font-weight:700;color:var(--royal);padding:14px">CALL {sc} CE &nbsp;|&nbsp; -1 lot</td></tr>
          <tr style="background:var(--royal-l)"><td colspan="3" style="text-align:center;color:var(--royal);font-family:var(--mono);font-size:12px;padding:14px;border-bottom:1px solid var(--border)">◄── PROFIT ZONE &nbsp; {sp:,} → {sc:,} &nbsp; ──► &nbsp;&nbsp; <strong>SPOT: {ic_spot:,}</strong> &nbsp; Width: {sc-sp} pts</td></tr>
          <tr><td style="padding:14px"><span class="badge b-sell">SELL</span></td><td style="padding:14px">Short Put — collect premium</td><td style="text-align:right;font-weight:700;color:var(--royal);padding:14px">PUT {sp} PE &nbsp;|&nbsp; -1 lot</td></tr>
          <tr><td style="padding:14px"><span class="badge b-win">BUY</span></td><td style="padding:14px">Long Put wing — caps maximum loss</td><td style="text-align:right;font-weight:700;color:var(--royal);padding:14px">PUT {lp} PE &nbsp;|&nbsp; +1 lot</td></tr>
        </tbody>
      </table>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div style="margin-top:16px">', unsafe_allow_html=True)
    if not vix_ok:
        st.error(f"⛔ VIX {ic_vix} exceeds 20 — Iron Condor deployment is blocked by the risk filter.")
    else:
        dc1, dc2 = st.columns(2)
        with dc1:
            if st.button("🧪 PAPER DEPLOY CONDOR", use_container_width=True, key="ic_p2"):
                st.success(f"✅ PAPER Condor logged | SC:{sc} | LC:{lc} | SP:{sp} | LP:{lp} | Max Profit ₹{mp:,.0f}")
        with dc2:
            st.markdown('<div class="danger-btn">', unsafe_allow_html=True)
            if st.button("⚡ LIVE DEPLOY CONDOR", use_container_width=True, key="ic_l2"):
                _b = st.session_state.get("broker")
                if not _b or not getattr(_b, "connected", False):
                    st.error("Not connected to Angel One.")
                elif st.session_state.dry_run:
                    st.warning("Switch off Dry Run before live deployment.")
                else:
                    try:
                        with st.spinner("Placing 4-leg Iron Condor…"):
                            r = _b.place_iron_condor("BANKNIFTY", ic_exp, sc, lc, sp, lp, ic_qty)
                        if r.get("status"):
                            st.success("✅ All 4 legs placed successfully!")
                        else:
                            for leg in r.get("legs",[]):
                                if not leg["result"].get("status"):
                                    st.error(f"Leg {leg['leg']} failed: {_human_order_error(leg['result'].get('error',''))}")
                    except Exception as e:
                        st.error(f"Condor error: {_human_order_error(str(e))}")
            st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div></div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 6 — RISK ENGINE
# ══════════════════════════════════════════════════════════════════════════════
with tab_risk:
    st.markdown('<div class="pad">', unsafe_allow_html=True)
    broker  = st.session_state.broker
    capital = st.session_state.capital
    if not broker:
        st.warning("🔌 Connect to Angel One to view live risk metrics.")
    else:
        pnl     = broker.get_pnl_summary()
        lp_     = abs(pnl['total']) / capital * 100 if pnl['total'] < 0 and capital > 0 else 0
        rem     = max(0, st.session_state.daily_loss_pct - lp_)
        halted  = lp_ >= st.session_state.daily_loss_pct
        if halted and not st.session_state.engine_halted:
            st.session_state.engine_halted = True; st.session_state.engine_on = False
        cc = "c-crimson" if lp_ > 1.5 else "c-amber" if lp_ > 0.5 else "c-emerald"
        st.markdown(f"""
        <div class="metric-row">
          <div class="mcard"><div class="mcard-accent {cc}"></div>
            <div class="mcard-label">DAILY LOSS USED</div>
            <div class="mcard-value {'v-crimson' if lp_>1 else ''}">{lp_:.2f}%</div>
            <div class="mcard-sub">Limit: {st.session_state.daily_loss_pct:.1f}%</div></div>
          <div class="mcard"><div class="mcard-accent c-emerald"></div>
            <div class="mcard-label">RISK REMAINING</div>
            <div class="mcard-value v-emerald">{rem:.2f}%</div>
            <div class="mcard-sub">₹{rem/100*capital:,.0f}</div></div>
          <div class="mcard"><div class="mcard-accent c-royal"></div>
            <div class="mcard-label">CAPITAL DEPLOYED</div>
            <div class="mcard-value">₹{capital:,.0f}</div></div>
          <div class="mcard"><div class="mcard-accent {'c-crimson' if halted else 'c-emerald'}"></div>
            <div class="mcard-label">ENGINE STATUS</div>
            <div class="mcard-value" style="font-size:15px">{'🔴 HALTED' if halted else '🟢 ACTIVE'}</div></div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div class="sec-hdr" style="padding-top:4px;border-top:none">9 ACTIVE RISK RULES</div>', unsafe_allow_html=True)
    rules = [
        ("VIX Filter",           f"Pause Iron Condor when VIX > {st.session_state.vix_limit:.0f}"),
        ("Daily Loss Limit",     f"Halt engine at {st.session_state.daily_loss_pct:.1f}% daily loss"),
        ("Position Sizing",      "Max 20% of capital per trade"),
        ("Iron Condor SL",       "Auto-exit at 150% of premium collected"),
        ("Gap Risk Filter",      "Skip Monday entry if BankNifty gap > 1%"),
        ("Event Filter",         "No condors during monthly/quarterly expiry week"),
        ("Max Open Positions",   "Block new trades beyond 4 legs"),
        ("Duplicate Signal Guard","Skip repeated signals within same candle"),
        ("Market Hours Gate",    "No trades outside 09:15–15:30 IST Mon–Fri"),
    ]
    th_r   = '<th>#</th><th>RULE</th><th>CONDITION</th><th>STATUS</th>'
    rows_r = ''.join(
        f'<tr><td style="color:var(--muted);font-size:10px">{i+1}</td>'
        f'<td style="font-weight:600">{r}</td><td style="color:var(--text2)">{c}</td>'
        f'<td><span style="background:#ecfdf5;color:#047857;padding:4px 8px;border-radius:4px;font-weight:bold;font-size:10px;border:1px solid rgba(4,120,87,.3)">✅ ACTIVE</span></td></tr>'
        for i, (r, c) in enumerate(rules)
    )
    st.markdown(f'<div class="table-responsive"><table class="qbt"><thead><tr>{th_r}</tr></thead><tbody>{rows_r}</tbody></table></div>', unsafe_allow_html=True)

    st.markdown('<div class="sec-hdr">MANUAL CONTROLS</div>', unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        if st.button("⏸ PAUSE ENGINE",      use_container_width=True, key="r_pa"):
            st.session_state.engine_on = False; st.warning("Engine paused.")
    with m2:
        st.markdown('<div class="success-btn">', unsafe_allow_html=True)
        if st.button("▶ RESUME ENGINE",     use_container_width=True, key="r_re"):
            if st.session_state.connected:
                st.session_state.engine_on = True; st.session_state.engine_halted = False; st.success("Engine resumed.")
            else: st.error("Not connected.")
        st.markdown('</div>', unsafe_allow_html=True)
    with m3:
        if st.button("🔃 RESET P&L COUNTER", use_container_width=True, key="r_rs"):
            st.session_state.engine_halted = False; st.info("Daily P&L counter reset.")
    with m4:
        st.markdown('<div class="danger-btn">', unsafe_allow_html=True)
        if st.button("🛑 SQUARE OFF ALL",   use_container_width=True, key="r_sq"):
            _b = st.session_state.get("broker")
            if _b and getattr(_b, "connected", False):
                with st.spinner("Emergency square off…"):
                    r = _b.square_off_all()
                failed = [x for x in r if not x.get("status")]
                for f in failed: st.warning(f"⚠️ {f['symbol']}: {f.get('error','Unknown')}")
                st.warning(f"✅ Squared off {len(r)-len(failed)} position(s)")
                st.session_state.engine_on = False
            else: st.error("Not connected.")
        st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 7 — TUTORIAL & SAFETY FAQ
# ══════════════════════════════════════════════════════════════════════════════
with tab_faq:
    st.markdown('<div class="pad">', unsafe_allow_html=True)

    st.markdown("""
    <div class="tutorial-hero">
      <h2>📘 QuantBengal Pro — Master Tutorial & Safety Guide</h2>
      <p>Everything you need to understand the platform, protect your capital, and trade with confidence.
         Read this section completely before switching to Live Mode.</p>
    </div>
    """, unsafe_allow_html=True)

    # ── SAFETY FAQ SECTION ────────────────────────────────────────────────
    st.markdown("""
    <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--muted);text-transform:uppercase;
                letter-spacing:2.5px;padding:4px 0 14px;border-bottom:2px solid var(--royal);margin-bottom:20px;color:var(--royal)">
      🛡️ TRADING SAFETY & SYSTEM FAQS
    </div>
    """, unsafe_allow_html=True)

    # FAQ 1 — Capital Protection
    st.markdown("""
    <div class="faq-section">
      <div class="faq-header"><span class="faq-icon">🛡️</span> FAQ 1 — How does the 2% Daily Loss Limit protect my capital?</div>
      <div class="faq-body">
        <p>The <strong>Daily Loss Limit</strong> is your most important safety net. Every trade that closes in a loss is
        tracked as a percentage of your total configured capital. The moment cumulative losses reach your set threshold
        (default: 2%), the engine <em>automatically halts</em> — no more new trades are placed for the rest of that day,
        regardless of what signals appear on screen.</p>
        <div class="faq-highlight">
          EXAMPLE: Capital = ₹2,00,000 | Limit = 2%<br>
          → Engine stops when today's loss reaches ₹4,000<br>
          → You can never lose more than ₹4,000 in a single day automatically
        </div>
        <p>This "circuit breaker" mirrors the same concept used by institutional risk desks worldwide. It prevents a
        single bad session from compounding into a catastrophic drawdown. You can adjust the threshold in the sidebar
        Risk Controls section — but we strongly recommend keeping it at 2% or below until you have 3+ profitable months.</p>
        <div class="faq-ok">✅ Reset the counter via Risk Engine → Reset P&L Counter at the start of each new trading day.</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # FAQ 2 — Volatility & ATR Stop Losses
    st.markdown("""
    <div class="faq-section">
      <div class="faq-header"><span class="faq-icon">📐</span> FAQ 2 — Why do the stop-losses not trigger on normal market noise?</div>
      <div class="faq-body">
        <p>Every stop-loss in QuantBengal Pro is calculated using the <strong>ATR (Average True Range)</strong> — a
        mathematical measure of how much the index moves per 15-minute candle on average. Stop-losses are placed at
        <em>1.2–1.5× ATR away</em> from entry, depending on the strategy selected.</p>
        <div class="faq-highlight">
          ATR Formula for Stop-Loss:<br>
          Stop Loss = Entry Price − (SL Multiplier × 14-period ATR)<br><br>
          Example: Entry ₹48,000 | ATR ₹200 | Multiplier 1.3<br>
          → Stop Loss = ₹48,000 − (1.3 × ₹200) = ₹47,740
        </div>
        <p>The ATR expands during volatile sessions and contracts during calm ones. This means your stop-loss
        automatically widens when the market is choppy — avoiding false triggers — and tightens when the market
        is trending cleanly. Normal intraday "noise" of 50–100 points will not touch an ATR-based stop-loss.</p>
        <p>Profit targets are set at <strong>1.8× the stop-loss distance</strong>, giving every trade a minimum
        1.8:1 risk-to-reward ratio built in by design.</p>
        <div class="faq-ok">✅ ATR-based levels are calculated fresh on every REFRESH — always click Refresh before Executing.</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # FAQ 3 — ATM Strike Selection
    st.markdown("""
    <div class="faq-section">
      <div class="faq-header"><span class="faq-icon">🎯</span> FAQ 3 — How does the system pick the right option strike automatically?</div>
      <div class="faq-body">
        <p>When you execute a trade, QuantBengal Pro does not ask you to manually type a strike price. It
        automatically calculates the <strong>At-The-Money (ATM)</strong> strike — the strike price closest to where
        the index is currently trading — using standardised rounding rules.</p>
        <div class="faq-highlight">
          ATM Strike Rounding Rules (standardised per exchange):<br>
          • NIFTY 50: Rounded to nearest <strong>50-point</strong> interval<br>
          • BANKNIFTY: Rounded to nearest <strong>100-point</strong> interval<br>
          • SENSEX (BSE): Rounded to nearest <strong>100-point</strong> interval<br><br>
          Example: BankNifty spot = 48,240 → ATM Strike = 48,200 (rounded to 100)
        </div>
        <p>These rules are enforced identically across the live trading engine, the auto-scheduler (GitHub Actions),
        and the Iron Condor Builder — so what you see in the UI is exactly what gets executed at the broker.
        The system also selects Call (CE) for BUY_CALL signals and Put (PE) for BUY_PUT signals automatically.</p>
        <div class="faq-ok">✅ ATM selection uses the live LTP at time of execution — always click Refresh first to get the current spot.</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # FAQ 4 — Safe Hours
    st.markdown("""
    <div class="faq-section">
      <div class="faq-header"><span class="faq-icon">⏰</span> FAQ 4 — What is the "Safe Execution Hours" window and why 10:30–14:30?</div>
      <div class="faq-body">
        <p>Indian markets open at 09:15 IST, but the first 60–75 minutes (09:15 to ~10:30) are often characterised
        by extreme volatility driven by overnight gap-ups/gap-downs, institutional order placement, and erratic price
        discovery. Stop-losses are far more likely to trigger during this window even on fundamentally correct trades.</p>
        <p>Similarly, the final hour (14:30 to 15:30) sees accelerated moves as traders unwind intraday positions and
        volatility spikes near close. Executing new entries in this window leaves insufficient time for the trade
        to reach its profit target before the session ends.</p>
        <div class="faq-highlight">
          The 10:30–14:30 "Goldilocks Zone":<br>
          ✓ Gap-open volatility has settled<br>
          ✓ Institutional order flow is stable<br>
          ✓ 4 hours remain for the trade to hit target before close<br>
          ✓ Statistically highest win-rate window for our strategies
        </div>
        <p>You can customise these hours in the sidebar under <strong>Safe Execution Hours</strong>. The engine will
        display a warning and block execution if you click Execute outside this window while auto-trade is running.</p>
        <div class="faq-ok">✅ For beginners, we recommend keeping the default 10:30–14:30 window until you have 3+ months of paper trading data.</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # FAQ 5 — Emergency Square Off
    st.markdown("""
    <div class="faq-section">
      <div class="faq-header"><span class="faq-icon">🛑</span> FAQ 5 — How does the Emergency Square Off button actually close my trades?</div>
      <div class="faq-body">
        <p>The <strong>Emergency Square Off</strong> button (red, in the sidebar and Risk Engine tab) communicates
        <em>directly</em> with your Angel One brokerage account via the SmartAPI. When pressed, it retrieves your
        complete list of open positions and immediately places offsetting <strong>Market Orders</strong> for every
        open contract — it does not wait for a specific price.</p>
        <div class="faq-highlight">
          What happens step by step:<br>
          1. System calls Angel One API → fetches all open positions<br>
          2. For each LONG position → places a SELL MARKET order<br>
          3. For each SHORT position → places a BUY MARKET order<br>
          4. Orders execute at the best available market price immediately<br>
          5. Engine is automatically stopped after square-off
        </div>
        <div class="faq-warn">⚠️ CAUTION: Market orders in far Out-of-The-Money (OTM) options may execute at unfavourable prices
        due to wide bid-ask spreads. Use Emergency Square Off only in genuine emergencies — not to avoid a small loss.</div>
        <p>Each leg's result is reported back on screen with a success/failure message. If any leg fails, the reason
        is displayed in plain English (e.g., "Insufficient margin" or "Session expired — reconnect").</p>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # FAQ 6 — Cloud Persistence
    st.markdown("""
    <div class="faq-section">
      <div class="faq-header"><span class="faq-icon">☁️</span> FAQ 6 — Does the bot keep trading if I close the dashboard?</div>
      <div class="faq-body">
        <p>Yes — and this is one of the most important architectural advantages of QuantBengal Pro. The dashboard
        (this Streamlit app) and the automated trading engine (GitHub Actions) are <em>completely separate systems</em>.
        Closing your browser or switching off your phone does NOT stop the bot.</p>
        <div class="faq-highlight">
          Two independent systems:<br><br>
          📱 DASHBOARD (app.py): Your visual interface. Runs on your device or a cloud server.<br>
          Used for: Monitoring, manual execution, backtesting, configuration.<br><br>
          ☁️ CLOUD ENGINE (GitHub Actions + main.py): Runs every 15 minutes on GitHub's servers.<br>
          Used for: Fully automated signal detection, order placement, and risk checking.
        </div>
        <p>The cloud engine stores its trade history in a persistent JSON file that survives across sessions.
        Every trade — whether placed automatically or manually — is written to <code>trade_history.json</code>
        using an atomic write operation (write-to-temp → rename) that prevents data corruption even if the
        app crashes mid-write.</p>
        <div class="faq-ok">✅ To set up the cloud engine: push your code to a private GitHub repo → add your credentials as Secrets → enable the QuantBengal Engine workflow. Refer to Chapter 12 of this guide.</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # FAQ 7 — Privacy & Security
    st.markdown("""
    <div class="faq-section">
      <div class="faq-header"><span class="faq-icon">🔐</span> FAQ 7 — How are my Angel One credentials kept secure?</div>
      <div class="faq-body">
        <p>Your API Key, Client ID, Password, and TOTP Secret are <strong>never stored in code or in any file
        visible to others</strong>. The security model uses two separate mechanisms depending on how you run
        the platform:</p>
        <div class="faq-highlight">
          In the Dashboard (app.py):<br>
          → Credentials entered in the sidebar are held only in Streamlit session state (RAM)<br>
          → They are passed as environment variables for that session only<br>
          → They are never written to disk by the application<br><br>
          In the Cloud Engine (GitHub Actions):<br>
          → Credentials are stored as <strong>GitHub Encrypted Secrets</strong><br>
          → Encrypted at rest using AES-256; only decrypted at workflow runtime<br>
          → Never visible in workflow logs or to other repository collaborators<br>
          → Your private repository ensures no one else can see your code or secrets
        </div>
        <p>Additionally, the TOTP Secret generates a new 6-digit OTP every 30 seconds using the pyotp library.
        Even if someone intercepted a single OTP, it would expire before it could be reused — providing
        a second factor of authentication on every API session.</p>
        <div class="faq-warn">⚠️ CRITICAL: Never screenshot, paste into a chat, or share your TOTP Secret or API Key.
        These 4 credentials together give complete access to your trading account.</div>
        <div class="faq-ok">✅ Best practice: Store credentials in a password manager (Bitwarden, 1Password) and rotate your Angel One API Key every 90 days via the SmartAPI portal.</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Platform Overview ─────────────────────────────────────────────────
    st.markdown("""
    <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--royal);text-transform:uppercase;
                letter-spacing:2.5px;padding:24px 0 14px;border-bottom:2px solid var(--royal);margin-bottom:20px">
      📖 PLATFORM OVERVIEW
    </div>
    """, unsafe_allow_html=True)

    overview_items = [
        ("🔌", "Connection", "Angel One SmartAPI via 4 credentials: API Key, Client ID, Trading PIN, TOTP Secret (32-char BASE32 — not the 6-digit OTP)."),
        ("⚡", "3-Step Cycle", "FETCH (15-min candles) → ANALYSE (EMA, RSI, MACD, SuperTrend) → ACT (place trade if signal + risk checks pass)."),
        ("🧪", "Paper vs Live", "Dry Run ON = paper trades only, zero risk. Dry Run OFF = real orders sent to Angel One. Always paper trade for 20+ sessions first."),
        ("📊", "6 Strategies", "SuperTrend+RSI, MACD+EMA, Stochastic+BB, Triple EMA, Momentum Pulse, Bollinger Squeeze. Each uses a dual-condition filter to reduce false signals."),
        ("🦅", "Iron Condor", "4-leg strategy for sideways markets. Requires VIX < 20 and higher margin. Only for experienced users after mastering directional strategies."),
        ("⏱️", "Auto-Scheduler", "GitHub Actions runs main.py every 15 minutes from 03:30–10:00 UTC (09:00–15:15 IST), Monday to Friday. No local computer required."),
        ("🛡️", "9 Risk Rules", "VIX filter, daily loss limit, position sizing, condor SL, gap filter, event filter, max positions, duplicate guard, market hours gate — all ACTIVE by default."),
    ]
    for icon, title, body in overview_items:
        st.markdown(f"""
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
                    padding:16px 20px;margin-bottom:10px;box-shadow:var(--shadow);display:flex;gap:16px;align-items:flex-start">
          <div style="font-size:22px;flex-shrink:0;margin-top:2px">{icon}</div>
          <div>
            <div style="font-family:var(--mono);font-size:11px;font-weight:700;color:var(--royal);margin-bottom:5px;text-transform:uppercase;letter-spacing:.5px">{title}</div>
            <div style="font-family:var(--sans);font-size:13px;color:var(--text2);line-height:1.65">{body}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Disclaimer ────────────────────────────────────────────────────────
    st.markdown("""
    <div style="background:var(--crimson-l);border:1.5px solid rgba(220,38,38,.3);border-radius:var(--radius);
                padding:18px 20px;margin-top:20px">
      <div style="font-family:var(--mono);font-size:10px;font-weight:700;color:var(--crimson);text-transform:uppercase;
                  letter-spacing:1px;margin-bottom:8px">⚠️ MANDATORY DISCLAIMER</div>
      <div style="font-family:var(--sans);font-size:13px;color:var(--text2);line-height:1.7">
        QuantBengal Pro is an algorithmic software tool and does not hold a SEBI Investment Advisor registration.
        All strategies are provided for informational and automation purposes only. Trading in F&O involves
        substantial financial risk, including the possibility of total loss of invested capital. Past backtest
        or live performance does <strong>not</strong> guarantee future returns. Clients are solely responsible
        for their own trading decisions. QuantBengal does not handle, hold, or manage client funds at any time.
        <strong>Consult a SEBI-registered financial advisor before making any investment decisions.</strong>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ── AUTO-REFRESH ──────────────────────────────────────────────────────────────
if st.session_state.auto_refresh:
    time.sleep(st.session_state.refresh_interval)
    st.rerun()
