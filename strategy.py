"""
QuantBengal Engine — strategy.py  v3.1
AUDIT ENHANCEMENTS:
- All 6 strategies 100% synchronized with app.py frontend logic
- Global ATM rounding imported from broker_api (50/100 step)
- RiskManager uses configurable thresholds (no magic numbers)
- IronCondorStrategy uses shared _nfo_symbol + get_atm_strike
- MorningBreakoutStrategy bug fix (orb_low undefined reference fixed)
- Improved logging with human-readable context
"""

import pandas as pd
import numpy as np
import logging
import os
from datetime import datetime, timedelta
import pytz

from ta.trend import EMAIndicator, MACD
from ta.volatility import BollingerBands, AverageTrueRange
from ta.momentum import RSIIndicator, StochasticOscillator

# Import shared ATM helpers from broker_api for consistent strike rounding
from broker_api import get_atm_strike, get_atm_symbol, _nfo_symbol

logger = logging.getLogger(__name__)
IST    = pytz.timezone('Asia/Kolkata')


def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ── SuperTrend calculator (shared with frontend) ─────────────────────────────

def calc_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    """
    Calculates SuperTrend indicator identical to the app.py frontend implementation.
    Returns (supertrend Series, direction Series) where direction 1=bullish, -1=bearish.
    """
    high  = df['high'].astype(float)
    low   = df['low'].astype(float)
    close = df['close'].astype(float)

    atr        = AverageTrueRange(high=high, low=low, close=close, window=period).average_true_range()
    hl2        = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(index=df.index, dtype=float)
    direction  = pd.Series(index=df.index, dtype=int)

    for i in range(1, len(df)):
        if pd.isna(atr.iloc[i]):
            supertrend.iloc[i] = lower_band.iloc[i]
            direction.iloc[i]  = 1
            continue

        prev_st  = supertrend.iloc[i - 1] if not pd.isna(supertrend.iloc[i - 1]) else lower_band.iloc[i]
        prev_dir = direction.iloc[i - 1]  if not pd.isna(direction.iloc[i - 1])  else 1
        curr_c   = float(close.iloc[i])

        if prev_dir == 1:
            curr_st  = max(lower_band.iloc[i], prev_st) if curr_c > prev_st else upper_band.iloc[i]
            curr_dir = 1 if curr_c > curr_st else -1
        else:
            curr_st  = min(upper_band.iloc[i], prev_st) if curr_c < prev_st else lower_band.iloc[i]
            curr_dir = -1 if curr_c < curr_st else 1

        supertrend.iloc[i] = curr_st
        direction.iloc[i]  = curr_dir

    return supertrend, direction


# ─────────────────────────────────────────────────────────────────────────────
#  RISK MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class RiskManager:
    """
    Centralised risk controls.
    All thresholds are configurable — no hidden magic numbers.
    """

    def __init__(
        self,
        capital:           float = 200_000,
        max_daily_loss_pct: float = 2.0,
        max_position_pct:   float = 20.0,
        max_open_positions: int   = 4,
        vix_threshold:      float = 20.0,
        margin_per_lot:     float = 80_000,
    ):
        self.capital             = capital
        self.max_daily_loss_pct  = max_daily_loss_pct
        self.max_position_pct    = max_position_pct
        self.max_open_positions  = max_open_positions
        self.vix_threshold       = vix_threshold
        self.margin_per_lot      = margin_per_lot
        self.daily_pnl           = 0.0
        self.halted              = False

    def check_vix(self, vix: float) -> bool:
        if vix > self.vix_threshold:
            logger.warning(
                f"⚠️  VIX {vix:.1f} exceeds threshold {self.vix_threshold:.1f} — "
                "Iron Condor deployment blocked. Wait for VIX to fall below threshold."
            )
            return False
        return True

    def check_daily_loss(self, current_pnl: float) -> bool:
        if current_pnl >= 0:
            return True
        loss_pct = abs(current_pnl) / self.capital * 100
        if loss_pct >= self.max_daily_loss_pct:
            self.halted = True
            logger.error(
                f"🛑 DAILY LOSS LIMIT HIT — {loss_pct:.2f}% loss exceeds {self.max_daily_loss_pct:.1f}% limit. "
                "Engine halted for the day. Reset via the Risk Engine tab."
            )
            return False
        return True

    def position_size(self, premium_per_lot: float = 0) -> int:
        """Returns number of lots based on available capital allocation."""
        max_capital = self.capital * (self.max_position_pct / 100)
        lots = max(1, int(max_capital / self.margin_per_lot))
        logger.info(f"Position sizing: {lots} lot(s) (max capital: ₹{max_capital:,.0f})")
        return lots

    def is_trading_allowed(self) -> bool:
        if self.halted:
            logger.warning("Engine is halted. Use Risk Engine → Reset P&L Counter to resume.")
        return not self.halted


