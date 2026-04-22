"""
QuantBengal Engine — main.py
GitHub Actions scheduler entry point.
Runs every 15 minutes during market hours (3:30–10:00 UTC = 9:00–15:30 IST)
"""

import logging
import json
import os
from datetime import datetime
import pytz

from broker_api import IndianBrokerAPI
from strategy import MomentumStrategy, IronCondorStrategy, MorningBreakoutStrategy, RiskManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')

# ─── CONFIG ────────────────────────────────────────────────────────────────

DRY_RUN        = os.environ.get("DRY_RUN", "true").lower() == "true"
ACTIVE_STRATEGY = os.environ.get("STRATEGY", "MOMENTUM")   # MOMENTUM | IRON_CONDOR | BREAKOUT
CAPITAL        = float(os.environ.get("CAPITAL", "200000"))
VIX_VALUE      = float(os.environ.get("VIX", "15.0"))      # Can be injected from a VIX fetch step

# Iron Condor specific
IC_EXPIRY      = os.environ.get("IC_EXPIRY", "23DEC")       # e.g. 23DEC for Dec weekly
IC_SPOT        = float(os.environ.get("BANKNIFTY_SPOT", "0"))


def is_market_hours() -> bool:
    now = datetime.now(IST)
    # Mon–Fri, 9:15 AM – 3:30 PM IST
    if now.weekday() > 4:
        return False
    start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    end   = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start <= now <= end


def run_bot():
    logger.info("=" * 60)
    logger.info(f"  QuantBengal Engine START | Strategy: {ACTIVE_STRATEGY}")
    logger.info(f"  DRY RUN: {DRY_RUN} | Capital: ₹{CAPITAL:,.0f}")
    logger.info("=" * 60)

    if not is_market_hours():
        logger.info("⏰ Outside market hours — engine idle.")
        return

    # Connect broker
    broker = IndianBrokerAPI()
    if not broker.connected:
        logger.error("❌ Broker connection failed. Aborting.")
        return

    # Init risk manager
    risk = RiskManager(capital=CAPITAL)

    # Check daily P&L before trading
    pnl = broker.get_pnl_summary()
    logger.info(f"📊 P&L | Realised: ₹{pnl['realised']:,.0f} | Unrealised: ₹{pnl['unrealised']:,.0f} | Total: ₹{pnl['total']:,.0f}")

    if not risk.check_daily_loss(pnl['total']):
        logger.error("🛑 Engine halted due to risk limits.")
        return

    # ── RUN SELECTED STRATEGY ─────────────────────────────────────────────
    if ACTIVE_STRATEGY == "MOMENTUM":
        strategy = MomentumStrategy(broker, risk)
        result   = strategy.check_and_trade(dry_run=DRY_RUN)

    elif ACTIVE_STRATEGY == "IRON_CONDOR":
        strategy = IronCondorStrategy(broker, risk)
        spot = IC_SPOT if IC_SPOT > 0 else broker.get_ltp("NSE", "BANKNIFTY-EQ", "99926009")
        result   = strategy.check_and_trade(
            spot=spot, vix=VIX_VALUE, expiry=IC_EXPIRY, dry_run=DRY_RUN
        )

    elif ACTIVE_STRATEGY == "BREAKOUT":
        strategy = MorningBreakoutStrategy(broker, risk)
        candles  = broker.get_data(symbol="NIFTY", interval="FIFTEEN_MINUTE")
        result   = strategy.get_signal(candles)

    else:
        logger.error(f"Unknown strategy: {ACTIVE_STRATEGY}")
        return

    # Log result (exclude df for clean JSON output)
    output = {k: v for k, v in result.items() if k != "df"}
    logger.info(f"📝 RESULT: {json.dumps(output, default=str, indent=2)}")

    # Final position summary
    positions = broker.get_positions()
    open_pos  = [p for p in positions if int(p.get("netqty", 0)) != 0]
    logger.info(f"📌 Open positions: {len(open_pos)}")
    for p in open_pos:
        pnl_val = _safe_float(p.get("unrealisedprofitandloss", 0))
        logger.info(f"   {p.get('tradingsymbol', '')} | Qty: {p.get('netqty')} | P&L: ₹{pnl_val:,.0f}")

    logger.info("=" * 60)
    logger.info("  QuantBengal Engine COMPLETE")
    logger.info("=" * 60)


def _safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    run_bot()
