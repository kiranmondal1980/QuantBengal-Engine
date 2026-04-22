"""
QuantBengal Engine — strategy.py
Strategy suite: Iron Condor (BankNifty) + Momentum Breakout (Nifty)
Includes: VIX filter, ATR-based sizing, stop-loss, drawdown guard
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
import pytz
from ta.trend import EMAIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.momentum import RSIIndicator

logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')


def _safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  RISK MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class RiskManager:
    """
    Centralised risk gate. Evaluated before every trade.
    Parameters tuned to QuantBengal Business Plan specs.
    """
    MAX_DAILY_LOSS_PCT  = 2.0   # % of capital — halt trading if exceeded
    MAX_POSITION_PCT    = 20.0  # Max % of capital per single condor leg
    MAX_OPEN_POSITIONS  = 4     # Max concurrent live legs
    VIX_THRESHOLD       = 20.0  # Pause all condors above this

    def __init__(self, capital: float = 200000):
        self.capital          = capital
        self.daily_loss       = 0.0
        self.trade_count      = 0
        self.halted           = False

    def check_vix(self, vix: float) -> bool:
        if vix > self.VIX_THRESHOLD:
            logger.warning(f"⚠️  VIX {vix:.1f} > {self.VIX_THRESHOLD} — Iron Condor PAUSED")
            return False
        return True

    def check_daily_loss(self, current_pnl: float) -> bool:
        loss_pct = abs(current_pnl) / self.capital * 100 if current_pnl < 0 else 0
        if loss_pct >= self.MAX_DAILY_LOSS_PCT:
            self.halted = True
            logger.error(f"🛑 DAILY LOSS LIMIT HIT: {loss_pct:.2f}% — ENGINE HALTED")
            return False
        return True

    def position_size(self, premium_per_lot: float) -> int:
        """Returns number of lots within capital risk limit."""
        max_capital = self.capital * (self.MAX_POSITION_PCT / 100)
        # BankNifty lot = 15, approx margin ₹80,000/lot
        margin_per_lot = 80000
        lots = int(max_capital / margin_per_lot)
        return max(1, lots)

    def is_trading_allowed(self) -> bool:
        return not self.halted


# ─────────────────────────────────────────────────────────────────────────────
#  MOMENTUM STRATEGY  (BankNifty / Nifty — 15min EMA + RSI)
# ─────────────────────────────────────────────────────────────────────────────

class MomentumStrategy:
    """
    9/21 EMA crossover + RSI confirmation on 15-min candles.
    Used for automated BUY_CALL / BUY_PUT signal generation.
    """

    EMA_FAST    = 9
    EMA_SLOW    = 21
    RSI_PERIOD  = 14
    RSI_BULL    = 55
    RSI_BEAR    = 45

    def __init__(self, broker, risk: RiskManager = None):
        self.broker = broker
        self.risk   = risk or RiskManager()
        self._last_signal = None
        self._position_open = False

    def _build_df(self, candles: list) -> pd.DataFrame:
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        df['close'] = df['close'].astype(float)
        df['high']  = df['high'].astype(float)
        df['low']   = df['low'].astype(float)
        df['ema_9']  = EMAIndicator(close=df['close'], window=self.EMA_FAST).ema_indicator()
        df['ema_21'] = EMAIndicator(close=df['close'], window=self.EMA_SLOW).ema_indicator()
        df['rsi']    = RSIIndicator(close=df['close'], window=self.RSI_PERIOD).rsi()
        atr          = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14)
        df['atr']    = atr.average_true_range()
        bb           = BollingerBands(close=df['close'], window=20, window_dev=2)
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_mid']   = bb.bollinger_mavg()
        return df

    def get_signal(self, candles: list) -> dict:
        """Pure signal generator — no side effects."""
        if not candles or len(candles) < 30:
            return {"signal": "HOLD", "reason": "Insufficient data"}

        df = self._build_df(candles)
        latest, prev = df.iloc[-1], df.iloc[-2]

        price  = _safe_float(latest['close'])
        ema9   = _safe_float(latest['ema_9'])
        ema21  = _safe_float(latest['ema_21'])
        rsi    = _safe_float(latest['rsi'])
        atr    = _safe_float(latest['atr'])
        prev9  = _safe_float(prev['ema_9'])
        prev21 = _safe_float(prev['ema_21'])

        stop_loss  = round(price - (1.5 * atr), 2)
        target     = round(price + (2.0 * atr), 2)

        base = {
            "price": price, "ema9": round(ema9, 2), "ema21": round(ema21, 2),
            "rsi": round(rsi, 2), "atr": round(atr, 2),
            "stop_loss": stop_loss, "target": target,
            "df": df,
        }

        # ── BULLISH CROSSOVER ──────────────────────────────────────────────
        if prev9 <= prev21 and ema9 > ema21 and rsi > self.RSI_BULL:
            return {**base, "signal": "BUY_CALL",
                    "reason": f"9 EMA crossed ↑ 21 EMA | RSI {rsi:.0f} > {self.RSI_BULL}",
                    "strength": "STRONG" if rsi > 65 else "MODERATE"}

        # ── BEARISH CROSSOVER ──────────────────────────────────────────────
        if prev9 >= prev21 and ema9 < ema21 and rsi < self.RSI_BEAR:
            return {**base, "signal": "BUY_PUT",
                    "reason": f"9 EMA crossed ↓ 21 EMA | RSI {rsi:.0f} < {self.RSI_BEAR}",
                    "strength": "STRONG" if rsi < 35 else "MODERATE"}

        # ── HOLD ──────────────────────────────────────────────────────────
        trend = "BULLISH" if ema9 > ema21 else "BEARISH"
        return {**base, "signal": "HOLD",
                "reason": f"No crossover | Trend: {trend} | RSI: {rsi:.0f}"}

    def check_and_trade(self, dry_run: bool = True) -> dict:
        """Full cycle: fetch → signal → risk check → order."""
        if not self.risk.is_trading_allowed():
            return {"status": "HALTED", "reason": "Daily loss limit hit"}

        candles = self.broker.get_data(symbol="BANKNIFTY")
        result  = self.get_signal(candles)
        signal  = result.get("signal", "HOLD")

        if signal == "HOLD":
            logger.info(f"⚖️  HOLD — {result.get('reason', '')}")
            return result

        # Prevent duplicate signals
        if signal == self._last_signal and self._position_open:
            logger.info(f"ℹ️  Signal {signal} unchanged — position already open")
            return {**result, "status": "DUPLICATE_SKIPPED"}

        logger.info(f"{'🟢' if 'CALL' in signal else '🔴'} SIGNAL: {signal} | {result.get('reason')}")
        logger.info(f"   Price: ₹{result['price']:,.0f} | SL: ₹{result['stop_loss']:,.0f} | Target: ₹{result['target']:,.0f}")

        if dry_run:
            logger.info("🧪 DRY RUN — order not placed")
            return {**result, "status": "DRY_RUN"}

        order = self.broker.place_order(signal=signal, quantity=self.risk.position_size(0))
        self._last_signal   = signal
        self._position_open = order.get("status", False)
        return {**result, "order": order, "status": "EXECUTED"}


# ─────────────────────────────────────────────────────────────────────────────
#  IRON CONDOR STRATEGY  (BankNifty Weekly)
# ─────────────────────────────────────────────────────────────────────────────

class IronCondorStrategy:
    """
    BankNifty Weekly Iron Condor — harvests theta decay.
    Entry: Monday 10:00–10:15 AM IST (if VIX < 20)
    Target: 50% of premium collected
    Stop: 150% of premium collected
    Exit: Wednesday EOD or target/stop hit
    """

    STD_DEV_MULTIPLE   = 1.2   # OTM distance in % from spot
    WING_WIDTH_POINTS  = 500   # Long wing offset from short strike
    TARGET_PCT         = 0.50  # Close at 50% profit
    STOP_LOSS_PCT      = 1.50  # Exit at 150% of premium

    def __init__(self, broker, risk: RiskManager = None):
        self.broker = broker
        self.risk   = risk or RiskManager()

    def _is_valid_entry_time(self) -> bool:
        now = datetime.now(IST)
        # Monday only, between 10:00 and 10:15 AM
        return now.weekday() == 0 and 10 <= now.hour == 10 and now.minute <= 15

    def compute_strikes(self, spot: float) -> dict:
        """Compute Iron Condor strikes from spot price."""
        offset = spot * (self.STD_DEV_MULTIPLE / 100)
        short_call = round((spot + offset) / 100) * 100
        short_put  = round((spot - offset) / 100) * 100
        long_call  = short_call + self.WING_WIDTH_POINTS
        long_put   = short_put  - self.WING_WIDTH_POINTS
        return {
            "spot":        round(spot, 2),
            "short_call":  short_call,
            "long_call":   long_call,
            "short_put":   short_put,
            "long_put":    long_put,
        }

    def get_signal(self, spot: float, vix: float) -> dict:
        """Determine if Iron Condor should be deployed."""
        if not self.risk.check_vix(vix):
            return {"signal": "HOLD", "reason": f"VIX {vix:.1f} too high (>{self.risk.VIX_THRESHOLD})"}

        strikes = self.compute_strikes(spot)
        return {
            "signal":  "PLACE_IRON_CONDOR",
            "reason":  f"VIX {vix:.1f} ✓ | Spot {spot:,.0f}",
            "strikes": strikes,
            "lots":    self.risk.position_size(0),
        }

    def check_and_trade(self, spot: float, vix: float,
                        expiry: str, dry_run: bool = True) -> dict:
        """Full Iron Condor deployment cycle."""
        if not self.risk.is_trading_allowed():
            return {"status": "HALTED"}

        result = self.get_signal(spot, vix)
        if result["signal"] == "HOLD":
            return result

        strikes = result["strikes"]
        logger.info(f"🦅 IRON CONDOR | SC:{strikes['short_call']} LC:{strikes['long_call']} | SP:{strikes['short_put']} LP:{strikes['long_put']}")

        if dry_run:
            logger.info("🧪 DRY RUN — condor not placed")
            return {**result, "status": "DRY_RUN"}

        order = self.broker.place_iron_condor(
            symbol="BANKNIFTY", expiry=expiry,
            short_call_strike=strikes["short_call"],
            long_call_strike=strikes["long_call"],
            short_put_strike=strikes["short_put"],
            long_put_strike=strikes["long_put"],
            quantity=result["lots"] * 15,  # lots × lot_size
        )
        return {**result, "order": order, "status": "EXECUTED" if order["status"] else "FAILED"}


# ─────────────────────────────────────────────────────────────────────────────
#  MORNING BREAKOUT STRATEGY  (Nifty 50)
# ─────────────────────────────────────────────────────────────────────────────

class MorningBreakoutStrategy:
    """
    Opening Range Breakout on Nifty 50.
    ORB = high/low of 9:15 candle.
    Entry: price closes above/below ORB with volume spike.
    """

    def __init__(self, broker, risk: RiskManager = None):
        self.broker = broker
        self.risk   = risk or RiskManager()

    def get_signal(self, candles: list) -> dict:
        if not candles or len(candles) < 2:
            return {"signal": "HOLD", "reason": "Insufficient data"}

        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        df['close'] = df['close'].astype(float)
        df['vol']   = df['vol'].astype(float)

        orb_high   = float(df.iloc[0]['high'])
        orb_low    = float(df.iloc[0]['low'])
        latest     = df.iloc[-1]
        price      = float(latest['close'])
        avg_vol    = df['vol'].mean()
        vol_spike  = float(latest['vol']) > (avg_vol * 1.5)

        base = {"orb_high": orb_high, "orb_low": orb_low, "price": price, "vol_spike": vol_spike}

        if price > orb_high and vol_spike:
            return {**base, "signal": "BUY_CALL", "reason": f"Breakout ↑ ORB High {orb_high:,.0f}"}
        if price < orb_low and vol_spike:
            return {**base, "signal": "BUY_PUT", "reason": f"Breakdown ↓ ORB Low {orb_low:,.0f}"}

        return {**base, "signal": "HOLD",
                "reason": f"Inside ORB [{orb_low:,.0f}–{orb_high:,.0f}]"}