# ─────────────────────────────────────────────────────────────────────────────
#  MOMENTUM STRATEGY SUITE
#  All 6 algorithms kept 100% identical to the app.py frontend logic.
# ─────────────────────────────────────────────────────────────────────────────

class MomentumStrategy:
    """
    Executes one of the 6 directional strategies.
    Strategy is selected via the STRATEGY_NAME environment variable
    or constructor argument — matching the UI dropdown exactly.
    """

    # SL multipliers per strategy (must match app.py backtest engine)
    _SL_MULTIPLIERS = {
        "SuperTrend + RSI":              1.2,
        "MACD + EMA Confluence":         1.3,
        "Stochastic + BB Mean Reversion": 1.0,
        "Triple EMA + Volume Trend":     1.4,
        "Momentum Pulse (EMA+RSI)":      1.5,
        "Bollinger Squeeze Breakout":    1.1,
    }

    def __init__(self, broker, risk: RiskManager = None, strategy_name: str = ""):
        self.broker         = broker
        self.risk           = risk or RiskManager()
        self._last_signal   = None
        self._position_open = False
        self.active_strategy = (
            strategy_name
            or os.environ.get("STRATEGY_NAME", "SuperTrend + RSI")
        )
        logger.info(f"MomentumStrategy initialised with: {self.active_strategy}")

    def _build_df(self, candles: list) -> pd.DataFrame:
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        for col in ['open', 'high', 'low', 'close', 'vol']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        cs = df['close']

        df['ema_9']  = EMAIndicator(close=cs, window=9).ema_indicator()
        df['ema_21'] = EMAIndicator(close=cs, window=21).ema_indicator()
        df['ema_50'] = EMAIndicator(close=cs, window=50).ema_indicator()
        df['rsi']    = RSIIndicator(close=cs, window=14).rsi()

        df['atr'] = AverageTrueRange(
            high=df['high'], low=df['low'], close=cs, window=14
        ).average_true_range()

        bo = BollingerBands(close=cs, window=20, window_dev=2)
        df['bb_u'] = bo.bollinger_hband()
        df['bb_l'] = bo.bollinger_lband()
        df['bb_m'] = bo.bollinger_mavg()

        mo = MACD(close=cs)
        df['macd']   = mo.macd()
        df['macd_s'] = mo.macd_signal()

        try:
            df['st'], df['st_dir'] = calc_supertrend(df, period=10, multiplier=3.0)
        except Exception:
            df['st']     = cs
            df['st_dir'] = 1

        try:
            sto = StochasticOscillator(
                high=df['high'], low=df['low'], close=cs, window=14, smooth_window=3
            )
            df['stoch_k'] = sto.stoch()
            df['stoch_d'] = sto.stoch_signal()
        except Exception:
            df['stoch_k'] = 50.0
            df['stoch_d'] = 50.0

        return df

    def get_signal(self, candles: list) -> dict:
        if not candles or len(candles) < 30:
            return {"signal": "HOLD", "reason": "Insufficient candle data (need ≥ 30 bars)."}

        df  = self._build_df(candles)
        lat = df.iloc[-1]
        p1  = df.iloc[-2]

        # ── Indicator values ───────────────────────────────────────────────
        c    = _safe_float(lat['close'])
        atr_ = _safe_float(lat.get('atr', c * 0.005)) or c * 0.005
        r    = _safe_float(lat['rsi'])
        e9   = _safe_float(lat['ema_9'])
        e21  = _safe_float(lat['ema_21'])
        e50  = _safe_float(lat.get('ema_50', e21))
        cm   = _safe_float(lat['macd'])
        cs_  = _safe_float(lat['macd_s'])
        pm   = _safe_float(p1['macd'])
        ps_  = _safe_float(p1['macd_s'])
        p1e9  = _safe_float(p1['ema_9'])
        p1e21 = _safe_float(p1['ema_21'])
        bu   = _safe_float(lat['bb_u'])
        bl   = _safe_float(lat['bb_l'])
        bm   = _safe_float(lat['bb_m'])
        st_d = int(_safe_float(lat.get('st_dir', 1) or 1))
        sk   = _safe_float(lat.get('stoch_k', 50))
        sd_  = _safe_float(lat.get('stoch_d', 50))
        p1sk = _safe_float(p1.get('stoch_k', 50))
        p1sd = _safe_float(p1.get('stoch_d', 50))

        # ── SL / Target ────────────────────────────────────────────────────
        sl_mult  = self._SL_MULTIPLIERS.get(self.active_strategy, 1.3)
        tgt_mult = sl_mult * 1.8
        sl_long   = round(c - sl_mult * atr_, 1)
        tgt_long  = round(c + tgt_mult * atr_, 1)
        sl_short  = round(c + sl_mult * atr_, 1)
        tgt_short = round(c - tgt_mult * atr_, 1)

        base = {"price": c, "stop_loss": sl_long, "target": tgt_long, "df": df}
        bull = bear = False
        reason = ""

        # ── Strategy logic (identical to app.py evaluate_signal) ──────────
        if self.active_strategy == "SuperTrend + RSI":
            bull = (st_d == 1  and 50 < r < 75  and e9 > e21)
            bear = (st_d == -1 and 25 < r < 50  and e9 < e21)
            reason = f"SuperTrend {'↑' if bull else '↓'} | RSI {r:.0f} | EMA aligned"

        elif self.active_strategy == "MACD + EMA Confluence":
            bull = (pm <= ps_ and cm > cs_ and cm - cs_ > 0 and e9 > e21 and e21 > e50 and 45 < r < 72)
            bear = (pm >= ps_ and cm < cs_ and cs_ - cm > 0 and e9 < e21 and e21 < e50 and 28 < r < 55)
            reason = f"MACD {'↑ cross' if bull else '↓ cross'} | EMA stack | RSI {r:.0f}"

        elif self.active_strategy == "Stochastic + BB Mean Reversion":
            bull = (p1sk <= p1sd and sk > sd_ and sk < 35 and c < bm and r < 50)
            bear = (p1sk >= p1sd and sk < sd_ and sk > 65 and c > bm and r > 50)
            reason = f"Stochastic {'oversold cross ↑' if bull else 'overbought cross ↓'} | RSI {r:.0f}"

        elif self.active_strategy == "Triple EMA + Volume Trend":
            bull = (e9 > e21 and e21 > e50 and p1e9 > p1e21 and 52 < r < 72)
            bear = (e9 < e21 and e21 < e50 and p1e9 < p1e21 and 28 < r < 48)
            reason = f"Triple EMA {'bull stack ↑' if bull else 'bear stack ↓'} | RSI {r:.0f}"

        elif self.active_strategy == "Bollinger Squeeze Breakout":
            bw  = (bu - bl) / bm if bm else 0.05
            sq  = bw < 0.04
            bull = (sq and c > bu and r > 55 and cm > cs_)
            bear = (sq and c < bl and r < 45 and cm < cs_)
            reason = f"BB Squeeze {'breakout ↑' if bull else 'breakdown ↓'} | RSI {r:.0f}"

        else:  # Momentum Pulse (EMA+RSI) — default
            bull = (p1e9 <= p1e21 and e9 > e21 and r > 55 and cm > cs_)
            bear = (p1e9 >= p1e21 and e9 < e21 and r < 45 and cm < cs_)
            reason = f"EMA crossover {'↑' if bull else '↓'} | RSI {r:.0f} | MACD conf"

        if bull:
            return {**base, "signal": "BUY_CALL", "reason": reason}
        if bear:
            return {**base, "signal": "BUY_PUT", "reason": reason,
                    "stop_loss": sl_short, "target": tgt_short}
        trend_label = "BULLISH" if st_d == 1 else "BEARISH"
        return {**base, "signal": "HOLD", "reason": f"No confluence | Trend: {trend_label} | RSI: {r:.0f}"}

    def check_and_trade(self, dry_run: bool = True, symbol: str = "BANKNIFTY", expiry: str = "") -> dict:
        if not self.risk.is_trading_allowed():
            return {"status": "HALTED", "reason": "Daily loss limit reached. Reset via Risk Engine tab."}

        candles = self.broker.get_data(symbol=symbol)
        result  = self.get_signal(candles)
        signal  = result.get("signal", "HOLD")

        if signal == "HOLD":
            logger.info(f"⚖️  HOLD — {result.get('reason', '')}")
            return result

        if signal == self._last_signal and self._position_open:
            logger.info(f"Duplicate signal '{signal}' — skipping to avoid double-entry.")
            return {**result, "status": "DUPLICATE_SKIPPED"}

        logger.info(f"{'🟢' if 'CALL' in signal else '🔴'} SIGNAL: {signal} | {result.get('reason', '')}")

        if dry_run:
            logger.info("DRY_RUN mode — no real order placed.")
            return {**result, "status": "DRY_RUN"}

        # Determine lot size dynamically per index
        qty_map = {"NIFTY": 25, "SENSEX": 10, "BANKNIFTY": 15}
        qty = qty_map.get(symbol.upper(), 15) * self.risk.position_size()

        order = self.broker.place_order(
            signal=signal,
            symbol=symbol,
            quantity=qty,
            spot_price=result.get("price", 0),
            expiry=expiry,
        )
        if order.get("status"):
            self._last_signal   = signal
            self._position_open = True
            return {**result, "order": order, "status": "EXECUTED"}
        else:
            logger.error(f"Order failed: {order.get('error')}")
            return {**result, "order": order, "status": "ORDER_FAILED",
                    "error": order.get("error")}


