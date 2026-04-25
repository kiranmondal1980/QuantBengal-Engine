"""
QuantBengal Engine — strategy.py  v5.0
Strategy suite: Momentum (EMA+RSI) + Iron Condor (BankNifty) + Morning Breakout
FIXES v5.0:
  - All float() casts replaced with null-safe _sf() helper
  - _build_df() uses pd.to_numeric(..., errors='coerce') — handles bad candle data
  - position_size_units() / position_size_lots() separated cleanly
  - IronCondorStrategy.compute_strikes() uses corrected 1.2% offset formula
"""

import pandas as pd
import logging
from datetime import datetime
import pytz
from ta.trend import EMAIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.momentum import RSIIndicator

logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')


def _sf(val, default: float = 0.0) -> float:
    """Safe float — never raises, returns default on any failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
#  RISK MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class RiskManager:
    """
    Centralised risk gate evaluated before every trade.
    All parameters match the QuantBengal Business Plan.
    """
    MAX_DAILY_LOSS_PCT = 2.0    # % of capital — halt all trading if exceeded
    MAX_POSITION_PCT   = 20.0   # Max % of capital per single spread
    MAX_OPEN_POSITIONS = 4      # Max concurrent live option legs
    VIX_THRESHOLD      = 20.0   # Pause all Iron Condors above this
    MARGIN_PER_LOT     = 80000  # BankNifty approx margin ₹80,000 / lot
    LOT_SIZE           = 15     # BankNifty lot size (units)

    def __init__(self, capital: float = 200000):
        self.capital     = max(capital, 1.0)   # avoid division by zero
        self.daily_loss  = 0.0
        self.trade_count = 0
        self.halted      = False

    def check_vix(self, vix: float) -> bool:
        if vix > self.VIX_THRESHOLD:
            logger.warning(f"VIX {vix:.1f} > {self.VIX_THRESHOLD} — Iron Condor PAUSED")
            return False
        return True

    def check_daily_loss(self, current_pnl: float) -> bool:
        loss_pct = abs(current_pnl) / self.capital * 100 if current_pnl < 0 else 0
        if loss_pct >= self.MAX_DAILY_LOSS_PCT:
            self.halted = True
            logger.error(f"DAILY LOSS LIMIT HIT: {loss_pct:.2f}% — ENGINE HALTED")
            return False
        return True

    def position_size_lots(self) -> int:
        """Number of lots within capital risk limit (min 1)."""
        max_capital = self.capital * (self.MAX_POSITION_PCT / 100)
        return max(1, int(max_capital / self.MARGIN_PER_LOT))

    def position_size_units(self) -> int:
        """Units = lots × lot_size."""
        return self.position_size_lots() * self.LOT_SIZE

    def is_trading_allowed(self) -> bool:
        return not self.halted


# ─────────────────────────────────────────────────────────────────────────────
#  MOMENTUM STRATEGY  (BankNifty / Nifty — 15-min EMA + RSI)
# ─────────────────────────────────────────────────────────────────────────────

class MomentumStrategy:
    """
    9/21 EMA crossover with RSI confirmation on 15-minute candles.
    Generates BUY_CALL / BUY_PUT signals for automated execution.
    """

    EMA_FAST   = 9
    EMA_SLOW   = 21
    RSI_PERIOD = 14
    RSI_BULL   = 55
    RSI_BEAR   = 45

    def __init__(self, broker, risk: RiskManager = None):
        self.broker         = broker
        self.risk           = risk or RiskManager()
        self._last_signal   = None
        self._position_open = False

    def _build_df(self, candles: list) -> pd.DataFrame:
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        for col in ['open', 'high', 'low', 'close', 'vol']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        cs = df['close']
        df['ema_9']  = EMAIndicator(close=cs, window=self.EMA_FAST).ema_indicator()
        df['ema_21'] = EMAIndicator(close=cs, window=self.EMA_SLOW).ema_indicator()
        df['rsi']    = RSIIndicator(close=cs, window=self.RSI_PERIOD).rsi()
        df['atr']    = AverageTrueRange(
            high=df['high'], low=df['low'], close=cs, window=14
        ).average_true_range()
        bb = BollingerBands(close=cs, window=20, window_dev=2)
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_mid']   = bb.bollinger_mavg()
        return df.dropna(subset=['ema_9', 'ema_21', 'rsi'])

    def get_signal(self, candles: list) -> dict:
        """Pure signal generator — no side effects, no orders."""
        if not candles or len(candles) < 30:
            return {"signal": "HOLD", "reason": "Insufficient candle data", "price": 0}

        df = self._build_df(candles)
        if len(df) < 2:
            return {"signal": "HOLD", "reason": "DataFrame too short after dropna", "price": 0}

        latest = df.iloc[-1]
        prev   = df.iloc[-2]

        price  = _sf(latest['close'])
        ema9   = _sf(latest['ema_9'])
        ema21  = _sf(latest['ema_21'])
        rsi    = _sf(latest['rsi'])
        atr    = _sf(latest['atr']) or price * 0.005
        prev9  = _sf(prev['ema_9'])
        prev21 = _sf(prev['ema_21'])

        sl_long   = round(price - 1.5 * atr, 2)
        tgt_long  = round(price + 2.0 * atr, 2)
        sl_short  = round(price + 1.5 * atr, 2)
        tgt_short = round(price - 2.0 * atr, 2)

        base = {
            "price": price, "ema9": round(ema9, 2), "ema21": round(ema21, 2),
            "rsi": round(rsi, 2), "atr": round(atr, 2), "df": df,
        }

        # Bullish crossover
        if prev9 <= prev21 and ema9 > ema21 and rsi > self.RSI_BULL:
            return {**base,
                    "signal": "BUY_CALL",
                    "stop_loss": sl_long, "target": tgt_long,
                    "reason": f"EMA9 ↑ EMA21 | RSI {rsi:.0f} > {self.RSI_BULL}",
                    "strength": "STRONG" if rsi > 65 else "MODERATE"}

        # Bearish crossover
        if prev9 >= prev21 and ema9 < ema21 and rsi < self.RSI_BEAR:
            return {**base,
                    "signal": "BUY_PUT",
                    "stop_loss": sl_short, "target": tgt_short,
                    "reason": f"EMA9 ↓ EMA21 | RSI {rsi:.0f} < {self.RSI_BEAR}",
                    "strength": "STRONG" if rsi < 35 else "MODERATE"}

        trend = "BULLISH" if ema9 > ema21 else "BEARISH"
        return {**base, "signal": "HOLD", "stop_loss": 0, "target": 0,
                "reason": f"No crossover | Trend: {trend} | RSI: {rsi:.0f}"}

    def check_and_trade(self, dry_run: bool = True) -> dict:
        """Full cycle: fetch candles → signal → risk gate → order."""
        if not self.risk.is_trading_allowed():
            return {"status": "HALTED", "reason": "Daily loss limit hit", "signal": "HOLD"}

        candles = self.broker.get_data(symbol="BANKNIFTY")
        result  = self.get_signal(candles)
        signal  = result.get("signal", "HOLD")

        if signal == "HOLD":
            logger.info(f"HOLD — {result.get('reason', '')}")
            return result

        # Duplicate signal guard
        if signal == self._last_signal and self._position_open:
            logger.info(f"Signal {signal} unchanged — position already open, skipping")
            return {**result, "status": "DUPLICATE_SKIPPED"}

        logger.info(f"SIGNAL: {signal} | {result.get('reason')}")
        logger.info(f"  Price: ₹{result['price']:,.0f} | SL: ₹{result.get('stop_loss',0):,.0f} | Tgt: ₹{result.get('target',0):,.0f}")

        if dry_run:
            logger.info("DRY RUN — order not placed")
            return {**result, "status": "DRY_RUN"}

        order = self.broker.place_order(
            signal=signal,
            quantity=self.risk.position_size_units()
        )
        self._last_signal   = signal
        self._position_open = order.get("status", False)
        return {**result, "order": order, "status": "EXECUTED"}


# ─────────────────────────────────────────────────────────────────────────────
#  IRON CONDOR STRATEGY  (BankNifty Weekly)
# ─────────────────────────────────────────────────────────────────────────────

class IronCondorStrategy:
    """
    BankNifty Weekly Iron Condor — harvests theta decay.
    Entry: Monday 10:00–10:15 AM IST (if VIX < threshold)
    Target exit: 50% of premium collected
    Stop loss:   150% of premium collected
    """

    STD_DEV_MULTIPLE   = 1.2    # OTM distance as % from spot
    WING_WIDTH_POINTS  = 500    # Long wing offset from short strike
    TARGET_PCT         = 0.50   # Exit at 50% profit
    STOP_LOSS_PCT      = 1.50   # Exit at 150% of premium (loss)

    def __init__(self, broker, risk: RiskManager = None):
        self.broker = broker
        self.risk   = risk or RiskManager()

    def _is_valid_entry_time(self) -> bool:
        now = datetime.now(IST)
        return (now.weekday() == 0          # Monday only
                and now.hour == 10
                and now.minute <= 15)

    def compute_strikes(self, spot: float) -> dict:
        """Compute all 4 Iron Condor strikes from spot price."""
        offset     = spot * (self.STD_DEV_MULTIPLE / 100)
        short_call = round((spot + offset) / 100) * 100
        short_put  = round((spot - offset) / 100) * 100
        return {
            "spot":       round(spot, 2),
            "short_call": short_call,
            "long_call":  short_call + self.WING_WIDTH_POINTS,
            "short_put":  short_put,
            "long_put":   short_put  - self.WING_WIDTH_POINTS,
        }

    def get_signal(self, spot: float, vix: float) -> dict:
        if not self.risk.check_vix(vix):
            return {"signal": "HOLD", "reason": f"VIX {vix:.1f} exceeds threshold"}
        strikes = self.compute_strikes(spot)
        return {
            "signal":  "PLACE_IRON_CONDOR",
            "reason":  f"VIX {vix:.1f} OK | Spot ₹{spot:,.0f}",
            "strikes": strikes,
            "lots":    self.risk.position_size_lots(),
        }

    def check_and_trade(self, spot: float, vix: float,
                        expiry: str, dry_run: bool = True) -> dict:
        if not self.risk.is_trading_allowed():
            return {"status": "HALTED", "signal": "HOLD"}

        result = self.get_signal(spot, vix)
        if result["signal"] == "HOLD":
            return result

        strikes = result["strikes"]
        logger.info(
            f"IRON CONDOR | SC:{strikes['short_call']} LC:{strikes['long_call']}"
            f" | SP:{strikes['short_put']} LP:{strikes['long_put']}"
        )

        if dry_run:
            logger.info("DRY RUN — condor not placed")
            return {**result, "status": "DRY_RUN"}

        order = self.broker.place_iron_condor(
            symbol="BANKNIFTY", expiry=expiry,
            short_call_strike=strikes["short_call"],
            long_call_strike=strikes["long_call"],
            short_put_strike=strikes["short_put"],
            long_put_strike=strikes["long_put"],
            quantity=result["lots"] * self.risk.LOT_SIZE,
        )
        return {**result, "order": order,
                "status": "EXECUTED" if order.get("status") else "FAILED"}


# ─────────────────────────────────────────────────────────────────────────────
#  MORNING BREAKOUT STRATEGY  (Nifty 50 — Opening Range Breakout)
# ─────────────────────────────────────────────────────────────────────────────

class MorningBreakoutStrategy:
    """
    Opening Range Breakout on Nifty 50.
    ORB = high/low of the first 9:15 candle.
    Entry: close above/below ORB with volume spike (1.5x average).
    """

    def __init__(self, broker, risk: RiskManager = None):
        self.broker = broker
        self.risk   = risk or RiskManager()

    def get_signal(self, candles: list) -> dict:
        if not candles or len(candles) < 2:
            return {"signal": "HOLD", "reason": "Insufficient data"}

        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['vol']   = pd.to_numeric(df['vol'],   errors='coerce')

        orb_high  = _sf(df.iloc[0]['high'])
        orb_low   = _sf(df.iloc[0]['low'])
        price     = _sf(df.iloc[-1]['close'])
        avg_vol   = float(df['vol'].mean())
        vol_spike = _sf(df.iloc[-1]['vol']) > (avg_vol * 1.5)

        base = {
            "orb_high":  orb_high,
            "orb_low":   orb_low,
            "price":     price,
            "vol_spike": vol_spike,
        }

        if price > orb_high and vol_spike:
            return {**base, "signal": "BUY_CALL",
                    "reason": f"ORB breakout ↑ {orb_high:,.0f}"}
        if price < orb_low and vol_spike:
            return {**base, "signal": "BUY_PUT",
                    "reason": f"ORB breakdown ↓ {orb_low:,.0f}"}

        return {**base, "signal": "HOLD",
                "reason": f"Inside ORB [{orb_low:,.0f} – {orb_high:,.0f}]"}