# ─────────────────────────────────────────────────────────────────────────────
#  IRON CONDOR STRATEGY  (BankNifty Weekly)
# ─────────────────────────────────────────────────────────────────────────────

class IronCondorStrategy:
    """
    Constructs and deploys a 4-leg BankNifty Iron Condor.
    Strike offsets use 1.2% of spot with 500-point wing width — identical to UI builder.
    """

    STD_DEV_MULTIPLE  = 1.2   # % offset from spot for short strikes
    WING_WIDTH_POINTS = 500   # distance from short to long strike

    def __init__(self, broker, risk: RiskManager = None):
        self.broker = broker
        self.risk   = risk or RiskManager()

    def compute_strikes(self, spot: float, underlying: str = "BANKNIFTY") -> dict:
        """
        Calculate all 4 option strikes.
        Uses get_atm_strike for correct rounding (100 pts for BANKNIFTY).
        """
        offset = spot * (self.STD_DEV_MULTIPLE / 100)
        sc = get_atm_strike(underlying, spot + offset)
        sp = get_atm_strike(underlying, spot - offset)
        return {
            "spot":        round(spot, 2),
            "short_call":  sc,
            "long_call":   sc + self.WING_WIDTH_POINTS,
            "short_put":   sp,
            "long_put":    sp - self.WING_WIDTH_POINTS,
        }

    def get_signal(self, spot: float, vix: float) -> dict:
        if not self.risk.check_vix(vix):
            return {
                "signal": "HOLD",
                "reason": f"VIX {vix:.1f} is above {self.risk.vix_threshold:.0f} — condor blocked.",
            }
        strikes = self.compute_strikes(spot)
        return {
            "signal":  "PLACE_IRON_CONDOR",
            "reason":  f"VIX {vix:.1f} is safe | Profit zone: {strikes['short_put']} → {strikes['short_call']}",
            "strikes": strikes,
            "lots":    self.risk.position_size(),
        }

    def check_and_trade(
        self, spot: float, vix: float, expiry: str, dry_run: bool = True
    ) -> dict:
        if not self.risk.is_trading_allowed():
            return {"status": "HALTED", "reason": "Risk limit reached."}

        result = self.get_signal(spot, vix)
        if result["signal"] == "HOLD":
            return {**result, "status": "BLOCKED_BY_VIX"}
        if dry_run:
            logger.info(f"DRY_RUN Iron Condor | Strikes: {result['strikes']}")
            return {**result, "status": "DRY_RUN"}

        strikes  = result["strikes"]
        quantity = result["lots"] * 15  # 1 lot = 15 units for BANKNIFTY

        order = self.broker.place_iron_condor(
            symbol            = "BANKNIFTY",
            expiry            = expiry,
            short_call_strike = strikes["short_call"],
            long_call_strike  = strikes["long_call"],
            short_put_strike  = strikes["short_put"],
            long_put_strike   = strikes["long_put"],
            quantity          = quantity,
        )
        return {
            **result,
            "order":  order,
            "status": "EXECUTED" if order["status"] else "FAILED",
        }


# ─────────────────────────────────────────────────────────────────────────────
#  MORNING BREAKOUT STRATEGY  (Nifty 50 / BankNifty)
# ─────────────────────────────────────────────────────────────────────────────

class MorningBreakoutStrategy:
    """
    Opening Range Breakout: uses the first 15-minute candle as the range.
    Enters on a close above/below the range with volume confirmation.
    Bug fix v3.1: resolved undefined 'orb_low' reference in original code.
    """

    def __init__(self, broker, risk: RiskManager = None):
        self.broker = broker
        self.risk   = risk or RiskManager()

    def get_signal(self, candles: list) -> dict:
        if not candles or len(candles) < 2:
            return {"signal": "HOLD", "reason": "Insufficient candles for ORB calculation."}

        df        = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        df['close'] = pd.to_numeric(df['close'], errors='coerce').fillna(0.0)
        df['vol']   = pd.to_numeric(df['vol'],   errors='coerce').fillna(0.0)

        # Opening Range: first candle of the session
        orb_h  = float(df.iloc[0]['high'])
        orb_l  = float(df.iloc[0]['low'])   # BUG FIX: was 'orb_low' (undefined) in v3.0
        price  = float(df.iloc[-1]['close'])
        avg_vol = df['vol'].mean()
        vol_spike = float(df.iloc[-1]['vol']) > (avg_vol * 1.5)

        base = {
            "orb_high":  orb_h,
            "orb_low":   orb_l,
            "price":     price,
            "vol_spike": vol_spike,
        }

        if price > orb_h and vol_spike:
            return {**base, "signal": "BUY_CALL",
                    "reason": f"Price {price:.0f} broke ORB high {orb_h:.0f} with volume surge"}
        if price < orb_l and vol_spike:
            return {**base, "signal": "BUY_PUT",
                    "reason": f"Price {price:.0f} broke ORB low {orb_l:.0f} with volume surge"}

        return {**base, "signal": "HOLD",
                "reason": f"Price {price:.0f} within ORB range {orb_l:.0f}–{orb_h:.0f}"}
